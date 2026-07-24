"""任务路由：上传、摄取、影像元数据查询。"""

import os
import shutil
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from PIL import Image

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from config import settings
from models.database import get_db, ImageResource as ImageDB, AITask as TaskDB
from preprocessing.dicom_parser import DicomParser, DicomParseException

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Task"])


class UploadIngestResponse(BaseModel):
    task_id: str
    status: str


class IngestRequest(BaseModel):
    image_source: str
    patient_id: Optional[str] = None
    study_uid: Optional[str] = None


class DicomTags(BaseModel):
    """DICOM 元数据字段，允许任意 key（_extra='allow'）。"""
    model_config = {"extra": "allow"}

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


class ErrorResponse(BaseModel):
    error: str
    error_code: str
    message: str


def _create_error_response(status_code: int, error: str, error_code: str, message: str) -> dict:
    return {"error": error, "error_code": error_code, "message": message}


@router.post("/upload", status_code=202, response_model=UploadIngestResponse)
async def upload_data(
        file: Optional[UploadFile] = File(None),
        clinical_text: Optional[str] = Form(None),
        clinical_json: Optional[str] = Form(None),
        lab_json: Optional[str] = Form(None),
        db: AsyncSession = Depends(get_db)
) -> UploadIngestResponse:
    """
    多模态数据上传接口。
    支持图片（含 DICOM）、病历文本、结构化 JSON 病历、化验 JSON。
    返回 task_id 用于后续流式查询。
    """
    if not file and not clinical_text and not clinical_json and not lab_json:
        raise HTTPException(
            status_code=400,
            detail="至少需要提供一项模态数据 (图片、病历或化验)"
        )

    task_id = str(uuid.uuid4())
    image_uid: Optional[str] = None

    if file:
        image_uid = f"img_{uuid.uuid4().hex[:16]}"
        content = await file.read()
        ext = os.path.splitext(file.filename or "")[1].lower()
        if not ext:
            ext = ".png"

        raw_filename = f"{image_uid}_{file.filename or 'unknown'}"
        raw_path = os.path.join(settings.UPLOAD_DIR, raw_filename)
        with open(raw_path, "wb") as f:
            f.write(content)

        is_dicom = file.content_type == "application/dicom" or ext == ".dcm"
        image_parsing_failed = False

        if is_dicom:
            try:
                parser = DicomParser(raw_path)
                static_filename = f"{image_uid}.png"
                static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
                img = parser.save_as_png(static_path)

                image = ImageDB(
                    image_uid=image_uid, task_id=task_id, format="PNG",
                    url=f"/ai-static/images/{static_filename}", status="ready",
                    width=img.width, height=img.height,
                    original_dicom_tags=parser.metadata_dict,
                    created_at=datetime.now(timezone.utc)
                )
                db.add(image)
            except DicomParseException as e:
                image = ImageDB(
                    image_uid=image_uid, task_id=task_id, format="DICOM",
                    status="failed", error_message=str(e),
                    created_at=datetime.now(timezone.utc)
                )
                db.add(image)
                image_parsing_failed = True
        else:
            static_filename = f"{image_uid}{ext}"
            static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
            shutil.copy(raw_path, static_path)

            with Image.open(raw_path) as img:
                img_width, img_height = img.size
            image = ImageDB(
                image_uid=image_uid, task_id=task_id, format=ext.lstrip(".").upper(),
                url=f"/ai-static/images/{static_filename}", status="ready",
                width=img_width, height=img_height,
                created_at=datetime.now(timezone.utc)
            )
            db.add(image)

    task = TaskDB(
        task_id=task_id, image_uid=image_uid,
        status="failed" if image_parsing_failed else "queued",
        clinical_text=clinical_text, clinical_json=clinical_json, lab_json=lab_json,
        created_at=datetime.now(timezone.utc)
    )
    db.add(task)
    await db.commit()

    logger.info(
        f"Upload accepted: task_id={task_id}, has_image={bool(file)}, "
        f"has_clinical={bool(clinical_json or clinical_text)}, has_lab={bool(lab_json)}, "
        f"image_parsing_failed={image_parsing_failed}"
    )

    return UploadIngestResponse(
        task_id=task_id,
        status="accepted" if not image_parsing_failed else "failed_image_parsing"
    )


