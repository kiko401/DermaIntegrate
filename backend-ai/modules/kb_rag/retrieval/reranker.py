"""
重排序模块

支持两种模式：
1. Cross-Encoder 重排（优先）：使用 BAAI/bge-reranker-large 对 query-chunk 对做语义相关性打分
2. 规则加权（兜底）：dense_norm * 0.6 + keyword_hit_ratio * 0.1

Cross-Encoder 不可用时（未安装/模型加载失败）自动降级到规则加权。
"""
import logging
import copy
from typing import List, Dict, Tuple, Optional

from shared.config import RERANK_MODEL

logger = logging.getLogger(__name__)

# 规则加权权重（Cross-Encoder 不可用时的兜底方案）
RERANK_WEIGHT_DENSE = 0.6
RERANK_WEIGHT_KEYWORD = 0.1

# Cross-Encoder 实例（延迟加载）
_reranker = None
_reranker_load_error: Optional[str] = None


def _get_reranker():
    """
    获取 Cross-Encoder 向量化器实例（延迟加载单例）。
    加载失败时返回 None，并记录错误原因供降级判断。
    """
    global _reranker, _reranker_load_error
    if _reranker is not None or _reranker_load_error:
        return _reranker

    try:
        from sentence_transformers import CrossEncoder
        logger.info(f"Loading Cross-Encoder model: {RERANK_MODEL}")
        _reranker = CrossEncoder(RERANK_MODEL, max_length=512)
        logger.info(f"Cross-Encoder model loaded successfully.")
        return _reranker
    except Exception as e:
        _reranker_load_error = str(e)
        logger.warning(f"Cross-Encoder model loading failed: {_reranker_load_error}. Falling back to rule-based reranking.")
        return None


def _tokenize_for_rerank(text: str) -> List[str]:
    """轻量分词：用于规则加权的关键词命中计算"""
    from ..utils import tokenize as _shared_tokenize
    return _shared_tokenize(text)


def _cross_encoder_rerank(query: str, chunks: List[Dict], top_k: int) -> List[Dict]:
    """
    Cross-Encoder 重排实现。

    对每个 (query, chunk_text) 对让 Cross-Encoder 打相关性分数，
    按分数降序返回 top_k。
    """
    reranker = _get_reranker()
    if reranker is None:
        return None  # 返回 None 表示不可用，调用方应降级

    # 构造 query-document 对
    pairs: List[Tuple[str, str]] = [(query, c.get("text", "")) for c in chunks]

    try:
        scores: List[float] = reranker.predict(pairs, show_progress_bar=False)

        # 将分数挂接到 chunks，并按分数降序
        scored = []
        for c, score in zip(chunks, scores):
            chunk_copy = copy.deepcopy(c)
            chunk_copy["rerank_score"] = float(score)
            chunk_copy["cross_encoder_score"] = float(score)
            scored.append(chunk_copy)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        logger.info(
            f"Cross-Encoder reranked {len(scored)} chunks, "
            f"top_score={scored[0]['rerank_score']:.4f}, "
            f"bottom_score={scored[-1]['rerank_score']:.4f}"
        )
        return scored[:top_k]

    except Exception as e:
        logger.warning(f"Cross-Encoder prediction failed: {e}. Falling back to rule-based reranking.")
        return None


def _rule_based_rerank(query: str, chunks: List[Dict], top_k: int) -> List[Dict]:
    """
    规则加权重排（兜底方案）。

    rerank_score = dense_norm * 0.6 + keyword_hit_ratio * 0.1
    """
    if not chunks:
        return []

    query_tokens = set(_tokenize_for_rerank(query))

    scored_chunks = []
    for c in chunks:
        chunk_copy = copy.deepcopy(c)

        dense_norm = chunk_copy.get("dense_norm", 0.0)

        text_tokens = set(_tokenize_for_rerank(chunk_copy.get("text", "")))
        keyword_hits = len(query_tokens & text_tokens)
        total_query_tokens = len(query_tokens) if query_tokens else 1
        keyword_hit_ratio = keyword_hits / total_query_tokens

        rerank_score = (
            RERANK_WEIGHT_DENSE * dense_norm
            + RERANK_WEIGHT_KEYWORD * keyword_hit_ratio
        )

        chunk_copy["rerank_score"] = round(rerank_score, 6)
        chunk_copy["rule_based_score"] = round(rerank_score, 6)
        chunk_copy["keyword_hits"] = keyword_hits
        scored_chunks.append(chunk_copy)

    scored_chunks.sort(key=lambda x: x["rerank_score"], reverse=True)
    logger.info(
        f"Rule-based reranked {len(scored_chunks)} chunks: "
        f"top_score={scored_chunks[0]['rerank_score']:.4f}"
    )
    return scored_chunks[:top_k]


def rerank(query: str, chunks: List[Dict], top_k: int = 5) -> List[Dict]:
    """
    对 RRF 融合后的 chunk 列表做二次重排序。

    策略：
    1. 优先使用 Cross-Encoder（BAAI/bge-reranker-large）
    2. Cross-Encoder 不可用时降级到规则加权

    Args:
        query: 用户原始问题
        chunks: RRF 融合后的 chunk 列表，每个须含 dense_norm、text 字段
        top_k: 返回的重排结果数量

    Returns:
        重排后的 chunk 列表（rerank_score 字段为最终分数）
    """
    if not chunks:
        return []

    # 预先计算 dense_norm（如果缺失的话）
    for c in chunks:
        if "dense_norm" not in c:
            max_dense = max((x.get("score", 0) for x in chunks), default=1.0)
            c["dense_norm"] = c.get("score", 0) / max_dense if max_dense > 0 else 0

    # 尝试 Cross-Encoder
    ce_result = _cross_encoder_rerank(query, chunks, top_k)
    if ce_result is not None:
        return ce_result

    # 降级到规则加权
    return _rule_based_rerank(query, chunks, top_k)
