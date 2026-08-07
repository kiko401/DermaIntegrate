import logging
import re
import asyncio
import hashlib
from uuid import uuid4
from datetime import datetime
from typing import Dict, Optional, List, Tuple

import httpx

from shared.config import (
    ETL_CONNECT_TIMEOUT,
    ETL_READ_TIMEOUT,
    MAX_ETL_JOBS as _MAX_ETL_JOBS,
    APP_BASE_URL,
    X_INTERNAL_SECRET,
    CALLBACK_CONNECT_TIMEOUT,
    CALLBACK_READ_TIMEOUT,
    CALLBACK_WRITE_TIMEOUT,
    CALLBACK_POOL_TIMEOUT,
    MAX_CALLBACK_RETRIES,
    CALLBACK_RETRY_DELAY,
)
from ..ingest.parsers import extract_text_with_metadata
from ..ingest.splitters import split_text, _get_chunk_position, _split_table_blocks
from ..ingest.embeddings import generate_embeddings
from ..ingest.vector_store import upsert_vectors_async
from ..ingest.ner import extract_medical_entities, get_entity_signature
from ..schemas import ETLJobStatus

logger = logging.getLogger(__name__)

# 内存级 ETL 任务状态（上限从 shared/config 统一读取）
_ETL_JOBS: Dict[str, ETLJobStatus] = {}


async def _notify_app_domain_etl_update(job_id: str, payload: Dict) -> None:
    """回调应用域，持久化 ETL 状态。"""
    if not APP_BASE_URL or not X_INTERNAL_SECRET:
        return

    callback_url = f"{APP_BASE_URL}/api/rag/etl/jobs/{job_id}/callback"
    timeout = httpx.Timeout(
        connect=CALLBACK_CONNECT_TIMEOUT,
        read=CALLBACK_READ_TIMEOUT,
        write=CALLBACK_WRITE_TIMEOUT,
        pool=CALLBACK_POOL_TIMEOUT,
    )

    last_error = None
    for attempt in range(1, MAX_CALLBACK_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(
                    callback_url,
                    json=payload,
                    headers={
                        "X-Internal-Token": X_INTERNAL_SECRET,
                        "Content-Type": "application/json",
                    },
                )
                res.raise_for_status()
                return
        except Exception as e:
            last_error = e
            if attempt < MAX_CALLBACK_RETRIES:
                await asyncio.sleep(CALLBACK_RETRY_DELAY)
    logger.warning(f"ETL callback failed for {job_id}: {last_error}")


async def _set_job_state(job_id: str, **patch):
    """统一更新内存态并回调应用域。"""
    job = _ETL_JOBS.get(job_id)
    if not job:
        return None

    for key, value in patch.items():
        setattr(job, key, value)

    callback_payload = {}
    for key in ("status", "progress", "stage", "detail", "error_message"):
        value = getattr(job, key, None)
        if value is not None:
            callback_payload[key] = value

    if callback_payload:
        await _notify_app_domain_etl_update(job_id, callback_payload)
    return job


def _derive_doc_title(filename: str) -> str:
    """从文件名推导文档标题（去掉常见扩展名）"""
    return re.sub(r"\.(pdf|docx?|xlsx?|csv|txt|md)$", "", filename, flags=re.IGNORECASE)


def _prune_etl_jobs():
    """清理最老的已完成 ETL 任务，保持内存占用受控"""
    if len(_ETL_JOBS) <= _MAX_ETL_JOBS:
        return
    # 按 created_at 升序，删除最早的已完成任务
    sorted_jobs = sorted(
        [(k, v) for k, v in _ETL_JOBS.items() if v.created_at],
        key=lambda x: x[1].created_at or "0"
    )
    remove_count = len(_ETL_JOBS) - _MAX_ETL_JOBS
    for k, _ in sorted_jobs[:remove_count]:
        del _ETL_JOBS[k]
    logger.info(f"Pruned {remove_count} old ETL jobs from memory.")


def register_etl_job_pending(job_id: str, job_name: Optional[str] = None):
    """后台任务提交前预注册 job，状态为 pending，确保立即可查询"""
    _ETL_JOBS[job_id] = ETLJobStatus(
        job_id=job_id,
        job_name=job_name,
        status="pending",
        progress=0,
        stage="pending",
        created_at=datetime.now().isoformat(),
    )
    _prune_etl_jobs()


def _clean_text(text: str) -> str:
    """
    文本增强清洗流程：
    1. 去除多余空格、换行
    2. 去除空值占位符（null/none/NA/-- 等）
    3. 去除连续重复行（如多个空行分隔符 ------- / **** 等）
    4. 去除句末残余特殊字符
    5. 去除首尾非文字符号（如 #### 标题边框）
    6. 合并孤立单字符（医学文本中无意义）
    7. 再次清理多余空格
    """
    # 1. 去除多余空格、换行
    text = re.sub(r'\s+', ' ', text).strip()

    # 2. 去除空值占位符（不同时打断有效文本）
    null_placeholders = [r'\bN/A\b', r'\bNA\b', r'\bNULL\b', r'\bNone\b', r'\bnull\b', r'\b--\b', r'\b####\b']
    for placeholder in null_placeholders:
        text = re.sub(placeholder, '', text, flags=re.IGNORECASE)

    # 3. 去除连续重复行（如多个空行分隔符 ------- / **** 等）
    text = re.sub(r'(^[_*\-\s]{3,}\s*$(?:\n[_*\-\s]{3,}\s*$)*)', '', text, flags=re.MULTILINE)

    # 4. 去除句末残余特殊字符
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)

    # 5. 去除首尾非文字符号（如 #### 标题边框）
    text = re.sub(r'^[#*=_\-\|~\^]{2,}\s*', '', text)
    text = re.sub(r'\s*[#*=_\-\|~\^]{2,}$', '', text)

    # 6. 合并孤立单字符（医学文本中无意义）
    text = re.sub(r'\b(?<!\w)[a-zA-Z\u4e00-\u9fff]\b(?!\w)(?!\d)', '', text)

    # 7. 再次清理多余空格
    text = re.sub(r'\s+', ' ', text).strip()

    return text


