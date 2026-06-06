import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "mysql+aiomysql://root:root@localhost:3307/derma_ai")
    UPLOAD_DIR: str = "uploads"
    STATIC_DIR: str = "static"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # 视觉语言模型配置 (DeepSeek-VL2)
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "")
    VLM_BASE_URL: str = os.getenv("VLM_BASE_URL", "https://api.deepseek.com")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "deepseek-vl2")

    # 整合大模型/病历提取模型配置 (DeepSeek-V4-Flash)
    INTEGRATION_API_KEY: str = os.getenv("INTEGRATION_API_KEY", "")
    INTEGRATION_BASE_URL: str = os.getenv("INTEGRATION_BASE_URL", "https://api.deepseek.com")
    INTEGRATION_MODEL: str = os.getenv("INTEGRATION_MODEL", "deepseek-v4-flash")

    # 降级开关配置
    USE_MOCK_VLM: bool = os.getenv("USE_MOCK_VLM", "false").lower() == "true"
    USE_MOCK_INTEGRATION: bool = os.getenv("USE_MOCK_INTEGRATION", "true").lower() == "true"


settings = Settings()