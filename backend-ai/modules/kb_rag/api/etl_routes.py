import logging
from datetime import datetime
from typing import Optional, List, Dict

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status, Query
from fastapi.responses import StreamingResponse

from shared.config import APP_CONVERSATION_CONNECT_TIMEOUT, APP_CONVERSATION_READ_TIMEOUT, APP_BASE_URL, X_INTERNAL_SECRET
from ..schemas import ETLJobStatus, ETLRunRequest, FeedbackExportRequest, ETLClinicalRequest
from ..etl.etl_service import (
    extract_and_ingest,
    get_etl_job_status,
    get_etl_jobs_list,
    submit_etl_job,
    export_feedback_by_filters,
    clinical_etl_and_ingest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/etl/run", status_code=status.HTTP_202_ACCEPTED)
async def run_etl_endpoint(req: ETLRunRequest):
    """触发 ETL 任务：抽取、清洗、行转文本、双重索引入库"""
    try:
        job_id, job_status = await submit_etl_job(req)
        return {"job_id": job_id, "status": job_status.status}
    except Exception as e:
        logger.error(f"ETL job submission failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/etl/run-file", status_code=status.HTTP_202_ACCEPTED)
async def run_etl_file_endpoint(
        file: UploadFile = File(...),
        kb_id: int = Form(...),
        doc_id: int = Form(...),
        doc_version_id: int = Form(...),
        job_name: Optional[str] = Form(None),
        chunk_size: int = Form(800),
        chunk_overlap: int = Form(120),
):
    """文件上传方式的 ETL 触发（兼容原接口）"""
    # 文件大小限制，默认 50MB
    MAX_FILE_SIZE = 50 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过限制（最大 {MAX_FILE_SIZE // (1024*1024)}MB）"
        )
    filename = file.filename
    job_id = f"etl_job_{doc_id}_{doc_version_id}"
    job_status = await extract_and_ingest(content, filename, kb_id, doc_id, doc_version_id, job_id, job_name)
    return {"job_id": job_id, "status": job_status.status}


@router.get("/etl/jobs")
async def list_etl_jobs_endpoint(
        status: Optional[str] = Query(None, description="按状态筛选：pending/running/succeeded/failed"),
        limit: int = Query(100, ge=1, le=1000, description="返回数量限制"),
):
    """查询 ETL 任务列表"""
    jobs = get_etl_jobs_list(status=status, limit=limit)
    return {"jobs": jobs}


@router.get("/etl/jobs/{job_id}", response_model=ETLJobStatus)
async def get_etl_job_endpoint(job_id: str):
    """查询 ETL 任务状态"""
    status_res = await get_etl_job_status(job_id)
    if not status_res:
        raise HTTPException(status_code=404, detail="Job not found")
    return status_res


@router.post("/etl/clinical", status_code=status.HTTP_202_ACCEPTED)
async def clinical_etl_endpoint(req: ETLClinicalRequest):
    """
    临床病例 ETL 入库接口（供应用域调用）。

    应用域传入脱敏后的患者上下文和病例文本，AI 域完成：
    1. 文本构建（患者概要 + 病例详情）
    2. 清洗切分
    3. Dense 向量生成
    4. Qdrant 索引入库

    PHI 脱敏须在调用前由应用域完成，本接口仅做二次检测（发现 PHI 关键词时告警不阻断）。
    """
    try:
        chunk_count, status = await clinical_etl_and_ingest(
            kb_id=req.kb_id,
            case_type=req.case_type,
            patient_context=req.patient_context.model_dump(),
            case_text=req.case_text,
            doc_version_id=req.doc_version_id,
            doctor_id=req.doctor_id,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
        return {
            "status": status,
            "kb_id": req.kb_id,
            "case_type": req.case_type,
            "chunk_count": chunk_count,
        }
    except Exception as e:
        logger.error(f"Clinical ETL failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback/export")
async def export_feedback_endpoint(req: FeedbackExportRequest):
    """
    导出反馈数据为 JSONL 格式。
    AI 域按传入的日期范围、kb_ids、置信度等条件筛选对话记录并导出。

    数据来源：先尝试从应用域拉取对话记录，再进行过滤转换。
    """
    try:
        # 尝试从应用域获取对话记录
        conversation_data = await _fetch_conversation_data_from_app_domain(req)

        if not conversation_data:
            logger.warning("No conversation data retrieved from app domain, returning empty export")
            import io
            filename = f"feedback_export_{datetime.now().strftime('%Y%m%d%H%M%S')}.jsonl"
            return StreamingResponse(
                io.StringIO(""),
                media_type="application/jsonl",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        jsonl_str, filename = await export_feedback_by_filters(
            start_date=req.start_date,
            end_date=req.end_date,
            kb_ids=req.kb_ids,
            min_confidence=req.min_confidence,
            conversation_data=conversation_data,
        )
        headers = {"Content-Disposition": f"attachment; filename={filename}"}
        return StreamingResponse(io.StringIO(jsonl_str), media_type="application/jsonl", headers=headers)
    except Exception as e:
        logger.error(f"Failed to export feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _fetch_conversation_data_from_app_domain(req: FeedbackExportRequest) -> Optional[List[Dict]]:
    """
    从应用域拉取对话记录数据。
    需要应用域提供 /api/rag/conversations 接口。
    """
    app_base_url = APP_BASE_URL
    secret = X_INTERNAL_SECRET

    if not app_base_url or not secret:
        logger.warning("APP_BASE_URL or X_INTERNAL_SECRET not configured, cannot fetch conversation data")
        return None

    # 构造查询参数
    params = {}
    if req.start_date:
        params["start_date"] = req.start_date
    if req.end_date:
        params["end_date"] = req.end_date
    if req.kb_ids:
        params["kb_ids"] = ",".join(map(str, req.kb_ids))
    if req.min_confidence is not None:
        params["min_confidence"] = str(req.min_confidence)

    callback_url = f"{app_base_url}/api/rag/conversations"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=APP_CONVERSATION_CONNECT_TIMEOUT, read=APP_CONVERSATION_READ_TIMEOUT)) as client:
            response = await client.get(
                callback_url,
                params=params,
                headers={
                    "X-Internal-Token": secret,
                    "Content-Type": "application/json"
                }
            )
            if response.status_code == 200:
                data = response.json()
                conversations = data.get("conversations", [])
                logger.info(f"Fetched {len(conversations)} conversations from app domain")
                return conversations
            else:
                logger.error(f"Failed to fetch conversations: HTTP {response.status_code} - {response.text}")
                return None
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching conversations from app domain")
        return None
    except Exception as e:
        logger.error(f"Error fetching conversations from app domain: {e}")
        return None
