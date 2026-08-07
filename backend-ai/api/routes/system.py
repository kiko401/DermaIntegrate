"""系统路由：健康检查。"""
import logging

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.database import get_db, AITask as TaskDB

logger = logging.getLogger(__name__)
router = APIRouter(tags=["System"])


class HealthResponse(BaseModel):
    service: str
    status: str
    db: str


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    """健康检查端点。"""
    try:
        await db.execute(select(TaskDB.task_id).limit(1))
        return HealthResponse(service="backend-ai", status="UP", db="connected")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(service="backend-ai", status="DEGRADED", db="disconnected")
