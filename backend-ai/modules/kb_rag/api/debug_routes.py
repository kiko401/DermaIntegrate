from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from ..retrieval.retriever import retrieve
from ..retrieval.rewrite_service import rewrite_and_classify
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class RetrievalDebugRequest(BaseModel):
    query: str
    kb_ids: List[int]
    top_k: int = 5
    threshold: float = 0.35

class RewriteDebugRequest(BaseModel):
    query: str
    history: Optional[List[dict]] = []

@router.post("/debug/retrieval")
async def debug_retrieval_endpoint(req: RetrievalDebugRequest):
    """检索调试：直接返回命中的 chunks 和分数"""
    try:
        chunks, is_blocked = await retrieve(req.query, req.kb_ids, req.top_k, req.threshold)
        return {
            "query": req.query,
            "is_blocked": is_blocked,
            "chunks": chunks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/debug/rewrite")
async def debug_rewrite_endpoint(req: RewriteDebugRequest):
    """重写调试：返回改写后的 query 和意图"""
    try:
        rewritten_query, route = await rewrite_and_classify(req.query, req.history)
        return {
            "original_query": req.query,
            "rewritten_query": rewritten_query,
            "route": route
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))