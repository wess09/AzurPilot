"""设备后端重试回归测试：只运行包装器和隔离的方法，不连接真实设备。"""

import ctypes
import importlib
import unittest
from json import JSONDecodeError
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

# Device 导入先安装项目的 pkg_resources 兼容补丁；不构造设备或读取配置。
from module.device.device import Device  # noqa: F401
from adbutils.errors import AdbError, AdbTimeout
from requests.exceptions import ConnectionError as HttpConnectionError, ReadTimeout

from module.device.method import (
    adb, ascreencap, droidcast, hermit, ldopengl, maatouch, minitouch, nemu_ipc,
    uiautomator_2, utils, wsa,
)
from module.exception import EmulatorNotRunningError, RequestHumanTakeover

scrcpy = importlib.import_module('module.device.method.scrcpy.scrcpy')
retry_module = importlib.import_module('module.device.method.retry')
BACKENDS = (adb, uiautomator_2, ascreencap, droidcast, minitouch, maatouch,
            scrcpy, hermit, wsa, nemu_ipc, ldopengl)
ADB_BACKENDS = BACKENDS[:9]


def perform(device, value='输入'):
    return device.perform(value)


class TestBackendRetry(unittest.TestCase):
    def setUp(self):
        self.sleep = self.enterContext(patch.object(retry_module.time, 'sleep'))
        self.enterContext(patch.object(retry_module, 'logger'))
        self.enterContext(patch.object(utils, 'logger'))
        for backend in BACKENDS:
            self.enterContext(patch.object(backend, 'logger'))

    def make_device(self):
        device = Mock()
        device._minitouch_port = 12345
        device._minitouch_builder = object()
        device._maatouch_builder = object()
        return device

    def test_explicit_takeover_and_offline_keep_identity_without_retry(self):
        for backend in BACKENDS:
            for error in (RequestHumanTakeover('请人工确认'), EmulatorNotRunningError('已确认离线')):
                with self.subTest(backend=backend.__name__, error=type(error).__name__):
                    device = self.make_device()
                    device.perform.side_effect = error
                    wrapped = backend.retry(perform, on_exhausted=EmulatorNotRunningError)
                    self.sleep.reset_mock()

                    with self.assertRaises(type(error)) as caught:
                        wrapped(device)

                    self.assertIs(caught.exception, error)
                    device.perform.assert_called_once_with('输入')
                    self.sleep.assert_not_called()
                    device.adb_reconnect.assert_not_called()
                    device.reconnect.assert_not_called()

    def test_recovery_takeover_and_offline_are_not_swallowed(self):
        for backend in ADB_BACKENDS:
            for error in (RequestHumanTakeover('重连发现配置错误'), EmulatorNotRunningError('重连确认离线')):
                with self.subTest(backend=backend.__name__, error=type(error).__name__):
                    device = self.make_device()
                    device.perform.side_effect = AdbError('device offline')
                    device.adb_reconnect.side_effect = error
                    with self.assertRaises(type(error)) as caught:
                        backend.retry(perform, on_exhausted=EmulatorNotRunningError)(device)
                    self.assertIs(caught.exception, error)
                    device.perform.assert_called_once()
                    device.adb_reconnect.assert_called_once()

    def test_retry_budget_backoff_and_exception_chain_are_preserved(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend.__name__):
                device = self.make_device()
                error = OSError('临时故障')
                device.perform.side_effect = error
                self.sleep.reset_mock()
                with self.assertRaises(EmulatorNotRunningError) as caught:
                    backend.retry(perform, on_exhausted=EmulatorNotRunningError)(device)

                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(device.perform.call_count, 5)
                self.assertEqual(self.sleep.call_args_list, [call(0), call(1), call(3), call(3)])

    def test_function_name_does_not_select_exhaustion_policy(self):
        for name in ('screenshot_adb', '_maatouch_builder', 'renamed_operation'):
            for policy in (RequestHumanTakeover, EmulatorNotRunningError):
                with self.subTest(name=name, policy=policy.__name__):
                    def operation(device):
                        return device.perform()
                    operation.__name__ = name
                    device = self.make_device()
                    device.perform.side_effect = OSError('临时故障')
                    with self.assertRaises(policy):
                        adb.retry(operation, on_exhausted=policy)(device)
                    self.assertEqual(device.perform.call_count, 5)

    def test_unrecoverable_adb_errors_request_takeover_even_for_restartable_methods(self):
        for backend in ADB_BACKENDS:
            with self.subTest(backend=backend.__name__):
                device = self.make_device()
                error = AdbError('device unauthorized')
                device.perform.side_effect = error
                with self.assertRaises(RequestHumanTakeover) as caught:
                    backend.retry(perform, on_exhausted=EmulatorNotRunningError)(device)
                self.assertIs(caught.exception.__cause__, error)
                device.perform.assert_called_once()
                device.adb_reconnect.assert_not_called()

    def test_unknown_host_restarts_adb_before_reconnect_including_maatouch(self):
        for backend in ADB_BACKENDS:
            with self.subTest(backend=backend.__name__):
                device = self.make_device()
                device.perform.side_effect = [AdbError('unknown host service'), '成功']
                self.assertEqual(backend.retry(perform)(device), '成功')
                actions = [entry[0] for entry in device.mock_calls]
                self.assertLess(actions.index('adb_start_server'), actions.index('adb_reconnect'))
                device.adb_start_server.assert_called_once()
                device.adb_reconnect.assert_called_once()

    def test_backend_specific_recovery_actions_keep_order(self):
        cases = (
            (uiautomator_2, HttpConnectionError('Connection aborted'), ['install_uiautomator2']),
            (uiautomator_2, HttpConnectionError('connection refused'), ['adb_reconnect']),
            (uiautomator_2, JSONDecodeError('无效 JSON', '', 0), ['install_uiautomator2']),
            (uiautomator_2, RuntimeError('USB device is offline'), ['adb_reconnect']),
            (adb, utils.PackageNotInstalled('测试包'), ['detect_package']),
            (wsa, utils.PackageNotInstalled('测试包'), ['detect_package']),
            (ascreencap, ascreencap.AscreencapError(), ['ascreencap_init']),
            (droidcast, ReadTimeout(), ['droidcast_init']),
            (droidcast, HttpConnectionError(), ['droidcast_init']),
            (droidcast, droidcast.DroidCastVersionIncompatible(), ['droidcast_init']),
            (minitouch, ConnectionAbortedError(), ['adb_reconnect', 'adb_forward_remove']),
            (minitouch, minitouch.MinitouchNotInstalledError(), ['install_uiautomator2', 'adb_forward_remove']),
            (minitouch, minitouch.MinitouchOccupiedError(), ['restart_atx', 'adb_forward_remove']),
            (maatouch, maatouch.MaaTouchSyncTimeout(), ['adb_reconnect', 'reset_maatouch']),
            (maatouch, maatouch.MaaTouchNotInstalledError(), ['maatouch_install']),
            (scrcpy, AdbTimeout('read timeout'), ['scrcpy_init']),
            (scrcpy, TimeoutError(), ['scrcpy_init']),
            (scrcpy, scrcpy.ScrcpyError(), ['scrcpy_init']),
            (hermit, HttpConnectionError('Connection aborted'), ['adb_reconnect', 'hermit_init']),
            (hermit, hermit.HermitError(), ['adb_reconnect', 'hermit_init']),
            (nemu_ipc, nemu_ipc.NemuIpcError(), ['reconnect']),
        )
        for backend, error, expected in cases:
            with self.subTest(backend=backend.__name__, error=type(error).__name__):
                device = self.make_device()
                device.perform.side_effect = [error, '成功']
                self.sleep.reset_mock()
                self.assertEqual(backend.retry(perform)(device), '成功')
                actions = [entry[0] for entry in device.mock_calls]
                self.assertEqual(actions, ['perform', *expected, 'perform'])
                self.sleep.assert_called_once_with(0)
                if backend == minitouch:
                    self.assertNotIn('_minitouch_builder', device.__dict__)
                    device.adb_forward_remove.assert_called_once_with('tcp:12345')
                elif backend == maatouch:
                    self.assertNotIn('_maatouch_builder', device.__dict__)

    def test_broken_pipe_only_invalidates_builder_without_reconnect(self):
        for backend, builder in ((minitouch, '_minitouch_builder'), (maatouch, '_maatouch_builder')):
            with self.subTest(backend=backend.__name__):
                device = self.make_device()
                device.perform.side_effect = [BrokenPipeError(), '成功']
                self.assertEqual(backend.retry(perform)(device), '成功')
                self.assertNotIn(builder, device.__dict__)
                device.adb_reconnect.assert_not_called()
                device.adb_forward_remove.assert_not_called()

    def test_recovery_failure_consumes_attempt_without_calling_operation_again(self):
        device = self.make_device()
        device.perform.side_effect = [AdbError('device offline'), '成功']
        device.adb_reconnect.side_effect = [AdbError('device offline'), None]
        self.assertEqual(adb.retry(perform)(device), '成功')
        self.assertEqual(device.perform.call_count, 2)
        self.assertEqual(device.adb_reconnect.call_count, 2)
        self.assertEqual(self.sleep.call_args_list, [call(0), call(1)])

    def test_incompatible_native_backends_are_not_classified_as_offline(self):
        for backend, error in ((nemu_ipc, nemu_ipc.NemuIpcIncompatible()),
                               (ldopengl, ldopengl.LDOpenGLIncompatible())):
            with self.subTest(backend=backend.__name__):
                device = self.make_device()
                device.perform.side_effect = error
                with self.assertRaises(RequestHumanTakeover) as caught:
                    backend.retry(perform, on_exhausted=EmulatorNotRunningError)(device)
                self.assertIs(caught.exception.__cause__, error)
                device.perform.assert_called_once()
                device.reconnect.assert_not_called()

    def test_shared_wrapper_preserves_metadata_arguments_and_return_value(self):
        device = self.make_device()
        result = object()
        device.perform.return_value = result
        wrapped = adb.retry(perform)
        self.assertEqual(wrapped.__name__, 'perform')
        self.assertIs(wrapped.__wrapped__, perform)
        self.assertIs(wrapped(device, value='透传参数'), result)
        device.perform.assert_called_once_with('透传参数')

    def test_process_stop_signals_are_never_retried(self):
        for backend in BACKENDS:
            for error in (KeyboardInterrupt(), SystemExit(1)):
                with self.subTest(backend=backend.__name__, error=type(error).__name__):
                    device = self.make_device()
                    device.perform.side_effect = error
                    with self.assertRaises(type(error)) as caught:
                        backend.retry(perform)(device)
                    self.assertIs(caught.exception, error)
                    device.perform.assert_called_once()
        self.sleep.assert_not_called()


