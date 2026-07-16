"""
混合检索器

支持 Dense向量检索 + BM25关键词检索 + RRF融合

RRF (Reciprocal Rank Fusion):
    score = Σ 1 / (k + rank_i)
    k = 60 (默认)
"""
import os
import re
import math
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional
from collections import Counter

from ..ingest.embeddings import get_embedder
from ..ingest.vector_store import get_qdrant_client, COLLECTION_NAME, DENSE_VECTOR_NAME
from qdrant_client.http import models

from .reranker import rerank

logger = logging.getLogger(__name__)

# BM25 参数（与bm25.py保持一致）
BM25_K1 = 1.5
BM25_B = 0.75
AVG_DOC_LEN = 200

# RRF 融合参数
RRF_K = 60  # 标准值


def _tokenize(text: str) -> List[str]:
    """中文/英文混合分词（委托给 utils.tokenize）"""
    from ..utils import tokenize as _shared_tokenize
    return _shared_tokenize(text)


def _compute_bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    idf: Dict[str, float],
    avg_doc_len: float
) -> float:
    """计算 query 对单篇文档的 BM25 得分"""
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
    """检索时 BM25 评分器（使用预存的 IDF 值）"""

    def __init__(self, idf: Dict[str, float], avg_doc_len: float = AVG_DOC_LEN):
        self.idf = idf
        self.avg_doc_len = avg_doc_len

    def score(self, query: str, doc_text: str) -> float:
        query_tokens = _tokenize(query)
        doc_tokens = _tokenize(doc_text)
        return _compute_bm25_score(query_tokens, doc_tokens, self.idf, self.avg_doc_len)


# BM25 IDF 全局缓存（启动时加载或动态构建）
_BM25_IDF_CACHE: Dict[str, Dict[str, float]] = {}
_BM25_IDF_PATH: str = os.path.join(os.path.dirname(__file__), "..", "assets", "bm25_idf.json")


def _load_bm25_idf() -> Dict[str, float]:
    """从本地文件加载 BM25 IDF 值（预计算并持久化）"""
    global _BM25_IDF_CACHE
    path = _BM25_IDF_PATH
    if not os.path.exists(path):
        logger.warning(f"BM25 IDF file not found at {path}. BM25 scoring will use fallback.")
        return {}
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _BM25_IDF_CACHE = data
        logger.info(f"Loaded BM25 IDF from {path}: {len(data)} terms.")
        return data
    except Exception as e:
        logger.warning(f"Failed to load BM25 IDF: {e}")
        return {}


def _save_bm25_idf(idf: Dict[str, float]):
    """持久化 BM25 IDF 到本地文件"""
    try:
        os.makedirs(os.path.dirname(_BM25_IDF_PATH), exist_ok=True)
        import json
        with open(_BM25_IDF_PATH, "w", encoding="utf-8") as f:
            json.dump(idf, f, ensure_ascii=False)
        logger.info(f"Saved BM25 IDF to {_BM25_IDF_PATH}: {len(idf)} terms.")
    except Exception as e:
        logger.warning(f"Failed to save BM25 IDF: {e}")


def _get_global_idf() -> Dict[str, float]:
    """获取全局 IDF（优先加载缓存，否则返回空字典）"""
    if not _BM25_IDF_CACHE:
        return _load_bm25_idf()
    return _BM25_IDF_CACHE


def _compute_idf_from_chunks(texts: List[str]) -> Dict[str, float]:
    """
    从 chunk 列表动态计算 IDF（当没有预存 IDF 时的兜底方案）
    用于初始化 IDF 缓存文件。
    """
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


def _rrf_fuse(dense_scores: Dict[str, float], bm25_scores: Dict[str, float], k: int = RRF_K) -> List[Tuple[str, float]]:
    """
    RRF 融合两个排名列表。

    Args:
        dense_scores: {chunk_id -> dense_similarity_score}
        bm25_scores: {chunk_id -> bm25_score}
        k: RRF 参数

    Returns:
        [(chunk_id, fused_score), ...] 按融合分数降序
    """
    all_ids = set(dense_scores.keys()) | set(bm25_scores.keys())

    # 分别排序
    dense_sorted = sorted(dense_scores.items(), key=lambda x: x[1], reverse=True)
    bm25_sorted = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)

    # rank 映射
    dense_rank = {cid: rank for rank, (cid, _) in enumerate(dense_sorted)}
    bm25_rank = {cid: rank for rank, (cid, _) in enumerate(bm25_sorted)}

    # RRF 得分
    fused = {}
    for cid in all_ids:
        d_rank = dense_rank.get(cid, len(dense_sorted))
        b_rank = bm25_rank.get(cid, len(bm25_sorted))
        score = 1.0 / (k + d_rank) + 1.0 / (k + b_rank)
        fused[cid] = score

    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


