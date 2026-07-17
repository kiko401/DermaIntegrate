import io
import logging
import asyncio
import httpx
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from shared.config import ETL_CONNECT_TIMEOUT, ETL_READ_TIMEOUT
from ..ingest.parsers import extract_text_from_file
from ..ingest.splitters import split_text
from ..ingest.embeddings import generate_embeddings
from ..ingest.vector_store import upsert_vectors_async
from ..ingest.bm25 import fit_bm25_on_collection, generate_sparse_vectors_batch
from ..schemas import ETLJobStatus

logger = logging.getLogger(__name__)

# 内存级 ETL 任务状态（上限从 shared/config 统一读取）
_ETL_JOBS: Dict[str, ETLJobStatus] = {}
from shared.config import MAX_ETL_JOBS as _MAX_ETL_JOBS


def _prune_etl_jobs():
    """清理最老的已完成 ETL 任务，保持内存占用受控"""
    if len(_ETL_JOBS) <= _MAX_ETL_JOBS:
        return
    # 按 created_at 升序，删除最早的已完成任务
    sorted_jobs = sorted(
        [(k, v) for k, v in _ETL_JOBS.items() if v.created_at],
        key=lambda x: x[1].created_at or ""
    )
    remove_count = len(_ETL_JOBS) - _MAX_ETL_JOBS
    for k, _ in sorted_jobs[:remove_count]:
        del _ETL_JOBS[k]
    logger.info(f"Pruned {remove_count} old ETL jobs from memory.")


def _clean_text(text: str) -> str:
    """
    M-13 增强清洗逻辑：
    1. 去除多余空格、换行
    2. regex 替换（可配置敏感模式）
    3. 去除重复行（如连续重复的标题/分隔符）
    4. 去除空值占位符（null/none/NA/-- 等）
    """
    import re

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
    M-13 数据库源 ETL：从 MySQL/PostgreSQL 等数据库拉取数据。

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
            connect_timeout=ETL_CONNECT_TIMEOUT, read_timeout=ETL_READ_TIMEOUT,
        )
        async with conn.cursor(aiomysql.DictCursor) as cur:
            if sql_query:
                await cur.execute(sql_query)
            else:
                await cur.execute(f"SELECT * FROM `{table_name}` LIMIT 10000")
            rows = await cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    elif db_type == "postgresql":
        import asyncpg
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password, database=database,
            timeout=ETL_READ_TIMEOUT,
        )
        if sql_query:
            rows = await conn.fetch(sql_query)
        else:
            rows = await conn.fetch(f'SELECT * FROM "{table_name}" LIMIT 10000')
        await conn.close()
        return [dict(r) for r in rows]

    else:
        raise ValueError(f"Unsupported db_type: {db_type}. Supported: mysql, postgresql")


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
    job_id = f"etl_job_{req.kb_id}_{int(datetime.now().timestamp())}"
    job_name = req.job_name or f"ETL-{job_id}"

    if req.source_type == "url":
        source_url = req.source_config.get("url", "")
        if not source_url:
            raise ValueError("source_type=url requires source_config.url")

        import httpx
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=ETL_CONNECT_TIMEOUT, read=ETL_READ_TIMEOUT)) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                content = resp.content
            filename = source_url.split("/")[-1] or "downloaded_file"
        except Exception as e:
            logger.error(f"Failed to fetch URL for ETL: {e}")
            raise RuntimeError(f"Failed to fetch source URL: {e}")

        # 异步执行入库
        asyncio.create_task(
            extract_and_ingest(content, filename, req.kb_id, 0, 0, job_id, job_name)
        )

    elif req.source_type == "database":
        # M-13: 数据库源 ETL
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
            filename = f"db_{table_name or 'query'}"
        except Exception as e:
            logger.error(f"Failed to fetch data from database for ETL: {e}")
            raise RuntimeError(f"Failed to fetch database: {e}")

        asyncio.create_task(
            extract_and_ingest(content, filename, req.kb_id, 0, 0, job_id, job_name)
        )

    else:
        # file/csv/excel 由 run_etl_file_endpoint 处理
        raise ValueError(f"source_type={req.source_type} should use /etl/run-file endpoint")

    job_status = ETLJobStatus(
        job_id=job_id,
        job_name=job_name,
        status="running",
        progress=0,
        stage="pending",
        created_at=datetime.now().isoformat(),
    )
    _ETL_JOBS[job_id] = job_status
    _prune_etl_jobs()
    return job_id, job_status


