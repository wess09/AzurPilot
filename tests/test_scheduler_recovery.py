"""使用真实调度循环验证恢复边界，所有设备、通知和后台服务均隔离。"""

import unittest
from unittest.mock import Mock, call, patch

from alas import AzurLaneAutoScript
from module.config.config import TaskEnd
from module.exception import (
    AutoSearchSetError,
    EmulatorNotRunningError,
    GameBugError,
    GameNotRunningError,
    GamePageUnknownError,
    GameStuckError,
    GameTooManyClickError,
    RequestHumanTakeover,
    ScriptError,
)


class TestSchedulerRecovery(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('alas.logger'))
        self.notify = self.enterContext(patch('alas.handle_notify'))
        self.webui = self.enterContext(patch('alas.notify_webui'))
        self.report = self.enterContext(patch('alas.ApiClient.submit_bug_log'))
        self.sleep = self.enterContext(patch('alas.time.sleep'))
        self.enterContext(patch('alas.del_cached_property'))
        self.enterContext(patch('module.config.utils.is_oobe_needed', return_value=False))
        self.enterContext(patch('module.base.backup.backup'))
        self.enterContext(patch('module.runtime.preview.set_task'))
        self.enterContext(patch.dict('os.environ', {'ALAS_DEBUG_SERVER': '0'}))
        self.enterContext(patch('module.runtime.scheduler_lock.acquire_scheduler_lock', return_value=None))

    def make_script(self, *, strict=False, sensitive=False):
        script = AzurLaneAutoScript('test')
        script.is_first_task = False
        script._channel_float_done = True
        script.__dict__['config'] = Mock(
            DailySummary_Enable=False,
            EmulatorManagement_ScheduledEmulatorRestart=False,
            Scheduler_PushNotification=False,
            Error_StrictRestart=strict,
            Error_GameStuckRestart=True,
            Error_GameStuckThreshold=3,
            Error_HandleError=True,
            Error_LlmAnalysis=False,
        )
        script.config.cross_get.return_value = sensitive
        script.__dict__['device'] = Mock()
        script.__dict__['checker'] = Mock()
        script.checker.is_recovered.return_value = False
        script.checker.is_available.return_value = True
        script.save_error_log = Mock()
        script._start_watchdog = Mock()
        script._stop_daily_summary_scheduler = Mock()
        script._record_daily_summary_task_finish = Mock()
        script._try_restart_emulator = Mock(return_value=True)
        script.handle_channel_float = Mock()
        script.restart = Mock()
        script.commission = Mock()
        return script

    def run_tasks(self, script, tasks):
        """每次循环消耗一个任务或异常，最后由停止事件结束，避免无限重试。"""
        script.get_next_task = Mock(side_effect=tasks)
        script.stop_event = Mock()
        script.stop_event.is_set.side_effect = [False] * len(tasks) + [True]
        return script.loop()

    def test_unhandled_task_failure_returns_false_when_recovery_is_disabled(self):
        script = self.make_script()
        script.config.Error_HandleError = False
        script.run = Mock(return_value=False)

        self.assertIs(self.run_tasks(script, ['Commission']), False)

        script._stop_daily_summary_scheduler.assert_called_once_with()
        script._try_restart_emulator.assert_not_called()
        script.config.task_call.assert_not_called()

    def test_initial_device_offline_is_recovered_by_scheduler(self):
        script = self.make_script()
        del script.__dict__['device']
        del script.__dict__['_try_restart_emulator']
        script.config.task.command = 'Commission'
        script.config.Error_AdbOfflineThreshold = 3
        connected_device = Mock()
        with (
            patch(
                'module.device.device.Device',
                side_effect=[EmulatorNotRunningError('设备离线'), connected_device],
            ) as device_class,
            patch('module.device.platform.Platform') as platform_class,
        ):
            self.run_tasks(script, ['Commission', 'Restart'])

        self.assertEqual(device_class.call_args_list, [
            call(config=script.config, auto_start_emulator=False),
            call(config=script.config, auto_start_emulator=False),
        ])
        platform_class.assert_called_once_with(script.config, connect=False)
        platform_class.return_value.emulator_stop.assert_called_once_with()
        platform_class.return_value.emulator_start.assert_called_once_with(deep=False, failures=0)
        script.config.task_call.assert_called_once_with('Restart')
        script.restart.assert_called_once_with()
        script.commission.assert_not_called()
        self.assertEqual(self.sleep.call_args_list, [call(5), call(20)])

    def test_strict_restart_policy_for_task_exceptions(self):
        errors = (
            GameNotRunningError, GameStuckError, GameTooManyClickError,
            GameBugError, GamePageUnknownError, ScriptError,
            EmulatorNotRunningError, RequestHumanTakeover, AutoSearchSetError,
            RuntimeError,
        )
        for error_type in errors:
            for strict, sensitive in ((False, False), (False, True), (True, False), (True, True)):
                with self.subTest(error=error_type.__name__, strict=strict, sensitive=sensitive):
                    script = self.make_script(strict=strict, sensitive=sensitive)
                    script.opsi_cross_month = Mock(side_effect=error_type('测试异常'))
                    if strict and sensitive:
                        with self.assertRaises(SystemExit) as caught:
                            script.run('opsi_cross_month')
                        self.assertEqual(caught.exception.code, 1)
                        script.config.task_call.assert_not_called()
                        script._try_restart_emulator.assert_not_called()
                    else:
                        self.assertEqual(script.run('opsi_cross_month'), 'recoverable')
                        script.config.task_call.assert_called_once_with('Restart')
                    if strict:
                        script.config.cross_get.assert_called_with(
                            keys='OpsiCrossMonth.Scheduler.Sensitive', default=False,
                        )

    def test_strict_restart_policy_for_failed_scheduler_result(self):
        for strict, sensitive in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(strict=strict, sensitive=sensitive):
                script = self.make_script(strict=strict, sensitive=sensitive)
                script.run = Mock(return_value=False)
                if strict and sensitive:
                    with self.assertRaises(SystemExit):
                        self.run_tasks(script, ['OpsiCrossMonth'])
                    self.report.assert_called_once()
                else:
                    self.run_tasks(script, ['OpsiCrossMonth'])
                self.assertEqual(script.failure_record['OpsiCrossMonth'], 1)
                script._try_restart_emulator.assert_not_called()

    def test_game_faults_escalate_across_successful_restarts(self):
        for error_type in (GameStuckError, GameTooManyClickError, RuntimeError):
            with self.subTest(error=error_type.__name__):
                script = self.make_script()
                script.commission.side_effect = error_type('重复故障')
                self.run_tasks(script, ['Commission', 'Restart', 'Commission', 'Restart', 'Commission'])

                script._try_restart_emulator.assert_called_once_with()
                self.assertEqual(script.commission.call_count, 3)
                self.assertEqual(script.restart.call_count, 2)
                self.assertEqual(script.failure_record['Commission'], 0)

    def test_script_errors_still_stop_after_three_failures_with_restarts(self):
        script = self.make_script()
        script.commission.side_effect = ScriptError('重复脚本错误')
        with self.assertRaises(SystemExit) as caught:
            self.run_tasks(script, ['Commission', 'Restart', 'Commission', 'Restart', 'Commission'])

        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(script.script_error_count, 3)
        script._try_restart_emulator.assert_not_called()
        self.assertEqual(script.config.task_call.call_count, 2)

    def test_success_breaks_script_error_streak(self):
        script = self.make_script()
        script.commission.side_effect = [ScriptError('故障一'), None, ScriptError('故障二'), ScriptError('故障三')]
        self.run_tasks(script, ['Commission', 'Restart', 'Commission', 'Commission', 'Restart', 'Commission'])

        self.assertEqual(script.script_error_count, 2)
        self.assertEqual(script.commission.call_count, 4)

    def test_success_and_task_end_reset_all_task_error_counters(self):
        for outcome in (None, TaskEnd()):
            with self.subTest(outcome=outcome):
                script = self.make_script()
                script.consecutive_game_stuck = 2
                script.consecutive_adb_offline = 2
                script.consecutive_unexpected_error = 2
                script.script_error_count = 2
                script.commission.side_effect = [outcome]
                self.run_tasks(script, ['Commission'])

                self.assertEqual(script.consecutive_game_stuck, 0)
                self.assertEqual(script.consecutive_adb_offline, 0)
                self.assertEqual(script.consecutive_unexpected_error, 0)
                self.assertEqual(script.script_error_count, 0)

    def test_restart_success_preserves_all_task_error_counters(self):
        script = self.make_script()
        script.consecutive_game_stuck = 2
        script.consecutive_adb_offline = 2
        script.consecutive_unexpected_error = 2
        script.script_error_count = 2
        self.run_tasks(script, ['Restart'])

        self.assertEqual(script.consecutive_game_stuck, 2)
        self.assertEqual(script.consecutive_adb_offline, 2)
        self.assertEqual(script.consecutive_unexpected_error, 2)
        self.assertEqual(script.script_error_count, 2)

    def test_global_backoff_increases_across_successful_restarts(self):
        script = self.make_script()
        self.run_tasks(script, [RuntimeError('故障一'), 'Restart', RuntimeError('故障二'), 'Restart', RuntimeError('故障三')])

        self.assertEqual(self.sleep.call_args_list, [call(20), call(40), call(80)])
        self.report.assert_called_once()

    def test_ordinary_task_success_resets_global_backoff(self):
        script = self.make_script()
        self.run_tasks(script, [RuntimeError('故障一'), 'Commission', RuntimeError('故障二')])

        self.assertEqual(self.sleep.call_args_list, [call(20), call(20)])

    def test_repeated_same_unexpected_error_delays_task_despite_other_successes(self):
        # 9/22 实机：Main 每轮抛同一个 AttributeError，中间穿插的其他任务成功
        # 会清零全局计数，导致 7 小时内 Main 崩溃 373 次。按任务计数不受其他任务影响。
        script = self.make_script()
        script.config.Error_GameStuckThreshold = 10
        script.main = Mock(side_effect=AttributeError('is_os'))
        self.run_tasks(script, [
            'Main', 'Restart', 'Commission',
            'Main', 'Restart', 'Commission',
            'Main',
        ])

        script.config.task_delay.assert_called_once_with(server_update=True, task='Main')
        self.assertNotIn('Main', script.unexpected_error_record)
        script._try_restart_emulator.assert_not_called()

    def test_different_unexpected_errors_do_not_delay_task(self):
        script = self.make_script()
        script.config.Error_GameStuckThreshold = 10
        script.main = Mock(side_effect=[AttributeError('a'), KeyError('b'), TypeError('c')])
        self.run_tasks(script, ['Main', 'Restart', 'Main', 'Restart', 'Main'])

        script.config.task_delay.assert_not_called()
        self.assertEqual(script.unexpected_error_record['Main'][1], 1)

    def test_task_success_clears_its_unexpected_error_record(self):
        script = self.make_script()
        script.config.Error_GameStuckThreshold = 10
        script.main = Mock(side_effect=[AttributeError('is_os'), AttributeError('is_os'), None])
        self.run_tasks(script, ['Main', 'Restart', 'Main', 'Restart', 'Main'])

        script.config.task_delay.assert_not_called()
        self.assertNotIn('Main', script.unexpected_error_record)

    def test_restart_defers_channel_float_handling_until_next_task(self):
        for command in ('restart', 'Restart'):
            with self.subTest(command=command):
                script = self.make_script()
                self.assertTrue(script.run(command))
                script.restart.assert_called_once_with()
                self.assertFalse(script._channel_float_done)
                script.handle_channel_float.assert_not_called()

                self.assertTrue(script.run('commission'))
                script.handle_channel_float.assert_called_once_with()
                script.commission.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