async def _fetch_from_database(
    db_type: str,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    table_name: str,
    sql_query: str,
    chunk_field: str,
) -> List[Dict]:
    """
    从 MySQL/PostgreSQL 等关系数据库拉取结构化数据并转换为文本。

    Args:
        db_type: mysql | postgresql
        sql_query: 优先使用原始 SQL；否则基于 table_name 构建 SELECT *
    Returns:
        List[Dict] - 每行数据为一个 dict
    """
    import json

    if db_type == "mysql":
        import aiomysql
        conn = await aiomysql.connect(
            host=host, port=port, user=user, password=password, db=database,
            connect_timeout=ETL_CONNECT_TIMEOUT,
        )
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if sql_query:
                    await asyncio.wait_for(cur.execute(sql_query), timeout=ETL_READ_TIMEOUT)
                else:
                    await asyncio.wait_for(
                        cur.execute(f"SELECT * FROM `{table_name}` LIMIT 10000"),
                        timeout=ETL_READ_TIMEOUT,
                    )
                rows = await asyncio.wait_for(cur.fetchall(), timeout=ETL_READ_TIMEOUT)
            return [dict(r) for r in rows]
        finally:
            conn.close()

    elif db_type == "postgresql":
        import asyncpg
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password, database=database,
            timeout=ETL_CONNECT_TIMEOUT,
        )
        try:
            if sql_query:
                rows = await asyncio.wait_for(conn.fetch(sql_query), timeout=ETL_READ_TIMEOUT)
            else:
                rows = await asyncio.wait_for(
                    conn.fetch(f'SELECT * FROM "{table_name}" LIMIT 10000'),
                    timeout=ETL_READ_TIMEOUT,
                )
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    else:
        raise ValueError(f"Unsupported db_type: {db_type}. Supported: mysql, postgresql")


