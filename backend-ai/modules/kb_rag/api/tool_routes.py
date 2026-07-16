from fastapi import APIRouter, HTTPException
from ..schemas import ToolRunRequest
from ..agent.tool_registry import get_tool_schemas
from ..agent.tool_executor import execute_tool
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/tools")
async def list_tools_endpoint():
    """返回工具清单及 schema"""
    tools = get_tool_schemas()
    return {"tools": tools}


@router.post("/tools/run")
async def run_tool_endpoint(req: ToolRunRequest):
    """执行指定工具"""
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
