"""
规则存储层 - MySQL（异步版本）

使用SQLAlchemy管理规则表，支持读写分离（应用域管元数据，AI域只消费和记录日志）。
表结构由AI域维护，规则配置由管理员通过API管理。

所有函数均为异步接口，统一使用 aiomysql 引擎。
"""
import os
import logging
import threading
from datetime import datetime
from typing import List, Optional, Tuple
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

load_dotenv()  # 加载 .env 环境变量

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    logger.warning(
        "DATABASE_URL environment variable is not set. "
        "Rules store will be unavailable until configured."
    )

def is_db_configured() -> bool:
    """检查数据库是否已配置（可写入）。"""
    return bool(DATABASE_URL.strip())


# 异步引擎（pool_pre_ping 防 MySQL 8h 空闲断连）
_async_engine = None
_async_session_factory = None
_engine_lock = threading.Lock()


def _get_async_engine():
    global _async_engine, _async_session_factory
    if _async_engine is None:
        with _engine_lock:
            # 二次检查：其他线程可能已初始化
            if _async_engine is None:
                if not DATABASE_URL:
                    raise RuntimeError(
                        "DATABASE_URL is not configured. "
                        "Cannot initialize rules store. Please set the DATABASE_URL environment variable."
                    )
                import re
                url = DATABASE_URL
                # 将 mysql:// / aiomysql:// / mysql+pymysql:// 等统一替换为 mysql+aiomysql://
                url = re.sub(r'^mysql(\+pymysql)?://', 'mysql+aiomysql://', url)
                _async_engine = create_async_engine(
            url,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
        )
        # SQLAlchemy 2.0.25 的 MySQLDialect_aiomysql 复用 pymysql.do_ping，
        # 但 pymysql.do_ping 调用 dbapi_connection.ping() 不传参数，
        # 而 aiomysql 的 AsyncAdapt_aiomysql_connection.ping(reconnect) 必填参数。
        # 修复方案：patch ping 方法使其 reconnect 有默认值。
        try:
            from sqlalchemy.dialects.mysql.aiomysql import AsyncAdapt_aiomysql_connection
            _orig_ping = AsyncAdapt_aiomysql_connection.ping
            def _patched_ping(self, reconnect=True):
                return _orig_ping(self, reconnect)
            AsyncAdapt_aiomysql_connection.ping = _patched_ping
        except Exception:
            pass  # 非关键路径，失败不阻断
        _async_session_factory = async_sessionmaker(
            _async_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _async_engine


def _get_session_factory():
    _get_async_engine()
    return _async_session_factory


async def init_rules_table():
    """
    初始化规则表（幂等建表，已存在则跳过）
    表: rag_rule_answers / rag_rejection_rules / rag_rejection_logs
    """
    engine = _get_async_engine()
    async with engine.connect() as conn:
        # 规则回答表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_rule_answers (
                rule_id INT AUTO_INCREMENT PRIMARY KEY,
                match_type VARCHAR(20) NOT NULL DEFAULT 'keyword',
                pattern VARCHAR(200) NOT NULL,
                answer TEXT NOT NULL,
                priority INT NOT NULL DEFAULT 0,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_enabled_priority (enabled, priority DESC),
                INDEX idx_match_type (match_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # 拒绝规则表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_rejection_rules (
                rule_id INT AUTO_INCREMENT PRIMARY KEY,
                match_type VARCHAR(20) NOT NULL DEFAULT 'keyword',
                pattern VARCHAR(200) NOT NULL,
                reject_reason VARCHAR(500) NOT NULL,
                log_only TINYINT(1) NOT NULL DEFAULT 0,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_enabled (enabled),
                INDEX idx_match_type (match_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # 拒绝日志表（只增不减，支持归档）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_rejection_logs (
                log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                rule_id INT NOT NULL,
                rule_pattern VARCHAR(200) NOT NULL,
                user_question VARCHAR(500) NOT NULL,
                action VARCHAR(20) NOT NULL,
                conversation_id INT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_rule_id (rule_id),
                INDEX idx_created_at (created_at),
                INDEX idx_conversation_id (conversation_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # 敏感词表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_sensitive_words (
                word_id INT AUTO_INCREMENT PRIMARY KEY,
                word VARCHAR(100) NOT NULL,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_word (word),
                INDEX idx_enabled (enabled)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # 模型配置表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_model_configs (
                config_id INT AUTO_INCREMENT PRIMARY KEY,
                config_key VARCHAR(100) NOT NULL,
                config_value VARCHAR(500) NOT NULL,
                description VARCHAR(200) DEFAULT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_config_key (config_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        await conn.commit()
    logger.info("Rules tables initialized.")


# ===== 规则回答 CRUD =====

async def get_rule_answers(enabled_only: bool = True) -> List[dict]:
    """获取所有规则回答，按priority降序"""
    factory = _get_session_factory()
    async with factory() as session:
        sql = "SELECT rule_id, match_type, pattern, answer, priority, enabled, created_at, updated_at FROM rag_rule_answers"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY priority DESC"
        result = await session.execute(text(sql))
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]


async def add_rule_answer(match_type: str, pattern: str, answer: str, priority: int = 0, enabled: bool = True) -> int:
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled) VALUES (:mt, :p, :a, :pri, :en)"),
            {"mt": match_type, "p": pattern, "a": answer, "pri": priority, "en": 1 if enabled else 0}
        )
        await session.commit()
        return result.lastrowid


async def update_rule_answer(rule_id: int, match_type: str = None, pattern: str = None,
                             answer: str = None, priority: int = None, enabled: bool = None) -> bool:
    factory = _get_session_factory()
    fields = []
    params = {"rid": rule_id}
    if match_type is not None:
        fields.append("match_type=:mt")
        params["mt"] = match_type
    if pattern is not None:
        fields.append("pattern=:p")
        params["p"] = pattern
    if answer is not None:
        fields.append("answer=:a")
        params["a"] = answer
    if priority is not None:
        fields.append("priority=:pri")
        params["pri"] = priority
    if enabled is not None:
        fields.append("enabled=:en")
        params["en"] = 1 if enabled else 0
    if not fields:
        return False
    async with factory() as session:
        sql = f"UPDATE rag_rule_answers SET {', '.join(fields)} WHERE rule_id=:rid"
        await session.execute(text(sql), params)
        await session.commit()
        return True


async def delete_rule_answer(rule_id: int) -> bool:
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("DELETE FROM rag_rule_answers WHERE rule_id=:rid"),
            {"rid": rule_id}
        )
        await session.commit()
        return result.rowcount > 0


# ===== 拒绝规则 CRUD =====

async def get_rejection_rules(enabled_only: bool = True) -> List[dict]:
    """获取所有拒绝规则"""
    factory = _get_session_factory()
    async with factory() as session:
        sql = "SELECT rule_id, match_type, pattern, reject_reason, log_only, enabled, created_at, updated_at FROM rag_rejection_rules"
        if enabled_only:
            sql += " WHERE enabled=1"
        result = await session.execute(text(sql))
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]


async def add_rejection_rule(match_type: str, pattern: str, reject_reason: str,
                              log_only: bool = False, enabled: bool = True) -> int:
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled) VALUES (:mt, :p, :rr, :lo, :en)"),
            {"mt": match_type, "p": pattern, "rr": reject_reason, "lo": 1 if log_only else 0, "en": 1 if enabled else 0}
        )
        await session.commit()
        return result.lastrowid


async def update_rejection_rule(rule_id: int, match_type: str = None, pattern: str = None,
                                reject_reason: str = None, log_only: bool = None, enabled: bool = None) -> bool:
    factory = _get_session_factory()
    fields = []
    params = {"rid": rule_id}
    if match_type is not None:
        fields.append("match_type=:mt")
        params["mt"] = match_type
    if pattern is not None:
        fields.append("pattern=:p")
        params["p"] = pattern
    if reject_reason is not None:
        fields.append("reject_reason=:rr")
        params["rr"] = reject_reason
    if log_only is not None:
        fields.append("log_only=:lo")
        params["lo"] = 1 if log_only else 0
    if enabled is not None:
        fields.append("enabled=:en")
        params["en"] = 1 if enabled else 0
    if not fields:
        return False
    async with factory() as session:
        sql = f"UPDATE rag_rejection_rules SET {', '.join(fields)} WHERE rule_id=:rid"
        await session.execute(text(sql), params)
        await session.commit()
        return True


async def delete_rejection_rule(rule_id: int) -> bool:
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("DELETE FROM rag_rejection_rules WHERE rule_id=:rid"),
            {"rid": rule_id}
        )
        await session.commit()
        return result.rowcount > 0


# ===== 拒绝日志 =====

async def add_rejection_log(rule_id: int, rule_pattern: str, user_question: str,
                            action: str, conversation_id: int = None) -> int:
    """记录拒绝命中日志"""
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("INSERT INTO rag_rejection_logs (rule_id, rule_pattern, user_question, action, conversation_id) VALUES (:rid, :rp, :uq, :act, :cid)"),
            {"rid": rule_id, "rp": rule_pattern, "uq": user_question[:500], "act": action, "cid": conversation_id}
        )
        await session.commit()
        return result.lastrowid


async def get_rejection_logs(limit: int = 100, offset: int = 0) -> Tuple[List[dict], int]:
    """查询拒绝日志（分页）"""
    factory = _get_session_factory()
    async with factory() as session:
        total_result = await session.execute(text("SELECT COUNT(*) FROM rag_rejection_logs"))
        total = total_result.scalar()
        rows_result = await session.execute(
            text("SELECT * FROM rag_rejection_logs ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {"lim": limit, "off": offset}
        )
        rows = rows_result.fetchall()
        return [dict(row._mapping) for row in rows], total


# ===== 敏感词 CRUD =====

async def get_sensitive_words(enabled_only: bool = True) -> List[dict]:
    """获取敏感词列表"""
    factory = _get_session_factory()
    async with factory() as session:
        sql = "SELECT word_id, word, enabled, created_at FROM rag_sensitive_words"
        if enabled_only:
            sql += " WHERE enabled=1"
        result = await session.execute(text(sql))
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]


async def add_sensitive_word(word: str, enabled: bool = True) -> int:
    """新增敏感词"""
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("INSERT INTO rag_sensitive_words (word, enabled) VALUES (:w, :en)"),
            {"w": word, "en": 1 if enabled else 0}
        )
        await session.commit()
        return result.lastrowid


async def update_sensitive_word(word_id: int, word: str = None, enabled: bool = None) -> bool:
    """更新敏感词"""
    factory = _get_session_factory()
    fields = []
    params = {"wid": word_id}
    if word is not None:
        fields.append("word=:w")
        params["w"] = word
    if enabled is not None:
        fields.append("enabled=:en")
        params["en"] = 1 if enabled else 0
    if not fields:
        return False
    async with factory() as session:
        sql = f"UPDATE rag_sensitive_words SET {', '.join(fields)} WHERE word_id=:wid"
        await session.execute(text(sql), params)
        await session.commit()
        return True


async def delete_sensitive_word(word_id: int) -> bool:
    """删除敏感词"""
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("DELETE FROM rag_sensitive_words WHERE word_id=:wid"),
            {"wid": word_id}
        )
        await session.commit()
        return result.rowcount > 0


# ===== 模型配置 CRUD =====

async def get_model_configs() -> List[dict]:
    """获取所有模型配置"""
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("SELECT config_id, config_key, config_value, description, updated_at FROM rag_model_configs")
        )
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]


async def get_model_config(config_key: str) -> Optional[dict]:
    """获取单个模型配置"""
    factory = _get_session_factory()
    async with factory() as session:
        row_result = await session.execute(
            text("SELECT config_id, config_key, config_value, description, updated_at FROM rag_model_configs WHERE config_key=:ck"),
            {"ck": config_key}
        )
        row = row_result.fetchone()
        return dict(row._mapping) if row else None


async def upsert_model_config(config_key: str, config_value: str, description: str = None) -> bool:
    """更新或插入模型配置（以 config_key 为唯一键）"""
    factory = _get_session_factory()
    async with factory() as session:
        existing = await session.execute(
            text("SELECT config_id FROM rag_model_configs WHERE config_key=:ck"),
            {"ck": config_key}
        )
        if existing.fetchone():
            sql = "UPDATE rag_model_configs SET config_value=:cv, description=:desc WHERE config_key=:ck"
            await session.execute(text(sql), {"cv": config_value, "desc": description, "ck": config_key})
        else:
            sql = "INSERT INTO rag_model_configs (config_key, config_value, description) VALUES (:ck, :cv, :desc)"
            await session.execute(text(sql), {"ck": config_key, "cv": config_value, "desc": description})
        await session.commit()
        return True
