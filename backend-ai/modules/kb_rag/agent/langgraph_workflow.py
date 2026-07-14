import os
import logging
import uuid
import asyncio
import functools
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from ..schemas import ChatRequest, ChatResponse, ToolCallObject
from ..generation.guardrails import check_input
from ..retrieval.rewrite_service import rewrite_and_classify
from ..retrieval.retriever import retrieve
from ..generation.chat_service import _call_llm
from ..generation.answer_builder import build_response
from .tool_executor import execute_tool, init_agent_trace, update_agent_trace, get_agent_run_trace

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    req: ChatRequest
    run_id: str
    rewritten_query: str
    route: str
    chunks: list
    is_blocked: bool
    tool_result: Optional[dict]
    tool_call_obj: Optional[ToolCallObject]
    answer: str
    response: Optional[ChatResponse]


def node_handler(func):
    @functools.wraps(func)
    async def wrapper(state: AgentState) -> AgentState:
        if state.get("is_blocked"):
            return state
        try:
            new_state = await func(state)
            update_agent_trace(state["run_id"], func.__name__, "completed")
            return new_state
        except Exception as e:
            logger.error(f"Node [{func.__name__}] exception: {e}", exc_info=True)
            state["is_blocked"] = True
            state["response"] = build_response(
                state["req"], f"节点 {func.__name__} 执行异常", [], "agent_workflow", 0.0, "failed", str(e)
            )
            update_agent_trace(state["run_id"], func.__name__, "failed")
            return state

    return wrapper


@node_handler
async def policy_check(state: AgentState) -> AgentState:
    req = state["req"]
    is_safe, hits = check_input(req.question)
    if not is_safe:
        state["response"] = build_response(req, f"输入违规: {hits}", [], "general_chat", 0.0, "blocked", "敏感词拦截")
        state["is_blocked"] = True
    return state


@node_handler
async def phi_guard(state: AgentState) -> AgentState:
    return state


@node_handler
async def intent_route(state: AgentState) -> AgentState:
    rq, route = await rewrite_and_classify(state["req"].question, state["req"].history)
    if state["req"].options.get("tool_payload"):
        route = "tool_call"
    state["rewritten_query"] = rq
    state["route"] = route
    return state


@node_handler
async def rewrite(state: AgentState) -> AgentState:
    return state


@node_handler
async def retrieval(state: AgentState) -> AgentState:
    if state["route"] == "general_chat":
        return state
    chunks, is_blocked = await retrieve(state["rewritten_query"], state["req"].kb_ids)
    state["chunks"] = chunks
    if is_blocked:
        state["response"] = build_response(state["req"], "未找到高置信度依据", [], state["route"], 0.0, "blocked",
                                           "低置信度阻断")
        state["is_blocked"] = True
    return state


@node_handler
async def tool_decision(state: AgentState) -> AgentState:
    if state["route"] == "tool_call":
        req = state["req"]
        tool_payload = req.options.get("tool_payload", {})
        if tool_payload:
            tool_name = tool_payload.get("tool_name", "pandas_analyzer")
            args = tool_payload.get("arguments", {})
            exec_result = await execute_tool(tool_name, args)

            state["tool_call_obj"] = ToolCallObject(
                tool_name=tool_name,
                arguments=args,
                status=exec_result.get("status", "failed"),
                output_summary=str(exec_result.get("result", exec_result.get("error", "")))[:200]
            )
            state["tool_result"] = exec_result
        else:
            state["is_blocked"] = True
            state["response"] = build_response(req, "检测到工具调用意图，但请求未携带必要的数据参数。", [], "tool_call",
                                               0.0, "failed", "Missing tool payload")
    return state


@node_handler
async def tool_execute(state: AgentState) -> AgentState:
    return state


@node_handler
async def answer_builder(state: AgentState) -> AgentState:
    context = "\n".join([c["text"] for c in state.get("chunks", [])])
    if state.get("tool_result"):
        context += f"\n工具分析结果: {state['tool_result']}"
    state["answer"] = await _call_llm(state["req"].question, context)
    return state


@node_handler
async def risk_highlight(state: AgentState) -> AgentState:
    return state


@node_handler
async def response_finalize(state: AgentState) -> AgentState:
    tool_calls = [state["tool_call_obj"]] if state.get("tool_call_obj") else []
    state["response"] = build_response(
        state["req"], state["answer"], state.get("chunks", []), state["route"], 0.8, "completed",
        tool_calls=tool_calls
    )
    return state


workflow = StateGraph(AgentState)
workflow.add_node("policy_check", policy_check)
workflow.add_node("phi_guard", phi_guard)
workflow.add_node("intent_route", intent_route)
workflow.add_node("rewrite", rewrite)
workflow.add_node("retrieval", retrieval)
workflow.add_node("tool_decision", tool_decision)
workflow.add_node("tool_execute", tool_execute)
workflow.add_node("answer_builder", answer_builder)
workflow.add_node("risk_highlight", risk_highlight)
workflow.add_node("response_finalize", response_finalize)

workflow.set_entry_point("policy_check")
workflow.add_edge("policy_check", "phi_guard")
workflow.add_edge("phi_guard", "intent_route")
workflow.add_edge("intent_route", "rewrite")
workflow.add_edge("rewrite", "retrieval")
workflow.add_edge("retrieval", "tool_decision")
workflow.add_edge("tool_decision", "tool_execute")
workflow.add_edge("tool_execute", "answer_builder")
workflow.add_edge("answer_builder", "risk_highlight")
workflow.add_edge("risk_highlight", "response_finalize")
workflow.add_edge("response_finalize", END)

app_workflow = workflow.compile()


async def run_agent_workflow(req: ChatRequest) -> ChatResponse:
    run_id = str(uuid.uuid4())
    init_agent_trace(run_id)
    state = {
        "req": req, "run_id": run_id, "rewritten_query": "", "route": "",
        "chunks": [], "is_blocked": False, "tool_result": None, "tool_call_obj": None,
        "answer": "", "response": None
    }
    pipeline = [policy_check, phi_guard, intent_route, rewrite, retrieval,
                tool_decision, tool_execute, answer_builder, risk_highlight, response_finalize]
    for node_func in pipeline:
        state = await node_func(state)

    response = state.get("response") or build_response(
        req, "智能体工作流执行异常", [], "agent_workflow", 0.0, "failed", "Unknown error"
    )

    trace = await get_agent_run_trace(run_id)
    if trace:
        response.agent_trace = trace

    return response
