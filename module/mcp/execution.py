"""同步工具的有限并发执行；设备工作额外使用可终止的子进程。"""
import asyncio
import json
import multiprocessing
import tempfile
import threading
from concurrent.futures import Future
from pathlib import Path

from module.api.protocol import ApiError


class BoundedCalls:
    """超时或客户端取消后仍保留执行槽，直到真实工作结束。"""

    def __init__(self, limit=4):
        self.limit = limit
        self.pending = set()
        self.lock = threading.Lock()
        self.closed = False

    async def run(self, function, *args, timeout=90):
        """
        在受限并发槽中异步执行同步函数。

        Args:
            function: 待执行的同步目标函数。
            *args: 传递给目标函数的位置参数。
            timeout: 执行超时时间（秒），默认 90 秒。

        Returns:
            目标函数的返回值。

        Raises:
            ApiError: 服务关闭 (SERVICE_STOPPING)、槽位已满 (TOOL_BUSY) 或超时 (TOOL_TIMEOUT)。
        """
        future = Future()
        with self.lock:
            if self.closed:
                raise ApiError('SERVICE_STOPPING', 'MCP 服务正在关闭')
            if len(self.pending) >= self.limit:
                raise ApiError('TOOL_BUSY', '工具执行槽已满，请稍后重试')
            # asyncio 包装层被取消时不能取消已交付线程的真实操作。
            future.set_running_or_notify_cancel()
            self.pending.add(future)

        def execute():
            try:
                future.set_result(function(*args))
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                with self.lock:
                    self.pending.discard(future)

        try:
            threading.Thread(target=execute, name='mcp-tool', daemon=True).start()
        except BaseException:
            with self.lock:
                self.pending.discard(future)
            raise
        wrapped = asyncio.wrap_future(future)
        # 超时后的后台异常已通过原请求报告，取走它避免事件循环告警。
        wrapped.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout)
        except TimeoutError as exc:
            raise ApiError('TOOL_TIMEOUT', '工具响应超时，操作可能仍在完成，请查询状态后再重试') from exc

    async def close(self):
        """关闭入口后排空，防止在清理 Manager 后仍有启动操作落地。"""
        with self.lock:
            self.closed = True
            pending = list(self.pending)
        if pending:
            await asyncio.gather(*(asyncio.wrap_future(item) for item in pending), return_exceptions=True)


DEVICE_TIMEOUTS = {
    'get_screenshot': 45, 'restart_emulator': 150, 'restart_adb': 50,
    # 控制类动作包含一次动作前校验帧与一次动作后验证帧，留给设备初始化的余量更多。
    'click': 75, 'swipe': 75, 'long_press': 75,
    'input_text': 60, 'press_key': 60, 'adb_shell': 45,
}


class DeviceCleanupError(ApiError):
    def __init__(self, process):
        super().__init__('DEVICE_CLEANUP_FAILED', '未确认设备进程树退出，已禁用设备工具，请检查服务日志')
        self.process = process


def cleanup_device(process):
    """
    清理并终止设备操作子进程及其子进程树。

    Args:
        process: multiprocessing.Process 实例。

    Raises:
        DeviceCleanupError: 当进程树未能完全退出时抛出。
    """
    from module.runtime.process_control import stop_process_tree

    if not stop_process_tree(process, name='MCP 设备操作', timeout=2, kill_timeout=3):
        # 保留根句柄和亲子关系；不能绕过进程树确认直接 kill 根进程。
        raise DeviceCleanupError(process)
    process.close()


def run_device(operation, instance, params=None):
    """
    在独立子进程中执行设备操作，并在超时时回收整棵进程树。

    Args:
        operation: 操作指令类型，如 'get_screenshot'、'click'、'restart_emulator'。
        instance: 目标 Alas 实例名称。
        params: 设备控制类操作的参数（坐标、文本、观测帧标识等）。

    Returns:
        dict: 工作进程返回的执行结果数据。

    Raises:
        ApiError: 设备操作超时、工作进程异常或操作失败。
    """
    from module.mcp.device_worker import execute

    with tempfile.TemporaryDirectory(prefix='azurpilot-mcp-') as directory:
        result_path = Path(directory) / 'result.json'
        process = multiprocessing.get_context('spawn').Process(
            target=execute, args=(operation, instance, params or {}, str(result_path)),
            name='mcp-device')
        process.start()
        try:
            process.join(DEVICE_TIMEOUTS[operation])
            if process.is_alive():
                raise ApiError('DEVICE_TIMEOUT', '设备操作超时，已请求终止；请检查设备状态后重试')
            if process.exitcode != 0 or not result_path.is_file():
                raise ApiError('DEVICE_FAILED', '设备工作进程未返回结果')
            result = json.loads(result_path.read_text(encoding='utf-8'))
            if 'error' in result:
                raise ApiError(result.get('code') or 'DEVICE_FAILED', result['error'],
                               result.get('details'))
            return result
        finally:
            if process.is_alive():
                cleanup_device(process)
            else:
                process.close()
