from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
from ..schemas import ETLJobStatus
from ..etl.etl_service import extract_and_ingest, get_etl_job_status
from ..etl.feedback_exporter import export_to_jsonl
import io
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# 定义微调数据导出的请求体模型
class FeedbackExportPayload(BaseModel):
    conversations: List[Dict[str, Any]] = []

    class Config:
        schema_extra = {
            "example": [
                {
                    "conversation_id": 101,
                    "question": "Breslow厚度意味着什么？",
                    "answer": "Breslow厚度是评估黑色素瘤侵袭深度的指标...",
                    "feedback": "positive"
                }
            ]
        }


@router.post("/etl/run", status_code=status.HTTP_202_ACCEPTED)
async def run_etl_endpoint(
        file: UploadFile = File(...),
        kb_id: int = Form(...),
        doc_id: int = Form(...),
        doc_version_id: int = Form(...)
):
    """触发 ETL 任务：抽取、清洗、行转文本、双重索引入库"""
    content = await file.read()
    filename = file.filename

    import asyncio
    job_id = f"etl_job_{doc_id}_{doc_version_id}"
    asyncio.create_task(extract_and_ingest(content, filename, kb_id, doc_id, doc_version_id, job_id))

    return {"job_id": job_id, "status": "accepted"}


@router.get("/etl/jobs/{job_id}", response_model=ETLJobStatus)
async def get_etl_job_endpoint(job_id: str):
    """查询 ETL 任务状态"""
    status_res = await get_etl_job_status(job_id)
    if not status_res:
        raise HTTPException(status_code=404, detail="Job not found")
    return status_res


@router.post("/feedback/export")
async def export_feedback_endpoint(req: FeedbackExportPayload):
    """
    导出微调数据为 JSONL (接收应用域传入的真实问答数据)。
    AI 域不直连应用域 DB，由应用域拉取历史问答记录后调用此接口进行格式化转换。
    """
    try:
        jsonl_str = await export_to_jsonl(req.conversations)
        headers = {
            "Content-Disposition": "attachment; filename=feedback_export.jsonl"
        }
        return StreamingResponse(io.StringIO(jsonl_str), media_type="application/jsonl", headers=headers)
    except Exception as e:
        logger.error(f"Failed to export feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))