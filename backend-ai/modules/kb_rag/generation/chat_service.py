import os
import httpx
import logging
from typing import List
from ..schemas import ChatRequest, ChatResponse
from .guardrails import check_input
from ..retrieval.rewrite_service import rewrite_and_classify
from ..retrieval.retriever import retrieve
from .answer_builder import build_response

logger = logging.getLogger(__name__)

# 5s connect + 30s read，防止 Windows TCP 连接 hang 拖满 60s OS 超时
DEFAULT_LLM_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=30.0)


async def _call_llm(prompt: str, context: str) -> str:
    """调用 LLM 生成回答。"""
    api_key = os.getenv("INTEGRATION_API_KEY")
    base_url = os.getenv("INTEGRATION_BASE_URL")
    model = os.getenv("INTEGRATION_MODEL", "deepseek-v4-flash")

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


async def run_rag_workflow(req: ChatRequest) -> ChatResponse:
    """非流式 RAG 主链编排。"""

    is_safe, hit_words = check_input(req.question)
    if not is_safe:
        return build_response(req, f"输入包含违规词汇: {', '.join(hit_words)}", [], "general_chat", 0.0, "blocked",
                              "输入敏感词拦截")

    rewritten_query, route = await rewrite_and_classify(req.question, req.history)

    if req.patient_context:
        route = "patient_context_query"

    chunks = []
    is_blocked = False
    if route in ["knowledge_query", "patient_context_query", "agent_workflow"]:
        top_k = req.options.get("top_k", 5)
        threshold = req.options.get("similarity_threshold", 0.35)
        chunks, is_blocked = await retrieve(rewritten_query, req.kb_ids, top_k, threshold)

        if is_blocked:
            return build_response(req, "知识库中未找到高置信度依据。", [], route, 0.0, "blocked", "低置信度阻断")

    context = "\n".join([c["text"] for c in chunks])
    if req.patient_context:
        context = f"患者上下文:\n{req.patient_context.summary_text}\n\n参考资料:\n{context}"

    answer = await _call_llm(req.question, context)

    confidence = chunks[0]["score"] if chunks else 0.8
    return build_response(req, answer, chunks, route, confidence, "completed")
