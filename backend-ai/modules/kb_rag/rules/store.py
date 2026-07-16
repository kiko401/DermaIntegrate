"""
规则存储层 - MySQL

使用SQLAlchemy管理规则表，支持读写分离（应用域管元数据，AI域只消费和记录日志）。
表结构由AI域维护，规则配置由管理员通过API管理。
"""
import os
import logging
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# 使用与主业务相同的数据库连接
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Please configure the MySQL connection string."
    )

# 同步引擎用于建表和CRUD（SQLAlchemy异步与pydantic不直接兼容，用同步引擎封装）
_sync_engine = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            DATABASE_URL.replace("+aiomysql", "").replace("aiomysql", "pymysql"),
            poolclass=QueuePool,
            pool_size=2,
            max_overflow=3,
            pool_pre_ping=True,
        )
    return _sync_engine


def init_rules_table():
    """
    初始化规则表（幂等建表，已存在则跳过）
    表: rag_rule_answers / rag_rejection_rules / rag_rejection_logs
    """
    engine = _get_sync_engine()
    with engine.connect() as conn:
        # 规则回答表
        conn.execute(text("""
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
        conn.execute(text("""
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
        conn.execute(text("""
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

        conn.commit()
    logger.info("Rules tables initialized.")

    # 敏感词表
    conn.execute(text("""
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
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS rag_model_configs (
            config_id INT AUTO_INCREMENT PRIMARY KEY,
            config_key VARCHAR(100) NOT NULL,
            config_value VARCHAR(500) NOT NULL,
            description VARCHAR(200) DEFAULT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_config_key (config_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))

    conn.commit()
    logger.info("Sensitive words and model configs tables initialized.")


# ===== 规则回答 CRUD =====

def get_rule_answers(enabled_only: bool = True) -> List[dict]:
    """获取所有规则回答，按priority降序"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        sql = "SELECT rule_id, match_type, pattern, answer, priority, enabled, created_at, updated_at FROM rag_rule_answers"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY priority DESC"
        rows = conn.execute(text(sql)).fetchall()
        return [dict(row._mapping) for row in rows]


def add_rule_answer(match_type: str, pattern: str, answer: str, priority: int = 0, enabled: bool = True) -> int:
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled) VALUES (:mt, :p, :a, :pri, :en)"),
            {"mt": match_type, "p": pattern, "a": answer, "pri": priority, "en": 1 if enabled else 0}
        )
        conn.commit()
        return result.lastrowid


def update_rule_answer(rule_id: int, match_type: str = None, pattern: str = None,
                       answer: str = None, priority: int = None, enabled: bool = None) -> bool:
    engine = _get_sync_engine()
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
    with engine.connect() as conn:
        sql = f"UPDATE rag_rule_answers SET {', '.join(fields)} WHERE rule_id=:rid"
        conn.execute(text(sql), params)
        conn.commit()
        return True


def delete_rule_answer(rule_id: int) -> bool:
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(text("DELETE FROM rag_rule_answers WHERE rule_id=:rid"), {"rid": rule_id})
        conn.commit()
        return result.rowcount > 0


# ===== 拒绝规则 CRUD =====

def get_rejection_rules(enabled_only: bool = True) -> List[dict]:
    """获取所有拒绝规则"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        sql = "SELECT rule_id, match_type, pattern, reject_reason, log_only, enabled, created_at, updated_at FROM rag_rejection_rules"
        if enabled_only:
            sql += " WHERE enabled=1"
        rows = conn.execute(text(sql)).fetchall()
        return [dict(row._mapping) for row in rows]


def add_rejection_rule(match_type: str, pattern: str, reject_reason: str,
                        log_only: bool = False, enabled: bool = True) -> int:
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled) VALUES (:mt, :p, :rr, :lo, :en)"),
            {"mt": match_type, "p": pattern, "rr": reject_reason, "lo": 1 if log_only else 0, "en": 1 if enabled else 0}
        )
        conn.commit()
        return result.lastrowid


def update_rejection_rule(rule_id: int, match_type: str = None, pattern: str = None,
                           reject_reason: str = None, log_only: bool = None, enabled: bool = None) -> bool:
    engine = _get_sync_engine()
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
    with engine.connect() as conn:
        sql = f"UPDATE rag_rejection_rules SET {', '.join(fields)} WHERE rule_id=:rid"
        conn.execute(text(sql), params)
        conn.commit()
        return True


def delete_rejection_rule(rule_id: int) -> bool:
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(text("DELETE FROM rag_rejection_rules WHERE rule_id=:rid"), {"rid": rule_id})
        conn.commit()
        return result.rowcount > 0


# ===== 拒绝日志 =====

def add_rejection_log(rule_id: int, rule_pattern: str, user_question: str,
                      action: str, conversation_id: int = None) -> int:
    """记录拒绝命中日志"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("INSERT INTO rag_rejection_logs (rule_id, rule_pattern, user_question, action, conversation_id) VALUES (:rid, :rp, :uq, :act, :cid)"),
            {"rid": rule_id, "rp": rule_pattern, "uq": user_question[:500], "act": action, "cid": conversation_id}
        )
        conn.commit()
        return result.lastrowid


def get_rejection_logs(limit: int = 100, offset: int = 0) -> Tuple[List[dict], int]:
    """查询拒绝日志（分页）"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM rag_rejection_logs")).scalar()
        rows = conn.execute(
            text("SELECT * FROM rag_rejection_logs ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {"lim": limit, "off": offset}
        ).fetchall()
        return [dict(row._mapping) for row in rows], total


# ===== 敏感词 CRUD =====

def get_sensitive_words(enabled_only: bool = True) -> List[dict]:
    """获取敏感词列表"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        sql = "SELECT word_id, word, enabled, created_at FROM rag_sensitive_words"
        if enabled_only:
            sql += " WHERE enabled=1"
        rows = conn.execute(text(sql)).fetchall()
        return [dict(row._mapping) for row in rows]


def add_sensitive_word(word: str, enabled: bool = True) -> int:
    """新增敏感词"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("INSERT INTO rag_sensitive_words (word, enabled) VALUES (:w, :en)"),
            {"w": word, "en": 1 if enabled else 0}
        )
        conn.commit()
        return result.lastrowid


