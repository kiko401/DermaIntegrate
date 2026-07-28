"""
BM25 稀疏向量生成模块（增量版）

核心改进：
- fit() 全量拟合：首次建库或主动触发全量重建时使用
- fit_incremental() 增量更新：新文档入库时只更新增量部分，不全量重算
- IDF 持久化到本地文件，启动时自动加载

BM25 稀疏向量结构：
- indices: 非零维度（token在词表中的位置）的列表
- values: 对应维度的 BM25 得分（归一化到 0~1）
"""
import os
import json
import logging
import math
import threading
from typing import List, Dict, Tuple, Optional, Set
from collections import Counter

from shared.constants import BM25_K1, BM25_B, AVG_DOC_LEN

logger = logging.getLogger(__name__)

# ===== 文件路径 =====

_IDF_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "bm25_idf.json")
_TOKEN_DOC_COUNT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "bm25_token_doc_counts.json")
_DOC_COUNT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "bm25_doc_count.json")


# ===== 全局缓存（线程安全）=====

_CACHE_VERSION: Dict[str, int] = {}
_COLLECTION_VOCAB: Dict[str, Dict[str, int]] = {}          # {collection: {token: vocab_index}}
_COLLECTION_IDF: Dict[str, Dict[str, float]] = {}         # {collection: {token: idf_value}}
_COLLECTION_TOKEN_DOC_COUNTS: Dict[str, Dict[str, int]] = {}  # {collection: {token: doc_freq}}
_COLLECTION_DOC_COUNT: Dict[str, int] = {}                  # {collection: total_doc_count}
_CACHE_LOCK = threading.RLock()


# ===== 持久化 =====

def _load_json(path: str, default: dict | int) -> dict | int:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")
    return default


def _save_json(path: str, data: dict | int):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save {path}: {e}")


def _load_cached_state(collection_name: str):
    """从磁盘加载已持久化的 BM25 状态（启动时调用）"""
    with _CACHE_LOCK:
        vocab = _load_json(_IDF_PATH, {})  # 共享 IDF 文件（多 collection 合并存储）
        token_doc_counts = _load_json(_TOKEN_DOC_COUNT_PATH, {})
        doc_count = _load_json(_DOC_COUNT_PATH, 0)

        _COLLECTION_IDF[collection_name] = vocab.get(collection_name, {})
        _COLLECTION_TOKEN_DOC_COUNTS[collection_name] = token_doc_counts.get(collection_name, {})
        _COLLECTION_DOC_COUNT[collection_name] = doc_count

        # 重建 vocab（从 token -> index 的映射）
        _COLLECTION_VOCAB[collection_name] = {
            token: idx for idx, token in enumerate(_COLLECTION_IDF[collection_name].keys())
        }

        logger.info(
            f"BM25 state loaded for '{collection_name}': "
            f"vocab={len(_COLLECTION_VOCAB[collection_name])}, "
            f"doc_count={_COLLECTION_DOC_COUNT[collection_name]}"
        )


def _persist_state(collection_name: str):
    """将当前 BM25 状态持久化到磁盘"""
    # 合并持久化（多 collection 共用文件）
    all_idf: Dict[str, Dict[str, float]] = {}
    all_token_counts: Dict[str, Dict[str, int]] = {}
    all_doc_counts: Dict[str, int] = {}

    # 读取现有数据
    existing_idf = _load_json(_IDF_PATH, {})
    existing_token_counts = _load_json(_TOKEN_DOC_COUNT_PATH, {})
    existing_doc_counts = _load_json(_DOC_COUNT_PATH, {})

    if isinstance(existing_idf, dict):
        all_idf = existing_idf
    if isinstance(existing_token_counts, dict):
        all_token_counts = existing_token_counts
    if isinstance(existing_doc_counts, dict):
        all_doc_counts = existing_doc_counts

    # 更新当前 collection
    all_idf[collection_name] = _COLLECTION_IDF.get(collection_name, {})
    all_token_counts[collection_name] = _COLLECTION_TOKEN_DOC_COUNTS.get(collection_name, {})
    all_doc_counts[collection_name] = _COLLECTION_DOC_COUNT.get(collection_name, 0)

    _save_json(_IDF_PATH, all_idf)
    _save_json(_TOKEN_DOC_COUNT_PATH, all_token_counts)
    _save_json(_DOC_COUNT_PATH, all_doc_counts)


# ===== BM25 向量化器 =====

