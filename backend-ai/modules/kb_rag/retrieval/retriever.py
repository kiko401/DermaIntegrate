"""
混合检索器

功能：
- Dense向量检索 + BM25关键词检索 + RRF融合
- RBAC 访问控制过滤（角色 × 科室 × 文档级别）
- 实体 boost（query 中检测到的医学实体，命中则加权）
- 结构化质量日志（各阶段耗时、召回率、阻断率）

RRF (Reciprocal Rank Fusion):
    score = Σ 1 / (k + rank_i)
    k = 60 (默认)
"""
import os
import re
import math
import json
import time
import logging
import asyncio
import hashlib
import uuid
from typing import List, Dict, Any, Tuple, Optional
from collections import Counter

from ..ingest.embeddings import get_embedder
from ..ingest.vector_store import get_qdrant_client, COLLECTION_NAME, DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME
from ..ingest.bm25 import get_bm25_vectorizer, fit_bm25_on_collection, generate_sparse_vector
from qdrant_client.http import models
from qdrant_client.http.models import SparseVector as QdrantSparseVector
from shared.constants import BM25_K1, BM25_B, AVG_DOC_LEN

from .reranker import rerank

logger = logging.getLogger(__name__)

# RRF 融合参数
RRF_K = 5
# Entity boost 权重
ENTITY_BOOST_WEIGHT = 0.15
# 最大候选集扩展倍数
MAX_CANDIDATE_MULTIPLIER = 4

# BM25Vectorizer 全局初始拟合标志（防止重复拟合）
_bm25_fitted = False

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
    bm25_count: int,
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
        "bm25_candidates": bm25_count,
        "rerank_mode": rerank_mode,
        "entity_boost_chunks": entity_boost_count,
    }
    if extra:
        event.update(extra)
    logger.info(json.dumps(event, ensure_ascii=False))


# ===== Tokenizer & BM25 Scorer =====

def _tokenize(text: str) -> List[str]:
    from ..utils import tokenize as _shared_tokenize
    return _shared_tokenize(text)


def _compute_bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    idf: Dict[str, float],
    avg_doc_len: float
) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    doc_len = len(doc_tokens)
    term_freq = Counter(doc_tokens)
    score = 0.0
    for token in query_tokens:
        if token not in term_freq:
            continue
        tf = term_freq[token]
        idf_val = idf.get(token, 0.0)
        score += idf_val * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / avg_doc_len))
    return score


class BM25Scorer:
    def __init__(self, idf: Dict[str, float], avg_doc_len: float = AVG_DOC_LEN):
        self.idf = idf
        self.avg_doc_len = avg_doc_len

    def score(self, query: str, doc_text: str) -> float:
        query_tokens = _tokenize(query)
        doc_tokens = _tokenize(doc_text)
        return _compute_bm25_score(query_tokens, doc_tokens, self.idf, self.avg_doc_len)


# ===== IDF & BM25 全局状态 =====

_BM25_IDF_CACHE: Dict[str, Dict[str, float]] = {}
_BM25_IDF_PATH: str = os.path.join(os.path.dirname(__file__), "..", "assets", "bm25_idf.json")


def _load_bm25_idf() -> Dict[str, float]:
    global _BM25_IDF_CACHE
    path = _BM25_IDF_PATH
    if not os.path.exists(path):
        logger.warning(f"BM25 IDF file not found at {path}.")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _BM25_IDF_CACHE = data
        logger.info(f"Loaded BM25 IDF from {path}: {len(data)} terms.")
        return data
    except Exception as e:
        logger.warning(f"Failed to load BM25 IDF: {e}")
        return {}


def _get_global_idf() -> Dict[str, float]:
    if not _BM25_IDF_CACHE:
        return _load_bm25_idf()
    return _BM25_IDF_CACHE


