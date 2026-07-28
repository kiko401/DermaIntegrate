"""
知识库初始化路由

提供 API 接口来初始化和管理知识库数据。
包括从本地文档目录初始化、检查状态等。

API 列表：
- POST /rag/init/from-docs  : 从本地文档目录初始化知识库
- GET  /rag/init/status     : 查看知识库初始化状态
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

# 模块级缓存：避免每次请求重新加载 Embedding 模型
_cached_embedder = None


def _get_cached_embedder():
    """获取缓存的 embedder，单例模式避免重复加载模型"""
    global _cached_embedder
    if _cached_embedder is None:
        from rag.knowledge_base import RAGKnowledgeBase
        # 只在首次请求时初始化，后续复用
        _cached_embedder = RAGKnowledgeBase()
        logger.info("Embedder loaded and cached at module level")
    return _cached_embedder


class InitFromDocsRequest(BaseModel):
    """从文档初始化请求"""
    docs_dir: Optional[str] = None  # 文档目录路径，默认为 rag/docs/
    recreate: bool = False          # 是否重建（清空现有数据）


class InitStatusResponse(BaseModel):
    """初始化状态响应"""
    collection: str
    initialized: bool
    docs_dir: str
    points_count: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class InitResultResponse(BaseModel):
    """初始化结果响应"""
    status: str
    collection: str
    docs_dir: str
    count: int
    tags: List[str]


@router.post("/init/from-docs", response_model=InitResultResponse)
async def init_from_docs_endpoint(req: InitFromDocsRequest):
    """
    从本地文档目录初始化知识库。

    文档格式要求：
    - 文件位置：backend-ai/rag/docs/*.txt
    - 每行格式：[ID] 文本内容 {{tags:tag1,tag2,...}}
    - 例如：[AJCC-01] AJCC第8版黑色素瘤分期系统... {{tags:MEL,通用}}

    有效 tags：MEL、BCC、SCC、NEV、ACK、SEK、T1、T2、T3、T4、高危、肢端、黏膜、通用
    """
    try:
        from rag.knowledge_base import init_knowledge_base

        logger.info(f"Received init request: docs_dir={req.docs_dir}, recreate={req.recreate}")

        result = init_knowledge_base(docs_dir=req.docs_dir, recreate=req.recreate)

        if result["status"] == "skipped":
            raise HTTPException(status_code=404, detail=result["message"])

        return InitResultResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Init from docs failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/init/status", response_model=InitStatusResponse)
async def get_init_status_endpoint():
    """
    获取知识库初始化状态。

    返回：
    - collection: collection 名称
    - initialized: 是否已初始化
    - docs_dir: 文档目录路径
    - points_count: 当前向量数量（仅在已初始化时返回）
    - message: 状态说明
    """
    try:
        from rag.knowledge_base import check_knowledge_base_status

        status = check_knowledge_base_status()
        return InitStatusResponse(**status)

    except Exception as e:
        logger.error(f"Get init status failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
