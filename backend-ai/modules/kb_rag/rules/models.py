"""
规则数据模型

RuleAnswer: 规则回答（管理员配置标准答案）
RejectionRule: 拒绝规则（无关/恶意问题拦截）
RejectionLog: 拒绝命中日志（审计用）
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class MatchType(str, Enum):
    KEYWORD = "keyword"       # 关键词包含匹配
    REGEX = "regex"           # 正则表达式匹配
    EXACT = "exact"           # 完全精确匹配


class RuleAnswerRequest(BaseModel):
    """规则回答 - 创建/更新请求"""
    match_type: MatchType = Field(default=MatchType.KEYWORD, description="匹配方式")
    pattern: str = Field(..., min_length=1, max_length=200, description="匹配模式")
    answer: str = Field(..., min_length=1, max_length=2000, description="标准回答")
    priority: int = Field(default=0, ge=0, le=100, description="优先级，数值越大越先匹配")
    enabled: bool = Field(default=True, description="是否启用")


class RuleAnswer(BaseModel):
    """规则回答"""
    rule_id: int = 0
    match_type: MatchType
    pattern: str
    answer: str
    priority: int = 0
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RejectionRuleRequest(BaseModel):
    """拒绝规则 - 创建/更新请求"""
    match_type: MatchType = Field(default=MatchType.KEYWORD, description="匹配方式")
    pattern: str = Field(..., min_length=1, max_length=200, description="匹配模式")
    reject_reason: str = Field(..., min_length=1, max_length=500, description="拒绝说明，返回给用户")
    log_only: bool = Field(default=False, description="True=仅记录不拒绝，False=拒绝并返回")
    enabled: bool = Field(default=True, description="是否启用")


class RejectionRule(BaseModel):
    """拒绝规则"""
    rule_id: int = 0
    match_type: MatchType
    pattern: str
    reject_reason: str
    log_only: bool = False
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RejectionLog(BaseModel):
    """拒绝命中日志"""
    log_id: int = 0
    rule_id: int
    rule_pattern: str
    user_question: str
    action: str  # "rejected" 或 "logged"
    conversation_id: Optional[int] = None
    created_at: Optional[datetime] = None


class RuleAnswerResponse(BaseModel):
    """规则回答 - 列表项"""
    rule_id: int
    match_type: str
    pattern: str
    answer: str
    priority: int
    enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RejectionRuleResponse(BaseModel):
    """拒绝规则 - 列表项"""
    rule_id: int
    match_type: str
    pattern: str
    reject_reason: str
    log_only: bool
    enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RejectionLogResponse(BaseModel):
    """拒绝日志 - 列表项"""
    log_id: int
    rule_id: int
    rule_pattern: str
    user_question: str
    action: str
    conversation_id: Optional[int] = None
    created_at: Optional[str] = None


# ===== 敏感词管理 =====

class SensitiveWordRequest(BaseModel):
    """敏感词 - 创建请求"""
    word: str = Field(..., min_length=1, max_length=100, description="敏感词")
    enabled: bool = Field(default=True, description="是否启用")


class SensitiveWord(BaseModel):
    """敏感词"""
    word_id: int = 0
    word: str
    enabled: bool = True
    created_at: Optional[datetime] = None


class SensitiveWordResponse(BaseModel):
    """敏感词 - 列表项"""
    word_id: int
    word: str
    enabled: bool
    created_at: Optional[str] = None


# ===== 模型配置 =====

class ModelConfigRequest(BaseModel):
    """模型配置 - 更新请求"""
    config_value: str = Field(..., min_length=1, max_length=500, description="配置值")


class ModelConfig(BaseModel):
    """模型配置"""
    config_id: int = 0
    config_key: str
    config_value: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None


class ModelConfigResponse(BaseModel):
    """模型配置 - 列表项"""
    config_id: int
    config_key: str
    config_value: str
    description: Optional[str] = None
    updated_at: Optional[str] = None
