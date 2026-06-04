import asyncio
import json
import os
import shutil
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, Request, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from models.database import (
    async_session, get_db,
    ImageResource as ImageDB,
    AITask as TaskDB,
    AIFeature as FeatureDB,
)

# ==========================================
# 日志配置（替换所有 print）
# ==========================================
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==========================================
# Pydantic 模型定义 (严格对齐 api-contract.yaml)
# ==========================================
class ErrorResponse(BaseModel):
    error: str
    error_code: str
    message: str


class UploadIngestResponse(BaseModel):
    task_id: str
    image_uid: str
    filename: Optional[str] = None
    content_type: Optional[str] = None
    status: str
    message: str


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
    url: Optional[str] = None  # 修改：DICOM可能为null
    status: str
    error_message: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    color_space: Optional[str] = "sRGB"
    original_dicom_tags: Optional[DicomTags] = None


class VisualEvidence(BaseModel):
    heatmap_url: str
    image_url: str
    lesion_region: List[int] = Field(..., min_length=4, max_length=4)


class Morphology(BaseModel):
    model_config = ConfigDict(extra='forbid')
    border: str
    pigment_network: str
    color_distribution: str
    diameter: Optional[str] = None
    symmetry: Optional[str] = None
    vascular_pattern: Optional[str] = None


class RagCitation(BaseModel):
    title: str
    source: Optional[str] = None
    relevance: float
    excerpt: Optional[str] = None


class SSEResultEvent(BaseModel):
    task_id: str
    image_uid: str
    visual_evidence: VisualEvidence
    morphology: Morphology
    rag_citations: List[RagCitation]
    confidence: float
    status: str = "completed"
    disclaimer: str
    completed_at: str


# ==========================================
# FastAPI 初始化与配置
# ==========================================
os.makedirs(f"{settings.STATIC_DIR}/images", exist_ok=True)
os.makedirs(f"{settings.STATIC_DIR}/heatmaps", exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期：仅做数据库连接探测，不建表"""
    try:
        async with async_session() as session:
            await session.execute(select(ImageDB).limit(1))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise RuntimeError("Database not ready") from e
    yield


app = FastAPI(
    title="DermaIntegrate AI Backend",
    description="智能推理域 API，严格遵循 api-contract.yaml",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ai-static", StaticFiles(directory=settings.STATIC_DIR), name="static")


# ==========================================
# 辅助函数
# ==========================================
def create_error_response(status_code: int, error: str, error_code: str, message: str):
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, error_code=error_code, message=message).model_dump()
    )


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


@app.post("/upload", status_code=202, response_model=UploadIngestResponse, tags=["Image"])
async def upload_image(
        file: UploadFile = File(...),
        patient_id: Optional[str] = Form(None),
        study_uid: Optional[str] = Form(None),
        db: AsyncSession = Depends(get_db)
):
    """上传影像：所有文件先落 uploads/，普通图片复制到 static/images/"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    content = await file.read()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if not ext:
        ext = ".png"

    # 1. 所有原始文件先落 uploads/（原始文件保全）
    raw_filename = f"{image_uid}_{file.filename or 'unknown'}"
    raw_path = os.path.join(settings.UPLOAD_DIR, raw_filename)
    with open(raw_path, "wb") as f:
        f.write(content)

    # 2. 判断类型，决定路由
    is_dicom = file.content_type == "application/dicom" or ext == ".dcm"

    if is_dicom:
        # DICOM：等待阶段4转码管线，url留空，status=processing
        img_status = "processing"
        img_url = None
        img_format = "DICOM"
    else:
        # 普通图片：复制到 static/images/，直接可访问
        static_filename = f"{image_uid}{ext}"
        static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
        shutil.copy(raw_path, static_path)

        img_status = "ready"
        img_url = f"/ai-static/images/{static_filename}"
        img_format = ext.lstrip(".").upper() if ext else "PNG"

    # 3. 入库
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
        width=1024,  # 阶段4用PIL读取真实尺寸替换
        height=768,
        created_at=datetime.now(timezone.utc)
    )
    db.add(image)
    await db.commit()

    logger.info(f"Upload accepted: task_id={task_id}, image_uid={image_uid}, status={img_status}")

    return UploadIngestResponse(
        task_id=task_id,
        image_uid=image_uid,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        status="accepted",
        message="影像已接收，预处理启动中" if is_dicom else "影像已就绪"
    )


