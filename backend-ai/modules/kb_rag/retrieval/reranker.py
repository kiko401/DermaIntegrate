"""
轻量级重排序模块

在 RRF 融合结果基础上，对 dense 归一化分、BM25 归一化分、关键词命中数做三元加权，
生成最终 rerank_score 并重排。

权重分配：
- dense_norm（语义相似度）: 0.6
- bm25_norm（关键词命中）: 0.3
- keyword_hit_ratio（命中密度）: 0.1

rerank_score = 0.6 * dense_norm + 0.3 * bm25_norm + 0.1 * keyword_hit_ratio
"""
import logging
import copy
from typing import List, Dict

logger = logging.getLogger(__name__)

# 重排序权重
RERANK_WEIGHT_DENSE = 0.6
RERANK_WEIGHT_BM25 = 0.3
RERANK_WEIGHT_KEYWORD = 0.1


def _tokenize_for_rerank(text: str) -> List[str]:
    """轻量分词：用于 rerank 关键词命中计算（委托给 utils.tokenize）"""
    from ..utils import tokenize as _shared_tokenize
    return _shared_tokenize(text)


def rerank(query: str, chunks: List[Dict], top_k: int = 5) -> List[Dict]:
    """
    对 RRF 融合后的 chunk 列表做二次重排序。

    Args:
        query: 用户原始问题
        chunks: RRF 融合后的 chunk 列表，每个须含 dense_norm、bm25_score 字段
        top_k: 返回的重排结果数量

    Returns:
        重排后的 chunk 列表（score 字段替换为 rerank_score）
        注意：返回新列表，不修改原始输入列表（M-08）
    """
    if not chunks:
        return []

    query_tokens = set(_tokenize_for_rerank(query))
    max_bm25 = max((c.get("bm25_score", 0.0) for c in chunks), default=1.0)
    if max_bm25 <= 0:
        max_bm25 = 1.0

    scored_chunks = []
    for c in chunks:
        # M-08: 深拷贝避免修改原始输入列表
        chunk_copy = copy.deepcopy(c)

        dense_norm = chunk_copy.get("dense_norm", 0.0)
        bm25_raw = chunk_copy.get("bm25_score", 0.0)
        bm25_norm = bm25_raw / max_bm25

        text_tokens = set(_tokenize_for_rerank(chunk_copy.get("text", "")))
        keyword_hits = len(query_tokens & text_tokens)
        # 命中密度：命中词数 / query 总词数（避免 query 长度影响）
        total_query_tokens = len(query_tokens) if query_tokens else 1
        keyword_hit_ratio = keyword_hits / total_query_tokens

        rerank_score = (
            RERANK_WEIGHT_DENSE * dense_norm
            + RERANK_WEIGHT_BM25 * bm25_norm
            + RERANK_WEIGHT_KEYWORD * keyword_hit_ratio
        )

        chunk_copy["score"] = round(rerank_score, 6)
        chunk_copy["rerank_score"] = round(rerank_score, 6)
        chunk_copy["keyword_hits"] = keyword_hits
        scored_chunks.append(chunk_copy)

    scored_chunks.sort(key=lambda x: x["rerank_score"], reverse=True)
    logger.info(f"Reranked {len(scored_chunks)} chunks: top score={scored_chunks[0]['rerank_score']:.4f}")

    return scored_chunks[:top_k]
