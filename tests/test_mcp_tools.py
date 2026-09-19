"""MCP 业务适配回归：使用临时配置和伪运行器，不操作真实设备或更新。"""
import asyncio
import datetime
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.protocol import ApiError
from module.api.runtime_service import RuntimeService
from module.mcp.tools import Tools
from module.mcp.execution import DeviceCleanupError
from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State


def fixture(directory):
    root = Path(directory)
    data = {'Alas': {}, 'Main': {'Scheduler': {'Enable': False, 'NextRun': '2026-01-01 00:00:00'},
                               'Option': {'Count': 2, 'Locked': False, 'Choice': 'a'}}}
    args = {'Main': {'Scheduler': {'Enable': {'type': 'checkbox', 'value': False},
                                  'NextRun': {'type': 'datetime', 'value': '2026-01-01 00:00:00'}},
                     'Option': {'Count': {'value': 2, 'validate': [1, 5]},
                                'Locked': {'value': False, 'display': 'readonly'},
                                'Choice': {'value': 'a', 'option': ['a', 'b']}}}}
    for name, value in [('config/template.json', data), ('config/demo.json', data),
                        ('module/config/argument/args.json', args),
                        ('module/config/argument/menu.json', {}), ('module/config/i18n/zh-CN.json', {})]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    return root


class McpToolsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = fixture(self.directory.name)
        self.configs = ConfigService(self.root)
        self.tools = Tools(self.configs, RuntimeService(self.configs))
        self.addAsyncCleanup(self.tools.close)

    async def invoke(self, name, **arguments):
        return (await self.tools.call(name, arguments))[0].text

    async def test_read_does_not_write_or_create_instances(self):
        path = self.root / 'config/demo.json'
        before = path.read_bytes(), path.stat().st_mtime_ns
        await self.invoke('get_config', instance='demo')
        await self.invoke('get_resources', instance='demo')
        await self.invoke('get_scheduler_queue', instance='demo')
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertIn('NOT_FOUND', await self.invoke('get_config', instance='missing'))
        self.assertFalse((self.root / 'config/missing.json').exists())

    async def test_invalid_updates_are_rejected_without_writes(self):
        before = (self.root / 'config/demo.json').read_bytes()
        for arg, value in [('Count', True), ('Count', 99), ('Locked', True), ('Choice', 'invalid'), ('Unknown', 1)]:
            with self.subTest(arg=arg, value=value):
                result = await self.invoke('update_config', instance='demo', task='Main', group='Option', arg=arg, value=value)
                self.assertIn('Error:', result)
                self.assertEqual(before, (self.root / 'config/demo.json').read_bytes())
        self.assertIn('INVALID_PARAMS', await self.invoke('get_config', instance='../demo'))

    async def test_valid_update_and_schedule_use_atomic_service_patch(self):
        with patch.object(self.configs, 'patch', wraps=self.configs.patch) as patch_config:
            result = await self.invoke('update_config', instance='demo', task='Main', group='Option', arg='Count', value=4)
            self.assertIn('Success:', result)
            patch_config.assert_called_once()
        with patch('module.mcp.tools.current_time', return_value=datetime.datetime(2026, 9, 19, 12, 30, 1, 123456)):
            self.assertIn('Success:', await self.invoke('trigger_task', instance='demo', task='Main'))
        scheduler = self.configs.read('demo')[0]['Main']['Scheduler']
        self.assertEqual({'Enable': True, 'NextRun': '2026-09-19 12:30:01'}, scheduler)
        self.assertIn('Success:', await self.invoke('clear_scheduler_queue', instance='demo'))
        self.assertFalse(self.configs.read('demo')[0]['Main']['Scheduler']['Enable'])

    async def test_invalid_schedule_is_atomic(self):
        self.configs.args['Main']['Scheduler']['NextRun']['display'] = 'readonly'
        before = (self.root / 'config/demo.json').read_bytes()
        self.assertIn('READ_ONLY', await self.invoke('trigger_task', instance='demo', task='Main'))
        self.assertEqual(before, (self.root / 'config/demo.json').read_bytes())

    async def test_clear_queue_reports_and_preserves_readonly_tasks(self):
        path = self.root / 'config/demo.json'
        data = json.loads(path.read_text())
        data['Main']['Scheduler']['Enable'] = True
        data['Restart'] = {'Scheduler': {'Enable': True}}
        path.write_text(json.dumps(data))
        self.configs.args['Restart'] = {'Scheduler': {'Enable': {'value': True, 'display': 'readonly'}}}
        result = await self.invoke('clear_scheduler_queue', instance='demo')
        self.assertIn('保留不可编辑的任务: Restart', result)
        values = self.configs.read('demo')[0]
        self.assertFalse(values['Main']['Scheduler']['Enable'])
        self.assertTrue(values['Restart']['Scheduler']['Enable'])

    async def test_failed_device_cleanup_disables_calls_and_retries_on_close(self):
        process = Mock()
        with patch('module.mcp.tools.run_device', side_effect=DeviceCleanupError(process)) as device:
            self.assertIn('DEVICE_CLEANUP_FAILED', await self.invoke('get_screenshot', instance='demo'))
            self.assertIn('SERVICE_STOPPING', await self.invoke('get_screenshot', instance='demo'))
            self.assertEqual(1, device.call_count)
        with patch('module.mcp.tools.cleanup_device') as cleanup:
            await self.tools.close()
        cleanup.assert_called_once_with(process)

    async def test_initialization_is_shared_across_simultaneous_calls(self):
        tools = Tools()
        self.addAsyncCleanup(tools.close)
        with patch('module.mcp.tools.ConfigService', return_value=self.configs) as configs, \
                patch('module.mcp.tools.RuntimeService', return_value=self.tools.runtime) as runtime:
            await asyncio.gather(*(tools.call('list_instances', {}) for _ in range(4)))
        configs.assert_called_once_with()
        runtime.assert_called_once_with(self.configs)

    async def test_runtime_start_and_stop_failures_do_not_report_success(self):
        manager = Mock(alive=False)
        manager.stop_by_user.return_value = False
        with patch.object(ProcessManager, 'get_manager', return_value=manager), \
                patch.dict(sys.modules, {'module.runtime.updater': SimpleNamespace(updater=SimpleNamespace(event=None))}):
            self.assertIn('START_FAILED', await self.invoke('start_instance', instance='demo'))
            self.assertIn('STOP_FAILED', await self.invoke('stop_instance', instance='demo'))
        manager.start.assert_called_once_with('alas', ev=None)
        manager.stop_by_user.assert_called_once_with()

    async def test_update_uses_shared_service_and_propagates_busy(self):
        with patch.object(State, 'restart_event', threading.Event()), \
                patch.object(State, 'dependency_sync_event', threading.Event()), \
                patch('module.mcp.tools.update_service.start', return_value={'accepted': True}) as start:
            self.assertIn('Success:', await self.invoke('update_alas'))
            start.assert_called_once_with('apply')
            start.side_effect = ApiError('UPDATE_BUSY', '已有更新')
            self.assertIn('UPDATE_BUSY', await self.invoke('update_alas'))

    async def test_standalone_update_refuses_before_starting_work(self):
        with patch.object(State, 'restart_event', None), \
                patch('module.mcp.tools.update_service.start') as start:
            self.assertIn('UPDATE_UNAVAILABLE', await self.invoke('update_alas'))
            start.assert_not_called()

    async def test_device_validation_and_image_contract(self):
        with patch('module.mcp.tools.run_device', return_value={'image': 'YWJj'}) as device:
            self.assertIn('INVALID_PARAMS', await self.invoke('get_screenshot', instance='../demo'))
            device.assert_not_called()
            content = await self.tools.call('get_screenshot', {'instance': 'demo'})
            self.assertEqual(('image', 'image/jpeg', 'YWJj'), (content[0].type, content[0].mimeType, content[0].data))

    async def test_long_device_work_keeps_other_tools_responsive(self):
        entered, release = threading.Event(), threading.Event()

        def device(*args):
            entered.set()
            release.wait(5)
            return {'text': '完成'}

        with patch('module.mcp.tools.run_device', side_effect=device):
            task = asyncio.create_task(self.invoke('restart_emulator', instance='demo'))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                result = await asyncio.wait_for(self.invoke('list_instances'), 0.5)
                self.assertEqual(['demo'], json.loads(result))
            finally:
                release.set()
                await task


if __name__ == '__main__':
    unittest.main()
