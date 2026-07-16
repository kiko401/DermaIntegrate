from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from ..retrieval.retriever import retrieve
from ..retrieval.rewrite_service import rewrite_and_classify
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class RetrievalDebugRequest(BaseModel):
    question: str
    kb_ids: List[int]
    options: Optional[Dict[str, Any]] = None

    class Config:
        fields = {"options": {"validate_default": True}}


class RewriteDebugRequest(BaseModel):
    question: str
    history: Optional[List[dict]] = []


class RetrievedChunk(BaseModel):
    doc_id: int
    chunk_id: str
    text: str
    score: float


@router.post("/debug/retrieval")
async def debug_retrieval_endpoint(req: RetrievalDebugRequest):
    """检索调试：返回 rewrite 结果、命中的 chunks、过滤逻辑与阻断原因"""
    try:
        top_k = req.options.get("top_k", 5) if req.options else 5
        threshold = req.options.get("similarity_threshold", 0.35) if req.options else 0.35

        rewritten_query, route = await rewrite_and_classify(req.question, [])
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
