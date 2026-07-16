"""
BM25 稀疏向量生成模块

为每个文档生成 BM25 权重向量，用于 Qdrant 混合检索。

BM25 稀疏向量结构：
- indices: 非零维度（token在词表中的位置）的列表
- values: 对应维度的 BM25 得分（归一化到 0~1）
"""
import re
import logging
import math
from typing import List, Dict, Tuple, Optional
from collections import Counter

logger = logging.getLogger(__name__)

# BM25 参数
BM25_K1 = 1.5   # 词频饱和参数
BM25_B = 0.75   # 文档长度归一化参数
AVG_DOC_LEN = 200  # 估算平均文档长度（字符数）

# 全局词表和IDF缓存（按collection隔离）
_COLLECTION_VOCAB: Dict[str, List[str]] = {}
_COLLECTION_IDF: Dict[str, Dict[str, float]] = {}
_CACHE_VERSION: Dict[str, int] = {}  # 用于判断是否需要重建索引


class BM25Vectorizer:
    """单机 BM25 实现，用于生成稀疏向量（不走外部服务）。"""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.vocab: List[str] = []       # 词表 [token -> index]
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
        frequent_tokens = [t for t, c in token_counter.most_common(50000) if c >= 2]
        self.vocab = frequent_tokens

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
            idx = self.vocab.index(token)
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
    """获取或创建 BM25 向量化器（按 collection 隔离）"""
    if collection_name not in _COLLECTION_VOCAB or not _COLLECTION_VOCAB[collection_name]:
        vectorizer = BM25Vectorizer(collection_name)
        _COLLECTION_VOCAB[collection_name] = []
        return vectorizer
    # 从缓存重建（有词表但未fit的情况，仅用于transform）
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

    _COLLECTION_VOCAB[collection_name] = vectorizer.vocab
    _COLLECTION_IDF[collection_name] = vectorizer.idf
    _CACHE_VERSION[collection_name] = _CACHE_VERSION.get(collection_name, 0) + 1

    logger.info(f"BM25 fitted for collection '{collection_name}': vocab={len(vectorizer.vocab)}, idf_terms={len(vectorizer.idf)}")


def generate_sparse_vector(text: str, collection_name: str = "rag_documents") -> Tuple[List[int], List[float]]:
    """
    生成单条文本的 BM25 稀疏向量。

    Args:
        text: 文本
        collection_name: 集合名（用于隔离词表）

    Returns:
        (indices, values) - 稀疏向量
    """
    vectorizer = get_bm25_vectorizer(collection_name)
    return vectorizer.transform(text)


def generate_sparse_vectors_batch(texts: List[str], collection_name: str = "rag_documents") -> List[Tuple[List[int], List[float]]]:
    """批量生成 BM25 稀疏向量"""
    vectorizer = get_bm25_vectorizer(collection_name)
    return vectorizer.transform_batch(texts)
