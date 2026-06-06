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

# 新增 httpx 导入，用于 4.3 离线摄取
import httpx

from config import settings
from models.database import (
    async_session, get_db,
    ImageResource as ImageDB,
    AITask as TaskDB,
    AIFeature as FeatureDB,
)

# 新增 DicomParser 导入，用于 4.2 和 4.3 转码
from preprocessing.dicom_parser import DicomParser, DicomParseException

# 新增阶段5 AI 管线导入
from cnn.lesion_extractor import LesionExtractor
from agents.vlm_agent import VLMAgent
from agents.clinical_agent import parse_clinical_data  # 新增：病历 Agent
from agents.lab_agent import evaluate_lab_data  # 新增：化验 Agent
from rag.knowledge_base import RAGKnowledgeBase

# 新增阶段6 自定义异常导入
from exceptions import ModelInferenceException, DiagnosisUncertainException

# ==========================================
# 日志配置（替换所有 print）
# ==========================================
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==========================================
# Pydantic 模型定义 (严格对齐 v2.0 契约)
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


# ===== 新增多模态结构化报告模型 =====
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
    status: str = "completed"


# ==========================================
# 整合 Agent 骨架与 Mock 机制 (阶段 8)
# ==========================================
def run_integration_agent(task_id: str, image_result: dict, clinical_result: dict, lab_result: dict,
                          rag_passages: list):
    """
    整合 Agent：当前阶段走 Mock 逻辑，保障工程端联调。
    后续阶段 9 会替换为真实 LLM 调用。
    """
    logger.info(f"Running MOCK Integration Agent for task: {task_id}")

    # 根据 Prompt 是否缺失动态生成 Mock 提示
    missing_modalities = []
    if not image_result: missing_modalities.append("图像")
    if not clinical_result: missing_modalities.append("病历")
    if not lab_result: missing_modalities.append("化验")

    risk_msg = "数据不足无法评估" if missing_modalities else "中危 (Mock)"
    concern_text = f"缺乏{'、'.join(missing_modalities)}信息，建议完善相关检查" if missing_modalities else "Mock关注要点"

    return SSEResultEvent(
        task_id=task_id,
        risk_level=risk_msg,
        key_concerns=[KeyConcern(item=concern_text, source_id="R00")],
        recommendations=[Recommendation(item="请完善相关检查 (Mock建议)", source_id="R00")],
        differential=["Mock黑色素瘤", "Mock色素痣"],
        disclaimer="本建议仅供辅助参考，最终诊断由执业医师结合临床判断"
    )


