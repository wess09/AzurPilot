"""托盘「暂停 / 继续任务」经启动器 WS 的回归测试，配置使用临时目录。"""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from starlette.testclient import TestClient

from module.api.app import create_app
from module.runtime.launcher import LauncherService
from tests.test_api import fixture
from tests.test_launcher_api import HEADERS, HELLO, call


class FakeRuntime:
    """记录 start / stop 调用，维护一份假的运行集合。"""

    def __init__(self, running, names):
        self.running = set(running)
        self.calls = []
        self.configs = SimpleNamespace(names=lambda: list(names))

    def stop(self, name):
        self.calls.append(('stop', name))
        self.running.discard(name)

    def start(self, name):
        self.calls.append(('start', name))
        self.running.add(name)


class LauncherSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict('os.environ', {'AP_WEBUI_TRUST_SECRET': 'test-secret'}):
            self.app = create_app(root=fixture(self.temp.name), password='private-password',
                                  manage_runtime=False, mount_mcp=False)
        self.service = self.app.state.gateway.router.launcher
        self.runtime = FakeRuntime(running=['alas'], names=['alas', 'alt'])
        self.service.runtime = self.runtime
        patcher = patch.object(LauncherService, '_running_names', staticmethod(lambda: sorted(self.runtime.running)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:25548', client=('127.0.0.1', 50000))

    def session(self):
        ws = self.client.websocket_connect('/api/v2/launcher/ws', headers=HEADERS)
        return ws

    def test_requires_handshake(self):
        with self.session() as ws:
            reply = call(ws, 'scheduler.pause')
            self.assertFalse(reply['ok'])
            self.assertEqual(reply['error']['code'], 'UNAUTHORIZED')
        self.assertEqual(self.runtime.calls, [])

    def test_pause_then_resume_restores_same_instances(self):
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            state = call(ws, 'scheduler.state')
            self.assertEqual(state['result']['running'], ['alas'])

            paused = call(ws, 'scheduler.pause')
            self.assertTrue(paused['ok'], paused)
            self.assertEqual(paused['result']['running'], [])
            self.assertEqual(paused['result']['paused'], ['alas'])

            resumed = call(ws, 'scheduler.resume')
            self.assertEqual(resumed['result']['running'], ['alas'])
            self.assertEqual(resumed['result']['paused'], [])
        self.assertEqual(self.runtime.calls, [('stop', 'alas'), ('start', 'alas')])

    def test_resume_without_memory_starts_all_instances(self):
        self.runtime.running.clear()
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            resumed = call(ws, 'scheduler.resume')
        self.assertEqual(resumed['result']['running'], ['alas', 'alt'])

    def test_errors_are_reported_per_instance(self):
        def broken(name):
            raise RuntimeError('boom')
        self.runtime.stop = broken
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            reply = call(ws, 'scheduler.pause')
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['result']['errors'], ['alas: boom'])


if __name__ == '__main__':
    unittest.main()
