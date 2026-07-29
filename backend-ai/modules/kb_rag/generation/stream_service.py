"""
SSE 流式 RAG 工作流

以 LangGraph StateGraph 为唯一执行引擎，本模块为 SSE 适配层。
通过 LangGraph 的 astream_events API 实现真正的实时节点进度流式推送，
用户在检索/生成等耗时段都能看到实时进度，而非等待完整执行后才知道结果。

工作流节点（12节点，与 langgraph_workflow.py 一致）：
1. policy_check       -> 输入安全检查
2. phi_guard          -> PHI 二次守护
3. rejection_check    -> 拒绝规则检查
4. rule_match         -> 规则回答匹配
5. intent_route       -> 意图识别与路由
6. rewrite            -> 查询改写
7. query_type_classify -> 查询类型分类（guideline vs case）
8. retrieval          -> 知识库检索
9. tool_decision      -> 工具调用决策
10. answer_builder    -> 答案生成
11. risk_highlight     -> 风险高亮提取
12. response_finalize  -> 响应封装
"""

import json
import logging
import uuid
from typing import AsyncGenerator, Any, Dict

from ..schemas import ChatRequest
from ..agent.langgraph_workflow import app_workflow
from ..agent.tool_executor import init_agent_trace

logger = logging.getLogger(__name__)


def _format_sse(event: str, data: Any) -> str:
    """将数据格式化为 SSE 事件字符串"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# 节点 -> (进度百分比, 开始消息, 结束消息)
NODE_PROGRESS: Dict[str, tuple[int, str, str]] = {
    "policy_check":        (8,  "正在进行输入安全检查",       "安全检查通过"),
    "phi_guard":          (12, "正在进行 PHI 脱敏检测",       "PHI 检测完成"),
    "rejection_check":    (16, "正在进行拒绝规则检查",        "规则检查通过"),
    "rule_match":         (20, "正在进行规则匹配",            "规则匹配完成"),
    "intent_route":       (28, "正在进行意图识别与路由",      "意图识别完成"),
    "rewrite":            (35, "正在进行查询改写",             "查询改写完成"),
    "query_type_classify":(42, "正在进行查询类型分类",        "查询类型分类完成"),
    "retrieval":          (60, "正在检索知识库",              "检索完成"),
    "tool_decision":      (60, "正在进行工具决策",            "工具决策完成"),
    "answer_builder":     (78, "正在生成回答",               "回答生成完成"),
    "risk_highlight":     (88, "正在提取风险高亮",            "风险高亮提取完成"),
    "response_finalize":  (95, "正在封装响应",               "响应封装完成"),
}


async def stream_rag_workflow(req: ChatRequest) -> AsyncGenerator[str, None]:
    """
    SSE 流式 RAG 主链编排。

    通过 astream_events 实时获取 LangGraph 各节点执行完成事件，
    并立即推送给客户端。用户在检索和生成等耗时段均能看到实时进度。

    SSE 事件顺序：
    - progress: 节点进度事件 (step, progress%, message)
    - agent_trace: 节点追踪事件 (workflow, node, status)
    - chunks: 检索完成时返回的参考资料
    - result: 最终响应
    - error: 异常信息
    """
    run_id = str(uuid.uuid4())
    init_agent_trace(run_id)

    # 初始化状态（与 run_agent_workflow 相同）
    initial_state = {
        "req": req,
        "run_id": run_id,
        "rewritten_query": "",
        "route": "",
        "query_type": "",
        "chunks": [],
        "is_blocked": False,
        "phi_detected": False,
        "tool_result": None,
        "tool_call_obj": None,
        "answer": "",
        "risk_highlights": [],
        "response": None,
    }

    resp_dict = None
    seen_nodes: set[str] = set()

    try:
        # 使用 astream_events 获取真实实时节点完成事件
        # LangGraph 1.2.x 使用 on_chain_start / on_chain_stream / on_chain_end
        async for event in app_workflow.astream_events(initial_state, config={"recursion_limit": 50}):
            event_type = event.get("event")
            event_name = event.get("name", "")

            # 0. 节点开始事件 -> 发送 thinking 提示（让用户知道接下来要做什么）
            if event_type == "on_chain_start":
                node_name = event_name
                if node_name in NODE_PROGRESS:
                    _, start_msg, _ = NODE_PROGRESS[node_name]
                    yield _format_sse("thinking", {
                        "step": node_name,
                        "message": start_msg
                    })

            # 1. 节点结束事件 -> 发送进度和追踪事件
            elif event_type == "on_chain_end":
                node_name = event_name
                # 忽略顶层 LangGraph 链结束事件（它包含整个工作流输出）
                if node_name == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict):
                        resp_dict = output.get("response")
                        if resp_dict is None:
                            resp_dict = output
                    elif output is not None:
                        resp_dict = output
                    continue

                if node_name in NODE_PROGRESS and node_name not in seen_nodes:
                    seen_nodes.add(node_name)
                    progress_pct, start_msg, end_msg = NODE_PROGRESS[node_name]

                    # 检索节点特殊处理：提取 chunks 数量
                    if node_name == "retrieval":
                        state_after = event.get("data", {}).get("output", {})
                        chunks = state_after.get("chunks", []) if isinstance(state_after, dict) else []
                        chunk_count = len(chunks) if chunks else 0
                        msg = f"检索到 {chunk_count} 条相关结果" if chunk_count > 0 else end_msg
                        yield _format_sse("progress", {
                            "step": node_name,
                            "progress": progress_pct,
                            "message": msg,
                            "chunks_count": chunk_count
                        })
                        # 检索完成后立即推送 chunks（让前端可以展示参考来源）
                        if chunks:
                            yield _format_sse("chunks", {"chunks": chunks})
                    else:
                        yield _format_sse("progress", {
                            "step": node_name,
                            "progress": progress_pct,
                            "message": end_msg
                        })

                    # 发送 agent_trace 事件
                    yield _format_sse("agent_trace", {
                        "workflow": "langgraph_rag_agent",
                        "node": node_name,
                        "status": "completed",
                    })

                # 所有普通节点的 on_chain_end 已在上面的 on_chain_end 分支处理完，无需额外逻辑

        # 3. 发送最终 result 事件
        if resp_dict is not None:
            # 转换 Pydantic 模型为 dict
            if hasattr(resp_dict, "model_dump"):
                resp_dict = resp_dict.model_dump()
            yield _format_sse("result", resp_dict)
        else:
            # 工作流异常，未产生有效响应
            yield _format_sse("result", {
                "answer": "智能体工作流执行异常，未生成有效响应",
                "route": "agent_workflow",
                "status": "failed",
                "chunks": [],
                "confidence": 0.0,
            })

    except Exception as e:
        logger.error(f"SSE stream failed: {e}", exc_info=True)
        yield _format_sse("error", {
            "code": "RAG_STREAM_ERROR",
            "message": str(e),
            "route": "agent_workflow",
            "status": "failed"
        })
