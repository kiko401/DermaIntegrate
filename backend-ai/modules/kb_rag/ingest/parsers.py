"""
文档解析器

支持 PDF、DOCX、CSV/Excel、TXT/MD 的文本提取。
为每个文档块附带丰富的结构化元数据（页码、段落标题、表格信息），
供下游切分和检索质量提升使用。
"""
import io
import logging
import re
from typing import Optional, List, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)


# ===== PDF 解析 =====

def _parse_pdf(content: bytes) -> List[Dict[str, Any]]:
    """
    解析 PDF，返回每页文本及页码元数据。
    返回: List[{"page_number": int, "text": str, "is_heading": bool, "section_title": str}]
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            # 清理空白
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                pages.append({
                    "page_number": page_num,
                    "text": text,
                    "is_heading": False,
                    "section_title": "",
                })
        return pages
    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        return []


def _detect_pdf_headings(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对 PDF 页面文本做标题检测：
    - 短行（<= 40字符）且居中或字号大的行 → 视为标题
    - 出现频率高的短行 → 章节标题
    """
    if not pages:
        return pages

    # 统计短行出现次数（可能是章节重复出现的标题）
    line_freq: Dict[str, int] = {}
    all_short_lines: List[tuple[int, str]] = []  # (page_index, line)

    for pi, page in enumerate(pages):
        for line in page["text"].split("\n"):
            line = line.strip()
            if 3 <= len(line) <= 40 and not line[-1] in "。！？；,":
                line_freq[line] = line_freq.get(line, 0) + 1
                all_short_lines.append((pi, line))

    # 出现 >= 2 次的短行视为章节标题
    chapter_titles = {line for line, cnt in line_freq.items() if cnt >= 2}

    # 为每页标记标题
    current_section = ""
    for page in pages:
        for line in page["text"].split("\n"):
            line = line.strip()
            if line in chapter_titles:
                current_section = line
                break
        page["section_title"] = current_section
        page["is_heading"] = any(
            line.strip() in chapter_titles for line in page["text"].split("\n")
        )

    return pages


def _extract_pdf_pages_with_metadata(content: bytes) -> List[Dict[str, Any]]:
    """PDF 解析入口，返回带元数据的页面列表"""
    pages = _parse_pdf(content)
    if not pages:
        return []
    return _detect_pdf_headings(pages)


# ===== DOCX 解析 =====

def _parse_docx_with_metadata(content: bytes) -> List[Dict[str, Any]]:
    """
    解析 DOCX，保留段落样式（标题/正文）信息。
    返回: List[{"text": str, "is_heading": bool, "heading_level": int, "section_title": str}]
    """
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))
        paragraphs = []
        current_heading = ""

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # 检测是否为标题
            style_name = para.style.name.lower() if para.style else ""
            is_heading = False
            heading_level = 0

            if "heading" in style_name or "title" in style_name or "caption" in style_name:
                is_heading = True
                # 提取标题级别
                match = re.search(r"Heading\s*(\d+)", style_name, re.IGNORECASE)
                if match:
                    heading_level = int(match.group(1))
                current_heading = text

            paragraphs.append({
                "text": text,
                "is_heading": is_heading,
                "heading_level": heading_level,
                "section_title": current_heading,
            })

        return paragraphs
    except Exception as e:
        logger.error(f"Failed to parse DOCX: {e}")
        return []


# ===== CSV/Excel 解析 =====

def _smart_row_to_text(row_dict: dict, row_index: int, columns: list) -> str:
    """将单行数据转换为自然语言描述。"""
    parts = []

    if all(pd.isna(v) for v in row_dict.values()):
        return ""

    for col in columns:
        val = row_dict.get(col)
        if pd.isna(val):
            continue
        val_str = str(val).strip()

        if isinstance(val, (int, float)):
            parts.append(f"{col}为{val_str}")
        elif isinstance(val, bool):
            parts.append(f"{col}为{'是' if val else '否'}")
        else:
            parts.append(f"{col}为{val_str}")

    if not parts:
        return ""

    row_num = row_index + 1
    if len(parts) == 1:
        return f"第{row_num}条记录：{parts[0]}。"
    elif len(parts) <= 3:
        return f"第{row_num}条记录：{'，'.join(parts[:-1])}，{parts[-1]}。"
    else:
        return f"第{row_num}条记录：{'，'.join(parts)}。"


def _summarize_table(df: pd.DataFrame) -> str:
    """生成表格摘要：行列数、数值列统计、文本列分布。"""
    summary_parts = []

    total_rows = len(df)
    total_cols = len(df.columns)
    summary_parts.append(f"本表格共{total_rows}条记录，{total_cols}个字段。")

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    for col in numeric_cols[:5]:
        col_data = df[col].dropna()
        if len(col_data) == 0:
            continue
        col_min = col_data.min()
        col_max = col_data.max()
        col_mean = col_data.mean()
        if col_min == col_max:
            summary_parts.append(f"字段【{col}】全部为{col_min}。")
        else:
            summary_parts.append(
                f"字段【{col}】范围为{col_min}至{col_max}，均值为{col_mean:.2f}。"
            )

    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    for col in categorical_cols[:3]:
        col_data = df[col].dropna().astype(str)
        unique_vals = col_data.unique()
        if 1 < len(unique_vals) <= 10:
            summary_parts.append(
                f"字段【{col}】包含：{'、'.join(str(v) for v in unique_vals[:8])}等{len(unique_vals)}种取值。"
            )

    return " ".join(summary_parts)


