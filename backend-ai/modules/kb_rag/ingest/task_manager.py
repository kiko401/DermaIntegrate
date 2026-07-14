import os
import httpx
import logging
from ..schemas import IngestCallback

logger = logging.getLogger(__name__)

# 5s connect + 15s read，防止回调无限挂起
CALLBACK_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=15.0)


async def send_task_callback(task_id: int, task_code: str, chunk_count: int, error_message: str = None):
    """通过 httpx 向主应用发送任务状态回调"""
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

    try:
        async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
            response = await client.post(callback_url, json=payload.dict(), headers=headers)
            if response.status_code == 200:
                logger.info(f"Callback succeeded for task {task_id}")
            else:
                logger.error(f"Callback failed for task {task_id}: HTTP {response.status_code} - {response.text}")
    except httpx.TimeoutException:
        logger.error(f"Callback timed out for task {task_id} after {CALLBACK_TIMEOUT.connect}s connect + {CALLBACK_TIMEOUT.read}s read.")
    except Exception as e:
        logger.error(f"Exception during callback for task {task_id}: {e}", exc_info=True)