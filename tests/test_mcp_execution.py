"""验证工具超时仍保留执行槽、关闭排空及设备子进程回收。"""
import asyncio
import json
import multiprocessing
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from module.api.protocol import ApiError
from module.mcp.device_worker import restart_adb
from module.mcp.execution import BoundedCalls, DEVICE_TIMEOUTS, DeviceCleanupError, run_device
from module.runtime.setting import State


def fake_device_result(operation, instance, result_path):
    Path(result_path).write_text(json.dumps({'text': f'{operation}:{instance}'}), encoding='utf-8')


def fake_device_hang(operation, instance, result_path):
    time.sleep(60)


class BoundedCallsTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_close_does_not_cancel_thread_future(self):
        runner = BoundedCalls(limit=1)
        entered, release = threading.Event(), threading.Event()

        def work():
            entered.set()
            release.wait(5)
            return '完成'

        task = asyncio.create_task(runner.run(work))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            future = next(iter(runner.pending))
            closing = asyncio.create_task(runner.close())
            await asyncio.sleep(0)
            closing.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await closing
            self.assertFalse(future.cancelled())
        finally:
            release.set()
            await runner.close()
        self.assertEqual('完成', await task)
        self.assertEqual('完成', future.result())

    async def test_timeout_keeps_capacity_and_close_drains_work(self):
        runner = BoundedCalls(limit=1)
        release = threading.Event()
        try:
            with self.assertRaisesRegex(ApiError, '超时'):
                await runner.run(release.wait, 5, timeout=0.01)
            with self.assertRaisesRegex(ApiError, '执行槽已满'):
                await runner.run(lambda: None)
            closing = asyncio.create_task(runner.close())
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
            with self.assertRaisesRegex(ApiError, '正在关闭'):
                await runner.run(lambda: None)
        finally:
            release.set()
            await runner.close()
        await closing

    async def test_cancellation_does_not_free_capacity(self):
        runner = BoundedCalls(limit=1)
        entered, release = threading.Event(), threading.Event()

        def work():
            entered.set()
            release.wait(5)

        task = asyncio.create_task(runner.run(work))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            with self.assertRaisesRegex(ApiError, '执行槽已满'):
                await runner.run(lambda: None)
        finally:
            release.set()
            await runner.close()


class DeviceExecutionTest(unittest.TestCase):
    def test_real_spawn_returns_result_without_loading_device(self):
        with patch('module.mcp.device_worker.execute', fake_device_result):
            self.assertEqual({'text': 'get_screenshot:demo'}, run_device('get_screenshot', 'demo'))

    def test_real_spawn_timeout_reaps_child(self):
        started = time.monotonic()
        with patch('module.mcp.device_worker.execute', fake_device_hang), \
                patch.dict(DEVICE_TIMEOUTS, {'get_screenshot': 0.2}):
            with self.assertRaisesRegex(ApiError, '设备操作超时'):
                run_device('get_screenshot', 'demo')
        self.assertLess(time.monotonic() - started, 10)
        self.assertFalse(any(process.name == 'mcp-device' for process in multiprocessing.active_children()))

    def test_device_timeout_stops_tree_and_closes_handle(self):
        process = Mock()
        process.is_alive.side_effect = [True, True]
        context = Mock()
        context.Process.return_value = process
        with patch('module.mcp.execution.multiprocessing.get_context', return_value=context), \
                patch('module.runtime.process_control.stop_process_tree', return_value=True) as stop:
            with self.assertRaisesRegex(ApiError, '设备操作超时'):
                run_device('get_screenshot', 'demo')
        process.join.assert_called_once_with(45)
        stop.assert_called_once_with(process, name='MCP 设备操作', timeout=2, kill_timeout=3)
        process.close.assert_called_once_with()

    def test_failed_tree_cleanup_preserves_root_handle(self):
        process = Mock()
        process.is_alive.return_value = True
        context = Mock()
        context.Process.return_value = process
        with patch('module.mcp.execution.multiprocessing.get_context', return_value=context), \
                patch('module.runtime.process_control.stop_process_tree', return_value=False):
            with self.assertRaises(DeviceCleanupError) as error:
                run_device('get_screenshot', 'demo')
        self.assertIs(process, error.exception.process)
        process.kill.assert_not_called()
        process.close.assert_not_called()

    def test_adb_commands_have_timeout_and_failures_propagate(self):
        with patch.object(State, '_deploy_config_', Mock(AdbExecutable='adb'), create=True), \
                patch('module.mcp.device_worker.os.path.exists', return_value=True), \
                patch('module.mcp.device_worker.subprocess.run') as run:
            restart_adb()
            self.assertEqual([['adb', 'kill-server'], ['adb', 'start-server']], [call.args[0] for call in run.call_args_list])
            for call in run.call_args_list:
                self.assertTrue(call.kwargs['check'])
                self.assertEqual(20, call.kwargs['timeout'])
            run.reset_mock()
            run.side_effect = TimeoutError('模拟超时')
            with self.assertRaises(TimeoutError):
                restart_adb()
            self.assertEqual(1, run.call_count)


if __name__ == '__main__':
    unittest.main()
