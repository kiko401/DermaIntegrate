"""
规则匹配引擎

match_rule: 单条规则匹配
apply_rule_answers: 批量应用规则回答，返回命中的标准答案或None
apply_rejection_rules: 批量应用拒绝规则，返回拒绝结果或None

所有 DB 操作均为异步（直接 await store 函数）。
"""
import re
import logging
import time
import threading
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# 缓存 TTL（从 shared/config 统一读取）
from shared.config import RULE_ANSWER_CACHE_TTL as _RULE_CACHE_TTL
from shared.config import REJECTION_RULE_CACHE_TTL as _REJECTION_CACHE_TTL


class _RuleCache:
    """
    线程安全的规则缓存

    使用 threading.RLock() 替代 asyncio.Lock()，
    可在同步/异步上下文中正确工作。
    """
    __slots__ = ('data', 'loaded_at', 'ttl')

    def __init__(self, ttl: float = 300.0):
        self.data: List[dict] = []
        self.loaded_at: float = 0.0
        self.ttl: float = ttl

    def is_expired(self) -> bool:
        """检查缓存是否过期"""
        return (time.monotonic() - self.loaded_at) > self.ttl

    def is_valid(self) -> bool:
        """检查缓存是否有效（非空且未过期）"""
        return bool(self.data) and not self.is_expired()

    def update(self, data: List[dict]):
        """更新缓存数据（线程安全）"""
        self.data = data
        self.loaded_at = time.monotonic()

    def clear(self):
        """清空缓存"""
        self.data = []
        self.loaded_at = 0.0


# 全局缓存实例
_rule_answers_cache = _RuleCache(ttl=_RULE_CACHE_TTL)
_rejection_rules_cache = _RuleCache(ttl=_REJECTION_CACHE_TTL)

# 线程锁（用于保护缓存更新操作，可重入）
_cache_write_lock = threading.RLock()


def match_rule(question: str, rule: dict) -> bool:
    """
    判断用户问题是否匹配规则（纯同步函数）

    注意：此函数是纯同步的，不涉及锁操作。
    缓存更新由调用方在合适的异步上下文中处理。

    Args:
        question: 用户问题
        rule: 规则字典，包含 match_type 和 pattern

    Returns:
        bool: 是否匹配
    """
    match_type = rule.get("match_type", "keyword")
    pattern = rule.get("pattern", "")

    if not pattern:
        return False

    try:
        if match_type == "exact":
            return question.strip() == pattern
        elif match_type == "keyword":
            return pattern in question
        elif match_type == "regex":
            return bool(re.search(pattern, question, re.IGNORECASE))
    except re.error as e:
        logger.warning(f"Regex error in rule {rule.get('rule_id')}: {e}")
        return False
    return False


async def _load_rule_answers() -> List[dict]:
    """
    从数据库异步加载规则回答

    使用双重检查锁定模式：
    1. 首次检查（不加锁）：快速判断是否需要加载
    2. 加锁后二次检查：防止并发刷新
    """
    global _rule_answers_cache

    # 首次检查：缓存有效则直接返回（读操作不加锁）
    if _rule_answers_cache.is_valid():
        return _rule_answers_cache.data

    # 获取锁后进行二次检查
    with _cache_write_lock:
        # 二次检查：其他协程可能已经刷新了缓存
        if _rule_answers_cache.is_valid():
            return _rule_answers_cache.data

        try:
            from .store import get_rule_answers
            data = await get_rule_answers(enabled_only=True)
            _rule_answers_cache.update(data)
            logger.info(f"Loaded {len(data)} rule answers into cache (TTL={_RULE_CACHE_TTL}s).")
            return data
        except Exception as e:
            logger.warning(f"Failed to load rule answers cache: {e}. Using stale cache if available.")
            # 返回过期缓存作为降级（即使过期也不丢弃）
            if _rule_answers_cache.data:
                return _rule_answers_cache.data
            return []


async def _load_rejection_rules() -> List[dict]:
    """
    从数据库异步加载拒绝规则

    使用双重检查锁定模式（同上）
    """
    global _rejection_rules_cache

    # 首次检查：缓存有效则直接返回
    if _rejection_rules_cache.is_valid():
        return _rejection_rules_cache.data

    # 获取锁后进行二次检查
    with _cache_write_lock:
        # 二次检查
        if _rejection_rules_cache.is_valid():
            return _rejection_rules_cache.data

        try:
            from .store import get_rejection_rules
            data = await get_rejection_rules(enabled_only=True)
            _rejection_rules_cache.update(data)
            logger.info(f"Loaded {len(data)} rejection rules into cache (TTL={_REJECTION_CACHE_TTL}s).")
            return data
        except Exception as e:
            logger.warning(f"Failed to load rejection rules cache: {e}. Using stale cache if available.")
            if _rejection_rules_cache.data:
                return _rejection_rules_cache.data
            return []


def invalidate_cache():
    """
    手动失效缓存（写操作，需要锁）

    供 admin_routes.py 的 CRUD 操作调用
    """
    global _rule_answers_cache, _rejection_rules_cache
    with _cache_write_lock:
        _rule_answers_cache.clear()
        _rejection_rules_cache.clear()
    logger.info("Rule caches invalidated.")


class RuleMatchResult:
    """规则匹配结果"""

    __slots__ = ('matched', 'rule_id', 'answer', 'reject_reason', 'log_only', 'rule_pattern')

    def __init__(self):
        self.matched: bool = False
        self.rule_id: int = 0
        self.answer: str = ""
        self.reject_reason: str = ""
        self.log_only: bool = False
        self.rule_pattern: str = ""


async def apply_rule_answers(question: str) -> Optional[RuleMatchResult]:
    """
    应用规则回答，返回匹配结果或None

    按priority降序遍历，一旦命中立即返回（取最高优先级）
    """
    rules = await _load_rule_answers()
    for rule in rules:
        if match_rule(question, rule):
            result = RuleMatchResult()
            result.matched = True
            result.rule_id = rule.get("rule_id", 0)
            result.rule_pattern = rule.get("pattern", "")
            result.answer = rule.get("answer", "")
            logger.info(f"Rule answer matched: rule_id={result.rule_id}, pattern={result.rule_pattern}")
            return result
    return None


async def apply_rejection_rules(question: str) -> Optional[RuleMatchResult]:
    """
    应用拒绝规则，返回匹配结果或None（log_only规则不阻断）

    注意：log_only=True的规则不阻断流程，仅记录日志
    """
    rules = await _load_rejection_rules()
    for rule in rules:
        if match_rule(question, rule):
            result = RuleMatchResult()
            result.matched = True
            result.rule_id = rule.get("rule_id", 0)
            result.rule_pattern = rule.get("pattern", "")
            result.reject_reason = rule.get("reject_reason", "")
            result.log_only = rule.get("log_only", 0) == 1
            logger.info(f"Rejection rule matched: rule_id={result.rule_id}, log_only={result.log_only}")
            return result
    return None
