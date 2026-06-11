import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


class Settings:
    """应用程序配置类。

    集中管理数据库连接、第三方 API 密钥及功能开关。
    配置优先级：环境变量 (.env) > 代码默认值。
    """

    # ==========================================================
    # 核心路径与数据库配置
    # ==========================================================
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "mysql+aiomysql://root:root@localhost:3307/derma_ai"
    )
    UPLOAD_DIR: str = "uploads"  # 原始文件存储路径（原图、DICOM）
    STATIC_DIR: str = "static"  # Web 可访问资源路径（热力图、缩略图）
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ==========================================================
    # 视觉语言模型 (VLM) 配置
    # 用于图像形态学特征提取
    # ==========================================================
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "")
    VLM_BASE_URL: str = os.getenv("VLM_BASE_URL", "https://api.minimaxi.com/v1")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "MiniMax-M3")

    # ==========================================================
    # 整合大模型 / 病历提取模型 配置
    # 用于多模态信息融合、结构化报告生成与病历文本解析
    # ==========================================================
    INTEGRATION_API_KEY: str = os.getenv("INTEGRATION_API_KEY", "")
    INTEGRATION_BASE_URL: str = os.getenv("INTEGRATION_BASE_URL", "https://api.deepseek.com")
    INTEGRATION_MODEL: str = os.getenv("INTEGRATION_MODEL", "deepseek-v4-flash")

    # ==========================================================
    # 功能降级开关
    # ==========================================================
    # 默认值为 False，遵循工程规范：生产环境必须使用真实推理。
    # 若需启用 Mock 模式（如本地调试），请在 .env 中显式设置为 true。
    USE_MOCK_VLM: bool = os.getenv("USE_MOCK_VLM", "false").lower() == "true"
    USE_MOCK_INTEGRATION: bool = os.getenv("USE_MOCK_INTEGRATION", "false").lower() == "true"


# 全局配置实例
settings = Settings()