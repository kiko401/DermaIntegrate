import logging
from typing import List, Dict
from ..schemas import SourceObject

logger = logging.getLogger(__name__)


def build_citations(chunks: List[Dict]) -> List[SourceObject]:
    """将检索到的 chunks 转换为 SourceObject 列表。"""
    sources = []
    for idx, chunk in enumerate(chunks):
        snippet = chunk.get("text", "")[:200].replace("\n", " ") + "..."
        source = SourceObject(
            doc_id=chunk.get("doc_id", 0),
            doc_code=chunk.get("doc_code", f"doc_{chunk.get('doc_id', 0)}"),
            title=chunk.get("title", f"文档 {chunk.get('doc_id', 0)}"),
            chunk_id=chunk.get("chunk_id", ""),
            chunk_index=idx,
            score=chunk.get("score", 0.0),
            snippet=snippet,
            source_location=chunk.get("source_location", {})
        )
        sources.append(source)

    return sources
