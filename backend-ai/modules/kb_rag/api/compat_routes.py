from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from typing import List, Optional
from pydantic import BaseModel
from ..generation.chat_service import run_rag_workflow
from ..generation.stream_service import stream_rag_workflow
from ..schemas import ChatRequest, PatientContextObject
import json
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class OpenAIMessage(BaseModel):
    role: str
    content: str


class OpenAIChatRequest(BaseModel):
    messages: List[OpenAIMessage]
    stream: bool = False
    model: Optional[str] = None
    temperature: Optional[float] = None


@router.post("/chat/completions")
async def openai_completions_endpoint(
        req: OpenAIChatRequest,
        x_kb_ids: Optional[str] = Header(None, alias="X-KB-IDS")  # 从 Header 中读取知识库 ID
):
    """OpenAI 兼容接口"""

    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages cannot be empty")

    last_msg = req.messages[-1]
    if last_msg.role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from user")

    question = last_msg.content
    history = [msg.dict() for msg in req.messages[:-1]]

    # 解析 Header 中的 kb_ids (格式: "1,2,3")
    kb_ids = []
    if x_kb_ids:
        try:
            kb_ids = [int(kid.strip()) for kid in x_kb_ids.split(",") if kid.strip()]
        except ValueError:
            pass

    chat_req = ChatRequest(
        conversation_id=0,
        question=question,
        history=history,
        kb_ids=kb_ids,  # 使用从 Header 解析的真实 kb_ids
        options={"stream": req.stream}
    )

    if req.stream:
        return StreamingResponse(stream_rag_workflow(chat_req), media_type="text/event-stream")
    else:
        resp = await run_rag_workflow(chat_req)
        return {
            "id": resp.message_id,
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": resp.answer
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }