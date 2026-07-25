"""
规则管理 API

提供规则回答、拒绝策略、敏感词管理、模型配置的增删改查及日志审计接口。

接口列表：
GET/POST/PUT/DELETE  /admin/rules          - 规则回答 CRUD
GET/POST/PUT/DELETE  /admin/rejections     - 拒绝规则 CRUD
GET                   /admin/rejection-logs - 拒绝日志（分页）
GET/POST/PUT/DELETE  /admin/sensitive-words - 敏感词 CRUD
GET/PUT               /admin/model-configs  - 模型配置查询/更新
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..rules.models import (
    RuleAnswerRequest, RejectionRuleRequest,
    RuleAnswerResponse, RejectionRuleResponse, RejectionLogResponse,
    SensitiveWordRequest, SensitiveWordResponse,
    ModelConfigRequest, ModelConfigResponse,
)
from ..rules.store import (
    get_rule_answers, add_rule_answer, update_rule_answer, delete_rule_answer,
    get_rejection_rules, add_rejection_rule, update_rejection_rule, delete_rejection_rule,
    get_rejection_logs,
    get_sensitive_words, add_sensitive_word, update_sensitive_word, delete_sensitive_word,
    get_model_configs, upsert_model_config,
)
from ..rules.matcher import invalidate_cache
from ..generation.guardrails import invalidate_sensitive_word_cache
from ..config import invalidate_model_config_cache
from ..schemas import CloneKbIndexRequest, VectorOptimizeRequest
from ..ingest.vector_store import clone_kb_index_async, vector_optimize_async

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== 规则回答 =====

class RuleAnswerCreateResponse(BaseModel):
    rule_id: int
    message: str = "规则回答创建成功"


class RuleAnswerUpdateResponse(BaseModel):
    message: str = "规则回答更新成功"


class RuleAnswerDeleteResponse(BaseModel):
    message: str = "规则回答删除成功"


@router.get("/admin/rules", response_model=list[RuleAnswerResponse])
async def list_rule_answers(include_disabled: bool = Query(False)):
    """获取所有规则回答"""
    try:
        rules = await get_rule_answers(enabled_only=not include_disabled)
        return [
            RuleAnswerResponse(
                rule_id=r["rule_id"],
                match_type=r["match_type"],
                pattern=r["pattern"],
                answer=r["answer"],
                priority=r["priority"],
                enabled=bool(r["enabled"]),
                created_at=str(r["created_at"]) if r.get("created_at") else None,
                updated_at=str(r["updated_at"]) if r.get("updated_at") else None,
            )
            for r in rules
        ]
    except Exception as e:
        logger.error(f"Failed to list rule answers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/rules", status_code=201, response_model=RuleAnswerCreateResponse)
async def create_rule_answer(req: RuleAnswerRequest):
    """新增规则回答"""
    try:
        rule_id = await add_rule_answer(
            match_type=req.match_type.value,
            pattern=req.pattern,
            answer=req.answer,
            priority=req.priority,
            enabled=req.enabled,
        )
        invalidate_cache()
        return RuleAnswerCreateResponse(rule_id=rule_id)
    except Exception as e:
        logger.error(f"Failed to create rule answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/rules/{rule_id}", response_model=RuleAnswerUpdateResponse)
async def update_rule_answer_endpoint(rule_id: int, req: RuleAnswerRequest):
    """更新规则回答"""
    try:
        updated = await update_rule_answer(
            rule_id=rule_id,
            match_type=req.match_type.value,
            pattern=req.pattern,
            answer=req.answer,
            priority=req.priority,
            enabled=req.enabled,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="规则回答不存在")
        invalidate_cache()
        return RuleAnswerUpdateResponse()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update rule answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/rules/{rule_id}", response_model=RuleAnswerDeleteResponse)
async def delete_rule_answer_endpoint(rule_id: int):
    """删除规则回答"""
    try:
        deleted = await delete_rule_answer(rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="规则回答不存在")
        invalidate_cache()
        return RuleAnswerDeleteResponse()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete rule answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== 拒绝规则 =====

class RejectionRuleCreateResponse(BaseModel):
    rule_id: int
    message: str = "拒绝规则创建成功"


class RejectionRuleUpdateResponse(BaseModel):
    message: str = "拒绝规则更新成功"


class RejectionRuleDeleteResponse(BaseModel):
    message: str = "拒绝规则删除成功"


@router.get("/admin/rejections", response_model=list[RejectionRuleResponse])
async def list_rejection_rules(include_disabled: bool = Query(False)):
    """获取所有拒绝规则"""
    try:
        rules = await get_rejection_rules(enabled_only=not include_disabled)
        return [
            RejectionRuleResponse(
                rule_id=r["rule_id"],
                match_type=r["match_type"],
                pattern=r["pattern"],
                reject_reason=r["reject_reason"],
                log_only=bool(r["log_only"]),
                enabled=bool(r["enabled"]),
                created_at=str(r["created_at"]) if r.get("created_at") else None,
                updated_at=str(r["updated_at"]) if r.get("updated_at") else None,
            )
            for r in rules
        ]
    except Exception as e:
        logger.error(f"Failed to list rejection rules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/rejections", status_code=201, response_model=RejectionRuleCreateResponse)
async def create_rejection_rule(req: RejectionRuleRequest):
    """新增拒绝规则"""
    try:
        rule_id = await add_rejection_rule(
            match_type=req.match_type.value,
            pattern=req.pattern,
            reject_reason=req.reject_reason,
            log_only=req.log_only,
            enabled=req.enabled,
        )
        invalidate_cache()
        return RejectionRuleCreateResponse(rule_id=rule_id)
    except Exception as e:
        logger.error(f"Failed to create rejection rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/rejections/{rule_id}", response_model=RejectionRuleUpdateResponse)
async def update_rejection_rule_endpoint(rule_id: int, req: RejectionRuleRequest):
    """更新拒绝规则"""
    try:
        updated = await update_rejection_rule(
            rule_id=rule_id,
            match_type=req.match_type.value,
            pattern=req.pattern,
            reject_reason=req.reject_reason,
            log_only=req.log_only,
            enabled=req.enabled,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="拒绝规则不存在")
        invalidate_cache()
        return RejectionRuleUpdateResponse()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update rejection rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/rejections/{rule_id}", response_model=RejectionRuleDeleteResponse)
async def delete_rejection_rule_endpoint(rule_id: int):
    """删除拒绝规则"""
    try:
        deleted = await delete_rejection_rule(rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="拒绝规则不存在")
        invalidate_cache()
        return RejectionRuleDeleteResponse()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete rejection rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== 拒绝日志 =====

class RejectionLogsResponse(BaseModel):
    logs: list[RejectionLogResponse]
    total: int
    limit: int
    offset: int


@router.get("/admin/rejection-logs", response_model=RejectionLogsResponse)
async def list_rejection_logs(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
):
    """查看拒绝命中日志（分页）"""
    try:
        logs, total = await get_rejection_logs(limit=limit, offset=offset)
        return RejectionLogsResponse(
            logs=[
                RejectionLogResponse(
                    log_id=log["log_id"],
                    rule_id=log["rule_id"],
                    rule_pattern=log["rule_pattern"],
                    user_question=log["user_question"],
                    action=log["action"],
                    conversation_id=log.get("conversation_id"),
                    created_at=str(log["created_at"]) if log.get("created_at") else None,
                )
                for log in logs
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"Failed to list rejection logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== 敏感词管理 =====

class SensitiveWordCreateResponse(BaseModel):
    word_id: int
    message: str = "敏感词创建成功"


class SensitiveWordUpdateResponse(BaseModel):
    message: str = "敏感词更新成功"


class SensitiveWordDeleteResponse(BaseModel):
    message: str = "敏感词删除成功"


@router.get("/admin/sensitive-words", response_model=list[SensitiveWordResponse])
async def list_sensitive_words(include_disabled: bool = Query(False)):
    """获取敏感词列表"""
    try:
        words = await get_sensitive_words(enabled_only=not include_disabled)
        return [
            SensitiveWordResponse(
                word_id=w["word_id"],
                word=w["word"],
                enabled=bool(w["enabled"]),
                created_at=str(w["created_at"]) if w.get("created_at") else None,
            )
            for w in words
        ]
    except Exception as e:
        logger.error(f"Failed to list sensitive words: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/sensitive-words", status_code=201, response_model=SensitiveWordCreateResponse)
async def create_sensitive_word(req: SensitiveWordRequest):
    """新增敏感词"""
    try:
        word_id = await add_sensitive_word(word=req.word, enabled=req.enabled)
        invalidate_sensitive_word_cache()
        return SensitiveWordCreateResponse(word_id=word_id)
    except Exception as e:
        logger.error(f"Failed to create sensitive word: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/sensitive-words/{word_id}", response_model=SensitiveWordUpdateResponse)
async def update_sensitive_word_endpoint(word_id: int, req: SensitiveWordRequest):
    """更新敏感词"""
    try:
        updated = await update_sensitive_word(word_id=word_id, word=req.word, enabled=req.enabled)
        if not updated:
            raise HTTPException(status_code=404, detail="敏感词不存在")
        invalidate_sensitive_word_cache()
        return SensitiveWordUpdateResponse()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update sensitive word: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/sensitive-words/{word_id}", response_model=SensitiveWordDeleteResponse)
async def delete_sensitive_word_endpoint(word_id: int):
    """删除敏感词"""
    try:
        deleted = await delete_sensitive_word(word_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="敏感词不存在")
        invalidate_sensitive_word_cache()
        return SensitiveWordDeleteResponse()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete sensitive word: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== 模型配置 =====

@router.get("/admin/model-configs", response_model=list[ModelConfigResponse])
async def list_model_configs():
    """获取所有模型配置"""
    try:
        configs = await get_model_configs()
        return [
            ModelConfigResponse(
                config_id=c["config_id"],
                config_key=c["config_key"],
                config_value=c["config_value"],
                description=c.get("description"),
                updated_at=str(c["updated_at"]) if c.get("updated_at") else None,
            )
            for c in configs
        ]
    except Exception as e:
        logger.error(f"Failed to list model configs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/model-configs/{config_key}", response_model=dict)
async def update_model_config(config_key: str, req: ModelConfigRequest):
    """更新模型配置（以 config_key 为唯一键，不存在则插入）"""
    try:
        await upsert_model_config(config_key=config_key, config_value=req.config_value)
        invalidate_model_config_cache()
        return {"message": "配置更新成功", "config_key": config_key, "config_value": req.config_value}
    except Exception as e:
        logger.error(f"Failed to update model config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== 知识库克隆 =====

class CloneKbIndexResponse(BaseModel):
    cloned_chunk_count: int
    cloned_doc_ids: list[int]


class VectorOptimizeResponse(BaseModel):
    kb_id: int
    total_chunks: int
    duplicate_chunks: int
    removed_duplicates: int
    idf_terms_updated: int
    optimizer_applied: bool


@router.post("/admin/vector-optimize", response_model=VectorOptimizeResponse)
async def vector_optimize_endpoint(req: VectorOptimizeRequest):
    """
    对指定知识库的向量进行优化处理。

    操作选项（均为幂等操作）：
    - remove_duplicates: 扫描并删除 text 完全重复的 chunk，保留 doc_version_id 最新的一个
    - rebuild_bm25_idf: 对该 kb_id 下所有 chunk 重新计算 BM25 IDF 并持久化
    - compact_collection: 触发 Qdrant 后台索引整理（vacuum/优化器）
    """
    try:
        result = await vector_optimize_async(
            kb_id=req.kb_id,
            remove_duplicates=req.remove_duplicates,
            rebuild_bm25_idf=req.rebuild_bm25_idf,
            compact_collection=req.compact_collection,
        )
        return VectorOptimizeResponse(**result)
    except Exception as e:
        logger.error(f"Vector optimize failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/kb/clone-index", response_model=CloneKbIndexResponse)
async def clone_kb_index_endpoint(req: CloneKbIndexRequest):
    """
    将源知识库的向量复制到目标知识库（混合向量完整复制）。

    应用域负责：
    - 源/目标 KB 元数据的创建或校验
    - doc_id -> target_doc_id 映射关联
    - 克隆后的文档列表同步

    AI 域仅负责 Qdrant 向量层面的复制。
    """
    try:
        result = await clone_kb_index_async(
            req.source_kb_id,
            req.target_kb_id,
            [mapping.model_dump() for mapping in req.document_mappings],
        )
        return CloneKbIndexResponse(**result)
    except Exception as e:
        logger.error(f"Failed to clone KB index: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
