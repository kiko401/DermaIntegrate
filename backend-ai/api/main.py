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
from rag.knowledge_base import RAGKnowledgeBase


# 自定义异常：证据链断裂
class DiagnosisUncertainException(Exception):
    pass


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
    """上传影像：所有文件先落 uploads/，普通图片复制到 static/images/，DICOM转码后存入"""
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

    # 初始化入库所需的变量
    img_status = "processing"
    img_url = None
    img_format = ext.lstrip(".").upper() if ext else "PNG"
    img_width = None
    img_height = None
    dicom_tags_json = None
    error_msg = None

    if is_dicom:
        img_format = "DICOM"
        try:
            # 调用 DicomParser 进行同步转码
            parser = DicomParser(raw_path)

            # 转码并保存到 static/images/
            static_filename = f"{image_uid}.png"
            static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
            img = parser.save_as_png(static_path)

            # 转码成功，更新状态和字段
            img_status = "ready"
            img_url = f"/ai-static/images/{static_filename}"
            img_format = "PNG"  # 转码后格式变为PNG
            img_width = img.width
            img_height = img.height
            dicom_tags_json = parser.metadata_dict

            logger.info(f"DICOM 转码成功: image_uid={image_uid}")

        except DicomParseException as e:
            # 转码失败，记录错误，状态标记为 failed
            img_status = "failed"
            error_msg = str(e)
            logger.error(f"DICOM 转码失败: image_uid={image_uid}, error={e}")
    else:
        # 普通图片：复制到 static/images/，直接可访问
        static_filename = f"{image_uid}{ext}"
        static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
        shutil.copy(raw_path, static_path)

        img_status = "ready"
        img_url = f"/ai-static/images/{static_filename}"
        # 普通图片暂不获取真实宽高，阶段5用PIL读取替换
        img_width = 1024
        img_height = 768

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
        error_message=error_msg,
        width=img_width,
        height=img_height,
        original_dicom_tags=dicom_tags_json,
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
    raw_path = None

    try:
        # 1. 异步下载文件
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(req.image_source)
            response.raise_for_status()  # 检查HTTP状态码
            content = response.content

        # 2. 原始文件落盘 uploads/
        ext = os.path.splitext(req.image_source)[1].lower() or ".dcm"
        raw_filename = f"{image_uid}_ingest{ext}"
        raw_path = os.path.join(settings.UPLOAD_DIR, raw_filename)
        with open(raw_path, "wb") as f:
            f.write(content)

        # 3. 执行 DICOM 转码 (复用 DicomParser 逻辑)
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

            logger.info(f"Ingest DICOM 转码成功: image_uid={image_uid}")

        except DicomParseException as e:
            img_status = "failed"
            error_msg = str(e)
            logger.error(f"Ingest DICOM 转码失败: image_uid={image_uid}, error={e}")

    except httpx.HTTPError as e:
        # 下载失败处理
        img_status = "failed"
        error_msg = f"文件下载失败: {str(e)}"
        logger.error(f"Ingest 下载失败: source={req.image_source}, error={e}")

    # 4. 入库
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
        width=img_width if img_width else 1024,  # 兜底默认值
        height=img_height if img_height else 768,
        original_dicom_tags=dicom_tags_json,
        created_at=datetime.now(timezone.utc)
    )
    db.add(image)
    await db.commit()

    logger.info(f"Ingest task created: task_id={task_id}, source={req.image_source}, status={img_status}")

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

    # 获取图像信息
    img_result = await db.execute(select(ImageDB).where(ImageDB.image_uid == image_uid))
    img_record = img_result.scalar_one_or_none()

    if not img_record or not img_record.url:
        return create_error_response(400, "Bad Request", "IMAGE_NOT_READY", "影像尚未准备就绪")

    # 构建绝对路径 (从 url 转换)
    # img_record.url 格式如: /ai-static/images/xxx.png
    # 需要转换为 static/images/xxx.png
    relative_path = img_record.url.replace("/ai-static/", "")
    original_image_path = os.path.join(settings.STATIC_DIR, relative_path)

    async def event_generator():
        try:
            # Step 1: 准备阶段
            yield f"event: step\ndata: {json.dumps({'step': 1, 'stage': 'image_preprocessing', 'msg': '影像预处理完成', 'progress': 0.2})}\n\n"
            await asyncio.sleep(0.2)

            # Step 2: 视觉依据 - 调用 LesionExtractor
            evidence_filename = f"{image_uid}_evidence.png"
            evidence_path = os.path.join(settings.STATIC_DIR, "heatmaps", evidence_filename)
            lesion_extractor.generate(original_image_path, evidence_path)
            evidence_url = f"/ai-static/heatmaps/{evidence_filename}"

            yield f"event: step\ndata: {json.dumps({'step': 2, 'stage': 'gradcam', 'msg': '显著性区域提取完成', 'progress': 0.4, 'data': {'image_url': evidence_url}})}\n\n"
            await asyncio.sleep(0.2)

            # Step 3: 形态描述 - 调用 VLMAgent
            morphology_dict = vlm_agent.analyze(original_image_path, evidence_path)

            yield f"event: step\ndata: {json.dumps({'step': 3, 'stage': 'vlm_analysis', 'msg': '形态学描述生成完成', 'progress': 0.6, 'data': morphology_dict})}\n\n"
            await asyncio.sleep(0.2)

            # Step 4: 文献检索 - 调用 RAGKnowledgeBase
            # 将形态学描述拼接为查询文本
            query_text = " ".join([f"{k}:{v}" for k, v in morphology_dict.items()])
            rag_kb = request.app.state.rag_kb
            rag_results = rag_kb.retrieve(query_text, top_k=2)

            yield f"event: step\ndata: {json.dumps({'step': 4, 'stage': 'rag_retrieval', 'msg': '检索相关医学文献完成', 'progress': 0.8, 'data': {'citations': rag_results}})}\n\n"
            await asyncio.sleep(0.2)

            # Step 5: 证据整合 - 校验逻辑
            # 如果关键组件为空，抛出异常
            if not morphology_dict or not rag_results:
                raise DiagnosisUncertainException("证据链断裂：缺乏足够的形态学或文献依据")

            # 组装最终结果
            result_event = SSEResultEvent(
                task_id=task_id,
                image_uid=image_uid,
                visual_evidence=VisualEvidence(
                    heatmap_url=evidence_url,
                    image_url=img_record.url,
                    lesion_region=[120, 80, 300, 250]  # 占位符区域
                ),
                morphology=Morphology(**morphology_dict),
                rag_citations=[RagCitation(title=f"文献片段 {i + 1}", source="本地知识库", relevance=0.9, excerpt=txt)
                               for i, txt in enumerate(rag_results)],
                confidence=0.85,  # 置信度目前写死
                disclaimer="本结果仅为AI辅助证据，最终诊断裁量权归临床医生所有。",
                completed_at=datetime.now(timezone.utc).isoformat()
            )

            # 保存特征到数据库
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

        except DiagnosisUncertainException as e:
            # 证据链断裂异常处理
            error_data = {"error_code": "EVIDENCE_CHAIN_BROKEN", "message": str(e)}
            yield f"event: error\ndata: {json.dumps(error_data)}\n\n"

        except Exception as e:
            logger.error(f"Error during SSE stream: {e}")
            error_data = {"error_code": "INTERNAL_ERROR", "message": "推理管线内部错误"}
            yield f"event: error\ndata: {json.dumps(error_data)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/features/{image_uid}", response_model=SSEResultEvent, tags=["Diagnosis"])
async def get_historical_features(image_uid: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureDB).where(FeatureDB.image_uid == image_uid))
    feature = result.scalar_one_or_none()

    if not feature:
        return create_error_response(404, "NotFound", "FEATURE_NOT_FOUND", "该影像尚无成功的推理结果")

    return SSEResultEvent(**feature.ai_features)