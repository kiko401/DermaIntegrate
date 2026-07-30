"""
文件清理模块

提供定时清理功能，自动删除超过保留期的上传文件和静态资源。
用于防止磁盘空间被过期文件占满。

清理策略：
- 保留期由 FILE_RETENTION_DAYS 配置（默认 7 天）
- 清理范围：上传目录、图片目录、热力图目录
- 执行频率：每天执行一次
- 清理条件：文件修改时间超过保留期
- 并发安全：多 worker 环境下通过文件锁互斥，防止重复清理或文件竞争

典型使用场景：
- FastAPI 应用启动时通过 lifespan 事件启动后台清理任务
- 配合 cleanup_loop() 在独立协程中持续运行
"""
import os
import time
import asyncio
import logging
from filelock import FileLock
from config import settings
from shared.config import FILE_RETENTION_DAYS

logger = logging.getLogger(__name__)

# 保留天数（从 shared/config 统一读取）
RETENTION_DAYS = FILE_RETENTION_DAYS
MAX_AGE_SECONDS = RETENTION_DAYS * 24 * 3600

# 文件锁路径（防止多 worker 并发清理）
_CLEANUP_LOCK_FILE = os.path.join(settings.UPLOAD_DIR, ".cleanup.lock")


def cleanup_old_files():
    """
    清理超过保留期的旧文件（文件锁防止多 worker 竞争）

    遍历上传目录和静态资源目录，删除所有修改时间超过 RETENTION_DAYS 的文件。
    目录不存在或删除失败不影响其他文件继续清理。

    Raises:
        OSError: 文件删除失败时仅记录日志，不抛出异常

    Returns:
        int: 实际删除的文件数量
    """
    lock = FileLock(_CLEANUP_LOCK_FILE, timeout=10.0)
    with lock:
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
                except OSError as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleanup task: Deleted {deleted_count} old files (older than {RETENTION_DAYS} days).")

        return deleted_count


async def cleanup_loop():
    """
    后台定时清理协程

    以每天一次的频率持续执行文件清理任务直到被取消。
    启动时会立即执行一次清理，然后进入定时循环。

    注意：
    - 该协程应在 FastAPI lifespan 或后台任务中启动
    - shutdown 时会被 cancel，需配合 try/except asyncio.CancelledError 处理

    CancelSafe: 取消时会引发 asyncio.CancelledError
    """
    logger.info("Started background file cleanup loop (runs daily).")
    # 启动时立即执行一次清理
    cleanup_old_files()
    while True:
        # 每天执行一次（86400 秒）
        await asyncio.sleep(86400)
        cleanup_old_files()
