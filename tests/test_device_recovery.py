"""验证连接、设备初始化与调度器之间的离线恢复责任和接管边界。"""

import unittest
from unittest.mock import Mock, PropertyMock, call, patch

from alas import AzurLaneAutoScript
from module.device.device import Device
from module.device.connection import AdbError, retry
from module.device.method.utils import RETRY_TRIES
from module.exception import EmulatorNotRunningError, RequestHumanTakeover


class TestConnectionRecovery(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('module.device.connection.time.sleep'))
        self.enterContext(patch('module.device.connection.logger'))
        self.enterContext(patch('module.device.method.utils.logger'))
        self.client = Mock()

    @staticmethod
    @retry
    def read_device(client):
        return client.read()

    def test_transient_offline_reconnects_without_restarting_emulator(self):
        self.client.read.side_effect = [AdbError('device offline'), '已连接']

        self.assertEqual(self.read_device(self.client), '已连接')

        self.client.adb_reconnect.assert_called_once_with()
        self.client.emulator_start.assert_not_called()
        self.client.emulator_stop.assert_not_called()

    def test_exhausted_transport_retries_preserve_offline_cause(self):
        offline = AdbError('device offline')
        self.client.read.side_effect = offline

        with self.assertRaises(EmulatorNotRunningError) as caught:
            self.read_device(self.client)

        self.assertIs(caught.exception.__cause__, offline)
        self.assertEqual(self.client.read.call_count, RETRY_TRIES)
        self.assertEqual(self.client.adb_reconnect.call_count, RETRY_TRIES - 1)
        self.client.emulator_start.assert_not_called()

    def test_explicit_takeover_is_not_retried_or_converted_to_offline(self):
        error = RequestHumanTakeover('设备配置需要修正')
        self.client.read.side_effect = error

        with self.assertRaises(RequestHumanTakeover) as caught:
            self.read_device(self.client)

        self.assertIs(caught.exception, error)
        self.client.read.assert_called_once_with()
        self.client.adb_reconnect.assert_not_called()

    def test_nonrecoverable_adb_error_requests_takeover(self):
        error = AdbError('device unauthorized')
        self.client.read.side_effect = error

        with self.assertRaises(RequestHumanTakeover) as caught:
            self.read_device(self.client)

        self.assertIs(caught.exception.__cause__, error)
        self.client.read.assert_called_once_with()
        self.client.adb_reconnect.assert_not_called()

    def test_reconnect_takeover_is_preserved(self):
        self.client.read.side_effect = AdbError('device offline')
        error = RequestHumanTakeover('重连发现无效配置')
        self.client.adb_reconnect.side_effect = error

        with self.assertRaises(RequestHumanTakeover) as caught:
            self.read_device(self.client)

        self.assertIs(caught.exception, error)
        self.client.adb_reconnect.assert_called_once_with()


class TestDeviceInitializationRecovery(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('module.device.device.logger'))
        self.device = Device.__new__(Device)
        self.device.config = Mock(Emulator_Serial='127.0.0.1:5555')

    def test_standalone_initialization_keeps_bounded_start_attempts(self):
        offline = EmulatorNotRunningError('设备仍离线')
        with (
            patch('module.device.connection.Connection.__init__', side_effect=offline) as connect,
            patch.object(Device, 'emulator_instance', new_callable=PropertyMock, return_value=Mock()),
            patch.object(Device, 'emulator_start') as start,
        ):
            with self.assertRaises(EmulatorNotRunningError) as caught:
                Device.__init__(self.device, self.device.config)

        self.assertIs(caught.exception, offline)
        self.assertEqual(connect.call_count, 4)
        self.assertEqual(start.call_args_list, [call(failures=0), call(failures=1), call(failures=2)])

    def test_disabled_auto_start_propagates_first_offline_error(self):
        offline = EmulatorNotRunningError('设备离线')
        with (
            patch('module.device.connection.Connection.__init__', side_effect=offline) as connect,
            patch.object(Device, 'emulator_instance', new_callable=PropertyMock) as instance,
            patch.object(Device, 'emulator_start') as start,
        ):
            with self.assertRaises(EmulatorNotRunningError) as caught:
                Device.__init__(self.device, self.device.config, auto_start_emulator=False)

        self.assertIs(caught.exception, offline)
        connect.assert_called_once()
        instance.assert_not_called()
        start.assert_not_called()

    def test_missing_managed_instance_still_requests_takeover_for_auto_start(self):
        with (
            patch('module.device.connection.Connection.__init__', side_effect=EmulatorNotRunningError),
            patch.object(Device, 'emulator_instance', new_callable=PropertyMock, return_value=None),
            patch.object(Device, 'emulator_start') as start,
        ):
            with self.assertRaises(RequestHumanTakeover):
                Device.__init__(self.device, self.device.config)

        start.assert_not_called()

    def test_configuration_takeover_is_not_retried(self):
        error = RequestHumanTakeover('序列号无效')
        with (
            patch('module.device.connection.Connection.__init__', side_effect=error) as connect,
            patch.object(Device, 'emulator_start') as start,
        ):
            with self.assertRaises(RequestHumanTakeover) as caught:
                Device.__init__(self.device, self.device.config)

        self.assertIs(caught.exception, error)
        connect.assert_called_once()
        start.assert_not_called()


