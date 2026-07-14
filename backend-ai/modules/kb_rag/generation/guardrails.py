import os
import re
import logging
from typing import List, Tuple
from ..schemas import RiskHighlightObject

logger = logging.getLogger(__name__)

# 敏感词库
_SENSITIVE_WORDS = []
_ASSET_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "sensitive_words.txt")
if os.path.exists(_ASSET_PATH):
    with open(_ASSET_PATH, "r", encoding="utf-8") as f:
        _SENSITIVE_WORDS = [line.strip() for line in f if line.strip()]

# 风险高亮正则规则
_RISK_PATTERNS = [
    (r"(阿司匹林|布洛芬|头孢|青霉素|干扰素|甲氨蝶呤|环磷酰胺|达卡巴嗪)", "drug"),
    (r"(\d+(\.\d+)?\s*(mg|g|ml|IU|万U|微克))", "dose"),
    (r"(禁忌|孕妇禁用|肝肾功能不全者慎用|过敏者禁用)", "contraindication"),
    (r"(Breslow\s*[>=]?\s*\d+(\.\d+)?\s*mm|T[1-4][a-b]?|阈值>\d+)", "threshold"),
    (r"(溃疡形成|核分裂像增多|淋巴结转移|复发风险高|侵袭性强)", "risk_factor")
]


def check_input(text: str) -> Tuple[bool, List[str]]:
    """检查输入是否包含敏感词。"""
    hits = [w for w in _SENSITIVE_WORDS if w in text]
    return len(hits) == 0, hits


def mask_output(text: str) -> str:
    """输出脱敏：敏感词替换为 ***。"""
    for w in _SENSITIVE_WORDS:
        text = text.replace(w, "***")
    return text


def extract_risk_highlights(text: str) -> List[RiskHighlightObject]:
    """从生成文本中抽取风险高亮实体（药名、剂量、禁忌症、阈值、风险因素）。"""
    highlights = []
    for pattern, category in _RISK_PATTERNS:
        for match in re.finditer(pattern, text):
            highlights.append(RiskHighlightObject(
                label=match.group(1),
                text=match.group(0),
                category=category,
                start=match.start(),
                end=match.end()
            ))
    return highlights
