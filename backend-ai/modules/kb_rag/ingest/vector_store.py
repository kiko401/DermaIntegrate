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
        host = "qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost"
        port = int(os.getenv("QDRANT_PORT", "6333"))
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
    _upsert_vectors_impl(vectors, payloads, sparse_vectors=None)


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
