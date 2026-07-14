import os
import logging
import warnings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType, Filter, FieldCondition, \
    MatchAny

from agents.pathology_agent import DISEASE_REGISTRY
from modules.kb_rag.ingest.embeddings import get_embedder

logger = logging.getLogger(__name__)


class RAGKnowledgeBase:
    """知识库检索类，负责加载 Embedding 模型并连接 Qdrant 向量数据库。"""

    def __init__(self, docs_dir: str = None):
        warnings.warn(
            "RAGKnowledgeBase 将在未来版本移除，请切换至 KB-RAG 模块",
            DeprecationWarning,
            stacklevel=2
        )
        logger.info("Initializing RAG Knowledge Base...")
        self.embedder = get_embedder()
        self.vector_size = self.embedder.get_sentence_embedding_dimension()

        qdrant_host = "qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost"
        self.client = QdrantClient(host=qdrant_host, port=6333)

        self.collection_name = "derma_knowledge"
        self.docs_dir = docs_dir

    def init_from_parsed_data(self, texts: list, payloads: list):
        """向量化并构建知识库索引。"""
        if not texts:
            logger.warning("No texts provided for initialization.")
            return

        logger.info(f"Embedding {len(texts)} text fragments and building index...")

        self.client.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
        )

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

        vectors = self.embedder.encode(texts, show_progress_bar=False)

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
        包括：病种标签（默认 MEL）、部位特殊标签（肢端/黏膜）、病理分期与分子靶向标签。
        """
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
        """
        执行知识检索：构建语义查询 -> 提取过滤标签 -> 向量检索 -> 返回格式化片段。
        """
        query_text = self._build_multimodal_query(image_result, clinical_result, pathology_result)
        logger.info(f"RAG Multimodal Query: {query_text}")

        query_vector = self.embedder.encode(query_text).tolist()
        filter_tags = self._extract_filter_tags(clinical_result, pathology_result)
        logger.info(f"RAG Hard Filter Tags: {filter_tags}")

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
