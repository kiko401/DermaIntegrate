from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any
from ..retrieval.retriever import retrieve
from ..retrieval.rewrite_service import rewrite_and_classify
from ..ingest.vector_store import get_qdrant_client, COLLECTION_NAME
from ..ingest.splitters import split_text
from qdrant_client.http import models
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class RetrievalDebugRequest(BaseModel):
    model_config = ConfigDict(validate_default=True)

    question: str
    kb_ids: List[int]
    options: Optional[Dict[str, Any]] = None


# ===== 拆分结果预览 =====

class SplitPreviewRequest(BaseModel):
    text: str = Field(..., description="待切分文本内容")
    kb_id: int = Field(..., description="所属知识库 ID（用于文档标识）")
    chunk_size: int = Field(800, ge=100, le=4000, description="每段字符数")
    chunk_overlap: int = Field(120, ge=0, le=2000, description="段间重叠字符数")
    doc_id: int = Field(0, description="文档 ID（预览时可用 0 占位）")
    doc_version_id: int = Field(0, description="文档版本 ID（预览时可用 0 占位）")


class ChunkPreview(BaseModel):
    chunk_index: int
    chunk_id: str
    char_count: int
    text_preview: str = Field(..., description="该 chunk 前 100 字符预览")


class SplitPreviewResponse(BaseModel):
    kb_id: int
    doc_id: int
    doc_version_id: int
    chunk_count: int
    total_chars: int
    chunks: List[ChunkPreview]


class RewriteDebugRequest(BaseModel):
    question: str
    history: Optional[List[dict]] = []


# ===== 文档全文关键词搜索 =====

class KeywordSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="搜索关键词（支持空格分隔多词）")
    kb_ids: List[int] = Field(..., min_length=1, description="要搜索的知识库 ID 列表")
    top_k: int = Field(20, ge=1, le=200, description="返回最多 top_k 条结果")
    doc_id: Optional[int] = Field(None, description="限定文档 ID（可选）")


class KeywordSearchResult(BaseModel):
    doc_id: int
    doc_version_id: int
    chunk_id: str
    chunk_index: int
    text_snippet: str = Field(..., description="命中文本片段（前 200 字符）")
    bm25_score: float
    keyword_matches: List[str] = Field(default_factory=list, description="命中的关键词列表")


class KeywordSearchResponse(BaseModel):
    query: str
    total_hits: int
    results: List[KeywordSearchResult]


class RetrievedChunk(BaseModel):
    doc_id: int
    chunk_id: str
    text: str
    score: float


# ===== 文档版本内容查询 =====

class DocVersionsRequest(BaseModel):
    doc_id: int
    doc_version_ids: Optional[List[int]] = None  # 空则返回所有版本


class DocVersionChunk(BaseModel):
    chunk_index: int
    chunk_id: str
    text: str


class DocVersionItem(BaseModel):
    doc_version_id: int
    chunk_count: int
    chunks: List[DocVersionChunk]


class DocVersionsResponse(BaseModel):
    doc_id: int
    versions: List[DocVersionItem]


