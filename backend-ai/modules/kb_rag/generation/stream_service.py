import json
import logging
import uuid
from typing import AsyncGenerator
from ..schemas import ChatRequest
from ..agent.langgraph_workflow import run_agent_workflow, init_agent_trace, update_agent_trace
from ..agent.tool_executor import execute_tool
from ..retrieval.rewrite_service import rewrite_and_classify
from ..retrieval.retriever import retrieve
from .chat_service import _call_llm
from .answer_builder import build_response
from .guardrails import check_input

logger = logging.getLogger(__name__)


async def stream_rag_workflow(req: ChatRequest) -> AsyncGenerator[str, None]:
    """SSE 流式 RAG 主链编排。"""

    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    run_id = str(uuid.uuid4())
    init_agent_trace(run_id)

    try:
        is_safe, hit_words = check_input(req.question)
        if not is_safe:
            resp = build_response(req, f"输入违规: {hit_words}", [], "general_chat", 0.0, "blocked", "敏感词拦截")
            yield format_sse("error", resp.dict())
            return
        update_agent_trace(run_id, "policy_check", "completed")
        yield format_sse("agent_trace",
                         {"workflow": "langgraph_rag_agent", "node": "policy_check", "status": "completed"})

        yield format_sse("progress", {"step": "rewrite", "progress": 10, "message": "正在重写并分析问题意图"})
        rewritten_query, route = await rewrite_and_classify(req.question, req.history)
        if req.patient_context:
            route = "patient_context_query"

        yield format_sse("progress", {"step": "intent_route", "progress": 20, "message": "意图路由完成"})
        update_agent_trace(run_id, "intent_route", "completed")
        yield format_sse("agent_trace",
                         {"workflow": "langgraph_rag_agent", "node": "intent_route", "status": "completed"})

        chunks = []
        if route in ["knowledge_query", "patient_context_query", "agent_workflow"]:
            yield format_sse("progress", {"step": "retrieval", "progress": 30, "message": "正在检索知识库"})
            top_k = req.options.get("top_k", 5)
            threshold = req.options.get("similarity_threshold", 0.35)
            chunks, is_blocked = await retrieve(rewritten_query, req.kb_ids, top_k, threshold)
            if is_blocked:
                resp = build_response(req, "知识库中未找到高置信度依据。", [], route, 0.0, "blocked", "低置信度阻断")
                yield format_sse("result", resp.dict())
                return
        update_agent_trace(run_id, "retrieval", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "retrieval", "status": "completed"})

        tool_calls = []
        if route == "tool_call":
            tool_payload = req.options.get("tool_payload", {})
            if tool_payload:
                tool_name = tool_payload.get("tool_name", "pandas_analyzer")
                yield format_sse("tool_call", {"tool_name": tool_name, "status": "running"})
                exec_result = await execute_tool(tool_name, tool_payload.get("arguments", {}))
                yield format_sse("tool_call", {"tool_name": tool_name, "status": exec_result.get("status", "failed")})
                tool_calls.append({"tool_name": tool_name, "arguments": tool_payload.get("arguments", {}),
                                   "status": exec_result.get("status"),
                                   "output_summary": str(exec_result.get("result", ""))[:200]})
            else:
                resp = build_response(req, "检测到工具调用意图，但未携带参数。", [], "tool_call", 0.0, "failed",
                                      "Missing payload")
                yield format_sse("result", resp.dict())
                return
        update_agent_trace(run_id, "tool_decision", "completed")
        yield format_sse("agent_trace",
                         {"workflow": "langgraph_rag_agent", "node": "tool_decision", "status": "completed"})

        yield format_sse("progress", {"step": "generation", "progress": 60, "message": "正在生成回答"})
        context = "\n".join([c["text"] for c in chunks])
        if req.patient_context:
            context = f"患者上下文:\n{req.patient_context.summary_text}\n\n参考资料:\n{context}"
        if tool_calls:
            context += f"\n工具分析结果: {tool_calls[0]['output_summary']}"

        answer = await _call_llm(req.question, context)
        update_agent_trace(run_id, "answer_builder", "completed")
        yield format_sse("agent_trace",
                         {"workflow": "langgraph_rag_agent", "node": "answer_builder", "status": "completed"})

        confidence = chunks[0]["score"] if chunks else 0.8
        final_resp = build_response(req, answer, chunks, route, confidence, "completed", tool_calls=tool_calls)
        update_agent_trace(run_id, "response_finalize", "completed")
        yield format_sse("agent_trace",
                         {"workflow": "langgraph_rag_agent", "node": "response_finalize", "status": "completed"})

        yield format_sse("result", final_resp.dict())

    except Exception as e:
        logger.error(f"Stream RAG workflow failed: {e}", exc_info=True)
        yield format_sse("error", {"code": "RAG_STREAM_ERROR", "message": str(e)})
