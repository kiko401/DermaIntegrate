import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


async def export_to_jsonl(conversation_data: List[Dict]) -> str:
    """
    将应用域传入的原始问答对转换为标准 ChatML JSONL 格式供微调使用。
    (符合架构规范：AI域不直连应用域DB，由应用域拉取数据后调用此服务格式化)
    """
    jsonl_lines = []

    for conv in conversation_data:
        question = conv.get("question")
        answer = conv.get("answer")

        if not question or not answer:
            continue

        # 标准 ChatML 格式
        entry = {
            "messages": [
                {"role": "system", "content": "你是一个严谨的皮肤病科助手。请基于知识库回答问题。"},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer}
            ],
            # 可附带元数据用于微调过滤
            "metadata": {
                "conversation_id": conv.get("conversation_id"),
                "feedback": conv.get("feedback", ""),
                "route": conv.get("route", ""),
                "confidence": conv.get("confidence", None),
                "kb_ids": conv.get("kb_ids", []),
                "created_at": conv.get("created_at", ""),
            }
        }
        jsonl_lines.append(json.dumps(entry, ensure_ascii=False))

    logger.info(f"Exported {len(jsonl_lines)} conversations to JSONL.")
    return "\n".join(jsonl_lines)