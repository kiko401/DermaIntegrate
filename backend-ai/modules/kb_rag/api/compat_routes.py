from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from typing import Optional, List
from ..generation.chat_service import run_rag_workflow
from ..generation.stream_service import stream_rag_workflow
from ..schemas import ChatRequest
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat/completions")
async def openai_completions_endpoint(
        req: ChatRequest,
        x_kb_ids: Optional[str] = Header(None, alias="X-KB-IDS"),
):
    """
    统一 API 入口，兼容外部系统调用。
    kb_ids 以 X-KB-IDS Header 传入（格式："1,2,3"），也接受 body.kb_ids。
    """
    # Header 中的 kb_ids 优先级更高
    if x_kb_ids:
        try:
            req.kb_ids = [int(kid.strip()) for kid in x_kb_ids.split(",") if kid.strip()]
        except ValueError:
            pass

    if not req.kb_ids:
        raise HTTPException(status_code=400, detail="kb_ids is required")

    if req.question is None or not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required")

    if req.stream:
        return StreamingResponse(stream_rag_workflow(req), media_type="text/event-stream")

    resp = await run_rag_workflow(req)
    return resp
