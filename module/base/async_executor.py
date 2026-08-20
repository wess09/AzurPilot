"""异步执行器模块。

提供单例模式的 AsyncExecutor，内部维护后台线程运行 asyncio 事件循环。
用于将存储、推送等阻塞操作投递到后台队列，确保主流程不被阻塞。
"""

# -*- coding: utf-8 -*-
import asyncio
import concurrent.futures
import inspect
import threading
from contextvars import copy_context
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
        runtime_context = copy_context()
        if inspect.iscoroutinefunction(func):
            # ContextVar 不会随线程自动传播。必须在 event loop 线程中以当前
            # worker 的 context 创建 Task，否则 OCR/日志会退回宿主默认状态。
            result = concurrent.futures.Future()

            def schedule_coroutine():
                try:
                    task = runtime_context.run(
                        asyncio.create_task, func(*args, **kwargs)
                    )
                except BaseException as exc:
                    result.set_exception(exc)
                    return

                def complete(done_task):
                    if done_task.cancelled():
                        result.cancel()
                        return
                    try:
                        result.set_result(done_task.result())
                    except BaseException as exc:
                        result.set_exception(exc)

                task.add_done_callback(complete)

            self._loop.call_soon_threadsafe(schedule_coroutine)
            return result
        else:
            # 对于普通的同步函数，直接包装为协程跑在loop里
            # 这样对于 SQLite 的写入来说，就变成了在单线程(event loop 线程)内的串行执行
            async def wrapper():
                return runtime_context.run(func, *args, **kwargs)
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
            logger.warning("[异步执行器] 刷新超时")
        except Exception as e:
            logger.warning(f"[异步执行器] 刷新错误: {e}")


# 全局唯一实例
async_executor = AsyncExecutor()

import atexit
atexit.register(async_executor.flush)