# ==========================================
# FastAPI 初始化与配置
# ==========================================
os.makedirs(f"{settings.STATIC_DIR}/images", exist_ok=True)
os.makedirs(f"{settings.STATIC_DIR}/heatmaps", exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期：探测数据库连接 & 预加载 RAG 模型"""
    try:
        async with async_session() as session:
            await session.execute(select(ImageDB).limit(1))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise RuntimeError("Database not ready") from e

    # 预加载 RAG 知识库（耗时操作，仅启动时执行一次）
    try:
        app.state.rag_kb = RAGKnowledgeBase(docs_dir="./rag/docs")
        app.state.rag_kb.init_from_documents()
        logger.info("RAG Knowledge Base loaded OK")
    except Exception as e:
        logger.error(f"RAG Knowledge Base load failed: {e}")

    yield


app = FastAPI(
    title="DermaIntegrate AI Backend",
    description="智能推理域 API，严格遵循 v2.0 契约",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ai-static", StaticFiles(directory=settings.STATIC_DIR), name="static")


# 全局异常处理器：拦截证据链断裂异常，返回422
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
    支持按需触发模态 Agent，并推送语义化步级状态。
    """
    image_result, clinical_result, lab_result = None, None, None

    try:
        # 1. 图像 Agent (按需触发)
        if image_uid and original_image_path:
            if cancel_event.is_set(): raise InterruptedError()

            evidence_filename = f"{image_uid}_evidence.png"
            evidence_path = os.path.join(settings.STATIC_DIR, "heatmaps", evidence_filename)
            lesion_extractor.generate(original_image_path, evidence_path, cancel_event=cancel_event)
            evidence_url = f"/ai-static/heatmaps/{evidence_filename}"

            if cancel_event.is_set(): raise InterruptedError()
            morphology_dict = vlm_agent.analyze(original_image_path, evidence_path, cancel_event=cancel_event)

            image_result = {"image_url": evidence_url, "morphology": morphology_dict}
            queue.put_nowait(("step", {"step": "image_done", "message": "视觉定位与形态学完成", "data": image_result}))

        # 2. 病历 Agent 按需触发 (接入真实 LLM 解析)
        if clinical_json or clinical_text:
            if cancel_event.is_set(): raise InterruptedError()
            logger.info(f"Task {task_id}: Running Clinical Agent...")

            # 安全处理 clinical_json 的数据类型 (SQLAlchemy 可能返回 dict 或 str)
            c_json_str = None
            if clinical_json:
                c_json_str = clinical_json if isinstance(clinical_json, str) else json.dumps(clinical_json)

            clinical_result = parse_clinical_data(
                clinical_json_str=c_json_str,
                clinical_text=clinical_text
            )
            queue.put_nowait(
                ("step", {"step": "clinical_done", "message": "病历结构化解析完成", "data": clinical_result}))

        # 3. 化验 Agent 按需触发 (接入真实规则引擎与跨模态依赖)
        if lab_json:
            if cancel_event.is_set(): raise InterruptedError()
            logger.info(f"Task {task_id}: Running Lab Agent...")

            # 安全处理 lab_json 的数据类型 (化验 Agent 需要接收 dict)
            lab_dict = lab_json if isinstance(lab_json, dict) else json.loads(lab_json)

            # 跨模态依赖核心逻辑：从病历 Agent 的结果中提取病灶位置
            lesion_location = None
            if clinical_result and clinical_result.get("lesion"):
                lesion_location = clinical_result.get("lesion", {}).get("location")

            lab_result = evaluate_lab_data(lab_json=lab_dict, location_from_clinical=lesion_location)
            queue.put_nowait(("step", {"step": "lab_done", "message": "化验规则引擎完成", "data": lab_result}))

        # 4. 整合 Agent (必触发)
        if cancel_event.is_set(): raise InterruptedError()
        # RAG 暂时不传给 Mock Agent，避免干扰
        final_report = run_integration_agent(task_id, image_result, clinical_result, lab_result, [])

        # 管线执行成功，推送最终数据组装标记
        queue.put_nowait(("final_data", final_report.model_dump()))

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
        file: Optional[UploadFile] = File(None),  # 必须加 Optional 才能真正可选！
        clinical_text: str = Form(None),  # 新增：病历自由文本
        clinical_json: str = Form(None),  # 新增：结构化病历 JSON 字符串
        lab_json: str = Form(None),  # 新增：化验数据 JSON 字符串
        db: AsyncSession = Depends(get_db)
):
    """多模态数据上传：接收图片、病历文本/JSON、化验JSON，统一生成 task_id"""

    # 1. 校验：至少要有一个数据传入
    if not file and not clinical_text and not clinical_json and not lab_json:
        raise HTTPException(status_code=400, detail="至少需要提供一项模态数据 (图片、病历或化验)")

    task_id = str(uuid.uuid4())
    image_uid = None  # 默认无图片

    # 2. 文件处理逻辑 (仅当 file 存在时执行)
    img_status = "ready"  # 如果没有图片，默认 ready
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

        # 原始文件落盘
        raw_filename = f"{image_uid}_{file.filename or 'unknown'}"
        raw_path = os.path.join(settings.UPLOAD_DIR, raw_filename)
        with open(raw_path, "wb") as f:
            f.write(content)

        # 判断类型，决定路由
        is_dicom = file.content_type == "application/dicom" or ext == ".dcm"
        img_status = "processing"  # 有图片时，状态先置为处理中

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
            img_width = 1024  # 兜底值
            img_height = 768

        # 图片入库
        image = ImageDB(
            image_uid=image_uid,
            task_id=task_id,
            format=img_format,
            url=img_url,
            status=img_status,
            error_message=error_msg,
            width=img_width,
            height=img_height,
            original_dicom_tags=dicom_tags_json,
            created_at=datetime.now(timezone.utc)
        )
        db.add(image)

    # 3. 任务入库 (包含多模态上下文)
    task = TaskDB(
        task_id=task_id,
        image_uid=image_uid,
        status="queued",
        clinical_text=clinical_text,
        clinical_json=clinical_json,
        lab_json=lab_json,
        created_at=datetime.now(timezone.utc)
    )
    db.add(task)
    await db.commit()

    logger.info(
        f"Upload accepted: task_id={task_id}, image_uid={image_uid}, has_clinical={bool(clinical_json or clinical_text)}, has_lab={bool(lab_json)}")

    return UploadIngestResponse(task_id=task_id, status="accepted")