class TestSchedulerDeviceBoundary(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('alas.logger'))
        self.enterContext(patch('alas.handle_notify'))
        self.enterContext(patch('alas.notify_webui'))
        self.script = AzurLaneAutoScript('test')
        self.script.__dict__['config'] = Mock(
            Error_HandleError=True,
            Error_StrictRestart=False,
            task=Mock(command='Commission'),
        )

    def test_offline_does_not_exit_or_poison_device_cache(self):
        offline = EmulatorNotRunningError('设备离线')
        connected = Mock()
        with patch('module.device.device.Device', side_effect=[offline, connected]) as device_class:
            with self.assertRaises(EmulatorNotRunningError) as caught:
                _ = self.script.device
            self.assertIs(caught.exception, offline)
            self.assertNotIn('device', self.script.__dict__)
            self.assertIs(self.script.device, connected)
            self.assertIs(self.script.device, connected)

        self.assertEqual(device_class.call_count, 2)
        device_class.assert_called_with(config=self.script.config, auto_start_emulator=False)

    def test_initialization_offline_stops_if_automatic_recovery_is_disabled(self):
        self.script.config.Error_HandleError = False
        with patch('module.device.device.Device', side_effect=EmulatorNotRunningError) as device_class:
            with self.assertRaises(SystemExit) as caught:
                _ = self.script.device

        self.assertEqual(caught.exception.code, 1)
        device_class.assert_called_once_with(config=self.script.config, auto_start_emulator=False)

    def test_initialization_offline_reaches_task_recovery_handler(self):
        self.script.save_error_log = Mock()
        self.script._try_restart_emulator = Mock(return_value=True)
        with patch('module.device.device.Device', side_effect=EmulatorNotRunningError('设备离线')):
            self.assertEqual(self.script.run('commission'), 'recoverable')

        self.script._try_restart_emulator.assert_called_once_with()
        self.script.config.task_call.assert_called_once_with('Restart')

    def test_initialization_offline_preserves_strict_sensitive_stop(self):
        self.script.config.Error_StrictRestart = True
        self.script.config.cross_get.return_value = True
        with patch('module.device.device.Device', side_effect=EmulatorNotRunningError):
            with self.assertRaises(SystemExit) as caught:
                _ = self.script.device

        self.assertEqual(caught.exception.code, 1)
        self.script.config.cross_get.assert_called_once_with(
            keys='Commission.Scheduler.Sensitive', default=False,
        )
        self.script.config.task_call.assert_not_called()

    def test_fatal_initialization_errors_still_exit(self):
        for error in (RequestHumanTakeover('无效配置'), ValueError('初始化错误')):
            with self.subTest(error=type(error).__name__):
                with patch('module.device.device.Device', side_effect=error):
                    with self.assertRaises(SystemExit) as caught:
                        _ = self.script.device
                self.assertEqual(caught.exception.code, 1)


if __name__ == '__main__':
    unittest.main()
