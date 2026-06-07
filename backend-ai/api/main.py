import asyncio
import json
import os
import shutil
import uuid
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import httpx

from config import settings
from models.database import (
    async_session, get_db,
    ImageResource as ImageDB,
    AITask as TaskDB,
    AIFeature as FeatureDB,
)

from preprocessing.dicom_parser import DicomParser, DicomParseException

from cnn.lesion_extractor import LesionExtractor
from agents.vlm_agent import VLMAgent
from agents.clinical_agent import parse_clinical_data
from agents.pathology_agent import evaluate_pathology_data
from agents.integration_agent import run_integration_agent
from rag.knowledge_base import RAGKnowledgeBase

from exceptions import ModelInferenceException, DiagnosisUncertainException

# ==========================================
# 日志配置
# ==========================================
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==========================================
# Pydantic 模型定义
# ==========================================
class ErrorResponse(BaseModel):
    error: str
    error_code: str
    message: str


class UploadIngestResponse(BaseModel):
    task_id: str
    status: str


class IngestRequest(BaseModel):
    image_source: str
    patient_id: Optional[str] = None
    study_uid: Optional[str] = None


class DicomTags(BaseModel):
    PatientID: Optional[str] = None
    StudyInstanceUID: Optional[str] = None
    PhotometricInterpretation: Optional[str] = None


class ImageMetadataResponse(BaseModel):
    image_uid: str
    format: str = "PNG"
    url: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    color_space: Optional[str] = "sRGB"
    original_dicom_tags: Optional[DicomTags] = None


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


