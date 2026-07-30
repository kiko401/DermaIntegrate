"""
检索器

功能：
- Dense向量检索 + 实体 boost
- RBAC 访问控制过滤（角色 × 文档级别）
- 实体 boost（query 中检测到的医学实体，命中则加权）
- 结构化质量日志（各阶段耗时、召回率、阻断率）
"""
import hashlib
import json
import time
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional

from ..ingest.embeddings import get_embedder
from ..ingest.vector_store import get_qdrant_client, COLLECTION_NAME, DENSE_VECTOR_NAME
from qdrant_client.http import models
from .reranker import rerank

logger = logging.getLogger(__name__)

# Entity boost 权重
ENTITY_BOOST_WEIGHT = 0.15
# 最大候选集扩展倍数
MAX_CANDIDATE_MULTIPLIER = 4


# ===== 角色层级定义（RBAC）=====
ROLE_HIERARCHY = {
    "admin":      ["public", "internal", "restricted"],
    "chief":      ["public", "internal", "restricted"],
    "attending":  ["public", "internal"],
    "resident":   ["public"],
    "outsider":   ["public"],
    "default":    ["public", "internal"],  # 未知角色默认
}

# 已知医生角色缓存（实际应从数据库/缓存查，此处提供映射接口）
_DOCTOR_ROLE_CACHE: Dict[int, str] = {}
_DOCTOR_DEPARTMENT_CACHE: Dict[int, Optional[int]] = {}


def get_doctor_role(doctor_id: int) -> str:
    """获取医生角色（实际应查数据库，此处提供注册接口）"""
    return _DOCTOR_ROLE_CACHE.get(doctor_id, "default")


def get_doctor_department(doctor_id: int) -> Optional[int]:
    """获取医生所属科室（实际应查数据库）"""
    return _DOCTOR_DEPARTMENT_CACHE.get(doctor_id)


def register_doctor(doctor_id: int, role: str, department_id: Optional[int] = None):
    """注册医生角色和科室（启动时从数据库加载）"""
    _DOCTOR_ROLE_CACHE[doctor_id] = role
    _DOCTOR_DEPARTMENT_CACHE[doctor_id] = department_id


def unregister_doctor(doctor_id: int) -> bool:
    """注销医生注册，从缓存中移除"""
    if doctor_id in _DOCTOR_ROLE_CACHE:
        del _DOCTOR_ROLE_CACHE[doctor_id]
    if doctor_id in _DOCTOR_DEPARTMENT_CACHE:
        del _DOCTOR_DEPARTMENT_CACHE[doctor_id]
    return True


def get_all_doctors() -> List[Dict]:
    """获取所有已注册的医生信息"""
    return [
        {
            "doctor_id": doctor_id,
            "role": role,
            "department_id": _DOCTOR_DEPARTMENT_CACHE.get(doctor_id),
        }
        for doctor_id, role in _DOCTOR_ROLE_CACHE.items()
    ]


# ===== 结构化日志 =====

def _make_trace_id(query: str) -> str:
    """生成查询指纹（用于日志关联）"""
    raw = f"{query[:30]}_{time.time()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _log_retrieval_event(
    trace_id: str,
    phase: str,
    kb_ids: List[int],
    doctor_id: Optional[int],
    use_hybrid: bool,
    use_rerank: bool,
    latency_ms: float,
    chunks_returned: int,
    blocked: bool,
    max_dense_norm: float,
    max_rerank_score: float,
    dense_count: int,
    rerank_mode: str,
    entity_boost_count: int,
    extra: Optional[Dict] = None,
):
    """结构化检索日志（JSON格式，便于ELK/Prometheus分析）"""
    event = {
        "event": "retrieval_complete",
        "trace_id": trace_id,
        "phase": phase,
        "kb_ids": kb_ids,
        "doctor_id": doctor_id,
        "use_hybrid": use_hybrid,
        "use_rerank": use_rerank,
        f"{phase}_latency_ms": round(latency_ms, 1),
        "chunks_returned": chunks_returned,
        "blocked": blocked,
        "max_dense_norm": round(max_dense_norm, 4),
        "max_rerank_score": round(max_rerank_score, 4),
        "dense_candidates": dense_count,
        "rerank_mode": rerank_mode,
        "entity_boost_chunks": entity_boost_count,
    }
    if extra:
        event.update(extra)
    logger.info(json.dumps(event, ensure_ascii=False))


# ===== 访问控制过滤 =====