def _compute_idf_from_chunks(texts: List[str]) -> Dict[str, float]:
    doc_count = len(texts)
    token_to_docs = Counter()
    for text in texts:
        tokens = set(_tokenize(text))
        for t in tokens:
            token_to_docs[t] += 1
    idf = {}
    for token, df in token_to_docs.items():
        idf[token] = math.log((doc_count - df + 0.5) / (df + 0.5) + 1)
        idf[token] = max(idf[token], 0.0)
    return idf


def _load_all_chunk_texts() -> List[str]:
    try:
        client = get_qdrant_client()
        all_texts = []
        offset = None
        while True:
            pts, next_offset = client.scroll(
                collection_name=COLLECTION_NAME, limit=500, offset=offset,
                with_payload=True, with_vectors=False,
            )
            for pt in pts:
                text = pt.payload.get("text", "") if pt.payload else ""
                if text:
                    all_texts.append(text)
            if next_offset is None:
                break
            offset = next_offset
        return all_texts
    except Exception as e:
        logger.warning(f"Failed to load chunk texts from Qdrant for BM25 fitting: {e}")
        return []


def fit_bm25_on_qdrant_chunks() -> bool:
    global _bm25_fitted
    if _bm25_fitted:
        return True
    texts = _load_all_chunk_texts()
    if not texts:
        logger.warning("No texts found in Qdrant for BM25 fitting.")
        return False
    try:
        fit_bm25_on_collection(COLLECTION_NAME, texts)
        _bm25_fitted = True
        logger.info(f"BM25 fitted on {len(texts)} chunks from Qdrant.")
        return True
    except Exception as e:
        logger.error(f"BM25 fitting failed: {e}")
        return False


# ===== RRF =====

def _rrf_fuse(
    dense_scores: Dict[str, float],
    bm25_scores: Dict[str, float],
    k: int = RRF_K
) -> List[Tuple[str, float]]:
    all_ids = set(dense_scores.keys()) | set(bm25_scores.keys())
    dense_sorted = sorted(dense_scores.items(), key=lambda x: x[1], reverse=True)
    bm25_sorted = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
    dense_rank = {cid: rank for rank, (cid, _) in enumerate(dense_sorted)}
    bm25_rank = {cid: rank for rank, (cid, _) in enumerate(bm25_sorted)}
    fused = {}
    for cid in all_ids:
        d_rank = dense_rank.get(cid, len(dense_sorted))
        b_rank = bm25_rank.get(cid, len(bm25_sorted))
        score = 1.0 / (k + d_rank) + 1.0 / (k + b_rank)
        fused[cid] = score
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


# ===== 实体 Boost =====

def _apply_entity_boost(
    chunks: List[Dict],
    query_entity_names: set[str],
) -> List[Dict]:
    """
    对检索结果做实体 boost。

    如果 query 中检测到了医学实体，而 chunk 的 entities 字段也包含这些实体，
    则对该 chunk 做分数加权（ ENTITY_BOOST_WEIGHT ）。
    """
    if not query_entity_names or not chunks:
        return chunks

    boosted = 0
    for chunk in chunks:
        chunk_entity_names = {
            e.get("name", "") for e in chunk.get("entities", [])
        }
        overlap = len(query_entity_names & chunk_entity_names)
        if overlap > 0:
            boost = ENTITY_BOOST_WEIGHT * (overlap / len(query_entity_names))
            chunk["score"] = chunk.get("score", 0) * (1 + boost)
            chunk["entity_overlap"] = overlap
            chunk["entity_boosted"] = True
            boosted += 1

    chunks.sort(key=lambda x: x.get("score", 0), reverse=True)
    return chunks


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

        # 科室过滤：只看不限科室 或 本科室的文档
        dept_id = get_doctor_department(doctor_id)
        if dept_id is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="department_id",
                    match=models.MatchAny(any=[dept_id, None])
                )
            )

    return models.Filter(must=must_conditions)


# ===== 主检索函数 =====

