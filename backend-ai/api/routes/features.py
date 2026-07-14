"""诊断结果路由：历史推理结果查询。"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.database import get_db, AIFeature as FeatureDB

router = APIRouter(tags=["Diagnosis"])


class KeyConcern(BaseModel):
    item: str
    source_id: str


class Recommendation(BaseModel):
    item: str
    source_id: str


class SSEResultEvent(BaseModel):
    task_id: str
    risk_level: str
    key_concerns: List[KeyConcern]
    recommendations: List[Recommendation]
    differential: List[str]
    disclaimer: str
    status: str = "complete"


@router.get("/features/{task_id}", response_model=SSEResultEvent)
async def get_historical_features(task_id: str, db: AsyncSession = Depends(get_db)) -> SSEResultEvent:
    """获取历史任务的诊断结果。"""
    result = await db.execute(select(FeatureDB).where(FeatureDB.task_id == task_id))
    feature = result.scalar_one_or_none()

    if not feature:
        raise HTTPException(
            status_code=404,
            detail="该任务尚无成功的推理结果"
        )

    return SSEResultEvent(**feature.ai_features)
