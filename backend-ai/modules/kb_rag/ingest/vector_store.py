import os
import logging
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)

COLLECTION_NAME = "rag_documents"

def get_qdrant_client() -> QdrantClient:
    """获取 Qdrant 客户端单例"""
    # 简单的单例实现，实际生产环境可放入依赖注入
    if not hasattr(get_qdrant_client, "_instance"):
        host = "qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost"
        port = int(os.getenv("QDRANT_PORT", "6333"))
        get_qdrant_client._instance = QdrantClient(host=host, port=port)
        logger.info(f"QdrantClient initialized for {host}:{port}")
    return get_qdrant_client._instance

def init_qdrant_collection():
    """启动时初始化 Qdrant 集合 (单一共享集合)"""
    client = get_qdrant_client()
    collections = client.get_collections().collections
    if not any(c.name == COLLECTION_NAME for c in collections):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE)
        )
        # 为 kb_id 和 doc_id 创建 payload 索引，加速过滤
        client.create_payload_index(COLLECTION_NAME, "kb_id", models.PayloadSchemaType.INTEGER)
        client.create_payload_index(COLLECTION_NAME, "doc_id", models.PayloadSchemaType.INTEGER)
        logger.info(f"Qdrant collection '{COLLECTION_NAME}' created.")
    else:
        logger.info(f"Qdrant collection '{COLLECTION_NAME}' already exists.")

def upsert_vectors(vectors: List[List[float]], payloads: List[Dict[str, Any]]):
    """写入向量，强制 payload 包含 kb_id, doc_id, chunk_id, doc_version_id, text"""
    client = get_qdrant_client()
    points = [
        models.PointStruct(
            # 使用 chunk_id 的哈希作为 Qdrant 的 point_id，保证幂等
            id=hash(p["chunk_id"]) % (2**63),
            vector=v,
            payload=p
        ) for v, p in zip(vectors, payloads)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info(f"Upserted {len(points)} vectors to Qdrant.")

def delete_document_index(doc_id: int):
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

def delete_kb_index(kb_id: int):
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