@router.post("/debug/doc-versions", response_model=DocVersionsResponse)
async def doc_versions_endpoint(req: DocVersionsRequest):
    """
    查询指定 doc_id 各版本的 chunk 文本，供应用域做版本 diff UI。

    - 按 doc_version_id 分组返回每个版本的所有 chunk
    - 空 doc_version_ids 时返回该 doc_id 下所有版本
    - 返回的 text 为原始 chunk 内容，不含向量
    """
    try:
        client = get_qdrant_client()

        # 构建过滤条件
        must_conditions = [
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=req.doc_id))
        ]
        if req.doc_version_ids is not None and len(req.doc_version_ids) > 0:
            must_conditions.append(
                models.FieldCondition(
                    key="doc_version_id",
                    match=models.MatchAny(any=req.doc_version_ids)
                )
            )

        kb_filter = models.Filter(must=must_conditions)

        # 扫描所有匹配的 point
        all_points = []
        offset = None
        while True:
            result = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=kb_filter,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            all_points.extend(result.points)
            if result.next_page_offset is None:
                break
            offset = result.next_page_offset

        if not all_points:
            return DocVersionsResponse(doc_id=req.doc_id, versions=[])

        # 按 doc_version_id 分组
        version_map: Dict[int, List[DocVersionChunk]] = {}
        for pt in all_points:
            payload = pt.payload or {}
            doc_version_id = payload.get("doc_version_id", 0)
            chunk_id = payload.get("chunk_id", "")

            # 解析 chunk_index: 格式 {doc_id}_{doc_version_id}_{chunk_index}，chunk_index 补零至三位
            chunk_index = 0
            parts = chunk_id.split("_")
            if len(parts) >= 3:
                try:
                    chunk_index = int(parts[-1])
                except ValueError:
                    chunk_index = 0

            chunk_item = DocVersionChunk(
                chunk_index=chunk_index,
                chunk_id=chunk_id,
                text=payload.get("text", ""),
            )

            if doc_version_id not in version_map:
                version_map[doc_version_id] = []
            version_map[doc_version_id].append(chunk_item)

        # 每组内按 chunk_index 排序
        for vid in version_map:
            version_map[vid].sort(key=lambda c: c.chunk_index)

        # 构建响应
        versions = [
            DocVersionItem(
                doc_version_id=vid,
                chunk_count=len(chunks),
                chunks=chunks,
            )
            for vid, chunks in sorted(version_map.items())
        ]

        return DocVersionsResponse(doc_id=req.doc_id, versions=versions)

    except Exception as e:
        logger.error(f"Doc versions query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debug/retrieval")
