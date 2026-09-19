"""总览状态、被动截图和统计口径回归，禁止连接真实模拟器。"""
import asyncio
import base64
import io
import multiprocessing
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
from PIL import Image

from module.api.runtime_service import RuntimeService
from module.api.socket import Gateway, Session
from module.api.statistics_service import report, series
from module.runtime.preview import PreviewHub


def emit_screenshot(output):
    """独立进程中运行真实统一截图入口，用假后端代替模拟器。"""
    from module.runtime.preview import initialize
    from module.device.screenshot import Screenshot
    initialize('preview-test', output, lambda _: None, 'test-run')
    device = Screenshot.__new__(Screenshot)
    device.config = SimpleNamespace(Emulator_ScreenshotMethod='test', Emulator_ScreenshotDedithering=False, Error_SaveError=False)
    device.__dict__['screenshot_methods'] = {'test': lambda: np.full((720, 1280, 3), (235, 30, 10), dtype=np.uint8)}
    device._screenshot_interval = SimpleNamespace(wait=lambda: None, reset=lambda: None)
    device.check_screen_size = lambda: True
    device.check_screen_black = lambda: True
    device.screenshot()
    # 等待编码完成再退出子进程，避免 daemon 编码线程被测试提前回收。
    import time
    deadline = time.monotonic() + 5
    while output.empty() and time.monotonic() < deadline:
        time.sleep(.01)


