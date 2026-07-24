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
SPARSE_VECTOR_NAME = "bm25"    # BM25 sparse 向量名

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
    """启动时初始化 Qdrant 集合（混合向量集合）"""
    client = get_qdrant_client()
    collections = client.get_collections().collections

    if not any(c.name == COLLECTION_NAME for c in collections):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(size=512, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(),
            }
        )
        client.create_payload_index(COLLECTION_NAME, "kb_id", models.PayloadSchemaType.INTEGER)
        client.create_payload_index(COLLECTION_NAME, "doc_id", models.PayloadSchemaType.INTEGER)
        client.create_payload_index(COLLECTION_NAME, "chunk_id", models.PayloadSchemaType.KEYWORD)
        logger.info(f"Qdrant collection '{COLLECTION_NAME}' created with hybrid vectors (dense + bm25 sparse).")
    else:
        logger.info(f"Qdrant collection '{COLLECTION_NAME}' already exists.")


def upsert_vectors(
    vectors: List[List[float]],
    payloads: List[Dict[str, Any]],
    sparse_vectors: Optional[List[Tuple[List[int], List[float]]]] = None
):
    """写入混合向量（dense + 可选 sparse BM25）。同步版本。"""
    _upsert_vectors_impl(vectors, payloads, sparse_vectors)


def upsert_vectors_dense_only(vectors: List[List[float]], payloads: List[Dict[str, Any]]):
    """仅写入 dense 向量（向后兼容）"""
    _upsert_vectors_impl(vectors, payloads, None)


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
    sparse_vectors: Optional[List[Tuple[List[int], List[float]]]] = None
):
    """写入混合向量内部实现"""
    client = get_qdrant_client()
    points = []

    for i, (v, p) in enumerate(zip(vectors, payloads)):
        point_dict: Dict[str, Any] = {
            "id": _chunk_id_to_point_id(p["chunk_id"]),
            "payload": p,
            DENSE_VECTOR_NAME: v,
        }

        if sparse_vectors and i < len(sparse_vectors):
            indices, values = sparse_vectors[i]
            if indices:
                from qdrant_client.http.models import SparseVector as QdrantSparseVector
                point_dict[SPARSE_VECTOR_NAME] = QdrantSparseVector(indices=indices, values=values)

        points.append(models.PointStruct(**point_dict))

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info(f"Upserted {len(points)} hybrid vectors to Qdrant (dense+sparse={sparse_vectors is not None}).")


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


def _clone_kb_index_impl(source_kb_id: int, target_kb_id: int) -> dict:
    """将 source_kb_id 下的所有向量复制到 target_kb_id"""
    client = get_qdrant_client()

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
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=kb_filter,
            limit=500,
            offset=offset,
            with_vectors=True,
        )
        all_points.extend(result.points)
        if result.next_page_offset is None:
            break
        offset = result.next_page_offset

    if not all_points:
        logger.info(f"Clone KB index: source kb_id={source_kb_id} has no points.")
        return {"cloned_chunk_count": 0, "cloned_doc_ids": []}

    from qdrant_client.http.models import SparseVector as QdrantSparseVector
    target_points = []
    cloned_doc_ids = set()

    for pt in all_points:
        payload = dict(pt.payload or {})
        payload["kb_id"] = target_kb_id

        new_chunk_id = payload.get("chunk_id", "")
        point_id = _chunk_id_to_point_id(new_chunk_id)

        point_dict: Dict[str, Any] = {
            "id": point_id,
            "payload": payload,
            DENSE_VECTOR_NAME: pt.vector.get(DENSE_VECTOR_NAME) if pt.vector else None,
        }

        if pt.vector and SPARSE_VECTOR_NAME in pt.vector:
            sparse = pt.vector[SPARSE_VECTOR_NAME]
            point_dict[SPARSE_VECTOR_NAME] = QdrantSparseVector(
                indices=sparse.indices,
                values=sparse.values,
            )

        target_points.append(models.PointStruct(**point_dict))
        cloned_doc_ids.add(payload.get("doc_id"))

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
    sparse_vectors: Optional[List[Tuple[List[int], List[float]]]] = None
):
    """写入混合向量（dense + 可选 sparse BM25）。Async 版本。"""
    await asyncio.to_thread(_upsert_vectors_impl, vectors, payloads, sparse_vectors)


async def upsert_vectors_dense_only_async(vectors: List[List[float]], payloads: List[Dict[str, Any]]):
    """仅写入 dense 向量。Async 版本。"""
    await asyncio.to_thread(_upsert_vectors_impl, vectors, payloads, None)


async def delete_document_index_async(doc_id: int):
    """删除指定 doc_id 的所有向量。Async 版本。"""
    await asyncio.to_thread(_delete_document_index_impl, doc_id)


async def delete_kb_index_async(kb_id: int):
    """删除指定 kb_id 下的所有向量。Async 版本。"""
    await asyncio.to_thread(_delete_kb_index_impl, kb_id)


async def clone_kb_index_async(source_kb_id: int, target_kb_id: int) -> dict:
    """将 source_kb_id 下的所有向量复制到 target_kb_id。Async 版本。"""
    return await asyncio.to_thread(_clone_kb_index_impl, source_kb_id, target_kb_id)


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
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=kb_filter,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        all_points.extend(result.points)
        if result.next_page_offset is None:
            break
        offset = result.next_page_offset

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
    idf_terms_updated = 0
    if rebuild_bm25_idf and total_chunks > 0:
        # 重新收集所有 chunk 文本
        texts_for_idf = [
            pt.payload.get("text", "") for pt in all_points if pt.payload
        ]
        from ..retrieval.retriever import _compute_idf_from_chunks
        new_idf = _compute_idf_from_chunks(texts_for_idf)

        # 合并到现有 IDF（增量更新，不丢失其他 kb_id 的 IDF）
        import json
        idf_path = os.path.join(os.path.dirname(__file__), "..", "retrieval", "bm25_idf.json")
        existing_idf = {}
        if os.path.exists(idf_path):
            try:
                with open(idf_path, "r", encoding="utf-8") as f:
                    existing_idf = json.load(f)
            except Exception:
                pass

        # 合并：new_idf 覆盖旧值
        existing_idf.update(new_idf)
        idf_terms_updated = len(new_idf)

        try:
            os.makedirs(os.path.dirname(idf_path), exist_ok=True)
            with open(idf_path, "w", encoding="utf-8") as f:
                json.dump(existing_idf, f, ensure_ascii=False)
            logger.info(f"Rebuilt BM25 IDF: {idf_terms_updated} terms updated, saved to {idf_path}")

            # 刷新全局缓存
            from ..retrieval.retriever import _BM25_IDF_CACHE
            _BM25_IDF_CACHE.clear()
            _BM25_IDF_CACHE.update(existing_idf)
        except Exception as e:
            logger.warning(f"Failed to persist BM25 IDF: {e}")

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