async def extract_and_ingest(
        content: bytes,
        filename: str,
        kb_id: int,
        doc_id: int,
        doc_version_id: int,
        job_id: str,
        job_name: Optional[str] = None,
):
    """ETL 主流程：抽取 -> 清洗 -> 行转文本 -> 切分 -> 双重索引入库"""
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
        job.stage = "extracting"
        job.progress = 10
        raw_text = extract_text_from_file(content, filename)

        job.stage = "cleaning"
        job.progress = 30
        cleaned_text = _clean_text(raw_text)

        job.stage = "splitting"
        job.progress = 50
        chunks = split_text(cleaned_text, 800, 120, doc_id, doc_version_id or 0)

        job.stage = "embedding"
        job.progress = 70
        texts = [c["text"] for c in chunks]
        vectors = generate_embeddings(texts)

        job.stage = "indexing"
        job.progress = 90
        payloads = []
        for c in chunks:
            keywords = list(set(c["text"].split()))[:10]
            payloads.append({
                "kb_id": kb_id,
                "doc_id": doc_id,
                "doc_version_id": doc_version_id,
                "chunk_id": c["chunk_id"],
                "text": c["text"],
                "keywords": keywords,
            })

        await upsert_vectors_async(vectors, payloads)

        job.status = "succeeded"
        job.progress = 100
        job.stage = "completed"
        logger.info(f"ETL job {job_id} succeeded.")
        return job

    except Exception as e:
        logger.error(f"ETL job {job_id} failed: {e}")
        job.status = "failed"
        job.error_message = str(e)
        job.stage = "failed"
        return job


async def get_etl_job_status(job_id: str) -> Optional[Dict]:
    """查询 ETL 任务状态"""
    job = _ETL_JOBS.get(job_id)
    return job.model_dump() if job else None


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
        chunk_size: int = 800,
        chunk_overlap: int = 120,
) -> Tuple[int, str]:
    """
    临床病例 ETL 主流程：文本构建 -> 清洗 -> 切分 -> 混合向量生成 -> Qdrant 入库。

    Returns:
        (chunk_count, status)
    """
    # 1. 构建自然语言文本
    raw_text = _build_clinical_text(patient_context, case_text, case_type)

    # 2. 清洗
    cleaned_text = _clean_text(raw_text)

    # 3. 切分（doc_id 用 0 占位，kb_id 相同即可检索）
    doc_id = 0
    chunks = split_text(cleaned_text, chunk_size, chunk_overlap, doc_id, doc_version_id)
    if not chunks:
        raise ValueError("clinical ETL: split produced no chunks")

    texts = [c["text"] for c in chunks]

    # 4. Dense embedding
    vectors = generate_embeddings(texts)

    # 5. BM25 拟合 + Sparse 向量
    from ..ingest.vector_store import COLLECTION_NAME
    fit_bm25_on_collection(COLLECTION_NAME, texts)
    sparse_vectors = generate_sparse_vectors_batch(texts, COLLECTION_NAME)

    # 6. Payload 构建
    payloads = [{
        "kb_id": kb_id,
        "doc_id": doc_id,
        "doc_version_id": doc_version_id,
        "chunk_id": c["chunk_id"],
        "text": c["text"],
    } for c in chunks]

    # 7. 混合向量写入 Qdrant
    await upsert_vectors_async(vectors, payloads, sparse_vectors)

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
