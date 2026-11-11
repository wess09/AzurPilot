"""异步执行器模块。

提供单例模式的 AsyncExecutor，内部维护后台线程运行 asyncio 事件循环。
用于将存储、推送等阻塞操作投递到后台队列，确保主流程不被阻塞。
"""

# -*- coding: utf-8 -*-
import asyncio
import threading
from typing import Callable, Any

from module.logger import logger

class AsyncExecutor:
    """统一的异步执行器。

    内部维护一个后台线程运行 asyncio 事件循环，
    将所有的存储、推送等阻塞操作投递到该后台队列中，以确保主流程不受阻塞。
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AsyncExecutor, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AsyncExecutorThread")
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        except Exception as e:
            logger.exception(f"AsyncExecutor event loop exception: {e}")

    def submit(self, func: Callable, *args, **kwargs) -> asyncio.Future:
        """提交一个同步或异步函数并在后台队列中执行。

        支持同步函数传入，会自动包装并在事件循环中串行化执行。

        Args:
            func (Callable): 待执行的可调用对象或协程函数。
            *args: 位置参数。
            **kwargs: 关键字参数。

        Returns:
            asyncio.Future: 代表异步执行结果的 Future 对象。
        """
        if asyncio.iscoroutinefunction(func):
            return asyncio.run_coroutine_threadsafe(func(*args, **kwargs), self._loop)
        else:
            # 对于普通的同步函数，直接包装为协程跑在loop里
            # 这样对于 SQLite 的写入来说，就变成了在单线程(event loop 线程)内的串行执行
            async def wrapper():
                return func(*args, **kwargs)
            return asyncio.run_coroutine_threadsafe(wrapper(), self._loop)

    def flush(self, timeout: float = 5.0):
        """等待队列内已有任务尽量执行完毕。

        先排空进程内写入队列，再利用提交一个空任务并等待返回值，实现简单的 flush 效果。

        Args:
            timeout (float): 等待超时时间（秒），默认为 5.0 秒。
        """
        try:
            from module.persistence.write_queue import write_queue
            write_queue.flush(timeout=timeout)
        except Exception as e:
            logger.warning(f"[异步执行器] 刷新写入队列失败: {type(e).__name__}")
        try:
            future = self.submit(lambda: None)
            future.result(timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("[异步执行器] 刷新超时")
        except Exception as e:
            logger.warning(f"[异步执行器] 刷新错误: {e}")


# 全局唯一实例
async_executor = AsyncExecutor()

import atexit
atexit.register(async_executor.flush)

