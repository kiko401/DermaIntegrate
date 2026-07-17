"""
SSE 流式 RAG 工作流

以 LangGraph StateGraph 为唯一执行引擎，本模块为 SSE 适配层，
负责将 LangGraph 执行结果转换为 SSE 事件流。

注意：M-09 本模块并非真正的 token 级流式输出。
LangGraph 完整执行后才生成模拟进度 SSE 事件，
目的是为客户提供阶段性进度感知，而非实时 token 流。
如需真正流式输出，需在 answer_builder 阶段引入 LLM 的 streaming API。

工作流节点（与 langgraph_workflow.py 一致）：
1. policy_check    -> 输入安全检查
2. phi_guard       -> PHI 二次守护
3. intent_route    -> 意图识别
4. rewrite         -> 查询改写
5. retrieval       -> 知识库检索
6. tool_decision   -> 工具调用
7. answer_builder  -> 答案生成
8. risk_highlight  -> 风险高亮
9. response_finalize -> 响应封装
"""

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

from ..schemas import ChatRequest
from ..agent.langgraph_workflow import run_agent_workflow
from ..agent.tool_executor import init_agent_trace

logger = logging.getLogger(__name__)


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_sse_events(resp_dict: dict, route: str) -> AsyncGenerator[str, None]:
    """将 LangGraph 执行结果转换为 SSE 事件序列。

    严格按照文档定义的事件顺序和格式生成 SSE 事件流。
    事件顺序：phi_guard -> rejection_check -> rule_match -> intent_route -> rewrite -> retrieval -> tool_decision -> generation -> risk_highlight -> finalize
    """
    # 阻断情况：直接返回 result 事件
    if resp_dict.get("status") == "blocked" or resp_dict.get("response"):
        yield _format_sse("result", resp_dict.get("response", resp_dict))
        return

    # 1. phi_guard - PHI 检测
    yield _format_sse("progress", {"step": "phi_guard", "progress": 5, "message": "正在进行安全检查"})
    yield _format_sse("agent_trace", {
        "workflow": "langgraph_rag_agent",
        "node": "phi_guard",
        "status": "completed",
    })

    # 2. rejection_check - 拒绝规则检查
    yield _format_sse("progress", {"step": "rejection_check", "progress": 6, "message": "正在进行规则过滤"})
    yield _format_sse("agent_trace", {
        "workflow": "langgraph_rag_agent",
        "node": "rejection_check",
        "status": "completed",
    })

    # 3. rule_match - 规则匹配（仅当有规则命中时）
    if route == "rule_answer":
        yield _format_sse("progress", {"step": "rule_match", "progress": 8, "message": "正在进行规则匹配"})
        yield _format_sse("agent_trace", {
            "workflow": "langgraph_rag_agent",
            "node": "rule_match",
            "status": "completed",
        })

    # 4. intent_route - 意图识别
    yield _format_sse("progress", {"step": "intent_route", "progress": 12, "message": "正在进行意图识别"})
    yield _format_sse("agent_trace", {
        "workflow": "langgraph_rag_agent",
        "node": "intent_route",
        "status": "completed",
    })

    # 5. rewrite - 查询改写（仅知识查询路由）
    if route in ["knowledge_query", "patient_context_query"]:
        yield _format_sse("progress", {"step": "rewrite", "progress": 17, "message": "正在进行查询改写"})
        yield _format_sse("agent_trace", {
            "workflow": "langgraph_rag_agent",
            "node": "rewrite",
            "status": "completed",
        })

    # 6. retrieval - 知识库检索（知识查询路由）
    if route in ["knowledge_query", "patient_context_query", "agent_workflow"]:
        sources = resp_dict.get("sources", [])
        yield _format_sse("progress", {"step": "retrieval", "progress": 35, "message": "正在检索知识库"})
        yield _format_sse("agent_trace", {
            "workflow": "langgraph_rag_agent",
            "node": "retrieval",
            "status": "completed",
        })
        yield _format_sse("progress", {"step": "retrieval", "progress": 40, "message": f"检索到 {len(sources)} 条相关结果"})

    # 7. tool_decision - 工具决策（如有工具调用）
    tool_calls = resp_dict.get("tool_calls", [])
    if tool_calls:
        yield _format_sse("progress", {"step": "tool_decision", "progress": 50, "message": "正在进行工具决策"})
        yield _format_sse("agent_trace", {
            "workflow": "langgraph_rag_agent",
            "node": "tool_decision",
            "status": "completed",
        })

    # 8. generation - 答案生成
    yield _format_sse("progress", {"step": "generation", "progress": 65, "message": "正在生成回答"})
    yield _format_sse("agent_trace", {
        "workflow": "langgraph_rag_agent",
        "node": "answer_builder",
        "status": "completed",
    })

    # 9. risk_highlight - 风险高亮
    yield _format_sse("progress", {"step": "risk_highlight", "progress": 85, "message": "正在提取风险信息"})
    yield _format_sse("agent_trace", {
        "workflow": "langgraph_rag_agent",
        "node": "risk_highlight",
        "status": "completed",
    })

    # 10. finalize - 响应封装
    yield _format_sse("progress", {"step": "finalize", "progress": 92, "message": "正在封装响应"})
    yield _format_sse("agent_trace", {
        "workflow": "langgraph_rag_agent",
        "node": "response_finalize",
        "status": "completed",
    })

    # 11. tool_call 事件（与文档一致，仅返回 tool_name 和 status）
    for tc in tool_calls:
        yield _format_sse("tool_call", {
            "tool_name": tc.get("tool_name", ""),
            "status": tc.get("status", "completed")
        })

    # 最终 result 事件
    yield _format_sse("result", resp_dict)


async def stream_rag_workflow(req: ChatRequest) -> AsyncGenerator[str, None]:
    """
    SSE 流式 RAG 主链编排。

    内部委托 LangGraph StateGraph 执行，以统一两套工作流。
    输出为 SSE 事件流，格式与原有接口完全兼容。
    """
    run_id = str(uuid.uuid4())
    init_agent_trace(run_id)

    try:
        # 调用统一的 LangGraph 引擎获取完整响应
        response = await run_agent_workflow(req)

        # 转换为 dict 以提取字段
        resp_dict = response.model_dump() if hasattr(response, 'model_dump') else dict(response)
        route = resp_dict.get("route", "knowledge_query")

        # 生成 SSE 事件流
        async for event in _build_sse_events(resp_dict, route):
            yield event

    except Exception as e:
        logger.error(f"SSE stream failed: {e}", exc_info=True)
        yield _format_sse("error", {
            "code": "RAG_STREAM_ERROR",
            "message": str(e),
            "route": "agent_workflow",
            "status": "failed"
        })