async def retrieve(
    query: str,
    kb_ids: List[int],
    top_k: int = 5,
    threshold: float = 0.35,
    use_hybrid: bool = True,
    use_rerank: bool = False,
) -> Tuple[List[Dict], bool]:
    """
    执行混合检索（Dense + BM25 + RRF融合）

    Args:
        query: 用户问题
        kb_ids: 知识库ID列表
        top_k: 返回的最终结果数
        threshold: Dense向量相似度阈值（低于此值阻断）
        use_hybrid: 是否启用混合检索（False则仅用Dense）

    Returns:
        (chunks列表, 是否被低置信度阻断)
    """
    if not kb_ids:
        return [], True

    try:
        embedder = get_embedder()
        query_vector = embedder.encode(query, normalize_embeddings=True).tolist()

        # 多知识库过滤
        kb_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="kb_id",
                    match=models.MatchAny(any=kb_ids)
                )
            ]
        )

        fetch_limit = top_k * 4 if use_hybrid else top_k

        # ===== 1. Dense 向量检索（Qdrant 同步调用包装为异步）=====
        async def _search_dense():
            client = get_qdrant_client()
            return client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                query_filter=kb_filter,
                limit=fetch_limit,
                using=DENSE_VECTOR_NAME,
                with_payload=True
            )

        search_response = await asyncio.to_thread(_search_dense)

        if not search_response.points:
            logger.warning(f"Dense retrieval returned no results. Query: {query[:50]}")
            return [], True

        # 构建 dense 结果映射
        dense_scores: Dict[str, float] = {}
        candidates: List[Dict] = []
        for hit in search_response.points:
            payload = hit.payload or {}
            chunk_id = payload.get("chunk_id", "")
            dense_scores[chunk_id] = hit.score
            candidates.append({
                "doc_id": payload.get("doc_id"),
                "doc_version_id": payload.get("doc_version_id"),
                "chunk_id": chunk_id,
                "text": payload.get("text", ""),
                "score": hit.score,  # 临时存 dense 分数
            })

        # ===== 2. BM25 关键词检索 =====
        bm25_scores: Dict[str, float] = {}
        if use_hybrid:
            idf = _get_global_idf()
            if idf:
                scorer = BM25Scorer(idf)
                for c in candidates:
                    bm25_s = scorer.score(query, c["text"])
                    bm25_scores[c["chunk_id"]] = bm25_s
            else:
                # 无预存 IDF：使用关键词命中计数作为轻量级替代
                query_tokens = set(_tokenize(query))
                for c in candidates:
                    doc_tokens = set(_tokenize(c["text"]))
                    overlap = len(query_tokens & doc_tokens)
                    bm25_scores[c["chunk_id"]] = float(overlap)

        # ===== 3. RRF 融合 =====
        max_dense = max(dense_scores.values()) if dense_scores else 1.0
        max_bm25 = max(bm25_scores.values()) if bm25_scores else 1.0

        if use_hybrid and bm25_scores:
            fused_order = _rrf_fuse(dense_scores, bm25_scores)
            chunk_id_to_data = {c["chunk_id"]: c for c in candidates}

            # 按融合顺序重排，并计算最终分数
            fused_chunks = []
            for chunk_id, fused_score in fused_order:
                c = chunk_id_to_data[chunk_id]
                norm_dense = c["score"] / max_dense if max_dense > 0 else 0
                fused_chunks.append({
                    "doc_id": c["doc_id"],
                    "doc_version_id": c["doc_version_id"],
                    "chunk_id": c["chunk_id"],
                    "text": c["text"],
                    "score": round(fused_score, 6),
                    "dense_score": round(c["score"], 4),
                    "bm25_score": round(bm25_scores.get(chunk_id, 0), 4),
                    "dense_norm": round(norm_dense, 4),
                })
        else:
            # 仅 Dense 模式
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
                })

        # ===== 4. 可选重排序 =====
        if use_rerank:
            final_chunks = rerank(query, fused_chunks, top_k)
        else:
            final_chunks = fused_chunks[:top_k]

        # ===== 4. 低置信度阻断 =====
        max_dense_score = max((c.get("dense_score", 0) for c in final_chunks), default=0)
        if max_dense_score < threshold and not use_hybrid:
            logger.warning(f"Retrieval blocked: max_dense_score={max_dense_score} < threshold={threshold}")
            return [], True

        # 混合模式下用归一化 dense 分数判断
        max_norm = max((c.get("dense_norm", 0) for c in final_chunks), default=0)
        if use_hybrid and max_norm < threshold:
            logger.warning(f"Hybrid retrieval blocked: max_norm={max_norm} < threshold={threshold}")
            return [], True

        return final_chunks, False

    except Exception as e:
        logger.error(f"Retrieval failed: {e}", exc_info=True)
        return [], True
