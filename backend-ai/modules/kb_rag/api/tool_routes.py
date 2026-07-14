from fastapi import APIRouter, HTTPException
from typing import List
from ..schemas import ToolDefinition, ToolRunRequest
from ..agent.tool_registry import get_tool_schemas
from ..agent.tool_executor import execute_tool
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/tools", response_model=List[ToolDefinition])
async def list_tools_endpoint():
    """返回工具清单及 schema"""
    return get_tool_schemas()

@router.post("/tools/run")
async def run_tool_endpoint(req: ToolRunRequest):
    """工具测试执行"""
    try:
        result = await execute_tool(req.tool_name, req.arguments)
        return {"status": "succeeded", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))