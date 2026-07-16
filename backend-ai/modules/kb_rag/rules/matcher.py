"""
规则匹配引擎

match_rule: 单条规则匹配
apply_rule_answers: 批量应用规则回答，返回命中的标准答案或None
apply_rejection_rules: 批量应用拒绝规则，返回拒绝结果或None
"""
import re
import logging
import time
from typing import Optional, List, Dict, Any
from .models import MatchType

logger = logging.getLogger(__name__)

# 内存缓存（服务启动时加载，定期刷新）
_rule_answers_cache: List[dict] = []
_rejection_rules_cache: List[dict] = []
_cache_loaded_at: float = 0.0


def match_rule(question: str, rule: dict) -> bool:
    """
    判断用户问题是否匹配规则

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


def _load_rule_answers() -> List[dict]:
    """从数据库加载规则回答，带内存缓存（5分钟刷新）"""
    global _rule_answers_cache, _cache_loaded_at
    if not _rule_answers_cache or (time.monotonic() - _cache_loaded_at) > 300:
        try:
            from .store import get_rule_answers
            _rule_answers_cache = get_rule_answers(enabled_only=True)
            _cache_loaded_at = time.monotonic()
            logger.info(f"Loaded {len(_rule_answers_cache)} rule answers into cache.")
        except Exception as e:
            logger.warning(f"Failed to load rule answers cache: {e}. Using stale cache if available.")
    return _rule_answers_cache


def _load_rejection_rules() -> List[dict]:
    """从数据库加载拒绝规则，带内存缓存（5分钟刷新）"""
    global _rejection_rules_cache, _cache_loaded_at
    if not _rejection_rules_cache or (time.monotonic() - _cache_loaded_at) > 300:
        try:
            from .store import get_rejection_rules
            _rejection_rules_cache = get_rejection_rules(enabled_only=True)
            _cache_loaded_at = time.monotonic()
            logger.info(f"Loaded {len(_rejection_rules_cache)} rejection rules into cache.")
        except Exception as e:
            logger.warning(f"Failed to load rejection rules cache: {e}. Using stale cache if available.")
    return _rejection_rules_cache


def invalidate_cache():
    """手动失效缓存，下次访问自动重新加载"""
    global _rule_answers_cache, _rejection_rules_cache, _cache_loaded_at
    _rule_answers_cache = []
    _rejection_rules_cache = []
    _cache_loaded_at = 0.0


class RuleMatchResult:
    """规则匹配结果"""

    def __init__(self):
        self.matched: bool = False
        self.rule_id: int = 0
        self.answer: str = ""
        self.reject_reason: str = ""
        self.log_only: bool = False
        self.rule_pattern: str = ""


def apply_rule_answers(question: str) -> Optional[RuleMatchResult]:
    """
    应用规则回答，返回匹配结果或None

    按priority降序遍历，一旦命中立即返回（取最高优先级）
    """
    rules = _load_rule_answers()
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


def apply_rejection_rules(question: str) -> Optional[RuleMatchResult]:
    """
    应用拒绝规则，返回匹配结果或None（log_only规则不阻断）

    注意：log_only=True的规则不阻断流程，仅记录日志
    """
    rules = _load_rejection_rules()
    for rule in rules:
        if match_rule(question, rule):
            result = RuleMatchResult()
            result.matched = True
            result.rule_id = rule.get("rule_id", 0)
            result.rule_pattern = rule.get("pattern", "")
            result.reject_reason = rule.get("reject_reason", "")
            result.log_only = rule.get("log_only", 0) == 1 or rule.get("log_only") is True
            logger.info(f"Rejection rule matched: rule_id={result.rule_id}, log_only={result.log_only}")
            return result
    return None
