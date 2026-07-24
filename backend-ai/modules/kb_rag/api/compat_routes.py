from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from ..generation.chat_service import run_rag_workflow
from ..generation.stream_service import stream_rag_workflow
from ..schemas import ChatRequest, PatientContextObject
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class OpenAIMessage(BaseModel):
    role: Literal['system', 'user', 'assistant', 'tool']
    content: str


class OpenAICompatRequest(BaseModel):
    messages: Optional[List[OpenAIMessage]] = None
    stream: bool = False
    model: Optional[str] = None
    conversation_id: Optional[int] = None
    kb_ids: List[int] = Field(default_factory=list)
    history: List[Dict[str, str]] = Field(default_factory=list)
    patient_context: Optional[PatientContextObject] = None
    options: Optional[Dict[str, Any]] = None
    question: Optional[str] = None


def _parse_kb_ids(x_kb_ids: Optional[str]) -> List[int]:
    if not x_kb_ids:
        return []
    ids = []
    for item in x_kb_ids.split(','):
        item = item.strip()
        if not item:
            continue
        try:
            ids.append(int(item))
        except ValueError:
            continue
    return ids


def _build_internal_request(req: OpenAICompatRequest, x_kb_ids: Optional[str]) -> ChatRequest:
    kb_ids = _parse_kb_ids(x_kb_ids) or list(req.kb_ids or [])
    if not kb_ids:
        raise HTTPException(status_code=400, detail='kb_ids is required')

    question = req.question.strip() if req.question else ''
    history: List[Dict[str, str]] = []

    if req.messages:
        user_indices = [idx for idx, msg in enumerate(req.messages) if msg.role == 'user']
        if not user_indices:
            raise HTTPException(status_code=400, detail='messages is required')
        last_user_idx = user_indices[-1]
        question = str(req.messages[last_user_idx].content).strip()
        if not question:
            raise HTTPException(status_code=400, detail='messages is required')
        for msg in req.messages[:last_user_idx]:
            if msg.role in {'user', 'assistant'} and str(msg.content).strip():
                history.append({'role': msg.role, 'content': str(msg.content)})
    elif req.history:
        history = [
            {'role': str(item.get('role', 'user')), 'content': str(item.get('content', ''))}
            for item in req.history
            if str(item.get('content', '')).strip()
        ]

    if not question:
        raise HTTPException(status_code=400, detail='messages is required')

    options = dict(req.options or {})
    options['stream'] = bool(req.stream)

    try:
        return ChatRequest(
            conversation_id=req.conversation_id or 0,
            question=question,
            history=history[-10:],
            kb_ids=kb_ids,
            patient_context=req.patient_context,
            options=options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post('/chat/completions')
async def openai_completions_endpoint(
        req: OpenAICompatRequest,
        x_kb_ids: Optional[str] = Header(None, alias='X-KB-IDS'),
):
    """OpenAI 风格兼容问答入口，响应体依然为自定义 ChatResponse。"""
    internal_req = _build_internal_request(req, x_kb_ids)

    if internal_req.options.get('stream'):
        return StreamingResponse(stream_rag_workflow(internal_req), media_type='text/event-stream')

    resp = await run_rag_workflow(internal_req)
    return resp
