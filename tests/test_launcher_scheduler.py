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
    """记录 start / stop 调用，维护 {实例名: 独立任务} 的假运行集合；None 表示主调度器。"""

    def __init__(self, running, names):
        self.running = dict.fromkeys(running)
        self.calls = []
        self.configs = SimpleNamespace(names=lambda: list(names))
        #: 调用时抛异常的实例名，用来模拟停止 / 启动失败。
        self.fail_stop = set()
        self.fail_start = set()
        #: 停止某实例时执行的回调，用来模拟暂停期间有新实例启动。
        self.on_stop = None

    def stop(self, name):
        self.calls.append(('stop', name))
        if name in self.fail_stop:
            raise RuntimeError('stop failed')
        if self.on_stop:
            self.on_stop(name)
        self.running.pop(name, None)

    def start(self, name, task=None):
        self.calls.append(('start', name) if task is None else ('start', name, task))
        if name in self.fail_start:
            raise RuntimeError('start failed')
        self.running[name] = task


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
        patcher = patch.object(LauncherService, '_running_tasks', staticmethod(lambda: dict(self.runtime.running)))
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
        self.runtime.fail_stop.add('alas')
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            reply = call(ws, 'scheduler.pause')
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['result']['errors'], ['alas: stop failed'])

    def test_pause_only_records_instances_actually_stopped(self):
        self.runtime.running = dict.fromkeys(['alas', 'alt'])
        self.runtime.fail_stop.add('alas')
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            reply = call(ws, 'scheduler.pause')
        self.assertEqual(reply['result']['running'], ['alas'])
        self.assertEqual(reply['result']['paused'], ['alt'])
        self.assertEqual(reply['result']['errors'], ['alas: stop failed'])

    def test_repeated_pause_merges_with_earlier_record(self):
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            first = call(ws, 'scheduler.pause')
            self.assertEqual(first['result']['paused'], ['alas'])
            # 第一次暂停之后，另一个实例被启动，再次暂停时不能覆盖旧记录。
            self.runtime.start('alt')
            second = call(ws, 'scheduler.pause', request_id='pause-2')
        self.assertEqual(second['result']['paused'], ['alas', 'alt'])
        self.assertEqual(second['result']['running'], [])

    def test_pause_stops_newcomer_started_during_pause(self):
        def start_newcomer(name):
            if name == 'alas':
                self.runtime.running['alt'] = None
        self.runtime.on_stop = start_newcomer
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            reply = call(ws, 'scheduler.pause')
        self.assertEqual(reply['result']['running'], [])
        self.assertEqual(reply['result']['paused'], ['alas', 'alt'])
        self.assertEqual(self.runtime.calls, [('stop', 'alas'), ('stop', 'alt')])

    def test_empty_pause_does_not_resume_all_instances(self):
        self.runtime.running.clear()
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            paused = call(ws, 'scheduler.pause')
            self.assertEqual(paused['result']['paused'], [])
            resumed = call(ws, 'scheduler.resume')
        self.assertEqual(resumed['result']['running'], [])
        self.assertEqual(self.runtime.calls, [])

    def test_resume_keeps_failed_starts_for_retry(self):
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            self.runtime.running['alt'] = None
            self.assertEqual(sorted(call(ws, 'scheduler.pause')['result']['paused']), ['alas', 'alt'])
            self.runtime.fail_start.add('alt')
            first = call(ws, 'scheduler.resume', request_id='resume-1')
            self.assertEqual(first['result']['running'], ['alas'])
            self.assertEqual(first['result']['paused'], ['alt'])
            self.assertEqual(first['result']['errors'], ['alt: start failed'])

            self.runtime.fail_start.clear()
            before = len(self.runtime.calls)
            second = call(ws, 'scheduler.resume', request_id='resume-2')
        self.assertEqual(self.runtime.calls[before:], [('start', 'alt')])
        self.assertEqual(second['result']['running'], ['alas', 'alt'])
        self.assertEqual(second['result']['paused'], [])

    def test_resume_restores_standalone_task(self):
        self.runtime.running.clear()
        self.runtime.running['alt'] = 'Commission'
        with self.session() as ws:
            self.assertTrue(call(ws, 'session.hello', HELLO)['ok'])
            paused = call(ws, 'scheduler.pause')
            self.assertEqual(paused['result']['paused'], ['alt'])
            resumed = call(ws, 'scheduler.resume')
        self.assertEqual(resumed['result']['running'], ['alt'])
        self.assertEqual(self.runtime.calls, [('stop', 'alt'), ('start', 'alt', 'Commission')])


if __name__ == '__main__':
    unittest.main()
