import os
import logging
from typing import List, Dict, Any, Tuple
from ..ingest.embeddings import get_embedder
from ..ingest.vector_store import get_qdrant_client, COLLECTION_NAME
from qdrant_client.http import models

logger = logging.getLogger(__name__)


async def retrieve(query: str, kb_ids: List[int], top_k: int = 5, threshold: float = 0.35) -> Tuple[List[Dict], bool]:
    """
    执行多知识库向量检索
    返回: (chunks列表, 是否被低置信度阻断)
    """
    if not kb_ids:
        return [], True

    try:
        # 1. 向量化 query
        embedder = get_embedder()
        query_vector = embedder.encode(query, normalize_embeddings=True).tolist()

        # 2. 构造多知识库过滤条件 (MatchAny 实现 OR 逻辑)
        kb_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="kb_id",
                    match=models.MatchAny(any=kb_ids)
                )
            ]
        )

        # 3. 执行 Qdrant 检索
        client = get_qdrant_client()
        search_response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=kb_filter,
            limit=top_k,
            score_threshold=threshold,
            with_payload=True
        )

        # 4. 处理结果与低置信度阻断
        if not search_response.points:
            logger.warning(f"Retrieval blocked due to low confidence. Query: {query}")
            return [], True

        chunks = []
        for hit in search_response.points:
            payload = hit.payload or {}
            chunks.append({
                "doc_id": payload.get("doc_id"),
                "doc_version_id": payload.get("doc_version_id"),
                "chunk_id": payload.get("chunk_id"),
                "text": payload.get("text", ""),
                "score": hit.score
            })

        return chunks, False

    except Exception as e:
        logger.error(f"Retrieval failed: {e}", exc_info=True)
        return [], True