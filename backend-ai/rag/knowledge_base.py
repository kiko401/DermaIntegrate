import os
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType, Filter, FieldCondition, \
    MatchAny
from sentence_transformers import SentenceTransformer

# 导入统一疾病注册表
from agents.pathology_agent import DISEASE_REGISTRY

logger = logging.getLogger(__name__)


class RAGKnowledgeBase:
    def __init__(self, docs_dir: str = None):
        logger.info("Initializing HuggingFace Embedding model (bge-small-zh-v1.5)...")
        self.embedder = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        self.vector_size = self.embedder.get_sentence_embedding_dimension()

        qdrant_host = "qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost"
        self.client = QdrantClient(host=qdrant_host, port=6333)

        self.collection_name = "derma_knowledge"
        self.docs_dir = docs_dir

    def init_from_parsed_data(self, texts: list, payloads: list):
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

        vectors = self.embedder.encode(texts, show_progress_bar=True)

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
        核心映射逻辑：基于疾病注册表动态提取硬匹配标签
        """
        filter_tags = ["通用"]

        # 1. 病种主标签 (读取注册表内部的英文Code作为精准匹配标签)
        disease_code = pathology_result.get("disease_type", "MEL") if pathology_result else "MEL"
        if disease_code in DISEASE_REGISTRY:
            filter_tags.append(disease_code)
        else:
            filter_tags.append("MEL")

        # 2. 部位映射 (仅对MEL等需要亚型区分的病种启用)
        if disease_code == "MEL" and clinical_result and clinical_result.get("lesion_clinical"):
            region = clinical_result.get("lesion_clinical", {}).get("region") or ""
            if any(kw in region for kw in ["手", "足", "甲"]):
                filter_tags.append("肢端")
            if any(kw in region for kw in ["口", "鼻", "唇", "生殖", "黏膜", "粘膜", "肛"]):
                filter_tags.append("黏膜")

        # 3. 病理分期与分子标签 (仅对需要分期的病种生效)
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
        """
        构造多模态复合查询：基于疾病注册表的纯中文模板化查询生成
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

        # 读取注册表中的纯中文模板并格式化
        template = disease_config.get("rag_template", "{subtype}疾病，病灶位于{region}的诊疗指南")
        query_text = template.format(
            subtype=subtype,
            region=region if region else "未知部位",
            stage=stage
        )

        return query_text

    def retrieve(self, image_result: dict, clinical_result: dict, pathology_result: dict, top_k: int = 3) -> list[str]:
        """
        两阶段检索：硬匹配筛选分类子集 + 向量模型精排 Top-K
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
        logger.warning("Called deprecated init_from_documents. Please use init_rag.py instead.")
        pass