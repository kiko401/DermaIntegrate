"""
RAG Knowledge Base - 文档初始化模块

提供从本地文档目录自动初始化知识库的能力。
支持两种使用方式：
1. API 调用：POST /rag/init/from-docs
2. 程序调用：RAGKnowledgeBase.init_from_documents()

文档格式：
- 文件名：{文档类型}_{版本}.txt，如 AJCC_8th.txt
- 每行格式：[ID] 文本内容 {{tags:tag1,tag2,...}}
- ID格式：如 AJCC-01、NCCN-01 等

Tags 有效值：MEL、BCC、SCC、NEV、ACK、SEK、T1、T2、T3、T4、高危、肢端、黏膜、通用
"""

import os
import re
import logging
from typing import List, Dict, Tuple, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models

from modules.kb_rag.ingest.embeddings import get_embedder

logger = logging.getLogger(__name__)

# 有效 tags 白名单
VALID_TAGS = {"MEL", "BCC", "SCC", "NEV", "ACK", "SEK", "T1", "T2", "T3", "T4", "高危", "肢端", "黏膜", "通用"}

# 文档目录
DEFAULT_DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")

# KB-RAG 使用的 collection 名称（与 modules/kb_rag/ingest/vector_store.py 保持一致）
COLLECTION_NAME = "rag_documents"