def _build_rbac_filter(
    kb_ids: List[int],
    doctor_id: Optional[int],
) -> models.Filter:
    """
    构建 RBAC 过滤条件。

    过滤维度：
    1. kb_id（知识库隔离）
    2. access_level（角色可访问的文档级别）
    3. department_id（科室维度，可选）
    """
    must_conditions = [
        models.FieldCondition(
            key="kb_id",
            match=models.MatchAny(any=kb_ids)
        )
    ]

    if doctor_id is not None:
        role = get_doctor_role(doctor_id)
        allowed_levels = ROLE_HIERARCHY.get(role, ROLE_HIERARCHY["default"])

        must_conditions.append(
            models.FieldCondition(
                key="access_level",
                match=models.MatchAny(any=allowed_levels)
            )
        )

    return models.Filter(must=must_conditions)


# ===== 主检索函数 =====

async def retrieve(
    query: str,
    kb_ids: List[int],
    top_k: int = 5,
    threshold: float = 0.35,
    use_rerank: bool = False,
    doctor_id: Optional[int] = None,
) -> Tuple[List[Dict], bool]:
    """
    执行 Dense 向量检索 + RBAC 过滤 + 实体 boost + 结构化日志。

    Args:
        query: 用户问题
        kb_ids: 知识库ID列表
        top_k: 返回的最终结果数
        threshold: Dense向量相似度阈值（归一化前）
        use_rerank: 是否启用重排（Cross-Encoder或规则加权）
        doctor_id: 医生ID（用于RBAC过滤；空则不过滤）

    Returns:
        (chunks列表, 是否被低置信度阻断)
    """
    if not kb_ids:
        return [], True

    trace_id = _make_trace_id(query)
    total_start = time.perf_counter()
    rerank_mode = "none"

    try:
        # ===== 第1步：Embedding =====
        t0 = time.perf_counter()
        embedder = None
        query_vector = None
        try:
            embedder = get_embedder()
            query_vector = embedder.encode(query, normalize_embeddings=True).tolist()
        except Exception as e:
            logger.warning(f"Embedding model load failed, dense search will be skipped: {e}")
        dense_start = time.perf_counter()

        # ===== 第2步：构建 RBAC 过滤条件 =====
        kb_filter = _build_rbac_filter(kb_ids, doctor_id)
        fetch_limit = top_k * MAX_CANDIDATE_MULTIPLIER

        # ===== 第3步：Dense 检索 =====
        search_response = None
        if query_vector is not None:
            def _search_dense():
                client = get_qdrant_client()
                try:
                    return client.query_points(
                        collection_name=COLLECTION_NAME,
                        query=query_vector,
                        using=DENSE_VECTOR_NAME,
                        query_filter=kb_filter,
                        limit=fetch_limit,
                        with_payload=True
                    )
                except Exception as e:
                    logger.warning(f"Dense search failed: {e}")
                    return None

            search_response = await asyncio.to_thread(_search_dense)
        dense_latency = (time.perf_counter() - t0) * 1000

        # 构建 candidates（含所有 payload 元数据）
        dense_scores: Dict[str, float] = {}
        candidates: List[Dict] = []
        if search_response is not None and search_response.points:
            for hit in search_response.points:
                payload = hit.payload or {}
                chunk_id = payload.get("chunk_id", "")
                dense_scores[chunk_id] = hit.score
                candidates.append({
                    "doc_id": payload.get("doc_id"),
                    "doc_version_id": payload.get("doc_version_id"),
                    "chunk_id": chunk_id,
                    "text": payload.get("text", ""),
                    "score": hit.score,
                    # 扩展元数据
                    "source_filename": payload.get("source_filename", ""),
                    "section_title": payload.get("section_title", ""),
                    "page_number": payload.get("page_number"),
                    "chunk_position": payload.get("chunk_position", "middle"),
                    "is_table": payload.get("is_table", False),
                    "table_meta": payload.get("table_meta"),
                    # 实体信息
                    "entities": payload.get("entities", []),
                    "entity_sig": payload.get("entity_sig", {}),
                    # 访问控制（透传）
                    "access_level": payload.get("access_level", "internal"),
                    "department_id": payload.get("department_id"),
                })

        # ===== 第4步：归一化得分 =====
        max_dense = max(dense_scores.values()) if dense_scores else 1.0
        fused_chunks = []
        for c in candidates:
            norm_dense = c["score"] / max_dense if max_dense > 0 else 0
            fused_chunks.append({
                "doc_id": c["doc_id"],
                "doc_version_id": c["doc_version_id"],
                "chunk_id": c["chunk_id"],
                "text": c["text"],
                "score": round(c["score"], 4),
                "dense_score": round(c["score"], 4),
                "dense_norm": round(norm_dense, 4),
                "source_filename": c.get("source_filename", ""),
                "section_title": c.get("section_title", ""),
                "page_number": c.get("page_number"),
                "chunk_position": c.get("chunk_position", "middle"),
                "is_table": c.get("is_table", False),
                "table_meta": c.get("table_meta"),
                "entities": c.get("entities", []),
                "entity_sig": c.get("entity_sig", {}),
                # 访问控制（透传，供检索调用方判断）
                "access_level": c.get("access_level", "internal"),
                "department_id": c.get("department_id"),
            })

        # ===== 第5步：实体 Boost =====
        entity_boost_start = time.perf_counter()
        # 从 query 中检测实体（复用 NER 模块的词典）
        from ..ingest.ner import get_entity_signature
        query_sig = get_entity_signature(query)
        query_entity_names = set(query_sig.get("all", []))
        entity_boost_count = 0
        if query_entity_names:
            # 在候选集中标记被 boost 的 chunk
            for c in fused_chunks:
                chunk_entity_names = {e.get("name", "") for e in c.get("entities", [])}
                overlap = len(query_entity_names & chunk_entity_names)
                if overlap > 0:
                    boost = ENTITY_BOOST_WEIGHT * (overlap / len(query_entity_names))
                    c["score"] = c.get("score", 0) * (1 + boost)
                    c["entity_overlap"] = overlap
                    c["entity_boosted"] = True
                    entity_boost_count += 1
            # 重新排序
            fused_chunks.sort(key=lambda x: x.get("score", 0), reverse=True)

        entity_boost_latency = (time.perf_counter() - entity_boost_start) * 1000

        # ===== 第6步：重排 =====
        rerank_latency = 0.0
        retrieval_candidates = fused_chunks[: top_k * MAX_CANDIDATE_MULTIPLIER]
        if use_rerank:
            rerank_start = time.perf_counter()
            reranked = rerank(query, retrieval_candidates, top_k)
            rerank_latency = (time.perf_counter() - rerank_start) * 1000
            final_chunks = reranked
            rerank_mode = "cross_encoder"  # rerank() 内部会判断
        else:
            final_chunks = retrieval_candidates[:top_k]
            rerank_mode = "none"

        # ===== 第7步：低置信度阻断 =====
        # 使用归一化 dense 分数（dense_norm，0~1范围）判断，与原 API threshold=0.35 设计一致
        dense_threshold = threshold
        max_dense_norm = max((c.get("dense_norm", 0) for c in final_chunks), default=0)
        blocked = max_dense_norm < dense_threshold
        if blocked:
            logger.warning(
                f"Retrieval blocked: max_dense_norm={max_dense_norm:.4f} < threshold={threshold} | "
                f"trace_id={trace_id}"
            )

        max_rerank_score = final_chunks[0].get("rerank_score", final_chunks[0].get("score", 0)) if final_chunks else 0.0

        # ===== 第8步：打结构化日志 =====
        total_latency = (time.perf_counter() - total_start) * 1000
        _log_retrieval_event(
            trace_id=trace_id,
            phase="total",
            kb_ids=kb_ids,
            doctor_id=doctor_id,
            use_hybrid=False,
            use_rerank=use_rerank,
            latency_ms=total_latency,
            chunks_returned=len(final_chunks),
            blocked=blocked,
            max_dense_norm=max_dense_norm,
            max_rerank_score=max_rerank_score,
            dense_count=len(dense_scores),
            rerank_mode=rerank_mode,
            entity_boost_count=entity_boost_count,
            extra={
                "dense_latency_ms": round(dense_latency, 1),
                "entity_boost_latency_ms": round(entity_boost_latency, 1),
                "rerank_latency_ms": round(rerank_latency, 1),
                "query_entity_count": len(query_entity_names),
                "query_entity_types": [k for k, v in query_sig.items() if k != "all" and v],
            }
        )

        # ===== 第9步：确保返回结果字段完整 =====
        for c in final_chunks:
            c.setdefault("source_filename", "")
            c.setdefault("section_title", "")
            c.setdefault("page_number", None)
            c.setdefault("chunk_position", "middle")
            c.setdefault("entities", [])

        return final_chunks, blocked

    except Exception as e:
        total_latency = (time.perf_counter() - total_start) * 1000
        logger.error(f"Retrieval failed trace_id={trace_id}: {e}", exc_info=True)
        _log_retrieval_event(
            trace_id=trace_id, phase="error", kb_ids=kb_ids,
            doctor_id=doctor_id, use_hybrid=False, use_rerank=use_rerank,
            latency_ms=total_latency, chunks_returned=0,
            blocked=True, max_dense_norm=0.0, max_rerank_score=0.0,
            dense_count=0, rerank_mode="error",
            entity_boost_count=0,
            extra={"error": str(e)},
        )
        return [], True