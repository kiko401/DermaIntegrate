import os
import logging
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def register_kb_rag_module(app: FastAPI):
    """
    注册 kb_rag 模块到 FastAPI 应用。
    """
    enabled = os.getenv("ENABLE_KB_RAG", "false").lower() == "true"
    if not enabled:
        logger.info("KB_RAG module is disabled (ENABLE_KB_RAG != true).")
        return

    logger.info("Registering KB_RAG module...")

    try:
        from .api.ingest_routes import router as ingest_router
        from .api.chat_routes import router as chat_router
        from .api.compat_routes import router as compat_router
        from .api.debug_routes import router as debug_router
        from .api.tool_routes import router as tool_router
        from .api.agent_routes import router as agent_router
        from .api.etl_routes import router as etl_router

        # 统一前缀 /rag
        app.include_router(ingest_router, prefix="/rag", tags=["KB_RAG Ingest"])
        app.include_router(chat_router, prefix="/rag", tags=["KB_RAG Chat"])
        app.include_router(compat_router, prefix="/rag", tags=["KB_RAG Compat"])
        app.include_router(debug_router, prefix="/rag", tags=["KB_RAG Debug"])
        app.include_router(tool_router, prefix="/rag", tags=["KB_RAG Tools"])
        app.include_router(agent_router, prefix="/rag", tags=["KB_RAG Agent"])
        app.include_router(etl_router, prefix="/rag", tags=["KB_RAG ETL"])

        logger.info("KB_RAG routes registered successfully.")

    except Exception as e:
        logger.error(f"Failed to register KB_RAG routes: {e}", exc_info=True)

    # 启动时预热 Qdrant 和 Embedding 模型
    @app.on_event("startup")
    async def startup_kb_rag_event():
        logger.info("KB_RAG startup: Initializing Qdrant collection and Embedding model...")
        from .ingest.vector_store import init_qdrant_collection
        from .ingest.embeddings import get_embedder
        try:
            init_qdrant_collection()
            get_embedder()  # 预加载模型
            logger.info("KB_RAG startup completed successfully.")
        except Exception as e:
            logger.error(f"KB_RAG startup failed: {e}", exc_info=True)