"""
文档入库主流程

功能：
- 解析 -> 切分 -> NER实体抽取 -> Dense向量化
- 完整payload元数据（来源/结构/权限/实体）-> 写入Qdrant -> 回调应用域

Payload 元数据（完整版）：
  kb_id, doc_id, doc_version_id, chunk_id, text,
  source_filename, file_type, page_number, section_title, chunk_position,
  is_table, table_meta, is_first_chunk, is_last_chunk,
  access_level, department_id,
  entities (NER抽取的医学实体列表)
"""
import asyncio
import logging
from typing import List, Dict, Optional

from shared.config import EMBEDDING_MODEL
from .parsers import extract_text_with_metadata
from .splitters import split_text, _get_chunk_position, _split_table_blocks
from .embeddings import generate_embeddings
from .vector_store import upsert_vectors_async, delete_document_index_async
from .vector_store import COLLECTION_NAME
from .ner import extract_medical_entities, get_entity_signature
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
        embedding_model: str = EMBEDDING_MODEL,
        progress_queue: Optional[asyncio.Queue] = None,
        # 访问控制参数（新增）
        access_level: str = "internal",
        department_id: Optional[int] = None,
):
    """
    文档入库主流程（完整版）。

    流程：
    1. 解析(带元数据)
    2. 语义切分
    3. NER实体抽取（医学词典 + 模型）
    4. Dense向量生成
    5. 写入Qdrant
    6. 回调应用域
    """
    chunk_count = 0
    error_msg = None

    async def push_event(event: str, data: dict):
        if progress_queue:
            await progress_queue.put({"event": event, "data": data})
            await asyncio.sleep(0)

    try:
        # ===== 第1步：解析 =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "parsing", "progress": 15, "message": "正在解析文档"})
        parsed = extract_text_with_metadata(content, filename)
        text = parsed["text"]
        file_meta = parsed.get("file_meta", {})
        blocks = parsed.get("blocks", [])
        if not text:
            raise ValueError("解析出的文本为空")

        # ===== 第2步：切分 =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "splitting", "progress": 30, "message": "正在切分文本"})
        ext = filename.split(".")[-1].lower()
        if ext in ["csv", "xlsx", "xls"] and blocks:
            chunks = _split_table_blocks(blocks, doc_id, doc_version_id)
        else:
            chunks = split_text(text, chunk_size, chunk_overlap, doc_id, doc_version_id)
        if not chunks:
            raise ValueError("切分后的 chunk 为空")

        # ===== 第3步：NER实体抽取 =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "ner_extraction", "progress": 40, "message": "正在抽取医学实体"})
        for chunk in chunks:
            chunk_text = chunk["text"]
            # 规则+模型混合抽取
            entities = extract_medical_entities(chunk_text)
            # 整理为payload友好格式
            chunk["entities"] = [
                {
                    "name": e["name"],
                    "type": e["type"],
                    "normalized": e["normalized"],
                }
                for e in entities
            ]
            # 实体签名（用于检索boost）
            sig = get_entity_signature(chunk_text)
            chunk["entity_sig"] = sig

        texts = [c["text"] for c in chunks]
        logger.info(f"Processing {len(texts)} chunks for doc_id={doc_id}, NER done.")

        # ===== 第4步：Dense向量 =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "dense_embedding", "progress": 70, "message": "正在生成Dense向量"})
        vectors = await asyncio.to_thread(generate_embeddings, texts)

        # ===== 第5步：构建Payload =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "preparing_payload", "progress": 85, "message": "正在准备索引数据"})
        payloads = []
        for c in chunks:
            payload: Dict = {
                # 基础ID
                "kb_id": kb_id,
                "doc_id": doc_id,
                "doc_version_id": doc_version_id,
                "chunk_id": c["chunk_id"],
                "text": c["text"],
                # 来源与结构
                "source_filename": file_meta.get("filename", filename),
                "file_type": file_meta.get("file_type", ext),
                "page_number": c.get("page_number"),
                "section_title": c.get("section_title", ""),
                "chunk_position": _get_chunk_position(c),
                # 表格
                "is_table": c.get("is_table", False),
                "table_meta": c.get("table_meta"),
                # 段落
                "is_heading": c.get("is_heading", False),
                "is_first_chunk": c.get("is_first_chunk", False),
                "is_last_chunk": c.get("is_last_chunk", False),
                # 访问控制（RBAC）
                "access_level": access_level,
                "department_id": department_id,
                # NER实体
                "entities": c.get("entities", []),
                "entity_sig": c.get("entity_sig", {}),
            }
            # 清除None和空字符串
            payload = {k: v for k, v in payload.items() if v is not None and v != ""}
            payloads.append(payload)

        # ===== 第6步：写入Qdrant =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "indexing", "progress": 95, "message": "正在写入向量数据库"})
        await upsert_vectors_async(vectors, payloads)
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
        content: bytes, filename: str, task_id: int, task_code: str,
        kb_id: int, doc_id: int, doc_version_id: int,
        chunk_size: int, chunk_overlap: int,
        embedding_model: str = EMBEDDING_MODEL,
        progress_queue: Optional[asyncio.Queue] = None,
        access_level: str = "internal",
        department_id: Optional[int] = None,
):
    """重建索引：先删旧索引，再重新入库"""
    try:
        await delete_document_index_async(doc_id)
        logger.info(f"Old index deleted for doc_id={doc_id}, proceeding with re-ingest.")
    except Exception as e:
        logger.warning(f"Failed to delete old index for doc_id={doc_id}: {e}")

    await process_and_ingest_document(
        content, filename, task_id, task_code, kb_id, doc_id, doc_version_id,
        chunk_size, chunk_overlap, embedding_model, progress_queue,
        access_level=access_level, department_id=department_id,
    )


