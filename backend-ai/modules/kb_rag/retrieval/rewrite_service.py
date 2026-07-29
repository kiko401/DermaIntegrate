import json
import logging
import httpx
from typing import Tuple, Optional
from shared.config import REWRITE_CONNECT_TIMEOUT, REWRITE_READ_TIMEOUT

logger = logging.getLogger(__name__)

VALID_ROUTES = ["knowledge_query", "patient_context_query", "tool_call", "general_chat", "agent_workflow", "rule_answer"]

# rewrite 超时配置（从 shared/config 统一读取）
REWRITE_TIMEOUT = httpx.Timeout(
    connect=REWRITE_CONNECT_TIMEOUT,
    read=REWRITE_READ_TIMEOUT,
    write=10.0,
    pool=10.0,
)


async def rewrite_and_classify(query: str, history: list) -> Tuple[str, str]:
    """
    调用 LLM 进行问题重写与意图分类。
    始终调用 LLM 进行查询扩展，将短问题扩展为富含医学术语的详细查询，
    弥补轻量级 embedding 模型对中文医学文本表达能力的不足。
    返回: (rewritten_query, route)
    """
    from ..config import get_integration_api_key, get_integration_base_url, get_integration_model
    api_key = get_integration_api_key()
    base_url = get_integration_base_url()
    model = get_integration_model()

    if not api_key or not base_url:
        logger.warning("LLM API not configured. Skipping rewrite.")
        return query, "knowledge_query"

    history_context = f"历史对话: {json.dumps(history, ensure_ascii=False)}\n" if history else "历史对话: 无\n"

    prompt = f"""你是一个医学问答系统的意图路由与查询改写助手。

你的任务是：将用户的简短问题扩展为详细的医学检索查询，提升向量检索召回率。

规则：
1. 意图路由必须是以下之一：{", ".join(VALID_ROUTES)}
2. 查询改写要求：
   - 将短查询（如"黑色素瘤治疗"）扩展为完整医学问题（如"黑色素瘤的治疗方案包括哪些 靶向治疗药物 免疫治疗药物 化疗方案"）
   - 融入相关医学术语（如分期、基因突变、药物名称等）
   - 去除代词指代，确保查询独立可检索
   - 如果原查询已足够详细，保持不变
3. 输出格式为纯 JSON，不要 markdown 标记：
{{"rewritten_query": "扩展后的查询", "route": "意图分类"}}
"""

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"{history_context}当前问题: {query}"}
    ]

    try:
        async with httpx.AsyncClient(timeout=REWRITE_TIMEOUT) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": messages, "temperature": 0.1}
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

        # 尝试解析 JSON
        result = json.loads(content.strip())
        rewritten = result.get("rewritten_query", query)
        route = result.get("route", "knowledge_query")

        if route not in VALID_ROUTES:
            route = "knowledge_query"

        return rewritten, route

    except httpx.TimeoutException:
        logger.warning(f"Rewrite timed out after {REWRITE_TIMEOUT.connect}s connect + {REWRITE_TIMEOUT.read}s read. Falling back to default.")
        return query, "knowledge_query"
    except Exception as e:
        logger.error(f"Rewrite and classify failed: {e}. Falling back to default.")
        return query, "knowledge_query"
