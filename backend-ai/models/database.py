import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, DateTime, JSON, Integer, Text, Index

from config import settings

logger = logging.getLogger(__name__)
Base = declarative_base()


class ImageResource(Base):
    """
    图像资源表。
    存储上传的原始图像（DICOM 或普通图片）及其预处理后的元数据。
    """
    __tablename__ = "image_resources"

    image_uid = Column(String(50), primary_key=True, comment="图像唯一标识")
    task_id = Column(String(50), nullable=False, index=True, comment="关联的任务 ID")
    format = Column(String(10), default="PNG", comment="图像格式 (PNG/JPG/DICOM)")

    # DICOM 处理异步流程中，URL 可能为空，待转码完成后再更新
    url = Column(String(255), nullable=True, comment="可访问的静态资源 URL")

    status = Column(String(20), default="processing", comment="处理状态: processing/ready/failed")
    error_message = Column(String(255), nullable=True, comment="处理失败时的错误信息")
    width = Column(Integer, nullable=True, comment="图像宽度")
    height = Column(Integer, nullable=True, comment="图像高度")
    color_space = Column(String(20), nullable=True, comment="色彩空间")
    original_dicom_tags = Column(JSON, nullable=True, comment="原始 DICOM 元数据 (仅当源文件为 DICOM 时有值)")
    created_at = Column(DateTime, nullable=True, comment="创建时间")


class AITask(Base):
    """
    AI 推理任务表 (核心主表)。
    记录一次多模态推理请求的上下文数据。
    支持纯病历、纯化验或混合模态的输入。
    """
    __tablename__ = "ai_tasks"

    task_id = Column(String(50), primary_key=True, comment="任务唯一标识")

    # image_uid 允许为空，以支持无图推理场景（如仅有病历文本）
    image_uid = Column(String(50), nullable=True, index=True, comment="关联的图像资源 ID (如有)")

    status = Column(String(20), default="queued", comment="任务状态: queued/running/completed/failed")
    error_code = Column(String(50), nullable=True, comment="错误代码")

    # 多模态输入字段存储 (使用 Text 类型以容纳长文本或原始 JSON 字符串)
    clinical_text = Column(Text, nullable=True, comment="病历自由文本输入")
    clinical_json = Column(Text, nullable=True, comment="结构化病历 JSON 字符串")
    lab_json = Column(Text, nullable=True, comment="化验数据 JSON 字符串")

    created_at = Column(DateTime, nullable=True, comment="任务创建时间")
    completed_at = Column(DateTime, nullable=True, comment="任务完成时间")


class AIFeature(Base):
    """
    AI 推理结果特征表。
    存储最终生成的结构化诊断报告。
    """
    __tablename__ = "ai_features"

    # 主键为 task_id，确保每个任务有且仅有一条结果记录
    task_id = Column(String(50), primary_key=True, comment="关联的任务 ID")

    image_uid = Column(String(50), nullable=True, index=True, comment="关联的图像资源 ID (冗余字段，便于回溯)")

    # 存储完整的 Agent 输出结果 (JSON 格式)
    ai_features = Column(JSON, nullable=False, comment="AI 推理结果 JSON (包含 risk_level, recommendations 等)")

    created_at = Column(DateTime, nullable=True, comment="结果生成时间")


# ==========================================================
# 数据库连接配置
# ==========================================================
# 创建异步引擎，echo=False 避免在生产环境打印大量 SQL 语句
engine = create_async_engine(settings.DATABASE_URL, echo=False)
# 创建异步会话工厂
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """
    FastAPI 依赖注入：获取异步数据库会话。
    使用上下文管理器确保会话自动关闭。
    """
    async with async_session() as session:
        yield session