def update_sensitive_word(word_id: int, word: str = None, enabled: bool = None) -> bool:
    """更新敏感词"""
    engine = _get_sync_engine()
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
    with engine.connect() as conn:
        sql = f"UPDATE rag_sensitive_words SET {', '.join(fields)} WHERE word_id=:wid"
        conn.execute(text(sql), params)
        conn.commit()
        return True


def delete_sensitive_word(word_id: int) -> bool:
    """删除敏感词"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(text("DELETE FROM rag_sensitive_words WHERE word_id=:wid"), {"wid": word_id})
        conn.commit()
        return result.rowcount > 0


# ===== 模型配置 CRUD =====

def get_model_configs() -> List[dict]:
    """获取所有模型配置"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT config_id, config_key, config_value, description, updated_at FROM rag_model_configs")
        ).fetchall()
        return [dict(row._mapping) for row in rows]


def get_model_config(config_key: str) -> Optional[dict]:
    """获取单个模型配置"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT config_id, config_key, config_value, description, updated_at FROM rag_model_configs WHERE config_key=:ck"),
            {"ck": config_key}
        ).fetchone()
        return dict(row._mapping) if row else None


def upsert_model_config(config_key: str, config_value: str, description: str = None) -> bool:
    """更新或插入模型配置（以 config_key 为唯一键）"""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT config_id FROM rag_model_configs WHERE config_key=:ck"),
            {"ck": config_key}
        ).fetchone()
        if existing:
            sql = "UPDATE rag_model_configs SET config_value=:cv, description=:desc WHERE config_key=:ck"
            conn.execute(text(sql), {"cv": config_value, "desc": description, "ck": config_key})
        else:
            sql = "INSERT INTO rag_model_configs (config_key, config_value, description) VALUES (:ck, :cv, :desc)"
            conn.execute(text(sql), {"ck": config_key, "cv": config_value, "desc": description})
        conn.commit()
        return True

