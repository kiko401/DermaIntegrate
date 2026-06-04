import asyncio
import json
import os
import uuid
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

from models.database import (
    init_db, get_db, async_session,
    ImageResource as ImageDB,
    AITask as TaskDB,
    AIFeature as FeatureDB,
)


# ==========================================
# 1. Pydantic 模型定义 (严格对齐 api-contract.yaml)
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
    url: str
    status: str  # processing, ready, failed
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
    # 等效于 JSON Schema 的 additionalProperties: false
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
    completed_at: str  # ISO格式时间戳


# ==========================================
# 2. FastAPI 初始化与配置
# ==========================================

os.makedirs("static/images", exist_ok=True)
os.makedirs("static/heatmaps", exist_ok=True)
os.makedirs("uploads", exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 服务启动时自动执行数据库初始化（建表）
    await init_db()
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

app.mount("/ai-static", StaticFiles(directory="static"), name="static")


# ==========================================
# 3. 辅助函数
# ==========================================

def create_error_response(status_code: int, error: str, error_code: str, message: str):
    """生成符合契约的统一错误响应"""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, error_code=error_code, message=message).model_dump()
    )


# ==========================================
# 4. 接口实现
# ==========================================

@app.get("/health", tags=["System"])
async def health(db: AsyncSession = Depends(get_db)):
    # 增加数据库心跳检测，微服务部署标准实践
    try:
        await db.execute(select(TaskDB.task_id).limit(1))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return {"service": "backend-ai", "status": "UP", "db": db_status}


@app.post("/upload", status_code=202, response_model=UploadIngestResponse, tags=["Image"])
async def upload_image(
        file: UploadFile = File(...),
        patient_id: Optional[str] = Form(None),
        study_uid: Optional[str] = Form(None),
        db: AsyncSession = Depends(get_db)
):
    """上传皮肤镜影像，异步返回 202 Accepted"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    content = await file.read()

    is_dicom = file.content_type == "application/dicom" or (file.filename and file.filename.lower().endswith(".dcm"))

    if is_dicom:
        source_path = f"uploads/{task_id}_{file.filename}"
        with open(source_path, "wb") as f:
            f.write(content)
        img_status = "processing"  # DICOM 需要后端异步转码管线处理
    else:

        target_path = f"static/images/{image_uid}.png"
        with open(target_path, "wb") as f:
            f.write(content)
        img_status = "ready"  # 普通 Web 图片上传即可用

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
        format="PNG",
        url=f"/ai-static/images/{image_uid}.png",
        status=img_status,  # 根据文件类型动态设置状态
        width=1024,
        height=768,
        created_at=datetime.now(timezone.utc)
    )
    db.add(image)
    await db.commit()

    return UploadIngestResponse(
        task_id=task_id,
        image_uid=image_uid,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        status="accepted",
        message="影像已接收，预处理启动中"
    )


@app.post("/ingest", status_code=202, response_model=UploadIngestResponse, tags=["Image"])
async def ingest_image(req: IngestRequest, db: AsyncSession = Depends(get_db)):
    """异步触发DICOM离线摄取管线，异步返回 202 Accepted"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    dicom_tags = DicomTags(
        PatientID=req.patient_id or "MOCK_PACIENT_001",
        StudyInstanceUID=req.study_uid or f"study_{uuid.uuid4().hex[:8]}",
        PhotometricInterpretation="YBR_FULL_422"
    )

    task = TaskDB(
        task_id=task_id,
        image_uid=image_uid,
        status="queued",
        created_at=datetime.now(timezone.utc)
    )
    db.add(task)

    # 离线摄取场景，文件尚未下载转码，一定是 processing 状态
    image = ImageDB(
        image_uid=image_uid,
        task_id=task_id,
        format="PNG",
        url=f"/ai-static/images/{image_uid}.png",
        status="processing",
        width=1024,
        height=768,
        original_dicom_tags=dicom_tags.model_dump(),
        created_at=datetime.now(timezone.utc)
    )
    db.add(image)
    await db.commit()

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
                print(f"Client disconnected during step {step_data['step']}. Aborting.")
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

        # SSE 流结束后，用独立 Session 保存结果，避免主 Session 被关闭的陷阱
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
            print(f"Error saving inference results to DB: {e}")

        yield f"event: result\ndata: {result_event.model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/features/{image_uid}", response_model=SSEResultEvent, tags=["Diagnosis"])
async def get_historical_features(image_uid: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureDB).where(FeatureDB.image_uid == image_uid))
    feature = result.scalar_one_or_none()

    if not feature:
        return create_error_response(404, "NotFound", "FEATURE_NOT_FOUND", "该影像尚无成功的推理结果")

    return SSEResultEvent(**feature.ai_features)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)