import os
import re
import pymysql
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Float, DateTime, JSON, Integer, text

Base = declarative_base()


class ImageResource(Base):
    __tablename__ = "image_resources"

    image_uid = Column(String(50), primary_key=True)
    task_id = Column(String(50), nullable=False, index=True)
    format = Column(String(10), default="PNG")
    url = Column(String(255))
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
    image_uid = Column(String(50), index=True)
    status = Column(String(20), default="queued")
    error_code = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class AIFeature(Base):
    __tablename__ = "ai_features"

    image_uid = Column(String(50), primary_key=True)
    task_id = Column(String(50))
    ai_features = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=True)


# ==========================================
# 数据库连接配置
# ==========================================
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+aiomysql://root:root@localhost:3306/derma_ai"
)

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """
    初始化数据库：先用同步 pymysql 创建数据库（如果缺失），
    再用异步引擎执行 init.sql 建表。
    """
    match = re.match(r"mysql\+aiomysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", DATABASE_URL)
    if not match:
        print("Warning: Cannot parse DATABASE_URL.")
        return

    user, password, host, port, db = match.groups()

    sync_conn = pymysql.connect(
        host=host, port=int(port), user=user, password=password,
        charset='utf8mb4', autocommit=True
    )
    try:
        with sync_conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS {db} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        sync_conn.commit()
    finally:
        sync_conn.close()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    sql_file_path = os.path.join(base_dir, "..", "sql", "init.sql")

    if not os.path.exists(sql_file_path):
        print("Warning: backend-ai/sql/init.sql not found. Database tables may not be created.")
        return

    with open(sql_file_path, "r", encoding="utf-8") as f:
        sql_script = f.read()

    sql_script = sql_script.replace(
        "CREATE DATABASE IF NOT EXISTS derma_ai DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;", "")
    sql_script = sql_script.replace("USE derma_ai;", "")

    async with engine.begin() as conn:
        for statement in sql_script.split(";"):
            stmt = statement.strip()
            if stmt:
                await conn.execute(text(stmt))
    print("AI Domain Database initialized successfully.")


async def get_db():
    """FastAPI 依赖注入：获取异步数据库会话"""
    async with async_session() as session:
        yield session