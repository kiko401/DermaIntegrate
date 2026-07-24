"""共享 API 数据模型（主诊断管线）。"""
from typing import List
from pydantic import BaseModel


class KeyConcern(BaseModel):
    item: str
    source_id: str


class Recommendation(BaseModel):
    item: str
    source_id: str


class SSEResultEvent(BaseModel):
    """最终诊断结果结构，与文档1.4 / 1.5定义的 result 事件完全一致。"""
    task_id: str
    risk_level: str
    key_concerns: List[KeyConcern] = []
    recommendations: List[Recommendation] = []
    differential: List[str] = []
    disclaimer: str
    status: str = "complete"
