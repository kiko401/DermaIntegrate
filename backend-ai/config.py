import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "mysql+aiomysql://root:root@localhost:3306/derma_ai")
    UPLOAD_DIR: str = "uploads"
    STATIC_DIR: str = "static"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # 视觉语言模型配置 (DeepSeek-VL2)
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "")
    VLM_BASE_URL: str = os.getenv("VLM_BASE_URL", "https://api.deepseek.com")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "deepseek-vl2")

    # 降级开关配置 (当前设为 true 测试降级逻辑)
    USE_MOCK_VLM: bool = os.getenv("USE_MOCK_VLM", "false").lower() == "true"


settings = Settings()