class RuntimeTests(unittest.TestCase):
    def test_instances_only_expose_live_current_task(self):
        configs = SimpleNamespace(names=lambda: ['pilot'], read=lambda _: ({'Alas': {}}, 'revision'))
        manager = SimpleNamespace(state=1, current_task='Commission')
        with patch('module.api.runtime_service.ProcessManager._processes', {'pilot': manager}):
            runtime = RuntimeService(configs)
            self.assertEqual(runtime.instances()[0]['currentTask'], 'Commission')
            for state in (2, 3, 4):
                manager.state = state
                self.assertIsNone(runtime.instances()[0]['currentTask'])

    def test_three_task_states_and_stopped_worker(self):
        data = {'Alas': {}, 'General': {},
                'Main': {'Scheduler': {'Enable': True, 'NextRun': '2020-01-01 00:00:00'}},
                'Commission': {'Scheduler': {'Enable': True, 'NextRun': '2099-01-01 00:00:00'}},
                'Research': {'Scheduler': {'Enable': True, 'NextRun': '2099-01-01 00:00:00'}}}
        configs = SimpleNamespace(read=lambda _: (data, 'revision'), translate=Mock())
        manager = SimpleNamespace(state=1, current_task='Commission')
        with patch('module.api.runtime_service.ProcessManager._processes', {'pilot': manager}), \
                patch('module.config.time_source.now', return_value=datetime(2026, 9, 13)):
            runtime = RuntimeService(configs)
            tasks = runtime.overview('pilot')['tasks']
            self.assertEqual('Commission', tasks[0]['name'])
            self.assertEqual({'running', 'waiting', 'pending'}, {task['state'] for task in tasks})
            self.assertTrue(all('label' not in task for task in tasks))
            configs.translate.assert_not_called()
            manager.state = 2
            self.assertNotIn('running', {task['state'] for task in runtime.overview('pilot')['tasks']})

    def test_overview_preserves_action_point_total(self):
        data = {'Dashboard': {'ActionPoint': {'Value': 101, 'Total': 1301, 'Record': '2026-09-16 12:00:00'}}}
        configs = SimpleNamespace(read=lambda _: (data, 'revision'), translate=Mock(return_value='行动力'))
        with patch('module.api.runtime_service.ProcessManager._processes', {}):
            resource = RuntimeService(configs).overview('pilot')['resources'][0]
        self.assertEqual('ActionPoint', resource['name'])
        self.assertEqual(101, resource['value'])
        self.assertEqual(1301, resource['total'])

    def test_logs_preserves_spaces_for_level_0_rule_title_and_tracebacks(self):
        from rich.rule import Rule
        from rich.text import Text
        manager = SimpleNamespace(renderables=[
            Rule(characters='═'),
            Rule('COMMISSION', characters=' '),
            Rule(characters='═'),
            Text('    indented text\n'),
        ])
        configs = SimpleNamespace(path=Mock())
        with patch('module.api.runtime_service.ProcessManager._processes', {'pilot': manager}):
            runtime = RuntimeService(configs)
            logs = runtime.logs('pilot')
            entries = logs['entries']
            self.assertEqual(4, len(entries))
            self.assertTrue(entries[1]['text'].startswith('   '))
            self.assertTrue(entries[1]['text'].endswith('   '))
            self.assertEqual('COMMISSION', entries[1]['text'].strip())
            self.assertTrue(entries[3]['text'].startswith('    '))

    def test_capture_is_cached_and_never_launches_adb(self):
        hub = PreviewHub()
        configs = SimpleNamespace(path=Mock())
        with patch('module.runtime.preview.hub', hub), patch('subprocess.run') as process:
            runtime = RuntimeService(configs)
            self.assertIsNone(runtime.capture('pilot')['image'])
            frame = {'instance': 'pilot', 'image': 'encoded', 'capturedAt': 'time'}
            hub.publish('pilot', frame)
            self.assertEqual(frame, runtime.capture('pilot'))
            self.assertIsNone(runtime.capture('other')['image'])
            process.assert_not_called()

    def test_screenshot_crosses_process_boundary_and_preserves_rgb(self):
        context = multiprocessing.get_context('spawn')
        with context.Manager() as manager:
            output = manager.Queue(maxsize=2)
            process = context.Process(target=emit_screenshot, args=(output,))
            process.start()
            try:
                frame = output.get(timeout=20)
                self.assertEqual('preview-test', frame['instance'])
                self.assertEqual('test-run', frame['runId'])
                with Image.open(io.BytesIO(base64.b64decode(frame['image'].split(',')[1]))) as image:
                    self.assertEqual((1280, 720), image.size)
                    red, _, blue = image.getpixel((0, 0))
                    self.assertGreater(red, 200)
                    self.assertLess(blue, 30)
            finally:
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)

    def test_all_registered_screenshot_backends_use_publication(self):
        from module.device.screenshot import Screenshot
        names = ['ADB', 'ADB_nc', 'uiautomator2', 'aScreenCap', 'aScreenCap_nc', 'DroidCast', 'DroidCast_raw', 'scrcpy', 'nemu_ipc', 'ldopengl']
        for name in names:
            with self.subTest(name=name):
                device = Screenshot.__new__(Screenshot)
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                device.config = SimpleNamespace(Emulator_ScreenshotMethod=name, Emulator_ScreenshotDedithering=False, Error_SaveError=False)
                device.__dict__['screenshot_methods'] = {name: Mock(return_value=frame)}
                device._screenshot_interval = Mock()
                device.check_screen_size = device.check_screen_black = lambda: True
                with patch('module.device.screenshot.publish') as publish:
                    self.assertIs(frame, device.screenshot())
                    publish.assert_called_once_with(frame)

    def test_slow_preview_replaces_frame_without_filling_control_queue(self):
        async def check():
            session = Session(Gateway(None, ''), SimpleNamespace(close=AsyncMock()))
            for index in range(100):
                await session.event('preview', {'instance': 'pilot', 'image': str(index)})
            self.assertEqual(1, session.queue.qsize())
            self.assertEqual('99', session.preview_pending['data']['image'])
        asyncio.run(check())

    def test_slow_logs_merge_without_filling_control_queue(self):
        async def check():
            session = Session(Gateway(None, ''), SimpleNamespace(close=AsyncMock()))
            for index in range(100):
                await session.event('logs', {
                    'instance': 'pilot', 'cursor': index + 1, 'reset': False,
                    'entries': [{'id': index + 1, 'level': 'INFO', 'text': str(index)}],
                })
            self.assertEqual(1, session.queue.qsize())
            self.assertEqual(100, len(session.log_pending['data']['entries']))
            self.assertEqual(100, session.log_pending['data']['cursor'])
        asyncio.run(check())

    def test_log_emit_streams_few_entries_and_batches_history(self):
        async def check():
            session = Session(Gateway(None, ''), SimpleNamespace(close=AsyncMock()))
            await session._emit_logs({
                'instance': 'pilot', 'cursor': 3, 'reset': False,
                'entries': [{'id': index, 'level': 'INFO', 'text': text} for index, text in enumerate(('a', 'b', 'c'), 1)],
            })
            self.assertEqual(3, session.queue.qsize())
            first = session.queue.get_nowait()
            self.assertEqual('logs', first['topic'])
            self.assertEqual('a', first['data']['entries'][0]['text'])

            session = Session(Gateway(None, ''), SimpleNamespace(close=AsyncMock()))
            entries = [{'id': index, 'level': 'INFO', 'text': str(index)} for index in range(9)]
            await session._emit_logs({'instance': 'pilot', 'cursor': 9, 'reset': False, 'entries': entries}, stream=False)
            self.assertEqual(1, session.queue.qsize())
            self.assertEqual(9, len(session.log_pending['data']['entries']))
        asyncio.run(check())

    def test_log_subscription_wakes_on_append_and_unsubscribes(self):
        async def check():
            from module.api.protocol import SubscribeParams
            from module.runtime.log_hub import LogHub
            hub = LogHub()
            runtime = SimpleNamespace(logs=Mock(return_value={
                'instance': 'pilot', 'cursor': 1, 'reset': False,
                'entries': [{'id': 1, 'level': 'INFO', 'text': 'hello'}],
            }))
            session = Session(Gateway(SimpleNamespace(runtime=runtime), ''), SimpleNamespace(close=AsyncMock()))
            session.subscription = SubscribeParams(instance='pilot', topics=['logs'])
            session.logs_primed = True
            with patch('module.runtime.log_hub.hub', hub):
                task = asyncio.create_task(session.log_producer())
                await asyncio.sleep(0)
                hub.publish('other')
                await asyncio.sleep(0)
                self.assertTrue(session.queue.empty())
                hub.publish('pilot')
                message = await asyncio.wait_for(session.queue.get(), timeout=.5)
                self.assertEqual('hello', message['data']['entries'][0]['text'])
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self.assertEqual(set(), hub.listeners)
        asyncio.run(check())

    def test_preview_subscription_wakes_on_frame_and_unsubscribes(self):
        async def check():
            from module.api.protocol import SubscribeParams
            hub = PreviewHub()
            session = Session(Gateway(None, ''), SimpleNamespace(close=AsyncMock()))
            session.subscription = SubscribeParams(instance='pilot', topics=['preview'])
            with patch('module.runtime.preview.hub', hub):
                task = asyncio.create_task(session.preview_producer())
                await asyncio.sleep(0)
                hub.publish('other', {'instance': 'other', 'image': 'wrong'})
                await asyncio.sleep(0)
                self.assertTrue(session.queue.empty())
                hub.publish('pilot', {'instance': 'pilot', 'image': 'new'})
                await asyncio.wait_for(session.queue.get(), timeout=.5)
                self.assertEqual('new', session.preview_pending['data']['image'])
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self.assertEqual(set(), hub.listeners)
        asyncio.run(check())


