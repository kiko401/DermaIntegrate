import logging
from typing import List, Dict
from ..schemas import SourceObject

logger = logging.getLogger(__name__)


def _parse_chunk_index(chunk_id: str) -> int:
    """从 chunk_id 解析真实 chunk 序号。

    chunk_id 格式: {doc_id}_{doc_version_id}_{chunk_index_zero_padded}
    示例: "5_1_007" -> 7, "12_3_001" -> 1, "doc_ver_042" -> 42
    从右边 rsplit 两次，以防 doc_version_id 本身含下划线。
    """
    parts = chunk_id.rsplit("_", 2)
    if len(parts) >= 3:
        try:
            return int(parts[2])
        except ValueError:
            pass
    return 0


def build_citations(chunks: List[Dict]) -> List[SourceObject]:
    """将检索到的 chunks 转换为 SourceObject 列表。"""
    sources = []
    for chunk in chunks:
        chunk_id_str = chunk.get("chunk_id", "")
        chunk_index = _parse_chunk_index(chunk_id_str)
        snippet = chunk.get("text", "")[:200].replace("\n", " ") + "..."
        source = SourceObject(
            doc_id=chunk.get("doc_id", 0),
            doc_code=chunk.get("doc_code", f"doc_{chunk.get('doc_id', 0)}"),
            title=chunk.get("title", f"文档 {chunk.get('doc_id', 0)}"),
            chunk_id=chunk_id_str,
            chunk_index=chunk_index,
            score=chunk.get("score", 0.0),
            snippet=snippet,
            source_location=chunk.get("source_location", {})
        )
        sources.append(source)

    return sources
