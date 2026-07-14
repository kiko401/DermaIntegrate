from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal


class PatientContextObject(BaseModel):
    """患者上下文对象，用于向知识库问答传递患者概要信息。"""
    summary_text: str
    structured: Dict[str, Any] = {}


class SourceObject(BaseModel):
    """检索来源对象，记录命中文档的 ID、分数与原文片段。"""
    doc_id: int
    doc_code: Optional[str] = None
    title: Optional[str] = None
    chunk_id: str = Field(..., description="格式: {doc_id}_{doc_version_id}_{chunk_index} (补零三位)")
    chunk_index: int
    score: float
    snippet: str
    source_location: Dict[str, Any] = {}


class RiskHighlightObject(BaseModel):
    """风险高亮对象，标记回答中需要用户注意的药物、剂量、禁忌等关键信息。"""
    label: str
    text: str
    category: Literal["drug", "dose", "contraindication", "threshold", "risk_factor"]
    start: int
    end: int


class ToolCallObject(BaseModel):
    """工具调用对象，记录工具名称、入参、执行状态与输出摘要。"""
    tool_name: str
    arguments: Dict[str, Any]
    status: Literal["running", "completed", "failed"]
    output_summary: Optional[str] = None


class AgentTraceNode(BaseModel):
    """Agent 工作流节点，记录节点名称与执行状态。"""
    name: str
    status: Literal["running", "completed", "failed", "skipped"]


class AgentTraceObject(BaseModel):
    """Agent 工作流轨迹，记录完整执行路径与各节点状态。"""
    workflow: str
    nodes: List[AgentTraceNode] = []


class ChatRequest(BaseModel):
    """知识库问答请求，包含会话 ID、问题、历史记录与检索配置。"""
    conversation_id: int
    question: str
    history: List[Dict[str, str]] = []
    kb_ids: List[int] = []
    patient_context: Optional[PatientContextObject] = None
    options: Dict[str, Any] = {
        "top_k": 5,
        "similarity_threshold": 0.35,
        "stream": False,
        "enable_tools": True,
        "enable_agent": True
    }


class ChatResponse(BaseModel):
    """知识库问答响应，包含答案、来源引用、风险高亮与 Agent 执行轨迹。"""
    trace_id: str
    message_id: str
    route: Literal["knowledge_query", "patient_context_query", "tool_call", "general_chat", "agent_workflow"]
    answer: str
    sources: List[SourceObject] = []
    confidence: float
    blocked_reason: Optional[str] = None
    risk_highlights: List[RiskHighlightObject] = []
    disclaimer: str = "⚠️ 本回答由 AI 基于知识库生成，仅供参考，不能替代执业医师临床判断"
    tool_calls: List[ToolCallObject] = []
    agent_trace: Optional[AgentTraceObject] = None
    status: Literal["completed", "blocked", "failed"]


class IngestCallback(BaseModel):
    """文档摄取回调，记录任务编码、执行状态与生成的 chunk 数量。"""
    task_code: str
    status: Literal["succeeded", "failed"]
    chunk_count: int
    error_message: Optional[str] = None


class ToolDefinition(BaseModel):
    """工具定义，描述工具名称、用途、参数 schema 与超时配置。"""
    name: str
    description: str
    args_schema: Dict[str, Any]
    enabled: bool = True
    timeout_seconds: int = 30
    access_scope: List[str] = []


class ToolRunRequest(BaseModel):
    """工具执行请求，包含工具名称与运行时参数。"""
    tool_name: str
    arguments: Dict[str, Any]


class AgentRunRequest(BaseModel):
    """Agent 工作流执行请求，包含问题、历史上下文与知识库列表。"""
    question: str
    history: List[Dict[str, str]] = []
    kb_ids: List[int] = []
    patient_context: Optional[PatientContextObject] = None
    workflow_name: str = "langgraph_rag_agent"


class ETLJobStatus(BaseModel):
    """ETL 任务状态，记录任务 ID、进度与执行详情。"""
    job_id: str
    status: Literal["pending", "running", "succeeded", "failed"]
    progress: int = 0
    detail: Optional[str] = None


class FeedbackExportRequest(BaseModel):
    """反馈导出请求，将对话评分与内容导出为指定格式。"""
    conversation_ids: List[int]
    output_format: Literal["jsonl"] = "jsonl"
