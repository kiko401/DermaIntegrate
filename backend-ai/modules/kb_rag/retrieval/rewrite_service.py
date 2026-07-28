import os
import json
import logging
import asyncio
import httpx
from typing import Tuple, Optional, Any
from shared.config import REWRITE_CONNECT_TIMEOUT, REWRITE_READ_TIMEOUT

logger = logging.getLogger(__name__)

VALID_ROUTES = ["knowledge_query", "patient_context_query", "tool_call", "general_chat", "agent_workflow"]

# rewrite 超时配置（从 shared/config 统一读取）
REWRITE_TIMEOUT = httpx.Timeout(
    connect=REWRITE_CONNECT_TIMEOUT,
    read=REWRITE_READ_TIMEOUT,
    write=10.0,
    pool=10.0,
)


async def rewrite_and_classify(query: str, history: list) -> Tuple[str, str]:
    """
    调用 LLM 进行问题重写与意图分类
    返回: (rewritten_query, route)
    """
    # 如果没有历史记录，直接返回原问题，避免不必要的 LLM 调用
    if not history:
        return query, "knowledge_query"

    from ..config import get_integration_api_key, get_integration_base_url, get_integration_model
    api_key = get_integration_api_key()
    base_url = get_integration_base_url()
    model = get_integration_model()

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

    def _sync_http_call() -> str:
        """同步 HTTP 调用，封装为 to_thread 可调用的形式"""
        with httpx.Client(timeout=REWRITE_TIMEOUT) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": messages, "temperature": 0.1}
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    try:
        # 使用 asyncio.to_thread 在线程池中执行同步 HTTP 调用，避免阻塞事件循环
        content = await asyncio.to_thread(_sync_http_call)

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


# ========== 查询类型分类（查指南 vs 查病例）==========


# 查询类型白名单
VALID_QUERY_TYPES = ["guideline", "case", "general"]


async def classify_query_type(query: str, patient_context: Optional[Any] = None, history: list = None) -> str:
    """
    第二层意图识别（查指南 vs 查病例）

    在 rewrite 节点之后执行，在检索之前明确"查什么类型的知识库"。
    这是对第一层 intent_route 的补充：
    - intent_route 解决"是否查知识库"（knowledge_query vs general_chat）
    - classify_query_type 解决"查指南还是查病例"（guideline vs case）

    分类逻辑：
    - guideline: 用户询问标准诊疗规范、指南共识、药物用法等通用医学知识
    - case: 用户询问类似病例、临床经验分享（本院案例库）
    - general: 闲聊或无法明确归类

    Args:
        query: 用户问题（已改写版本优先）
        patient_context: 患者上下文（可帮助判断是否在查病例）
        history: 历史对话

    Returns:
        str: query_type - "guideline" | "case" | "general"
    """
    from ..config import get_integration_api_key, get_integration_base_url, get_integration_model
    api_key = get_integration_api_key()
    base_url = get_integration_base_url()
    model = get_integration_model()

    if not api_key or not base_url:
        # API 不可用时，基于关键词的启发式判断
        return _heuristic_query_type(query, patient_context)

    # 构造提示词
    patient_hint = ""
    if patient_context:
        patient_hint = f"\n患者上下文：{patient_context.summary_text if hasattr(patient_context, 'summary_text') else str(patient_context)}"

    history_hint = ""
    if history:
        history_hint = f"\n历史对话摘要：{[h.get('content', '')[:50] for h in history[-2:]]}"

    prompt = f"""
你是一个医学检索系统的查询分类助手。

给定用户问题，判断用户想查哪类知识库：

**guideline（指南/规范）**：用户想了解标准诊疗规范、指南共识、药物用法、剂量、预后统计等**通用医学知识**。
    典型问法：
    - "黑色素瘤的 AJCC 分期标准是什么"
    - "帕博利珠单抗的适应症有哪些"
    - "肢端黑色素瘤的预后如何"
    - "NCCN 指南对 T1b 期有什么建议"
    - "BRAF 突变阳性用什么靶向药"

**case（病例）**：用户想查找**类似临床病例**、本院经验分享、真实案例参考。
    典型问法：
    - "我们医院有这样的案例吗"
    - "有没有类似的病例"
    - "其他患者的治疗经验是什么"
    - "类似分期的患者预后怎样"
    - "临床上这种方案效果如何"

**general（通用）**：日常问候、闲聊、或无法归类为上述两类的问题。

请严格以纯 JSON 格式输出：
{{"query_type": "guideline" | "case" | "general", "reason": "分类理由（10字以内）"}}

注意：
- 如果问题同时涉及指南和病例（如"类似病例的治疗方案有没有指南依据"），优先按 case 归类。
- 如果有患者上下文且包含具体分期/症状，"类似病例"的意图更明确，应归 case。
{patient_hint}{history_hint}
问题：{query}
"""

    messages = [
        {"role": "system", "content": "你是一个严谨的医学分类助手，只输出 JSON。"},
        {"role": "user", "content": prompt}
    ]

    def _sync_http_call() -> str:
        with httpx.Client(timeout=REWRITE_TIMEOUT) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": messages, "temperature": 0.1}
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    try:
        content = await asyncio.to_thread(_sync_http_call)
        result = json.loads(content.strip())
        qt = result.get("query_type", "general")
        if qt not in VALID_QUERY_TYPES:
            qt = "general"
        logger.info(f"Query type classified: {qt}, reason: {result.get('reason', 'N/A')}")
        return qt
    except httpx.TimeoutException:
        logger.warning("Query type classification timed out, using heuristic fallback.")
        return _heuristic_query_type(query, patient_context)
    except Exception as e:
        logger.error(f"Query type classification failed: {e}, using heuristic fallback.")
        return _heuristic_query_type(query, patient_context)


def _heuristic_query_type(query: str, patient_context: Optional[Any] = None) -> str:
    """
    启发式查询类型判断（LLM 不可用时的兜底方案）。

    判断依据：
    1. 病例检索关键词：医院、案例、病例、类似、临床经验、预后（结合分期信息）
    2. 指南检索关键词：指南、共识、标准、规范、适应症、用法用量
    3. 患者上下文中的分期信息越具体，越像在查病例
    """
    query_lower = query.lower()

    # 病例检索的典型词
    case_keywords = [
        "医院", "案例", "病例", "类似", "其他患者", "临床经验",
        "真实案例", "患者经验", "病友", "住院", "门诊病例",
        "治疗效果如何", "预后怎样", "有没有类似的"
    ]

    # 指南检索的典型词
    guideline_keywords = [
        "指南", "共识", "标准", "规范", "适应症", "用法用量",
        "剂量", "药物", "药品", "方案", "分期标准",
        "nccn", "ajcc", "分期", "治疗方案", "靶向", "免疫治疗"
    ]

    case_score = sum(1 for kw in case_keywords if kw in query_lower)
    guideline_score = sum(1 for kw in guideline_keywords if kw in query_lower)

    # 有具体患者上下文（分期/症状） + case 关键词 → 病例
    has_patient_context = patient_context is not None
    if has_patient_context and case_score > 0:
        return "case"

    # 有 case 关键词且得分明显高 → 病例
    if case_score > guideline_score:
        return "case"

    # 有 guideline 关键词 → 指南
    if guideline_score > 0:
        return "guideline"

    # 默认走指南（通用医学知识查询）
    return "guideline"