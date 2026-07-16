import logging
from typing import List, Dict, Any
from ..schemas import ToolDefinition

logger = logging.getLogger(__name__)

# 严格按规范注册首批 4 个工具
TOOL_REGISTRY: List[ToolDefinition] = [
    ToolDefinition(
        name="pandas_analyzer",
        description="接收应用域传来的数据集引用或内容，使用 Pandas 进行自然语言统计分析。",
        args_schema={
            "type": "object",
            "properties": {
                "dataset_ref": {"type": "string", "description": "数据集引用或内容（含 CSV 字符串、JSON 或 ETL job 结果引用等）"},
                "query": {"type": "string", "description": "自然语言分析请求，如'按病理类型统计病例数'"}
            },
            "required": ["dataset_ref", "query"]
        },
        enabled=True,
        timeout_seconds=30,
        access_scope=["admin", "system"]
    ),
    ToolDefinition(
        name="kb_lookup_debug",
        description="直接检索知识库并返回原始切片及分数，用于调试检索效果。",
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kb_ids": {"type": "array", "items": {"type": "integer"}}
            },
            "required": ["query", "kb_ids"]
        },
        enabled=True,
        timeout_seconds=10,
        access_scope=["admin"]
    ),
    ToolDefinition(
        name="clinical_context_summarizer",
        description="提取患者临床视图最小必要字段并生成结构化摘要。",
        args_schema={
            "type": "object",
            "properties": {
                "patient_id": {"type": "integer", "description": "患者内部 ID"}
            },
            "required": ["patient_id"]
        },
        enabled=True,
        timeout_seconds=15,
        access_scope=["doctor", "system"]
    ),
    ToolDefinition(
        name="etl_preview",
        description="预览 ETL 任务的抽取与清洗结果前 5 行。",
        args_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string"}
            },
            "required": ["job_id"]
        },
        enabled=True,
        timeout_seconds=10,
        access_scope=["admin"]
    )
]

def get_tool_schemas() -> List[Dict[str, Any]]:
    """返回工具清单及 schema"""
    return [tool.dict() for tool in TOOL_REGISTRY if tool.enabled]