class BM25Vectorizer:
    """单机 BM25 向量化器"""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.vocab: Dict[str, int] = {}        # {token: vocab_index}
        self.idf: Dict[str, float] = {}        # {token: idf_value}
        self.token_doc_counts: Dict[str, int] = {}  # {token: doc_freq}
        self.doc_count = 0

    def _tokenize(self, text: str) -> List[str]:
        from ..utils import tokenize as _shared_tokenize
        return _shared_tokenize(text)

    def _compute_idf(self, token_to_docs: Dict[str, int], total_docs: int) -> Dict[str, float]:
        """计算所有 token 的 IDF（log 公式，IDF >= 0）"""
        idf = {}
        for token, doc_freq in token_to_docs.items():
            idf[token] = max(
                math.log((total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1),
                0.0
            )
        return idf

    def fit(self, texts: List[str]) -> "BM25Vectorizer":
        """全量拟合：首次建库或主动全量重建时使用"""
        self.doc_count = len(texts)
        token_doc_counts: Counter = Counter()

        for text in texts:
            unique_tokens = set(self._tokenize(text))
            token_doc_counts.update(unique_tokens)

        self.token_doc_counts = dict(token_doc_counts)

        # 词表：出现次数 >= 2 的高频词
        frequent_tokens = [t for t, c in token_doc_counts.most_common(50000) if c >= 2]
        self.vocab = {t: i for i, t in enumerate(frequent_tokens)}

        # 全量计算 IDF
        self.idf = self._compute_idf(self.token_doc_counts, self.doc_count)

        logger.info(f"BM25 fit: vocab={len(self.vocab)}, docs={self.doc_count}")
        return self

    def fit_incremental(self, new_texts: List[str]) -> "BM25Vectorizer":
        """
        增量更新：新文档入库时调用，只更新增量部分。

        算法：
        1. 遍历新文档，统计每个 token 出现在多少个新文档中（新增 doc_freq）
        2. 将增量 doc_freq 合并到全局 token_doc_counts
        3. 更新总 doc_count
        4. 用新 N 重新计算所有 token 的 IDF（增量词直接加到词表）
        """
        if not new_texts:
            return self

        # 已有状态
        existing_doc_count = self.doc_count
        existing_token_doc_counts = self.token_doc_counts.copy()
        existing_vocab = set(self.vocab.keys())

        # 统计新文档中每个 token 的 doc_freq
        new_token_doc_counts: Counter = Counter()
        for text in new_texts:
            unique_tokens = set(self._tokenize(text))
            new_token_doc_counts.update(unique_tokens)

        new_doc_count = len(new_texts)
        total_doc_count = existing_doc_count + new_doc_count

        # 合并 doc_freq（只加不覆盖）
        for token, count in new_token_doc_counts.items():
            existing_token_doc_counts[token] = existing_token_doc_counts.get(token, 0) + count

        # 更新词表：加入新词（即使出现次数少也加入，支持增量场景）
        for token in new_token_doc_counts:
            if token not in existing_vocab:
                new_idx = len(self.vocab)
                self.vocab[token] = new_idx

        # 用新 doc_count 重新计算所有 token 的 IDF
        self.idf = self._compute_idf(existing_token_doc_counts, total_doc_count)
        self.token_doc_counts = existing_token_doc_counts
        self.doc_count = total_doc_count

        logger.info(
            f"BM25 incremental fit: new_docs={new_doc_count}, "
            f"total_docs={total_doc_count}, "
            f"new_tokens={len(new_token_doc_counts)}, "
            f"total_vocab={len(self.vocab)}"
        )
        return self

    def transform(self, text: str) -> Tuple[List[int], List[float]]:
        """将单条文本转换为稀疏向量（BM25 权重）"""
        if not self.vocab:
            return [], []

        tokens = self._tokenize(text)
        token_freq = Counter(tokens)
        doc_len = len(tokens) or 1

        indices = []
        values = []

        for token in set(tokens):
            if token not in self.vocab:
                continue
            idx = self.vocab[token]
            tf = token_freq[token]
            idf = self.idf.get(token, 0.0)
            bm25_score = idf * (tf * (BM25_K1 + 1)) / (
                tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / AVG_DOC_LEN)
            )
            indices.append(idx)
            values.append(bm25_score)

        if values:
            max_val = max(values)
            if max_val > 0:
                values = [v / max_val for v in values]

        sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
        indices, values = zip(*sorted_pairs) if sorted_pairs else ([], [])
        return list(indices), list(values)

    def transform_batch(self, texts: List[str]) -> List[Tuple[List[int], List[float]]]:
        return [self.transform(t) for t in texts]


# ===== 全局缓存访问 =====

def _ensure_collection_loaded(collection_name: str):
    """惰性加载：如果缓存为空，从磁盘加载"""
    with _CACHE_LOCK:
        if collection_name not in _COLLECTION_VOCAB:
            _load_cached_state(collection_name)
        if collection_name not in _COLLECTION_VOCAB:
            _COLLECTION_VOCAB[collection_name] = {}
        if collection_name not in _COLLECTION_IDF:
            _COLLECTION_IDF[collection_name] = {}
        if collection_name not in _COLLECTION_TOKEN_DOC_COUNTS:
            _COLLECTION_TOKEN_DOC_COUNTS[collection_name] = {}
        if collection_name not in _COLLECTION_DOC_COUNT:
            _COLLECTION_DOC_COUNT[collection_name] = 0


