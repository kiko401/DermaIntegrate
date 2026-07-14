import os
import json
import logging
import httpx
from typing import Tuple

logger = logging.getLogger(__name__)

VALID_ROUTES = ["knowledge_query", "patient_context_query", "tool_call", "general_chat", "agent_workflow"]

# 3s connect + 10s read，防止 rewrite 拖满 OS TCP 超时
REWRITE_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=10.0)


async def rewrite_and_classify(query: str, history: list) -> Tuple[str, str]:
    """
    调用 LLM 进行问题重写与意图分类
    返回: (rewritten_query, route)
    """
    # 如果没有历史记录，直接返回原问题，避免不必要的 LLM 调用
    if not history:
        return query, "knowledge_query"

    api_key = os.getenv("INTEGRATION_API_KEY")
    base_url = os.getenv("INTEGRATION_BASE_URL")
    model = os.getenv("INTEGRATION_MODEL", "deepseek-v4-flash")

    if not api_key or not base_url:
        logger.warning("LLM API not configured. Skipping rewrite.")
        return query, "knowledge_query"

    prompt = f"""
你是一个医学问答系统的意图路由与查询重写助手。
请根据用户的历史对话和当前问题，执行以下两个任务：
1. 判断当前问题的意图路由，必须是以下之一：{", ".join(VALID_ROUTES)}
   - knowledge_query: 查询医学知识库
   - patient_context_query: 针对当前患者上下文的提问
   - tool_call: 需要调用外部工具(如数据分析)
   - general_chat: 日常问候或闲聊
   - agent_workflow: 需要复杂多步推理的医学问题
2. 将当前问题重写为一个独立、清晰、无代词指代的查询语句。

请严格以纯 JSON 格式输出，不要包含 markdown 标记：
{{"rewritten_query": "重写后的查询", "route": "意图分类"}}
"""

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"历史对话: {json.dumps(history, ensure_ascii=False)}\n当前问题: {query}"}
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