@app.post("/ingest", status_code=202, response_model=UploadIngestResponse, tags=["Task"])
async def ingest_image(req: IngestRequest, db: AsyncSession = Depends(get_db)):
    """离线摄取：下载URL资源，执行DICOM转码并入库"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    # 初始化入库所需的变量
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

    task = TaskDB(
        task_id=task_id,
        image_uid=image_uid,
        status="queued",
        created_at=datetime.now(timezone.utc)
    )
    db.add(task)

    image = ImageDB(
        image_uid=image_uid,
        task_id=task_id,
        format=img_format,
        url=img_url,
        status=img_status,
        error_message=error_msg,
        width=img_width if img_width else 1024,
        height=img_height if img_height else 768,
        original_dicom_tags=dicom_tags_json,
        created_at=datetime.now(timezone.utc)
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
        image_uid=image.image_uid,
        format=image.format,
        url=image.url,
        status=image.status,
        error_message=image.error_message,
        width=image.width,
        height=image.height,
        color_space=image.color_space or "sRGB",
        original_dicom_tags=dicom_tags
    )


@app.get("/stream/{task_id}", tags=["Diagnosis"])
async def stream_diagnosis(request: Request, task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TaskDB).where(TaskDB.task_id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        return create_error_response(404, "NotFound", "TASK_NOT_FOUND", "task_id 不存在")

    # 获取多模态上下文
    image_uid = task.image_uid
    clinical_text = task.clinical_text
    clinical_json = task.clinical_json
    lab_json = task.lab_json

    task.status = "running"
    await db.commit()

    # 获取图像物理路径 (如果有)
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

        # 启动子线程执行耗时推理管线
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
                        # 收到最终数据，执行入库，推送 result 事件
                        try:
                            result_event = SSEResultEvent(**data)

                            try:
                                async with async_session() as session:
                                    # 更新 Task 状态
                                    task_res = await session.execute(select(TaskDB).where(TaskDB.task_id == task_id))
                                    db_task = task_res.scalar_one()
                                    db_task.status = "completed"
                                    db_task.completed_at = datetime.now(timezone.utc)

                                    # 保存特征 (以 task_id 为主键)
                                    feat_res = await session.execute(
                                        select(FeatureDB).where(FeatureDB.task_id == task_id))
                                    existing_feature = feat_res.scalar_one_or_none()

                                    if existing_feature:
                                        existing_feature.ai_features = result_event.model_dump()
                                        existing_feature.image_uid = image_uid  # 同步更新关联的 image_uid
                                    else:
                                        feature = FeatureDB(
                                            task_id=task_id,
                                            image_uid=image_uid,
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


# 路由修改：从 /features/{image_uid} 改为 /features/{task_id}
@app.get("/features/{task_id}", response_model=SSEResultEvent, tags=["Diagnosis"])
async def get_historical_features(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureDB).where(FeatureDB.task_id == task_id))
    feature = result.scalar_one_or_none()

    if not feature:
        return create_error_response(404, "NotFound", "FEATURE_NOT_FOUND", "该任务尚无成功的推理结果")

    return SSEResultEvent(**feature.ai_features)