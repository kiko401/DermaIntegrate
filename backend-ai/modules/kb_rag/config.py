"""
模型配置管理

MySQL 表 rag_model_configs 优先，环境变量兜底。
缓存 TTL 2 分钟，写操作后主动失效。
"""
import os
import logging
import time
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ========== 缓存结构 ==========

_MODEL_CONFIG_CACHE: dict = {}
_MODEL_CONFIG_CACHE_AT: float = 0
_CONFIG_CACHE_TTL: float = 120.0  # 默认2分钟

# 线程锁（保护配置缓存更新）
_CONFIG_CACHE_LOCK = threading.RLock()

# 缓存 TTL（从 shared/config 统一读取）
from shared.config import MODEL_CONFIG_CACHE_TTL as _MODEL_CONFIG_CACHE_TTL
_CONFIG_CACHE_TTL = _MODEL_CONFIG_CACHE_TTL


def _load_config_from_db(config_key: str) -> Optional[str]:
    """从 MySQL 加载配置值（同步接口，内部委托 AsyncExecutor 执行异步操作）

    使用 shared.event_loop 的 AsyncExecutor 在独立线程中执行异步协程，
    避免在已有事件循环的线程中创建新循环。
    """
    try:
        from .rules.store import get_model_config

        async def _fetch():
            return await get_model_config(config_key)

        # 使用统一的 AsyncExecutor
        from shared.event_loop import get_async_executor
        row = get_async_executor().run_sync(_fetch, timeout=10.0)
        return row["config_value"] if row else None
    except TimeoutError:
        logger.warning(f"Failed to load config '{config_key}' from DB: timeout")
        return None
    except Exception as e:
        logger.warning(f"Failed to load config '{config_key}' from DB: {e}")
        return None


def _invalidate_config_cache():
    """清空配置缓存"""
    global _MODEL_CONFIG_CACHE, _MODEL_CONFIG_CACHE_AT
    with _CONFIG_CACHE_LOCK:
        _MODEL_CONFIG_CACHE = {}
        _MODEL_CONFIG_CACHE_AT = 0
    logger.info("Model config cache invalidated.")


def get_config(config_key: str, env_var: str = None, default: str = None) -> str:
    """
    获取模型配置：MySQL 优先 → 环境变量 → 默认值。

    使用双重检查锁定模式确保线程安全。

    Args:
        config_key: MySQL 表中的 config_key（如 "integration_model"）
        env_var: 环境变量名（如 "INTEGRATION_MODEL"）
        default: 默认值
    """
    global _MODEL_CONFIG_CACHE, _MODEL_CONFIG_CACHE_AT
    now = time.monotonic()

    # 首次检查：缓存命中且未过期（读操作不加锁）
    if config_key in _MODEL_CONFIG_CACHE and (now - _MODEL_CONFIG_CACHE_AT) <= _CONFIG_CACHE_TTL:
        return _MODEL_CONFIG_CACHE.get(config_key, default)

    # 获取锁后进行二次检查
    with _CONFIG_CACHE_LOCK:
        # 二次检查
        if config_key in _MODEL_CONFIG_CACHE and (now - _MODEL_CONFIG_CACHE_AT) <= _CONFIG_CACHE_TTL:
            return _MODEL_CONFIG_CACHE.get(config_key, default)

        # 缓存未命中或已过期，重新加载
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
