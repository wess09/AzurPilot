"""设备替身验证扫描恢复不换目标、不动旁机，物理互斥在退出后释放。"""
import multiprocessing
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.device.connection import Connection
from module.device.lease import DeviceLease
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.map.map_grids import SelectedGrids


def hold_device(serial, directory, pipe):
    lease = DeviceLease(serial, 'child', directory)
    pipe.send('ready')
    pipe.recv()
    lease.release()


class ScanConnectionIsolationTests(unittest.TestCase):
    def connection(self, serial='127.0.0.1:5555', devices=()):
        connection = Connection.__new__(Connection)
        connection.config = SimpleNamespace(_scan_device_isolation=True, Emulator_AdbRestart=True,
                                            DEVICE_OVER_HTTP=False, Emulator_Serial=serial)
        connection.serial = serial
        connection.adb_client = Mock()
        connection.adb_client.connect.return_value = 'connected'
        connection.list_device = Mock(return_value=SelectedGrids([
            SimpleNamespace(serial=serial, status=status) for serial, status in devices]))
        connection.__dict__['is_mumu12_family'] = False
        connection.release_resource = Mock()
        return connection

    def test_missing_a_never_selects_online_b_or_disconnects_b(self):
        connection = self.connection(devices=[('127.0.0.1:5557', 'device'), ('127.0.0.1:5559', 'offline')])
        connection.detect_device()
        self.assertEqual(connection.serial, '127.0.0.1:5555')
        connection.adb_reconnect()
        connection.adb_client.disconnect.assert_called_once_with('127.0.0.1:5555')
        connection.adb_client.connect.assert_called_once_with('127.0.0.1:5555')
        connection.adb_client.server_kill.assert_not_called()

    def test_empty_device_list_cannot_restart_shared_adb_even_when_config_enables_it(self):
        connection = self.connection()
        connection.adb_reconnect()
        connection.adb_client.server_kill.assert_not_called()

    def test_scheduler_device_initialization_is_isolated_before_run_sets_temporary_flag(self):
        connection = self.connection(devices=[('127.0.0.1:5557', 'device')])
        connection.config._scan_device_isolation = False
        connection.config.task = SimpleNamespace(command='MindCalculatorScan')
        connection.detect_device()
        self.assertEqual(connection.serial, '127.0.0.1:5555')
        connection.adb_reconnect()
        connection.adb_client.server_kill.assert_not_called()
        with self.assertRaises(EmulatorNotRunningError):
            connection.adb_restart()
        connection.adb_client.server_kill.assert_not_called()

    def test_same_device_alias_pair_recovers_without_touching_another_device(self):
        connection = self.connection(devices=[('emulator-5554', 'device'), ('127.0.0.1:5557', 'device')])
        connection.detect_device()
        self.assertEqual(connection.serial, 'emulator-5554')
        connection.adb_connect(wait_device=False)
        connection.adb_client.disconnect.assert_not_called()

    def test_auto_binding_is_pinned_after_initial_unique_selection(self):
        connection = self.connection('auto', [('127.0.0.1:5555', 'device'), ('emulator-5554', 'device')])
        connection.detect_device()
        self.assertEqual(connection.serial, '127.0.0.1:5555')
        connection.list_device.return_value = SelectedGrids([SimpleNamespace(serial='127.0.0.1:5557', status='device')])
        connection.detect_device()
        self.assertEqual(connection.serial, '127.0.0.1:5555')
        self.assertEqual(connection.config.Emulator_Serial, 'auto')
        ambiguous = self.connection('auto', [('127.0.0.1:5555', 'device'), ('127.0.0.1:5557', 'device')])
        with self.assertRaises(RequestHumanTakeover):
            ambiguous.detect_device()


class PhysicalDeviceLeaseTests(unittest.TestCase):
    def test_same_device_different_config_and_alias_are_exclusive_but_a_b_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DeviceLease('127.0.0.1:5555', 'A', directory)
            self.addCleanup(first.release)
            with self.assertRaises(RequestHumanTakeover):
                DeviceLease('emulator-5554', 'B', directory)
            other = DeviceLease('127.0.0.1:5557', 'B', directory)
            other.release()
            first.release()
            replacement = DeviceLease('emulator-5554', 'B', directory)
            replacement.release()

    def test_stopped_process_releases_os_lock_without_background_input(self):
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context('spawn')
            parent, child = context.Pipe()
            process = context.Process(target=hold_device, args=('127.0.0.1:5555', directory, child))
            process.start()
            try:
                self.assertTrue(parent.poll(15))
                self.assertEqual(parent.recv(), 'ready')
                with self.assertRaises(RequestHumanTakeover):
                    DeviceLease('emulator-5554', 'parent', directory)
            finally:
                process.terminate()
                process.join(15)
                parent.close()
                child.close()
            self.assertFalse(process.is_alive())
            lease = DeviceLease('emulator-5554', 'parent', directory)
            lease.release()
