# -*- coding: utf-8 -*-
import asyncio
import threading
from typing import Callable, Any

from module.logger import logger

class AsyncExecutor:
    """
    统一的异步执行器，内部维护一个后台线程运行 asyncio event loop。
    将所有的存储、推送等阻塞操作投递到该后台队列中，以确保主要流程不受阻塞。
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
        """
        提交一个同步或异步函数并在队列中执行，返回 future。
        支持同步调用传入，从而自动被包装并在事件循环中串行/并发执行。
        因 event loop 在单线程内调度同步 wrapper，默认会串行化所有非 await 的同步操作。
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
        """
        等待队列内已有任务尽量执行完毕。
        利用提交一个空任务并等待返回值，实现简单的 flush 效果。
        """
        try:
            future = self.submit(lambda: None)
            future.result(timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("AsyncExecutor flush timeout")
        except Exception as e:
            logger.warning(f"AsyncExecutor flush error: {e}")


# 全局唯一实例
async_executor = AsyncExecutor()

import atexit
atexit.register(async_executor.flush)

