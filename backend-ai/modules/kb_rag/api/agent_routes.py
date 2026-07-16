from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from ..schemas import AgentRunRequest, ChatRequest
from ..agent.langgraph_workflow import run_agent_workflow
from ..agent.tool_executor import get_agent_run_trace, init_agent_trace
import logging
import uuid

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agents/run", status_code=status.HTTP_202_ACCEPTED)
async def run_agent_endpoint(req: AgentRunRequest):
    """
    触发 LangGraph 智能体工作流。
    返回 run_id 用于后续查询执行结果。
    """
    try:
        run_id = str(uuid.uuid4())
        init_agent_trace(run_id)

        chat_req = ChatRequest(
            conversation_id=req.conversation_id,
            question=req.question,
            history=req.history,
            kb_ids=req.kb_ids,
            patient_context=req.patient_context,
            options={
                "enable_agent": True,
                "enable_tools": True,
                "tool_payload": req.options.get("tool_payload"),
            },
        )

        # 异步执行，避免阻塞
        import asyncio
        asyncio.create_task(run_agent_workflow(chat_req))

        return {
            "run_id": run_id,
            "workflow": req.workflow,
            "status": "started",
        }

    except Exception as e:
        logger.error(f"Agent run failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/runs/{run_id}")
async def get_agent_run_endpoint(run_id: str):
    """获取智能体运行轨迹"""
    trace = await get_agent_run_trace(run_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Run trace not found")
    return trace