class TestActualBackendMethods(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(retry_module.time, 'sleep'))
        self.enterContext(patch.object(retry_module, 'logger'))
        for backend in BACKENDS:
            self.enterContext(patch.object(backend, 'logger'))

    def test_adb_screenshot_variants_keep_restart_policy(self):
        for over_http in (False, True):
            with self.subTest(over_http=over_http):
                device = Mock(config=SimpleNamespace(DEVICE_OVER_HTTP=over_http))
                device.adb_shell.side_effect = OSError('截图传输失败')
                with self.assertRaises(EmulatorNotRunningError):
                    adb.Adb.screenshot_adb(device)
                self.assertEqual(device.adb_shell.call_count, 5)

    def test_adb_click_keeps_takeover_policy(self):
        device = Mock()
        device.adb_shell.side_effect = OSError('触控失败')
        with self.assertRaises(RequestHumanTakeover):
            adb.Adb.click_adb(device, 1, 2)
        self.assertEqual(device.adb_shell.call_count, 5)

    def test_u2_screenshot_and_click_keep_different_exhaustion_policies(self):
        for method, action, args, policy in (
            (uiautomator_2.Uiautomator2.screenshot_uiautomator2, 'screenshot', (), EmulatorNotRunningError),
            (uiautomator_2.Uiautomator2.click_uiautomator2, 'click', (1, 2), RequestHumanTakeover),
        ):
            with self.subTest(action=action):
                device = Mock()
                operation = getattr(device.u2, action)
                operation.side_effect = OSError('服务暂时失败')
                with self.assertRaises(policy):
                    method(device, *args)
                self.assertEqual(operation.call_count, 5)

    def test_touch_builder_initialization_keeps_restart_policy(self):
        for backend_type, init_name, property_name in (
            (minitouch.Minitouch, 'minitouch_init', '_minitouch_builder'),
            (maatouch.MaaTouch, 'maatouch_init', '_maatouch_builder'),
        ):
            with self.subTest(backend=backend_type.__name__):
                device = backend_type.__new__(backend_type)
                operation = Mock(side_effect=OSError('触控服务初始化失败'))
                setattr(device, init_name, operation)
                with self.assertRaises(EmulatorNotRunningError):
                    getattr(device, property_name)
                self.assertEqual(operation.call_count, 5)
                self.assertNotIn(property_name, device.__dict__)


