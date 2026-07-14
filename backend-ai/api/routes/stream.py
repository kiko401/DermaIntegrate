"""流式诊断路由：SSE 实时推送推理进度与最终结果。"""

import os
import json
import logging
import asyncio
import threading
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from models.database import get_db, ImageResource as ImageDB, AITask as TaskDB, AIFeature as FeatureDB, async_session
from pipeline.runner import run_pipeline_with_cancel

logger = logging.getLogger(__name__)
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


@router.get("/stream/{task_id}")
async def stream_diagnosis(request: Request, task_id: str, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    """SSE 流式诊断接口，实时推送推理步骤与最终结果。"""
    result = await db.execute(select(TaskDB).where(TaskDB.task_id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="task_id 不存在")

    image_uid = task.image_uid
    original_image_path: Optional[str] = None
    if image_uid:
        img_result = await db.execute(select(ImageDB).where(ImageDB.image_uid == image_uid))
        img_record = img_result.scalar_one_or_none()
        if not img_record or not img_record.url or img_record.status != "ready":
            raise HTTPException(
                status_code=400,
                detail="影像尚未准备就绪或处理失败"
            )

        relative_path = img_record.url.replace("/ai-static/", "")
        original_image_path = os.path.join(settings.STATIC_DIR, relative_path)

    task.status = "running"
    await db.commit()

    rag_kb = request.app.state.rag_kb

    async def event_generator():
        cancel_event = threading.Event()
        queue: asyncio.Queue = asyncio.Queue()

        inference_thread = threading.Thread(
            target=run_pipeline_with_cancel,
            args=(
                task_id, image_uid, original_image_path,
                task.clinical_text, task.clinical_json, task.lab_json,
                cancel_event, queue, rag_kb
            ),
            daemon=True
        )
        inference_thread.start()

        try:
            while True:
                if await request.is_disconnected():
                    cancel_event.set()
                    logger.warning(f"Client disconnected. Aborting task: {task_id}")
                    break

                try:
                    event_type, data = queue.get_nowait()

                    if event_type == "step":
                        yield f"event: step\ndata: {json.dumps(data)}\n\n"
                    elif event_type == "error":
                        yield f"event: error\ndata: {json.dumps(data)}\n\n"
                        break
                    elif event_type == "final_data":
                        try:
                            result_event = SSEResultEvent(**data)

                            async with async_session() as session:
                                task_res = await session.execute(
                                    select(TaskDB).where(TaskDB.task_id == task_id)
                                )
                                db_task = task_res.scalar_one()
                                db_task.status = "completed"
                                db_task.completed_at = datetime.now(timezone.utc)

                                feat_res = await session.execute(
                                    select(FeatureDB).where(FeatureDB.task_id == task_id)
                                )
                                existing_feature = feat_res.scalar_one_or_none()

                                if existing_feature:
                                    existing_feature.ai_features = result_event.model_dump()
                                    existing_feature.image_uid = image_uid
                                else:
                                    feature = FeatureDB(
                                        task_id=task_id, image_uid=image_uid,
                                        ai_features=result_event.model_dump(),
                                        created_at=datetime.now(timezone.utc)
                                    )
                                    session.add(feature)
                                await session.commit()
                        except Exception as db_e:
                            logger.error(f"Error saving inference results to DB: {db_e}")

                        yield f"event: result\ndata: {result_event.model_dump_json()}\n\n"
                        break

                except asyncio.QueueEmpty:
                    yield f"event: heartbeat\ndata: {{}}\n\n"
                    await asyncio.sleep(15)

        except asyncio.CancelledError:
            cancel_event.set()
        finally:
            inference_thread.join(timeout=2.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
