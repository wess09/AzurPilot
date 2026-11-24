"""模拟器启动完成后只最小化目标实例，不受前台焦点切换影响。"""

import itertools
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from module.device.env import IS_WINDOWS

if IS_WINDOWS:
    from module.device.platform import platform_windows
    from module.device.platform.emulator_windows import EmulatorInstance
    from module.device.platform.platform_windows import PlatformWindows


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器窗口测试')
class TestProcessWindow(unittest.TestCase):
    def setUp(self):
        self.user32 = Mock()
        self.enterContext(patch.object(platform_windows.ctypes.windll, 'user32', self.user32))

    def set_windows(self, windows):
        """窗口夹具包含句柄、进程、可见性和 owner，不枚举真实桌面。"""
        self.user32.IsWindowVisible.side_effect = lambda hwnd: windows[hwnd.value]['visible']
        self.user32.GetWindow.side_effect = lambda hwnd, _: windows[hwnd.value]['owner']

        def get_pid(hwnd, pointer):
            pointer._obj.value = windows[hwnd.value]['pid']
            return 1

        def enum_windows(callback, _):
            for hwnd in windows:
                callback(hwnd, 0)
            return 1

        self.user32.GetWindowThreadProcessId.side_effect = get_pid
        self.user32.EnumWindows.side_effect = enum_windows

    def test_ignores_unrelated_hidden_and_owned_windows(self):
        target = 0x100000001
        self.set_windows({
            10: {'pid': 2, 'visible': True, 'owner': 0},
            20: {'pid': 1, 'visible': False, 'owner': 0},
            30: {'pid': 1, 'visible': True, 'owner': target},
            target: {'pid': 1, 'visible': True, 'owner': 0},
        })

        self.assertEqual(platform_windows.get_process_window(1), target)

    def test_ambiguous_or_missing_window_is_skipped(self):
        self.set_windows({
            10: {'pid': 1, 'visible': True, 'owner': 0},
            20: {'pid': 1, 'visible': True, 'owner': 0},
        })

        self.assertEqual(platform_windows.get_process_window(1), 0)
        self.assertEqual(platform_windows.get_process_window(2), 0)
        self.assertEqual(platform_windows.get_process_window(0), 0)

    def test_enumeration_failure_is_skipped(self):
        self.user32.EnumWindows.return_value = 0
        self.assertEqual(platform_windows.get_process_window(1), 0)

    def test_window_operations_preserve_pointer_sized_handles(self):
        target = 0x100000001
        platform_windows.minimize_window(target)
        self.assertEqual(self.user32.ShowWindow.call_args.args[0].value, target)
        self.assertEqual(self.user32.ShowWindow.call_args.args[1], 6)


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器实例定位测试')
class TestEmulatorWindow(unittest.TestCase):
    def setUp(self):
        self.platform = PlatformWindows.__new__(PlatformWindows)
        self.window = self.enterContext(patch.object(platform_windows, 'get_process_window', return_value=100))
        self.enterContext(patch.object(platform_windows, 'logger'))

    def set_instance(self, path, name):
        self.platform.emulator_instance = EmulatorInstance(serial='127.0.0.1:5555', name=name, path=path)

    def test_mumu_query_selects_only_the_configured_instance(self):
        self.set_instance('D:/MuMu/nx_main/MuMuNxMain.exe', 'MuMuPlayer-12.0-1')
        info = {
            '0': {'pid': 10, 'is_process_started': True},
            '1': {'pid': 20, 'is_process_started': True},
        }
        with patch.object(self.platform, '_mumu12_instances', return_value=info):
            self.assertEqual(self.platform._get_emulator_window(), 100)

        self.window.assert_called_once_with(20)

    def test_mumu_unavailable_or_shared_process_is_skipped(self):
        self.set_instance('D:/MuMu/nx_main/MuMuNxMain.exe', 'MuMuPlayer-12.0-1')
        cases = [
            None,
            {},
            {'1': {'is_process_started': False, 'pid': 20}},
            {'1': {'is_process_started': True, 'pid': None}},
            {'0': {'is_process_started': True, 'pid': 20},
             '1': {'is_process_started': True, 'pid': 20}},
        ]
        for info in cases:
            with self.subTest(info=info), patch.object(self.platform, '_mumu12_instances', return_value=info):
                self.assertEqual(self.platform._get_emulator_window(), 0)

        self.window.assert_not_called()

    def test_ldplayer_query_selects_index_and_checks_window_owner(self):
        self.set_instance('D:/LDPlayer9/dnplayer.exe', 'leidian1')
        stdout = '0,同名窗口,101,201,1,11,21\n1,同名窗口,102,202,1,12,22,1280,720,160\n'
        result = SimpleNamespace(returncode=0, stdout=stdout)
        with (
            patch.object(platform_windows.subprocess, 'run', return_value=result) as run,
            patch.object(platform_windows, 'get_window_process_id', return_value=12),
            patch.object(platform_windows.ctypes.windll.user32, 'IsWindowVisible', return_value=1),
        ):
            self.assertEqual(self.platform._get_emulator_window(), 102)

        self.assertEqual(run.call_args.args[0], ['D:/LDPlayer9/ldconsole.exe', 'list2'])
        self.assertEqual(run.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    def test_ldplayer_unavailable_or_reused_handle_is_skipped(self):
        self.set_instance('D:/LDPlayer9/dnplayer.exe', 'leidian1')
        cases = [
            SimpleNamespace(returncode=1, stdout=''),
            SimpleNamespace(returncode=0, stdout='invalid output'),
            SimpleNamespace(returncode=0, stdout='1,窗口,0,202,1,12,22'),
            SimpleNamespace(returncode=0, stdout='1,窗口,102,202,1,12,22'),
            subprocess.TimeoutExpired('ldconsole', 5),
            FileNotFoundError('ldconsole'),
        ]
        for result in cases:
            with (
                self.subTest(result=result),
                patch.object(platform_windows.subprocess, 'run', side_effect=[result]),
                patch.object(platform_windows, 'get_window_process_id', return_value=99),
            ):
                self.assertEqual(self.platform._get_emulator_window(), 0)

    def test_other_emulators_match_path_and_exact_instance_arguments(self):
        cases = [
            ('D:/Nox/bin/Nox.exe', 'Nox_1', ['-clone:Nox_1'], ['-clone:Nox_10']),
            ('D:/BlueStacks_nxt/HD-Player.exe', 'Pie64', ['--instance', 'Pie64'], ['--instance', 'Pie64_1']),
            ('D:/BlueStacks/Bluestacks.exe', 'Android_1', ['-vmname', 'Android_1'], ['-vmname', 'Android_10']),
            ('D:/MEmu/MEmu.exe', 'MEmu_1', ['MEmu_1'], ['MEmu_10']),
            ('D:/MuMu9/emulator/nemu9/EmulatorShell/NemuPlayer.exe',
             'nemu-12.0-x64-1', ['-m', 'nemu-12.0-x64-1'], ['-m', 'nemu-12.0-x64-10']),
        ]
        for path, name, args, other_args in cases:
            with self.subTest(name=name):
                self.set_instance(path, name)
                processes = [
                    SimpleNamespace(pid=1, info={'exe': 'D:/Other/other.exe', 'cmdline': ['other.exe', *args]}),
                    SimpleNamespace(pid=2, info={'exe': path, 'cmdline': [path, *other_args]}),
                    SimpleNamespace(pid=3, info={'exe': path.lower().replace('/', '\\'), 'cmdline': [path, *args]}),
                ]
                self.window.reset_mock()
                with patch.object(psutil, 'process_iter', return_value=processes):
                    self.assertEqual(self.platform._get_emulator_window(), 100)
                self.window.assert_called_once_with(3)

    def test_missing_or_duplicate_process_is_skipped(self):
        self.set_instance('D:/Nox/bin/Nox.exe', 'Nox_1')
        process = SimpleNamespace(pid=1, info={
            'exe': 'D:/Nox/bin/Nox.exe', 'cmdline': ['Nox.exe', '-clone:Nox_1'],
        })
        for processes in ([], [process, process]):
            with patch.object(psutil, 'process_iter', return_value=processes):
                self.assertEqual(self.platform._get_emulator_window(), 0)
        self.window.assert_not_called()


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器启动焦点回归测试')
class TestEmulatorStartWindow(unittest.TestCase):
    def setUp(self):
        self.platform = PlatformWindows.__new__(PlatformWindows)
        # read_run_param 对 None config 回退默认值,本测试无需真实配置
        self.platform.config = None
        self.platform.emulator_instance = SimpleNamespace(serial='127.0.0.1:5555')
        self.platform.serial = '127.0.0.1:5555'
        devices = Mock()
        devices.first_or_none.return_value = SimpleNamespace(status='device')
        self.platform.list_device = Mock()
        self.platform.list_device.return_value.select.return_value = devices
        self.platform.adb_shell = Mock(return_value='pong')
        self.platform.list_known_packages = Mock(side_effect=[[], ['package']])
        self.platform._get_emulator_window = Mock(return_value=100)
        self.focus = self.enterContext(patch.object(platform_windows, 'get_focused_window'))
        self.set_focus = self.enterContext(patch.object(platform_windows, 'set_focus_window'))
        self.minimize = self.enterContext(patch.object(platform_windows, 'minimize_window'))
        self.flash = self.enterContext(patch.object(platform_windows, 'flash_window'))
        self.enterContext(patch.object(platform_windows, 'logger'))
        timer = Mock()
        timer.start.return_value = timer
        timer.reached.side_effect = [False, False, False, True]
        timer.reached_and_reset.return_value = False
        self.enterContext(patch.object(platform_windows, 'Timer', return_value=timer))

    def test_focus_switch_does_not_change_minimize_target(self):
        self.focus.side_effect = itertools.chain([1], itertools.repeat(2))

        self.assertTrue(self.platform.emulator_start_watch())

        self.minimize.assert_called_once_with(100)
        self.set_focus.assert_not_called()
        self.flash.assert_called_once_with(100, flash=True)

    def test_emulator_taking_focus_restores_previous_window(self):
        self.focus.side_effect = itertools.chain([1], itertools.repeat(100))

        self.assertTrue(self.platform.emulator_start_watch())

        self.minimize.assert_called_once_with(100)
        self.set_focus.assert_called_once_with(1)

    def test_missing_window_does_not_touch_other_applications(self):
        self.platform._get_emulator_window.return_value = 0
        self.focus.side_effect = itertools.chain([1], itertools.repeat(2))

        self.assertTrue(self.platform.emulator_start_watch())

        self.minimize.assert_not_called()
        self.set_focus.assert_not_called()
        self.flash.assert_not_called()

    def test_missing_initial_focus_still_minimizes_emulator(self):
        self.focus.return_value = 0

        self.assertTrue(self.platform.emulator_start_watch())

        self.minimize.assert_called_once_with(100)
        self.set_focus.assert_not_called()

    def test_emulator_already_focused_still_minimizes_itself(self):
        self.focus.return_value = 100

        self.assertTrue(self.platform.emulator_start_watch())

        self.minimize.assert_called_once_with(100)
        self.set_focus.assert_not_called()