class RAGKnowledgeBase:
    """知识库检索类，负责加载 Embedding 模型并连接 Qdrant 向量数据库。"""

    def __init__(self, docs_dir: str = None):
        logger.info("Initializing RAG Knowledge Base...")
        self.embedder = get_embedder()
        self.vector_size = self.embedder.get_sentence_embedding_dimension()

        qdrant_host = "qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost"
        port = int(os.getenv("QDRANT_PORT", "6333"))
        self.client = QdrantClient(host=qdrant_host, port=port)

        self.collection_name = COLLECTION_NAME
        self.docs_dir = docs_dir or DEFAULT_DOCS_DIR

    def _ensure_collection_exists(self):
        """确保 collection 存在，不存在则创建"""
        collections = self.client.get_collections().collections
        if not any(c.name == self.collection_name for c in collections):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE)
            )
            # 创建 payload 索引
            self.client.create_payload_index(self.collection_name, "kb_id", models.PayloadSchemaType.INTEGER)
            self.client.create_payload_index(self.collection_name, "doc_id", models.PayloadSchemaType.INTEGER)
            self.client.create_payload_index(self.collection_name, "doc_version_id", models.PayloadSchemaType.INTEGER)
            logger.info(f"Collection '{self.collection_name}' created with payload indexes.")

    def _parse_documents(self, docs_dir: str) -> Tuple[List[str], List[Dict]]:
        """
        解析文档目录中的所有文档。

        Returns:
            (texts, payloads) - 文本列表和元数据列表
        """
        all_texts = []
        all_payloads = []

        if not os.path.exists(docs_dir):
            logger.error(f"文档目录不存在: {docs_dir}")
            return [], []

        for filename in os.listdir(docs_dir):
            if not filename.endswith(".txt"):
                continue

            filepath = os.path.join(docs_dir, filename)
            logger.info(f"正在解析文档: {filename}")

            # 从文件名提取 doc_id 和 kb_id
            # 约定：文件名格式为 {type}_{id}.txt 或 {type}{id}.txt
            file_basename = os.path.splitext(filename)[0]

            # 解析文件名获取文档编码（如 AJCC_8th -> AJCC, NCCN_2024 -> NCCN）
            doc_code = re.sub(r'_\d+.*$', '', file_basename)  # 去掉版本号后缀

            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue

                # 提取文档 ID：[AJCC-01] 格式
                id_match = re.match(r'\[([\w-]+)\]', line)
                doc_id_str = id_match.group(1) if id_match else f"{doc_code}-{line_num:03d}"

                # 提取 tags：{{tags:MEL,通用}}
                tags_match = re.search(r'\{\{tags:(.*?)\}\}', line)
                raw_tags = tags_match.group(1).split(',') if tags_match else ["通用"]
                validated_tags = [t.strip() for t in raw_tags if t.strip() in VALID_TAGS] or ["通用"]

                # 清洗文本中的标记
                clean_text = re.sub(r'\[\w+-\d+\]', '', line)  # 去掉 [ID]
                clean_text = re.sub(r'\{\{tags:.*?\}\}', '', clean_text).strip()

                if clean_text:
                    all_texts.append(clean_text)
                    all_payloads.append({
                        "doc_id": hash(doc_id_str) % (2**31),  # 稳定的数字 ID
                        "doc_code": doc_code,
                        "doc_id_str": doc_id_str,
                        "kb_id": 0,  # 0 表示默认知识库
                        "doc_version_id": 1,
                        "chunk_id": f"{doc_id_str}_001",
                        "text": clean_text,
                        "tags": validated_tags,
                        "source_file": filename,
                        "source_line": line_num + 1
                    })

        logger.info(f"从 {docs_dir} 解析出 {len(all_texts)} 条文档记录")
        return all_texts, all_payloads

    def init_from_documents(self, docs_dir: str = None, recreate: bool = False) -> Dict:
        """
        从本地文档目录初始化知识库。

        Args:
            docs_dir: 文档目录路径，默认为 rag/docs/
            recreate: 是否重建 collection（清空现有数据）

        Returns:
            初始化结果统计
        """
        docs_dir = docs_dir or self.docs_dir

        logger.info(f"开始从文档初始化知识库: {docs_dir}")

        # 1. 确保 collection 存在
        self._ensure_collection_exists()

        # 2. 如果需要重建，先清空 collection
        if recreate:
            try:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(must=[])
                    )
                )
                logger.info(f"已清空 collection '{self.collection_name}'")
            except Exception as e:
                logger.warning(f"清空 collection 失败: {e}")

        # 3. 解析文档
        texts, payloads = self._parse_documents(docs_dir)
        if not texts:
            logger.warning("未找到任何文档，知识库初始化取消")
            return {"status": "skipped", "message": "未找到文档", "count": 0}

        # 4. 向量化
        logger.info(f"正在向量化 {len(texts)} 条文档...")
        vectors = self.embedder.encode(texts, normalize_embeddings=True).tolist()

        # 5. 构建 points
        points = [
            models.PointStruct(
                id=payloads[i]["doc_id"],
                vector=vectors[i],
                payload=payloads[i]
            )
            for i in range(len(texts))
        ]

        # 6. 写入向量数据库
        self.client.upsert(collection_name=self.collection_name, points=points)

        result = {
            "status": "succeeded",
            "collection": self.collection_name,
            "docs_dir": docs_dir,
            "count": len(texts),
            "tags": list(VALID_TAGS)
        }
        logger.info(f"知识库初始化完成: {result}")
        return result

    def check_initialized(self) -> bool:
        """检查知识库是否已初始化（有数据）"""
        try:
            result = self.client.get_collection(collection_name=self.collection_name)
            return result.points_count > 0
        except Exception:
            return False

    def init_from_parsed_data(self, texts: list, payloads: list):
        """向量化并构建知识库索引（兼容旧接口）。"""
        if not texts:
            logger.warning("No texts provided for initialization.")
            return

        logger.info(f"Embedding {len(texts)} text fragments and building index...")

        self._ensure_collection_exists()

        vectors = self.embedder.encode(texts, show_progress_bar=False)

        points = [
            models.PointStruct(
                id=idx,
                vector=vectors[idx].tolist(),
                payload={"text": texts[idx], **payloads[idx]}
            )
            for idx in range(len(texts))
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
        logger.info("RAG Knowledge Base built successfully!")

    def _extract_filter_tags(self, clinical_result: dict, pathology_result: dict) -> list:
        """动态提取检索过滤标签。"""
        from agents.pathology_agent import DISEASE_REGISTRY

        filter_tags = ["通用"]

        disease_code = pathology_result.get("disease_type", "MEL") if pathology_result else "MEL"
        if disease_code in DISEASE_REGISTRY:
            filter_tags.append(disease_code)
        else:
            filter_tags.append("MEL")

        if disease_code == "MEL" and clinical_result and clinical_result.get("lesion_clinical"):
            region = clinical_result.get("lesion_clinical", {}).get("region") or ""
            if any(kw in region for kw in ["手", "足", "甲"]):
                filter_tags.append("肢端")
            if any(kw in region for kw in ["口", "鼻", "唇", "生殖", "黏膜", "粘膜", "肛"]):
                filter_tags.append("黏膜")

        if pathology_result and DISEASE_REGISTRY.get(disease_code, {}).get("needs_staging", False):
            t_stage = pathology_result.get("t_stage", "")
            if "T1" in t_stage:
                filter_tags.extend(["T1", "病理"])
            elif "T2" in t_stage:
                filter_tags.extend(["T2", "病理"])
            elif "T3" in t_stage:
                filter_tags.extend(["T3", "病理", "高危"])
            elif "T4" in t_stage:
                filter_tags.extend(["T4", "病理", "高危"])
            elif "无法分期" in t_stage or "未提供" in t_stage:
                filter_tags.append("病理")

            if pathology_result.get("braf_mutation") == "突变型":
                filter_tags.append("分子靶向")

        return list(set(filter_tags))

    def _build_multimodal_query(self, image_result: dict, clinical_result: dict, pathology_result: dict) -> str:
        """利用疾病注册表中的模板构建多模态语义查询语句。"""
        from agents.pathology_agent import DISEASE_REGISTRY

        disease_code = pathology_result.get("disease_type", "MEL") if pathology_result else "MEL"
        disease_config = DISEASE_REGISTRY.get(disease_code, DISEASE_REGISTRY["MEL"])

        region = ""
        if clinical_result and clinical_result.get("lesion_clinical"):
            region = clinical_result.get("lesion_clinical", {}).get("region") or ""

        subtype = ""
        if disease_code == "MEL":
            if any(kw in region for kw in ["手", "足", "甲"]):
                subtype = "肢端型"
            elif any(kw in region for kw in ["口", "鼻", "唇", "生殖", "黏膜", "粘膜", "肛"]):
                subtype = "黏膜型"

        stage = pathology_result.get("t_stage", "未知") if pathology_result else "未知"

        template = disease_config.get("rag_template", "{subtype}疾病，病灶位于{region}的诊疗指南")
        query_text = template.format(
            subtype=subtype,
            region=region if region else "未知部位",
            stage=stage
        )

        return query_text

    def retrieve(self, image_result: dict, clinical_result: dict, pathology_result: dict, top_k: int = 3) -> list[str]:
        """执行知识检索：构建语义查询 -> 提取过滤标签 -> 向量检索 -> 返回格式化片段。"""
        query_text = self._build_multimodal_query(image_result, clinical_result, pathology_result)
        logger.info(f"RAG Multimodal Query: {query_text}")

        query_vector = self.embedder.encode(query_text).tolist()
        filter_tags = self._extract_filter_tags(clinical_result, pathology_result)
        logger.info(f"RAG Hard Filter Tags: {filter_tags}")

        query_filter = models.Filter(
            should=[
                models.FieldCondition(key="tags", match=models.MatchAny(any=filter_tags))
            ]
        )

        try:
            search_response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                score_threshold=0.3,
                with_payload=True
            )
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}. Attempting fallback search without filter.")
            search_response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                score_threshold=0.3,
                with_payload=True
            )

        formatted_results = []
        for hit in search_response.points:
            doc_id = hit.payload.get("doc_id_str", hit.payload.get("doc_id", "UNK-00"))
            text = hit.payload.get("text", "")
            formatted_results.append(f"[{doc_id}] {text}")

        logger.info(f"Retrieved {len(formatted_results)} relevant fragments with IDs.")
        return formatted_results


# ============ 独立的初始化函数 ============

def init_knowledge_base(docs_dir: str = None, recreate: bool = False) -> Dict:
    """
    独立的知识库初始化函数。

    Args:
        docs_dir: 文档目录路径
        recreate: 是否重建 collection

    Returns:
        初始化结果统计
    """
    kb = RAGKnowledgeBase(docs_dir=docs_dir)
    return kb.init_from_documents(docs_dir=docs_dir, recreate=recreate)


def check_knowledge_base_status() -> Dict:
    """
    检查知识库状态。

    Returns:
        状态信息
    """
    kb = RAGKnowledgeBase()
    is_init = kb.check_initialized()

    status = {
        "collection": COLLECTION_NAME,
        "initialized": is_init,
        "docs_dir": DEFAULT_DOCS_DIR
    }

    if is_init:
        try:
            result = kb.client.get_collection(collection_name=COLLECTION_NAME)
            status["points_count"] = result.points_count
        except Exception as e:
            status["error"] = str(e)
    else:
        status["message"] = "知识库未初始化，请调用 init_knowledge_base() 或 POST /rag/init/from-docs"

    return status
