"""系统路由：健康检查。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.database import get_db, AITask as TaskDB

router = APIRouter(tags=["System"])


class HealthResponse(BaseModel):
    service: str
    status: str
    db: str


@router.get("/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """健康检查端点。"""
    try:
        await db.execute(select(TaskDB.task_id).limit(1))
        return HealthResponse(service="backend-ai", status="UP", db="connected")
    except Exception as e:
        import logging
        logging.error(f"Health check failed: {e}")
        return HealthResponse(service="backend-ai", status="DEGRADED", db="disconnected")
