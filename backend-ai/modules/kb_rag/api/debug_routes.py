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
    offset: int = Field(0, ge=0, description="版本分页偏移")
    limit: int = Field(50, ge=1, le=200, description="最多返回版本数")
    max_chunks_per_version: int = Field(100, ge=1, le=500, description="每个版本最多返回 chunk 数")


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
    total_versions: int
    returned_versions: int
    total_chunks: int
    versions: List[DocVersionItem]


@router.post("/debug/doc-versions", response_model=DocVersionsResponse)
async def doc_versions_endpoint(req: DocVersionsRequest):
    """
    查询指定 doc_id 各版本的 chunk 文本，供应用域做版本 diff UI。

    - 按 doc_version_id 分组返回每个版本的所有 chunk
    - 空 doc_version_ids 时返回该 doc_id 下所有版本
    - 返回的 text 为原始 chunk 内容，不含向量
    - 分页参数控制版本数量，每个版本内最多 max_chunks_per_version 个 chunk
    - 全程流式处理，不一次性加载全部 point 到内存
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

        # 流式分组：边扫描边构建 version_map，不一次性加载全部
        version_map: Dict[int, List[DocVersionChunk]] = {}
        total_chunks = 0
        offset = None

        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=kb_filter,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break

            for pt in points:
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

                if doc_version_id not in version_map:
                    version_map[doc_version_id] = []

                # 每个版本最多 max_chunks_per_version，超过则跳过（保持内存稳定）
                if len(version_map[doc_version_id]) >= req.max_chunks_per_version:
                    total_chunks += 1
                    continue

                version_map[doc_version_id].append(DocVersionChunk(
                    chunk_index=chunk_index,
                    chunk_id=chunk_id,
                    text=payload.get("text", ""),
                ))
                total_chunks += 1

            if next_offset is None:
                break
            offset = next_offset

        if not version_map:
            return DocVersionsResponse(
                doc_id=req.doc_id,
                total_versions=0,
                returned_versions=0,
                total_chunks=0,
                versions=[]
            )

        # 每组内按 chunk_index 排序
        for vid in version_map:
            version_map[vid].sort(key=lambda c: c.chunk_index)

        sorted_versions = sorted(version_map.items())
        total_versions = len(sorted_versions)
        paginated_versions = sorted_versions[req.offset:req.offset + req.limit]

        versions = [
            DocVersionItem(
                doc_version_id=vid,
                chunk_count=len(chunks),
                chunks=chunks,
            )
            for vid, chunks in paginated_versions
        ]

        return DocVersionsResponse(
            doc_id=req.doc_id,
            total_versions=total_versions,
            returned_versions=len(versions),
            total_chunks=total_chunks,
            versions=versions,
        )

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
    拆分结果预览接口：返回切分后的 chunk 内容、长度与边界信息，不入库。

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
    文档全文关键词搜索：基于 BM25 词频-逆文档频率评分，
    在指定 kb_ids 范围内搜索匹配的 chunk。

    - 支持多关键词（空格分隔，按 AND 逻辑匹配）
    - 返回每个命中文档的 BM25 分数和关键词命中列表
    - 使用真实 IDF 加权，避免简化评分的排序失真
    - 分批 scroll 并维护有序 top 结果，防止大知识库 OOM
    """
    try:
        from ..utils import tokenize as _shared_tokenize
        from ..retrieval.retriever import _get_global_idf
        from collections import Counter

        # 1. 解析关键词（对查询短语也进行分词，实现 token 级别匹配）
        query_phrases = req.query.strip().split()
        if not query_phrases:
            raise ValueError("查询词不能为空")
        query_tokens: list[str] = []
        for phrase in query_phrases:
            for tok in _shared_tokenize(phrase):
                if tok not in query_tokens:
                    query_tokens.append(tok)
        if not query_tokens:
            raise ValueError("查询词不能为空")

        # 获取全局 IDF（来自已持久化的 bm25_idf.json）
        idf_map = _get_global_idf()
        avg_doc_len = 200.0  # 默认平均文档长度（字符级估算）

        # 2. 分批 scroll Qdrant，维护有序 top_k 结果（防止 OOM）
        client = get_qdrant_client()
        must_conditions = [
            models.FieldCondition(key="kb_id", match=models.MatchAny(any=req.kb_ids))
        ]
        if req.doc_id is not None:
            must_conditions.append(
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=req.doc_id))
            )
        kb_filter = models.Filter(must=must_conditions)

        top_results: list[dict] = []
        offset = None

        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=kb_filter,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break

            for pt in points:
                payload = pt.payload or {}
                text = payload.get("text", "")
                if not text:
                    continue

                doc_tokens = _shared_tokenize(text)
                doc_token_set = set(doc_tokens)
                doc_len = len(doc_tokens)

                # 命中关键词：查询 token 与文档 token 的交集
                hit_tokens = [tok for tok in query_tokens if tok in doc_token_set]
                if not hit_tokens:
                    continue

                # 真实 BM25 评分：Σ IDF(t) * (tf * (k1+1)) / (tf + k1 * (1 - b + b * doc_len/avg_doc_len))
                BM25_K1 = 1.5
                BM25_B = 0.75
                doc_tf = Counter(doc_tokens)
                bm25_score = 0.0
                for tok in hit_tokens:
                    tf = doc_tf.get(tok, 0)
                    idf = idf_map.get(tok, 1.0)  # 未知词默认 IDF=1.0
                    bm25_score += idf * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / avg_doc_len))

                # 解析 chunk_index
                chunk_id = payload.get("chunk_id", "")
                chunk_index = 0
                parts = chunk_id.split("_")
                if len(parts) >= 3:
                    try:
                        chunk_index = int(parts[-1])
                    except ValueError:
                        chunk_index = 0

                entry = {
                    "doc_id": payload.get("doc_id", 0),
                    "doc_version_id": payload.get("doc_version_id", 0),
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "text_snippet": text[:200],
                    "bm25_score": round(bm25_score, 4),
                    "keyword_matches": hit_tokens,
                }

                # 插入有序列表（保持降序）
                inserted = False
                for i, existing in enumerate(top_results):
                    if bm25_score > existing["bm25_score"]:
                        top_results.insert(i, entry)
                        inserted = True
                        break
                if not inserted:
                    top_results.append(entry)

                # 超过候选上限则截断，防止内存膨胀
                max_candidates = req.top_k * 3
                if len(top_results) > max_candidates:
                    top_results = top_results[:max_candidates]

            if next_offset is None:
                break
            offset = next_offset

        final_top = top_results[:req.top_k]

        return KeywordSearchResponse(
            query=req.query,
            total_hits=len(top_results),
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
                for r in final_top
            ],
        )

    except Exception as e:
        logger.error(f"Keyword search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
