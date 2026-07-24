from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from ..schemas import ToolRunRequest
from ..agent.tool_registry import get_tool_schemas, list_quick_templates, get_quick_template, create_quick_template, update_quick_template, delete_quick_template
from ..agent.tool_executor import execute_tool
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== M-08 快捷提问模板 CRUD =====

class QuickTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    question_template: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=200)
    kb_ids: Optional[List[int]] = Field(default_factory=list)


class QuickTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    question_template: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=200)
    kb_ids: Optional[List[int]] = None
    enabled: Optional[bool] = None


@router.get("/tools")
async def list_tools_endpoint():
    """返回工具清单及 schema"""
    tools = get_tool_schemas()
    return {"tools": tools}


@router.post("/tools/run")
async def run_tool_endpoint(req: ToolRunRequest):
    """执行指定工具"""
    # H-06: RCE防护 - 执行前校验工具名在注册表中
    schemas = get_tool_schemas()
    registered_names = {t["name"] for t in schemas}
    if req.tool_name not in registered_names:
        raise HTTPException(
            status_code=400,
            detail=f"工具 '{req.tool_name}' 未注册或已禁用。可用工具: {sorted(registered_names)}"
        )

    try:
        result = await execute_tool(req.tool_name, req.arguments)
        output_summary = str(result.get("result", ""))[:200] if result.get("result") else None
        return {
            "tool_name": req.tool_name,
            "status": result.get("status", "completed"),
            "output_summary": output_summary,
            "output_detail": result.get("result"),
        }
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 快捷提问模板管理

@router.get("/tools/templates")
async def list_templates_endpoint(enabled_only: bool = False):
    """列出所有快捷提问模板"""
    return {"templates": list_quick_templates(enabled_only=enabled_only)}


@router.get("/tools/templates/{template_id}")
async def get_template_endpoint(template_id: str):
    """获取单个模板详情"""
    tpl = get_quick_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.post("/tools/templates", status_code=201)
async def create_template_endpoint(req: QuickTemplateCreate):
    """创建新快捷提问模板"""
    try:
        tpl = create_quick_template(
            name=req.name,
            question_template=req.question_template,
            description=req.description,
            kb_ids=req.kb_ids,
        )
        return tpl
    except Exception as e:
        logger.error(f"Create template failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/tools/templates/{template_id}")
async def update_template_endpoint(template_id: str, req: QuickTemplateUpdate):
    """更新快捷提问模板"""
    updated = update_quick_template(template_id, **req.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found")
    return updated


@router.delete("/tools/templates/{template_id}")
async def delete_template_endpoint(template_id: str):
    """删除快捷提问模板"""
    if not delete_quick_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "deleted", "template_id": template_id}
