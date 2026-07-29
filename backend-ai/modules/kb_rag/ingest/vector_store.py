import os
import logging
import asyncio
import hashlib
from typing import List, Dict, Any, Tuple, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


def _chunk_id_to_point_id(chunk_id: str) -> int:
    """将 chunk_id 映射为确定性点 ID（SHA256 前8字节转大端整数）"""
    return int.from_bytes(hashlib.sha256(chunk_id.encode()).digest()[:8], byteorder="big")


COLLECTION_NAME = "rag_documents"
DENSE_VECTOR_NAME = "dense"    # Dense embedding 向量名

# ========== Qdrant 客户端单例 ==========

def get_qdrant_client() -> QdrantClient:
    """获取 Qdrant 客户端单例（同步版，供内部及向后兼容用）"""
    if not hasattr(get_qdrant_client, "_instance"):
        from shared.config import QDRANT_HOST, QDRANT_PORT
        host = QDRANT_HOST if QDRANT_HOST else ("qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost")
        port = QDRANT_PORT
        get_qdrant_client._instance = QdrantClient(host=host, port=port)
        logger.info(f"QdrantClient initialized for {host}:{port}")
    return get_qdrant_client._instance


# ========== 同步版本（向后兼容） ==========

def init_qdrant_collection():
    """启动时初始化 Qdrant 集合（pure Dense 向量格式）"""
    client = get_qdrant_client()
    collections = client.get_collections().collections

    if not any(c.name == COLLECTION_NAME for c in collections):
        _create_dense_collection(client)
    else:
        # 已有 collection 时，检查是否配置了 named vectors
        try:
            coll_info = client.get_collection(COLLECTION_NAME)
            vectors_cfg = coll_info.config.params.vectors
            has_named_vectors = isinstance(vectors_cfg, dict) and DENSE_VECTOR_NAME in vectors_cfg
            if not has_named_vectors:
                logger.info(f"Collection needs migration to named dense format.")
                _create_dense_collection(client)
            else:
                logger.info(f"Collection already has dense vector config.")
        except Exception as e:
            logger.warning(f"Failed to check collection config: {e}")
        # 补充 doctor_id 索引（幂等）
        try:
            client.create_payload_index(COLLECTION_NAME, "doctor_id", models.PayloadSchemaType.INTEGER)
        except Exception:
            pass  # 索引已存在不报错


def _create_dense_collection(client):
    """创建纯 Dense 向量配置的 collection"""
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            DENSE_VECTOR_NAME: {
                "size": 512,
                "distance": models.Distance.COSINE,
            }
        },
    )
    client.create_payload_index(COLLECTION_NAME, "kb_id", models.PayloadSchemaType.INTEGER)
    client.create_payload_index(COLLECTION_NAME, "doc_id", models.PayloadSchemaType.INTEGER)
    client.create_payload_index(COLLECTION_NAME, "chunk_id", models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(COLLECTION_NAME, "doctor_id", models.PayloadSchemaType.INTEGER)
    logger.info(f"Qdrant collection '{COLLECTION_NAME}' created with pure Dense vectors.")


def upsert_vectors(
    vectors: List[List[float]],
    payloads: List[Dict[str, Any]],
):
    """写入 Dense 向量。同步版本。"""
    _upsert_vectors_impl(vectors, payloads)


def delete_document_index(doc_id: int):
    """删除指定 doc_id 的所有向量。同步版本。"""
    _delete_document_index_impl(doc_id)


def delete_kb_index(kb_id: int):
    """删除指定 kb_id 下的所有向量。同步版本。"""
    _delete_kb_index_impl(kb_id)


def clone_kb_index(source_kb_id: int, target_kb_id: int) -> dict:
    """将 source_kb_id 下的所有向量复制到 target_kb_id。同步版本。"""
    return _clone_kb_index_impl(source_kb_id, target_kb_id)


# ========== 内部实现（同步，供 to_thread 包装用） ==========

def _upsert_vectors_impl(
    vectors: List[List[float]],
    payloads: List[Dict[str, Any]],
):
    """写入 Dense 向量内部实现"""
    client = get_qdrant_client()
    points = []

    for v, p in zip(vectors, payloads):
        point_dict: Dict[str, Any] = {
            "id": _chunk_id_to_point_id(p["chunk_id"]),
            "vector": {DENSE_VECTOR_NAME: v},
            "payload": p,
        }
        points.append(models.PointStruct(**point_dict))
    client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info(f"Upserted {len(points)} dense vectors to Qdrant.")


def _delete_document_index_impl(doc_id: int):
    """删除指定 doc_id 的所有向量"""
    client = get_qdrant_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
            )
        )
    )
    logger.info(f"Deleted vectors for doc_id={doc_id}.")