async def reindex_text(
        text: str, task_id: int, task_code: str,
        kb_id: int, doc_id: int, doc_version_id: int,
        chunk_size: int, chunk_overlap: int,
        embedding_model: str = EMBEDDING_MODEL,
        progress_queue: Optional[asyncio.Queue] = None,
        access_level: str = "internal",
        department_id: Optional[int] = None,
):
    """纯文本重索引（文档版本回滚）"""
    chunk_count = 0
    error_msg = None

    async def push_event(event: str, data: dict):
        if progress_queue:
            await progress_queue.put({"event": event, "data": data})
            await asyncio.sleep(0)

    try:
        await delete_document_index_async(doc_id)
        logger.info(f"Old index deleted for doc_id={doc_id} before text reindex.")

        await push_event("progress",
                         {"task_id": task_id, "stage": "splitting", "progress": 35, "message": "正在切分文本"})
        chunks = split_text(text, chunk_size, chunk_overlap, doc_id, doc_version_id)
        if not chunks:
            raise ValueError("切分后的 chunk 为空")

        # NER
        await push_event("progress",
                         {"task_id": task_id, "stage": "ner_extraction", "progress": 40, "message": "正在抽取医学实体"})
        for c in chunks:
            entities = extract_medical_entities(c["text"])
            c["entities"] = [{"name": e["name"], "type": e["type"], "normalized": e["normalized"]} for e in entities]
            c["entity_sig"] = get_entity_signature(c["text"])

        texts = [c["text"] for c in chunks]

        # Dense
        await push_event("progress",
                         {"task_id": task_id, "stage": "dense_embedding", "progress": 70, "message": "正在生成Dense向量"})
        vectors = await asyncio.to_thread(generate_embeddings, texts)

        # Payload
        await push_event("progress",
                         {"task_id": task_id, "stage": "preparing_payload", "progress": 85, "message": "正在准备索引数据"})
        payloads = []
        for c in chunks:
            payload: Dict = {
                "kb_id": kb_id, "doc_id": doc_id, "doc_version_id": doc_version_id,
                "chunk_id": c["chunk_id"], "text": c["text"],
                "source_filename": "", "file_type": "text",
                "section_title": c.get("section_title", ""),
                "chunk_position": _get_chunk_position(c),
                "is_table": False, "table_meta": None,
                "is_heading": c.get("is_heading", False),
                "is_first_chunk": c.get("is_first_chunk", False),
                "is_last_chunk": c.get("is_last_chunk", False),
                "access_level": access_level,
                "department_id": department_id,
                "entities": c.get("entities", []),
                "entity_sig": c.get("entity_sig", {}),
            }
            payload = {k: v for k, v in payload.items() if v is not None and v != ""}
            payloads.append(payload)

        # 写入
        await push_event("progress",
                         {"task_id": task_id, "stage": "indexing", "progress": 95, "message": "正在写入向量数据库"})
        await upsert_vectors_async(vectors, payloads)
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
