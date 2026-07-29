"""
应用配置 - 统一管理所有运维参数

所有可外部配置的参数在此集中定义，
业务代码从此模块导入，不在各自文件中硬编码。

分类：
- 外部运维参数：超时、端口、保留策略等（从环境变量读取）
- 算法常数：RRF_K、BM25参数等（硬编码，仅做注释说明）
"""
import os

# ============================================================
# LLM 超时配置
# ============================================================
LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT", "5.0"))   # 连接超时(秒)
LLM_READ_TIMEOUT = float(os.getenv("LLM_READ_TIMEOUT", "30.0"))        # 读取超时(秒)
LLM_WRITE_TIMEOUT = float(os.getenv("LLM_WRITE_TIMEOUT", "10.0"))     # 写入超时(秒)
LLM_POOL_TIMEOUT = float(os.getenv("LLM_POOL_TIMEOUT", "30.0"))      # 连接池超时(秒)

# rewrite/重写服务超时（较短，适合轻量LLM调用）
REWRITE_CONNECT_TIMEOUT = float(os.getenv("REWRITE_CONNECT_TIMEOUT", "3.0"))
REWRITE_READ_TIMEOUT = float(os.getenv("REWRITE_READ_TIMEOUT", "10.0"))

# ============================================================
# 缓存 TTL 配置
# ============================================================
SENSITIVE_WORD_CACHE_TTL = int(os.getenv("SENSITIVE_WORD_CACHE_TTL", "300"))   # 敏感词缓存 TTL(秒)，默认5分钟
RULE_ANSWER_CACHE_TTL = int(os.getenv("RULE_ANSWER_CACHE_TTL", "300"))       # 规则回答缓存 TTL(秒)
REJECTION_RULE_CACHE_TTL = int(os.getenv("REJECTION_RULE_CACHE_TTL", "300")) # 拒绝规则缓存 TTL(秒)
MODEL_CONFIG_CACHE_TTL = int(os.getenv("MODEL_CONFIG_CACHE_TTL", "120"))       # 模型配置缓存 TTL(秒)，默认2分钟

# ============================================================
# 文件清理策略
# ============================================================
FILE_RETENTION_DAYS = int(os.getenv("FILE_RETENTION_DAYS", "7"))  # 文件保留天数

# ============================================================
# SSE 流式推理超时配置
# ============================================================
TASK_TIMEOUT_SECONDS = int(os.getenv("TASK_TIMEOUT_SECONDS", "600"))  # 推理任务超时(秒)，默认10分钟
SSE_HEARTBEAT_INTERVAL = int(os.getenv("SSE_HEARTBEAT_INTERVAL", "15"))  # SSE心跳间隔(秒)

# ============================================================
# ETL 资源配置
# ============================================================
MAX_ETL_JOBS = int(os.getenv("MAX_ETL_JOBS", "200"))  # 内存中最大 ETL 任务数

# ============================================================
# Qdrant 连接配置
# ============================================================
QDRANT_HOST = os.getenv("QDRANT_HOST", "")                    # 留空则用 DOCKER_ENV 自动推断
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

# ============================================================
# HTTP 客户端超时配置（用于外部 URL 摄取、回调等）
# ============================================================
# ETL URL 摄取超时（较长，因为要从远程下载文件）
ETL_CONNECT_TIMEOUT = float(os.getenv("ETL_CONNECT_TIMEOUT", "10.0"))
ETL_READ_TIMEOUT = float(os.getenv("ETL_READ_TIMEOUT", "60.0"))

# 应用域对话拉取超时
APP_CONVERSATION_CONNECT_TIMEOUT = float(os.getenv("APP_CONVERSATION_CONNECT_TIMEOUT", "5.0"))
APP_CONVERSATION_READ_TIMEOUT = float(os.getenv("APP_CONVERSATION_READ_TIMEOUT", "30.0"))

# 任务回调超时（回调给应用域）
CALLBACK_CONNECT_TIMEOUT = float(os.getenv("CALLBACK_CONNECT_TIMEOUT", "5.0"))
CALLBACK_READ_TIMEOUT = float(os.getenv("CALLBACK_READ_TIMEOUT", "15.0"))
CALLBACK_WRITE_TIMEOUT = float(os.getenv("CALLBACK_WRITE_TIMEOUT", "10.0"))
CALLBACK_POOL_TIMEOUT = float(os.getenv("CALLBACK_POOL_TIMEOUT", "15.0"))

# ============================================================
# 检索质量参数
# ============================================================
# KB-RAG 检索置信度阈值：用于判断检索结果是否足以生成回答（低于此值则阻断）
RETRIEVAL_SCORE_THRESHOLD = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.35"))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))                            # 默认返回条数
# 旧版 RAG 检索置信度阈值：用于 legacy rag/knowledge_base.py 的 retrieve 方法
RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.3"))

# ============================================================
# 算法常数（不推荐外部修改，仅供内部参考）
# ============================================================
# BM25 参数已统一到 shared/constants.py（BM25_K1=1.5, BM25_B=0.75, AVG_DOC_LEN=200）
# MAX_LLM_RETRIES = 2          # LLM 调用最大重试次数
