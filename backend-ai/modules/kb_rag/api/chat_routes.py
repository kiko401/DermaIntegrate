from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import List, Optional
from ..schemas import ChatRequest, ChatResponse, PatientContextObject
from ..generation.chat_service import run_rag_workflow
from ..generation.stream_service import stream_rag_workflow
import json
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """非流式问答接口"""
    try:
        response = await run_rag_workflow(req)
        return response
    except Exception as e:
        logger.error(f"Chat failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream/{conversation_id}")
async def stream_chat_endpoint(
        conversation_id: int,
        question: str = Query(...),
        kb_ids: List[int] = Query([]),
        top_k: int = Query(5),
        similarity_threshold: float = Query(0.35),
        enable_tools: bool = Query(True),
        enable_agent: bool = Query(True),
        patient_context: Optional[str] = Query(None)  # JSON string of PatientContextObject
):
    """SSE 流式问答接口 (GET 方法)"""

    # 构造 ChatRequest 对象
    req = ChatRequest(
        conversation_id=conversation_id,
        question=question,
        kb_ids=kb_ids,
        options={
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "stream": True,
            "enable_tools": enable_tools,
            "enable_agent": enable_agent
        }
    )

    if patient_context:
        try:
            req.patient_context = PatientContextObject.parse_raw(patient_context)
        except Exception:
            pass  # 忽略解析错误，视为无上下文

    return StreamingResponse(
        stream_rag_workflow(req),
        media_type="text/event-stream"
    )