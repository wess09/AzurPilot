"""Windows 模拟器启动须同时脱离进程树、启动器 Job 和退出清理标记。"""

import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from module.device.env import IS_WINDOWS

if IS_WINDOWS:
    from module.device.platform.platform_windows import PlatformWindows


@unittest.skipUnless(IS_WINDOWS, 'Windows 模拟器进程生命周期测试')
class TestEmulatorProcessLifetime(unittest.TestCase):
    COMMAND = '"C:/Program Files/Emulator/player.exe" --instance 2'

    def test_launcher_capability_detaches_job_and_removes_private_environment(self):
        environment = {
            'PATH': 'fixture-path',
            'ALAS_LAUNCHER_PID': '12345',
            'ALAS_LAUNCHER_JOB_BREAKAWAY': '1',
            'ALAS_WEBUI_TRUST_SECRET': 'test-only',
        }
        process = Mock()
        with patch.dict(os.environ, environment, clear=True), patch(
            'module.device.platform.platform_windows.subprocess.Popen', return_value=process,
        ) as spawn:
            self.assertIs(PlatformWindows.execute(self.COMMAND), process)
            self.assertEqual(dict(os.environ), environment)

        self.assertEqual(spawn.call_args.args, (f'start "" /b {self.COMMAND}',))
        self.assertEqual(spawn.call_args.kwargs['env'], {'PATH': 'fixture-path'})
        self.assertEqual(
            spawn.call_args.kwargs['creationflags'],
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB,
        )
        self.assertTrue(spawn.call_args.kwargs['shell'])
        self.assertTrue(spawn.call_args.kwargs['close_fds'])
        process.wait.assert_called_once_with(timeout=5)

    def test_old_launcher_and_direct_launch_do_not_request_unsupported_breakaway(self):
        for capability in (None, '0', 'true'):
            with self.subTest(capability=capability):
                environment = {'ALAS_LAUNCHER_PID': '12345', 'PATH': 'fixture-path'}
                if capability is not None:
                    environment['ALAS_LAUNCHER_JOB_BREAKAWAY'] = capability
                with patch.dict(os.environ, environment, clear=True), patch(
                    'module.device.platform.platform_windows.subprocess.Popen',
                ) as spawn:
                    PlatformWindows.execute(self.COMMAND)
                self.assertEqual(spawn.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
                self.assertEqual(spawn.call_args.kwargs['env'], {'PATH': 'fixture-path'})

    def test_shell_timeout_keeps_bounded_wait(self):
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired('cmd', 5)
        with patch('module.device.platform.platform_windows.subprocess.Popen', return_value=process):
            self.assertIs(PlatformWindows.execute(self.COMMAND), process)
        process.wait.assert_called_once_with(timeout=5)
        process.kill.assert_not_called()

    def test_breakaway_failure_does_not_silently_start_inside_launcher_job(self):
        with patch.dict(os.environ, {'ALAS_LAUNCHER_JOB_BREAKAWAY': '1'}), patch(
            'module.device.platform.platform_windows.subprocess.Popen',
            side_effect=OSError('test job rejects breakaway'),
        ) as spawn:
            with self.assertRaisesRegex(OSError, 'rejects breakaway'):
                PlatformWindows.execute(self.COMMAND)
        spawn.assert_called_once()

    def test_synchronous_management_command_keeps_existing_behavior(self):
        result = subprocess.CompletedProcess('manager', 0)
        with patch('module.device.platform.platform_windows.subprocess.run', return_value=result) as run, patch(
            'module.device.platform.platform_windows.subprocess.Popen',
        ) as spawn:
            self.assertIs(PlatformWindows.execute('manager shutdown', wait=True, timeout=7), result)
        spawn.assert_not_called()
        self.assertEqual(run.call_args.kwargs['timeout'], 7)
        self.assertEqual(run.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    def test_synchronous_timeout_still_returns_none(self):
        with patch('module.device.platform.platform_windows.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('manager', 7)):
            self.assertIsNone(PlatformWindows.execute('manager shutdown', wait=True, timeout=7))


if __name__ == '__main__':
    unittest.main()
