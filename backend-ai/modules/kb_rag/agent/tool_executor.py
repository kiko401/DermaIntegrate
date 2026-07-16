import asyncio
import logging
import uuid
from typing import Dict, Any, Optional
from collections import OrderedDict
from .pandas_agent import analyze as pandas_analyze
from ..retrieval.retriever import retrieve as kb_lookup
from ..schemas import AgentRunTraceObject

logger = logging.getLogger(__name__)

# 使用 LRU 缓存限制最大容量为 100，防止内存泄漏
MAX_TRACE_COUNT = 100
_RUN_TRACES: OrderedDict[str, AgentRunTraceObject] = OrderedDict()


async def execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """路由并执行工具调用，包含超时控制"""
    logger.info(f"Executing tool {tool_name} with args: {args}")

    try:
        if tool_name == "pandas_analyzer":
            result = await asyncio.wait_for(
                pandas_analyze(args.get("dataset_ref", ""), args.get("query", "")),
                timeout=30
            )
            return {"status": "completed", "result": result}

        elif tool_name == "kb_lookup_debug":
            chunks, is_blocked = await kb_lookup(args.get("query"), args.get("kb_ids", []))
            return {"status": "completed", "result": {"chunks": chunks, "is_blocked": is_blocked}}

        elif tool_name == "clinical_context_summarizer":
            clinical_data = args.get("clinical_view", {})
            if not clinical_data:
                return {"status": "failed", "error": "Missing clinical_view data"}

            summary = {
                "gender": clinical_data.get("gender", "未知"),
                "age": clinical_data.get("age", "未知"),
                "diagnosis": clinical_data.get("diagnosis", "未知")
            }
            summary_text = f"当前患者，{summary['gender']}，{summary['age']}岁，近期临床考虑{summary['diagnosis']}。"
            return {"status": "completed", "result": {"summary_text": summary_text, "structured": summary}}

        elif tool_name == "etl_preview":
            etl_data = args.get("etl_result_csv", "")
            if not etl_data:
                return {"status": "failed", "error": "Missing etl_result_csv data"}

            import io
            import pandas as pd
            df = pd.read_csv(io.StringIO(etl_data))
            return {"status": "completed", "result": {"preview": df.head(5).to_dict(orient="records")}}

        else:
            return {"status": "failed", "error": "Tool not found"}

    except asyncio.TimeoutError:
        logger.error(f"Tool {tool_name} execution timed out.")
        return {"status": "failed", "error": "Timeout"}
    except Exception as e:
        logger.error(f"Tool {tool_name} execution failed: {e}")
        return {"status": "failed", "error": str(e)}


def init_agent_trace(run_id: str) -> AgentRunTraceObject:
    """初始化运行轨迹，使用 LRU 策略管理内存"""
    from datetime import datetime
    trace = AgentRunTraceObject(
        workflow="langgraph_rag_agent",
        nodes=[],
        created_at=datetime.now().isoformat(),
    )
    _RUN_TRACES[run_id] = trace

    # 如果超过最大容量，移除最老的记录
    if len(_RUN_TRACES) > MAX_TRACE_COUNT:
        _RUN_TRACES.popitem(last=False)

    return trace


def update_agent_trace(run_id: str, node_name: str, status: str):
    if run_id in _RUN_TRACES:
        _RUN_TRACES[run_id].nodes.append({"name": node_name, "status": status})


async def get_agent_run_trace(run_id: str) -> Optional[Dict]:
    trace = _RUN_TRACES.get(run_id)
    return trace.dict() if trace else None