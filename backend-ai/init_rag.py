import os
import re
import logging
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置路径与常量
DOCS_DIR = os.path.join(os.path.dirname(__file__), "rag", "docs")
COLLECTION_NAME = "derma_knowledge"
VALID_TAGS = ["MEL", "BCC", "SCC", "NEV", "ACK", "SEK", "T1", "T2", "T3", "T4", "高危", "肢端", "黏膜", "通用"]


def parse_documents(docs_dir: str):
    """解析带有 [ID] 和 {{tags}} 标记的文本文档。"""
    all_texts = []
    all_payloads = []

    if not os.path.exists(docs_dir):
        logger.error(f"文档目录不存在: {docs_dir}")
        return all_texts, all_payloads

    for filename in os.listdir(docs_dir):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(docs_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 提取文档 ID
            id_match = re.match(r'\[([\w-]+)\]', line)
            doc_id = id_match.group(1) if id_match else "UNK-00"

            # 提取并校验标签
            tags_match = re.search(r'\{\{tags:(.*?)\}\}', line)
            raw_tags = tags_match.group(1).split(',') if tags_match else ["通用"]
            validated_tags = [t.strip() for t in raw_tags if t.strip() in VALID_TAGS] or ["通用"]

            # 清洗文本中的标签标记
            clean_text = re.sub(r'\[([\w-]+)\]', '', line)
            clean_text = re.sub(r'\{\{tags:.*?\}\}', '', clean_text).strip()

            if clean_text:
                all_texts.append(clean_text)
                all_payloads.append({"doc_id": doc_id, "tags": validated_tags, "source": filename})

    return all_texts, all_payloads


if __name__ == "__main__":
    logger.info(f"正在从 {DOCS_DIR} 初始化 RAG 知识库...")

    # 第一步：解析本地文档
    texts, payloads = parse_documents(DOCS_DIR)
    if not texts:
        logger.error("未找到任何文档！请检查 rag/docs 目录下是否有 txt 文件。")
        exit(1)

    # 第二步：初始化模型和客户端（独立于 FastAPI 运行）
    is_docker = os.getenv("DOCKER_ENV", "false").lower() == "true"
    qdrant_host = "qdrant" if is_docker else "localhost"
    qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))

    logger.info("正在加载 Embedding 模型 (BAAI/bge-small-zh-v1.5)...")
    embedder = SentenceTransformer("BAAI/bge-small-zh-v1.5")

    logger.info(f"正在连接 Qdrant {qdrant_host}:{qdrant_port}...")
    client = QdrantClient(host=qdrant_host, port=qdrant_port)

    # 第三步：创建 Collection（如不存在）
    collections = client.get_collections().collections
    if not any(c.name == COLLECTION_NAME for c in collections):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE)
        )
        # 为主链路 RAG 创建索引
        client.create_payload_index(COLLECTION_NAME, "tags", models.PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION_NAME, "doc_id", models.PayloadSchemaType.KEYWORD)
        logger.info(f"Collection '{COLLECTION_NAME}' 创建成功。")
    else:
        logger.info(f"Collection '{COLLECTION_NAME}' 已存在，数据将追加写入。")

    # 第四步：向量化并写入向量数据库
    logger.info(f"正在向量化 {len(texts)} 个文本片段...")
    vectors = embedder.encode(texts, normalize_embeddings=True).tolist()

    points = [
        models.PointStruct(
            id=hash(payloads[i]["doc_id"] + str(i)) % (2 ** 63),  # 生成稳定的数字 ID
            vector=vectors[i],
            payload=payloads[i]
        ) for i in range(len(texts))
    ]

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info(f"成功写入 {len(texts)} 个片段至 '{COLLECTION_NAME}' Collection。")