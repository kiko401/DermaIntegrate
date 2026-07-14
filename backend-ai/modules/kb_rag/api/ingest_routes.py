import asyncio
import json
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from ..schemas import IngestCallback
from ..ingest.vector_store import init_qdrant_collection, delete_kb_index, delete_document_index
from ..ingest.ingestion import process_and_ingest_document, reindex_document

logger = logging.getLogger(__name__)
router = APIRouter()


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
        stream: bool = Query(False)  # 通过 query 参数 ?stream=true 开启 SSE
):
    """文档入库，支持异步回调或 SSE 流式返回进度"""
    content = await file.read()
    filename = file.filename

    if stream:
        # 流式模式：创建队列，启动后台任务，返回 SSE 流
        progress_queue = asyncio.Queue()
        asyncio.create_task(
            process_and_ingest_document(
                content, filename, task_id, task_code, kb_id, doc_id, doc_version_id,
                chunk_size, chunk_overlap, progress_queue=progress_queue
            )
        )
        return StreamingResponse(event_generator(progress_queue), media_type="text/event-stream")

    # 默认模式：纯异步静默处理，返回 202
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
        stream: bool = Query(False)  # 通过 query 参数 ?stream=true 开启 SSE
):
    """文档重索引：删除旧向量，等待新 ingest"""
    content = await file.read()
    filename = file.filename

    if stream:
        # 流式模式
        progress_queue = asyncio.Queue()
        asyncio.create_task(
            reindex_document(
                content, filename, task_id, task_code, kb_id, doc_id, doc_version_id,
                chunk_size, chunk_overlap, progress_queue=progress_queue
            )
        )
        return StreamingResponse(event_generator(progress_queue), media_type="text/event-stream")

    # 默认模式
    asyncio.create_task(
        reindex_document(
            content, filename, task_id, task_code, kb_id, doc_id, doc_version_id, chunk_size, chunk_overlap
        )
    )
    return {"task_id": task_id, "status": "accepted"}


@router.post("/delete-index", status_code=status.HTTP_200_OK)
async def delete_document_index_endpoint(doc_id: int = Form(...)):
    """删除指定 doc_id 的所有向量"""
    try:
        delete_document_index(doc_id)
        return {"status": "succeeded", "doc_id": doc_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))