def _make_synthetic_doc_ids(job_id: str) -> Tuple[int, int]:
    """Create stable doc identifiers for URL/database ETL jobs to avoid chunk_id collisions."""
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()
    # Keep IDs in positive signed 32-bit range for broad DB/frontend compatibility.
    doc_id = int.from_bytes(digest[:4], byteorder="big") % 2_147_483_647
    if doc_id == 0:
        doc_id = 1
    doc_version_id = int.from_bytes(digest[4:8], byteorder="big") % 2_147_483_647
    if doc_version_id == 0:
        doc_version_id = 1
    return doc_id, doc_version_id


def _rows_to_text(rows: List[Dict], chunk_field: str) -> str:
    """
    将 DB 行列表转换为文本。
    - 如果指定了 chunk_field（逗号分隔的列名），只拼接这些列
    - 否则将所有列的 key=value 形式拼接
    """
    if not rows:
        return ""

    if chunk_field:
        fields = [f.strip() for f in chunk_field.split(",")]
        parts = []
        for row in rows:
            line_parts = [str(row.get(f, "")) for f in fields if row.get(f) is not None]
            if line_parts:
                parts.append(" ".join(line_parts))
    else:
        parts = []
        for row in rows:
            line_parts = [f"{k}={v}" for k, v in row.items() if v is not None]
            parts.append(" ".join(line_parts))

    return " | ".join(parts)


async def submit_etl_job(req) -> Tuple[str, ETLJobStatus]:
    """
    根据 source_type 和 source_config 调度 ETL 任务。
    source_type=url 时从远程 URL 拉取文件内容；
    source_type=file/csv/excel 时由调用方通过 run_etl_file_endpoint 上传。
    """
    # 避免同一 KB 在同一秒提交多个任务时发生 job_id 冲突。
    job_id = f"etl_job_{req.kb_id}_{int(datetime.now().timestamp())}_{uuid4().hex[:10]}"
    job_name = req.job_name or f"ETL-{job_id}"
    job_status = ETLJobStatus(
        job_id=job_id,
        job_name=job_name,
        status="running",
        progress=0,
        stage="pending",
        created_at=datetime.now().isoformat(),
    )
    # 先把 job 注册到内存状态表，再启动后台任务。
    # 否则 create_task 若先一步执行并更新了进度，
    # 这里再覆盖写回一个新的 0% 对象，会导致查询卡在 0%。
    _ETL_JOBS[job_id] = job_status
    _prune_etl_jobs()

    if req.source_type == "url":
        source_url = req.source_config.get("url", "")
        if not source_url:
            raise ValueError("source_type=url requires source_config.url")

        import httpx
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=ETL_CONNECT_TIMEOUT, read=ETL_READ_TIMEOUT, write=ETL_READ_TIMEOUT, pool=ETL_CONNECT_TIMEOUT)) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                content = resp.content
            filename = source_url.split("/")[-1] or "downloaded_file"
        except Exception as e:
            logger.error(f"Failed to fetch URL for ETL: {e}")
            raise RuntimeError(f"Failed to fetch source URL: {e}")

        # URL 文件大小限制，默认 50MB
        MAX_URL_FILE_SIZE = 50 * 1024 * 1024
        if len(content) > MAX_URL_FILE_SIZE:
            raise RuntimeError(f"URL file size {len(content)} exceeds limit {MAX_URL_FILE_SIZE}MB")

        # 异步执行入库，错误由 extract_and_ingest 内部捕获并更新 job 状态
        try:
            asyncio.create_task(
                extract_and_ingest(
                    content, filename, req.kb_id, *_make_synthetic_doc_ids(job_id), job_id, job_name,
                    chunk_size=req.chunk_size, chunk_overlap=req.chunk_overlap,
                )
            )
        except Exception as e:
            logger.error(f"Failed to start ETL task {job_id}: {e}")
            job = _ETL_JOBS.get(job_id)
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.stage = "failed"
            raise RuntimeError(f"Failed to start ETL task: {e}")

    elif req.source_type == "database":
        # 数据库源 ETL
        db_config = req.source_config or {}
        db_type = db_config.get("db_type", "mysql")
        table_name = db_config.get("table_name", "")
        sql_query = db_config.get("sql_query", "")
        chunk_field = db_config.get("chunk_field", "")  # 用于拼文本的 DB 字段

        if not table_name and not sql_query:
            raise ValueError("source_type=database requires source_config.table_name or source_config.sql_query")

        try:
            rows_data = await _fetch_from_database(
                db_type=db_type,
                host=db_config.get("host", ""),
                port=int(db_config.get("port", 3306)),
                user=db_config.get("user", ""),
                password=db_config.get("password", ""),
                database=db_config.get("database", ""),
                table_name=table_name,
                sql_query=sql_query,
                chunk_field=chunk_field,
            )
            # 将每行数据拼接为文本
            raw_text = _rows_to_text(rows_data, chunk_field)
            content = raw_text.encode("utf-8")
            filename = f"db_{table_name or 'query'}.txt"
        except Exception as e:
            logger.error(f"Failed to fetch data from database for ETL: {e}")
            raise RuntimeError(f"Failed to fetch database: {e}")

        try:
            asyncio.create_task(
                extract_and_ingest(
                    content, filename, req.kb_id, *_make_synthetic_doc_ids(job_id), job_id, job_name,
                    chunk_size=req.chunk_size, chunk_overlap=req.chunk_overlap,
                )
            )
        except Exception as e:
            logger.error(f"Failed to start ETL task {job_id}: {e}")
            job = _ETL_JOBS.get(job_id)
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.stage = "failed"
            raise RuntimeError(f"Failed to start ETL task: {e}")

    else:
        # file/csv/excel 由 run_etl_file_endpoint 处理
        raise ValueError(f"source_type={req.source_type} should use /etl/run-file endpoint")

    return job_id, job_status


