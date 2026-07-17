import os
import httpx
import logging
import asyncio
from shared.config import (
    CALLBACK_CONNECT_TIMEOUT, CALLBACK_READ_TIMEOUT,
    CALLBACK_WRITE_TIMEOUT, CALLBACK_POOL_TIMEOUT,
)
from ..schemas import IngestCallback

logger = logging.getLogger(__name__)

# 回调超时配置（从 shared/config 统一读取）
CALLBACK_TIMEOUT = httpx.Timeout(
    connect=CALLBACK_CONNECT_TIMEOUT,
    read=CALLBACK_READ_TIMEOUT,
    write=CALLBACK_WRITE_TIMEOUT,
    pool=CALLBACK_POOL_TIMEOUT,
)
MAX_CALLBACK_RETRIES = 3
CALLBACK_RETRY_DELAY = 1.0  # 秒


async def send_task_callback(task_id: int, task_code: str, chunk_count: int, error_message: str = None):
    """通过 httpx 向主应用发送任务状态回调，最多重试 3 次"""
    base_url = os.getenv("APP_BASE_URL")
    secret = os.getenv("X_INTERNAL_SECRET")

    if not base_url or not secret:
        logger.error("APP_BASE_URL or X_INTERNAL_SECRET is not configured. Callback will fail.")
        return

    callback_url = f"{base_url}/api/rag/tasks/{task_id}/callback"

    status = "succeeded" if not error_message else "failed"

    payload = IngestCallback(
        task_code=task_code,
        status=status,
        chunk_count=chunk_count,
        error_message=error_message
    )

    headers = {
        "X-Internal-Token": secret,
        "Content-Type": "application/json"
    }

    last_error = None
    for attempt in range(1, MAX_CALLBACK_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
                response = await client.post(callback_url, json=payload.model_dump(), headers=headers)
                if response.status_code == 200:
                    logger.info(f"Callback succeeded for task {task_id} (attempt {attempt})")
                    return
                else:
                    last_error = f"HTTP {response.status_code} - {response.text}"
                    logger.warning(f"Callback failed for task {task_id} (attempt {attempt}): {last_error}")
        except httpx.TimeoutException:
            last_error = f"timeout after {CALLBACK_TIMEOUT.connect}s connect + {CALLBACK_TIMEOUT.read}s read"
            logger.warning(f"Callback timed out for task {task_id} (attempt {attempt}): {last_error}")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Callback exception for task {task_id} (attempt {attempt}): {last_error}")

        if attempt < MAX_CALLBACK_RETRIES:
            await asyncio.sleep(CALLBACK_RETRY_DELAY)

    # M-15: 回调失败时抛出异常，不再静默忽略
    logger.error(f"Callback exhausted all {MAX_CALLBACK_RETRIES} retries for task {task_id}. Last error: {last_error}")
    raise RuntimeError(f"Task callback failed for task_id={task_id} after {MAX_CALLBACK_RETRIES} retries: {last_error}")