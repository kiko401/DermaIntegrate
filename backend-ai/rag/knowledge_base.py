import os
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class RAGKnowledgeBase:
    def __init__(self, docs_dir: str = None):
        logger.info("Initializing HuggingFace Embedding model (bge-small-zh-v1.5)...")
        # 加载本地向量化模型
        self.embedder = SentenceTransformer('BAAI/bge-small-zh-v1.5')

        # 使用 Qdrant 内存模式，无需启动 Docker，非常适合当前开发测试
        self.client = QdrantClient(":memory:")
        self.collection_name = "derma_knowledge"
        self.docs_dir = docs_dir

    def init_from_documents(self, docs_dir: str = None):
        """读取文档，按段落切分，向量化并存入 Qdrant"""
        target_dir = docs_dir or self.docs_dir
        if not target_dir or not os.path.exists(target_dir):
            logger.warning(f"Docs directory not found: {target_dir}")
            return

        # 1. 简单读取所有 txt 文件
        texts = []
        for filename in os.listdir(target_dir):
            if filename.endswith(".txt"):
                with open(os.path.join(target_dir, filename), "r", encoding="utf-8") as f:
                    # 按空行或换行简单切分段落
                    for line in f.readlines():
                        line = line.strip()
                        if line:  # 忽略空行
                            texts.append(line)

        if not texts:
            logger.warning("No valid text found in the directory.")
            return

        logger.info(f"Loaded {len(texts)} text fragments. Embedding and building index...")

        # 2. 向量化文本
        vectors = self.embedder.encode(texts)

        # 3. 创建 Qdrant 集合
        self.client.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE),
        )

        # 4. 批量插入数据
        points = [
            PointStruct(id=idx, vector=vectors[idx].tolist(), payload={"text": texts[idx]})
            for idx in range(len(texts))
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
        logger.info("RAG Knowledge Base built successfully!")

    def retrieve(self, query_text: str, top_k: int = 2) -> list[str]:
        """基于查询文本召回相关文献片段"""
        logger.info(f"Retrieving for query: {query_text}")
        query_vector = self.embedder.encode(query_text).tolist()

        # 执行向量搜索 (适配 qdrant-client 1.18.0+ 新版 API)
        search_response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            score_threshold=0.3  # 基础相似度阈值
        )

        # query_points 返回的是 QueryResponse 对象，需要取 .points 属性
        results = [hit.payload["text"] for hit in search_response.points]
        logger.info(f"Retrieved {len(results)} relevant fragments.")
        return results