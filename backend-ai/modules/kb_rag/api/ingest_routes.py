import asyncio
import json
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from ..schemas import IngestCallback, ReindexTextRequest
from ..ingest.vector_store import init_qdrant_collection, delete_kb_index, delete_document_index, delete_kb_index_async, delete_document_index_async, get_qdrant_client, COLLECTION_NAME
from ..ingest.ingestion import reindex_text
from ..ingest.ingestion import process_and_ingest_document, reindex_document

logger = logging.getLogger(__name__)
router = APIRouter()


class DeleteIndexRequest(BaseModel):
    """删除向量索引的请求体"""
    kb_id: int
    doc_id: Optional[int] = None
    doc_version_id: Optional[int] = None
    delete_all: bool = False


async def event_generator(queue: asyncio.Queue):
    """SSE 事件生成器，从 asyncio.Queue 中读取事件并推送给客户端"""
    try:
        while True:
            event = await queue.get()
            if event is None:  # 收到结束信号
                break

            event_type = event.get("event", "message")
            data = event.get("data", {})

            yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

            # 如果是 done 或 error 事件，推送后结束流
            if event_type in ["done", "error"]:
                break
    except Exception as e:
        logger.error(f"SSE stream error: {e}")
        yield f"event: error\ndata: {json.dumps({'code': 'STREAM_ERROR', 'message': str(e)})}\n\n"


@router.post("/index/create", status_code=status.HTTP_200_OK)
async def create_index_endpoint(kb_id: int = Form(...)):
    """为指定 kb_id 创建 Qdrant collection 空间 (实际共享集合，此处为语义兼容)"""
    try:
        init_qdrant_collection()
        return {"status": "succeeded", "kb_id": kb_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/index/delete", status_code=status.HTTP_200_OK)
async def delete_index_endpoint(kb_id: int = Form(...)):
    """删除指定 kb_id 下的所有向量"""
    try:
        delete_kb_index(kb_id)
        return {"status": "succeeded", "kb_id": kb_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def ingest_document_endpoint(
        file: UploadFile = File(...),
        task_id: int = Form(...),
        task_code: str = Form(...),
        kb_id: int = Form(...),
        doc_id: int = Form(...),
        doc_version_id: int = Form(...),
        chunk_size: int = Form(800),
        chunk_overlap: int = Form(120),
        embedding_model: str = Form("BAAI/bge-small-zh-v1.5"),
):
    """
    文档入库主接口（纯异步）。

    进度推送由应用域通过 GET /api/rag/tasks/:taskId/stream 以 SSE 方式完成，
    AI 域不直接对前端 SSE。回调协议见 §5.2.3。
    """
    content = await file.read()
    filename = file.filename

    asyncio.create_task(
        process_and_ingest_document(
            content, filename, task_id, task_code, kb_id, doc_id, doc_version_id, chunk_size, chunk_overlap
        )
    )
    return {"task_id": task_id, "status": "accepted"}


@router.post("/reindex")
async def reindex_document_endpoint(
        file: UploadFile = File(...),
        task_id: int = Form(...),
        task_code: str = Form(...),
        kb_id: int = Form(...),
        doc_id: int = Form(...),
        doc_version_id: int = Form(...),
        chunk_size: int = Form(800),
        chunk_overlap: int = Form(120),
        embedding_model: str = Form("BAAI/bge-small-zh-v1.5"),
):
    """
    文档重索引：先删除旧 chunk，再执行重新入库。

    与 /rag/ingest 的区别在于：reindex 会调用 delete-index 清除该 doc_id 下的所有旧向量，
    保证新旧索引的一致性（ingest 不清除旧向量，适合增量追加）。
    回调协议与 ingest 相同。
    """
    content = await file.read()
    filename = file.filename

    asyncio.create_task(
        reindex_document(
            content, filename, task_id, task_code, kb_id, doc_id, doc_version_id, chunk_size, chunk_overlap
        )
    )
    return {"task_id": task_id, "status": "accepted"}


@router.post("/reindex-text")
async def reindex_text_endpoint(req: ReindexTextRequest):
    """
    纯文本重索引（文档版本回滚专用）。

    应用域传入历史版本文本，AI 域先删旧版向量，再入新版向量。
    跳过文件解析，直接切分+向量化+写入。
    """
    asyncio.create_task(
        reindex_text(
            text=req.text,
            task_id=0,
            task_code="reindex-text",
            kb_id=req.kb_id,
            doc_id=req.doc_id,
            doc_version_id=req.doc_version_id,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
    )
    return {"status": "accepted", "doc_id": req.doc_id, "doc_version_id": req.doc_version_id}


@router.post("/delete-index", status_code=status.HTTP_200_OK)
async def delete_document_index_endpoint(req: DeleteIndexRequest):
    """删除指定文档或知识库的向量索引"""
    try:
        if req.delete_all:
            await delete_kb_index_async(req.kb_id)
            return {"status": "deleted", "deleted_chunk_count": -1}
        elif req.doc_id is not None:
            from qdrant_client.http import models
            conditions = [models.FieldCondition(key="doc_id", match=models.MatchValue(value=req.doc_id))]
            if req.doc_version_id is not None:
                conditions.append(
                    models.FieldCondition(key="doc_version_id", match=models.MatchValue(value=req.doc_version_id))
                )
            # 包装 Qdrant 同步调用，避免阻塞事件循环
            async def _delete():
                client = get_qdrant_client()
                client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(must=conditions)
                    )
                )
            await asyncio.to_thread(_delete)
            return {"status": "deleted", "deleted_chunk_count": -1}
        else:
            raise HTTPException(status_code=400, detail="doc_id or delete_all=true is required")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))