async def retrieve(
    query: str,
    kb_ids: List[int],
    top_k: int = 5,
    threshold: float = 0.35,
    use_hybrid: bool = False,  # BM25混合检索在当前知识库上效果差，暂用纯Dense
    use_rerank: bool = False,
    doctor_id: Optional[int] = None,
) -> Tuple[List[Dict], bool]:
    """
    执行混合检索 + RBAC 过滤 + 实体 boost + 结构化日志。

    Args:
        query: 用户问题
        kb_ids: 知识库ID列表
        top_k: 返回的最终结果数
        threshold: Dense向量相似度阈值
        use_hybrid: 是否启用混合检索（False则仅用Dense）
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

        # ===== 第4步：BM25 Sparse 检索 =====
        bm25_start = time.perf_counter()
        bm25_scores: Dict[str, float] = {}
        if use_hybrid:
            sparse_indices, sparse_values = generate_sparse_vector(query, COLLECTION_NAME)
            if sparse_indices:
                def _search_sparse():
                    try:
                        client = get_qdrant_client()
                        return client.query_points(
                            collection_name=COLLECTION_NAME,
                            query=QdrantSparseVector(indices=sparse_indices, values=sparse_values),
                            using=SPARSE_VECTOR_NAME,
                            query_filter=kb_filter,
                            limit=fetch_limit,
                            with_payload=True,
                        )
                    except Exception as e:
                        logger.warning(f"Sparse search failed: {e}")
                        return None

                sparse_resp = await asyncio.to_thread(_search_sparse)
                sparse_hits: List[Dict[str, Any]] = []
                if sparse_resp and sparse_resp.points:
                    for hit in sparse_resp.points:
                        p = hit.payload or {}
                        cid = p.get("chunk_id", "")
                        bm25_scores[cid] = hit.score
                        sparse_hits.append({
                            "doc_id": p.get("doc_id"),
                            "doc_version_id": p.get("doc_version_id"),
                            "chunk_id": cid,
                            "text": p.get("text", ""),
                            "score": hit.score,
                            "source_filename": p.get("source_filename", ""),
                            "section_title": p.get("section_title", ""),
                            "page_number": p.get("page_number"),
                            "chunk_position": p.get("chunk_position", "middle"),
                            "is_table": p.get("is_table", False),
                            "table_meta": p.get("table_meta"),
                            "entities": p.get("entities", []),
                            "entity_sig": p.get("entity_sig", {}),
                            "access_level": p.get("access_level", "internal"),
                            "department_id": p.get("department_id"),
                        })
                    logger.info(f"Sparse search: {len(sparse_resp.points)} hits.")
                    # 当 dense 无结果时，用 sparse_hits 补充 candidates
                    if not candidates and sparse_hits:
                        candidates.extend(sparse_hits)

        bm25_latency = (time.perf_counter() - bm25_start) * 1000

        # 兜底 in-memory BM25
        if not bm25_scores:
            idf = _get_global_idf()
            if idf:
                scorer = BM25Scorer(idf)
                for c in candidates:
                    bm25_s = scorer.score(query, c["text"])
                    bm25_scores[c["chunk_id"]] = bm25_s
            else:
                query_tokens = set(_tokenize(query))
                for c in candidates:
                    doc_tokens = set(_tokenize(c["text"]))
                    bm25_scores[c["chunk_id"]] = float(len(query_tokens & doc_tokens))

        # ===== 第5步：RRF 融合 =====
        rrf_start = time.perf_counter()
        max_dense = max(dense_scores.values()) if dense_scores else 1.0

        if use_hybrid and bm25_scores:
            fused_order = _rrf_fuse(dense_scores, bm25_scores)
            chunk_id_to_data = {c["chunk_id"]: c for c in candidates}
            fused_chunks = []
            for cid, fused_score in fused_order:
                # 如果 cid 不在 candidates 中（只有 sparse 结果），需要跳过或使用默认值
                if cid not in chunk_id_to_data:
                    logger.warning(f"Chunk ID {cid} found in BM25 scores but not in candidates, skipping.")
                    continue
                c = chunk_id_to_data[cid]
                norm_dense = c["score"] / max_dense if max_dense > 0 else 0
                fused_chunks.append({
                    "doc_id": c["doc_id"],
                    "doc_version_id": c["doc_version_id"],
                    "chunk_id": c["chunk_id"],
                    "text": c["text"],
                    "score": round(fused_score, 6),
                    "dense_score": round(c["score"], 4),
                    "bm25_score": round(bm25_scores.get(cid, 0), 4),
                    "dense_norm": round(norm_dense, 4),
                    "source_filename": c.get("source_filename", ""),
                    "section_title": c.get("section_title", ""),
                    "page_number": c.get("page_number"),
                    "chunk_position": c.get("chunk_position", "middle"),
                    "is_table": c.get("is_table", False),
                    "table_meta": c.get("table_meta"),
                    "entities": c.get("entities", []),
                    "entity_sig": c.get("entity_sig", {}),
                })
        else:
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
                    "bm25_score": 0.0,
                    "dense_norm": round(norm_dense, 4),
                    "source_filename": c.get("source_filename", ""),
                    "section_title": c.get("section_title", ""),
                    "page_number": c.get("page_number"),
                    "chunk_position": c.get("chunk_position", "middle"),
                    "is_table": c.get("is_table", False),
                    "table_meta": c.get("table_meta"),
                    "entities": c.get("entities", []),
                    "entity_sig": c.get("entity_sig", {}),
                })

        rrf_latency = (time.perf_counter() - rrf_start) * 1000

        # ===== 第6步：实体 Boost =====
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

        # ===== 第7步：重排 =====
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

        # ===== 第8步：低置信度阻断 =====
        # 使用 RRF 融合分数（final_chunks 的排序依据）判断，而非单独的 dense_norm
        # RRF 分数量级约 0.01~0.1，原 API threshold=0.35 基于 dense_norm(0~1) 设计
        # 换算：RRF_threshold ≈ dense_threshold / 100，保证 RRF 在合理范围内通过
        rrf_threshold = threshold / 100.0
        max_rrf_score = max((c.get("score", 0) for c in final_chunks), default=0)
        blocked = max_rrf_score < rrf_threshold
        if blocked:
            logger.warning(
                f"Retrieval blocked: max_rrf_score={max_rrf_score:.4f} < threshold={threshold} | "
                f"trace_id={trace_id}"
            )

        max_rerank_score = final_chunks[0].get("rerank_score", final_chunks[0].get("score", 0)) if final_chunks else 0.0

        # ===== 第9步：打结构化日志 =====
        total_latency = (time.perf_counter() - total_start) * 1000
        _log_retrieval_event(
            trace_id=trace_id,
            phase="total",
            kb_ids=kb_ids,
            doctor_id=doctor_id,
            use_hybrid=use_hybrid,
            use_rerank=use_rerank,
            latency_ms=total_latency,
            chunks_returned=len(final_chunks),
            blocked=blocked,
            max_dense_norm=max_rrf_score,
            max_rerank_score=max_rerank_score,
            dense_count=len(dense_scores),
            bm25_count=len(bm25_scores),
            rerank_mode=rerank_mode,
            entity_boost_count=entity_boost_count,
            extra={
                "dense_latency_ms": round(dense_latency, 1),
                "bm25_latency_ms": round(bm25_latency, 1),
                "rrf_latency_ms": round(rrf_latency, 1),
                "entity_boost_latency_ms": round(entity_boost_latency, 1),
                "rerank_latency_ms": round(rerank_latency, 1),
                "query_entity_count": len(query_entity_names),
                "query_entity_types": [k for k, v in query_sig.items() if k != "all" and v],
            }
        )

        # ===== 第10步：确保返回结果字段完整 =====
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
            doctor_id=doctor_id, use_hybrid=use_hybrid, use_rerank=use_rerank,
            latency_ms=total_latency, chunks_returned=0,
            blocked=True, max_dense_norm=0.0, max_rerank_score=0.0,
            dense_count=0, bm25_count=0, rerank_mode="error",
            entity_boost_count=0,
            extra={"error": str(e)},
        )
        return [], True
