import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def split_text(text: str, chunk_size: int, chunk_overlap: int, doc_id: int, doc_version_id: int) -> List[Dict]:
    """
    滑动窗口切分文本。
    强制生成 chunk_id 格式: {doc_id}_{doc_version_id}_{chunk_index(补零三位)}

    M-13: chunk_overlap >= chunk_size 时自动修正为 chunk_size // 2
    """
    if not text:
        return []

    # M-13: 防止步进 <= 0 导致无限循环
    if chunk_overlap >= chunk_size:
        logger.warning(f"chunk_overlap ({chunk_overlap}) >= chunk_size ({chunk_size}), auto-correcting to {chunk_size // 2}")
        chunk_overlap = chunk_size // 2

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end]

        if chunk_text.strip():
            # 强制规范：chunk_id 补零至三位
            chunk_id = f"{doc_id}_{doc_version_id}_{str(chunk_index).zfill(3)}"

            chunks.append({
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "text": chunk_text
            })
            chunk_index += 1

        # 移动窗口
        if end >= len(text):
            break
        start += (chunk_size - chunk_overlap)

    logger.info(f"Split text into {len(chunks)} chunks for doc_id={doc_id}.")
    return chunks