def get_bm25_vectorizer(collection_name: str) -> BM25Vectorizer:
    """获取已拟合的 BM25 向量化器（按 collection 隔离）"""
    _ensure_collection_loaded(collection_name)
    with _CACHE_LOCK:
        vectorizer = BM25Vectorizer(collection_name)
        vectorizer.vocab = _COLLECTION_VOCAB[collection_name]
        vectorizer.idf = _COLLECTION_IDF[collection_name]
        vectorizer.token_doc_counts = _COLLECTION_TOKEN_DOC_COUNTS[collection_name]
        vectorizer.doc_count = _COLLECTION_DOC_COUNT[collection_name]
        return vectorizer


def fit_bm25_on_collection(collection_name: str, texts: List[str]):
    """
    全量拟合：首次建库或主动全量重建时使用。
    会重建词表、全局 IDF、全量 token doc counts。
    """
    vectorizer = BM25Vectorizer(collection_name)
    vectorizer.fit(texts)

    with _CACHE_LOCK:
        _COLLECTION_VOCAB[collection_name] = vectorizer.vocab
        _COLLECTION_IDF[collection_name] = vectorizer.idf
        _COLLECTION_TOKEN_DOC_COUNTS[collection_name] = vectorizer.token_doc_counts
        _COLLECTION_DOC_COUNT[collection_name] = vectorizer.doc_count
        _CACHE_VERSION[collection_name] = _CACHE_VERSION.get(collection_name, 0) + 1

    _persist_state(collection_name)
    logger.info(
        f"BM25 full fit done for '{collection_name}': "
        f"vocab={len(vectorizer.vocab)}, docs={vectorizer.doc_count}"
    )


def fit_bm25_incremental(collection_name: str, new_texts: List[str]):
    """
    增量更新：新文档入库时调用。

    - 不重建词表（只扩展）
    - 不全量重算 IDF（只更新受影响的词）
    - 持久化增量状态到磁盘
    """
    _ensure_collection_loaded(collection_name)

    with _CACHE_LOCK:
        current_vocab = _COLLECTION_VOCAB[collection_name]
        current_idf = _COLLECTION_IDF[collection_name]
        current_token_doc_counts = _COLLECTION_TOKEN_DOC_COUNTS[collection_name]
        current_doc_count = _COLLECTION_DOC_COUNT[collection_name]

        # 构建当前向量化器
        vectorizer = BM25Vectorizer(collection_name)
        vectorizer.vocab = current_vocab
        vectorizer.idf = current_idf
        vectorizer.token_doc_counts = current_token_doc_counts
        vectorizer.doc_count = current_doc_count

        # 增量更新
        vectorizer.fit_incremental(new_texts)

        # 写回缓存
        _COLLECTION_VOCAB[collection_name] = vectorizer.vocab
        _COLLECTION_IDF[collection_name] = vectorizer.idf
        _COLLECTION_TOKEN_DOC_COUNTS[collection_name] = vectorizer.token_doc_counts
        _COLLECTION_DOC_COUNT[collection_name] = vectorizer.doc_count
        _CACHE_VERSION[collection_name] = _CACHE_VERSION.get(collection_name, 0) + 1

    _persist_state(collection_name)


def generate_sparse_vector(text: str, collection_name: str = "rag_documents") -> Tuple[List[int], List[float]]:
    """生成单条文本的 BM25 稀疏向量"""
    vectorizer = get_bm25_vectorizer(collection_name)
    if not vectorizer.vocab:
        logger.warning(f"generate_sparse_vector called on unfitted collection '{collection_name}'. Returning empty.")
        return [], []
    return vectorizer.transform(text)


def generate_sparse_vectors_batch(
    texts: List[str],
    collection_name: str = "rag_documents"
) -> List[Tuple[List[int], List[float]]]:
    """批量生成 BM25 稀疏向量"""
    vectorizer = get_bm25_vectorizer(collection_name)
    if not vectorizer.vocab:
        logger.warning(f"generate_sparse_vectors_batch called on unfitted collection '{collection_name}'. Returning empty.")
        return [([], []) for _ in texts]
    return vectorizer.transform_batch(texts)


def get_collection_doc_count(collection_name: str) -> int:
    """获取 collection 已入库的文档总数（用于判断是否需要先全量拟合）"""
    _ensure_collection_loaded(collection_name)
    with _CACHE_LOCK:
        return _COLLECTION_DOC_COUNT.get(collection_name, 0)