def _validate_url(url: str) -> None:
    """校验URL仅限http/https且禁止访问内网段"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="仅支持 http/https 协议的URL")
    # 禁止访问内网IP段
    host = parsed.hostname or ""
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith("192.168.") or host.startswith("10.") or host.startswith("172."):
        # 更精确的内网段检测（10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16）
        if host == "localhost" or host == "127.0.0.1" or host == "0.0.0.0":
            raise HTTPException(status_code=400, detail="禁止访问本地回环地址")
        if host.startswith("192.168.") or host.startswith("10.") or (host.startswith("172.") and 16 <= int(host.split(".")[1]) <= 31):
            raise HTTPException(status_code=400, detail="禁止访问内网地址")


@router.post("/ingest", status_code=202, response_model=UploadIngestResponse)
async def ingest_image(req: IngestRequest, db: AsyncSession = Depends(get_db)) -> UploadIngestResponse:
    """通过 URL 摄取 DICOM/图像数据。"""
    task_id = str(uuid.uuid4())
    image_uid = f"img_{uuid.uuid4().hex[:16]}"

    # H-05: SSRF防护 - URL校验
    _validate_url(req.image_source)

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

        parser = DicomParser(raw_path)
        static_filename = f"{image_uid}.png"
        static_path = os.path.join(settings.STATIC_DIR, "images", static_filename)
        img = parser.save_as_png(static_path)

        image = ImageDB(
            image_uid=image_uid, task_id=task_id, format="PNG",
            url=f"/ai-static/images/{static_filename}", status="ready",
            width=img.width, height=img.height,
            original_dicom_tags=parser.metadata_dict,
            created_at=datetime.now(timezone.utc)
        )
        db.add(image)
        task_status = "queued"

    except httpx.HTTPError as e:
        image = ImageDB(
            image_uid=image_uid, task_id=task_id, format="ERROR",
            status="failed", error_message=f"文件下载失败: {str(e)}",
            created_at=datetime.now(timezone.utc)
        )
        db.add(image)
        task_status = "failed"
    except DicomParseException as e:
        image = ImageDB(
            image_uid=image_uid, task_id=task_id, format="DICOM",
            status="failed", error_message=str(e),
            created_at=datetime.now(timezone.utc)
        )
        db.add(image)
        task_status = "failed"

    # H-04: DicomParseException后不再入队zombie任务
    task = TaskDB(
        task_id=task_id, image_uid=image_uid, status=task_status,
        created_at=datetime.now(timezone.utc)
    )
    db.add(task)
    await db.commit()

    return UploadIngestResponse(
        task_id=task_id,
        status="accepted" if task_status == "queued" else "failed_image_parsing"
    )


@router.get("/images/{image_uid}", response_model=ImageMetadataResponse)
async def get_image(image_uid: str, db: AsyncSession = Depends(get_db)) -> ImageMetadataResponse:
    """
    查询单张图片的元数据信息。

    image_uid 路径参数支持两种格式：
    - 带前缀（数据库存储格式）：img_3ed673b06b8c4683
    - 不带前缀（文档规定格式）：3ed673b06b8c4683
    自动兼容两种传参方式。
    """
    # 自动兼容带/不带 img_ 前缀的两种传参方式
    query_uid = image_uid if image_uid.startswith("img_") else f"img_{image_uid}"
    result = await db.execute(select(ImageDB).where(ImageDB.image_uid == query_uid))
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(status_code=404, detail="影像 UID 不存在")

    dicom_tags: Optional[DicomTags] = None
    if image.original_dicom_tags:
        dicom_tags = DicomTags(**image.original_dicom_tags)

    return ImageMetadataResponse(
        image_uid=image.image_uid, format=image.format, url=image.url, status=image.status,
        error_message=image.error_message, width=image.width, height=image.height,
        color_space=image.color_space or "sRGB", original_dicom_tags=dicom_tags
    )
