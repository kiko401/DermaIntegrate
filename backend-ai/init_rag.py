import os
import re
import logging
from rag.knowledge_base import RAGKnowledgeBase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def parse_documents(docs_dir: str):
    """解析带有强制ID(支持前缀-数字)和预打标标签的文档"""
    all_texts = []
    all_payloads = []

    if not os.path.exists(docs_dir):
        logger.error(f"Docs directory not found: {docs_dir}")
        return all_texts, all_payloads

    for filename in sorted(os.listdir(docs_dir)):
        if not filename.endswith(".txt"):
            continue

        filepath = os.path.join(docs_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line: continue

            # 1. 提取强制 ID [前缀-数字] (如 [WHW-01], [AJCC-02])
            # 正则修改：匹配字母/下划线 + 可选连字符 + 数字
            id_match = re.match(r'\[([\w-]+)\]', line)
            doc_id = id_match.group(1) if id_match else "UNK-00"

            # 2. 提取预打标标签 {{tags:xxx,yyy}}
            tags_match = re.search(r'\{\{tags:(.*?)\}\}', line)
            tags = [t.strip() for t in tags_match.group(1).split(',')] if tags_match else ["通用"]

            # 3. 清洗文本：移除 ID 前缀和末尾标签（保留纯净正文供向量化）
            clean_text = re.sub(r'\[([\w-]+)\]', '', line)  # 新增：移除开头的 [WHW-01] 等 ID
            clean_text = re.sub(r'\{\{tags:.*?\}\}', '', clean_text).strip()  # 移除末尾标签

            all_texts.append(clean_text)
            all_payloads.append({
                "doc_id": doc_id,
                "tags": tags,
                "source": filename
            })

    return all_texts, all_payloads


if __name__ == "__main__":
    # 默认从 rag/docs 读取
    DOCS_DIR = os.path.join(os.path.dirname(__file__), "rag", "docs")

    logger.info(f"Starting RAG initialization from {DOCS_DIR}...")
    kb = RAGKnowledgeBase(docs_dir=DOCS_DIR)

    texts, payloads = parse_documents(DOCS_DIR)

    if not texts:
        logger.warning("No documents found to initialize.")
    else:
        logger.info(f"Parsed {len(texts)} documents. Starting vectorization and upsert...")
        # 调用新的批量初始化方法
        kb.init_from_parsed_data(texts, payloads)
        logger.info("RAG Knowledge Base initialization complete!")