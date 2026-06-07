# backend-ai/init_rag.py
import os
import re
import logging
from rag.knowledge_base import RAGKnowledgeBase
from agents.pathology_agent import DISEASE_REGISTRY  # 引入疾病注册表

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 🚨 新增：合法标签受控词表 (单一事实来源)
# 结合了你提供的规则和 DISEASE_REGISTRY
VALID_TAGS = set()

# 1. 从注册表自动提取病种 Code
for code in DISEASE_REGISTRY.keys():
    VALID_TAGS.add(code)

# 2. 手动维护的分期、部位、属性标签
VALID_TAGS.update([
    "T1", "T2", "T3", "T4",
    "肢端", "黏膜",
    "病理", "分子靶向", "免疫治疗", "高危", "通用"
])


def parse_documents(docs_dir: str):
    """解析带有强制ID和预打标标签的文档，并对标签进行强校验"""
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

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line: continue

            # 1. 提取强制 ID [前缀-数字]
            id_match = re.match(r'\[([\w-]+)\]', line)
            doc_id = id_match.group(1) if id_match else "UNK-00"

            # 2. 提取预打标标签 {{tags:xxx,yyy}}
            tags_match = re.search(r'\{\{tags:(.*?)\}\}', line)
            raw_tags = [t.strip() for t in tags_match.group(1).split(',')] if tags_match else ["通用"]

            # 🚨 核心增强：标签受控校验与过滤
            validated_tags = []
            for tag in raw_tags:
                if tag in VALID_TAGS:
                    validated_tags.append(tag)
                else:
                    logger.warning(f"文件 {filename} 第 {line_num} 行包含非法标签 '{tag}' (合法词表: {VALID_TAGS})，已自动忽略！")

            # 如果过滤后标签为空，兜底赋予通用标签
            if not validated_tags:
                validated_tags = ["通用"]
                logger.warning(f"文件 {filename} 第 {line_num} 行有效标签为空，已降级赋值 ['通用']")

            # 3. 清洗文本
            clean_text = re.sub(r'\[([\w-]+)\]', '', line)
            clean_text = re.sub(r'\{\{tags:.*?\}\}', '', clean_text).strip()

            all_texts.append(clean_text)
            all_payloads.append({
                "doc_id": doc_id,
                "tags": validated_tags,  # 仅使用校验通过的标签
                "source": filename
            })

    return all_texts, all_payloads


if __name__ == "__main__":
    DOCS_DIR = os.path.join(os.path.dirname(__file__), "rag", "docs")

    logger.info(f"Starting RAG initialization from {DOCS_DIR}...")
    kb = RAGKnowledgeBase(docs_dir=DOCS_DIR)

    texts, payloads = parse_documents(DOCS_DIR)

    if not texts:
        logger.warning("No documents found to initialize.")
    else:
        logger.info(f"Parsed {len(texts)} documents with validated tags. Starting vectorization and upsert...")
        kb.init_from_parsed_data(texts, payloads)
        logger.info("RAG Knowledge Base initialization complete!")