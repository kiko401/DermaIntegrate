# backend-ai/init_rag.py
import os
import re
import logging
from rag.knowledge_base import RAGKnowledgeBase
from agents.pathology_agent import DISEASE_REGISTRY

logger = logging.getLogger(__name__)

# ==========================================================
# 受控词表配置
# ==========================================================
# 构建单一事实来源的标签集合，用于入库前的严格校验。
# 包含从疾病注册表自动提取的病种代码，以及手动定义的分期/部位标签。
VALID_TAGS = set(DISEASE_REGISTRY.keys())
VALID_TAGS.update([
    "T1", "T2", "T3", "T4",
    "肢端", "黏膜",
    "病理", "分子靶向", "免疫治疗", "高危", "通用"
])


def parse_documents(docs_dir: str):
    """
    解析带 ID 和 Tags 标记的文本文档。

    期望格式：[ID-01] 文本内容 {{tags:TagA,TagB}}

    Args:
        docs_dir: 包含 txt 文件的目录路径。

    Returns:
        tuple: (文本列表, payload 字典列表)
    """
    all_texts = []
    all_payloads = []

    if not os.path.exists(docs_dir):
        logger.error(f"Documents directory not found: {docs_dir}")
        return all_texts, all_payloads

    for filename in sorted(os.listdir(docs_dir)):
        if not filename.endswith(".txt"):
            continue

        filepath = os.path.join(docs_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            # 1. 提取文档 ID (例如: [AJCC-01])
            id_match = re.match(r'\[([\w-]+)\]', line)
            doc_id = id_match.group(1) if id_match else "UNK-00"

            # 2. 提取并校验标签 (例如: {{tags:MEL,通用}})
            tags_match = re.search(r'\{\{tags:(.*?)\}\}', line)
            raw_tags = [t.strip() for t in tags_match.group(1).split(',')] if tags_match else ["通用"]

            # 对照 VALID_TAGS 进行严格过滤
            validated_tags = []
            for tag in raw_tags:
                if tag in VALID_TAGS:
                    validated_tags.append(tag)
                else:
                    logger.warning(f"File {filename}, Line {line_num}: Invalid tag '{tag}'. Ignoring.")

            # 如果标签被完全过滤，回退到 '通用' (General)
            if not validated_tags:
                validated_tags = ["通用"]
                logger.warning(f"File {filename}, Line {line_num}: No valid tags found, fallback to '通用'.")

            # 3. 清洗文本以供向量化（移除 ID 和标签标记）
            clean_text = re.sub(r'\[([\w-]+)\]', '', line)
            clean_text = re.sub(r'\{\{tags:.*?\}\}', '', clean_text).strip()

            all_texts.append(clean_text)
            all_payloads.append({
                "doc_id": doc_id,
                "tags": validated_tags,
                "source": filename
            })

    return all_texts, all_payloads


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 语料目录
    DOCS_DIR = os.path.join(os.path.dirname(__file__), "rag", "docs")

    logger.info(f"Initializing RAG Knowledge Base from {DOCS_DIR}...")
    kb = RAGKnowledgeBase(docs_dir=DOCS_DIR)

    texts, payloads = parse_documents(DOCS_DIR)

    if not texts:
        logger.warning("No documents found. Initialization aborted.")
    else:
        logger.info(f"Parsed {len(texts)} documents. Starting vectorization and upload...")
        kb.init_from_parsed_data(texts, payloads)
        logger.info("RAG Knowledge Base initialization complete!")