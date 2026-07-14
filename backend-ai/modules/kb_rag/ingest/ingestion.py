import asyncio
import logging
from typing import List, Dict, Optional
from .parsers import extract_text_from_file
from .splitters import split_text
from .embeddings import generate_embeddings
from .vector_store import upsert_vectors, delete_document_index
from .task_manager import send_task_callback

logger = logging.getLogger(__name__)


async def process_and_ingest_document(
        content: bytes,
        filename: str,
        task_id: int,
        task_code: str,
        kb_id: int,
        doc_id: int,
        doc_version_id: int,
        chunk_size: int,
        chunk_overlap: int,
        progress_queue: Optional[asyncio.Queue] = None
):
    """文档入库主流程：解析 -> 切分 -> 向量化 -> 写入向量数据库 -> 回调应用域。"""
    chunk_count = 0
    error_msg = None

    async def push_event(event: str, data: dict):
        if progress_queue:
            await progress_queue.put({"event": event, "data": data})
            await asyncio.sleep(0)

    try:
        await push_event("progress",
                         {"task_id": task_id, "stage": "parsing", "progress": 25, "message": "正在解析文档"})
        text = extract_text_from_file(content, filename)
        if not text:
            raise ValueError("解析出的文本为空")

        await push_event("progress",
                         {"task_id": task_id, "stage": "splitting", "progress": 50, "message": "正在切分文本"})
        chunks = split_text(text, chunk_size, chunk_overlap, doc_id, doc_version_id)
        if not chunks:
            raise ValueError("切分后的 chunk 为空")

        await push_event("progress",
                         {"task_id": task_id, "stage": "embedding", "progress": 75, "message": "正在生成向量"})
        texts_to_embed = [c["text"] for c in chunks]
        vectors = generate_embeddings(texts_to_embed)

        payloads = [{
            "kb_id": kb_id,
            "doc_id": doc_id,
            "doc_version_id": doc_version_id,
            "chunk_id": c["chunk_id"],
            "text": c["text"]
        } for c in chunks]

        await push_event("progress",
                         {"task_id": task_id, "stage": "indexing", "progress": 100, "message": "正在写入向量数据库"})
        upsert_vectors(vectors, payloads)
        chunk_count = len(vectors)

        await push_event("done", {"task_id": task_id, "status": "succeeded", "chunk_count": chunk_count})

    except Exception as e:
        logger.error(f"Ingest failed for task {task_id}: {e}", exc_info=True)
        error_msg = str(e)
        await push_event("error", {"task_id": task_id, "code": "INGEST_FAILED", "message": error_msg})

    finally:
        await send_task_callback(task_id, task_code, chunk_count, error_msg)
        if progress_queue:
            await progress_queue.put(None)


async def reindex_document(
        content: bytes,
        filename: str,
        task_id: int,
        task_code: str,
        kb_id: int,
        doc_id: int,
        doc_version_id: int,
        chunk_size: int,
        chunk_overlap: int,
        progress_queue: Optional[asyncio.Queue] = None
):
    """重建索引：先删旧索引，再重新入库。"""
    try:
        delete_document_index(doc_id)
        logger.info(f"Old index deleted for doc_id={doc_id}, proceeding with re-ingest.")
    except Exception as e:
        logger.warning(f"Failed to delete old index for doc_id={doc_id}: {e}")

    await process_and_ingest_document(
        content, filename, task_id, task_code, kb_id, doc_id, doc_version_id, chunk_size, chunk_overlap, progress_queue
    )