def _delete_kb_index_impl(kb_id: int):
    """删除指定 kb_id 下的所有向量"""
    client = get_qdrant_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id))]
            )
        )
    )
    logger.info(f"Deleted vectors for kb_id={kb_id}.")


def _clone_kb_index_impl(
    source_kb_id: int,
    target_kb_id: int,
    document_mappings: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """
    将 source_kb_id 下的向量复制到 target_kb_id。

    Args:
        source_kb_id: 源知识库 ID
        target_kb_id: 目标知识库 ID
        document_mappings: 可选，doc_id 映射列表，每项包含 source_doc_id, target_doc_id, version_id_map
    """
    client = get_qdrant_client()

    # 构建 source_doc_id -> (target_doc_id, version_id_map) 的查询映射
    doc_mapping: Dict[int, Tuple[int, Dict[int, int]]] = {}
    if document_mappings:
        for m in document_mappings:
            doc_mapping[m["source_doc_id"]] = (m["target_doc_id"], m.get("version_id_map", {}))

    # 先扫描源 KB（幂等：源无数据时直接返回，不删目标）
    kb_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="kb_id",
                match=models.MatchAny(any=[source_kb_id])
            )
        ]
    )

    all_points = []
    offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=kb_filter,
            limit=500,
            offset=offset,
            with_vectors=True,
        )
        all_points.extend(points)
        if next_offset is None:
            break
        offset = next_offset

    if not all_points:
        logger.info(f"Clone KB index: source kb_id={source_kb_id} has no points.")
        return {"cloned_chunk_count": 0, "cloned_doc_ids": []}

    target_points = []
    cloned_doc_ids = set()

    for pt in all_points:
        payload = dict(pt.payload or {})
        src_doc_id = payload.get("doc_id")
        src_doc_version_id = payload.get("doc_version_id", 0)

        # 如果指定了映射，只克隆映射中的 doc
        if doc_mapping:
            if src_doc_id not in doc_mapping:
                continue
            tgt_doc_id, version_map = doc_mapping[src_doc_id]
            payload["doc_id"] = tgt_doc_id
            payload["doc_version_id"] = version_map.get(src_doc_version_id, src_doc_version_id)

        payload["kb_id"] = target_kb_id

        new_chunk_id = payload.get("chunk_id", "")
        point_id = _chunk_id_to_point_id(new_chunk_id)

        # 提取 dense 向量（支持无名 plain list 或 named vector）
        existing_vec = pt.vector if pt.vector else []
        if isinstance(existing_vec, (list, tuple)):
            dense_vec = list(existing_vec)
        elif isinstance(existing_vec, dict) and DENSE_VECTOR_NAME in existing_vec:
            dense_vec = existing_vec[DENSE_VECTOR_NAME]
        else:
            dense_vec = list(existing_vec) if existing_vec else []

        named_vector: Dict[str, Any] = {DENSE_VECTOR_NAME: dense_vec}

        target_points.append(models.PointStruct(
            id=point_id,
            vector=named_vector,
            payload=payload,
        ))
    client.upsert(collection_name=COLLECTION_NAME, points=target_points)

    logger.info(
    f"Clone KB index done: source={source_kb_id} -> target={target_kb_id}, "
    f"chunks={len(target_points)}, docs={list(cloned_doc_ids)}"
    )
    return {
    "cloned_chunk_count": len(target_points),
    "cloned_doc_ids": list(cloned_doc_ids),
    }


# ========== Async 版本（推荐在 async 上下文中使用） ==========

async def init_qdrant_collection_async():
    """启动时初始化 Qdrant 集合（混合向量集合）- Async 版本"""
    await asyncio.to_thread(init_qdrant_collection)


async def upsert_vectors_async(
    vectors: List[List[float]],
    payloads: List[Dict[str, Any]],
):
    """写入 Dense 向量。Async 版本。"""
    await asyncio.to_thread(_upsert_vectors_impl, vectors, payloads)


async def delete_document_index_async(doc_id: int):
    """删除指定 doc_id 的所有向量。Async 版本。"""
    await asyncio.to_thread(_delete_document_index_impl, doc_id)


