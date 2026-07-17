import os
import logging
from typing import List

logger = logging.getLogger(__name__)

_embedder_instance = None

def get_embedder():
    """单例模式加载 HuggingFace Embedding 模型"""
    global _embedder_instance
    if _embedder_instance is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
            logger.info(f"Loading Embedding model: {model_name}")
            _embedder_instance = SentenceTransformer(model_name)
            logger.info("Embedding model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Embedding model: {e}", exc_info=True)
            raise
    return _embedder_instance

def generate_embeddings(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    """
    生成向量

    Args:
        texts: 文本列表
        batch_size: 批处理大小，控制每批发送的文本数量，避免大文档集内存溢出
    """
    embedder = get_embedder()
    return embedder.encode(texts, batch_size=batch_size, normalize_embeddings=True).tolist()