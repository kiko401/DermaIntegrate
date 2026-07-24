"""
LangGraph 智能体工作流 - 完整业务实现

工作流设计（基于需求文档 UC-RAG-24 / M12）：
1. policy_check    -> 输入安全检查（敏感词过滤）
2. phi_guard       -> PHI 二次守护（检测患者敏感信息泄露风险）
3. intent_route    -> 意图识别与路由分类
4. rewrite         -> 查询改写与纠错
5. retrieval       -> 知识库向量检索
6. tool_decision   -> 工具调用决策与执行
7. answer_builder  -> LLM 答案生成
8. risk_highlight  -> 风险高亮提取（药名、剂量、禁忌等）
9. response_finalize -> 响应封装与元数据注入

路由类型（route）：
- knowledge_query      : 知识库问答
- patient_context_query: 患者上下文问答
- tool_call           : 工具调用
- general_chat        : 通用闲聊
- agent_workflow      : 复杂多步推理
"""

import os
import logging
import uuid
import asyncio
import functools
from typing import TypedDict, Optional, List, Dict, Any, Literal
from langgraph.graph import StateGraph, END
from ..schemas import (
    ChatRequest, ChatResponse, ToolCallObject, AgentTraceObject,
    RiskHighlightObject, PatientContextObject
)
from ..generation.guardrails import check_input, extract_risk_highlights
from ..retrieval.rewrite_service import rewrite_and_classify
from ..retrieval.retriever import retrieve
from ..generation.answer_builder import _call_llm
from ..generation.answer_builder import build_response
from .tool_executor import execute_tool, init_agent_trace, update_agent_trace, get_agent_run_trace
from ..rules.matcher import apply_rejection_rules, apply_rule_answers
from ..rules.store import add_rejection_log
from ..utils import detect_phi, mask_phi

logger = logging.getLogger(__name__)

# 路由类型白名单
VALID_ROUTES = ["knowledge_query", "patient_context_query", "tool_call", "general_chat", "agent_workflow", "rule_answer"]


class AgentState(TypedDict):
    """智能体工作流状态"""
    req: ChatRequest
    run_id: str
    rewritten_query: str
    route: str
    chunks: list
    is_blocked: bool
    phi_detected: bool
    tool_result: Optional[dict]
    tool_call_obj: Optional[ToolCallObject]
    answer: str
    risk_highlights: List[RiskHighlightObject]
    response: Optional[ChatResponse]


def node_handler(func):
    """节点装饰器：统一异常处理与状态更新"""
    @functools.wraps(func)
    async def wrapper(state: AgentState) -> AgentState:
        if state.get("is_blocked"):
            update_agent_trace(state["run_id"], func.__name__, "skipped")
            return state
        try:
            new_state = await func(state)
            update_agent_trace(state["run_id"], func.__name__, "completed")
            return new_state
        except Exception as e:
            logger.error(f"Node [{func.__name__}] exception: {e}", exc_info=True)
            state["is_blocked"] = True
            state["response"] = build_response(
                state["req"], f"处理节点 {func.__name__} 执行异常: {str(e)}",
                [], "agent_workflow", 0.0, "failed", str(e)
            )
            update_agent_trace(state["run_id"], func.__name__, "failed")
            return state
    return wrapper


@node_handler
async def policy_check(state: AgentState) -> AgentState:
    """
    节点1: 输入安全检查
    检查用户输入是否包含敏感词，如命中则阻断流程
    """
    req = state["req"]
    is_safe, hits = check_input(req.question)

    if not is_safe:
        logger.warning(f"Policy check blocked input: {hits}")
        state["response"] = build_response(
            req, f"输入包含违规词汇: {', '.join(hits)}",
            [], "general_chat", 0.0, "blocked", "敏感词拦截"
        )
        state["is_blocked"] = True

    return state


