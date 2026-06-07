import os
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType, Filter, FieldCondition, \
    MatchAny
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class RAGKnowledgeBase:
    def __init__(self, docs_dir: str = None):
        logger.info("Initializing HuggingFace Embedding model (bge-small-zh-v1.5)...")
        # 加载本地向量化模型
        self.embedder = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        self.vector_size = self.embedder.get_sentence_embedding_dimension()

        # 切换 Qdrant 连接逻辑：Docker 环境连接容器名，本地连接 localhost
        qdrant_host = "qdrant" if os.getenv("DOCKER_ENV") == "true" else "localhost"
        self.client = QdrantClient(host=qdrant_host, port=6333)

        self.collection_name = "derma_knowledge"
        self.docs_dir = docs_dir

    def init_from_parsed_data(self, texts: list, payloads: list):
        """
        接收由 init_rag.py 解析好的文本和带有 doc_id/tags 的 payload，向量化并存入 Qdrant。
        支持两阶段检索的索引创建。
        """
        if not texts:
            logger.warning("No texts provided for initialization.")
            return

        logger.info(f"Embedding {len(texts)} text fragments and building index...")

        # 1. 重建集合
        self.client.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
        )

        # 2. 创建 Payload 索引 (极重要：两阶段检索的硬匹配前提)
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

        # 3. 向量化文本
        vectors = self.embedder.encode(texts, show_progress_bar=True)

        # 4. 批量插入数据 (合并 text 和 payload)
        points = [
            PointStruct(
                id=idx,
                vector=vectors[idx].tolist(),
                payload={"text": texts[idx], **payloads[idx]}  # 包含 text, doc_id, tags, source
            )
            for idx in range(len(texts))
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
        logger.info("RAG Knowledge Base built successfully with tag indexes!")

    def _extract_filter_tags(self, clinical_result: dict, pathology_result: dict) -> list:
        """
        核心映射逻辑：将多模态 Agent 的中文输出特征，映射为 Qdrant 的硬匹配标签。
        规则严格对齐 v3.1 契约。
        """
        filter_tags = ["通用"]  # 默认必须有通用标签兜底，防止空召回

        # 1. 部位映射：肢端型
        if clinical_result and clinical_result.get("lesion_clinical"):
            region = clinical_result.get("lesion_clinical", {}).get("region") or ""
            if any(kw in region for kw in ["手", "足", "甲"]):
                filter_tags.append("肢端")

        # 2. 病理分期映射
        if pathology_result:
            t_stage = pathology_result.get("t_stage", "")
            if "T1" in t_stage:
                filter_tags.extend(["T1", "病理", "MEL"])
            elif "T2" in t_stage:
                filter_tags.extend(["T2", "病理", "MEL"])
            elif "T3" in t_stage:
                filter_tags.extend(["T3", "病理", "高危", "MEL"])
            elif "T4" in t_stage:
                filter_tags.extend(["T4", "病理", "高危", "MEL"])
            elif "无法分期" in t_stage or "未提供" in t_stage:
                filter_tags.append("病理")  # 只要有病理意图，优先召回病理类指南

            # 3. 分子靶向映射
            if pathology_result.get("braf_mutation") == "突变型":
                filter_tags.append("分子靶向")

        return list(set(filter_tags))  # 去重

    def _build_multimodal_query(self, image_result: dict, clinical_result: dict, pathology_result: dict) -> str:
        """
        构造多模态复合查询向量：将关键特征拼接为自然语言查询。
        """
        query_parts = []

        # 临床特征
        if clinical_result and clinical_result.get("lesion_clinical"):
            region = clinical_result.get("lesion_clinical", {}).get("region")
            if region: query_parts.append(f"病灶位于{region}")

        # 视觉特征
        if image_result and image_result.get("morphology"):
            morph = image_result["morphology"]
            if morph.get("border"): query_parts.append(f"边缘{morph['border']}")
            if morph.get("pigment_network"): query_parts.append(f"色素网{morph['pigment_network']}")

        # 病理特征
        if pathology_result:
            t_stage = pathology_result.get("t_stage")
            if t_stage and t_stage not in ["未提供", "无法分期"]:
                query_parts.append(f"病理分期为{t_stage}")

        return "，".join(query_parts) + "的诊疗指南" if query_parts else "皮肤黑色素瘤一般诊疗原则"

    def retrieve(self, image_result: dict, clinical_result: dict, pathology_result: dict, top_k: int = 3) -> list[str]:
        """
        两阶段检索：硬匹配筛选分类子集 + 向量模型精排 Top-3
        """
        # 1. 生成复合查询文本与向量
        query_text = self._build_multimodal_query(image_result, clinical_result, pathology_result)
        logger.info(f"RAG Multimodal Query: {query_text}")
        query_vector = self.embedder.encode(query_text).tolist()

        # 2. 提取硬匹配标签
        filter_tags = self._extract_filter_tags(clinical_result, pathology_result)
        logger.info(f"RAG Hard Filter Tags: {filter_tags}")

        # 3. 构建 Qdrant 的 Filter 条件 (满足任一标签即进入候选子集)
        query_filter = Filter(
            should=[
                FieldCondition(key="tags", match=MatchAny(any=filter_tags))
            ]
        )

        # 4. 执行检索 (带过滤器)
        try:
            search_response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,  # 注入硬匹配过滤器
                limit=top_k,
                score_threshold=0.3,  # 基础相似度阈值
                with_payload=True
            )
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}. Attempting fallback search without filter.")
            # 降级：如果带过滤搜索失败(例如索引未建立)，退回全量检索
            search_response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                score_threshold=0.3,
                with_payload=True
            )

        # 5. 拼装带 ID 的返回结果 (防幻觉核心：强制 LLM 照抄 ID)
        formatted_results = []
        for hit in search_response.points:
            doc_id = hit.payload.get("doc_id", "UNK-00")
            text = hit.payload.get("text", "")
            # 将 [WHW-01] 重新拼回给 LLM 看
            formatted_results.append(f"[{doc_id}] {text}")

        logger.info(f"Retrieved {len(formatted_results)} relevant fragments with IDs.")
        return formatted_results

    # 保留旧方法以兼容可能的直接调用，但核心管线将不再使用
    def init_from_documents(self, docs_dir: str = None):
        """旧版初始化方法 (已废弃，请使用 init_rag.py 调用 init_from_parsed_data)"""
        logger.warning("Called deprecated init_from_documents. Please use init_rag.py instead.")
        pass