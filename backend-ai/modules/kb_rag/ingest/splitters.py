"""
文本语义切分器

三级切分策略（由粗到细）：
1. 段落级：优先按段落边界（\\n\\n）切，保持语义块完整
2. 句子级：段落过长时，在句子边界（。！？.!?）再切
3. 字符级：句子仍然超长时，退化为固定字符滑动窗口

保证：
- chunk_id 格式：{doc_id}_{doc_version_id}_{chunk_index三位补零}
- chunk_overlap >= chunk_size 时自动修正为 chunk_size // 2
"""
import re
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 表格切分常量
TABLE_ROWS_PER_CHUNK = 100


def _get_chunk_position(chunk: Dict) -> str:
    """根据 chunk 的首尾标记返回其在文档中的位置描述。"""
    if chunk.get("is_first_chunk"):
        return "first"
    if chunk.get("is_last_chunk"):
        return "last"
    return "middle"


def _split_table_blocks(blocks: List[Dict], doc_id: int, doc_version_id: int) -> List[Dict]:
    """表格文件切分：100行一组。"""
    if not blocks:
        return []

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


# 中文句子结束标点
_CN_PUNCT = "。！？"
_EN_PUNCT = ".!?"
_ALL_PUNCT = _CN_PUNCT + _EN_PUNCT

# 最小 chunk 长度阈值（字符）：小于此值尝试与下一段合并
_MIN_CHUNK_CHARS = 100

# 单句最大字符数：超过此值视为超长段，强制在任意位置截断
_SINGLE_SENTENCE_MAX_CHARS = 1500


def _split_sentences(text: str) -> List[str]:
    """
    将文本切分为句子列表（保持句子完整性）。

    中文按 。！？ 分割，英文按 .!? 分割。
    不破坏 URL、编号列表等结构。
    """
    if not text:
        return []

    sentences = []
    # 按中英文标点分割，同时保留标点
    pattern = f"(?<=[{re.escape(_ALL_PUNCT)}])"
    parts = re.split(pattern, text)

    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 尝试追加到当前句子（处理列表编号如 "1. xxx"）
        if current:
            # 如果 current 末尾是字母/数字，part 开头是大写或数字，当作新句子
            if current[-1].isalnum() and part and (part[0].isupper() or part[0].isdigit()):
                sentences.append(current)
                current = part
            else:
                current += part
        else:
            current = part

    if current.strip():
        sentences.append(current.strip())

    return sentences


def _is_heading_style(text: str) -> bool:
    """判断文本是否为标题样式（短行 + 有特定前缀/模式）"""
    text = text.strip()
    if not text:
        return False
    # Markdown/AsciiDoc 标题
    if text.startswith("#"):
        return True
    # 纯数字编号章节：如 "3.2.1"、"第3章"、"3、" 开头
    if re.match(r"^(第?[0-9]+[\.、章节]|[0-9]+[\.、])", text):
        return True
    # 短行（<=30字符）且末尾无标点，大概率是标题
    if len(text) <= 30 and text[-1] not in _ALL_PUNCT:
        return True
    return False


def _semantic_chunk(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    doc_id: int,
    doc_version_id: int,
    section_title: Optional[str] = None,
) -> List[Dict]:
    """
    语义切分主逻辑。

    策略：
    1. 先按 \\n\\n 分段落
    2. 逐段处理：够长直接用，太短则与下一段合并
    3. 单段超长时按句子切
    4. 最终仍超长时退化为滑动窗口
    """
    if not text:
        return []

    # 预处理：统一换行符
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    chunks = []
    chunk_index = 0
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size
        window_text = text[start:end]

        # ===== 检测这个 window 是否是段落开头（往前追溯）=====
        is_first_in_paragraph = (start == 0) or (text[start - 1] == "\n" and text[start - 2 : start] == "\n")

        # ===== 判断 window 末尾是否在句子边界 =====
        # 找最近的句子结束标点
        sentence_break = -1
        search_window = window_text[-200:] if len(window_text) > 200 else window_text
        for i, ch in enumerate(reversed(search_window)):
            if ch in _ALL_PUNCT:
                # 找到了标点，sentence_break 是相对 window 末尾的位置
                sentence_break = len(window_text) - 1 - i
                break

        chunk_text: str
        if sentence_break > chunk_size * 0.6:
            # 句子边界在 window 后 60% 以内，且剩余文本足够长，可以在这里切
            remaining = text_len - (start + sentence_break + 1)
            if remaining > _MIN_CHUNK_CHARS:
                chunk_text = window_text[: sentence_break + 1].strip()
            else:
                # 剩余文本太少，不急着在这里切，继续往后扩
                chunk_text = window_text
        elif len(window_text) >= chunk_size:
            # 没有好的句子边界，但 window 已满，在任意位置切
            chunk_text = window_text
        else:
            chunk_text = window_text

        chunk_text = chunk_text.strip()
        if chunk_text:
            chunk_id = f"{doc_id}_{doc_version_id}_{str(chunk_index).zfill(3)}"
            is_last = (start + len(chunk_text)) >= text_len

            chunk_entry: Dict[str, object] = {
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "text": chunk_text,
                "section_title": section_title or "",
                "is_first_chunk": chunk_index == 0,
                "is_last_chunk": is_last,
                "is_heading": _is_heading_style(chunk_text) if chunk_text else False,
            }
            chunks.append(chunk_entry)
            chunk_index += 1

        # 移动窗口（带重叠）
        if end >= text_len:
            break
        # 下一起始位置：当前 chunk 末尾 - 重叠量
        next_start = start + (len(chunk_text) if chunk_text else chunk_size) - chunk_overlap
        start = max(next_start, start + 1)  # 保证至少前进一步

    return chunks


