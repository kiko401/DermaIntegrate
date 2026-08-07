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
    """
    非流式问答接口（仅供调试/服务间调用使用）。

    生产环境建议统一使用流式接口 GET /stream/，
    前端可对 SSE 响应进行缓冲后一次性展示，体验等同于非流式。
    """
    if not req.kb_ids:
        raise HTTPException(status_code=422, detail="kb_ids must not be empty")

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
        use_rerank: bool = Query(False),
        max_length: int = Query(0),
        max_paragraphs: int = Query(0),
        patient_context: Optional[str] = Query(None),  # JSON string of PatientContextObject
        history: Optional[str] = Query(None),  # JSON string of List[Dict[str, str]]
        doctor_id: Optional[int] = Query(None),  # 医生 ID（临床病例权限隔离）
):
    """SSE 流式问答接口 (GET 方法)"""

    # 构造 ChatRequest 对象
    parsed_history = []
    if history:
        try:
            import json as _json
            parsed_history = _json.loads(history)
        except Exception:
            logger.warning(f"Failed to parse history JSON for conversation {conversation_id}, ignoring.")

    # 解析 patient_context（JSON 字符串）
    parsed_patient_context = None
    if patient_context:
        try:
            parsed_patient_context = PatientContextObject.model_validate_json(patient_context)
        except Exception:
            raise HTTPException(
                status_code=422,
                detail=f"patient_context JSON 格式错误: {patient_context[:100]}"
            )

    try:
        req = ChatRequest(
            conversation_id=conversation_id,
            question=question,
            history=parsed_history,
            kb_ids=kb_ids,
            options={
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
                "stream": True,
                "enable_tools": enable_tools,
                "enable_agent": enable_agent,
                "use_rerank": use_rerank,
                "max_length": max_length,
                "max_paragraphs": max_paragraphs,
            },
            patient_context=parsed_patient_context,
            doctor_id=doctor_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    async def error_safe_stream():
        """包装流式生成器，捕获异常并以 SSE 错误事件返回"""
        try:
            async for chunk in stream_rag_workflow(req):
                yield chunk
        except Exception as e:
            logger.error(f"Stream error for conversation {conversation_id}: {e}", exc_info=True)
            payload = {"code": "RAG_STREAM_ERROR", "message": str(e)}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        error_safe_stream(),
        media_type="text/event-stream"
    )


class StreamChatRequest(ChatRequest):
    """
    POST /rag/stream/{conversation_id} 的请求体。

    继承自 ChatRequest，新增 stream 标志（固定为 True）。
    应用域通过此接口以 JSON body 传递完整请求参数（含 history / patient_context），
    避免将大型 JSON 结构序列化到 URL query string，规避 URL 长度限制与 PHI 进入 access log 的风险。
    """
    pass


@router.post("/stream/{conversation_id}")
async def stream_chat_post_endpoint(conversation_id: int, req: StreamChatRequest):
    """
    SSE 流式问答接口（POST 方法）。

    与 GET /stream/{conversation_id} 功能完全一致，但以 JSON body 传参，
    适合 history 较长或存在 patient_context 的场景，避免 URL 超长问题。

    conversation_id 路径参数与 req.conversation_id 必须一致，
    以 req.conversation_id 为准（路径参数仅用于路由匹配）。
    """
    # 强制 stream=True，确保选项与接口语义一致
    if req.options is not None:
        req.options["stream"] = True

    async def error_safe_stream():
        try:
            async for chunk in stream_rag_workflow(req):
                yield chunk
        except Exception as e:
            logger.error(f"Stream POST error for conversation {conversation_id}: {e}", exc_info=True)
            payload = {"code": "RAG_STREAM_ERROR", "message": str(e)}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        error_safe_stream(),
        media_type="text/event-stream"
    )