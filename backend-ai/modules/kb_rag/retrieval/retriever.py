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
from ..ingest.vector_store import get_qdrant_client, COLLECTION_NAME, DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME
from ..ingest.bm25 import get_bm25_vectorizer, fit_bm25_on_collection, generate_sparse_vector
from qdrant_client.http import models
from qdrant_client.http.models import SparseVector as QdrantSparseVector
from shared.constants import BM25_K1, BM25_B, AVG_DOC_LEN

from .reranker import rerank

logger = logging.getLogger(__name__)

# BM25 参数（已统一到 shared/constants.py）
# RRF 融合参数
RRF_K = 60  # 标准值

# BM25Vectorizer 全局初始拟合标志（防止重复拟合）
_bm25_fitted = False


def _load_all_chunk_texts() -> List[str]:
    """从 Qdrant 加载所有 chunk 的原文（用于 BM25 全量拟合）"""
    try:
        client = get_qdrant_client()
        all_texts = []
        offset = None
        while True:
            pts, next_offset = client.scroll(
                collection_name=COLLECTION_NAME,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
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
    """
    在 Qdrant 所有 chunk 上拟合 BM25Vectorizer（全量词表 + 全局 IDF）。
    应在 KB-RAG 初始化时调用一次，使后续 generate_sparse_vector 生效。
    """
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
    doctor_id: Optional[int] = None,
) -> Tuple[List[Dict], bool]:
    """
    执行混合检索（Dense + BM25 + RRF融合）

    Args:
        query: 用户问题
        kb_ids: 知识库ID列表
        top_k: 返回的最终结果数
        threshold: Dense向量相似度阈值（低于此值阻断）
        use_hybrid: 是否启用混合检索（False则仅用Dense）
        doctor_id: 医生ID（用于临床病例权限隔离；空则不过滤）

    Returns:
        (chunks列表, 是否被低置信度阻断)
    """
    if not kb_ids:
        return [], True

    try:
        embedder = get_embedder()
        query_vector = embedder.encode(query, normalize_embeddings=True).tolist()

        # 多知识库过滤 + 医生权限隔离
        must_conditions = [
            models.FieldCondition(
                key="kb_id",
                match=models.MatchAny(any=kb_ids)
            )
        ]
        if doctor_id is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="doctor_id",
                    match=models.MatchValue(value=doctor_id)
                )
            )
        kb_filter = models.Filter(must=must_conditions)

        fetch_limit = top_k * 4 if use_hybrid else top_k

        # ===== 1. Dense 向量检索（Qdrant 同步调用包装为异步）=====
        def _search_dense():
            client = get_qdrant_client()
            # 优先用命名向量搜索
            try:
                return client.query_points(
                    collection_name=COLLECTION_NAME,
                    query=query_vector,
                    query_filter=kb_filter,
                    limit=fetch_limit,
                    using=DENSE_VECTOR_NAME,
                    with_payload=True
                )
            except Exception:
                # fallback：尝试默认向量（兼容 legacy init 写入的无名向量数据）
                try:
                    return client.query_points(
                        collection_name=COLLECTION_NAME,
                        query=query_vector,
                        query_filter=kb_filter,
                        limit=fetch_limit,
                        with_payload=True
                    )
                except Exception as e:
                    logger.warning(f"Dense search failed (both named and default): {e}")
                    # 两个搜索都失败时返回 None，后续统一处理
                    return None

        search_response = await asyncio.to_thread(_search_dense)

        if search_response is None or not search_response.points:
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

        # ===== 2. BM25 Sparse 向量检索（真实 Qdrant sparse index 查询）=====
        bm25_scores: Dict[str, float] = {}
        if use_hybrid:
            # 优先使用 Qdrant sparse index 做真正的 BM25 混合检索
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
                if sparse_resp and sparse_resp.points:
                    for hit in sparse_resp.points:
                        payload = hit.payload or {}
                        chunk_id = payload.get("chunk_id", "")
                        bm25_scores[chunk_id] = hit.score
                    logger.info(f"Sparse search retrieved {len(sparse_resp.points)} hits.")

            # 兜底：如果 sparse 搜索无结果或未拟合，使用本地 BM25 评分（候选集重打分）
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
        # 使用归一化 dense 分数（0~1）判断，兼容 hybrid 和 dense-only 两种模式
        # dense_norm 已在融合阶段计算（dense_score / max_dense），保证跨模式可比性
        max_norm = max((c.get("dense_norm", 0) for c in final_chunks), default=0)
        if max_norm < threshold:
            mode = "hybrid" if use_hybrid else "dense"
            logger.warning(f"Retrieval blocked: {mode} max_norm={max_norm:.4f} < threshold={threshold}")
            return [], True

        return final_chunks, False

    except Exception as e:
        logger.error(f"Retrieval failed: {e}", exc_info=True)
        return [], True
