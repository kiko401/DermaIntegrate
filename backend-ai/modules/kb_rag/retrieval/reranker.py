import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


async def rerank(query: str, chunks: List[Dict]) -> List[Dict]:
    """
    对检索结果进行轻量级重排序。
    在向量相似度得分基础上，根据 query 中关键词在 chunk 文本中的命中次数进行加分。
    """
    if not chunks:
        return []

    query_words = list(set(query.replace("？", "").replace("？", "").split()))

    for chunk in chunks:
        text = chunk.get("text", "")
        keyword_hits = sum(1 for word in query_words if word in text)
        original_score = chunk.get("score", 0.0)
        chunk["reranked_score"] = original_score + (keyword_hits * 0.05)
        chunk["keyword_hits"] = keyword_hits

    reranked_chunks = sorted(chunks, key=lambda x: x["reranked_score"], reverse=True)
    logger.info(f"Reranked {len(reranked_chunks)} chunks based on keyword hits.")
    return reranked_chunks