@node_handler
async def phi_guard(state: AgentState) -> AgentState:
    """
    节点2: PHI 二次守护
    检测患者敏感信息是否泄露到问题中（如患者姓名、住院号等）
    注：根据双域职责约束，PHI脱敏应在应用域完成，此处为二次兜底检测
    """
    req = state["req"]

    input_phi = detect_phi(req.question)
    ctx_phi = detect_phi(req.patient_context.summary_text) if req.patient_context else []

    if input_phi or ctx_phi:
        state["phi_detected"] = True
        logger.warning(
            f"PHI guard detected potential PHI leak. "
            f"Input PHI: {input_phi}, Context PHI: {ctx_phi}"
        )

    return state


@node_handler
async def rejection_check(state: AgentState) -> AgentState:
    """
    节点3: 拒绝规则检查
    命中拒绝规则 -> 阻断并返回拒绝原因（log_only=True仅记录不阻断）
    """
    req = state["req"]

    rejection_result = await apply_rejection_rules(req.question)
    if rejection_result:
        if rejection_result.log_only:
            # 仅记录日志，不阻断流程
            try:
                asyncio.create_task(add_rejection_log(
                    rule_id=rejection_result.rule_id,
                    rule_pattern=rejection_result.rule_pattern,
                    user_question=req.question,
                    action="logged",
                    conversation_id=req.conversation_id,
                ))
            except Exception as e:
                logger.warning(f"Failed to log rejection: {e}")
        else:
            # 拒绝回答
            try:
                asyncio.create_task(add_rejection_log(
                    rule_id=rejection_result.rule_id,
                    rule_pattern=rejection_result.rule_pattern,
                    user_question=req.question,
                    action="rejected",
                    conversation_id=req.conversation_id,
                ))
            except Exception as e:
                logger.warning(f"Failed to log rejection: {e}")

            state["response"] = build_response(
                req,
                rejection_result.reject_reason,
                [],
                "general_chat",
                0.0,
                "blocked",
                f"拒绝规则 rule_id={rejection_result.rule_id}"
            )
            state["is_blocked"] = True
            logger.info(f"Question rejected by rule_id={rejection_result.rule_id}")

    return state


@node_handler
async def rule_match(state: AgentState) -> AgentState:
    """
    节点4: 规则回答匹配
    命中标准回答规则 -> 直接使用标准答案，跳过知识库检索
    """
    req = state["req"]

    rule_result = await apply_rule_answers(req.question)
    if rule_result:
        state["route"] = "rule_answer"  # 必须在 build_response 之前设置，供后续条件边判断
        state["response"] = build_response(
            req,
            rule_result.answer,
            [],
            "rule_answer",
            1.0,
            "completed",
        )
        state["is_blocked"] = True
        logger.info(f"Rule answer matched: rule_id={rule_result.rule_id}")

    return state


@node_handler
async def intent_route(state: AgentState) -> AgentState:
    """
    节点5: 意图识别与路由
    调用 LLM 进行问题分类，决定后续走知识问答、工具调用还是闲聊
    """
    req = state["req"]

    # 如果请求中明确指定了 tool_payload，优先走工具调用
    if req.options.get("tool_payload"):
        state["route"] = "tool_call"
        return state

    # 如果有患者上下文，优先考虑患者上下文问答
    if req.patient_context:
        state["route"] = "patient_context_query"
        return state

    # 调用 LLM 进行意图分类
    rewritten_query, route = await rewrite_and_classify(req.question, req.history)

    # 校验路由类型有效性
    if route not in VALID_ROUTES:
        route = "knowledge_query"

    state["rewritten_query"] = rewritten_query
    state["route"] = route

    logger.info(f"Intent route result: route={route}, rewritten_query={rewritten_query[:50]}...")
    return state


