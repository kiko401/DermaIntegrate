import re
import json
import uuid
import logging

import jieba

jieba.setLogLevel(logging.WARNING)  # 减少日志噪音

logger = logging.getLogger(__name__)


# ========== PHI 二次检测常量 ==========
# 用于检测用户输入和患者上下文中是否包含患者敏感信息
# 应用域已做脱敏处理，此处为二次兜底检测

PHI_PATTERNS = [
    (r"姓名[：:]\s*[^\s，,。]+", "patient_name"),
    (r"住院号[：:]\s*[A-Z0-9]{6,}", "hospitalization_id"),
    (r"身份证号[：:]\s*\d{15,18}", "id_card"),
    (r"手机号[：:]\s*\d{11}", "phone"),
    (r"地址[：:]\s*[^\s，,。]{5,}", "address"),
]


def detect_phi(text: str) -> list:
    """检测文本中是否包含 PHI 模式，返回匹配列表。"""
    detected = []
    for pattern, phi_type in PHI_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            detected.append({"type": phi_type, "matches": matches})
    return detected


def mask_phi(text: str) -> str:
    """
    对文本中的 PHI 进行脱敏替换。

    使用从后往前的替换顺序，避免先替换短模式（如"姓名"）
    导致长模式（如"姓名：张三"）中匹配范围错位。
    按匹配起始位置倒序排列，确保每次替换不影响后续位置。
    """
    # 收集所有匹配：(起始位置, 结束位置, 匹配文本, phi类型)
    all_matches = []
    for pattern, phi_type in PHI_PATTERNS:
        for m in re.finditer(pattern, text):
            all_matches.append((m.start(), m.end(), m.group(), phi_type))

    if not all_matches:
        return text

    # 按起始位置从后往前排序
    all_matches.sort(key=lambda x: x[0], reverse=True)

    # 逐个替换（从后往前不影响前面位置）
    for start, end, matched_text, phi_type in all_matches:
        text = text[:start] + f"[{phi_type}]" + text[end:]

    return text


# ========== 共享分词器 ==========

def tokenize(text: str) -> list:
    """
    中文/英文混合分词器（供检索和 Rerank 共用）。

    - 中文：基于 jieba 词组分词（精确模式）
    - 英文：按空格/符号切分，转小写
    - 其他字符：跳过
    """
    if not text:
        return []
    tokens = []
    for word in jieba.cut(text, cut_all=False):
        word = word.strip()
        if not word:
            continue
        # 英文词转小写，数字/标点丢弃
        if re.match(r'^[a-zA-Z]+$', word):
            tokens.append(word.lower())
        elif re.match(r'^\d+$', word):
            pass  # 纯数字不加入 token（减少噪音）
        elif re.match(r'^[\u4e00-\u9fff]+$', word):
            tokens.append(word)  # 保留完整中文词
        else:
            # 混合词（如 "PD-1"）拆解
            sub = re.findall(r'[a-zA-Z]+|\d+|[^\da-zA-Z\u4e00-\u9fff]+', word)
            for s in sub:
                s = s.strip()
                if s and re.match(r'^[a-zA-Z]+$', s):
                    tokens.append(s.lower())
                elif s and re.match(r'^[\u4e00-\u9fff]+$', s):
                    tokens.append(s)
    return tokens


# ========== 工具函数 ==========

def generate_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:12]}"


def generate_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def extract_json_from_text(text: str) -> dict:
    """从 LLM 输出（可能含 Markdown 代码块）中提取 JSON 字典。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to extract JSON from text: {text[:100]}...")
    return {}


def truncate_text(text: str, max_chars: int = 4000) -> str:
    """截断文本以防止超出 LLM 上下文限制。"""
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[已截断]"
    return text
