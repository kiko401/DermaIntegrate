"""
文档解析器

支持 PDF、DOCX、CSV/Excel、TXT/MD 的文本提取。
CSV/Excel 使用智能行转文本，生成自然语言结构化描述。
"""
import io
import logging
import re
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _parse_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        return ""


def _parse_docx(content: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        logger.error(f"Failed to parse DOCX: {e}")
        return ""


def _smart_row_to_text(row_dict: dict, row_index: int, columns: list) -> str:
    """
    将单行数据转换为自然语言描述。

    Args:
        row_dict: {列名: 值} 字典
        row_index: 行号（从0开始）
        columns: 列名列表（保持顺序）
    """
    parts = []

    # 跳过全空值行
    if all(pd.isna(v) for v in row_dict.values()):
        return ""

    for col in columns:
        val = row_dict.get(col)
        if pd.isna(val):
            continue
        val_str = str(val).strip()

        # 数值类列：直接用值
        if isinstance(val, (int, float)):
            parts.append(f"{col}为{val_str}")
        # 布尔类
        elif isinstance(val, bool):
            parts.append(f"{col}为{'是' if val else '否'}")
        # 文本类列：引用格式
        else:
            parts.append(f"{col}为{val_str}")

    if not parts:
        return ""

    # 组合成句
    row_num = row_index + 1
    if len(parts) == 1:
        return f"第{row_num}条记录：{parts[0]}。"
    elif len(parts) <= 3:
        return f"第{row_num}条记录：{'，'.join(parts[:-1])}，{parts[-1]}。"
    else:
        return f"第{row_num}条记录：{'，'.join(parts)}。"


def _summarize_table(df: pd.DataFrame) -> str:
    """
    生成表格摘要：行列数、数值列统计、文本列分布。
    用于在完整行描述之后追加全局概览，提升检索匹配率。
    """
    summary_parts = []

    total_rows = len(df)
    total_cols = len(df.columns)
    summary_parts.append(f"本表格共{total_rows}条记录，{total_cols}个字段。")

    # 数值列统计（最多5列）
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
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

    # 分类型列（枚举种类，最多种）
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
    for col in categorical_cols[:3]:
        col_data = df[col].dropna().astype(str)
        unique_vals = col_data.unique()
        if 1 < len(unique_vals) <= 10:
            summary_parts.append(
                f"字段【{col}】包含：{'、'.join(str(v) for v in unique_vals[:8])}等{len(unique_vals)}种取值。"
            )

    return " ".join(summary_parts)


def _parse_csv_excel(content: bytes, filename: str) -> str:
    """
    智能解析 CSV/Excel：将表格转换为自然语言结构化描述。

    相比简单的 'col: val' 格式，生成：
    - 每行一条自然语言描述（第N条记录：字段1为X，字段2为Y）
    - 表格级别的数值统计摘要
    - 最大保留原始列名，供下游切分和检索使用
    """
    try:
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        if df.empty:
            return ""

        columns = df.columns.tolist()

        # 逐行转换为自然语言
        lines = []
        for idx, row in df.iterrows():
            row_text = _smart_row_to_text(row.to_dict(), idx, columns)
            if row_text:
                lines.append(row_text)

        # 添加表格摘要
        if lines:
            summary = _summarize_table(df)
            lines.append(summary)

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Failed to parse CSV/Excel: {e}")
        return ""


def extract_text_from_file(content: bytes, filename: str) -> str:
    """根据文件扩展名调用对应的解析器"""
    ext = filename.split('.')[-1].lower()
    if ext == 'pdf':
        return _parse_pdf(content)
    elif ext == 'docx':
        return _parse_docx(content)
    elif ext in ['csv', 'xlsx', 'xls']:
        return _parse_csv_excel(content, filename)
    elif ext in ['txt', 'md']:
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            return content.decode('gbk', errors='ignore')
    else:
        logger.warning(f"Unsupported file format: {ext}")
        try:
            return content.decode('utf-8', errors='ignore')
        except:
            return ""