async def extract_and_ingest(
        content: bytes,
        filename: str,
        kb_id: int,
        doc_id: int,
        doc_version_id: int,
        job_id: str,
        job_name: Optional[str] = None,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        access_level: str = "internal",
        department_id: Optional[int] = None,
):
    """
    ETL 主流程：抽取 -> 清洗 -> 切分 -> NER 实体抽取 -> Dense 向量生成 -> Qdrant 写入

    Payload 完整元数据与 ingestion.py 保持一致。
    """
    if job_id not in _ETL_JOBS:
        _ETL_JOBS[job_id] = ETLJobStatus(
            job_id=job_id,
            job_name=job_name,
            status="running",
            progress=0,
            created_at=datetime.now().isoformat(),
        )

    job = _ETL_JOBS[job_id]
    try:
        # ===== 第1步：抽取（带元数据）=====
        await _set_job_state(job_id, status="running", stage="extracting", progress=10)
        parsed = extract_text_with_metadata(content, filename)
        raw_text = parsed["text"]
        file_meta = parsed.get("file_meta", {})
        blocks = parsed.get("blocks", [])
        if not raw_text:
            raise ValueError("解析出的文本为空")

        # ===== 第2步：清洗 =====
        await _set_job_state(job_id, status="running", stage="cleaning", progress=25)
        cleaned_text = _clean_text(raw_text)

        # ===== 第3步：切分（区分表格/非表格）=====
        await _set_job_state(job_id, status="running", stage="splitting", progress=40)
        ext = filename.split(".")[-1].lower()
        if ext in ["csv", "xlsx", "xls"] and blocks:
            chunks = _split_table_blocks(blocks, doc_id, doc_version_id or 0)
        else:
            chunks = split_text(cleaned_text, chunk_size, chunk_overlap, doc_id, doc_version_id or 0)
        if not chunks:
            raise ValueError("切分后的 chunk 为空")

        # ===== 第4步：NER 实体抽取 =====
        await _set_job_state(job_id, status="running", stage="ner_extraction", progress=50)
        texts = []
        for c in chunks:
            chunk_text = c["text"]
            entities = extract_medical_entities(chunk_text)
            c["entities"] = [
                {"name": e["name"], "type": e["type"], "normalized": e["normalized"]}
                for e in entities
            ]
            c["entity_sig"] = get_entity_signature(chunk_text)
            texts.append(chunk_text)

        # ===== 第5步：Dense 向量 =====
        await _set_job_state(job_id, status="running", stage="embedding", progress=68)
        vectors = generate_embeddings(texts)

        # ===== 第6步：构建完整 Payload =====
        await _set_job_state(job_id, status="running", stage="indexing", progress=85)
        payloads = []
        for c in chunks:
            payload = {
                # 基础ID
                "kb_id": kb_id,
                "doc_id": doc_id,
                "doc_version_id": doc_version_id,
                "chunk_id": c["chunk_id"],
                "text": c["text"],
                # 来源与结构
                "source_filename": file_meta.get("filename", filename),
                "doc_title": _derive_doc_title(file_meta.get("filename", filename)),
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
                # 访问控制
                "access_level": access_level,
                "department_id": department_id,
                # NER 实体
                "entities": c.get("entities", []),
                "entity_sig": c.get("entity_sig", {}),
            }
            payload = {k: v for k, v in payload.items() if v is not None and v != ""}
            payloads.append(payload)

        # ===== 第7步：写入 Qdrant（纯 Dense 向量）=====
        await upsert_vectors_async(vectors, payloads)

        await _set_job_state(job_id, status="succeeded", progress=100, stage="completed")
        logger.info(f"ETL job {job_id} succeeded, {len(vectors)} chunks indexed.")
        return job

    except Exception as e:
        logger.error(f"ETL job {job_id} failed: {e}", exc_info=True)
        await _set_job_state(job_id, status="failed", stage="failed", error_message=str(e))
        return job


