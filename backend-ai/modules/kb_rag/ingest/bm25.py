"""
BM25 稀疏向量生成模块

为每个文档生成 BM25 权重向量，用于 Qdrant 混合检索。

BM25 稀疏向量结构：
- indices: 非零维度（token在词表中的位置）的列表
- values: 对应维度的 BM25 得分（归一化到 0~1）
"""
import os
import re
import json
import logging
import math
import threading
from typing import List, Dict, Tuple, Optional
from collections import Counter

from shared.constants import BM25_K1, BM25_B, AVG_DOC_LEN

logger = logging.getLogger(__name__)

# IDF 持久化路径（与 retriever.py 共用同一路径）
_IDF_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "bm25_idf.json")


def _save_bm25_idf(idf: Dict[str, float]):
    """持久化 BM25 IDF 到本地文件（追加合并）"""
    try:
        existing = {}
        if os.path.exists(_IDF_PATH):
            with open(_IDF_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.update(idf)
        os.makedirs(os.path.dirname(_IDF_PATH), exist_ok=True)
        with open(_IDF_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)
        logger.info(f"Saved BM25 IDF to {_IDF_PATH}: {len(idf)} new terms, {len(existing)} total.")
    except Exception as e:
        logger.warning(f"Failed to save BM25 IDF: {e}")

# BM25 参数（已统一到 shared/constants.py）
_CACHE_VERSION: Dict[str, int] = {}  # 用于判断是否需要重建索引

# 全局 BM25 缓存（按 collection 隔离，必须初始化为字面量 dict）
_COLLECTION_VOCAB: Dict[str, List[str]] = {}  # {collection_name: vocab_list}
_COLLECTION_IDF: Dict[str, Dict[str, float]] = {}  # {collection_name: {token: idf_value}}
_CACHE_LOCK = threading.RLock()  # M-07: 保护全局缓存的线程安全访问


class BM25Vectorizer:
    """单机 BM25 实现，用于生成稀疏向量（不走外部服务）。"""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.vocab: Dict[str, int] = {}    # M-06: 词表 {token: index}，O(1)查找
        self.idf: Dict[str, float] = {}   # 每个词的 IDF 得分
        self.doc_count = 0

    def _tokenize(self, text: str) -> List[str]:
        """中文/英文混合分词（委托给 utils.tokenize）"""
        from ..utils import tokenize as _shared_tokenize
        return _shared_tokenize(text)

    def _compute_idf(self, token_to_docs: Dict[str, int], total_docs: int) -> Dict[str, float]:
        """计算 IDF：log((N - n + 0.5) / (n + 0.5) + 1)"""
        idf = {}
        for token, doc_freq in token_to_docs.items():
            # 避免 log(0)：加 1平滑
            idf[token] = math.log((total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1)
            idf[token] = max(idf[token], 0.0)  # IDF >= 0
        return idf

    def fit(self, texts: List[str]) -> "BM25Vectorizer":
        """
        在语料上拟合：构建词表，计算全局 IDF。

        Args:
            texts: 文档文本列表
        """
        self.doc_count = len(texts)
        token_counter = Counter()
        token_to_docs = Counter()

        for text in texts:
            tokens = self._tokenize(text)
            unique_tokens = set(tokens)
            for token in unique_tokens:
                token_to_docs[token] += 1
            token_counter.update(tokens)

        # 词表 = 出现次数 >= 2 的词（或取 top 50000）
        # M-06: 使用 dict {token: index} 而非 list，transform 时 O(1) 查找
        frequent_tokens = [t for t, c in token_counter.most_common(50000) if c >= 2]
        self.vocab = {t: i for i, t in enumerate(frequent_tokens)}

        # 构建 IDF
        self.idf = self._compute_idf(dict(token_to_docs), self.doc_count)

        logger.info(f"BM25 fitted: vocab_size={len(self.vocab)}, docs={self.doc_count}")
        return self

    def transform(self, text: str) -> Tuple[List[int], List[float]]:
        """
        将单条文本转换为稀疏向量（BM25 权重）。

        Returns:
            (indices, values) - 稀疏向量的非零维度和对应值（归一化到 0~1）
        """
        if not self.vocab:
            return [], []

        tokens = self._tokenize(text)
        token_freq = Counter(tokens)

        # 统计文档长度（token数）
        doc_len = len(tokens) or 1

        indices = []
        values = []

        for token in set(tokens):
            if token not in self.vocab:
                continue
            idx = self.vocab[token]  # M-06: O(1) dict lookup
            tf = token_freq[token]
            idf = self.idf.get(token, 0.0)

            # BM25 公式：IDF * (tf * (k1+1)) / (tf + k1 * (1 - b + b * d/avg_d))
            bm25_score = idf * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / AVG_DOC_LEN))

            indices.append(idx)
            values.append(bm25_score)

        # 归一化到 0~1（按最大值）
        if values:
            max_val = max(values)
            if max_val > 0:
                values = [v / max_val for v in values]

        # 按 index 排序（Qdrant sparse vector 要求 indices 升序）
        sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
        indices, values = zip(*sorted_pairs) if sorted_pairs else ([], [])

        return list(indices), list(values)

    def transform_batch(self, texts: List[str]) -> List[Tuple[List[int], List[float]]]:
        """批量转换"""
        return [self.transform(t) for t in texts]


