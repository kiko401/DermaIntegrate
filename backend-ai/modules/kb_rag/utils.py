import re
import json
import uuid
import logging

logger = logging.getLogger(__name__)


def generate_trace_id() -> str:
    return f"rag_trace_{uuid.uuid4().hex[:12]}"


def generate_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def extract_json_from_text(text: str) -> dict:
    """从 LLM 输出（可能含 Markdown 代码块）中提取 JSON 字典。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to extract JSON from text: {text[:100]}...")
    return {}


def truncate_text(text: str, max_chars: int = 4000) -> str:
    """截断文本以防止超出 LLM 上下文限制。"""
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[已截断]"
    return text
