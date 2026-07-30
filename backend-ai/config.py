import os
import logging
from dotenv import load_dotenv

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()


class Settings:
    """应用程序配置类，集中管理数据库、API密钥及功能开关。"""

    # 数据库连接，生产环境必须通过 DATABASE_URL 环境变量配置，禁止使用默认凭证
    _db_url_env = os.getenv("DATABASE_URL", "").strip()
    if _db_url_env:
        DATABASE_URL: str = _db_url_env
    else:
        logger.warning("DATABASE_URL environment variable is not set. Database connection will fail.")
        DATABASE_URL: str = ""

    UPLOAD_DIR: str = "uploads"
    STATIC_DIR: str = "static"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # VLM 配置（图像形态学特征提取）
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "")
    VLM_BASE_URL: str = os.getenv("VLM_BASE_URL", "https://api.minimaxi.com/v1")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "MiniMax-M3")

    # 整合大模型配置（病历提取、多模态融合、报告生成）
    INTEGRATION_API_KEY: str = os.getenv("INTEGRATION_API_KEY", "")
    INTEGRATION_BASE_URL: str = os.getenv("INTEGRATION_BASE_URL", "https://api.deepseek.com")
    INTEGRATION_MODEL: str = os.getenv("INTEGRATION_MODEL", "deepseek-v4-flash")

    # 功能降级开关（本地调试时可设为 true）
    USE_MOCK_VLM: bool = os.getenv("USE_MOCK_VLM", "false").lower() == "true"
    USE_MOCK_INTEGRATION: bool = os.getenv("USE_MOCK_INTEGRATION", "false").lower() == "true"

    # Docker 环境与 HuggingFace 镜像
    DOCKER_ENV: bool = os.getenv("DOCKER_ENV", "false").lower() == "true"
    HF_ENDPOINT: str = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

    # KB-RAG 拓展模块配置
    ENABLE_KB_RAG: bool = os.getenv("ENABLE_KB_RAG", "false").lower() == "true"
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "")
    X_INTERNAL_SECRET: str = os.getenv("X_INTERNAL_SECRET", "")

    # CORS 配置，修复空字符串判断
    # Qdrant 连接，明确配置层级，不依赖隐式推断
    _origins_raw = os.getenv("ALLOWED_ORIGINS", "").strip()
    if not _origins_raw or _origins_raw == "*":
        ALLOWED_ORIGINS: list = ["*"]
    else:
        ALLOWED_ORIGINS: list = [o.strip() for o in _origins_raw.split(",") if o.strip()]


settings = Settings()

# 启动时配置校验
if not settings.VLM_API_KEY and not settings.USE_MOCK_VLM:
    logger.warning("VLM_API_KEY 未配置，且未启用 USE_MOCK_VLM。VLM 相关功能将不可用或降级。")

if not settings.INTEGRATION_API_KEY and not settings.USE_MOCK_INTEGRATION:
    logger.warning("INTEGRATION_API_KEY 未配置，且未启用 USE_MOCK_INTEGRATION。LLM 相关功能将不可用或降级。")

if settings.ENABLE_KB_RAG:
    if not settings.APP_BASE_URL or not settings.X_INTERNAL_SECRET:
        logger.warning("KB-RAG 模块已启用，但 APP_BASE_URL 或 X_INTERNAL_SECRET 未配置，任务回调将失败。")
