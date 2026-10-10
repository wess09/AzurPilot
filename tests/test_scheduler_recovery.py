"""使用真实调度循环验证恢复边界，所有设备、通知和后台服务均隔离。"""

import unittest
from datetime import datetime, timedelta
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
    MindCalculatorScanError,
    RequestHumanTakeover,
    ScriptError,
    StorageStatisticsError,
)


class TestSchedulerRecovery(unittest.TestCase):
    def setUp(self):
        self.logger = self.enterContext(patch('alas.logger'))
        self.notify = self.enterContext(patch('alas.handle_notify'))
        self.webui = self.enterContext(patch('alas.notify_webui'))
        self.report = self.enterContext(patch('alas.ApiClient.submit_bug_log'))
        self.sleep = self.enterContext(patch('alas.time.sleep'))
        self.enterContext(patch('alas.del_cached_property'))
        self.enterContext(patch('module.config.utils.is_oobe_needed', return_value=False))
        self.enterContext(patch('module.base.backup.backup'))
        self.enterContext(patch('module.runtime.preview.set_task'))
        self.enterContext(patch.dict('os.environ', {'ALAS_DEBUG_SERVER': '0'}))

    def make_script(self, *, strict=False, sensitive=False):
        script = AzurLaneAutoScript('test')
        script.is_first_task = False
        script._channel_float_done = True
        script.__dict__['config'] = Mock(
            DailySummary_Enable=False,
            EmulatorManagement_ScheduledEmulatorRestart=False,
            Scheduler_PushNotification=False,
            Error_StrictRestart=strict,
            Error_TaskRestartLimit=0,
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

    def test_repeated_storage_recognition_failures_do_not_restart_or_stop_scheduler(self):
        script = self.make_script()
        script.config.Error_HandleError = False
        script.storage_statistics = Mock(side_effect=StorageStatisticsError('数量无法确认，已延后'))
        self.run_tasks(script, ['StorageStatistics'] * 3)
        self.assertEqual(script.storage_statistics.call_count, 3)
        script._try_restart_emulator.assert_not_called()
        script.config.task_call.assert_not_called()
        self.assertNotIn('StorageStatistics', script.failure_record)

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

    def test_mind_scan_recognition_failure_reports_cause_without_restart(self):
        script = self.make_script()
        error = MindCalculatorScanError('相邻船坞截图没有明确的重叠位移')
        script.mind_calculator_scan = Mock(side_effect=error)
        self.assertFalse(script.run('MindCalculatorScan'))
        script.save_error_log.assert_called_once_with()
        script._try_restart_emulator.assert_not_called()
        script.config.task_call.assert_not_called()
        self.assertEqual(self.logger.error_context.call_args.kwargs['reason'], str(error))
        self.assertIs(self.logger.error_context.call_args.kwargs['exc'], error)

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

    def test_repeated_recovery_defers_only_failing_task_and_pushes_in_low_mode(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 3
        script.config.Error_LowPushMode = True
        script.config.Error_OnePushConfig = 'provider: null'
        script.commission.side_effect = GameStuckError('重复故障')
        script.research = Mock()
        tomorrow = datetime.now().replace(microsecond=0) + timedelta(days=1)
        with patch('alas.get_server_next_update', return_value=tomorrow):
            self.run_tasks(script, ['Commission', 'Restart', 'Research',
                                    'Commission', 'Restart', 'Commission'])

        script.config.task_delay.assert_called_once_with(target=tomorrow, task='Commission')
        self.assertEqual(script.task_restart_delays, {'Commission': tomorrow})
        self.assertNotIn('Commission', script.task_restart_record)
        self.assertEqual(script.restart.call_count, 2)
        script.research.assert_called_once_with()
        alerts = [c for c in self.notify.call_args_list if '已达上限' in c.kwargs['title']]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].args, ('provider: null',))
        self.assertIn('连续恢复 3 次', alerts[0].kwargs['content'])

    def test_success_resets_only_its_own_restart_streak(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 3
        script.task_restart_record = {'Commission': 2, 'Research': 2}
        self.run_tasks(script, ['Restart', 'Commission'])
        self.assertEqual(script.task_restart_record, {'Research': 2})
        script.config.task_delay.assert_not_called()

    def test_disabled_limit_keeps_existing_recovery(self):
        script = self.make_script()
        script.commission.side_effect = GameNotRunningError('未运行')
        self.run_tasks(script, ['Commission'] * 5)
        script.config.task_delay.assert_not_called()
        self.assertEqual(script.config.task_call.call_count, 5)

    def test_failed_restart_task_is_never_deferred(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 2
        script.restart.side_effect = GameNotRunningError('无法启动')
        self.run_tasks(script, ['Restart'] * 5)
        self.assertEqual(script.restart.call_count, 5)
        self.assertEqual(script.config.task_call.call_args_list, [call('Restart')] * 5)
        script.config.task_delay.assert_not_called()
        self.assertNotIn('Restart', script.task_restart_record)
        self.assertNotIn('Restart', script.task_restart_delays)

    def test_restart_bypasses_stale_cooldown_in_all_scheduler_modes(self):
        for mode in ('native', 'enhance', 'takeover'):
            with self.subTest(mode=mode):
                script = self.make_script()
                script.config.Error_TaskRestartLimit = 1
                script.task_restart_record = {'Restart': 3, 'Commission': 2}
                deadline = datetime.now() + timedelta(days=1)
                script.task_restart_delays = {'Restart': deadline, 'Commission': deadline}
                script.__dict__['_program_runtime'] = Mock(mode=mode)
                script.wait_until = Mock()
                self.run_tasks(script, ['Restart'])
                script.restart.assert_called_once_with()
                script.config.task_delay.assert_not_called()
                script.wait_until.assert_not_called()
                self.assertEqual(script.task_restart_record, {'Commission': 2})
                self.assertEqual(script.task_restart_delays, {'Commission': deadline})

    def test_restart_global_failures_keep_recovering_emulator_and_game(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 2
        script.device.stuck_record_clear.side_effect = EmulatorNotRunningError('设备离线')
        self.run_tasks(script, ['Restart'] * 4)
        self.assertEqual(script._try_restart_emulator.call_count, 4)
        self.assertEqual(script.config.task_call.call_args_list, [call('Restart')] * 4)
        script.config.task_delay.assert_not_called()
        self.assertEqual(script.task_restart_record, {})
        self.assertEqual(script.task_restart_delays, {})

    def test_restart_failed_results_still_escalate_to_emulator_recovery(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 1
        script.run = Mock(return_value=False)
        self.run_tasks(script, ['Restart'] * 3)
        script._try_restart_emulator.assert_called_once_with()
        script.config.task_call.assert_called_once_with('Restart')
        script.config.task_delay.assert_not_called()

    def test_custom_dispatch_cannot_bypass_cooldown_and_resumes_after_deadline(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 3
        now = datetime(2026, 10, 1, 12)
        deadline = datetime(2026, 10, 2)
        script.task_restart_delays['Commission'] = deadline
        runtime = script.__dict__['_program_runtime'] = Mock(mode='takeover')
        script.wait_until = Mock()
        with patch('alas.current_time', return_value=now):
            self.run_tasks(script, ['Commission'])
        script.commission.assert_not_called()
        runtime.task_finished.assert_called_once_with('Commission', False)
        script.wait_until.assert_called_once_with(now + timedelta(seconds=4))
        with patch('alas.current_time', return_value=deadline):
            self.run_tasks(script, ['Commission'])
        script.commission.assert_called_once_with()
        self.assertEqual(script.task_restart_delays, {})

    def test_global_failure_after_task_selection_counts_toward_limit(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 2
        script.device.stuck_record_clear.side_effect = RuntimeError('设备故障')
        tomorrow = datetime.now() + timedelta(days=1)
        with patch('alas.get_server_next_update', return_value=tomorrow):
            self.run_tasks(script, ['Commission', 'Commission'])
        script.config.task_delay.assert_called_once_with(target=tomorrow, task='Commission')
        self.assertEqual(script._try_restart_emulator.call_count, 2)
        self.assertEqual(script.config.task_call.call_args_list, [call('Restart')] * 2)

    def test_global_failure_recovers_before_deferring_business_task(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 1
        script.device.stuck_record_clear.side_effect = EmulatorNotRunningError('设备离线')
        recovery = Mock()
        recovery.attach_mock(script._try_restart_emulator, 'emulator')
        recovery.attach_mock(script.config.task_call, 'game')
        recovery.attach_mock(script.config.task_delay, 'defer')
        tomorrow = datetime.now() + timedelta(days=1)
        with patch('alas.get_server_next_update', return_value=tomorrow):
            self.run_tasks(script, ['Commission'])
        self.assertEqual(recovery.mock_calls, [
            call.emulator(), call.game('Restart'),
            call.defer(target=tomorrow, task='Commission'),
        ])

    def test_global_failure_preserves_sensitive_task_protection(self):
        for strict, sensitive in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(strict=strict, sensitive=sensitive):
                script = self.make_script(strict=strict, sensitive=sensitive)
                script.config.Error_TaskRestartLimit = 1
                script.device.stuck_record_clear.side_effect = RuntimeError('任务初始化失败')
                tomorrow = datetime.now() + timedelta(days=1)
                with patch('alas.get_server_next_update', return_value=tomorrow):
                    if strict and sensitive:
                        with self.assertRaises(SystemExit) as caught:
                            self.run_tasks(script, ['OpsiCrossMonth'])
                        self.assertEqual(caught.exception.code, 1)
                        script._try_restart_emulator.assert_not_called()
                        script.config.task_call.assert_not_called()
                        script.config.task_delay.assert_not_called()
                    else:
                        self.run_tasks(script, ['OpsiCrossMonth'])
                        script._try_restart_emulator.assert_called_once_with()
                        script.config.task_call.assert_called_once_with('Restart')
                        script.config.task_delay.assert_called_once_with(
                            target=tomorrow, task='OpsiCrossMonth')

    def test_notification_failure_does_not_undo_deferral(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 1
        self.notify.side_effect = RuntimeError('推送失败')
        tomorrow = datetime.now() + timedelta(days=1)
        with patch('alas.get_server_next_update', return_value=tomorrow):
            self.assertTrue(script._record_task_restart('Commission', 'recoverable'))
        self.assertEqual(script.task_restart_delays['Commission'], tomorrow)
        self.webui.assert_called_once()
        self.assertEqual(self.webui.call_args.args, ('test',))
        self.assertEqual(self.webui.call_args.kwargs['title'], '任务已延后至次日')

    def test_webui_notification_failure_does_not_undo_deferral_or_push(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 1
        self.webui.side_effect = RuntimeError('WebUI 通知失败')
        tomorrow = datetime.now() + timedelta(days=1)
        with patch('alas.get_server_next_update', return_value=tomorrow):
            self.assertTrue(script._record_task_restart('Commission', 'recoverable'))
        self.assertEqual(script.task_restart_delays['Commission'], tomorrow)
        self.notify.assert_called_once()
        self.webui.assert_called_once()

    def test_emulator_restart_does_not_reset_task_restart_limit(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 5
        script.run = Mock(return_value=False)
        tomorrow = datetime.now() + timedelta(days=1)
        with patch('alas.get_server_next_update', return_value=tomorrow):
            self.run_tasks(script, ['Commission'] * 5)
        script._try_restart_emulator.assert_called_once_with()
        script.config.task_delay.assert_called_once_with(target=tomorrow, task='Commission')

    def test_midnight_deferral_is_always_in_the_future(self):
        script = self.make_script()
        script.config.Error_TaskRestartLimit = 1
        now = datetime(2026, 10, 1)
        with (patch('alas.current_time', return_value=now),
              patch('alas.get_server_next_update', return_value=now) as next_update):
            script._record_task_restart('Commission', False)
        next_update.assert_called_once_with('00:00')
        script.config.task_delay.assert_called_once_with(
            target=now + timedelta(days=1), task='Commission')


if __name__ == '__main__':
    unittest.main()