class TestNativeRetryMethods(unittest.TestCase):
    def setUp(self):
        self.sleep = self.enterContext(patch.object(retry_module.time, 'sleep'))
        self.enterContext(patch.object(retry_module, 'logger'))
        self.enterContext(patch.object(nemu_ipc, 'logger'))

    def test_nemu_screenshot_keeps_timeout_ladder_and_exhaustion_policy(self):
        device = Mock(connect_id=1)
        device.run_func.side_effect = nemu_ipc.JobTimeout()
        with self.assertRaises(EmulatorNotRunningError):
            nemu_ipc.NemuIpcImpl.screenshot(device)
        self.assertEqual([item.kwargs['timeout'] for item in device.run_func.call_args_list],
                         [0.5, 0.5, 1, 3, 3])
        self.assertEqual(self.sleep.call_args_list, [call(0), call(1), call(3), call(3)])
        device.reconnect.assert_not_called()

    def test_nemu_invalid_touch_parameters_are_never_retried(self):
        for value, error_type in ((None, TypeError), (float('nan'), ValueError), (float('inf'), OverflowError)):
            with self.subTest(value=value):
                device = Mock(connect_id=1)
                with self.assertRaises(error_type):
                    nemu_ipc.NemuIpcImpl.down(device, value, 10)
                device.reconnect.assert_not_called()
                device.run_func.assert_not_called()
        self.sleep.assert_not_called()

    def test_nemu_ctypes_touch_error_preserves_original_exception(self):
        device = Mock(connect_id=1)
        error = ctypes.ArgumentError('无效触控参数')
        device.run_func.side_effect = error
        with self.assertRaises(ctypes.ArgumentError) as caught:
            nemu_ipc.NemuIpcImpl.up(device)
        self.assertIs(caught.exception, error)
        device.run_func.assert_called_once()
        device.reconnect.assert_not_called()
        self.sleep.assert_not_called()