@node_handler
async def rewrite(state: AgentState) -> AgentState:
    """
    节点6: 查询改写
    对用户问题进行语义优化，提高检索召回
    注：已在 intent_route 中完成初步改写，此处可进行额外的查询扩展
    """
    req = state["req"]
    route = state["route"]

    # 只有知识问答和患者上下文问答需要改写
    if route not in ["knowledge_query", "patient_context_query"]:
        return state

    # 如果 rewrite 和 intent_route 结果相同，说明无需额外处理
    # 如果有历史记录，可以进行更多扩展
    if req.history and state["rewritten_query"] == req.question:
        # 多轮对话场景：尝试从历史中提取关键实体进行查询扩展
        context_entities = []
        for hist in req.history[-3:]:  # 取最近3轮
            # 简单策略：提取历史回答中的名词实体
            import re
            entities = re.findall(r'[^，,。\s]{2,4}(?:症|癌|瘤|病|药|治疗)', hist.get("content", ""))
            context_entities.extend(entities[:3])  # 每轮最多取3个

        if context_entities:
            # 将实体融入查询
            unique_entities = list(set(context_entities))[:5]
            state["rewritten_query"] = f"{state['rewritten_query']} {' '.join(unique_entities)}"
            logger.info(f"Query expanded with entities: {unique_entities}")

    return state


@node_handler
async def retrieval(state: AgentState) -> AgentState:
    """
    节点7: 知识库检索
    基于改写后的问题检索知识库，获取相关 chunks
    """
    req = state["req"]
    route = state["route"]

    # 只有知识问答类路由需要检索
    if route in ["general_chat", "tool_call"]:
        return state

    # 获取检索参数
    top_k = req.options.get("top_k", 5)
    threshold = req.options.get("similarity_threshold", 0.35)
    use_rerank = req.options.get("use_rerank", False)

    # 执行检索（含医生权限隔离）
    chunks, is_blocked = await retrieve(
        state["rewritten_query"],
        req.kb_ids,
        top_k,
        threshold,
        use_rerank=use_rerank,
        doctor_id=req.doctor_id,
    )

    state["chunks"] = chunks

    if is_blocked:
        logger.warning(f"Retrieval blocked due to low confidence. Query: {state['rewritten_query']}")
        state["response"] = build_response(
            req, "知识库中未找到高置信度依据，请尝试调整问题表述或联系管理员检查知识库内容。",
            [], route, 0.0, "blocked", "低置信度阻断"
        )
        state["is_blocked"] = True

    return state


@node_handler
async def tool_decision(state: AgentState) -> AgentState:
    """
    节点8: 工具调用决策与执行
    如果路由为 tool_call，则执行工具调用
    """
    req = state["req"]
    route = state["route"]

    if route != "tool_call":
        return state

    tool_payload = req.options.get("tool_payload", {})
    if not tool_payload:
        state["response"] = build_response(
            req, "检测到工具调用意图，但请求未携带必要的工具参数。",
            [], "tool_call", 0.0, "failed", "Missing tool payload"
        )
        state["is_blocked"] = True
        return state

    tool_name = tool_payload.get("tool_name", "pandas_analyzer")
    args = tool_payload.get("arguments", {})

    logger.info(f"Executing tool: {tool_name} with args: {args}")

    # 执行工具
    exec_result = await execute_tool(tool_name, args)

    # 构建工具调用对象
    exec_status = exec_result.get("status", "failed")
    exec_result_str = exec_result.get("result")
    output_summary: str | None = None
    if exec_status == "completed" and exec_result_str is not None:
        output_summary = str(exec_result_str)[:200]
    # status=failed 时 output_summary 固定为 None（文档规定）
    state["tool_call_obj"] = ToolCallObject(
        tool_name=tool_name,
        arguments=args,
        status=exec_status,
        output_summary=output_summary,
    )
    state["tool_result"] = exec_result

    return state


