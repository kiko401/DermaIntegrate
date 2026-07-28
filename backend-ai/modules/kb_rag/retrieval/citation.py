import re
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
    """
    将检索到的 chunks 转换为 SourceObject 列表。

    来源字段优先级：
    - title / doc_code：优先使用 doc_title（入库时从文件名推导），
      fallback 到 source_filename（去扩展名）
    - source_location：补充 page_number + section_title（来自 chunk 元数据）
    """
    sources = []
    for chunk in chunks:
        chunk_id_str = chunk.get("chunk_id", "")
        chunk_index = _parse_chunk_index(chunk_id_str)

        # 截取 snippet（保留前200字符，表格内容换行转空格）
        raw_text = chunk.get("text", "")
        snippet = raw_text[:200].replace("\n", " ").replace("\r", " ") + ("..." if len(raw_text) > 200 else "")

        # 标题：优先 doc_title，fallback 到 source_filename（去掉扩展名）
        doc_title = chunk.get("doc_title")
        source_filename = chunk.get("source_filename", "")
        if doc_title:
            title = doc_title
        elif source_filename:
            # 去掉常见扩展名，保留可读标题
            title = re.sub(r"\.(pdf|docx?|xlsx?|csv|txt|md)$", "", source_filename, flags=re.IGNORECASE)
        else:
            title = f"文档 {chunk.get('doc_id', 0)}"

        # doc_code 使用 title 本身（避免无意义 ID）
        doc_code = title

        # source_location：补充页码和章节信息
        page_number = chunk.get("page_number")
        section_title = chunk.get("section_title", "")
        source_location: Dict = {}
        if page_number is not None:
            source_location["page"] = page_number
        if section_title:
            source_location["section"] = section_title
        chunk_position = chunk.get("chunk_position", "")
        if chunk_position:
            source_location["position"] = chunk_position

        source = SourceObject(
            doc_id=chunk.get("doc_id", 0),
            doc_code=doc_code,
            title=title,
            chunk_id=chunk_id_str,
            chunk_index=chunk_index,
            score=chunk.get("score", 0.0),
            snippet=snippet,
            source_location=source_location if source_location else chunk.get("source_location", {}),
        )
        sources.append(source)

    return sources
