"""
SSE 流式 RAG 工作流

与 langgraph_workflow.py 保持一致的逻辑，但输出为 SSE 流式事件。
适用于需要实时展示推理进度的场景。

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

import json
import logging
import uuid
from typing import AsyncGenerator, List, Dict, Any, Optional
from ..schemas import ChatRequest, RiskHighlightObject
from ..agent.langgraph_workflow import VALID_ROUTES
from ..agent.tool_executor import execute_tool, init_agent_trace, update_agent_trace
from ..retrieval.rewrite_service import rewrite_and_classify
from ..retrieval.retriever import retrieve
from .chat_service import _call_llm
from .answer_builder import build_response
from .guardrails import check_input, extract_risk_highlights
from ..rules.matcher import apply_rejection_rules, apply_rule_answers
from ..rules.store import add_rejection_log
from ..utils import detect_phi, mask_phi

logger = logging.getLogger(__name__)


async def stream_rag_workflow(req: ChatRequest) -> AsyncGenerator[str, None]:
    """
    SSE 流式 RAG 主链编排。

    产生以下 SSE 事件：
    - progress: 进度更新
    - agent_trace: 节点执行轨迹
    - tool_call: 工具调用状态
    - result: 最终结果
    - error: 错误信息
    """

    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    run_id = str(uuid.uuid4())
    init_agent_trace(run_id)

    # 初始化状态
    is_blocked = False
    blocked_response = None
    rewritten_query = ""
    route = ""
    chunks = []
    tool_calls_result = []
    tool_result = None
    answer = ""
    risk_highlights: List[RiskHighlightObject] = []
    phi_detected = False  # 输入中是否检测到 PHI

    try:
        # ===== 节点1: policy_check =====
        is_safe, hit_words = check_input(req.question)
        if not is_safe:
            blocked_response = build_response(
                req, f"输入包含违规词汇: {', '.join(hit_words)}",
                [], "general_chat", 0.0, "blocked", "敏感词拦截"
            )
            is_blocked = True
            yield format_sse("error", blocked_response.dict())
            return

        update_agent_trace(run_id, "policy_check", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "policy_check", "status": "completed"})

        # ===== 节点2: phi_guard =====
        yield format_sse("progress", {"step": "phi_guard", "progress": 5, "message": "正在进行安全检查"})
        input_phi = detect_phi(req.question)
        ctx_phi = detect_phi(req.patient_context.summary_text) if req.patient_context else []
        if input_phi or ctx_phi:
            phi_detected = True
            logger.warning(f"PHI guard detected: input={input_phi}, context={ctx_phi}")
        update_agent_trace(run_id, "phi_guard", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "phi_guard", "status": "completed"})

        # ===== 节点3: rejection_check =====
        yield format_sse("progress", {"step": "rejection_check", "progress": 6, "message": "正在进行规则过滤"})
        rejection_result = apply_rejection_rules(req.question)
        if rejection_result:
            if rejection_result.log_only:
                try:
                    asyncio.create_task(asyncio.to_thread(
                        add_rejection_log,
                        rule_id=rejection_result.rule_id,
                        rule_pattern=rejection_result.rule_pattern,
                        user_question=req.question,
                        action="logged",
                        conversation_id=req.conversation_id,
                    ))
                except Exception as e:
                    logger.warning(f"Failed to log rejection: {e}")
            else:
                try:
                    asyncio.create_task(asyncio.to_thread(
                        add_rejection_log,
                        rule_id=rejection_result.rule_id,
                        rule_pattern=rejection_result.rule_pattern,
                        user_question=req.question,
                        action="rejected",
                        conversation_id=req.conversation_id,
                    ))
                except Exception as e:
                    logger.warning(f"Failed to log rejection: {e}")

                blocked_response = build_response(
                    req,
                    rejection_result.reject_reason,
                    [],
                    "general_chat",
                    0.0,
                    "blocked",
                    f"拒绝规则 rule_id={rejection_result.rule_id}"
                )
                yield format_sse("result", blocked_response.dict())
                return

        update_agent_trace(run_id, "rejection_check", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "rejection_check", "status": "completed"})

        # ===== 节点4: rule_match =====
        yield format_sse("progress", {"step": "rule_match", "progress": 8, "message": "正在匹配规则回答"})
        rule_match_result = apply_rule_answers(req.question)
        if rule_match_result:
            rule_response = build_response(
                req,
                rule_match_result.answer,
                [],
                "rule_answer",
                1.0,
                "completed",
                blocked_reason=f"规则回答 rule_id={rule_match_result.rule_id}"
            )
            update_agent_trace(run_id, "rule_match", "completed")
            yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "rule_match", "status": "completed"})
            yield format_sse("result", rule_response.dict())
            return

        update_agent_trace(run_id, "rule_match", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "rule_match", "status": "completed"})

        # ===== 节点5: intent_route =====
        yield format_sse("progress", {"step": "intent_route", "progress": 12, "message": "正在分析问题意图"})

        # 优先检查 tool_payload
        if req.options.get("tool_payload"):
            route = "tool_call"
            rewritten_query = req.question
        elif req.patient_context:
            route = "patient_context_query"
            rewritten_query = req.question
        else:
            rewritten_query, route = await rewrite_and_classify(req.question, req.history)

        if route not in VALID_ROUTES:
            route = "knowledge_query"

        # intent_route 进度已完成（step="intent_route" 在 progress 事件中）
        update_agent_trace(run_id, "intent_route", "completed")

        # ===== 节点6: rewrite =====
        yield format_sse("progress", {"step": "rewrite", "progress": 17, "message": "正在改写查询"})

        if route in ["knowledge_query", "patient_context_query"] and req.history:
            # 多轮对话场景的查询扩展
            context_entities = []
            for hist in req.history[-3:]:
                entities = re.findall(r'[^，,。\s]{2,4}(?:症|癌|瘤|病|药|治疗)', hist.get("content", ""))
                context_entities.extend(entities[:3])

            if context_entities:
                unique_entities = list(set(context_entities))[:5]
                rewritten_query = f"{rewritten_query} {' '.join(unique_entities)}"

        update_agent_trace(run_id, "rewrite", "completed")

        # ===== 节点7: retrieval =====
        if route in ["knowledge_query", "patient_context_query", "agent_workflow"]:
            yield format_sse("progress", {"step": "retrieval", "progress": 35, "message": "正在检索知识库"})

            top_k = req.options.get("top_k", 5)
            threshold = req.options.get("similarity_threshold", 0.35)
            use_rerank = req.options.get("use_rerank", False)
            chunks, is_retrieval_blocked = await retrieve(rewritten_query, req.kb_ids, top_k, threshold, use_rerank=use_rerank)

            if is_retrieval_blocked:
                blocked_response = build_response(
                    req, "知识库中未找到高置信度依据，请尝试调整问题表述或联系管理员检查知识库内容。",
                    [], route, 0.0, "blocked", "低置信度阻断"
                )
                yield format_sse("result", blocked_response.dict())
                return

            update_agent_trace(run_id, "retrieval", "completed")
            yield format_sse("progress", {"step": "retrieval", "progress": 40, "message": f"检索到 {len(chunks)} 条相关结果"})
        elif route == "general_chat":
            yield format_sse("progress", {"step": "retrieval", "progress": 40, "message": "闲聊模式，跳过检索"})

        # ===== 节点8: tool_decision =====
        if route == "tool_call":
            yield format_sse("progress", {"step": "tool_decision", "progress": 55, "message": "正在执行工具调用"})

            tool_payload = req.options.get("tool_payload", {})
            if tool_payload:
                tool_name = tool_payload.get("tool_name", "pandas_analyzer")
                args = tool_payload.get("arguments", {})

                yield format_sse("tool_call", {"tool_name": tool_name, "status": "running"})
                tool_result = await execute_tool(tool_name, args)
                yield format_sse("tool_call", {"tool_name": tool_name, "status": tool_result.get("status", "failed")})

                tool_calls_result.append({
                    "tool_name": tool_name,
                    "arguments": args,
                    "status": tool_result.get("status"),
                    "output_summary": str(tool_result.get("result", ""))[:200]
                })

            update_agent_trace(run_id, "tool_decision", "completed")
            yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "tool_decision", "status": "completed"})

        # ===== 节点9: answer_builder =====
        yield format_sse("progress", {"step": "generation", "progress": 65, "message": "正在生成回答"})

        context_parts = []

        # 患者上下文
        if req.patient_context:
            context_parts.append(f"【患者上下文】：{req.patient_context.summary_text}")

        # 知识库内容
        if chunks:
            chunks_text = "\n".join([c["text"] for c in chunks])
            context_parts.append(f"【知识库参考】：\n{chunks_text}")

        # 工具结果
        if tool_result:
            tool_result_text = str(tool_result.get("result", ""))
            context_parts.append(f"【工具分析结果】：{tool_result_text}")

        context = "\n\n".join(context_parts) if context_parts else ""

        if not context:
            if route == "general_chat":
                answer = "您好，我是医学知识助手。请问有什么医学问题可以帮您解答？"
            else:
                answer = "抱歉，知识库检索未返回相关参考内容，无法生成回答。"
        else:
            answer = await _call_llm(req.question, context)

        update_agent_trace(run_id, "answer_builder", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "answer_builder", "status": "completed"})

        # 如果输入中检测到 PHI，对生成的 answer 进行脱敏（防止 LLM 从上下文中泄露）
        if phi_detected and answer:
            answer = mask_phi(answer)

        # ===== 节点10: risk_highlight =====
        yield format_sse("progress", {"step": "risk_highlight", "progress": 85, "message": "正在提取风险信息"})
        risk_highlights = extract_risk_highlights(answer)
        update_agent_trace(run_id, "risk_highlight", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "risk_highlight", "status": "completed"})

        # ===== 节点11: response_finalize =====
        yield format_sse("progress", {"step": "finalize", "progress": 95, "message": "正在封装响应"})

        confidence = chunks[0]["score"] if chunks else 0.8

        # 构建 tool_calls 对象
        from ..schemas import ToolCallObject
        tool_call_objects = []
        if tool_calls_result:
            for tc in tool_calls_result:
                tool_call_objects.append(ToolCallObject(
                    tool_name=tc["tool_name"],
                    arguments=tc["arguments"],
                    status=tc["status"],
                    output_summary=tc["output_summary"]
                ))

        final_resp = build_response(
            req,
            answer,
            chunks,
            route,
            confidence,
            "completed",
            tool_calls=tool_call_objects,
            risk_highlights=risk_highlights
        )

        update_agent_trace(run_id, "response_finalize", "completed")
        yield format_sse("agent_trace", {"workflow": "langgraph_rag_agent", "node": "response_finalize", "status": "completed"})

        yield format_sse("result", final_resp.dict())

    except Exception as e:
        logger.error(f"Stream RAG workflow failed: {e}", exc_info=True)
        yield format_sse("error", {"code": "RAG_STREAM_ERROR", "message": str(e)})
