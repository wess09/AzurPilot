"""真实共享进程与 ASGI 生命周期的集成回归，隔离所有游戏及网络任务。"""
import tempfile
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from module.api.app import create_app
from module.api import lifecycle
from module.runtime.setting import State
from module.runtime.task_handler import TaskHandler
from tests.test_api import fixture


class ApiLifecycleTests(unittest.TestCase):
    def run_lifecycle(self, fail_start=False, fail_discord=False, fail_discord_start=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = fixture(directory)
            executed = threading.Event()

            def schedule():
                yield
                while True:
                    executed.set()
                    yield

            settings = SimpleNamespace(Run='', StartOcrServer=False, EnableRemoteAccess=False,
                                       DiscordRichPresence=fail_discord_start)
            tasks = TaskHandler()
            stack.enter_context(patch.object(State, '_deploy_config_', settings, create=True))
            stack.enter_context(patch.multiple(State, _init=False, _clearup=False, manager=None,
                                               process_registry=None, _restart_requested=False))
            stack.enter_context(patch('module.runtime.worker_registry.WORKER_REGISTRY_FILE', root / 'workers.json'))
            stack.enter_context(patch('module.runtime.worker_registry.LEGACY_WORKER_REGISTRY_FILE', root / 'old.json'))
            stack.enter_context(patch('module.runtime.updater.updater', SimpleNamespace(delay=0, schedule_update=schedule)))
            stack.enter_context(patch.object(lifecycle, 'task_handler', tasks))
            # 禁止读取用户的自动运行列表或接触设备进程；Manager 与调度线程真实运行。
            stack.enter_context(patch.object(lifecycle.ProcessManager, 'restart_processes'))
            stack.enter_context(patch.object(lifecycle.ProcessManager, 'running_instances', return_value=[]))
            if fail_discord:
                stack.enter_context(patch('module.runtime.discord_presence.async_close_discord_rpc',
                                          new=AsyncMock(side_effect=RuntimeError('模拟 Discord 清理失败'))))
            if fail_discord_start:
                stack.enter_context(patch('module.runtime.discord_presence.init_discord_rpc',
                                          side_effect=RuntimeError('模拟 Discord 启动失败')))
            if fail_start:
                stack.enter_context(patch.object(tasks, 'start', side_effect=RuntimeError('模拟启动失败')))
            app = create_app(root=root, password='', mount_mcp=False)
            if fail_start:
                with self.assertRaisesRegex(RuntimeError, '模拟启动失败'), TestClient(app):
                    pass
            else:
                with TestClient(app) as client:
                    self.assertTrue(executed.wait(timeout=2))
                    self.assertIsNotNone(State.manager)
                    self.assertEqual(200, client.get('/healthz').status_code)
                    with client.websocket_connect('/api/v1/ws') as socket:
                        self.assertEqual('session', socket.receive_json()['topic'])
                        socket.send_json({'v': 1, 'type': 'request', 'id': 'smoke',
                                          'method': 'system.ping', 'params': {}})
                        self.assertEqual({'pong': True}, socket.receive_json()['result'])
            self.assertIsNone(State.manager)
            self.assertTrue(State._clearup)
            self.assertFalse(tasks._thread and tasks._thread.is_alive())

    def test_real_manager_and_background_scheduler_start_and_stop(self):
        self.run_lifecycle()

    def test_partial_startup_failure_releases_manager(self):
        self.run_lifecycle(fail_start=True)

    def test_discord_cleanup_failure_releases_real_manager(self):
        self.run_lifecycle(fail_discord=True)

    def test_discord_startup_failure_keeps_webui_available(self):
        self.run_lifecycle(fail_discord_start=True)