async def delete_kb_index_async(kb_id: int):
    """删除指定 kb_id 下的所有向量。Async 版本。"""
    await asyncio.to_thread(_delete_kb_index_impl, kb_id)


async def clone_kb_index_async(
    source_kb_id: int,
    target_kb_id: int,
    document_mappings: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """将 source_kb_id 下的向量复制到 target_kb_id。Async 版本。"""
    return await asyncio.to_thread(
        _clone_kb_index_impl, source_kb_id, target_kb_id, document_mappings
    )


async def vector_optimize_async(
    kb_id: int,
    remove_duplicates: bool = False,
    rebuild_bm25_idf: bool = False,
    compact_collection: bool = False,
) -> dict:
    """
    对指定 kb_id 执行向量优化。

    Args:
        kb_id: 知识库 ID
        remove_duplicates: 是否删除 text 完全重复的 chunk（保留 doc_version_id 最新）
        rebuild_bm25_idf: 是否重新计算 BM25 IDF 并持久化
        compact_collection: 是否触发 Qdrant 后台索引整理

    Returns:
        优化报告 dict
    """
    return await asyncio.to_thread(
        _vector_optimize_impl,
        kb_id, remove_duplicates, rebuild_bm25_idf, compact_collection
    )


def _vector_optimize_impl(
    kb_id: int,
    remove_duplicates: bool = False,
    rebuild_bm25_idf: bool = False,
    compact_collection: bool = False,
) -> dict:
    """向量优化同步实现"""
    client = get_qdrant_client()

    # ---- 1. 扫描该 kb_id 下所有 chunk ----
    kb_filter = models.Filter(
        must=[models.FieldCondition(key="kb_id", match=models.MatchValue(value=kb_id))]
    )

    all_points = []
    offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=kb_filter,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        all_points.extend(points)
        if next_offset is None:
            break
        offset = next_offset

    total_chunks = len(all_points)
    removed_duplicates = 0

    # ---- 2. 去重：按 text 分组，保留 doc_version_id 最大的 ----
    if remove_duplicates and total_chunks > 0:
        # {text -> [(point_id, doc_version_id)]}
        text_groups: Dict[str, List[Tuple[int, int]]] = {}
        for pt in all_points:
            payload = pt.payload or {}
            text = payload.get("text", "")
            doc_version_id = payload.get("doc_version_id", 0)
            chunk_id = payload.get("chunk_id", "")
            point_id = _chunk_id_to_point_id(chunk_id)
            if text not in text_groups:
                text_groups[text] = []
            text_groups[text].append((point_id, doc_version_id))

        # 对每组：按 doc_version_id 降序，删除除第一个外的所有点
        duplicate_chunks = sum(len(v) - 1 for v in text_groups.values() if len(v) > 1)
        ids_to_delete = []
        for group in text_groups.values():
            if len(group) > 1:
                # 按 doc_version_id 降序排列，保留第一个，其余删除
                sorted_group = sorted(group, key=lambda x: x[1], reverse=True)
                for point_id, _ in sorted_group[1:]:
                    ids_to_delete.append(point_id)
                    removed_duplicates += 1

        if ids_to_delete:
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=models.PointIdsList(points=ids_to_delete),
            )
            logger.info(f"Removed {removed_duplicates} duplicate chunks from kb_id={kb_id}")
    else:
        duplicate_chunks = 0

    # ---- 3. 重建 BM25 IDF ----
    # BM25 已在纯 Dense 架构下废弃，该参数保留但无实际效果
    idf_terms_updated = 0
    if rebuild_bm25_idf:
        logger.info("rebuild_bm25_idf is deprecated in pure Dense architecture, skipping.")

    # ---- 4. 触发 Qdrant 索引整理 ----
    optimizer_applied = False
    if compact_collection:
        try:
            client.update_collection(
                collection_name=COLLECTION_NAME,
                optimizer_config=models.OptimizersConfig(
                    indexing_threshold=512,
                    memmap_threshold=512,
                ),
            )
            optimizer_applied = True
            logger.info(f"Qdrant optimizer config updated for collection '{COLLECTION_NAME}'")
        except Exception as e:
            logger.warning(f"Failed to apply Qdrant optimizer: {e}")

    return {
        "kb_id": kb_id,
        "total_chunks": total_chunks,
        "duplicate_chunks": duplicate_chunks,
        "removed_duplicates": removed_duplicates,
        "idf_terms_updated": idf_terms_updated,
        "optimizer_applied": optimizer_applied,
    }
