import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "mysql+aiomysql://root:root@localhost:3306/derma_ai")
    UPLOAD_DIR: str = "uploads"
    STATIC_DIR: str = "static"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # 后续阶段4/5会用到，先占坑
    USE_MOCK_VLM: bool = os.getenv("USE_MOCK_VLM", "false").lower() == "true"

settings = Settings()