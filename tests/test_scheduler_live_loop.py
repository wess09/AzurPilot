"""运行真实配置、任务包装器和主循环，仅替换设备与游戏业务。"""
import json
import gc
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from alas import AzurLaneAutoScript
from module.api.app import create_app
from module.config.config import TaskEnd
from module.exception import GameNotRunningError
from module.scheduler.engine import simulate
from module.scheduler.models import ProgramDocument
from module.scheduler.runtime import SchedulerRuntime
from module.scheduler.templates import builtins, default_program, edge, enhance_program, node
from tests.test_api import fixture


class BoundaryReached(BaseException):
    """到达等待边界后结束隔离验收，不让主循环的恢复逻辑吞掉断言。"""


class LiveLoopTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = fixture(self.directory)
        self.enterContext(patch('module.statistics.resource_stats._LOCAL_DB', str(self.root / 'config/azurstats_local.db')))
        self.path = self.root / 'config/testpilot.json'
        self.time = datetime(2026, 9, 28, 10)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        for task in data.values():
            if 'Scheduler' in task:
                task['Scheduler']['Enable'] = False
                task['Scheduler']['NextRun'] = '2026-09-28 09:00:00'
        data['Alas']['Optimization']['TaskHoardingDuration'] = 0
        data['Alas']['DailySummary']['Enable'] = False
        data['Alas']['Backup']['Enable'] = False
        data['Alas']['EmulatorManagement']['ScheduledEmulatorRestart'] = False
        data['General']['OilControl']['Enable'] = False
        data['General']['YukikazeTaskManager']['TaskPriorityAdjustment'] = 'Main > Research > Commission'
        self.path.write_text(json.dumps(data), encoding='utf-8')
        for module in ('module.config.config', 'module.config.config_updater', 'module.config.utils', 'module.config.watcher', 'module.config.recovery', 'alas'):
            self.enterContext(patch(f'{module}.filepath_config', side_effect=lambda name, *args: str(self.root / f'config/{name}.json')))
        for module in ('module.scheduler.runtime', 'module.config.config', 'alas'):
            self.enterContext(patch(f'{module}.{"now" if module.endswith("runtime") else "current_time"}', side_effect=lambda: self.time))
        self.script = AzurLaneAutoScript('testpilot')
        self.script.stop_event = threading.Event()
        self.script.__dict__['device'] = Mock()
        self.script.__dict__['checker'] = Mock()
        self.script.checker.is_recovered.return_value = False
        self.script._channel_float_done = True
        self.runtime = self.script.__dict__['_program_runtime'] = SchedulerRuntime(self.script, self.root / 'config')
        self.script.wait_until = self.virtual_wait
        self.script._start_watchdog = Mock()
        self.script._is_strict_restart = Mock(return_value=False)
        self.script._record_daily_summary_task_finish = Mock()
        self.script._notify_recoverable = Mock()
        self.script._check_sensitive_exit = Mock()
        self.enterContext(patch('module.config.utils.is_oobe_needed', return_value=False))
        self.enterContext(patch('module.base.backup.backup'))
        self.enterContext(patch('alas.logger.set_file_logger'))
        # 验收失败立即抛出，禁止进入生产的持续恢复与退避等待。
        self.enterContext(patch('alas.time.sleep', side_effect=BoundaryReached('发生意外恢复')))
        self.calls = []
        # Windows 上先回收 SQLite 游标，避免清理临时目录时生成 WAL 辅助文件。
        self.addCleanup(gc.collect)

    def virtual_wait(self, deadline):
        self.time = max(self.time, deadline + timedelta(milliseconds=1))
        if self.time > datetime(2026, 9, 28, 10, 5):
            raise BoundaryReached('程序未在五分钟虚拟时间内选出任务')
        return True

    def apply(self, document, mode='takeover'):
        current = self.runtime.store.get('testpilot')
        self.runtime.store.update('testpilot', current['revision'], active=document.model_dump(),
                                  draft=document.model_dump(), mode=mode, generation=current['generation'] + 1)

    def program(self, **params):
        return ProgramDocument(entry='start', subgraphs=builtins(), nodes=[
            node('start', 'entry'), node('run', 'execute', **params), node('wait', 'wait', seconds=10),
            node('second', 'execute', task='Research')], edges=[edge('start', 'run'),
            *[edge('run', 'wait', result) for result in ('completed', 'yielded', 'recoverable', 'failed')],
            edge('wait', 'second')])

    def finish_research(self):
        self.calls.append('Research')
        self.script.stop_event.set()

    def test_restart_limit_is_loaded_and_deferral_survives_config_reload(self):
        config = self.script.config
        self.assertEqual(config.Error_TaskRestartLimit, 3)
        config.Error_TaskRestartLimit = 2
        self.assertFalse(self.script._record_task_restart('Main', 'recoverable'))
        deadline = datetime(2026, 9, 29)
        with (patch('alas.get_server_next_update', return_value=deadline),
              patch('alas.handle_notify'), patch('alas.notify_webui')):
            self.assertTrue(self.script._record_task_restart('Main', 'recoverable'))
        del self.script.__dict__['config']
        reloaded = self.script.config
        self.assertEqual(reloaded.Error_TaskRestartLimit, 2)
        self.assertEqual(reloaded.cross_get('Main.Scheduler.NextRun'), deadline)

    def test_takeover_program_skips_task_in_restart_cooldown(self):
        self.apply(self.program(task='Main'))
        self.script.task_restart_delays['Main'] = datetime(2026, 9, 29)
        self.script.main = Mock()
        self.script.research = self.finish_research
        self.script.loop()
        self.script.main.assert_not_called()
        self.assertEqual(['Research'], self.calls)
        self.assertEqual('failed', self.runtime.engine.records['results']['Main']['status'])

    def test_real_loop_task_end_wait_reload_and_overlay_cleanup(self):
        original = json.loads(self.path.read_text(encoding='utf-8'))
        self.apply(self.program(overrides={'Campaign_Name': '1-1', 'StopCondition_RunCount': 2}))
        self.runtime.load_program()
        simulated = simulate(self.runtime.engine.document, self.runtime.context())
        def main():
            self.calls.append('Main')
            config = self.script.config
            self.assertEqual('1-1', config.Campaign_Name)
            config.StopCondition_RunCount = 1
            config.load(); config.bind(config.task)
            self.assertEqual(1, config.StopCondition_RunCount)
            config.task_call('Commission')
            self.assertFalse(config.data['Commission']['Scheduler']['Enable'])
            raise TaskEnd
        self.script.main = main
        self.script.research = self.finish_research
        self.script.loop()
        self.assertEqual(['Main', 'Research'], self.calls)
        self.assertEqual(self.calls, [effect['task'] for effect in simulated['effects'] if effect['kind'] == 'execute'])
        self.assertGreaterEqual(self.time, datetime(2026, 9, 28, 10, 0, 10))
        self.assertEqual({}, self.runtime.overlay)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(original['Main']['Campaign']['Name'], saved['Main']['Campaign']['Name'])
        self.assertEqual(original['Main']['StopCondition']['RunCount'], saved['Main']['StopCondition']['RunCount'])
        self.assertEqual('completed', self.runtime.engine.records['results']['Main']['status'])
        self.assertEqual('Commission', self.runtime.requests[0]['task'])

    def test_guard_yields_at_real_task_switch_checkpoint(self):
        self.apply(self.program(guard='builtin.oil.guard'))
        self.runtime.store.observe('testpilot', 'Oil', 5000, self.time.isoformat(), 'fixture')
        def main():
            self.calls.append('Main')
            self.assertFalse(self.script.config.task_switched())
            self.runtime.store.observe('testpilot', 'Oil', 1000, self.time.isoformat(), 'fixture')
            self.assertTrue(self.script.config.task_switched())
            raise TaskEnd
        self.script.main = main
        self.script.research = self.finish_research
        self.script.loop()
        self.assertEqual(['Main', 'Research'], self.calls)
        self.assertEqual('yielded', self.runtime.engine.records['results']['Main']['status'])

    def test_config_cache_reload_keeps_recovery_channel_before_selection(self):
        self.apply(self.program())
        self.runtime.load_program()
        del self.script.__dict__['config']
        before = self.path.read_bytes()
        enabled = self.script.config.data['Restart']['Scheduler']['Enable']
        self.script.config.task_call('Restart')
        self.assertTrue(self.runtime.recovery_requested)
        self.assertEqual(enabled, self.script.config.data['Restart']['Scheduler']['Enable'])
        self.assertEqual(before, self.path.read_bytes())

    def test_first_explicit_recovery_runs_before_business_task(self):
        self.apply(self.program())
        self.runtime.load_program()
        self.runtime.request('Restart')
        self.script.restart = lambda: self.calls.append('Restart')
        self.script.main = lambda: (self.calls.append('Main'), self.script.stop_event.set())
        self.script.loop()
        self.assertEqual(['Restart', 'Main'], self.calls)

    def test_original_template_respects_existing_custom_priority(self):
        config = self.script.config
        for name in ('Main', 'Commission'):
            config.data[name]['Scheduler']['Enable'] = True
        config.write_file('testpilot', config.data)
        doc = self.program()
        doc.nodes.append(node('original', 'call', graph='builtin.original'))
        doc.edges.append(edge('original', 'run', 'value', 'task', True))
        self.apply(doc)
        self.assertEqual('Main', self.script.get_next_task())

    def test_default_program_does_not_idle_behind_pending_restart(self):
        config = self.script.config
        config.data['General']['YukikazeTaskManager']['TaskPriorityAdjustment'] = 'Restart > Main > Commission'
        config.data['Main']['Scheduler']['Enable'] = True
        config.write_file('testpilot', config.data)
        self.apply(default_program())
        self.assertEqual('Main', self.script.get_next_task())

    def test_resource_confirmation_requires_consecutive_visible_frames(self):
        from module.scheduler.resources import stable_read
        visible = iter([True, False, True, True, True])
        reads = iter([41, 41, 42, 42])
        ui = Mock()
        ui.loop.return_value = range(5)
        self.assertEqual(42, stable_read(ui, lambda: next(visible), lambda: next(reads)))

    def test_recoverable_game_error_runs_recovery_then_result_branch(self):
        self.apply(self.program(overrides={'Campaign_Name': '1-1'}))
        def main():
            self.calls.append('Main')
            raise GameNotRunningError
        self.script.main = main
        self.script.restart = lambda: self.calls.append('Restart')
        self.script.research = self.finish_research
        self.script.loop()
        self.assertEqual(['Main', 'Restart', 'Research'], self.calls)
        self.assertEqual('recoverable', self.runtime.engine.records['results']['Main']['status'])
        self.assertEqual({}, self.runtime.overlay)

    def test_business_task_limit_does_not_block_requested_restart(self):
        self.script.config.Error_TaskRestartLimit = 1
        self.apply(self.program())
        deadline = datetime(2026, 9, 29)
        self.script.task_restart_delays['Restart'] = deadline
        self.script.task_restart_record['Restart'] = 3

        def main():
            self.calls.append('Main')
            raise GameNotRunningError

        self.script.main = main
        self.script.restart = lambda: self.calls.append('Restart')
        self.script.research = self.finish_research
        with (patch('alas.get_server_next_update', return_value=deadline),
              patch('alas.handle_notify'), patch('alas.notify_webui')):
            self.script.loop()
        self.assertEqual(['Main', 'Restart', 'Research'], self.calls)
        self.assertEqual({'Main': deadline}, self.script.task_restart_delays)
        self.assertNotIn('Restart', self.script.task_restart_record)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual('2026-09-29 00:00:00', saved['Main']['Scheduler']['NextRun'])

    def test_disabling_restart_limit_releases_persisted_queue_before_selection(self):
        deadline = self.time + timedelta(days=1)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['Alas']['Error']['TaskRestartLimit'] = 0
        data['Main']['Scheduler'].update(Enable=True, NextRun=str(deadline))
        data['Restart']['Scheduler']['NextRun'] = str(self.time + timedelta(hours=3))
        self.path.write_text(json.dumps(data), encoding='utf-8')
        self.script.task_restart_delays = {'Main': deadline}
        self.script.task_restart_record = {'Main': 2}
        self.assertEqual(self.script.get_next_task(), 'Main')
        self.assertEqual(self.script.task_restart_delays, {})
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(str(self.time), saved['Main']['Scheduler']['NextRun'])
        self.assertTrue(saved['Main']['Scheduler']['Enable'])

    def test_disabling_restart_limit_preserves_new_manual_schedule_and_disabled_task(self):
        deadline = self.time + timedelta(days=1)
        manual = deadline + timedelta(hours=3)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['Alas']['Error']['TaskRestartLimit'] = 0
        data['Main']['Scheduler'].update(Enable=True, NextRun=str(manual))
        data['Research']['Scheduler'].update(Enable=False, NextRun=str(deadline))
        self.path.write_text(json.dumps(data), encoding='utf-8')
        self.script.task_restart_delays = {'Main': deadline, 'Research': deadline}
        before = self.path.read_bytes()
        self.script._sync_task_restart_limit()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.script.task_restart_delays, {})

    def test_apply_at_checkpoint_restarts_from_new_entry(self):
        self.apply(self.program())
        def main():
            self.calls.append('Main')
            replacement = ProgramDocument(entry='entry', nodes=[node('entry', 'entry'),
                node('research', 'execute', task='Research')], edges=[edge('entry', 'research')])
            self.apply(replacement)
            self.assertTrue(self.script.config.task_switched())
            raise TaskEnd
        self.script.main = main
        self.script.research = self.finish_research
        self.script.loop()
        self.assertEqual(['Main', 'Research'], self.calls)
        self.assertEqual(datetime(2026, 9, 28, 10), self.time)
        self.assertEqual('entry', self.runtime.engine.document.entry)
        self.assertEqual('yielded', self.runtime.engine.records['results']['Main']['status'])

    def test_waiting_apply_responds_at_next_poll_without_old_task(self):
        doc = ProgramDocument(entry='entry', nodes=[node('entry', 'entry'), node('wait', 'wait', seconds=3600),
            node('old', 'execute')], edges=[edge('entry', 'wait'), edge('wait', 'old')])
        self.apply(doc)
        def waiting(deadline):
            self.virtual_wait(deadline)
            self.apply(ProgramDocument(entry='entry', nodes=[node('entry', 'entry'),
                node('new', 'execute', task='Research')], edges=[edge('entry', 'new')]))
        self.script.wait_until = waiting
        self.assertEqual('Research', self.script.get_next_task())
        self.assertLess((self.time - datetime(2026, 9, 28, 10)).total_seconds(), 5)

    def test_program_fault_does_not_fall_back_to_native_queue(self):
        self.apply(ProgramDocument(entry='entry', nodes=[node('entry', 'entry'), node('math', 'math', operator='/', a=1, b=0),
            node('debug', 'debug')], edges=[edge('entry', 'debug'), edge('math', 'debug', 'value', 'value', True)]))
        self.script.config.get_next = Mock(side_effect=AssertionError('不得回退原调度'))
        self.script.wait_until = Mock(side_effect=BoundaryReached('故障等待'))
        with self.assertRaises(BoundaryReached):
            self.script.get_next_task()
        self.assertIn('卡片程序已停止派发', self.runtime.fault)
        self.assertEqual('math', self.runtime.engine.state.node)
        self.script.config.get_next.assert_not_called()

    def test_automatic_resource_refresh_resumes_same_branch(self):
        doc = ProgramDocument(entry='entry', nodes=[node('entry', 'entry'), node('oil', 'resource'),
            node('check', 'compare', b=2000), node('branch', 'branch'), node('run', 'execute')], edges=[
            edge('entry', 'branch'), edge('oil', 'check', 'value', 'a', True),
            edge('check', 'branch', 'value', 'condition', True), edge('branch', 'run', 'yes')])
        self.apply(doc)
        def refresh():
            self.calls.append('refresh')
            self.assertEqual(['Coin', 'Oil'], self.runtime.refresh_names)
            for name in self.runtime.refresh_names:
                self.runtime.store.observe('testpilot', name, 8000, self.time.isoformat(), 'fixture')
            self.runtime.refresh_result = True
        self.script.scheduler_refresh = refresh
        self.assertEqual('Main', self.script.get_next_task())
        self.assertEqual(['refresh'], self.calls)
        self.assertEqual(8000, self.runtime.engine.context['resources']['Oil']['value'])

    def test_enhance_excludes_disabled_and_future_tasks(self):
        config = self.script.config
        config.data['Main']['Scheduler']['Enable'] = True
        config.data['Commission']['Scheduler']['Enable'] = True
        config.data['Commission']['Scheduler']['NextRun'] = self.time + timedelta(hours=1)
        config.write_file('testpilot', config.data)
        self.apply(enhance_program(), mode='enhance')
        self.assertEqual('Main', self.script.get_next_task())
        self.assertEqual(['Main'], [task['name'] for task in self.runtime.engine.context['tasks']])

    def test_native_mode_still_uses_original_task_selection(self):
        config = self.script.config
        config.data['Main']['Scheduler']['Enable'] = True
        config.write_file('testpilot', config.data)
        # 原调度的最高优先级 Restart 由既有初始化规则启用。
        config.data['Restart']['Scheduler']['Enable'] = False
        self.assertEqual('Main', self.script.get_next_task())
        self.assertEqual('native', self.runtime.mode)
        self.assertIsNone(self.runtime.engine)


