"""
非流式 RAG 工作流

委托 LangGraph StateGraph 统一执行，本模块仅负责请求入口和异常封装。
"""
import logging
from ..schemas import ChatRequest, ChatResponse
from ..agent.langgraph_workflow import run_agent_workflow

logger = logging.getLogger(__name__)


async def run_rag_workflow(req: ChatRequest) -> ChatResponse:
    """非流式 RAG 主链编排（委托 LangGraph 引擎）"""
    try:
        return await run_agent_workflow(req)
    except Exception as e:
        logger.error(f"Chat failed: {e}", exc_info=True)
        # 异常时构建失败响应（run_agent_workflow 内部已 try/except，
        # 此处仅作最外层安全网）
        from .answer_builder import build_response
        return build_response(
            req, f"处理异常: {str(e)}", [], "general_chat",
            0.0, "failed", str(e)
        )