# ===== 全局缓存访问函数 =====

def get_bm25_vectorizer(collection_name: str) -> BM25Vectorizer:
    """
    获取已拟合的 BM25 向量化器（按 collection 隔离）。

    注意：必须先调用 fit_bm25_on_collection 填充缓存，此函数才能返回有效的向量化器。
    如果 collection 未被拟合（vocab 为空），返回一个带有空词表的向量化器，
    其 transform() 会返回空结果（不崩溃）。
    """
    with _CACHE_LOCK:
        # 情况1：collection 从未被记录过（未 fit），创建空壳并标记
        if collection_name not in _COLLECTION_VOCAB:
            vectorizer = BM25Vectorizer(collection_name)
            _COLLECTION_VOCAB[collection_name] = {}
            _COLLECTION_IDF[collection_name] = {}
            logger.warning(f"BM25 vectorizer for '{collection_name}' requested before fit. Returning empty vectorizer.")
            return vectorizer

        # 情况2：collection 存在但 vocab 为空（上次 fit 失败或刚创建），返回空壳
        if not _COLLECTION_VOCAB[collection_name]:
            logger.warning(f"BM25 vectorizer for '{collection_name}' has empty vocab (not fitted). Returning empty vectorizer.")
            vectorizer = BM25Vectorizer(collection_name)
            return vectorizer

        # 情况3：已拟合，从缓存重建
        vectorizer = BM25Vectorizer(collection_name)
        vectorizer.vocab = _COLLECTION_VOCAB[collection_name]
        vectorizer.idf = _COLLECTION_IDF.get(collection_name, {})
        return vectorizer


def fit_bm25_on_collection(collection_name: str, texts: List[str]):
    """
    在已有 chunk 上拟合 BM25，建立全局词表和 IDF。
    用于后续 transform 单条文本。

    Args:
        collection_name: 集合名（用于隔离词表）
        texts: 所有 chunk 的文本列表
    """
    vectorizer = BM25Vectorizer(collection_name)
    vectorizer.fit(texts)

    with _CACHE_LOCK:
        _COLLECTION_VOCAB[collection_name] = vectorizer.vocab
        _COLLECTION_IDF[collection_name] = vectorizer.idf
        _CACHE_VERSION[collection_name] = _CACHE_VERSION.get(collection_name, 0) + 1

    # 持久化 IDF 到磁盘（供后续启动时加载，实现增量更新）
    _save_bm25_idf(vectorizer.idf)

    logger.info(f"BM25 fitted for collection '{collection_name}': vocab={len(vectorizer.vocab)}, idf_terms={len(vectorizer.idf)}")


def generate_sparse_vector(text: str, collection_name: str = "rag_documents") -> Tuple[List[int], List[float]]:
    """
    生成单条文本的 BM25 稀疏向量。

    Args:
        text: 文本
        collection_name: 集合名（用于隔离词表）

    Returns:
        (indices, values) - 稀疏向量（未 fit 时返回空列表）

    Raises:
        在 collection 未被 fit 时记录 warning 但不崩溃。
    """
    vectorizer = get_bm25_vectorizer(collection_name)
    if not vectorizer.vocab:
        logger.warning(f"generate_sparse_vector called on unfitted collection '{collection_name}'. Returning empty sparse vector.")
        return [], []
    return vectorizer.transform(text)


def generate_sparse_vectors_batch(texts: List[str], collection_name: str = "rag_documents") -> List[Tuple[List[int], List[float]]]:
    """
    批量生成 BM25 稀疏向量。

    在 collection 未被 fit 时记录 warning 但不崩溃。
    """
    vectorizer = get_bm25_vectorizer(collection_name)
    if not vectorizer.vocab:
        logger.warning(f"generate_sparse_vectors_batch called on unfitted collection '{collection_name}'. Returning empty results.")
        return [([], []) for _ in texts]
    return vectorizer.transform_batch(texts)
