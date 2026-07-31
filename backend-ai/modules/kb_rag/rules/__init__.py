"""
KB-RAG 规则模块

提供规则回答配置、拒绝回答策略、敏感词管理与模型配置能力。
"""
from .models import (
    RuleAnswer, RejectionRule, RejectionLog,
    RuleAnswerRequest, RejectionRuleRequest,
    SensitiveWord, SensitiveWordRequest, SensitiveWordResponse,
    ModelConfig, ModelConfigRequest, ModelConfigResponse,
)
from .store import (
    init_rules_table,
    get_rule_answers, get_rejection_rules, get_rejection_logs,
    add_rule_answer, update_rule_answer, delete_rule_answer,
    add_rejection_rule, update_rejection_rule, delete_rejection_rule,
    add_rejection_log,
    get_sensitive_words, add_sensitive_word, update_sensitive_word, delete_sensitive_word,
    get_model_configs, get_model_config, upsert_model_config,
)
from .matcher import match_rule, apply_rule_answers, apply_rejection_rules

__all__ = [
    # models
    "RuleAnswer", "RejectionRule", "RejectionLog",
    "RuleAnswerRequest", "RejectionRuleRequest",
    "SensitiveWord", "SensitiveWordRequest", "SensitiveWordResponse",
    "ModelConfig", "ModelConfigRequest", "ModelConfigResponse",
    # store
    "init_rules_table",
    "get_rule_answers", "get_rejection_rules", "get_rejection_logs",
    "add_rule_answer", "update_rule_answer", "delete_rule_answer",
    "add_rejection_rule", "update_rejection_rule", "delete_rejection_rule",
    "add_rejection_log",
    "get_sensitive_words", "add_sensitive_word", "update_sensitive_word", "delete_sensitive_word",
    "get_model_configs", "get_model_config", "upsert_model_config",
    # matcher
    "match_rule", "apply_rule_answers", "apply_rejection_rules",
]
