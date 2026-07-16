"""
模型配置管理

MySQL 表 rag_model_configs 优先，环境变量兜底。
缓存 TTL 2 分钟，写操作后主动失效。
"""
import os
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ========== 缓存结构 ==========

_MODEL_CONFIG_CACHE: dict = {}
_MODEL_CONFIG_CACHE_TTL: float = 120  # 2分钟
_MODEL_CONFIG_CACHE_AT: float = 0


def _load_config_from_db(config_key: str) -> Optional[str]:
    """从 MySQL 加载配置值"""
    try:
        from .rules.store import get_model_config
        row = get_model_config(config_key)
        return row["config_value"] if row else None
    except Exception as e:
        logger.warning(f"Failed to load config '{config_key}' from DB: {e}")
        return None


def _invalidate_config_cache():
    """清空配置缓存"""
    global _MODEL_CONFIG_CACHE, _MODEL_CONFIG_CACHE_AT
    _MODEL_CONFIG_CACHE = {}
    _MODEL_CONFIG_CACHE_AT = 0
    logger.info("Model config cache invalidated.")


def get_config(config_key: str, env_var: str = None, default: str = None) -> str:
    """
    获取模型配置：MySQL 优先 → 环境变量 → 默认值。

    Args:
        config_key: MySQL 表中的 config_key（如 "integration_model"）
        env_var: 环境变量名（如 "INTEGRATION_MODEL"）
        default: 默认值
    """
    global _MODEL_CONFIG_CACHE, _MODEL_CONFIG_CACHE_AT
    now = time.monotonic()

    # 缓存未命中或已过期
    if (config_key not in _MODEL_CONFIG_CACHE) or (now - _MODEL_CONFIG_CACHE_AT) > _MODEL_CONFIG_CACHE_TTL:
        db_val = _load_config_from_db(config_key)
        if db_val is not None:
            _MODEL_CONFIG_CACHE[config_key] = db_val
        elif env_var and os.getenv(env_var):
            _MODEL_CONFIG_CACHE[config_key] = os.getenv(env_var)
        else:
            _MODEL_CONFIG_CACHE[config_key] = default
        _MODEL_CONFIG_CACHE_AT = now

    return _MODEL_CONFIG_CACHE.get(config_key, default)


def invalidate_model_config_cache():
    """写操作后主动失效缓存"""
    _invalidate_config_cache()


# ========== 便捷访问函数 ==========

def get_integration_model() -> str:
    """获取 Integration 模型名称（LLM 重写/生成用）"""
    return get_config("integration_model", env_var="INTEGRATION_MODEL", default="deepseek-v4-flash")


def get_integration_api_key() -> str:
    """获取 Integration API Key"""
    # API Key 不走 MySQL，始终从环境变量
    return os.getenv("INTEGRATION_API_KEY", "")


def get_integration_base_url() -> str:
    """获取 Integration Base URL"""
    return os.getenv("INTEGRATION_BASE_URL", "https://api.deepseek.com")
