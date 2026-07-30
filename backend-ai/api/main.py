import os
import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from config import settings
from models.database import async_session, get_db, ImageResource as ImageDB
from rag.knowledge_base import RAGKnowledgeBase
from exceptions import DiagnosisUncertainException
from utils.file_cleaner import cleanup_loop
from .routes import system_router, tasks_router, stream_router, features_router

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ENABLE_KB_RAG = settings.ENABLE_KB_RAG

# 确保静态目录存在
os.makedirs(f"{settings.STATIC_DIR}/images", exist_ok=True)
os.makedirs(f"{settings.STATIC_DIR}/heatmaps", exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：数据库探活 -> RAG初始化 -> 启动清理任务。"""
    # 1. 数据库探活（async，直接等待）
    try:
        async with async_session() as session:
            await session.execute(select(ImageDB).limit(1))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise RuntimeError("Database not ready") from e

    # 2. 旧 RAG 初始化：SentenceTransformer 下载/加载是同步阻塞调用，
    #    用 asyncio.to_thread 在线程池中运行，不阻塞事件循环
    def _init_rag():
        try:
            return RAGKnowledgeBase()
        except Exception as e:
            logger.error(f"RAG KB init failed: {e}")
            return None

    rag_init_task = asyncio.create_task(asyncio.to_thread(_init_rag))

    # 3. KB-RAG 模块注册（在 yield 之前执行）
    if ENABLE_KB_RAG:
        try:
            from modules.kb_rag import register_kb_rag_module
            register_kb_rag_module(app)
            logger.info("KB-RAG routes registered.")
        except Exception as e:
            logger.error(f"Failed to register KB-RAG routes: {e}")

        # KB-RAG 初始化：规则表必须创建，Qdrant/Embedding 失败不阻断
        try:
            from modules.kb_rag.rules.store import init_rules_table
            await init_rules_table()
            logger.info("KB-RAG rules tables initialized.")
            # Qdrant 集合初始化（网络问题不阻断）
            try:
                from modules.kb_rag.ingest.vector_store import init_qdrant_collection_async
                await init_qdrant_collection_async()
                logger.info("KB-RAG Qdrant collection initialized.")
            except Exception as e:
                logger.warning(f"KB-RAG Qdrant init skipped (non-fatal): {e}")
            # Embedding 模型预热（网络问题不阻断启动）
            try:
                from modules.kb_rag.ingest.embeddings import get_embedder
                await asyncio.to_thread(get_embedder)
                logger.info("KB-RAG embedding model loaded.")
            except Exception as e:
                logger.warning(f"KB-RAG embedding model load skipped (non-fatal): {e}")
        except Exception as e:
            logger.error(f"KB-RAG init failed: {e}")

    # 4. 启动清理任务（异步，无阻塞）
    cleanup_task = asyncio.create_task(cleanup_loop())
    logger.info("File cleanup background task started.")

    # 6. 【关键】在 yield 之前等待 rag_init 完成，
    #    确保 app.state.rag_kb 在服务器接受第一个请求前就已赋值
    #    注意：rag_init 在线程池中运行，await asyncio.to_thread 的结果是
    #    在子线程完全执行完毕后主线程才继续——这仍然是阻塞 startup 的，
    #    但避免了 uvicorn 启动前就阻塞（因为 to_thread 把阻塞转移到了线程池）
    rag_kb = await rag_init_task
    app.state.rag_kb = rag_kb

    # 8. 服务器现在开始接受连接（cleanup_task 已在后台运行）
    yield

    # shutdown：取消清理任务
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        logger.info("File cleanup background task cancelled.")


app = FastAPI(
    title="DermaIntegrate AI Backend",
    description="智能推理域 API，提供多模态辅助诊断服务",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ai-static", StaticFiles(directory=settings.STATIC_DIR), name="static")

# 注册路由
app.include_router(system_router)
app.include_router(tasks_router)
app.include_router(stream_router)
app.include_router(features_router)


@app.exception_handler(DiagnosisUncertainException)
async def diagnosis_uncertain_handler(request: Request, exc: DiagnosisUncertainException):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )

