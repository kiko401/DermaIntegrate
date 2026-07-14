import io
import logging
from typing import Optional

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


def _parse_csv_excel(content: bytes, filename: str) -> str:
    try:
        import pandas as pd
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        # 将每一行转换为文本
        text_lines = []
        for _, row in df.iterrows():
            row_text = ", ".join([f"{col}: {val}" for col, val in row.items() if pd.notna(val)])
            text_lines.append(row_text)
        return "\n".join(text_lines)
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