class SchedulerSocketTests(unittest.TestCase):
    def test_socket_save_apply_disconnect_and_real_host_selection(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = fixture(directory)
        app = create_app(root=root, password='isolated-test', manage_runtime=False, mount_mcp=False)
        counter = 0
        def request(socket, method, params):
            nonlocal counter
            counter += 1
            identifier = str(counter)
            socket.send_json({'v': 1, 'type': 'request', 'id': identifier, 'method': method, 'params': params})
            while True:
                response = socket.receive_json()
                if response.get('id') == identifier:
                    self.assertTrue(response['ok'], response)
                    return response['result']
        document = ProgramDocument(entry='entry', nodes=[node('entry', 'entry'), node('run', 'execute')],
                                   edges=[edge('entry', 'run')])
        with patch('module.runtime.process_manager.ProcessManager.start') as start, \
                patch('module.device.device.Device.__init__', side_effect=AssertionError('验收禁止连接设备')), \
                TestClient(app) as client:
            with client.websocket_connect('/api/v1/ws') as socket:
                self.assertEqual('session', socket.receive_json()['topic'])
                request(socket, 'auth.login', {'password': 'isolated-test'})
                self.assertTrue(request(socket, 'scheduler.program.catalog', {'instance': 'testpilot'})['cards'])
                current = request(socket, 'scheduler.program.get', {'instance': 'testpilot'})
                params = {'instance': 'testpilot', 'document': document.model_dump()}
                self.assertTrue(request(socket, 'scheduler.program.validate', params)['valid'])
                saved = request(socket, 'scheduler.program.save', {**params, 'revision': current['revision']})
                self.assertEqual('native', saved['mode'])
                result = request(socket, 'scheduler.program.simulate', {**params, 'steps': 5})
                self.assertEqual('Main', next(effect['task'] for effect in result['effects'] if effect['kind'] == 'execute'))
                applied = request(socket, 'scheduler.program.apply', {'instance': 'testpilot', 'revision': saved['revision'], 'mode': 'takeover'})
                self.assertEqual('takeover', applied['mode'])
                self.assertEqual('takeover', request(socket, 'scheduler.program.state', {'instance': 'testpilot'})['mode'])
            # 断开浏览器连接后，从持久方案启动真正的调度宿主。
            for module in ('module.config.config', 'module.config.config_updater', 'module.config.utils', 'module.config.watcher'):
                self.enterContext(patch(f'{module}.filepath_config', side_effect=lambda name, *args: str(root / f'config/{name}.json')))
            script = AzurLaneAutoScript('testpilot')
            script.__dict__['_program_runtime'] = SchedulerRuntime(script, root / 'config')
            self.assertEqual('Main', script.get_next_task())
            self.assertEqual('Main', script._program_runtime.invocation['task'])
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
