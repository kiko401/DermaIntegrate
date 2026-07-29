"""
安全 guardrails：敏感词过滤、输出脱敏、风险高亮提取

架构改进（M-03修复）：
- 使用 shared.event_loop.AsyncExecutor 替代 asyncio.new_event_loop()
- 避免在已有事件循环的线程中创建新循环
"""
import os
import re
import logging
import time
import threading
from typing import List, Tuple, Optional

from shared.config import SENSITIVE_WORD_CACHE_TTL
from ..schemas import RiskHighlightObject

logger = logging.getLogger(__name__)

# ========== 敏感词缓存（MySQL + 5分钟TTL + AC自动机）==========

try:
    import ahocorasick
    _AHOCORASICK_AVAILABLE = True
except ImportError:
    _AHOCORASICK_AVAILABLE = False
    logger.warning("pyahocorasick not installed, sensitive word masking will use regex fallback")


class _SensitiveWordCache:
    """敏感词缓存容器，同时存储词表和 AC 自动机"""
    __slots__ = ('words', 'automaton', 'words_regex')

    def __init__(self):
        self.words: List[str] = []
        self.automaton: Optional[object] = None
        self.words_regex: Optional[re.Pattern] = None


_CACHE: Optional[_SensitiveWordCache] = None
_CACHE_AT: float = 0

# 线程锁（保护缓存更新）
_CACHE_LOCK = threading.RLock()

# 缓存 TTL（从 shared/config 统一读取）
_CACHE_TTL: float = SENSITIVE_WORD_CACHE_TTL


def _build_automaton(words: List[str]):
    """从词表构建 AC 自动机"""
    if not words:
        return None
    automaton = ahocorasick.Automaton(ahocorasick.STORE_INTS)
    for word in words:
        automaton.add_word(word, len(word))
    automaton.make_automaton()
    return automaton


def _build_words_regex(words: List[str]) -> Optional[re.Pattern]:
    """从词表构建正则（fallback 方案）"""
    if not words:
        return None
    # 转义特殊字符，按长度降序排列（优先匹配最长词）
    escaped = [re.escape(w) for w in words]
    escaped.sort(key=len, reverse=True)
    pattern = "|".join(escaped)
    return re.compile(pattern)


def _reload_sensitive_words() -> _SensitiveWordCache:
    """从 MySQL 同步加载启用的敏感词列表，重建缓存。

    使用 shared.event_loop.AsyncExecutor 在独立线程中执行异步协程，
    避免在已有事件循环的线程中创建新循环。
    """
    try:
        from ..rules.store import get_sensitive_words

        async def _fetch():
            return await get_sensitive_words(enabled_only=True)

        # 使用统一的 AsyncExecutor
        from shared.event_loop import get_async_executor
        words = get_async_executor().run_sync(_fetch, timeout=10.0)
        word_list = [w["word"] for w in words]
        logger.info(f"Reloaded {len(word_list)} sensitive words from DB.")
    except TimeoutError:
        logger.warning("Failed to reload sensitive words from DB: timeout, using file fallback.")
        word_list = _load_from_file()
    except Exception as e:
        logger.warning(f"Failed to reload sensitive words from DB: {e}, using file fallback.")
        word_list = _load_from_file()

    cache = _SensitiveWordCache()
    cache.words = word_list
    cache.automaton = _build_automaton(word_list) if _AHOCORASICK_AVAILABLE else None
    cache.words_regex = _build_words_regex(word_list)
    return cache


def _load_from_file() -> List[str]:
    """从文件加载敏感词（启动兜底）"""
    asset_path = os.path.join(os.path.dirname(__file__), "..", "assets", "sensitive_words.txt")
    if os.path.exists(asset_path):
        with open(asset_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []


def _get_cache() -> _SensitiveWordCache:
    """获取敏感词缓存（TTL 5分钟，使用双重检查锁定）"""
    global _CACHE, _CACHE_AT
    now = time.monotonic()

    # 首次检查：缓存有效且未过期（读操作不加锁）
    if _CACHE is not None and (now - _CACHE_AT) <= _CACHE_TTL:
        return _CACHE

    # 获取锁后进行二次检查和更新
    with _CACHE_LOCK:
        # 二次检查：其他线程可能已经刷新了缓存
        if _CACHE is not None and (now - _CACHE_AT) <= _CACHE_TTL:
            return _CACHE

        # 缓存 miss 或过期，重新加载
        _CACHE = _reload_sensitive_words()
        _CACHE_AT = time.monotonic()
        return _CACHE


def invalidate_sensitive_word_cache():
    """写操作后主动失效缓存，下一次 check 触发回源"""
    global _CACHE, _CACHE_AT
    with _CACHE_LOCK:
        _CACHE = None
        _CACHE_AT = 0
    logger.info("Sensitive word cache invalidated.")


def check_input(text: str) -> Tuple[bool, List[str]]:
    """检查输入是否包含敏感词，返回 (是否安全, 命中的敏感词列表)"""
    cache = _get_cache()
    hits: List[str] = []

    if cache.automaton is not None:
        # AC 自动机：一次性多模式匹配
        found_words = set()
        for _, length in cache.automaton.iter(text):
            # 从末尾往前取 length 个字符即为匹配词
            matched = text[_[0] - length + 1:_[0] + 1] if length > 0 else text[_[0]]
            found_words.add(matched)
        hits = list(found_words)
    elif cache.words_regex is not None:
        for m in cache.words_regex.finditer(text):
            hits.append(m.group())
        hits = list(set(hits))

    return len(hits) == 0, hits


def mask_output(text: str) -> str:
    """输出脱敏：使用 AC 自动机一次性检测所有匹配，从后往前替换避免位置偏移"""
    cache = _get_cache()
    if not cache.words:
        return text

    # 收集所有匹配：(起始位置, 结束位置)
    matches: List[Tuple[int, int]] = []

    if cache.automaton is not None:
        # AC 自动机模式
        for end_idx, length in cache.automaton.iter(text):
            start_idx = end_idx - length + 1
            matches.append((start_idx, end_idx))
    elif cache.words_regex is not None:
        for m in cache.words_regex.finditer(text):
            # m.end() 是 exclusive（Python regex 语义），与 AC 自动机的 inclusive end 对齐
            matches.append((m.start(), m.end() - 1))

    if not matches:
        return text

    # 按起始位置从后往前排序（避免替换后位置偏移）
    matches.sort(key=lambda x: x[0], reverse=True)

    for start, end in matches:
        text = text[:start] + "***" + text[end + 1:]

    return text


# ========== 风险高亮正则规则 ==========

_RISK_PATTERNS = [
    (r"(阿司匹林|布洛芬|头孢|青霉素|干扰素|甲氨蝶呤|环磷酰胺|达卡巴嗪)", "drug"),
    (r"(\d+(\.\d+)?\s*(mg|g|ml|IU|万U|微克))", "dose"),
    (r"(禁忌|孕妇禁用|肝肾功能不全者慎用|过敏者禁用)", "contraindication"),
    (r"(Breslow\s*[>=]?\s*\d+(\.\d+)?\s*mm|T[1-4][a-b]?|阈值>\d+)", "threshold"),
    (r"(溃疡形成|核分裂像增多|淋巴结转移|复发风险高|侵袭性强)", "risk_factor")
]


def extract_risk_highlights(text: str) -> List[RiskHighlightObject]:
    """从生成文本中抽取风险高亮实体（药名、剂量、禁忌症、阈值、风险因素）"""
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