class TestImageTruncatedRecovery(unittest.TestCase):
    def setUp(self):
        self.sleep = self.enterContext(patch.object(retry_module.time, 'sleep'))
        self.enterContext(patch.object(retry_module, 'logger'))
        self.enterContext(patch.object(utils, 'logger'))
        self.device = Mock(serial='隔离重试测试')
        utils.reset_image_truncated(self.device.serial)
        self.addCleanup(utils.reset_image_truncated, self.device.serial)

    def test_truncation_recovery_still_runs_at_original_threshold(self):
        self.device.perform.side_effect = [utils.ImageTruncated()] * 3 + ['成功']
        events = []
        self.device.droidcast_init.side_effect = lambda: events.append('droidcast')
        self.device.ascreencap_init.side_effect = lambda: events.append('ascreencap')
        self.device.adb_reconnect.side_effect = lambda: events.append('adb')
        self.sleep.side_effect = lambda seconds: events.append(('sleep', seconds))

        self.assertEqual(adb.retry(perform)(self.device), '成功')

        self.assertEqual(events, [('sleep', 0), ('sleep', 1), 'droidcast', 'ascreencap', 'adb', ('sleep', 3)])
        self.assertEqual(utils.report_image_truncated(self.device.serial), 1)

    def test_truncation_recovery_does_not_swallow_takeover_or_offline_at_any_stage(self):
        stages = ('droidcast_init', 'ascreencap_init', 'adb_reconnect')
        for index, stage in enumerate(stages):
            for error in (RequestHumanTakeover('截图恢复需要人工确认'), EmulatorNotRunningError('设备离线')):
                with self.subTest(stage=stage, error=type(error).__name__):
                    self.device.reset_mock(side_effect=True)
                    utils.reset_image_truncated(self.device.serial)
                    self.device.perform.side_effect = utils.ImageTruncated()
                    getattr(self.device, stage).side_effect = error

                    with self.assertRaises(type(error)) as caught:
                        adb.retry(perform, on_exhausted=EmulatorNotRunningError)(self.device)

                    self.assertIs(caught.exception, error)
                    self.assertEqual(self.device.perform.call_count, 3)
                    for later_stage in stages[index + 1:]:
                        getattr(self.device, later_stage).assert_not_called()
                    self.assertEqual(utils.report_image_truncated(self.device.serial), 1)

    def test_truncation_recovery_continues_after_ordinary_service_failure(self):
        self.device.perform.side_effect = [utils.ImageTruncated()] * 3 + ['成功']
        self.device.droidcast_init.side_effect = OSError('服务不可用')
        self.device.ascreencap_init.side_effect = OSError('服务不可用')

        self.assertEqual(adb.retry(perform)(self.device), '成功')

        self.device.adb_reconnect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
