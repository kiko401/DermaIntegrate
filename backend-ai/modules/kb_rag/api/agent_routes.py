from fastapi import APIRouter, HTTPException, BackgroundTasks, status
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from ..schemas import AgentRunRequest, ChatRequest
from ..agent.langgraph_workflow import run_agent_workflow
from ..agent.tool_executor import get_agent_run_trace, init_agent_trace
import logging
import uuid

logger = logging.getLogger(__name__)
router = APIRouter()

# 会话级上下文配置存储（内存，key=conversation_id）
# 应用域可通过此接口管理 AI 域的上下文保留策略
_SESSION_CONFIGS: Dict[int, Dict[str, Any]] = {}


class SessionContextConfig(BaseModel):
    """会话级上下文配置：控制该会话的上下文保留策略"""
    conversation_id: int
    context_retention_rounds: int = Field(default=10, ge=0, le=50, description="保留的历史对话轮次，0=不保留历史")
    context_max_tokens: int = Field(default=4000, ge=0, le=32000, description="上下文最大 token 数（参考值，由调用方控制）")
    max_length: int = Field(default=0, ge=0, le=10000, description="回答最大字符数，0=不限制")
    max_paragraphs: int = Field(default=0, ge=0, le=50, description="回答最大段落数，0=不限制")
    enabled: bool = Field(default=True, description="是否启用上下文追踪")


class SessionContextUpdate(BaseModel):
    """更新会话上下文配置的可选字段"""
    context_retention_rounds: Optional[int] = Field(default=None, ge=0, le=50)
    context_max_tokens: Optional[int] = Field(default=None, ge=0, le=32000)
    max_length: Optional[int] = Field(default=None, ge=0, le=10000)
    max_paragraphs: Optional[int] = Field(default=None, ge=0, le=50)
    enabled: Optional[bool] = None


@router.post("/agents/run", status_code=status.HTTP_202_ACCEPTED)
async def run_agent_endpoint(req: AgentRunRequest, background_tasks: BackgroundTasks):
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
                # 从会话配置中读取回答长度限制
                "max_length": _SESSION_CONFIGS.get(req.conversation_id, {}).get("max_length", 0),
                "max_paragraphs": _SESSION_CONFIGS.get(req.conversation_id, {}).get("max_paragraphs", 0),
            },
        )

        # BackgroundTasks 确保任务在 FastAPI 生命周期内完成，异常可被记录
        background_tasks.add_task(run_agent_workflow, chat_req)

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


# ===== 会话上下文配置管理 =====

@router.get("/agents/sessions/{conversation_id}/context-config", response_model=SessionContextConfig)
async def get_session_context_config(conversation_id: int):
    """
    查询指定会话的上下文配置。
    未配置过则返回默认配置。
    """
    config = _SESSION_CONFIGS.get(conversation_id)
    if config is None:
        return SessionContextConfig(conversation_id=conversation_id)
    return SessionContextConfig(conversation_id=conversation_id, **config)


@router.put("/agents/sessions/{conversation_id}/context-config", response_model=SessionContextConfig)
async def update_session_context_config(conversation_id: int, req: SessionContextUpdate):
    """
    更新指定会话的上下文配置。
    仅更新传入的非空字段。
    """
    current = _SESSION_CONFIGS.get(conversation_id, {})
    update_data = req.model_dump(exclude_unset=True)
    current.update(update_data)
    _SESSION_CONFIGS[conversation_id] = current
    logger.info(f"Updated context config for conversation {conversation_id}: {update_data}")
    return SessionContextConfig(conversation_id=conversation_id, **current)


@router.delete("/agents/sessions/{conversation_id}/context-config")
async def delete_session_context_config(conversation_id: int):
    """清除指定会话的上下文配置（恢复默认）"""
    if conversation_id in _SESSION_CONFIGS:
        del _SESSION_CONFIGS[conversation_id]
        logger.info(f"Cleared context config for conversation {conversation_id}")
    return {"status": "cleared", "conversation_id": conversation_id}
