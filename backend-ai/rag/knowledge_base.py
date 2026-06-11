import os
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType, Filter, FieldCondition, \
    MatchAny
from sentence_transformers import SentenceTransformer

from agents.pathology_agent import DISEASE_REGISTRY

logger = logging.getLogger(__name__)


class RAGKnowledgeBase:
    """
    知识库检索类。
    负责加载 Embedding 模型，连接 Qdrant 向量数据库，并提供基于多模态上下文的精准检索服务。
    """

    def __init__(self, docs_dir: str = None):
        """
        初始化 RAG 组件。
        加载 bge-small-zh-v1.5 模型，并根据环境变量连接 Qdrant 实例。
        """
        logger.info("Initializing HuggingFace Embedding model (bge-small-zh-v1.5)...")
        self.embedder = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        self.vector_size = self.embedder.get_sentence_embedding_dimension()

        # 环境感知：Docker 环境下使用容器名 'qdrant'，本地开发使用 'localhost'
        qdrant_host = "qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost"
        self.client = QdrantClient(host=qdrant_host, port=6333)

        self.collection_name = "derma_knowledge"
        self.docs_dir = docs_dir

    def init_from_parsed_data(self, texts: list, payloads: list):
        """
        向量化并构建知识库索引（离线初始化用）。

        Args:
            texts: 待入库的文本列表。
            payloads: 对应的元数据列表（必须包含 doc_id 和 tags）。
        """
        if not texts:
            logger.warning("No texts provided for initialization.")
            return

        logger.info(f"Embedding {len(texts)} text fragments and building index...")

        # 创建或重建集合，配置向量维度与距离度量
        self.client.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
        )

        # 创建 Payload 索引以加速过滤查询
        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="tags",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="doc_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # 批量向量化
        vectors = self.embedder.encode(texts, show_progress_bar=True)

        # 构建点集并上传
        points = [
            PointStruct(
                id=idx,
                vector=vectors[idx].tolist(),
                payload={"text": texts[idx], **payloads[idx]}
            )
            for idx in range(len(texts))
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
        logger.info("RAG Knowledge Base built successfully with tag indexes!")

    def _extract_filter_tags(self, clinical_result: dict, pathology_result: dict) -> list:
        """
        动态提取检索过滤标签。

        策略：
        1. 基础标签：通用。
        2. 病种标签：从注册表获取 Code (如 MEL, BCC)。
        3. 部位标签：针对黑色素瘤，识别肢端或黏膜亚型。
        4. 病理标签：根据 T 分期和基因突变状态添加高危/靶向标签。
        """
        filter_tags = ["通用"]

        # 1. 获取病种标签（默认 MEL）
        disease_code = pathology_result.get("disease_type", "MEL") if pathology_result else "MEL"
        if disease_code in DISEASE_REGISTRY:
            filter_tags.append(disease_code)
        else:
            filter_tags.append("MEL")

        # 2. 解析部位特殊标签（仅针对黑色素瘤等特定病种）
        if disease_code == "MEL" and clinical_result and clinical_result.get("lesion_clinical"):
            region = clinical_result.get("lesion_clinical", {}).get("region") or ""
            # 肢端型判定
            if any(kw in region for kw in ["手", "足", "甲"]):
                filter_tags.append("肢端")
            # 黏膜型判定
            if any(kw in region for kw in ["口", "鼻", "唇", "生殖", "黏膜", "粘膜", "肛"]):
                filter_tags.append("黏膜")

        # 3. 解析病理分期与分子特征（仅针对需要分期的病种）
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

            # 分子靶向指征
            if pathology_result.get("braf_mutation") == "突变型":
                filter_tags.append("分子靶向")

        return list(set(filter_tags))

    def _build_multimodal_query(self, image_result: dict, clinical_result: dict, pathology_result: dict) -> str:
        """
        构建多模态语义查询语句。
        利用疾病注册表中的模板，生成符合专科术语习惯的查询文本，提高语义召回准确度。
        """
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

        # 使用注册表定义的模板格式化查询
        template = disease_config.get("rag_template", "{subtype}疾病，病灶位于{region}的诊疗指南")
        query_text = template.format(
            subtype=subtype,
            region=region if region else "未知部位",
            stage=stage
        )

        return query_text

    def retrieve(self, image_result: dict, clinical_result: dict, pathology_result: dict, top_k: int = 3) -> list[str]:
        """
        执行知识检索。

        流程：
        1. 构建语义查询文本。
        2. 提取过滤标签（病种、分期、部位）。
        3. 在 Qdrant 中执行混合检索（向量相似度 + Payload 过滤）。
        4. 返回格式化后的文本片段 [ID] Content。
        """
        query_text = self._build_multimodal_query(image_result, clinical_result, pathology_result)
        logger.info(f"RAG Multimodal Query: {query_text}")

        query_vector = self.embedder.encode(query_text).tolist()
        filter_tags = self._extract_filter_tags(clinical_result, pathology_result)
        logger.info(f"RAG Hard Filter Tags: {filter_tags}")

        # 构建 Filter：匹配任意一个标签 (逻辑 OR)
        query_filter = Filter(
            should=[
                FieldCondition(key="tags", match=MatchAny(any=filter_tags))
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
            # 降级策略：去除过滤器，仅依赖向量检索
            search_response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                score_threshold=0.3,
                with_payload=True
            )

        formatted_results = []
        for hit in search_response.points:
            doc_id = hit.payload.get("doc_id", "UNK-00")
            text = hit.payload.get("text", "")
            formatted_results.append(f"[{doc_id}] {text}")

        logger.info(f"Retrieved {len(formatted_results)} relevant fragments with IDs.")
        return formatted_results

    def init_from_documents(self, docs_dir: str = None):
        """已弃用：请使用离线脚本 init_rag.py 进行数据初始化。"""
        logger.warning("Called deprecated init_from_documents. Please use init_rag.py instead.")
        pass