class StatisticsTests(unittest.TestCase):
    def test_series_keeps_zero_skips_missing_and_sorts(self):
        data = series([{'ts': '2026-09-13 12:00:00', 'ap': 0}, {'ts': '2026-09-13 10:00:00', 'ap': 10},
                       {'ts': '2026-09-13 11:00:00'}, {'ts': 'bad', 'ap': 2}, {'ts': '2026-09-13', 'ap': float('nan')}], 'ap', '行动力')
        self.assertEqual([10, 0], [point['value'] for point in data['points']])

    def test_opsi_preserves_old_rounding_and_five_ap_cost(self):
        summary = {'total_battles': 5, 'akashi_encounters': 2, 'siren_research_devices': 1}
        with patch('module.statistics.opsi_month.get_opsi_stats', return_value=SimpleNamespace(summary=lambda *_: summary)), \
                patch('module.statistics.opsi_month.compute_monthly_cl1_akashi_ap', return_value=100), \
                patch('module.statistics.cl1_database.db.get_meow_stats', return_value={}):
            result = report(SimpleNamespace(path=lambda _: None), 'pilot', 'opsi', '2026-09', 7, 'month')
        values = {item['label']: item['value'] for item in result['metrics']}
        self.assertEqual(3, values['出击轮数'])
        self.assertEqual(15, values['出击消耗'])
        self.assertEqual(85, values['净行动力'])

    def test_action_sources_and_commission_records_keep_time_and_scope(self):
        raw = {'ap_snapshots': [{'ts': '2026-09-01 12:00:00', 'ap': 0, 'asset': 50, 'distance': 100, 'source': 'cl1'}],
               'coins_snapshots': [{'ts': '2026-09-02 13:00:00', 'yellow_coins': 200, 'purple_coins': 5}]}
        entries = [{'ts': '2026-09-01 12:00:00', 'commission_count': 2, 'items': {'Gems': 7, 'Cubes': 3}},
                   {'ts': '2026-09-02 12:00:00', 'commission_count': 1, 'items': {}},
                   {'ts': '2026-10-01 00:00:00', 'items': {'Gem': 999}}]
        database = SimpleNamespace(get_stats=Mock(return_value=raw), get_commission_income=Mock(side_effect=lambda instance, year, month: entries if month == 9 else []))
        configs = SimpleNamespace(path=lambda _: None)
        with patch('module.statistics.cl1_database.db', database), \
                patch('module.statistics.opsi_month.cl1_db', database), \
                patch('module.statistics.commission_income_stats.cl1_db', database):
            action = report(configs, 'pilot', 'action', '2026-09', 7, 'month')
            self.assertEqual(5, len(action['series']))
            self.assertEqual(0, action['series'][0]['points'][0]['value'])
            self.assertEqual('2026-09-02 13:00:00', action['series'][3]['points'][0]['time'])
            income = report(configs, 'pilot', 'commission', '2026-09', 7, 'month')
            metrics = {item['label']: item['value'] for item in income['metrics']}
            self.assertEqual(7, metrics['钻石'])
            self.assertEqual(3, metrics['完成委托'])
            self.assertEqual(2, len(income['tables'][1]['rows']))
            self.assertEqual({'index': 0, 'descending': True}, income['tables'][1]['defaultSort'])
            self.assertEqual(3, income['series'][1]['points'][0]['value'])
            database.get_commission_income.assert_called_with('pilot', 2026, 9)

    def test_ship_progress_and_daily_efficiency_are_exposed(self):
        from module.statistics.ship_exp_stats import ShipExpStats
        with tempfile.TemporaryDirectory() as directory:
            stats = ShipExpStats(path=Path(directory) / 'ships.json')
            stats.data = {'target_level': 125, 'ships': [{'position': 1, 'level': 100, 'current_exp': 500, 'total_exp': 100000}],
                          'daily_stats': {'2026-09-01': {'battle_count': 10, 'total_exp_gained': 1000, 'total_run_time': 500}}}
            with patch('module.statistics.ship_exp_stats.ShipExpStats', return_value=stats), \
                    patch('module.statistics.opsi_month.get_opsi_stats', return_value=SimpleNamespace(summary=lambda: {'total_battles': 10})):
                result = report(SimpleNamespace(path=lambda _: None), 'pilot', 'ships', None, 7, 'month')
            self.assertEqual(9, len(result['tables'][0]['rows'][0]))
            self.assertEqual(1000, result['series'][0]['points'][0]['value'])

    def test_loot_keeps_legacy_columns_and_refreshes_local_cache(self):
        from module.api.statistics_service import refresh_loot
        with patch('module.statistics.azurstats.AzurStats.load_meowofficer_farming', return_value=np.array([[3, 1000000000, 2, 10, 1, .5, .25]])), \
                patch('module.statistics.azurstats.AzurStats.get_meowofficer_farming') as refresh:
            configs = SimpleNamespace(path=lambda _: None)
            result = report(configs, 'pilot', 'loot', None, 7, 'month')
            self.assertEqual(7, len(result['tables'][0]['columns']))
            self.assertEqual(.25, result['tables'][0]['rows'][0][-1])
            self.assertTrue(refresh_loot(configs, 'pilot')['refreshed'])
            refresh.assert_called_once()


if __name__ == '__main__':
    unittest.main()
