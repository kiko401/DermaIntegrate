"""
文档入库主流程

功能：
- 解析 -> 切分 -> NER实体抽取 -> BM25增量拟合 -> Dense+Sparse向量化
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
from .parsers import extract_text_with_metadata
from .splitters import split_text
from .embeddings import generate_embeddings
from .vector_store import upsert_vectors_async, delete_document_index_async
from .bm25 import fit_bm25_on_collection, fit_bm25_incremental, get_collection_doc_count, COLLECTION_NAME
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
        embedding_model: str = "BAAI/bge-small-zh-v1.5",
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
    4. BM25增量拟合（已有文档则增量，新库则全量）
    5. Dense向量生成
    6. 写入Qdrant
    7. 回调应用域
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

        # ===== 第4步：BM25增量/全量拟合 =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "bm25_fitting", "progress": 50, "message": "正在拟合BM25模型"})
        existing_doc_count = get_collection_doc_count(COLLECTION_NAME)
        if existing_doc_count == 0:
            # 首个文档，全量拟合
            await asyncio.to_thread(fit_bm25_on_collection, COLLECTION_NAME, texts)
            logger.info(f"BM25 full fit (first document): {len(texts)} chunks")
        else:
            # 已有文档，增量更新
            await asyncio.to_thread(fit_bm25_incremental, COLLECTION_NAME, texts)
            logger.info(f"BM25 incremental fit: +{len(texts)} chunks")

        # 生成sparse向量
        from .bm25 import generate_sparse_vectors_batch
        sparse_vectors = await asyncio.to_thread(generate_sparse_vectors_batch, texts, COLLECTION_NAME)

        # ===== 第5步：Dense向量 =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "dense_embedding", "progress": 65, "message": "正在生成Dense向量"})
        vectors = await asyncio.to_thread(generate_embeddings, texts)

        # ===== 第6步：构建Payload =====
        await push_event("progress",
                         {"task_id": task_id, "stage": "preparing_payload", "progress": 80, "message": "正在准备索引数据"})
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

        # ===== 第7步：写入Qdrant =====
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


def _get_chunk_position(chunk: Dict) -> str:
    if chunk.get("is_first_chunk"):
        return "first"
    if chunk.get("is_last_chunk"):
        return "last"
    return "middle"


def _split_table_blocks(blocks: List[Dict], doc_id: int, doc_version_id: int) -> List[Dict]:
    """表格文件切分：100行一组"""
    if not blocks:
        return []

    TABLE_ROWS_PER_CHUNK = 100
    chunks = []
    chunk_index = 0

    table_blocks = [b for b in blocks if b.get("is_table")]
    non_table_blocks = [b for b in blocks if not b.get("is_table")]

    for nt in non_table_blocks:
        text = nt["text"].strip()
        if not text:
            continue
        chunk_id = f"{doc_id}_{doc_version_id}_{str(chunk_index).zfill(3)}"
        chunks.append({
            "chunk_id": chunk_id, "chunk_index": chunk_index, "text": text,
            "section_title": nt.get("section_title", ""),
            "is_first_chunk": chunk_index == 0, "is_last_chunk": False,
            "is_heading": nt.get("is_heading", False),
        })
        chunk_index += 1

    for tb in table_blocks:
        tm = tb.get("table_meta") or {}
        row_count = tm.get("row_count", 0)
        lines = tb["text"].split("\n")
        group_count = max(1, (row_count + TABLE_ROWS_PER_CHUNK - 1) // TABLE_ROWS_PER_CHUNK)

        for gi in range(group_count):
            start_i = gi * TABLE_ROWS_PER_CHUNK
            end_i = min(start_i + TABLE_ROWS_PER_CHUNK, len(lines))
            group_text = "\n".join(lines[start_i:end_i])
            chunk_id = f"{doc_id}_{doc_version_id}_{str(chunk_index).zfill(3)}"
            chunks.append({
                "chunk_id": chunk_id, "chunk_index": chunk_index, "text": group_text,
                "section_title": tb.get("section_title", ""),
                "is_first_chunk": False, "is_last_chunk": (gi == group_count - 1),
                "is_heading": False, "is_table": True,
                "table_meta": {**tm, "chunk_row_start": start_i, "chunk_row_end": end_i,
                                "chunk_index": gi, "total_chunks": group_count},
            })
            chunk_index += 1

    if chunks:
        chunks[-1]["is_last_chunk"] = True
    logger.info(f"Table split: {len(chunks)} chunks for doc_id={doc_id}")
    return chunks


async def reindex_document(
        content: bytes, filename: str, task_id: int, task_code: str,
        kb_id: int, doc_id: int, doc_version_id: int,
        chunk_size: int, chunk_overlap: int,
        embedding_model: str = "BAAI/bge-small-zh-v1.5",
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
        embedding_model: str = "BAAI/bge-small-zh-v1.5",
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

        # BM25增量
        await push_event("progress",
                         {"task_id": task_id, "stage": "bm25_fitting", "progress": 50, "message": "正在拟合BM25模型"})
        existing_doc_count = get_collection_doc_count(COLLECTION_NAME)
        if existing_doc_count == 0:
            await asyncio.to_thread(fit_bm25_on_collection, COLLECTION_NAME, texts)
        else:
            await asyncio.to_thread(fit_bm25_incremental, COLLECTION_NAME, texts)

        from .bm25 import generate_sparse_vectors_batch
        sparse_vectors = await asyncio.to_thread(generate_sparse_vectors_batch, texts, COLLECTION_NAME)

        # Dense
        await push_event("progress",
                         {"task_id": task_id, "stage": "dense_embedding", "progress": 60, "message": "正在生成Dense向量"})
        vectors = await asyncio.to_thread(generate_embeddings, texts)

        # Payload
        await push_event("progress",
                         {"task_id": task_id, "stage": "preparing_payload", "progress": 80, "message": "正在准备索引数据"})
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
