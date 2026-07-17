from pydantic import BaseModel, Field, model_validator
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
    """
    Agent 工作流轨迹，记录完整执行路径与各节点状态。

    注意：ChatResponse 内嵌时不含 created_at；
    GET /rag/agents/runs/:run_id 查询响应中保留 created_at（见 AgentRunTraceObject）。
    """
    workflow: str
    nodes: List[AgentTraceNode] = []


class AgentRunTraceObject(BaseModel):
    """
    Agent 运行轨迹响应对象（GET /rag/agents/runs/:run_id 专用，含 created_at）。
    """
    workflow: str
    nodes: List[AgentTraceNode] = []
    created_at: str


class ChatRequest(BaseModel):
    """知识库问答请求，包含会话 ID、问题、历史记录与检索配置。"""
    conversation_id: int
    question: str
    history: List[Dict[str, str]] = []
    kb_ids: List[int] = []
    patient_context: Optional[PatientContextObject] = None
    options: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _merge_options(self):
        if self.options is None:
            self.options = {
                "top_k": 5,
                "similarity_threshold": 0.35,
                "stream": False,
                "enable_tools": True,
                "enable_agent": True,
                "use_rerank": False,
                "max_length": 0,
                "max_paragraphs": 0,
            }
        else:
            # 深度合并：用户提供的值覆盖默认值
            defaults = {
                "top_k": 5,
                "similarity_threshold": 0.35,
                "stream": False,
                "enable_tools": True,
                "enable_agent": True,
                "use_rerank": False,
                # M-06: 回答长度限制
                "max_length": 0,        # 0=不限制，最大字符数
                "max_paragraphs": 0,   # 0=不限制，最大段落数
            }
            defaults.update(self.options)
            self.options = defaults
        return self


class ChatResponse(BaseModel):
    """知识库问答响应，包含答案、来源引用、风险高亮与 Agent 执行轨迹。"""
    trace_id: str
    message_id: str
    route: Literal["knowledge_query", "patient_context_query", "tool_call", "general_chat", "agent_workflow", "rule_answer"]
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
    workflow: str = "langgraph_rag_agent"
    conversation_id: int = 0
    question: str
    history: List[Dict[str, str]] = []
    kb_ids: List[int] = []
    patient_context: Optional[PatientContextObject] = None
    options: Dict[str, Any] = {}


class ETLJobStatus(BaseModel):
    """ETL 任务状态，记录任务 ID、进度与执行详情。"""
    job_id: str
    job_name: Optional[str] = None
    status: Literal["pending", "running", "succeeded", "failed"]
    progress: int = 0
    stage: Optional[str] = None
    detail: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None


class FeedbackExportRequest(BaseModel):
    """反馈导出请求，按条件筛选并导出对话数据供微调使用。"""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    kb_ids: Optional[List[int]] = None
    min_confidence: Optional[float] = None
    format: Literal["jsonl"] = "jsonl"


class ETLRunRequest(BaseModel):
    """ETL 任务触发请求，支持多源数据接入。"""
    job_name: Optional[str] = None
    source_type: Literal["file", "csv", "excel", "url", "database"] = "file"
    source_config: Dict[str, Any] = {}
    kb_id: int
    chunk_size: int = 800
    chunk_overlap: int = 120


class ETLClinicalRequest(BaseModel):
    """
    临床病例 ETL 入库请求（来自应用域的脱敏病例文本）。

    应用域在调用前须完成：
    - 患者姓名、ID、日期等 PHI 字段脱敏
    - 合并 patient_context 与 case_text，生成自然语言结构化描述
    """
    kb_id: int
    case_type: Literal["his", "lis", "pacs", "pathology"]
    patient_context: PatientContextObject
    case_text: str
    doc_version_id: int
    chunk_size: int = 800
    chunk_overlap: int = 120


class ReindexTextRequest(BaseModel):
    """
    纯文本重索引请求（用于文档版本回滚）。

    应用域将历史版本文本通过此接口写入，AI 域先删旧版向量再入新版。
    """
    kb_id: int
    doc_id: int
    doc_version_id: int
    text: str
    chunk_size: int = 800
    chunk_overlap: int = 120


class CloneKbIndexRequest(BaseModel):
    """知识库克隆请求，将源知识库的向量复制到目标知识库。"""
    source_kb_id: int
    target_kb_id: int


class VectorOptimizeRequest(BaseModel):
    """向量优化请求，对指定 kb_id 执行清理优化操作。"""
    kb_id: int
    remove_duplicates: bool = False
    rebuild_bm25_idf: bool = False
    compact_collection: bool = False
