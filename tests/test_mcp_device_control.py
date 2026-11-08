"""设备控制组契约回归：租约、坐标、观测帧失效与结果语义，不触碰真实设备。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import jsonschema

from module.api.config_service import ConfigService
from module.api.runtime_service import RuntimeService
from module.mcp import device_contract
from module.mcp.registry import TOOL_BY_NAME
from module.mcp.tools import Tools


def fixture(directory):
    root = Path(directory)
    data = {'Alas': {}, 'Main': {'Scheduler': {'Enable': False, 'NextRun': '2026-01-01 00:00:00'}}}
    args = {'Main': {'Scheduler': {'Enable': {'type': 'checkbox', 'value': False},
                                  'NextRun': {'type': 'datetime', 'value': '2026-01-01 00:00:00'}}}}
    for name, value in [('config/template.json', data), ('config/demo.json', data),
                        ('module/config/argument/args.json', args),
                        ('module/config/argument/menu.json', {}),
                        ('module/config/i18n/zh-CN.json', {})]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    return root


def control_result(**overrides):
    result = {
        'frame_id': 'a' * 32, 'width': 1280, 'height': 720,
        'frame_changed': True, 'frame_difference': 12.5,
        'observation_verified': True,
        'detail': {'target': [320, 180], 'control_method': 'nemu_ipc'},
    }
    result.update(overrides)
    return result


class DeviceControlTest(unittest.IsolatedAsyncioTestCase):
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
        self.assertTrue(result.isError, result.content[0].text)
        self.assertEqual('failed', result.structuredContent['status'])
        jsonschema.validate(result.structuredContent, TOOL_BY_NAME[name].output)
        return result.structuredContent

    async def acquire(self, instance='demo'):
        return await self.data('azurpilot_acquire_device_control', instance=instance)

    async def test_acquire_is_idempotent_and_release_invalidates_lease(self):
        first = await self.acquire()
        second = await self.acquire()
        self.assertEqual(first['lease_id'], second['lease_id'])
        self.assertFalse(first['already_held'])
        self.assertTrue(second['already_held'])
        self.assertEqual('stopped', first['instance_status'])

        released = await self.data('azurpilot_release_device_control',
                                   instance='demo', lease_id=first['lease_id'])
        self.assertTrue(released['released'])
        error = await self.error('azurpilot_click', instance='demo',
                                 lease_id=first['lease_id'], x=10, y=10)
        self.assertEqual('DEVICE_NOT_ACQUIRED', error['error']['code'])
        self.assertEqual('azurpilot_acquire_device_control', error['next_step']['tool'])

    async def test_acquire_rejects_running_scheduler(self):
        with patch.object(self.runtime, 'overview', Mock(return_value={'status': 'running'})):
            error = await self.error('azurpilot_acquire_device_control', instance='demo')
        self.assertEqual('DEVICE_IN_USE', error['error']['code'])
        self.assertFalse(error['error']['retryable'])
        self.assertEqual('azurpilot_get_context', error['next_step']['tool'])
        self.assertEqual({}, self.tools.leases)

    async def test_control_without_lease_never_reaches_device(self):
        with patch('module.mcp.tools.run_device') as device:
            error = await self.error('azurpilot_click', instance='demo',
                                     lease_id='f' * 32, x=10, y=10)
        self.assertEqual('DEVICE_NOT_ACQUIRED', error['error']['code'])
        device.assert_not_called()

    async def test_expired_and_revoked_leases_are_refused(self):
        lease = await self.acquire()
        self.tools.leases['demo'].expires_at = 0
        expired = await self.error('azurpilot_click', instance='demo',
                                   lease_id=lease['lease_id'], x=10, y=10)
        self.assertEqual('LEASE_EXPIRED', expired['error']['code'])

        lease = await self.acquire()
        with patch.object(self.runtime, 'overview',
                          Mock(return_value={'status': 'running'})):
            revoked = await self.error('azurpilot_click', instance='demo',
                                       lease_id=lease['lease_id'], x=10, y=10)
        self.assertEqual('DEVICE_IN_USE', revoked['error']['code'])
        self.assertNotIn('demo', self.tools.leases)

    async def test_click_separates_dispatched_frame_change_and_task_completion(self):
        lease = await self.acquire()
        record = {'width': 1280, 'height': 720, 'orientation': 'landscape'}
        with patch('module.mcp.tools.load_frame', return_value=record), \
                patch('module.mcp.tools.run_device', return_value=control_result()) as device:
            result = await self.invoke('azurpilot_click', instance='demo',
                                       lease_id=lease['lease_id'], x=320, y=180,
                                       frame_id='b' * 32)
        self.assertFalse(result.isError, result.content[0].text)
        jsonschema.validate(result.structuredContent, TOOL_BY_NAME['azurpilot_click'].output)
        data = result.structuredContent
        self.assertTrue(data['command_dispatched'])
        self.assertTrue(data['frame_changed'])
        self.assertEqual(12.5, data['frame_difference'])
        self.assertTrue(data['observation_verified'])
        self.assertEqual('a' * 32, data['frame_id'])
        spec, instance, params = device.call_args.args
        self.assertEqual('click', spec)
        self.assertEqual('demo', instance)
        self.assertEqual('b' * 32, params['frame_id'])

        summary = result.content[0].text
        self.assertIn('点击已发送', summary)
        self.assertIn('画面已变化', summary)
        self.assertIn('任务是否完成未知', summary)

    async def test_unverified_click_reports_null_frame_change(self):
        lease = await self.acquire()
        with patch('module.mcp.tools.run_device',
                   return_value=control_result(frame_changed=None, frame_difference=None,
                                               observation_verified=False)):
            data = await self.data('azurpilot_click', instance='demo',
                                   lease_id=lease['lease_id'], x=1, y=1, verify=False)
        self.assertIsNone(data['frame_changed'])
        self.assertFalse(data['observation_verified'])

    async def test_stale_observation_and_device_rejections_are_actionable(self):
        lease = await self.acquire()
        stale = await self.error('azurpilot_click', instance='demo',
                                 lease_id=lease['lease_id'], x=10, y=10,
                                 frame_id='c' * 32)
        self.assertEqual('STALE_OBSERVATION', stale['error']['code'])
        self.assertEqual('azurpilot_observe_device', stale['next_step']['tool'])

        # 设备工作进程上报的拒绝同样带稳定错误码和对应下一步。
        from module.api.protocol import ApiError
        with patch('module.mcp.tools.run_device',
                   side_effect=ApiError('OUT_OF_RANGE', '坐标超出画面',
                                        {'x': 5000, 'y': 10, 'width': 1280, 'height': 720})):
            out_of_range = await self.error('azurpilot_click', instance='demo',
                                            lease_id=lease['lease_id'], x=5000, y=10)
        self.assertEqual('OUT_OF_RANGE', out_of_range['error']['code'])
        self.assertEqual('azurpilot_observe_device', out_of_range['next_step']['tool'])
        self.assertEqual(1280, out_of_range['error']['details']['width'])

    async def test_control_timeout_is_not_retryable(self):
        lease = await self.acquire()
        from module.api.protocol import ApiError
        with patch('module.mcp.tools.run_device',
                   side_effect=ApiError('DEVICE_TIMEOUT', '设备操作超时')):
            error = await self.error('azurpilot_click', instance='demo',
                                     lease_id=lease['lease_id'], x=10, y=10)
        self.assertEqual('DEVICE_TIMEOUT', error['error']['code'])
        self.assertFalse(error['error']['retryable'])
        self.assertFalse(error['error']['outcome_certain'])
        self.assertEqual('azurpilot_observe_device', error['next_step']['tool'])

    async def test_adb_shell_returns_output_without_frame(self):
        lease = await self.acquire()
        raw = {'frame_id': None, 'width': None, 'height': None, 'frame_changed': None,
               'frame_difference': None, 'observation_verified': False,
               'detail': {'argv': ['wm', 'size']}, 'output': 'Physical size: 1280x720',
               'truncated': False}
        with patch('module.mcp.tools.run_device', return_value=raw):
            data = await self.data('azurpilot_adb_shell', instance='demo',
                                   lease_id=lease['lease_id'], argv=['wm', 'size'])
        self.assertEqual('Physical size: 1280x720', data['output'])
        self.assertIsNone(data['frame_id'])
        self.assertFalse(data['truncated'])

    async def test_context_reports_control_capability_and_active_lease(self):
        before = await self.data('azurpilot_get_context', instance='demo')
        self.assertTrue(before['device']['control_supported'])
        self.assertTrue(before['device']['control_requires_lease'])
        self.assertIsNone(before['device']['lease'])
        lease = await self.acquire()
        after = await self.data('azurpilot_get_context', instance='demo')
        self.assertEqual(lease['lease_id'], after['device']['lease']['lease_id'])

    async def test_scheduler_takeover_invalidates_lease_everywhere(self):
        lease = await self.acquire()
        overview = self.runtime.overview('demo')
        running = {**overview, 'status': 'running'}
        with patch.object(self.runtime, 'overview', return_value=running):
            context = await self.data('azurpilot_get_context', instance='demo')
            self.assertIsNone(context['device']['lease'])
            error = await self.error('azurpilot_click', instance='demo',
                                     lease_id=lease['lease_id'], x=10, y=10)
        self.assertEqual('DEVICE_NOT_ACQUIRED', error['error']['code'])


class DeviceContractTest(unittest.TestCase):
    def test_coordinates_must_stay_inside_frame(self):
        device_contract.ensure_point(0, 0, 1280, 720)
        with self.assertRaises(device_contract.DeviceOperationError) as caught:
            device_contract.ensure_point(1280, 10, 1280, 720)
        self.assertEqual('OUT_OF_RANGE', caught.exception.code)
        self.assertEqual(1280, caught.exception.details['width'])

    def test_swipe_rejects_click_sized_gesture(self):
        with self.assertRaises(device_contract.DeviceOperationError) as caught:
            device_contract.ensure_swipe(100, 100, 104, 102, 1280, 720)
        self.assertEqual('INVALID_PARAMS', caught.exception.code)

    def test_text_escape_only_allows_shell_safe_ascii(self):
        self.assertEqual('Azur%sLane-01', device_contract.escape_text('Azur Lane-01'))
        with self.assertRaises(device_contract.DeviceOperationError) as caught:
            device_contract.escape_text('战斗中')
        self.assertEqual('UNSUPPORTED_TEXT', caught.exception.code)
        with self.assertRaises(device_contract.DeviceOperationError):
            device_contract.escape_text('a;rm -rf /')

    def test_shell_whitelist_rejects_mutating_and_piped_commands(self):
        for argv in (['wm', 'size'], ['getprop'], ['dumpsys', 'battery'],
                     ['dumpsys', 'window'], ['pm', 'list', 'packages']):
            with self.subTest(allowed=argv):
                self.assertEqual(argv, device_contract.validate_shell(argv))
        for argv in (['am', 'start'], ['dumpsys', 'connect'], ['pm', 'install'],
                     ['wm', 'size;rm'], ['input', 'tap', '1', '1']):
            with self.subTest(denied=argv):
                with self.assertRaises(device_contract.DeviceOperationError) as caught:
                    device_contract.validate_shell(argv)
                self.assertEqual('ADB_SHELL_DENIED', caught.exception.code)

    def test_keycodes_are_named_not_raw(self):
        self.assertEqual(4, device_contract.keycode('BACK'))
        with self.assertRaises(device_contract.DeviceOperationError):
            device_contract.keycode('999')

    def test_signature_comparison_detects_change(self):
        before = [10] * 1024
        self.assertEqual(0.0, device_contract.compare_signature(before, before))
        self.assertTrue(device_contract.frame_changed(
            device_contract.compare_signature(before, [200] * 1024)))
        # 静止帧实测噪声不超过 0.1，阈值应明显高于噪声、又能识别小幅变化。
        self.assertFalse(device_contract.frame_changed(0.1))
        self.assertTrue(device_contract.frame_changed(1.2))
        self.assertIsNone(device_contract.compare_signature(before, [1] * 10))

    def test_frames_are_cached_per_instance_and_evicted(self):
        with tempfile.TemporaryDirectory() as directory:
            original = device_contract.frame_root
            device_contract.frame_root = lambda: Path(directory) / 'mcp_frames'
            try:
                record = {'frame_id': 'd' * 32, 'instance': 'demo', 'width': 1280,
                          'height': 720, 'orientation': 'landscape',
                          'signature': [0] * 4}
                device_contract.save_frame('demo', record)
                self.assertEqual(record, device_contract.load_frame('demo', 'd' * 32))
                self.assertIsNone(device_contract.load_frame('other', 'd' * 32))
                self.assertIsNone(device_contract.load_frame('demo', '../etc/passwd'))
            finally:
                device_contract.frame_root = original


class DeviceToolDirectoryTest(unittest.TestCase):
    def test_control_tools_require_lease_in_schema(self):
        for name in ('azurpilot_click', 'azurpilot_swipe', 'azurpilot_long_press',
                     'azurpilot_input_text', 'azurpilot_press_key', 'azurpilot_adb_shell'):
            with self.subTest(tool=name):
                spec = TOOL_BY_NAME[name]
                self.assertIn('lease_id', spec.input['required'])
                self.assertEqual(False, spec.input['additionalProperties'])
                self.assertIn('command_dispatched', spec.output['properties'])
                self.assertIn('frame_changed', spec.output['properties'])

    def test_observe_device_is_the_only_frame_source(self):
        spec = TOOL_BY_NAME['azurpilot_observe_device']
        self.assertIn('frame_id', spec.output['properties'])
        self.assertNotIn('lease_id', spec.input['required'])