@node_handler
async def answer_builder(state: AgentState) -> AgentState:
    """
    节点9: LLM 答案生成
    基于检索结果和上下文生成最终答案
    """
    req = state["req"]
    route = state["route"]

    # 闲聊路由直接返回友好回复
    if route == "general_chat":
        context = "你是一个严谨的医学助手，请基于医学知识回答用户问题。"
        state["answer"] = await _call_llm(req.question, context)
        return state

    # 构建上下文
    context_parts = []

    # 1. 患者上下文
    if req.patient_context:
        context_parts.append(f"【患者上下文】：{req.patient_context.summary_text}")

    # 2. 检索到的知识库内容
    if state.get("chunks"):
        chunks_text = "\n".join([c["text"] for c in state["chunks"]])
        context_parts.append(f"【知识库参考】：\n{chunks_text}")

    # 3. 工具执行结果
    if state.get("tool_result"):
        tool_result_text = str(state["tool_result"].get("result", ""))
        context_parts.append(f"【工具分析结果】：{tool_result_text}")

    context = "\n\n".join(context_parts) if context_parts else ""

    # 调用 LLM 生成答案
    if not context:
        state["answer"] = "抱歉，知识库检索未返回相关参考内容，无法生成回答。建议您完善问题描述或联系管理员检查知识库配置。"
    else:
        state["answer"] = await _call_llm(req.question, context)

    # 如果输入中检测到 PHI，对生成的 answer 进行脱敏（防止 LLM 从上下文中泄露）
    if state.get("phi_detected") and state["answer"]:
        state["answer"] = mask_phi(state["answer"])

    return state


@node_handler
async def risk_highlight(state: AgentState) -> AgentState:
    """
    节点10: 风险高亮提取
    从生成的答案中提取药名、剂量、禁忌等关键风险信息
    """
    answer = state.get("answer", "")

    if not answer:
        return state

    # 使用 guardrails 中的 extract_risk_highlights
    highlights = extract_risk_highlights(answer)

    state["risk_highlights"] = highlights

    if highlights:
        logger.info(f"Extracted {len(highlights)} risk highlights from answer")

    return state


@node_handler
async def response_finalize(state: AgentState) -> AgentState:
    """
    节点11: 响应封装
    组装最终的 ChatResponse，包含答案、来源、风险高亮等
    """
    req = state["req"]
    route = state["route"]

    # 如果已被阻断，直接使用已有的 response
    if state.get("response"):
        return state

    # 计算置信度（使用归一化 dense 分数，与阻断阈值单位一致，0~1范围）
    chunks = state.get("chunks", [])
    if chunks:
        confidence = max(c.get("dense_norm", 0.0) for c in chunks)
    else:
        confidence = 0.8  # 闲聊等场景的默认置信度

    # 构建 tool_calls 列表
    tool_calls = []
    if state.get("tool_call_obj"):
        tool_calls = [state["tool_call_obj"]]

    # 封装最终响应
    state["response"] = build_response(
        req,
        state["answer"],
        chunks,
        route,
        confidence,
        "completed",
        tool_calls=tool_calls,
        risk_highlights=state.get("risk_highlights", [])
    )

    return state


# ============ 构建 LangGraph 工作流 ============

workflow = StateGraph(AgentState)

# 添加节点（11节点）
workflow.add_node("policy_check", policy_check)
workflow.add_node("phi_guard", phi_guard)
workflow.add_node("rejection_check", rejection_check)
workflow.add_node("rule_match", rule_match)
workflow.add_node("intent_route", intent_route)
workflow.add_node("rewrite", rewrite)
workflow.add_node("retrieval", retrieval)
workflow.add_node("tool_decision", tool_decision)
workflow.add_node("answer_builder", answer_builder)
workflow.add_node("risk_highlight", risk_highlight)
workflow.add_node("response_finalize", response_finalize)

# 设置入口
workflow.set_entry_point("policy_check")

