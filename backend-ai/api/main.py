import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict


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
    # 严禁 DeepSeek-VL2 夹带契约外字段(如偷偷输出 diagnosis)，违例直接 ValidationError 打回
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

app = FastAPI(
    title="DermaIntegrate AI Backend",
    description="智能推理域 API，严格遵循 api-contract.yaml"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ai-static", StaticFiles(directory="static"), name="static")

# Mock 内存数据库
tasks_db = {}
images_db = {}
features_db = {}


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
async def health():
    return {"service": "backend-ai", "status": "UP"}


@app.post("/upload", status_code=202, response_model=UploadIngestResponse, tags=["Image"])
async def upload_image(
        file: UploadFile = File(...),
        patient_id: Optional[str] = Form(None),
        study_uid: Optional[str] = Form(None)
):
    """上传皮肤镜影像，异步返回 202 Accepted"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    # 实际场景下会丢给后台线程/消息队列处理，此处仅Mock记录
    content = await file.read()
    file_path = f"uploads/{task_id}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    tasks_db[task_id] = {"task_id": task_id, "image_uid": image_uid}

    images_db[image_uid] = ImageMetadataResponse(
        image_uid=image_uid,
        url=f"/ai-static/images/{image_uid}.png",
        status="processing",
        width=1024,
        height=768
    )

    return UploadIngestResponse(
        task_id=task_id,
        image_uid=image_uid,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        status="accepted",
        message="影像已接收，预处理启动中"
    )


@app.post("/ingest", status_code=202, response_model=UploadIngestResponse, tags=["Image"])
async def ingest_image(req: IngestRequest):
    """异步触发DICOM离线摄取管线，异步返回 202 Accepted"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    tasks_db[task_id] = {"task_id": task_id, "image_uid": image_uid}

    # Mock DICOM解析提取Tag
    dicom_tags = DicomTags(
        PatientID=req.patient_id or "MOCK_PACIENT_001",
        StudyInstanceUID=req.study_uid or f"study_{uuid.uuid4().hex[:8]}",
        PhotometricInterpretation="YBR_FULL_422"
    )

    images_db[image_uid] = ImageMetadataResponse(
        image_uid=image_uid,
        url=f"/ai-static/images/{image_uid}.png",
        status="processing",
        width=1024,
        height=768,
        original_dicom_tags=dicom_tags
    )

    return UploadIngestResponse(
        task_id=task_id,
        image_uid=image_uid,
        filename=req.image_source.split("/")[-1],
        content_type="application/dicom",
        status="accepted",
        message="摄取任务已接受，DICOM解析启动中"
    )


@app.get("/images/{image_uid}", response_model=ImageMetadataResponse, tags=["Image"])
async def get_image(image_uid: str):
    if image_uid not in images_db:
        return create_error_response(404, "NotFound", "IMAGE_NOT_FOUND", "影像 UID 不存在")
    return images_db[image_uid]


@app.get("/stream/{task_id}", tags=["Diagnosis"])
async def stream_diagnosis(request: Request, task_id: str):
    if task_id not in tasks_db:
        return create_error_response(404, "NotFound", "TASK_NOT_FOUND", "task_id 不存在")

    image_uid = tasks_db[task_id].get("image_uid", "unknown")

    async def event_generator():
        steps = [
            {"step": 1, "stage": "image_preprocessing", "msg": "影像预处理完成", "progress": 0.2},
            {"step": 2, "stage": "gradcam", "msg": "显著性区域提取完成", "progress": 0.4,
             "data": {"image_url": f"/ai-static/images/{image_uid}.png"}},
            {"step": 3, "stage": "vlm_analysis", "msg": "形态学描述生成中...", "progress": 0.6},
            {"step": 4, "stage": "rag_retrieval", "msg": "检索相关医学文献...", "progress": 0.8},
            {"step": 5, "stage": "evidence_integration", "msg": "证据链组装完成", "progress": 1.0},
        ]

        # 模拟异步推理步级生成
        for step_data in steps:
            if await request.is_disconnected():
                print(f"Client disconnected during step {step_data['step']}. Aborting.")
                return  # 终止生成器，释放资源

            yield f"event: step\ndata: {json.dumps(step_data)}\n\n"
            await asyncio.sleep(0.8)  # 模拟推理耗时

            # 兑现心跳契约
            hb_data = {"ping": True}
            yield f"event: heartbeat\ndata: {json.dumps(hb_data)}\n\n"

        # 推理完成，更新影像状态为 ready
        if image_uid in images_db:
            images_db[image_uid].status = "ready"

        # 构建符合 SSEResultEvent 的完整证据链
        result = SSEResultEvent(
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

        # 缓存历史特征
        features_db[image_uid] = result

        # 发送成功终结事件
        yield f"event: result\ndata: {result.model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/features/{image_uid}", response_model=SSEResultEvent, tags=["Diagnosis"])
async def get_historical_features(image_uid: str):
    if image_uid not in features_db:
        return create_error_response(404, "NotFound", "FEATURE_NOT_FOUND", "该影像尚无成功的推理结果")
    return features_db[image_uid]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)