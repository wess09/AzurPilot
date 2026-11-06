"""MCP 结构化工具契约回归：不操作真实设备或更新。"""
import asyncio
import datetime
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import jsonschema
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.protocol import ApiError
from module.api.runtime_service import RuntimeService
from module.mcp.tools import Tools
from module.mcp.execution import DeviceCleanupError
from module.mcp.registry import TOOL_BY_NAME
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


def screenshot_result():
    return {'image': 'YWJj', 'frame_id': 'f' * 32, 'width': 1280, 'height': 720,
            'orientation': 'landscape', 'captured_at': '2026-11-06T10:00:00+00:00',
            'cached': False, 'backend': 'ADB'}


class McpToolsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = fixture(self.directory.name)
        self.configs = ConfigService(self.root)
        self.runtime = RuntimeService(self.configs)
        self.tools = Tools(self.configs, self.runtime)
        self.addAsyncCleanup(self.tools.close)

    async def invoke(self, name, **arguments):
        return await self.tools.call(name, arguments)

    async def data(self, name, **arguments):
        result = await self.invoke(name, **arguments)
        self.assertFalse(result.isError, result.content[0].text)
        jsonschema.validate(result.structuredContent, TOOL_BY_NAME[name].output)
        return result.structuredContent

    async def error(self, name, **arguments):
        result = await self.invoke(name, **arguments)
        self.assertTrue(result.isError)
        self.assertEqual('failed', result.structuredContent['status'])
        return result.structuredContent

    def read_config(self):
        return self.configs.read('demo')[0]

    async def test_read_does_not_write_or_create_instances(self):
        path = self.root / 'config/demo.json'
        before = path.read_bytes(), path.stat().st_mtime_ns
        config = await self.data('azurpilot_get_config', instance='demo', path='Main.Option.Count')
        self.assertEqual(2, config['values'])
        context = await self.data('azurpilot_get_context', instance='demo')
        self.assertEqual('stopped', context['instance_status'])
        self.assertIsNone(context['current_task'])
        self.assertIn('device', context)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        error = await self.error('azurpilot_get_config', instance='missing')
        self.assertEqual('NOT_FOUND', error['error']['code'])
        self.assertFalse((self.root / 'config/missing.json').exists())

    async def test_context_merges_schedule_resources_and_recent_error(self):
        path = self.root / 'config/demo.json'
        data = json.loads(path.read_text())
        data['_stockInstance'] = 'test-identity'
        data['Dashboard'] = {'Oil': {'Value': 123, 'Limit': 500}}
        data['Main']['Scheduler']['Enable'] = True
        path.write_text(json.dumps(data), encoding='utf-8')
        self.runtime.logs = Mock(return_value={'cursor': 1, 'reset': False, 'entries': [
            {'id': 1, 'level': 'ERROR', 'text': '模拟错误'}]})
        context = await self.data('azurpilot_get_context', instance='demo')
        self.assertEqual('Main', context['schedule'][0]['task'])
        self.assertEqual(123, context['resources']['Oil']['value'])
        self.assertEqual('模拟错误', context['recent_error']['text'])
        self.assertEqual('test-identity', self.read_config()['_stockInstance'])

    async def test_task_search_and_schema_are_compact_and_describe_writability(self):
        found = await self.data('azurpilot_search_tasks', query='mai')
        self.assertEqual(['Main'], [item['task'] for item in found['tasks']])
        schema = await self.data('azurpilot_get_task_schema', task='Main')
        option = schema['groups']['Option']['arguments']
        self.assertTrue(option['Count']['writable'])
        self.assertFalse(option['Locked']['writable'])
        self.assertEqual(['a', 'b'], option['Choice']['options'])
        self.assertEqual('Main.Option.Count', option['Count']['path'])
        missing = await self.error('azurpilot_get_task_schema', task='Missing')
        self.assertEqual('NOT_FOUND', missing['error']['code'])
        self.assertEqual('azurpilot_search_tasks', missing['next_step']['tool'])

    async def test_task_search_understands_colloquial_chinese_and_ranks_results(self):
        self.configs.translations = {
            'Task': {'Main': {'name': '每日任务'}},
            'Main': {'Option': {'_info': {'name': '日常选项'},
                                'Count': {'name': '次数', 'help': '每日清空'}}},
        }
        found = await self.invoke('azurpilot_search_tasks', query='日常')
        self.assertFalse(found.isError, found.content[0].text)
        self.assertEqual(['Main'], [item['task'] for item in found.structuredContent['tasks']])
        self.assertEqual('每日任务', found.structuredContent['tasks'][0]['display_name'])
        self.assertIn('Main(每日任务)', found.content[0].text)
        group = await self.data('azurpilot_search_tasks', query='option')
        self.assertEqual(['Main'], [item['task'] for item in group['tasks']])
        missing = await self.invoke('azurpilot_search_tasks', query='不存在的关键词')
        self.assertEqual([], missing.structuredContent['tasks'])
        self.assertIn('未找到', missing.content[0].text)

    async def test_unknown_fields_and_invalid_values_are_correctable_without_writes(self):
        before = (self.root / 'config/demo.json').read_bytes()
        revision = self.configs.read('demo')[1]
        unknown = await self.error('azurpilot_patch_config', instance='demo', revision=revision,
                                   changes=[{'path': 'Main.Option.Count', 'value': 4}], typo=True)
        self.assertEqual('INVALID_PARAMS', unknown['error']['code'])
        self.assertEqual('additionalProperties', unknown['error']['details']['rule'])
        self.assertFalse(unknown['error']['retryable'])
        for arg, value, code in [('Count', True, 'INVALID_PARAMS'), ('Count', 99, 'INVALID_PARAMS'),
                                 ('Locked', True, 'READ_ONLY'), ('Choice', 'invalid', 'INVALID_PARAMS'),
                                 ('Unknown', 1, 'NOT_FOUND')]:
            with self.subTest(arg=arg, value=value):
                result = await self.error('azurpilot_patch_config', instance='demo', revision=revision,
                                          changes=[{'path': f'Main.Option.{arg}', 'value': value}])
                self.assertEqual(code, result['error']['code'])
                if code == 'NOT_FOUND':
                    self.assertEqual('azurpilot_get_task_schema', result['next_step']['tool'])
                self.assertEqual(before, (self.root / 'config/demo.json').read_bytes())
        self.assertEqual('INVALID_PARAMS',
                         (await self.error('azurpilot_get_config', instance='../demo'))['error']['code'])

    async def test_patch_is_atomic_supports_dry_run_and_returns_diff(self):
        revision = self.configs.read('demo')[1]
        before = (self.root / 'config/demo.json').read_bytes()
        preview = await self.invoke('azurpilot_patch_config', instance='demo', revision=revision, dry_run=True,
                                    changes=[{'path': 'Main.Option.Count', 'value': 4},
                                             {'path': 'Main.Option.Choice', 'value': 'b'}])
        self.assertTrue(preview.structuredContent['dry_run'])
        self.assertEqual(4, preview.structuredContent['changes'][0]['after'])
        self.assertIn('2 → 4', preview.content[0].text)
        self.assertIn('未写入', preview.content[0].text)
        self.assertEqual(before, (self.root / 'config/demo.json').read_bytes())
        with patch.object(self.configs, 'patch', wraps=self.configs.patch) as patch_config:
            saved = await self.data('azurpilot_patch_config', instance='demo', revision=revision,
                                    changes=[{'path': 'Main.Option.Count', 'value': 4},
                                             {'path': 'Main.Option.Choice', 'value': 'b'}])
            patch_config.assert_called_once()
        self.assertEqual(2, saved['changes'][0]['before'])
        self.assertEqual('b', saved['changes'][1]['after'])
        self.assertNotEqual(revision, saved['revision'])
        self.assertEqual(4, self.read_config()['Main']['Option']['Count'])

    async def test_stale_revision_is_rejected_before_any_field_writes(self):
        stale = self.configs.read('demo')[1]
        current = self.configs.read('demo')[0]
        current['Main']['Option']['Count'] = 3
        (self.root / 'config/demo.json').write_text(json.dumps(current), encoding='utf-8')
        before = (self.root / 'config/demo.json').read_bytes()
        error = await self.error('azurpilot_patch_config', instance='demo', revision=stale,
                                 changes=[{'path': 'Main.Option.Choice', 'value': 'b'}])
        self.assertEqual('CONFLICT', error['error']['code'])
        self.assertEqual('azurpilot_get_config', error['next_step']['tool'])
        self.assertEqual(before, (self.root / 'config/demo.json').read_bytes())

    async def test_schedule_reports_scheduling_not_task_completion(self):
        with patch('module.mcp.tools.current_time', return_value=datetime.datetime(2026, 9, 19, 12, 30, 1)):
            result = await self.data('azurpilot_set_task_schedule', instance='demo', task='Main',
                                     enabled=True, next_run='2026-09-19 12:30:01')
        self.assertTrue(result['scheduled'])
        self.assertFalse(result['running'])
        self.assertEqual({'Enable': True, 'NextRun': '2026-09-19 12:30:01'},
                         self.read_config()['Main']['Scheduler'])
        disabled = await self.data('azurpilot_set_task_schedule', instance='demo', task='Main', enabled=False)
        self.assertFalse(disabled['scheduled'])
        self.assertEqual('2026-09-19 12:30:01', disabled['next_run'])

    async def test_schedule_requires_a_change_and_is_atomic(self):
        self.assertEqual('INVALID_PARAMS',
                         (await self.error('azurpilot_set_task_schedule', instance='demo', task='Main'))['error']['code'])
        self.configs.args['Main']['Scheduler']['NextRun']['display'] = 'readonly'
        before = (self.root / 'config/demo.json').read_bytes()
        result = await self.error('azurpilot_set_task_schedule', instance='demo', task='Main',
                                  enabled=True, next_run='2026-01-01 00:00:00')
        self.assertEqual('READ_ONLY', result['error']['code'])
        self.assertEqual(before, (self.root / 'config/demo.json').read_bytes())

    async def test_clear_queue_is_legacy_only_and_reports_readonly_tasks(self):
        self.assertEqual('UNKNOWN_TOOL',
                         (await self.error('clear_scheduler_queue', instance='demo'))['error']['code'])
        legacy = Tools(self.configs, self.runtime, allow_legacy=True)
        self.addAsyncCleanup(legacy.close)
        path = self.root / 'config/demo.json'
        data = json.loads(path.read_text())
        data['Main']['Scheduler']['Enable'] = True
        data['Restart'] = {'Scheduler': {'Enable': True}}
        path.write_text(json.dumps(data))
        self.configs.args['Restart'] = {'Scheduler': {'Enable': {'value': True, 'display': 'readonly'}}}
        result = await legacy.call('clear_scheduler_queue', {'instance': 'demo'})
        self.assertFalse(result.isError)
        self.assertEqual(['Main'], result.structuredContent['cleared'])
        self.assertEqual(['Restart'], result.structuredContent['retained'])
        self.assertFalse(self.read_config()['Main']['Scheduler']['Enable'])
        self.assertTrue(self.read_config()['Restart']['Scheduler']['Enable'])

    async def test_failed_device_cleanup_disables_calls_and_retries_on_close(self):
        process = Mock()
        with patch('module.mcp.tools.run_device', side_effect=DeviceCleanupError(process)) as device:
            self.assertEqual('DEVICE_CLEANUP_FAILED',
                             (await self.error('azurpilot_observe_device', instance='demo'))['error']['code'])
            self.assertEqual('SERVICE_STOPPING',
                             (await self.error('azurpilot_observe_device', instance='demo'))['error']['code'])
            self.assertEqual(1, device.call_count)
        with patch('module.mcp.tools.cleanup_device') as cleanup:
            await self.tools.close()
        cleanup.assert_called_once_with(process)

    async def test_initialization_is_shared_across_simultaneous_calls(self):
        tools = Tools()
        self.addAsyncCleanup(tools.close)
        with patch('module.mcp.tools.ConfigService', return_value=self.configs) as configs, \
                patch('module.mcp.tools.RuntimeService', return_value=self.runtime) as runtime:
            await asyncio.gather(*(tools.call('azurpilot_list_instances', {}) for _ in range(4)))
        configs.assert_called_once_with()
        runtime.assert_called_once_with(self.configs)

    async def test_runtime_start_and_stop_failures_do_not_report_success(self):
        manager = Mock(alive=False)
        manager.stop_by_user.return_value = False
        with patch.object(ProcessManager, 'get_manager', return_value=manager), \
                patch.dict(sys.modules, {'module.runtime.updater': SimpleNamespace(updater=SimpleNamespace(event=None))}):
            self.assertEqual('START_FAILED',
                             (await self.error('azurpilot_start_instance', instance='demo'))['error']['code'])
            self.assertEqual('STOP_FAILED',
                             (await self.error('azurpilot_stop_instance', instance='demo'))['error']['code'])
        manager.start.assert_called_once_with('alas', ev=None)
        manager.stop_by_user.assert_called_once_with()

    async def test_update_returns_pending_and_operation_is_queryable(self):
        with patch.object(State, 'restart_event', threading.Event()), \
                patch.object(State, 'dependency_sync_event', threading.Event()), \
                patch('module.mcp.tools.update_service.start', return_value={'accepted': True}) as start:
            result = await self.data('azurpilot_update_application', request_id='update-1')
            start.assert_called_once_with('apply')
            self.assertEqual('pending', result['status'])
            self.assertFalse(result['update_completed'])
            with patch('module.mcp.tools.update_service.status', return_value={'busy': True, 'error': ''}):
                operation = await self.data('azurpilot_get_operation', operation_id=result['operation_id'])
            self.assertEqual('pending', operation['operation']['status'])
            duplicate = await self.data('azurpilot_update_application', request_id='update-1')
            self.assertTrue(duplicate['deduplicated'])
            self.assertEqual(1, start.call_count)

    async def test_standalone_update_refuses_before_starting_work(self):
        with patch.object(State, 'restart_event', None), \
                patch('module.mcp.tools.update_service.start') as start:
            self.assertEqual('UPDATE_UNAVAILABLE',
                             (await self.error('azurpilot_update_application'))['error']['code'])
            start.assert_not_called()

    async def test_device_observation_has_structured_metadata_and_image(self):
        with patch('module.mcp.tools.run_device', return_value=screenshot_result()) as device:
            self.assertEqual('INVALID_PARAMS',
                             (await self.error('azurpilot_observe_device', instance='../demo'))['error']['code'])
            device.assert_not_called()
            result = await self.invoke('azurpilot_observe_device', instance='demo')
            self.assertEqual('image', result.content[1].type)
            self.assertEqual('image/jpeg', result.content[1].mimeType)
            self.assertEqual('YWJj', result.content[1].data)
            self.assertEqual((1280, 720, 'landscape', False),
                             (result.structuredContent['width'], result.structuredContent['height'],
                              result.structuredContent['orientation'], result.structuredContent['cached']))

    async def test_request_id_deduplicates_writes_and_rejects_different_payload(self):
        revision = self.configs.read('demo')[1]
        arguments = {'instance': 'demo', 'revision': revision,
                     'changes': [{'path': 'Main.Option.Count', 'value': 4}], 'request_id': 'patch-1'}
        with patch.object(self.configs, 'patch', wraps=self.configs.patch) as apply:
            first_result = await self.invoke('azurpilot_patch_config', **arguments)
            second_result = await self.invoke('azurpilot_patch_config', **arguments)
        first, second = first_result.structuredContent, second_result.structuredContent
        self.assertFalse(first_result.isError, first_result.content[0].text)
        self.assertFalse(second_result.isError, second_result.content[0].text)
        self.assertEqual(first['operation_id'], second['operation_id'])
        self.assertTrue(second['deduplicated'])
        self.assertIn('请求去重', second_result.content[0].text)
        self.assertEqual(1, apply.call_count)
        conflict = await self.error('azurpilot_patch_config', **{**arguments, 'changes': [
            {'path': 'Main.Option.Count', 'value': 5}]})
        self.assertEqual('REQUEST_ID_CONFLICT', conflict['error']['code'])
        self.assertEqual(4, self.read_config()['Main']['Option']['Count'])

    async def test_timeout_is_uncertain_and_retry_queries_same_operation(self):
        with patch.object(self.tools.devices, 'run', side_effect=ApiError('TOOL_TIMEOUT', '等待超时')) as run:
            error = await self.error('azurpilot_restart_emulator', instance='demo', request_id='restart-1')
            self.assertFalse(error['error']['outcome_certain'])
            self.assertTrue(error['error']['retryable'])
            self.assertEqual('azurpilot_get_operation', error['next_step']['tool'])
            pending = await self.data('azurpilot_restart_emulator', instance='demo', request_id='restart-1')
            self.assertTrue(pending['deduplicated'])
            self.assertEqual(error['operation_id'], pending['operation_id'])
            operation = await self.data('azurpilot_get_operation', operation_id=error['operation_id'])
            self.assertEqual('pending', operation['operation']['status'])
            self.assertEqual(1, run.call_count)

    async def test_logs_filter_and_cursor_contract(self):
        self.runtime.logs = Mock(return_value={'cursor': 3, 'reset': False, 'entries': [
            {'id': 1, 'level': 'INFO', 'text': '启动'},
            {'id': 2, 'level': 'ERROR', 'text': '截图失败'},
            {'id': 3, 'level': 'ERROR', 'text': '已恢复'},
        ]})
        result = await self.data('azurpilot_get_logs', instance='demo', level='ERROR', keyword='失败')
        self.assertEqual([2], [entry['id'] for entry in result['entries']])
        self.assertEqual(3, result['next_cursor'])
        self.runtime.logs.assert_called_with('demo', after=0)

    async def test_long_device_work_keeps_other_tools_responsive(self):
        entered, release = threading.Event(), threading.Event()

        def device(*args):
            entered.set()
            release.wait(5)
            return {'text': '完成'}

        with patch('module.mcp.tools.run_device', side_effect=device):
            task = asyncio.create_task(self.invoke('azurpilot_restart_emulator', instance='demo'))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                result = await asyncio.wait_for(self.data('azurpilot_list_instances'), 0.5)
                self.assertEqual(['demo'], [item['name'] for item in result['instances']])
            finally:
                release.set()
                await task


if __name__ == '__main__':
    unittest.main()
