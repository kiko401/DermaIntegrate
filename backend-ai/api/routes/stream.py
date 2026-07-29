"""流式诊断路由：SSE 实时推送推理进度与最终结果。"""

import os
import json
import logging
import asyncio
import threading
from datetime import datetime, timezone
from typing import Optional

from api.schemas import SSEResultEvent

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from shared.config import TASK_TIMEOUT_SECONDS
from models.database import get_db, ImageResource as ImageDB, AITask as TaskDB, AIFeature as FeatureDB, async_session
from pipeline.runner import run_pipeline_with_cancel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Diagnosis"])


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

    rag_kb = getattr(request.app.state, "rag_kb", None)

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

        # M-16: 任务超时保护（从 shared/config 统一读取）
        _task_timeout = TASK_TIMEOUT_SECONDS
        _heartbeat_interval = 15  # 心跳间隔秒数
        last_event_time = asyncio.get_event_loop().time()

        try:
            while True:
                if await request.is_disconnected():
                    cancel_event.set()
                    logger.warning(f"Client disconnected. Aborting task: {task_id}")
                    break

                try:
                    # 每隔 15 秒检查一次队列，超时则发送心跳
                    event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=_heartbeat_interval
                    )
                    last_event_time = asyncio.get_event_loop().time()

                    if event_type == "step":
                        # 发送 progress 事件（文档定义格式）
                        step_name = data.get("step", "")
                        stage_map = {
                            "image_done": ("vlm", 30),
                            "clinical_done": ("clinical", 50),
                            "pathology_done": ("pathology", 70),
                            "final": ("integration", 90),
                        }
                        if step_name in stage_map:
                            stage, percent = stage_map[step_name]
                            yield f"event: progress\ndata: {json.dumps({'stage': stage, 'percent': percent})}\n\n"
                        # 发送 step 事件（仅包含 step 和 message 字段，与文档一致）
                        yield f"event: step\ndata: {json.dumps({'step': step_name, 'message': data.get('message', '')})}\n\n"
                    elif event_type == "error":
                        # 文档定义 error 事件格式为 {error: string}，转换 runner 发出的 {error_code, message}
                        error_msg = data.get("message", data.get("error", "未知错误"))
                        yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                        break
                    elif event_type == "final_data":
                        try:
                            result_event = SSEResultEvent(**data)

                            async with async_session() as session:
                                task_res = await session.execute(
                                    select(TaskDB).where(TaskDB.task_id == task_id)
                                )
                                # M-17: 使用 scalar_one_or_none 避免 task 被删除时抛 NoResultFound
                                db_task = task_res.scalar_one_or_none()
                                if db_task is None:
                                    logger.error(f"Task {task_id} not found when saving results (may have been deleted)")
                                    yield f"event: error\ndata: {json.dumps({'error': '任务已被删除，无法保存结果'})}\n\n"
                                    break
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
                            # 文档定义：结果已生成但保存失败时，发送特殊 error 事件后仍发 result
                            yield f"event: error\ndata: {json.dumps({'error': '结果已生成但保存失败，请稍后查询 /features/{task_id}'})}\n\n"

                        yield f"event: result\ndata: {result_event.model_dump_json()}\n\n"
                        break

                except asyncio.TimeoutError:
                    # 心跳：15秒无事件则发送心跳保活
                    yield f"event: heartbeat\ndata: {json.dumps({})}\n\n"
                    # 同时检查是否超过任务总超时
                    elapsed = asyncio.get_event_loop().time() - last_event_time
                    if elapsed >= _task_timeout:
                        logger.error(f"Task {task_id} appears stuck (no events for {elapsed:.0f}s). Forcing cancellation.")
                        cancel_event.set()
                        yield f"event: error\ndata: {json.dumps({'error': f'任务执行超时（{_task_timeout}秒），请稍后重试或联系管理员'})}\n\n"
                        break
                    continue

        except asyncio.CancelledError:
            cancel_event.set()
        finally:
            inference_thread.join(timeout=2.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