@app.post("/ingest", status_code=202, response_model=UploadIngestResponse, tags=["Image"])
async def ingest_image(req: IngestRequest, db: AsyncSession = Depends(get_db)):
    """离线摄取：仅创建记录，实际下载转码在阶段4实现"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

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
        format="DICOM",
        url=None,  # 下载转码后更新
        status="processing",  # 明确标记为处理中
        width=1024,
        height=768,
        original_dicom_tags={
            "PatientID": req.patient_id or "MOCK_PATIENT_001",
            "StudyInstanceUID": req.study_uid or f"study_{uuid.uuid4().hex[:8]}",
            "PhotometricInterpretation": "YBR_FULL_422"
        },
        created_at=datetime.now(timezone.utc)
    )
    db.add(image)
    await db.commit()

    logger.info(f"Ingest task created: task_id={task_id}, source={req.image_source}")

    return UploadIngestResponse(
        task_id=task_id,
        image_uid=image_uid,
        filename=req.image_source.split("/")[-1],
        content_type="application/dicom",
        status="accepted",
        message="摄取任务已接受，DICOM解析启动中"
    )


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

    image_uid = task.image_uid
    task.status = "running"
    await db.commit()

    async def event_generator():
        steps = [
            {"step": 1, "stage": "image_preprocessing", "msg": "影像预处理完成", "progress": 0.2},
            {"step": 2, "stage": "gradcam", "msg": "显著性区域提取完成", "progress": 0.4,
             "data": {"image_url": f"/ai-static/images/{image_uid}.png"}},
            {"step": 3, "stage": "vlm_analysis", "msg": "形态学描述生成中...", "progress": 0.6},
            {"step": 4, "stage": "rag_retrieval", "msg": "检索相关医学文献...", "progress": 0.8},
            {"step": 5, "stage": "evidence_integration", "msg": "证据链组装完成", "progress": 1.0},
        ]

        for step_data in steps:
            if await request.is_disconnected():
                logger.warning(f"Client disconnected during step {step_data['step']}. Aborting.")
                return

            yield f"event: step\ndata: {json.dumps(step_data)}\n\n"
            await asyncio.sleep(0.8)

            hb_data = {"ping": True}
            yield f"event: heartbeat\ndata: {json.dumps(hb_data)}\n\n"

        result_event = SSEResultEvent(
            task_id=task_id,
            image_uid=image_uid,
            visual_evidence=VisualEvidence(
                heatmap_url=f"/ai-static/heatmaps/{image_uid}_heatmap.png",
                image_url=f"/ai-static/images/{image_uid}.png",
                lesion_region=[120, 80, 300, 250]
            ),
            morphology=Morphology(
                border="不规则",
                pigment_network="非典型网络",
                color_distribution="多色不均匀",
                diameter=">6mm",
                symmetry="不对称",
                vascular_pattern="点状不规则血管"
            ),
            rag_citations=[
                RagCitation(
                    title="皮肤镜诊断指南2024",
                    source="中华皮肤科杂志",
                    relevance=0.92,
                    excerpt="色素网络变异伴边界不规则提示需进一步评估..."
                )
            ],
            confidence=0.85,
            disclaimer="本结果仅为AI辅助证据，最终诊断裁量权归临床医生所有。",
            completed_at=datetime.now(timezone.utc).isoformat()
        )

        try:
            async with async_session() as session:
                img_res = await session.execute(select(ImageDB).where(ImageDB.image_uid == image_uid))
                img = img_res.scalar_one()
                img.status = "ready"

                feature = FeatureDB(
                    image_uid=image_uid,
                    task_id=task_id,
                    ai_features=result_event.model_dump(),
                    created_at=datetime.now(timezone.utc)
                )
                session.add(feature)
                await session.commit()
        except Exception as e:
            logger.error(f"Error saving inference results to DB: {e}")

        yield f"event: result\ndata: {result_event.model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/features/{image_uid}", response_model=SSEResultEvent, tags=["Diagnosis"])
async def get_historical_features(image_uid: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureDB).where(FeatureDB.image_uid == image_uid))
    feature = result.scalar_one_or_none()

    if not feature:
        return create_error_response(404, "NotFound", "FEATURE_NOT_FOUND", "该影像尚无成功的推理结果")

    return SSEResultEvent(**feature.ai_features)