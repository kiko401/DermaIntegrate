import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, DateTime, JSON, Integer, Text

from config import settings

logger = logging.getLogger(__name__)
Base = declarative_base()


class ImageResource(Base):
    __tablename__ = "image_resources"

    image_uid = Column(String(50), primary_key=True)
    task_id = Column(String(50), nullable=False, index=True)
    format = Column(String(10), default="PNG")
    url = Column(String(255), nullable=True)  # DICOM转码前可为NULL
    status = Column(String(20), default="processing")
    error_message = Column(String(255), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    color_space = Column(String(20), nullable=True)
    original_dicom_tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=True)


class AITask(Base):
    __tablename__ = "ai_tasks"

    task_id = Column(String(50), primary_key=True)
    # 允许为空：因为现在可能只传病历不传图片，没有图片就没有 image_uid
    image_uid = Column(String(50), nullable=True, index=True)

    status = Column(String(20), default="queued")
    error_code = Column(String(50), nullable=True)

    # ===== 新增多模态上下文存储字段 =====
    clinical_text = Column(Text, nullable=True, comment="病历自由文本输入")
    clinical_json = Column(Text, nullable=True, comment="病历结构化JSON输入")
    lab_json = Column(Text, nullable=True, comment="化验数据JSON输入")

    created_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class AIFeature(Base):
    __tablename__ = "ai_features"

    # 核心改造：特征绑定到 task_id，而不是 image_uid
    # 因为现在特征可能是多模态融合的结果，不一定只来源于图像
    task_id = Column(String(50), primary_key=True)
    image_uid = Column(String(50), nullable=True)  # 关联的图像（如果有）
    ai_features = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=True)


# 异步引擎：echo=False 避免日志刷屏
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI 依赖注入：获取异步数据库会话"""
    async with async_session() as session:
        yield session