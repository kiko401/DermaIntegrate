from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from ..schemas import AgentRunRequest, ChatResponse, ChatRequest, PatientContextObject
from ..agent.langgraph_workflow import run_agent_workflow
from ..agent.tool_executor import get_agent_run_trace
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# 扩展请求模型，增加 options 字段以支持传递 tool_payload
class AgentRunRequestExt(AgentRunRequest):
    options: Dict[str, Any] = {}


@router.post("/agents/run", response_model=ChatResponse)
async def run_agent_endpoint(req: AgentRunRequestExt):
    """触发 LangGraph 智能体"""
    try:
        logger.info(f"Agent run requested for question: {req.question}")

        # 将 AgentRunRequest 转换为内部 ChatRequest
        chat_req = ChatRequest(
            conversation_id=0,  # Agent 测试无固定会话
            question=req.question,
            history=req.history,
            kb_ids=req.kb_ids,
            patient_context=req.patient_context,
            options={
                "enable_agent": True,
                "enable_tools": True,
                "tool_payload": req.options.get("tool_payload")
            }
        )

        response = await run_agent_workflow(chat_req)

        if response is None:
            raise HTTPException(status_code=500, detail="Agent workflow returned null response")

        return response

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