async def get_etl_job_status(job_id: str) -> Optional[Dict]:
    """查询 ETL 任务状态"""
    job = _ETL_JOBS.get(job_id)
    return job.model_dump() if job else None


def get_etl_jobs_list(status: Optional[str] = None, limit: int = 100) -> List[Dict]:
    """
    查询 ETL 任务列表。

    Args:
        status: 按状态筛选（pending/running/succeeded/failed），None 则返回全部
        limit: 返回数量限制

    Returns:
        符合条件的 ETL 任务列表（dict 形式）
    """
    all_jobs = list(_ETL_JOBS.values())
    # 按 created_at 降序排列
    sorted_jobs = sorted(
        all_jobs,
        key=lambda x: x.created_at or "0",
        reverse=True
    )
    # 按状态筛选
    if status:
        sorted_jobs = [j for j in sorted_jobs if j.status == status]
    # 限制数量
    limited_jobs = sorted_jobs[:limit]
    return [job.model_dump() for job in limited_jobs]


def _build_clinical_text(patient_context: Dict, case_text: str, case_type: str) -> str:
    """
    将脱敏后的患者上下文和病例文本构建为自然语言描述。

    Args:
        patient_context: PatientContextObject 的 dict 形式（summary_text + structured）
        case_text: 原始病例文本（已脱敏）
        case_type: 病例类型 his|lis|pacs|pathology
    """
    parts = []
    parts.append(f"【{case_type.upper()}病例】")

    summary = patient_context.get("summary_text", "")
    if summary:
        parts.append(f"患者概况：{summary}")

    structured = patient_context.get("structured", {})
    if structured:
        items = [f"{k}为{v}" for k, v in structured.items() if v]
        if items:
            parts.append("，".join(items) + "。")

    parts.append(f"病例详情：{case_text}")

    return " ".join(parts)


