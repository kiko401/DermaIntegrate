import io
import logging
import asyncio
from typing import Dict, Optional
from ..ingest.parsers import extract_text_from_file
from ..ingest.splitters import split_text
from ..ingest.embeddings import generate_embeddings
from ..ingest.vector_store import upsert_vectors
from ..schemas import ETLJobStatus

logger = logging.getLogger(__name__)

# 内存级 ETL 任务状态
_ETL_JOBS: Dict[str, ETLJobStatus] = {}


def _clean_text(text: str) -> str:
    """清洗逻辑：去除多余空格、换行"""
    import re
    text = re.sub(r'\s+', ' ', text).strip()
    return text


async def extract_and_ingest(content: bytes, filename: str, kb_id: int, doc_id: int, doc_version_id: int, job_id: str):
    """ETL 主流程：抽取 -> 清洗 -> 行转文本 -> 切分 -> 双重索引入库"""
    if job_id not in _ETL_JOBS:
        _ETL_JOBS[job_id] = ETLJobStatus(job_id=job_id, status="running", progress=0)

    try:
        _ETL_JOBS[job_id].progress = 10
        # 1. 抽取
        raw_text = extract_text_from_file(content, filename)

        _ETL_JOBS[job_id].progress = 30
        # 2. 清洗
        cleaned_text = _clean_text(raw_text)

        _ETL_JOBS[job_id].progress = 50
        # 3. 行转文本 (如果是表格格式，解析器已转为 text，这里统一处理)
        # 4. 切分
        chunks = split_text(cleaned_text, 800, 120, doc_id, doc_version_id)

        _ETL_JOBS[job_id].progress = 70
        # 5. 向量化
        texts = [c["text"] for c in chunks]
        vectors = generate_embeddings(texts)

        _ETL_JOBS[job_id].progress = 90
        # 6. 双重索引入库 (Qdrant 向量索引 + Payload 关键词索引)
        # Qdrant 支持 payload 索引，这里我们在 payload 中存入 keywords 模拟双重索引
        payloads = []
        for c in chunks:
            # 简单提取前 10 个词作为关键词索引
            keywords = list(set(c["text"].split()))[:10]
            payloads.append({
                "kb_id": kb_id, "doc_id": doc_id, "doc_version_id": doc_version_id,
                "chunk_id": c["chunk_id"], "text": c["text"], "keywords": keywords
            })

        upsert_vectors(vectors, payloads)

        _ETL_JOBS[job_id].status = "succeeded"
        _ETL_JOBS[job_id].progress = 100
        logger.info(f"ETL job {job_id} succeeded.")

    except Exception as e:
        logger.error(f"ETL job {job_id} failed: {e}")
        _ETL_JOBS[job_id].status = "failed"
        _ETL_JOBS[job_id].detail = str(e)


async def get_etl_job_status(job_id: str) -> Optional[Dict]:
    """查询 ETL 任务状态"""
    job = _ETL_JOBS.get(job_id)
    return job.dict() if job else None