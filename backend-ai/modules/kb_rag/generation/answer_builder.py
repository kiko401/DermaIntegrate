import logging
import httpx
import re
from typing import List, Optional
from ..schemas import ChatRequest, ChatResponse, ToolCallObject, AgentTraceObject, RiskHighlightObject
from .guardrails import mask_output, extract_risk_highlights
from ..retrieval.citation import build_citations
from ..utils import generate_trace_id, generate_message_id
from ..config import get_integration_api_key, get_integration_base_url, get_integration_model

logger = logging.getLogger(__name__)

# 超时配置（从 shared/config 统一读取）
from shared.config import LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT, LLM_WRITE_TIMEOUT, LLM_POOL_TIMEOUT
DEFAULT_LLM_TIMEOUT = httpx.Timeout(
    connect=LLM_CONNECT_TIMEOUT,
    read=LLM_READ_TIMEOUT,
    write=LLM_WRITE_TIMEOUT,
    pool=LLM_POOL_TIMEOUT,
)

DISCLAIMER = "⚠️ 本回答由 AI 基于知识库生成，仅供参考，不能替代执业医师临床判断"


def _truncate_answer(answer: str, max_length: int, max_paragraphs: int) -> str:
    """
    M-06 回答长度截断：
    - max_length > 0 时按字符数截断（保留完整句子）
    - max_paragraphs > 0 时按段落数截断
    两者可叠加，以先到达的条件为准。
    """
    if not answer:
        return answer

    # 1. 段落数截断
    if max_paragraphs > 0:
        paragraphs = answer.split("\n")
        if len(paragraphs) > max_paragraphs:
            answer = "\n".join(paragraphs[:max_paragraphs])
            if not answer.endswith("。"):
                answer += "。"
            answer += "\n（内容已按段落数截断）"

    # 2. 字符数截断（保留完整句子）
    if max_length > 0 and len(answer) > max_length:
        truncated = answer[:max_length]
        # 找到最后一个完整句子（句号/问号/感叹号/引号结束）
        sentence_end = re.search(r'[。？！」』]\s*[」』]?|[。？！.?!]', truncated[::-1])
        if sentence_end:
            cut = len(truncated) - sentence_end.end() + 1
            answer = truncated[:cut] + "\n（内容已按字数截断）"
        else:
            answer = truncated + "\n（内容已按字数截断）"

    return answer


async def _call_llm(prompt: str, context: str) -> str:
    """调用 LLM 生成回答。"""
    api_key = get_integration_api_key()
    base_url = get_integration_base_url()
    model = get_integration_model()

    if not api_key or not base_url:
        return "LLM 服务未配置，无法生成回答。"

    system_prompt = f"你是一个严谨的医学助手。请根据以下参考资料回答问题。\n参考资料:\n{context}\n\n要求：回答必须基于参考资料，不得捏造。"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_LLM_TIMEOUT) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3
                }
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        logger.error(f"LLM call timed out after {DEFAULT_LLM_TIMEOUT.connect}s connect + {DEFAULT_LLM_TIMEOUT.read}s read.")
        return "LLM 服务响应超时，请稍后重试。"
    except Exception as e:
        logger.error(f"LLM call failed: {e}. Returning context as fallback.")
        return context if context else "生成回答时发生错误，且无可用上下文。"


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

    # M-06: 回答长度截断
    opts = req.options or {}
    max_length = opts.get("max_length", 0) or 0
    max_paragraphs = opts.get("max_paragraphs", 0) or 0
    if max_length > 0 or max_paragraphs > 0:
        safe_answer = _truncate_answer(safe_answer, max_length, max_paragraphs)

    # 如果传入了预提取的风险高亮则使用，否则自动提取
    final_risk_highlights = risk_highlights if risk_highlights is not None else extract_risk_highlights(safe_answer)

    sources = build_citations(chunks) if chunks else []

    # 强制语义约束：blocked_reason 仅在 status=blocked 时有值
    final_blocked_reason: Optional[str] = blocked_reason if status == "blocked" else None

    # 置信度约束：文档规定 0~1，RRF 融合分可能超过 1.0，需截断
    final_confidence = min(confidence, 1.0)

    return ChatResponse(
        trace_id=generate_trace_id(),
        message_id=generate_message_id(),
        route=route,
        answer=safe_answer,
        sources=sources,
        confidence=final_confidence,
        blocked_reason=final_blocked_reason,
        risk_highlights=final_risk_highlights,
        disclaimer=DISCLAIMER,
        tool_calls=tool_calls,
        agent_trace=agent_trace,
        status=status
    )