def _parse_csv_excel_with_metadata(content: bytes, filename: str) -> Dict[str, Any]:
    """
    解析 CSV/Excel，返回文本内容和表格元数据。
    返回: {"text": str, "table_meta": dict}
    """
    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        if df.empty:
            return {"text": "", "table_meta": None}

        columns = df.columns.tolist()

        lines = []
        for idx, row in df.iterrows():
            row_text = _smart_row_to_text(row.to_dict(), idx, columns)
            if row_text:
                lines.append(row_text)

        summary = _summarize_table(df)
        if summary:
            lines.append(summary)

        table_meta = {
            "columns": columns,
            "row_count": len(df),
            "column_count": len(columns),
            "numeric_columns": df.select_dtypes(include=["number"]).columns.tolist(),
            "text_columns": df.select_dtypes(include=["object", "category"]).columns.tolist(),
        }

        return {
            "text": "\n".join(lines),
            "table_meta": table_meta,
        }

    except Exception as e:
        logger.error(f"Failed to parse CSV/Excel: {e}")
        return {"text": "", "table_meta": None}


# ===== TXT/MD 解析 =====

def _parse_txt_with_metadata(content: bytes) -> List[Dict[str, Any]]:
    """
    解析 TXT/MD，返回段落列表及标题检测结果。
    返回: List[{"text": str, "is_heading": bool, "section_title": str}]
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("gbk", errors="ignore")

    paragraphs = []
    current_section = ""

    # 按段落分割
    raw_paragraphs = text.split("\n\n")

    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue

        # 跳过单行标题类内容（通常与下一段合并）
        if len(para) <= 40 and re.match(r"^(#{1,3}\s|[0-9]+[\.、章节]|#)", para.strip()):
            current_section = para.strip().lstrip("#").strip()
            continue

        is_heading = bool(re.match(r"^#{1,3}\s", para.strip()))
        if is_heading:
            current_section = para.strip().lstrip("#").strip()

        paragraphs.append({
            "text": para,
            "is_heading": is_heading,
            "section_title": current_section,
        })

    return paragraphs


# ===== 统一解析入口 =====

def extract_text_with_metadata(content: bytes, filename: str) -> Dict[str, Any]:
    """
    带元数据的解析入口。

    返回:
    {
        "text": str,           # 合并后的纯文本（供切分用）
        "blocks": List[Dict],  # 分块信息（block_text, page_number, section_title, is_table）
        "file_meta": Dict,     # 文件级元数据
    }

    block 格式（统一抽象）：
    {
        "text": str,
        "page_number": int | None,   # PDF 页码；其他格式为 None
        "section_title": str,         # 当前章节标题
        "is_heading": bool,           # 是否为标题段落
        "is_table": bool,             # 是否为表格内容
        "table_meta": dict | None,    # 表格元数据（is_table=True 时）
    }
    """
    ext = filename.split(".")[-1].lower()

    # 文件级元数据
    file_meta = {
        "filename": filename,
        "file_type": ext,
        "source": f"{filename}（{ext.upper()}文档）",
    }

    # ----- PDF -----
    if ext == "pdf":
        pages = _extract_pdf_pages_with_metadata(content)
        blocks = []
        for page in pages:
            blocks.append({
                "text": page["text"],
                "page_number": page["page_number"],
                "section_title": page["section_title"],
                "is_heading": page["is_heading"],
                "is_table": False,
                "table_meta": None,
            })
        file_meta["total_pages"] = len(pages)
        return {
            "text": "\n\n".join(p["text"] for p in pages),
            "blocks": blocks,
            "file_meta": file_meta,
        }

    # ----- DOCX -----
    if ext == "docx":
        paragraphs = _parse_docx_with_metadata(content)
        blocks = []
        for para in paragraphs:
            blocks.append({
                "text": para["text"],
                "page_number": None,
                "section_title": para["section_title"],
                "is_heading": para["is_heading"],
                "is_table": False,
                "table_meta": None,
            })
        file_meta["total_paragraphs"] = len(paragraphs)
        return {
            "text": "\n\n".join(p["text"] for p in paragraphs),
            "blocks": blocks,
            "file_meta": file_meta,
        }

    # ----- CSV/Excel -----
    if ext in ["csv", "xlsx", "xls"]:
        result = _parse_csv_excel_with_metadata(content, filename)
        blocks = [{
            "text": result["text"],
            "page_number": None,
            "section_title": "",
            "is_heading": False,
            "is_table": True,
            "table_meta": result["table_meta"],
        }]
        file_meta["row_count"] = result["table_meta"].get("row_count", 0) if result["table_meta"] else 0
        file_meta["column_count"] = result["table_meta"].get("column_count", 0) if result["table_meta"] else 0
        return {
            "text": result["text"],
            "blocks": blocks,
            "file_meta": file_meta,
        }

    # ----- TXT/MD -----
    if ext in ["txt", "md"]:
        paragraphs = _parse_txt_with_metadata(content)
        blocks = []
        for para in paragraphs:
            blocks.append({
                "text": para["text"],
                "page_number": None,
                "section_title": para["section_title"],
                "is_heading": para["is_heading"],
                "is_table": False,
                "table_meta": None,
            })
        return {
            "text": "\n\n".join(p["text"] for p in paragraphs),
            "blocks": blocks,
            "file_meta": file_meta,
        }

    # ----- 兜底 -----
    logger.warning(f"Unsupported file format: {ext}, using raw text decode.")
    try:
        raw_text = content.decode("utf-8", errors="ignore")
    except:
        raw_text = ""
    return {
        "text": raw_text,
        "blocks": [{"text": raw_text, "page_number": None, "section_title": "", "is_heading": False, "is_table": False, "table_meta": None}],
        "file_meta": file_meta,
    }
