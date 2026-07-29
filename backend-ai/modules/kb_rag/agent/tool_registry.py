import logging
import uuid
from typing import List, Dict, Any, Optional
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
                "query": {"type": "string", "description": "检索查询词"},
                "kb_ids": {"type": "array", "items": {"type": "integer"}, "description": "知识库 ID 列表"},
                "top_k": {"type": "integer", "description": "召回 chunk 数量，默认 5", "default": 5},
                "similarity_threshold": {"type": "number", "description": "相似度阈值（0~1），默认 0.35，低于此值不返回", "default": 0.35}
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
                "clinical_view": {
                    "type": "object",
                    "description": "患者临床视图对象，包含 gender（性别）、age（年龄）、diagnosis（诊断）等字段",
                    "properties": {
                        "gender": {"type": "string", "description": "性别，如'男'或'女'"},
                        "age": {"type": "string", "description": "年龄，如'45'或'45岁'"},
                        "diagnosis": {"type": "string", "description": "临床诊断结论"}
                    }
                }
            },
            "required": ["clinical_view"]
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
                "etl_result_csv": {
                    "type": "string",
                    "description": "ETL 任务结果的 CSV 格式字符串内容"
                }
            },
            "required": ["etl_result_csv"]
        },
        enabled=True,
        timeout_seconds=10,
        access_scope=["admin"]
    )
]

def get_tool_schemas() -> List[Dict[str, Any]]:
    """返回工具清单及 schema"""
    return [tool.model_dump() for tool in TOOL_REGISTRY if tool.enabled]


# ===== 快捷提问模板管理 =====

class QuickQuestionTemplate:
    """快捷提问模板对象"""
    def __init__(
        self,
        template_id: str,
        name: str,
        question_template: str,
        description: str = "",
        kb_ids: Optional[List[int]] = None,
        enabled: bool = True,
    ):
        self.template_id = template_id
        self.name = name
        self.question_template = question_template
        self.description = description
        self.kb_ids = kb_ids or []
        self.enabled = enabled

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "question_template": self.question_template,
            "description": self.description,
            "kb_ids": self.kb_ids,
            "enabled": self.enabled,
        }


# 内存级模板存储
_QUICK_QUESTION_TEMPLATES: Dict[str, QuickQuestionTemplate] = {
    # 默认预置模板（皮肤科常见场景）
    "tpl_001": QuickQuestionTemplate(
        template_id="tpl_001",
        name="皮疹鉴别",
        question_template="患者表现为{location}的{color}皮疹，请鉴别诊断",
        description="用于皮疹的部位、颜色等多维度鉴别诊断提问",
        kb_ids=[],
    ),
    "tpl_002": QuickQuestionTemplate(
        template_id="tpl_002",
        name="药物副作用查询",
        question_template="{drug}的主要不良反应有哪些？禁忌人群是？",
        description="查询特定药物的副作用和禁忌",
        kb_ids=[],
    ),
    "tpl_003": QuickQuestionTemplate(
        template_id="tpl_003",
        name="治疗方案对比",
        question_template="{disease}的一线治疗方案是什么？与{n替代方案}相比有何优劣？",
        description="对比两种治疗方案的优劣",
        kb_ids=[],
    ),
}


def list_quick_templates(enabled_only: bool = False) -> List[dict]:
    """列出所有快捷模板"""
    templates = _QUICK_QUESTION_TEMPLATES.values()
    if enabled_only:
        templates = [t for t in templates if t.enabled]
    return [t.to_dict() for t in templates]


def get_quick_template(template_id: str) -> Optional[dict]:
    """根据 ID 获取单个模板"""
    tpl = _QUICK_QUESTION_TEMPLATES.get(template_id)
    return tpl.to_dict() if tpl else None


def create_quick_template(
    name: str,
    question_template: str,
    description: str = "",
    kb_ids: Optional[List[int]] = None,
) -> dict:
    """创建新模板（自动生成 ID）"""
    template_id = f"tpl_{uuid.uuid4().hex[:8]}"
    tpl = QuickQuestionTemplate(
        template_id=template_id,
        name=name,
        question_template=question_template,
        description=description,
        kb_ids=kb_ids or [],
    )
    _QUICK_QUESTION_TEMPLATES[template_id] = tpl
    logger.info(f"Created quick template: {template_id}")
    return tpl.to_dict()


def update_quick_template(template_id: str, **kwargs) -> Optional[dict]:
    """更新模板（部分更新，仅修改传入字段）"""
    tpl = _QUICK_QUESTION_TEMPLATES.get(template_id)
    if not tpl:
        return None
    for key, value in kwargs.items():
        if key in ("name", "question_template", "description", "kb_ids", "enabled"):
            setattr(tpl, key, value)
    logger.info(f"Updated quick template: {template_id}")
    return tpl.to_dict()


def delete_quick_template(template_id: str) -> bool:
    """删除模板"""
    if template_id in _QUICK_QUESTION_TEMPLATES:
        del _QUICK_QUESTION_TEMPLATES[template_id]
        logger.info(f"Deleted quick template: {template_id}")
        return True
    return False