async def debug_retrieval_endpoint(req: RetrievalDebugRequest):
    """检索调试：返回 rewrite 结果、命中的 chunks、过滤逻辑与阻断原因"""
    try:
        top_k = req.options.get("top_k", 5) if req.options else 5
        threshold = req.options.get("similarity_threshold", 0.35) if req.options else 0.35

        rewritten_query, _ = await rewrite_and_classify(req.question, [])
        chunks, is_blocked = await retrieve(req.question, req.kb_ids, top_k, threshold)

        retrieved_chunks = [
            {
                "doc_id": c.get("doc_id", 0),
                "chunk_id": c.get("chunk_id", ""),
                "text": c.get("text", ""),
                "score": c.get("score", 0.0)
            }
            for c in chunks
        ]

        fallback_reason = None
        if is_blocked:
            fallback_reason = "知识库中未找到高置信度依据"

        return {
            "rewrite_question": rewritten_query,
            "retrieved_chunks": retrieved_chunks,
            "filter_logic": {"kb_ids": req.kb_ids, "top_k": top_k, "threshold": threshold},
            "fallback_reason": fallback_reason
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debug/rewrite")
async def debug_rewrite_endpoint(req: RewriteDebugRequest):
    """重写调试：返回原问题、改写结果、纠错标识"""
    try:
        rewritten_query, route = await rewrite_and_classify(req.question, req.history or [])

        # 检查是否有纠错（重写后与原问题有明显差异）
        corrected = rewritten_query != req.question
        correction = None
        if corrected:
            correction = rewritten_query

        return {
            "original": req.question,
            "rewritten": rewritten_query,
            "corrected": corrected,
            "correction": correction
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debug/split-preview", response_model=SplitPreviewResponse)
async def split_preview_endpoint(req: SplitPreviewRequest):
    """
    M-02 拆分结果预览接口：返回切分后的 chunk 内容、长度与边界信息，不入库。

    - chunk_size / chunk_overlap 支持 100~4000 / 0~2000 范围
    - 返回每个 chunk 的前 100 字符预览
    """
    try:
        # 调用切分函数（不触发 embedding/indexing）
        chunks = split_text(
            text=req.text,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            doc_id=req.doc_id or 0,
            doc_version_id=req.doc_version_id or 0,
        )

        chunk_previews = [
            ChunkPreview(
                chunk_index=c["chunk_index"],
                chunk_id=c["chunk_id"],
                char_count=len(c["text"]),
                text_preview=c["text"][:100],
            )
            for c in chunks
        ]

        return SplitPreviewResponse(
            kb_id=req.kb_id,
            doc_id=req.doc_id or 0,
            doc_version_id=req.doc_version_id or 0,
            chunk_count=len(chunks),
            total_chars=len(req.text),
            chunks=chunk_previews,
        )
    except Exception as e:
        logger.error(f"Split preview failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debug/keyword-search", response_model=KeywordSearchResponse)
async def keyword_search_endpoint(req: KeywordSearchRequest):
    """
    M-02 文档全文关键词搜索：基于 BM25 词频-逆文档频率评分，
    在指定 kb_ids 范围内搜索匹配的 chunk。

    - 支持多关键词（空格分隔，按 AND 逻辑匹配）
    - 返回每个命中文档的 BM25 分数和关键词命中列表
    """
    try:
        from ..utils import tokenize as _shared_tokenize
        from ..ingest.vector_store import COLLECTION_NAME

        # 1. 解析关键词
        keywords = req.query.strip().split()
        if not keywords:
            raise ValueError("查询词不能为空")

        # 2. 查询 Qdrant 获取所有候选 chunk（按 kb_id + doc_id 过滤）
        client = get_qdrant_client()
        must_conditions = [
            models.FieldCondition(key="kb_id", match=models.MatchAny(any=req.kb_ids))
        ]
        if req.doc_id is not None:
            must_conditions.append(
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=req.doc_id))
            )
        kb_filter = models.Filter(must=must_conditions)

        all_points = []
        offset = None
        while True:
            result = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=kb_filter,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            all_points.extend(result.points)
            if result.next_page_offset is None:
                break
            offset = result.next_page_offset

        if not all_points:
            return KeywordSearchResponse(query=req.query, total_hits=0, results=[])

        # 3. 对每个 chunk 计算 BM25 分数（基于 token 命中）
        scored = []
        for pt in all_points:
            payload = pt.payload or {}
            text = payload.get("text", "")
            if not text:
                continue

            tokens = _shared_tokenize(text)
            token_set = set(tokens)

            # 命中关键词
            hit_keywords = [kw for kw in keywords if kw in token_set]
            if not hit_keywords:
                continue

            # BM25 简化评分：命中词数 * log(文档总数/匹配文档数)
            hit_count = len(hit_keywords)
            bm25_score = hit_count * 1.0  # 简化模式（忽略 IDF 以减少计算量）

            # 解析 chunk_id 获取 chunk_index
            chunk_id = payload.get("chunk_id", "")
            chunk_index = 0
            parts = chunk_id.split("_")
            if len(parts) >= 3:
                try:
                    chunk_index = int(parts[-1])
                except ValueError:
                    chunk_index = 0

            scored.append({
                "doc_id": payload.get("doc_id", 0),
                "doc_version_id": payload.get("doc_version_id", 0),
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "text_snippet": text[:200],
                "bm25_score": bm25_score,
                "keyword_matches": hit_keywords,
            })

        # 4. 按 BM25 分数降序，取 top_k
        scored.sort(key=lambda x: x["bm25_score"], reverse=True)
        top_results = scored[:req.top_k]

        return KeywordSearchResponse(
            query=req.query,
            total_hits=len(scored),
            results=[
                KeywordSearchResult(
                    doc_id=r["doc_id"],
                    doc_version_id=r["doc_version_id"],
                    chunk_id=r["chunk_id"],
                    chunk_index=r["chunk_index"],
                    text_snippet=r["text_snippet"],
                    bm25_score=r["bm25_score"],
                    keyword_matches=r["keyword_matches"],
                )
                for r in top_results
            ],
        )

    except Exception as e:
        logger.error(f"Keyword search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
