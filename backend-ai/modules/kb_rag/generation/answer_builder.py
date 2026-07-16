import logging
from typing import List, Optional
from ..schemas import ChatRequest, ChatResponse, ToolCallObject, AgentTraceObject, RiskHighlightObject
from .guardrails import mask_output, extract_risk_highlights
from ..retrieval.citation import build_citations
from ..utils import generate_trace_id, generate_message_id

logger = logging.getLogger(__name__)

DISCLAIMER = "⚠️ 本回答由 AI 基于知识库生成，仅供参考，不能替代执业医师临床判断"


def build_response(
        req: ChatRequest,
        answer: str,
        chunks: List[dict],
        route: str,
        confidence: float,
        status: str = "completed",
        blocked_reason: Optional[str] = None,
        tool_calls: List[ToolCallObject] = [],
        agent_trace: Optional[AgentTraceObject] = None,
        risk_highlights: Optional[List[RiskHighlightObject]] = None
) -> ChatResponse:
    """
    组装最终的 ChatResponse，包含脱敏、风险高亮和免责声明注入。

    Args:
        req: 原始请求对象
        answer: 生成的答案文本
        chunks: 检索到的文档片段
        route: 路由类型
        confidence: 置信度
        status: 状态
        blocked_reason: 阻断原因
        tool_calls: 工具调用列表
        agent_trace: Agent执行轨迹
        risk_highlights: 预提取的风险高亮列表（可选，如未提供则自动提取）
    """
    safe_answer = mask_output(answer)

    # 如果传入了预提取的风险高亮则使用，否则自动提取
    final_risk_highlights = risk_highlights if risk_highlights is not None else extract_risk_highlights(safe_answer)

    sources = build_citations(chunks) if chunks else []

    return ChatResponse(
        trace_id=generate_trace_id(),
        message_id=generate_message_id(),
        route=route,
        answer=safe_answer,
        sources=sources,
        confidence=confidence,
        blocked_reason=blocked_reason,
        risk_highlights=final_risk_highlights,
        disclaimer=DISCLAIMER,
        tool_calls=tool_calls,
        agent_trace=agent_trace,
        status=status
    )
