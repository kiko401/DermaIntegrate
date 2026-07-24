"""
异步执行器模块

提供在同步上下文中安全调用异步函数的机制。

核心组件：
- AsyncExecutor: 专用线程事件循环执行器
- run_in_executor: 装饰器，将异步函数包装为同步调用

架构设计（M-02/M-03 修复）：
1. 在独立线程中运行事件循环
2. 同步代码通过 queue 将协程提交给该线程执行
3. 避免在已有事件循环的线程中创建新循环
4. 程序退出时自动清理

使用示例：
    from shared.event_loop import get_async_executor

    # 同步接口调用异步函数
    result = get_async_executor().run_sync(async_function, arg1, arg2)

    # 或使用装饰器
    @run_in_executor
    async def fetch_data():
        return await some_async_function()
"""
import asyncio
import threading
import atexit
import logging
from typing import TypeVar, Callable, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)

_T = TypeVar('_T')


class AsyncExecutor:
    """
    专用线程事件循环执行器

    在独立线程中运行事件循环，同步代码通过线程安全队列将协程
    提交给该线程执行。避免在已有事件循环的线程中创建新循环。

    特性：
    - 线程安全：使用 queue 进行跨线程通信
    - 自动清理：程序退出时自动关闭
    - 超时控制：默认30秒超时
    - 异常传播：子线程中的异常会传播到主线程
    """
    _instance: Optional['AsyncExecutor'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'AsyncExecutor':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue] = None
        self._started = threading.Event()
        self._stopped = False
        self._default_timeout = 30.0

        self._start()
        atexit.register(self._shutdown)
        self._initialized = True
        logger.info("AsyncExecutor started in dedicated thread.")

    def _start(self):
        """启动事件循环线程"""
        def loop_runner():
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._queue = asyncio.Queue(maxsize=1000)  # 防止无限入队导致内存耗尽
                self._started.set()

                self._loop.run_until_complete(self._process_queue())
            except Exception as e:
                logger.error(f"AsyncExecutor loop error: {e}")
            finally:
                self._loop.close()
                self._loop = None

        self._thread = threading.Thread(
            target=loop_runner,
            daemon=True,
            name="AsyncExecutor-Worker"
        )
        self._thread.start()
        self._started.wait(timeout=5.0)  # 等待循环启动完成

    async def _process_queue(self):
        """队列消费者协程，持续从队列中取任务执行"""
        while not self._stopped:
            try:
                future, coro, args, kwargs = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                try:
                    result = await coro(*args, **kwargs)
                    future.result.append(result)
                except Exception as e:
                    future.result.append(e)
                finally:
                    future.ready.set()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"AsyncExecutor queue processing error: {e}")

    def _shutdown(self):
        """关闭执行器（供 atexit 调用）"""
        if self._thread and self._thread.is_alive():
            self._stopped = True
            self._thread.join(timeout=3.0)
            logger.info("AsyncExecutor shutdown complete.")

    def run_sync(
        self,
        coro: Callable[..., Any],
        *args,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """
        同步接口：在专用事件循环中执行异步协程

        Args:
            coro: 异步协程函数（非协程对象，是函数）
            *args: 协程位置参数
            timeout: 超时时间（秒），默认30秒
            **kwargs: 协程关键字参数

        Returns:
            协程执行结果

        Raises:
            TimeoutError: 执行超时
            RuntimeError: 执行器未运行
            Exception: 协程执行中的异常会重新抛出
        """
        if self._loop is None or not self._thread.is_alive():
            raise RuntimeError("AsyncExecutor not running")

        timeout = timeout or self._default_timeout

        class _Future:
            def __init__(self):
                self.result: list = []
                self.ready = threading.Event()

        future = _Future()
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, (future, coro, args, kwargs)
        )

        if not future.ready.wait(timeout=timeout):
            raise TimeoutError(f"AsyncExecutor.run_sync timed out after {timeout}s")

        if not future.result:
            raise RuntimeError("AsyncExecutor.run_sync returned no result")

        result = future.result[0]
        if isinstance(result, Exception):
            raise result
        return result

    def is_running(self) -> bool:
        """检查执行器是否正在运行"""
        return self._loop is not None and self._thread is not None and self._thread.is_alive()


# ============================================================
# 模块级接口
# ============================================================

_executor: Optional[AsyncExecutor] = None


def get_async_executor() -> AsyncExecutor:
    """
    获取全局 AsyncExecutor 单例

    Returns:
        AsyncExecutor 实例
    """
    global _executor
    if _executor is None:
        _executor = AsyncExecutor()
    return _executor


def run_in_executor(coro_func: Callable[..., Any]) -> Callable[..., Any]:
    """
    装饰器：在异步执行器中运行异步协程

    将异步函数包装为同步函数，方便在同步代码中调用。

    示例：
        @run_in_executor
        async def fetch_sensitive_words():
            return await get_sensitive_words(enabled_only=True)

        # 同步调用
        words = fetch_sensitive_words()

    Args:
        coro_func: 异步协程函数

    Returns:
        包装后的同步函数
    """
    @wraps(coro_func)
    def wrapper(*args, **kwargs):
        return get_async_executor().run_sync(coro_func, *args, **kwargs)
    return wrapper


def shutdown_executor():
    """
    主动关闭执行器。

    L-04: 补充 atexit 机制，提供显式关闭接口。
    建议在 FastAPI lifespan shutdown 阶段调用此函数，确保所有待处理任务完成。
    """
    global _executor
    if _executor is not None:
        _executor._shutdown()
        _executor = None
        logger.info("AsyncExecutor explicitly shutdown via shutdown_executor().")