# 定义边（条件分支）
workflow.add_edge("policy_check", "phi_guard")
workflow.add_edge("phi_guard", "rejection_check")
workflow.add_edge("rejection_check", "rule_match")
workflow.add_edge("rule_match", "intent_route")
workflow.add_edge("intent_route", "rewrite")

# rewrite 之后根据路由分支（is_blocked 优先，确保规则命中等阻断场景直接到达终点）
workflow.add_conditional_edges(
    "rewrite",
    lambda state: "blocked" if state.get("is_blocked") else state["route"],
    {
        "blocked": "response_finalize",  # 被阻断直接结束
        "knowledge_query": "retrieval",
        "patient_context_query": "retrieval",
        "tool_call": "tool_decision",
        "general_chat": "answer_builder",
        "agent_workflow": "retrieval",  # agent_workflow 也先检索
        "rule_answer": "response_finalize",  # 规则命中的直接走响应封装（is_blocked=True，response已构建）
    }
)

# 检索后进入工具决策或直接生成答案
workflow.add_conditional_edges(
    "retrieval",
    lambda state: "blocked" if state.get("is_blocked") else state["route"],
    {
        "blocked": "response_finalize",  # 被阻断直接结束
        "tool_call": "tool_decision",
        "knowledge_query": "answer_builder",
        "patient_context_query": "answer_builder",
        "agent_workflow": "answer_builder",
        "general_chat": "answer_builder",
    }
)

# 工具决策后进入答案生成
workflow.add_edge("tool_decision", "answer_builder")

# 答案生成后提取风险高亮
workflow.add_edge("answer_builder", "risk_highlight")

# 风险高亮后封装响应
workflow.add_edge("risk_highlight", "response_finalize")

# 响应封装后结束
workflow.add_edge("response_finalize", END)

# 编译工作流
app_workflow = workflow.compile()


async def run_agent_workflow(req: ChatRequest) -> ChatResponse:
    """
    运行智能体工作流

    Args:
        req: ChatRequest 请求对象

    Returns:
        ChatResponse: 完整的响应对象
    """
    run_id = str(uuid.uuid4())
    init_agent_trace(run_id)

    # 初始化状态
    initial_state: AgentState = {
        "req": req,
        "run_id": run_id,
        "rewritten_query": "",
        "route": "",
        "chunks": [],
        "is_blocked": False,
        "phi_detected": False,
        "tool_result": None,
        "tool_call_obj": None,
        "answer": "",
        "risk_highlights": [],
        "response": None
    }

    try:
        # 执行工作流
        final_state = await app_workflow.ainvoke(initial_state)

        # 获取最终响应
        response = final_state.get("response")

        if not response:
            response = build_response(
                req,
                "智能体工作流执行异常，未生成有效响应",
                [],
                "agent_workflow",
                0.0,
                "failed",
                "No response generated"
            )

        # 附加执行轨迹
        trace = await get_agent_run_trace(run_id)
        if trace:
            response.agent_trace = trace

        return response

    except Exception as e:
        logger.error(f"Agent workflow failed: {e}", exc_info=True)
        return build_response(
            req,
            f"智能体工作流执行失败: {str(e)}",
            [],
            "agent_workflow",
            0.0,
            "failed",
            str(e)
        )


# ============ 辅助函数 ============

async def run_agent_workflow_simple(
    question: str,
    kb_ids: List[int],
    history: List[Dict[str, str]] = None,
    patient_context: Any = None,
    options: Dict[str, Any] = None
) -> ChatResponse:
    """
    简化的入口函数，直接传入参数运行工作流

    Args:
        question: 用户问题
        kb_ids: 知识库ID列表
        history: 历史对话
        patient_context: 患者上下文对象
        options: 配置选项

    Returns:
        ChatResponse: 完整的响应对象
    """
    req = ChatRequest(
        conversation_id=0,
        question=question,
        history=history or [],
        kb_ids=kb_ids,
        patient_context=patient_context,
        options=options or {}
    )

    return await run_agent_workflow(req)