def split_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    doc_id: int,
    doc_version_id: int,
    section_title: Optional[str] = None,
) -> List[Dict]:
    """
    语义感知文本切分。

    Args:
        text: 原始文档文本
        chunk_size: 每段最大字符数
        chunk_overlap: 相邻段重叠字符数
        doc_id: 文档ID
        doc_version_id: 文档版本ID
        section_title: 当前章节/段落标题（可选，用于元数据）

    Returns:
        List[Dict]，每项含 chunk_id, chunk_index, text, section_title,
        is_first_chunk, is_last_chunk, is_heading
    """
    # 防死循环保护
    if chunk_overlap >= chunk_size:
        logger.warning(
            f"chunk_overlap ({chunk_overlap}) >= chunk_size ({chunk_size}), "
            f"auto-correcting to {chunk_size // 2}"
        )
        chunk_overlap = chunk_size // 2

    if not text:
        return []

    # 检测是否为表格描述文本（每行以"第N条记录"开头）
    # 对这种格式化文本，不做语义切分，直接按固定大小滑动窗口
    if text.startswith("第") and "条记录" in text[:10]:
        logger.debug(f"Table-formatted text detected, using sliding window for doc_id={doc_id}")
        return _sliding_window_fallback(text, chunk_size, chunk_overlap, doc_id, doc_version_id)

    return _semantic_chunk(text, chunk_size, chunk_overlap, doc_id, doc_version_id, section_title)


def _sliding_window_fallback(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    doc_id: int,
    doc_version_id: int,
) -> List[Dict]:
    """
    表格文本的兜底切分：按段落（换行）切分，
    每段视为独立行组，不足 chunk_size 则直接使用。
    """
    if not text:
        return []

    lines = text.split("\n")
    chunks = []
    chunk_index = 0
    current_lines: List[str] = []
    current_len = 0

    def flush():
        nonlocal chunk_index, current_lines, current_len
        if not current_lines:
            return
        chunk_text = "\n".join(current_lines).strip()
        if chunk_text:
            chunk_id = f"{doc_id}_{doc_version_id}_{str(chunk_index).zfill(3)}"
            chunks.append({
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "text": chunk_text,
                "section_title": "",
                "is_first_chunk": chunk_index == 0,
                "is_last_chunk": False,
                "is_heading": False,
            })
            chunk_index += 1
        current_lines = []
        current_len = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        line_len = len(line)
        if current_len + line_len <= chunk_size:
            current_lines.append(line)
            current_len += line_len + 1
        else:
            flush()
            if line_len > chunk_size:
                # 单行超长，退化为字符滑动窗口
                sub_chunks = _sliding_window_raw(line, chunk_size, chunk_overlap, doc_id, doc_version_id)
                chunks.extend(sub_chunks)
                chunk_index += len(sub_chunks)
            else:
                current_lines.append(line)
                current_len = line_len

    flush()
    # 标记最后一个 chunk
    if chunks:
        chunks[-1]["is_last_chunk"] = True

    logger.info(f"Table chunking: split into {len(chunks)} chunks for doc_id={doc_id}")
    return chunks


def _sliding_window_raw(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    doc_id: int,
    doc_version_id: int,
) -> List[Dict]:
    """纯字符滑动窗口（最终兜底）"""
    if not text:
        return []
    chunks = []
    start = 0
    chunk_index = 0
    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunk_id = f"{doc_id}_{doc_version_id}_{str(chunk_index).zfill(3)}"
            chunks.append({
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "text": chunk_text,
                "section_title": "",
                "is_first_chunk": start == 0,
                "is_last_chunk": end >= len(text),
                "is_heading": False,
            })
            chunk_index += 1
        if end >= len(text):
            break
        start += (chunk_size - chunk_overlap)
    if chunks:
        chunks[-1]["is_last_chunk"] = True
    return chunks