async def clinical_etl_and_ingest(
        kb_id: int,
        case_type: str,
        patient_context: Dict,
        case_text: str,
        doc_version_id: int,
        doctor_id: Optional[int] = None,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        access_level: str = "internal",
        department_id: Optional[int] = None,
) -> Tuple[int, str]:
    """
    临床病例 ETL 主流程：文本构建 -> 清洗 -> 切分 -> NER 实体抽取 ->
    Dense 向量生成 -> Qdrant 写入。

    Payload 完整元数据（与 ingestion.py 保持一致），含：
    - 基础ID（kb_id/doc_id/doc_version_id/chunk_id）
    - 来源与结构（doc_title/section_title/chunk_position/is_table等）
    - 访问控制（access_level/department_id）
    - NER 实体（entities/entity_sig）

    Returns:
        (chunk_count, status)
    """
    # 1. 构建自然语言文本
    raw_text = _build_clinical_text(patient_context, case_text, case_type)

    # 2. 清洗
    cleaned_text = _clean_text(raw_text)

    # 3. 切分（doc_id 使用 kb_id 以保证不同 kb_id 的 chunk_id 不互相覆盖）
    doc_id = kb_id
    chunks = split_text(cleaned_text, chunk_size, chunk_overlap, doc_id, doc_version_id)
    if not chunks:
        raise ValueError("clinical ETL: split produced no chunks")

    texts = [c["text"] for c in chunks]

    # 4. NER 实体抽取
    for c in chunks:
        entities = extract_medical_entities(c["text"])
        c["entities"] = [
            {"name": e["name"], "type": e["type"], "normalized": e["normalized"]}
            for e in entities
        ]
        c["entity_sig"] = get_entity_signature(c["text"])

    # 5. Dense embedding
    vectors = generate_embeddings(texts)

    # 6. Payload 构建（含完整元数据与权限隔离字段）
    payloads = []
    for c in chunks:
        payload = {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "doc_version_id": doc_version_id,
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            # 来源与结构
            "source_filename": "",
            "doc_title": f"{case_type.upper()}病例",
            "section_title": "",
            "chunk_position": _get_chunk_position(c),
            # 段落
            "is_heading": c.get("is_heading", False),
            "is_first_chunk": c.get("is_first_chunk", False),
            "is_last_chunk": c.get("is_last_chunk", False),
            # 访问控制
            "access_level": access_level,
            "department_id": department_id,
            "doctor_id": doctor_id,
            # NER 实体
            "entities": c.get("entities", []),
            "entity_sig": c.get("entity_sig", {}),
        }
        payload = {k: v for k, v in payload.items() if v is not None and v != ""}
        payloads.append(payload)

    # 7. 纯 Dense 向量写入 Qdrant
    await upsert_vectors_async(vectors, payloads)

    logger.info(f"Clinical ETL done: kb_id={kb_id}, case_type={case_type}, chunks={len(vectors)}")
    return len(vectors), "succeeded"


async def export_feedback_by_filters(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        kb_ids: Optional[List[int]] = None,
        min_confidence: Optional[float] = None,
        conversation_data: Optional[List[Dict]] = None,
) -> Tuple[str, str]:
    """
    按条件筛选对话记录并导出为 JSONL。

    Args:
        start_date: 开始日期（ISO格式）
        end_date: 结束日期（ISO格式）
        kb_ids: 知识库ID列表（用于过滤）
        min_confidence: 最低置信度阈值
        conversation_data: 对话数据列表（由调用方从应用域获取后传入）

    Returns:
        (jsonl字符串, 文件名)
    """
    from .feedback_exporter import export_to_jsonl

    filename = f"feedback_export_{datetime.now().strftime('%Y%m%d%H%M%S')}.jsonl"

    if not conversation_data:
        logger.warning(
            f"Feedback export called but no conversation_data provided. "
            f"Filters: start={start_date}, end={end_date}, kb_ids={kb_ids}, min_confidence={min_confidence}"
        )
        return "", filename

    # 过滤符合条件的对话记录
    filtered_data = []
    for conv in conversation_data:
        # 按日期范围过滤
        if start_date or end_date:
            conv_date = conv.get("created_at", "")
            if start_date and conv_date < start_date:
                continue
            if end_date and conv_date > end_date:
                continue

        # 按知识库ID过滤
        if kb_ids:
            conv_kb_ids = conv.get("kb_ids", [])
            if not any(kb_id in conv_kb_ids for kb_id in kb_ids):
                continue

        # 按置信度过滤
        if min_confidence is not None:
            conv_confidence = conv.get("confidence", 1.0)
            if conv_confidence < min_confidence:
                continue

        filtered_data.append(conv)

    logger.info(
        f"Feedback export: filtered {len(conversation_data)} records to {len(filtered_data)} records. "
        f"Filters: start={start_date}, end={end_date}, kb_ids={kb_ids}, min_confidence={min_confidence}"
    )

    # 调用 feedback_exporter 转换为 JSONL 格式
    jsonl_str = await export_to_jsonl(filtered_data)
    return jsonl_str, filename
