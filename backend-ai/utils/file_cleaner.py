import os
import time
import asyncio
import logging
from config import settings

logger = logging.getLogger(__name__)

# 保留天数
RETENTION_DAYS = 7
MAX_AGE_SECONDS = RETENTION_DAYS * 24 * 3600


def cleanup_old_files():
    """清理超过 7 天的旧文件"""
    directories = [
        settings.UPLOAD_DIR,
        os.path.join(settings.STATIC_DIR, "images"),
        os.path.join(settings.STATIC_DIR, "heatmaps")
    ]

    now = time.time()
    deleted_count = 0

    for dir_path in directories:
        if not os.path.exists(dir_path):
            continue
        for filename in os.listdir(dir_path):
            file_path = os.path.join(dir_path, filename)
            try:
                if os.path.isfile(file_path):
                    file_mtime = os.path.getmtime(file_path)
                    if now - file_mtime > MAX_AGE_SECONDS:
                        os.remove(file_path)
                        deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")

    if deleted_count > 0:
        logger.info(f"Cleanup task: Deleted {deleted_count} old files (older than {RETENTION_DAYS} days).")


async def cleanup_loop():
    """后台定时清理任务，每天执行一次"""
    logger.info("Started background file cleanup loop (runs daily).")
    # 启动时先执行一次
    cleanup_old_files()
    while True:
        # 每天执行一次 (86400 秒)
        await asyncio.sleep(86400)
        cleanup_old_files()