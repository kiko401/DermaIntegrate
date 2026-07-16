"""
文档入库主流程

解析 -> 切分 -> BM25拟合 -> 向量化(同步dense+sparse) -> 写入Qdrant -> 回调应用域
"""
import asyncio
import logging
from typing import List, Dict, Optional
from .parsers import extract_text_from_file
from .splitters import split_text
from .embeddings import generate_embeddings
from .vector_store import upsert_vectors_async, delete_document_index_async
from .bm25 import fit_bm25_on_collection, generate_sparse_vectors_batch
from .vector_store import COLLECTION_NAME
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
    """
    文档入库主流程（混合向量版）：
    解析 -> 切分 -> BM25拟合 -> Dense向量 + Sparse向量生成 -> 写入Qdrant -> 回调应用域
    """
    chunk_count = 0
    error_msg = None

    async def push_event(event: str, data: dict):
        if progress_queue:
            await progress_queue.put({"event": event, "data": data})
            await asyncio.sleep(0)

    try:
        await push_event("progress",
                         {"task_id": task_id, "stage": "parsing", "progress": 20, "message": "正在解析文档"})
        text = extract_text_from_file(content, filename)
        if not text:
            raise ValueError("解析出的文本为空")

        await push_event("progress",
                         {"task_id": task_id, "stage": "splitting", "progress": 35, "message": "正在切分文本"})
        chunks = split_text(text, chunk_size, chunk_overlap, doc_id, doc_version_id)
        if not chunks:
            raise ValueError("切分后的 chunk 为空")

        texts = [c["text"] for c in chunks]
        logger.info(f"Processing {len(texts)} chunks for doc_id={doc_id}")

        # ===== 1. Dense Embedding =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "dense_embedding", "progress": 50, "message": "正在生成Dense向量"})
        vectors = generate_embeddings(texts)

        # ===== 2. BM25 Sparse Vectors =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "bm25_fitting", "progress": 65, "message": "正在拟合BM25模型"})
        fit_bm25_on_collection(COLLECTION_NAME, texts)
        sparse_vectors = generate_sparse_vectors_batch(texts, COLLECTION_NAME)

        # ===== 3. 构建 Payloads =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "preparing_payload", "progress": 80, "message": "正在准备索引数据"})
        payloads = [{
            "kb_id": kb_id,
            "doc_id": doc_id,
            "doc_version_id": doc_version_id,
            "chunk_id": c["chunk_id"],
            "text": c["text"]
        } for c in chunks]

        # ===== 4. 写入 Qdrant（混合向量） =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "indexing", "progress": 95, "message": "正在写入向量数据库"})
        await upsert_vectors_async(vectors, payloads, sparse_vectors)
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
    """重建索引：先删旧索引，再重新入库（混合向量）"""
    try:
        await delete_document_index_async(doc_id)
        logger.info(f"Old index deleted for doc_id={doc_id}, proceeding with re-ingest.")
    except Exception as e:
        logger.warning(f"Failed to delete old index for doc_id={doc_id}: {e}")

    await process_and_ingest_document(
        content, filename, task_id, task_code, kb_id, doc_id, doc_version_id, chunk_size, chunk_overlap, progress_queue
    )


async def reindex_text(
        text: str,
        task_id: int,
        task_code: str,
        kb_id: int,
        doc_id: int,
        doc_version_id: int,
        chunk_size: int,
        chunk_overlap: int,
        progress_queue: Optional[asyncio.Queue] = None
):
    """
    纯文本重索引（用于文档版本回滚）。

    直接接收应用域传入的历史版本文本，跳过文件解析步骤。
    先删旧版向量，再入新版向量。
    """
    chunk_count = 0
    error_msg = None

    async def push_event(event: str, data: dict):
        if progress_queue:
            await progress_queue.put({"event": event, "data": data})
            await asyncio.sleep(0)

    try:
        # 先删旧版
        try:
            await delete_document_index_async(doc_id)
            logger.info(f"Old index deleted for doc_id={doc_id} before text reindex.")
        except Exception as e:
            logger.warning(f"Failed to delete old index for doc_id={doc_id}: {e}")

        await push_event("progress",
                         {"task_id": task_id, "stage": "splitting", "progress": 35, "message": "正在切分文本"})
        chunks = split_text(text, chunk_size, chunk_overlap, doc_id, doc_version_id)
        if not chunks:
            raise ValueError("切分后的 chunk 为空")

        texts = [c["text"] for c in chunks]
        logger.info(f"Reindex text: processing {len(texts)} chunks for doc_id={doc_id}")

        # Dense Embedding
        await push_event("progress",
                         {"task_id": task_id, "stage": "dense_embedding", "progress": 50, "message": "正在生成Dense向量"})
        vectors = generate_embeddings(texts)

        # BM25 Sparse Vectors
        await push_event("progress",
                         {"task_id": task_id, "stage": "bm25_fitting", "progress": 65, "message": "正在拟合BM25模型"})
        fit_bm25_on_collection(COLLECTION_NAME, texts)
        sparse_vectors = generate_sparse_vectors_batch(texts, COLLECTION_NAME)

        # Payloads
        await push_event("progress",
                         {"task_id": task_id, "stage": "preparing_payload", "progress": 80, "message": "正在准备索引数据"})
        payloads = [{
            "kb_id": kb_id,
            "doc_id": doc_id,
            "doc_version_id": doc_version_id,
            "chunk_id": c["chunk_id"],
            "text": c["text"]
        } for c in chunks]

        # 写入 Qdrant
        await push_event("progress",
                         {"task_id": task_id, "stage": "indexing", "progress": 95, "message": "正在写入向量数据库"})
        await upsert_vectors_async(vectors, payloads, sparse_vectors)
        chunk_count = len(vectors)

        await push_event("done", {"task_id": task_id, "status": "succeeded", "chunk_count": chunk_count})

    except Exception as e:
        logger.error(f"Reindex text failed for task {task_id}: {e}", exc_info=True)
        error_msg = str(e)
        await push_event("error", {"task_id": task_id, "code": "REINDEX_TEXT_FAILED", "message": error_msg})

    finally:
        await send_task_callback(task_id, task_code, chunk_count, error_msg)
        if progress_queue:
            await progress_queue.put(None)