# ==========================================
# FastAPI 初始化与配置
# ==========================================
os.makedirs(f"{settings.STATIC_DIR}/images", exist_ok=True)
os.makedirs(f"{settings.STATIC_DIR}/heatmaps", exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期：探测数据库连接 & 挂载 RAG 检索器"""
    try:
        async with async_session() as session:
            await session.execute(select(ImageDB).limit(1))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise RuntimeError("Database not ready") from e

    # 🚨 核心修复：API启动时只需实例化连接 Qdrant 的检索器
    # 不需要重新执行向量化入库，那是 init_rag.py 离线干的活
    try:
        app.state.rag_kb = RAGKnowledgeBase()
        logger.info("RAG Knowledge Base connector initialized OK")
    except Exception as e:
        logger.error(f"RAG Knowledge Base init failed: {e}")
        app.state.rag_kb = None  # 降级处理，防止启动崩溃

    yield


app = FastAPI(
    title="DermaIntegrate AI Backend",
    description="智能推理域 API，严格遵循 v3.1 契约",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ai-static", StaticFiles(directory=settings.STATIC_DIR), name="static")


# 全局异常处理器
@app.exception_handler(DiagnosisUncertainException)
async def diagnosis_uncertain_handler(request: Request, exc: DiagnosisUncertainException):
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )


# 全局初始化视觉提取器和 VLM Agent
lesion_extractor = LesionExtractor()
vlm_agent = VLMAgent()


# ==========================================
# 辅助函数
# ==========================================
def create_error_response(status_code: int, error: str, error_code: str, message: str):
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, error_code=error_code, message=message).model_dump()
    )


def run_pipeline_with_cancel(task_id: str, image_uid: Optional[str], original_image_path: Optional[str],
                             clinical_text: Optional[str], clinical_json: Optional[str], lab_json: Optional[str],
                             cancel_event: threading.Event, queue: asyncio.Queue, rag_kb: RAGKnowledgeBase):
    """
    可取消的多模态推理管线包装，在独立子线程中执行。
    """
    image_result, clinical_result, pathology_result = None, None, None

    try:
        # 1. 图像 Agent
        if image_uid and original_image_path:
            if cancel_event.is_set(): raise InterruptedError()

            evidence_filename = f"{image_uid}_evidence.png"
            evidence_path = os.path.join(settings.STATIC_DIR, "heatmaps", evidence_filename)

            visual_features = lesion_extractor.generate(original_image_path, evidence_path, cancel_event=cancel_event)
            evidence_url = f"/ai-static/heatmaps/{evidence_filename}"

            if cancel_event.is_set(): raise InterruptedError()
            morphology_dict = vlm_agent.analyze(original_image_path, evidence_path, cancel_event=cancel_event)

            image_result = {
                "image_url": evidence_url,
                "morphology": morphology_dict,
                "coverage": visual_features.get("coverage", 0) if visual_features else 0,
                "location": visual_features.get("location", "未知") if visual_features else "未知"
            }
            queue.put_nowait(("step", {"step": "image_done", "message": "视觉定位与形态学完成", "data": image_result}))

        # 2. 病历 Agent
        if clinical_json or clinical_text:
            if cancel_event.is_set(): raise InterruptedError()
            logger.info(f"Task {task_id}: Running Clinical Agent...")

            c_json_str = None
            if clinical_json:
                c_json_str = clinical_json if isinstance(clinical_json, str) else json.dumps(clinical_json)

            clinical_result = parse_clinical_data(
                clinical_json_str=c_json_str,
                clinical_text=clinical_text
            )
            queue.put_nowait(
                ("step", {"step": "clinical_done", "message": "病历结构化解析完成", "data": clinical_result}))

        # 3. 病理与分子 Agent
        if lab_json:
            if cancel_event.is_set(): raise InterruptedError()
            logger.info(f"Task {task_id}: Running Pathology Agent...")

            path_dict = lab_json if isinstance(lab_json, dict) else json.loads(lab_json)

            lesion_location = None
            if clinical_result and clinical_result.get("lesion_clinical"):
                lesion_location = clinical_result.get("lesion_clinical", {}).get("region")

            pathology_result = evaluate_pathology_data(pathology_json=path_dict, location_from_clinical=lesion_location)
            queue.put_nowait(("step", {"step": "pathology_done", "message": "病理与分子规则引擎完成", "data": pathology_result}))

        # 4. RAG 两阶段检索
        rag_passages = []
        if rag_kb:
            if cancel_event.is_set(): raise InterruptedError()
            try:
                rag_passages = rag_kb.retrieve(image_result, clinical_result, pathology_result, top_k=3)
                logger.info(f"Task {task_id}: Retrieved {len(rag_passages)} RAG passages.")
            except Exception as e:
                logger.error(f"Task {task_id}: RAG retrieval failed: {e}. Proceeding without RAG.")

        # 5. 整合 Agent
        if cancel_event.is_set(): raise InterruptedError()
        final_report_dict = run_integration_agent(task_id, image_result, clinical_result, pathology_result, rag_passages)

        queue.put_nowait(("final_data", final_report_dict))

    except InterruptedError:
        logger.info(f"Pipeline execution cancelled for task: {task_id}")
        queue.put_nowait(("error", {"error_code": "CANCELLED", "message": "推理任务被中断取消"}))
    except ModelInferenceException as e:
        logger.error(f"Model inference failed for task {task_id}: {e}")
        queue.put_nowait(("error", {"error_code": "INFERENCE_FAILED", "message": str(e)}))
    except DiagnosisUncertainException as e:
        logger.warning(f"Evidence chain broken for task {task_id}: {e}")
        queue.put_nowait(("error", {"error_code": "EVIDENCE_CHAIN_BROKEN", "message": str(e)}))
    except Exception as e:
        logger.error(f"Pipeline unknown error for task {task_id}: {e}", exc_info=True)
        queue.put_nowait(("error", {"error_code": "INTERNAL_ERROR", "message": f"未知异常: {str(e)}"}))


# ==========================================
# 接口实现
# ==========================================
@app.get("/health", tags=["System"])
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(TaskDB.task_id).limit(1))
        return {"service": "backend-ai", "status": "UP", "db": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"service": "backend-ai", "status": "DEGRADED", "db": "disconnected"}


@app.post("/upload", status_code=202, response_model=UploadIngestResponse, tags=["Task"])
async def upload_data(
        file: Optional[UploadFile] = File(None),
        clinical_text: Optional[str] = Form(None),
        clinical_json: Optional[str] = Form(None),
        lab_json: Optional[str] = Form(None),
        db: AsyncSession = Depends(get_db)
):
    if not file and not clinical_text and not clinical_json and not lab_json:
        raise HTTPException(status_code=400, detail="至少需要提供一项模态数据 (图片、病历或化验)")

    task_id = str(uuid.uuid4())
    image_uid = None

    img_status = "ready"
    img_url = None
    img_format = None
    img_width = None
    img_height = None
    dicom_tags_json = None
    error_msg = None

    if file:
        image_uid = f"img_{uuid.uuid4().hex[:16]}"
        content = await file.read()
        ext = os.path.splitext(file.filename or "")[1].lower()
        if not ext: ext = ".png"

        raw_filename = f"{image_uid}_{file.filename or 'unknown'}"
        raw_path = os.path.join(settings.UPLOAD_DIR, raw_filename)
        with open(raw_path, "wb") as f:
            f.write(content)

        is_dicom = file.content_type == "application/dicom" or ext == ".dcm"
        img_status = "processing"

        if is_dicom:
            img_format = "DICOM"
            try:
                parser = DicomParser(raw_path)
                static_filename = f"{image_uid}.png"
                static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
                img = parser.save_as_png(static_path)

                img_status = "ready"
                img_url = f"/ai-static/images/{static_filename}"
                img_format = "PNG"
                img_width = img.width
                img_height = img.height
                dicom_tags_json = parser.metadata_dict
            except DicomParseException as e:
                img_status = "failed"
                error_msg = str(e)
        else:
            static_filename = f"{image_uid}{ext}"
            static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
            shutil.copy(raw_path, static_path)

            img_status = "ready"
            img_url = f"/ai-static/images/{static_filename}"
            img_format = ext.lstrip(".").upper()
            img_width = 1024
            img_height = 768

        image = ImageDB(
            image_uid=image_uid, task_id=task_id, format=img_format, url=img_url, status=img_status,
            error_message=error_msg, width=img_width, height=img_height,
            original_dicom_tags=dicom_tags_json, created_at=datetime.now(timezone.utc)
        )
        db.add(image)

    task = TaskDB(
        task_id=task_id, image_uid=image_uid, status="queued",
        clinical_text=clinical_text, clinical_json=clinical_json, lab_json=lab_json,
        created_at=datetime.now(timezone.utc)
    )
    db.add(task)
    await db.commit()

    logger.info(f"Upload accepted: task_id={task_id}, image_uid={image_uid}, has_clinical={bool(clinical_json or clinical_text)}, has_lab={bool(lab_json)}")

    return UploadIngestResponse(task_id=task_id, status="accepted")


@app.post("/ingest", status_code=202, response_model=UploadIngestResponse, tags=["Task"])
async def ingest_image(req: IngestRequest, db: AsyncSession = Depends(get_db)):
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    img_status = "processing"
    img_url = None
    img_format = "DICOM"
    img_width = None
    img_height = None
    dicom_tags_json = None
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(req.image_source)
            response.raise_for_status()
            content = response.content

        ext = os.path.splitext(req.image_source)[1].lower() or ".dcm"
        raw_filename = f"{image_uid}_ingest{ext}"
        raw_path = os.path.join(settings.UPLOAD_DIR, raw_filename)
        with open(raw_path, "wb") as f:
            f.write(content)

        try:
            parser = DicomParser(raw_path)
            static_filename = f"{image_uid}.png"
            static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
            img = parser.save_as_png(static_path)

            img_status = "ready"
            img_url = f"/ai-static/images/{static_filename}"
            img_format = "PNG"
            img_width = img.width
            img_height = img.height
            dicom_tags_json = parser.metadata_dict
        except DicomParseException as e:
            img_status = "failed"
            error_msg = str(e)

    except httpx.HTTPError as e:
        img_status = "failed"
        error_msg = f"文件下载失败: {str(e)}"

    task = TaskDB(task_id=task_id, image_uid=image_uid, status="queued", created_at=datetime.now(timezone.utc))
    db.add(task)

    image = ImageDB(
        image_uid=image_uid, task_id=task_id, format=img_format, url=img_url, status=img_status,
        error_message=error_msg, width=img_width if img_width else 1024, height=img_height if img_height else 768,
        original_dicom_tags=dicom_tags_json, created_at=datetime.now(timezone.utc)
    )
    db.add(image)
    await db.commit()

    return UploadIngestResponse(task_id=task_id, status="accepted")


@app.get("/images/{image_uid}", response_model=ImageMetadataResponse, tags=["Image"])
async def get_image(image_uid: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ImageDB).where(ImageDB.image_uid == image_uid))
    image = result.scalar_one_or_none()

    if not image:
        return create_error_response(404, "NotFound", "IMAGE_NOT_FOUND", "影像 UID 不存在")

    dicom_tags = None
    if image.original_dicom_tags:
        dicom_tags = DicomTags(**image.original_dicom_tags)

    return ImageMetadataResponse(
        image_uid=image.image_uid, format=image.format, url=image.url, status=image.status,
        error_message=image.error_message, width=image.width, height=image.height,
        color_space=image.color_space or "sRGB", original_dicom_tags=dicom_tags
    )


@app.get("/stream/{task_id}", tags=["Diagnosis"])
async def stream_diagnosis(request: Request, task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TaskDB).where(TaskDB.task_id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        return create_error_response(404, "NotFound", "TASK_NOT_FOUND", "task_id 不存在")

    image_uid = task.image_uid
    clinical_text = task.clinical_text
    clinical_json = task.clinical_json
    lab_json = task.lab_json

    task.status = "running"
    await db.commit()

    original_image_path = None
    if image_uid:
        img_result = await db.execute(select(ImageDB).where(ImageDB.image_uid == image_uid))
        img_record = img_result.scalar_one_or_none()

        if not img_record or not img_record.url or img_record.status != "ready":
            return create_error_response(400, "Bad Request", "IMAGE_NOT_READY", "影像尚未准备就绪或处理失败")

        relative_path = img_record.url.replace("/ai-static/", "")
        original_image_path = os.path.join(settings.STATIC_DIR, relative_path)

    rag_kb = request.app.state.rag_kb

    async def event_generator():
        cancel_event = threading.Event()
        queue = asyncio.Queue()

        inference_thread = threading.Thread(
            target=run_pipeline_with_cancel,
            args=(task_id, image_uid, original_image_path,
                  clinical_text, clinical_json, lab_json,
                  cancel_event, queue, rag_kb),
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

                            try:
                                async with async_session() as session:
                                    task_res = await session.execute(select(TaskDB).where(TaskDB.task_id == task_id))
                                    db_task = task_res.scalar_one()
                                    db_task.status = "completed"
                                    db_task.completed_at = datetime.now(timezone.utc)

                                    feat_res = await session.execute(select(FeatureDB).where(FeatureDB.task_id == task_id))
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

                        except Exception as assemble_e:
                            logger.error(f"Error assembling final result: {assemble_e}")
                            yield f"event: error\ndata: {json.dumps({'error_code': 'ASSEMBLE_ERROR', 'message': str(assemble_e)})}\n\n"
                            break

                except asyncio.QueueEmpty:
                    yield f"event: heartbeat\ndata: {{}}\n\n"
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            cancel_event.set()
        finally:
            inference_thread.join(timeout=2.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/features/{task_id}", response_model=SSEResultEvent, tags=["Diagnosis"])
async def get_historical_features(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureDB).where(FeatureDB.task_id == task_id))
    feature = result.scalar_one_or_none()

    if not feature:
        return create_error_response(404, "NotFound", "FEATURE_NOT_FOUND", "该任务尚无成功的推理结果")

    return SSEResultEvent(**feature.ai_features)