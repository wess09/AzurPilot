"""在原有恢复流程上验证授权边界、真实原生对象和工作进程退出。"""

import json
import multiprocessing
from types import SimpleNamespace
import tempfile
import threading
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from module.config.recovery import RecoveryStopped
from module.device.method.retry import retry_backend
from module.exception import (
    EmulatorNotRunningError, GameBugError, GameNotRunningError, GamePageUnknownError,
    GameStuckError, GameTooManyClickError, RequestHumanTakeover, ScriptError,
)
from tests import test_scheduler_recovery as legacy_recovery


def worker_exit_probe(folder, background, queue):
    """隔离子进程只调用生产调度入口，所有设备、通知和备份均替换。"""
    from contextlib import ExitStack
    from alas import AzurLaneAutoScript
    from module.runtime.process_manager import ProcessManager

    with ExitStack() as stack:
        for name in ('alas.logger', 'alas.handle_notify', 'alas.notify_webui',
                     'module.runtime.preview.set_task', 'module.base.backup.backup'):
            stack.enter_context(patch(name))
        stack.enter_context(patch('module.config.utils.is_oobe_needed', return_value=False))
        stack.enter_context(patch.dict('os.environ', {'ALAS_DEBUG_SERVER': '0'}))
        script = AzurLaneAutoScript('isolated-recovery')
        script.config = Mock(
            Error_HandleError=False, Error_StrictRestart=False, Error_TaskRestartLimit=0,
            DailySummary_Enable=False, EmulatorManagement_ScheduledEmulatorRestart=False,
            Error_WatchdogEnable=True, Error_WatchdogTaskEnable=True, Error_WatchdogTaskTimeout=1,
        )
        script.device = Mock()
        script.checker = Mock()
        script.checker.is_recovered.return_value = False
        script._channel_float_done = True
        script._start_watchdog = Mock()
        script._sync_background_services = Mock()
        script.get_next_task = Mock(return_value='Commission')
        script.commission = Mock(side_effect=GameStuckError('模拟故障'))
        script.save_error_log = lambda: Path(folder, 'scene.txt').write_text('已保存', encoding='utf-8')

        def forbidden(*args, **kwargs):
            Path(folder, 'forbidden.txt').write_text('越权恢复', encoding='utf-8')
            raise AssertionError('不允许恢复')

        script.config.task_call = Mock(side_effect=forbidden)
        script.device.app_start.side_effect = forbidden
        script.device.app_stop.side_effect = forbidden
        script._try_restart_emulator = Mock(side_effect=forbidden)
        if background:
            threading.Thread(target=lambda: script._watchdog_recover(61, task_name='Commission'),
                             daemon=True).start()
            threading.Event().wait(40)
            raise AssertionError('监护没有结束整个 worker')
        stack.enter_context(patch.object(ProcessManager, '_run_process', side_effect=lambda *args: script.loop()))
        ProcessManager.run_process('isolated-recovery', 'alas', queue, run_id='isolated-probe')


class RecoveryAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.legacy = legacy_recovery.TestSchedulerRecovery()
        self.legacy.setUp()
        self.addCleanup(self.legacy.doCleanups)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / 'instance.json'
        self.enterContext(patch('module.config.recovery.filepath_config', return_value=str(self.path)))
        self.enterContext(patch('alas.filepath_config', return_value=str(self.path)))
        self.script = self.legacy.make_script()
        self.script.config.config_name = 'isolated-recovery'
        self.script.config.task.command = 'Commission'
        self.script._emulator_op_with_timeout = Mock(side_effect=lambda func, **kwargs: func())
        del self.script.__dict__['_try_restart_emulator']
        self.script.device.emulator_stop.return_value = True
        self.script.device.emulator_start.return_value = False
        self.data = {
            'Alas': {'Error': {
                'HandleError': True, 'StrictRestart': False, 'TaskRestartLimit': 5,
                'AdbOfflineRestart': True, 'AdbOfflineThreshold': 3,
                'GameStuckRestart': True, 'GameStuckThreshold': 3,
                'WatchdogEnable': False, 'WatchdogTaskEnable': True, 'WatchdogTaskTimeout': 1,
            }, 'EmulatorManagement': {'ScheduledEmulatorRestart': False, 'ForceScheduledRestart': False,
                                      'RestartIntervalHours': 1}, 'DailySummary': {'Enable': False}},
            'RunParams': {'Reboot': {'Tries': 3}},
        }
        self.write()
        self.enterContext(patch.dict('os.environ', {}))

    def write(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')

    def settings(self, **values):
        self.data['Alas']['Error'].update(values)
        self.write()

    def test_disabled_master_stops_all_fault_types_before_recovery_or_rescheduling(self):
        self.settings(HandleError=False)
        for kind in (GameStuckError, GameTooManyClickError, GameNotRunningError,
                     GameBugError, GamePageUnknownError, EmulatorNotRunningError,
                     RequestHumanTakeover, ScriptError, AttributeError):
            with self.subTest(error=kind.__name__):
                self.script.commission.side_effect = kind('模拟故障')
                with self.assertRaises(SystemExit) as stopped:
                    self.script.run('Commission')
                self.assertEqual(stopped.exception.code, 1)
        self.script.config.task_call.assert_not_called()
        self.script.device.emulator_stop.assert_not_called()
        self.script.device.app_start.assert_not_called()

    def test_repeated_offline_retains_original_recovery_from_all_scheduler_boundaries(self):
        for first in ('Commission', 'Restart', None):
            with self.subTest(first=first):
                script = self.legacy.make_script()
                script.config = self.script.config
                del script.__dict__['_try_restart_emulator']
                script._emulator_op_with_timeout = Mock(side_effect=lambda func, **kwargs: func())
                script.device.emulator_stop.return_value = True
                script.device.emulator_start.return_value = False
                offline = EmulatorNotRunningError('持续离线')
                tasks = [offline] * 7 if first is None else [first] + ['Restart'] * 6
                if first is not None:
                    script.device.stuck_record_clear.side_effect = offline
                script.config.task_call.reset_mock()
                self.legacy.run_tasks(script, tasks)
                self.assertEqual(script.device.emulator_start.call_count, 5)
                self.assertEqual(script.config.task_call.call_count, 7)
                script.config.task_delay.assert_not_called()

    def test_cold_start_can_launch_emulator_then_run_restart_and_business(self):
        script = self.script
        original = script.device
        del script.__dict__['device']
        script.config.task.command = 'Commission'
        offline = EmulatorNotRunningError('设备未启动')
        from module.device.platform import Platform
        with (patch('module.device.device.Device', side_effect=[offline, offline, offline, original]) as device,
              patch('module.device.platform.Platform', autospec=Platform) as platform):
            platform.return_value.emulator_stop.return_value = True
            platform.return_value.emulator_start.return_value = True
            self.legacy.run_tasks(script, ['Commission', 'Restart', 'Restart', 'Restart', 'Commission'])
        self.assertEqual(device.call_count, 4)
        platform.assert_called_once_with(script.config, connect=False)
        platform.return_value.emulator_start.assert_called_once_with(deep=False, failures=0)
        script.restart.assert_called_once_with()
        script.commission.assert_called_once_with()

    def test_saved_offline_switch_and_threshold_apply_without_loading_bound_config(self):
        self.settings(AdbOfflineRestart=False)
        for _ in range(4):
            self.assertFalse(self.script._try_restart_emulator())
        self.script.device.emulator_start.assert_not_called()
        self.settings(AdbOfflineRestart=True, AdbOfflineThreshold=2)
        self.assertFalse(self.script._try_restart_emulator())
        self.assertFalse(self.script._try_restart_emulator())
        self.script.device.emulator_start.assert_called_once()
        self.script.config.load.assert_not_called()
        self.script.config.bind.assert_not_called()

    def test_game_switch_does_not_disable_offline_recovery_or_stop_client_retries(self):
        self.settings(GameStuckRestart=False, AdbOfflineThreshold=1)
        self.script.restart.side_effect = GameStuckError('启动或登录卡住')
        self.legacy.run_tasks(self.script, ['Restart'] * 6)
        self.script.device.emulator_start.assert_not_called()
        self.assertEqual(self.script.restart.call_count, 6)
        self.assertFalse(self.script._try_restart_emulator())
        self.script.device.emulator_start.assert_called_once()

    def test_game_restart_failure_can_upgrade_without_becoming_offline(self):
        self.settings(AdbOfflineRestart=False)
        self.script.restart.side_effect = GameStuckError('游戏启停或观察阶段失败')
        self.legacy.run_tasks(self.script, ['Restart'] * 6)
        self.assertEqual(self.script.device.emulator_start.call_count, 4)

    def test_revoked_pending_recovery_stops_before_task_selection_or_device_initialization(self):
        self.script.commission.side_effect = GameStuckError('故障')
        self.assertEqual(self.script.run('Commission'), 'recoverable')
        self.settings(HandleError=False)
        self.script.get_next_task = Mock()
        with self.assertRaises(SystemExit):
            self.script.loop()
        self.script.get_next_task.assert_not_called()
        self.script.device.emulator_start.assert_not_called()

    def test_master_disable_after_restart_success_cannot_run_failed_business_task_again(self):
        self.script.commission.side_effect = GameStuckError('原业务任务故障')
        self.assertEqual(self.script.run('Commission'), 'recoverable')
        self.assertTrue(self.script.run('Restart'))
        self.settings(HandleError=False)
        with self.assertRaises(SystemExit):
            self.script.run('Commission')
        self.script.commission.assert_called_once()

    def test_successful_restart_clears_recovery_after_failed_business_was_deferred(self):
        self.script.commission.side_effect = GameStuckError('故障任务已进入次日冷却')
        self.assertEqual(self.script.run('Commission'), 'recoverable')
        self.script.task_restart_delays['Commission'] = datetime(2026, 10, 24)
        self.assertTrue(self.script.run('Restart'))
        self.assertIsNone(self.script._pending_recovery)

    def test_initialization_recovery_is_cleared_after_restart_without_business_failure(self):
        self.script._pending_recovery = ('Alas', EmulatorNotRunningError('启动前设备离线'))
        self.assertTrue(self.script.run('Restart'))
        self.assertIsNone(self.script._pending_recovery)

    def test_failed_restart_preserves_original_failed_task_for_live_permission_check(self):
        self.script.commission.side_effect = GameStuckError('原业务故障')
        self.assertEqual(self.script.run('Commission'), 'recoverable')
        self.script.restart.side_effect = EmulatorNotRunningError('恢复阶段离线')
        self.assertEqual(self.script.run('Restart'), 'recoverable')
        self.assertEqual(self.script._pending_recovery[0], 'commission')

    def test_watchdog_obeys_both_switches_and_waits_for_threshold_without_stopping_worker(self):
        script = self.script
        with patch('module.device.platform.Platform') as platform:
            script._watchdog_recover(61, task_name='Commission')
            platform.assert_not_called()
            self.settings(WatchdogEnable=True, GameStuckRestart=False)
            script._watchdog_recover(61, task_name='Commission')
            platform.assert_not_called()
            self.assertFalse(getattr(script, '_stopping_after_error', False))
            self.settings(GameStuckRestart=True)
            script._watchdog_recover(61, task_name='Commission')
            script._watchdog_recover(61, task_name='Commission')
            platform.assert_not_called()
            platform.return_value.emulator_stop.return_value = True
            script._watchdog_recover(61, task_name='Commission')
            script._watchdog_recover(61, task_name='Commission')
            platform.return_value.emulator_stop.assert_called_once()
        self.assertTrue(script._watchdog_recovery_pending)

    def test_scheduled_restart_is_independent_and_manual_manager_skips_device_initialization(self):
        self.settings(HandleError=False, AdbOfflineRestart=False, GameStuckRestart=False)
        self.data['Alas']['EmulatorManagement']['ScheduledEmulatorRestart'] = True
        self.write()
        self.script.device.emulator_start.return_value = True
        self.assertTrue(self.script._try_restart_emulator(reason='scheduled'))
        self.script.emulator_manager = Mock()
        self.script.device.screenshot.reset_mock()
        self.assertTrue(self.script.run('EmulatorManager'))
        self.script.emulator_manager.assert_called_once()
        self.script.device.screenshot.assert_not_called()

    def test_unknown_failure_cannot_request_emulator_restart_without_device_evidence(self):
        self.script.commission.side_effect = AttributeError('模拟脚本错误，不能据此判断模拟器离线')
        for _ in range(3):
            self.assertEqual(self.script.run('Commission'), 'recoverable')
            self.assertTrue(self.script.run('Restart'))
        self.script.device.emulator_stop.assert_not_called()

    def test_scheduled_interruption_completes_with_master_off_and_does_not_count_business_failure(self):
        self.settings(HandleError=False)
        self.data['Alas']['EmulatorManagement']['ScheduledEmulatorRestart'] = True
        self.write()
        self.script._forced_restart_pending = True
        self.script.device.emulator_start.return_value = True
        self.script.commission.side_effect = [RecoveryStopped(ConnectionResetError('计划关闭模拟器'), '预期断连'), None]
        self.legacy.run_tasks(self.script, ['Commission', 'Restart', 'Commission'])
        self.assertEqual(self.script.commission.call_count, 2)
        self.script.restart.assert_called_once()
        self.assertEqual(self.script.task_restart_record, {})
        self.script.config.task_delay.assert_not_called()

    def test_scheduled_marker_does_not_exempt_unrelated_script_error(self):
        self.settings(HandleError=False)
        self.script._forced_restart_pending = True
        self.script.commission.side_effect = AttributeError('真实脚本错误')
        with self.assertRaises(SystemExit):
            self.script.run('Commission')
        self.script.device.emulator_start.assert_not_called()

    def test_source_switch_is_rechecked_after_emulator_stop(self):
        for reason, name in (('adb_offline', 'AdbOfflineRestart'), ('game_stuck', 'GameStuckRestart')):
            with self.subTest(reason=reason):
                self.settings(AdbOfflineRestart=True, AdbOfflineThreshold=1, GameStuckRestart=True)
                self.script.consecutive_game_stuck = 3
                self.script.device.emulator_stop.side_effect = lambda: self.settings(**{name: False})
                self.assertFalse(self.script._try_restart_emulator(reason=reason))
                self.script.device.emulator_start.assert_not_called()

    def test_increased_threshold_during_backoff_prevents_stale_restart(self):
        self.settings(AdbOfflineThreshold=1)
        self.script.consecutive_adb_offline = 1
        self.legacy.sleep.side_effect = lambda _: self.settings(AdbOfflineThreshold=10)
        self.assertFalse(self.script._try_restart_emulator())
        self.script.device.emulator_stop.assert_not_called()

    def test_watchdog_records_source_before_io_breaks_and_does_not_bypass_new_game_setting(self):
        self.settings(WatchdogEnable=True, GameStuckThreshold=1, AdbOfflineThreshold=1)
        def stop():
            self.assertTrue(self.script._watchdog_recovery_pending)
            self.settings(GameStuckRestart=False)
            self.assertFalse(self.script._try_restart_emulator())
            return True
        with patch('module.device.platform.Platform') as platform:
            platform.return_value.emulator_stop.side_effect = stop
            self.script._watchdog_recover(61, task_name='Commission')
        self.script.device.emulator_stop.assert_not_called()

    def test_watchdog_interruption_keeps_recovering_after_threshold_is_raised(self):
        self.settings(GameStuckThreshold=5)
        self.script.consecutive_game_stuck = 3
        self.script._watchdog_recovery_pending = True
        self.assertFalse(self.script._try_restart_emulator())
        self.script.device.emulator_start.assert_not_called()
        self.assertFalse(self.script._try_restart_emulator())
        self.script.device.emulator_start.assert_called_once()

    def test_watchdog_scheduled_source_checks_switches_sensitive_task_and_stop_result(self):
        settings = self.data['Alas']['EmulatorManagement']
        with patch('module.device.platform.Platform') as platform:
            self.script._watchdog_recover(3601, reason='unknown', task_name='Commission')
            self.script._watchdog_recover(3601, reason='force_scheduled_restart', task_name='Commission')
            platform.assert_not_called()
            settings.update(ScheduledEmulatorRestart=True, ForceScheduledRestart=True)
            self.data['Commission'] = {'Scheduler': {'Sensitive': True}}
            self.write()
            self.script._watchdog_recover(3601, reason='force_scheduled_restart', task_name='Commission')
            platform.assert_not_called()
            self.data['Commission']['Scheduler']['Sensitive'] = False
            self.settings(HandleError=False)
            platform.return_value.emulator_stop.return_value = False
            self.script._watchdog_recover(3601, reason='force_scheduled_restart', task_name='Commission')
            self.assertFalse(self.script._forced_restart_pending)
            platform.return_value.emulator_stop.return_value = True
            self.script._watchdog_recover(3601, reason='force_scheduled_restart', task_name='Commission')
            self.assertTrue(self.script._forced_restart_pending)

    def test_game_start_exhaustion_uses_configured_attempts_and_observation_without_outer_cap(self):
        from module.handler.login import LoginHandler
        login = LoginHandler.__new__(LoginHandler)
        login.config = self.script.config
        login.device = self.script.device
        login.device.config = self.script.config
        login.device.app_is_running_bounded.return_value = False
        login.handle_app_login = Mock()
        self.data['RunParams']['Reboot']['Tries'] = 2
        self.write()
        with patch('module.handler.login.time.monotonic', side_effect=[0, 1000]):
            with self.assertRaises(GameStuckError):
                login.app_restart()
        self.assertEqual(login.device.app_start.call_count, 2)
        login.handle_app_login.assert_not_called()
        self.assertNotIn('_recovery_error', login.device.__dict__)

    def test_timeout_does_not_stack_another_operation_on_blocked_device(self):
        from module.handler.login import LoginHandler
        login = LoginHandler.__new__(LoginHandler)
        login.device = self.script.device
        finished = threading.Event()
        operation = Mock(side_effect=lambda: finished.wait(3))
        self.addCleanup(finished.set)
        with self.assertRaises(GameStuckError):
            login._call_with_restart_deadline(operation, timeout=0.01, operation_name='模拟阻塞')
        old = login.device.__dict__['_restart_operation_thread']
        with self.assertRaises(GameStuckError):
            login._call_with_restart_deadline(operation, timeout=0.01, operation_name='仍在阻塞')
        operation.assert_called_once()
        finished.set()
        old.join(2)
        completed = Mock(return_value=True)
        self.assertTrue(login._call_with_restart_deadline(completed, timeout=1, operation_name='完成后正常调用'))

    def test_unknown_page_preserves_one_local_recovery_then_returns_error_to_scheduler(self):
        from module.ui.ui import UI
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.settings(HandleError=enabled)
                self.script.device.app_stop.reset_mock()
                self.script.device.app_is_running.return_value = False
                ui = UI.__new__(UI)
                ui.config = self.script.config
                ui.device = self.script.device
                with (patch('module.ui.ui.Timer') as timer,
                      patch('module.handler.login.LoginHandler') as login):
                    timer.return_value.start.return_value.reached.return_value = True
                    login.return_value.device = self.script.device
                    with self.assertRaises(GamePageUnknownError if enabled else RecoveryStopped):
                        ui.ui_get_current_page()
                self.assertEqual(self.script.device.app_stop.call_count, int(enabled))

    def test_warmup_initial_start_is_preserved_but_failure_cannot_bypass_master(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.settings(HandleError=enabled)
                with patch('module.handler.login.LoginHandler') as login:
                    self.assertTrue(self.script._warmup_prestart(cold=False))
                    login.return_value.app_restart.side_effect = AttributeError('预热失败')
                    if enabled:
                        self.assertFalse(self.script._warmup_prestart(cold=False))
                        self.assertIsNotNone(self.script._pending_recovery)
                    else:
                        with self.assertRaises(RecoveryStopped):
                            self.script._warmup_prestart(cold=False)

    def test_initial_active_emulator_start_is_allowed_but_failure_requires_authorized_recovery(self):
        self.settings(HandleError=False, AdbOfflineRestart=False)
        with patch('module.device.platform.Platform') as platform:
            platform.return_value.emulator_start.return_value = True
            self.assertTrue(self.script._start_emulator_after_long_wait())
            platform.return_value.emulator_start.return_value = False
            with self.assertRaises(RecoveryStopped):
                self.script._start_emulator_after_long_wait()

    def test_watchdog_stop_failure_after_master_disable_stops_worker_instead_of_only_thread(self):
        self.settings(HandleError=False)
        self.data['Alas']['EmulatorManagement'].update(ScheduledEmulatorRestart=True, ForceScheduledRestart=True)
        self.write()
        with patch('module.device.platform.Platform') as platform:
            platform.return_value.emulator_stop.side_effect = RecoveryStopped(
                EmulatorNotRunningError('停止失败后禁止继续补救'), '异常处理关闭')
            with self.assertRaises(SystemExit):
                self.script._watchdog_recover(3601, reason='force_scheduled_restart', task_name='Commission')
        self.assertFalse(self.script._forced_restart_pending)
        platform.return_value.emulator_start.assert_not_called()

    def test_manual_restart_preserves_void_platform_contract_without_claiming_confirmed_success(self):
        from module.device.platform.platform_base import PlatformBase
        from module.mcp.device_worker import perform
        platform = PlatformBase.__new__(PlatformBase)
        platform.config = SimpleNamespace(EmulatorInfo_Emulator='SSH', EmulatorInfo_RemoteStartCommand='start',
                                         EmulatorInfo_RemoteStopCommand='stop')
        platform.run_remote_ssh_command = Mock()
        with (patch('module.config.config.AzurLaneConfig', return_value=self.script.config),
              patch('module.device.platform.Platform', return_value=platform)):
            text = perform('restart_emulator', 'isolated-recovery')['text']
        self.assertEqual([call.args[0] for call in platform.run_remote_ssh_command.call_args_list], ['stop', 'start'])
        self.assertIn('未返回完成确认', text)
        self.assertNotIn('Success', text)

    def test_stop_preserves_cached_image_and_log_without_fresh_capture_or_remote_analysis(self):
        import os
        import numpy as np
        current = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, current)
        log = self.root / 'source.log'
        log.write_text('原始故障日志\n', encoding='utf-8')
        self.script.config.Error_SaveError = True
        self.script.config.Error_LlmAnalysis = True
        self.script.device.screenshot_deque = [{'time': datetime(2026, 10, 23),
                                              'image': np.zeros((720, 1280, 3), dtype=np.uint8)}]
        del self.script.__dict__['save_error_log']
        self.settings(HandleError=False)
        with (patch('alas.logger.log_file', str(log)),
              patch('module.handler.sensitive_info.handle_sensitive_image', side_effect=lambda image: image),
              patch('module.handler.sensitive_info.handle_sensitive_logs', side_effect=lambda lines: lines),
              patch('module.llm.analyze_exception') as analyze):
            with self.assertRaises(SystemExit):
                self.script._stop_recovery(RecoveryStopped(GameStuckError('原始异常'), '等待人工处理'))
        saved = list((self.root / 'log/error/test').glob('*'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(list(saved[0].glob('*.png'))), 1)
        self.assertIn('原始故障日志', (saved[0] / 'log.txt').read_text(encoding='utf-8'))
        self.script.device.screenshot.assert_not_called()
        self.script.device.app_stop.assert_not_called()
        analyze.assert_not_called()

    def test_unreadable_settings_stop_instead_of_restarting_with_stale_configuration(self):
        self.path.write_text('{invalid', encoding='utf-8')
        with self.assertRaises(RecoveryStopped):
            self.script._try_restart_emulator()
        self.script.device.emulator_start.assert_not_called()

    def test_direct_backend_takeover_and_offline_signals_cannot_be_swallowed_by_local_handlers(self):
        self.settings(HandleError=False)
        for kind in (RequestHumanTakeover, EmulatorNotRunningError):
            with self.subTest(kind=kind.__name__):
                recover = Mock()
                @retry_backend(recover=recover, label='isolated')
                def read(device):
                    raise kind('直接上抛的设备故障')
                with self.assertRaises(RecoveryStopped):
                    read(Mock(config=self.script.config))
                recover.assert_not_called()

    def test_actual_worker_exit_preserves_parent_and_another_process(self):
        context = multiprocessing.get_context('spawn')
        done = context.Event()
        sibling = context.Process(target=done.wait, args=(30,))
        sibling.start()
        self.addCleanup(lambda: sibling.join(5))
        self.addCleanup(done.set)
        for background in (False, True):
            with self.subTest(background=background):
                scene = self.root / 'scene.txt'
                if scene.exists():
                    scene.unlink()
                queue = context.Queue()
                child = context.Process(target=worker_exit_probe, args=(str(self.root), background, queue))
                child.start()
                child.join(25)
                if child.is_alive():
                    child.terminate()
                    child.join(5)
                    self.fail('隔离 worker 没有退出')
                self.assertEqual(child.exitcode, 1)
                self.assertTrue(scene.exists())
                self.assertFalse((self.root / 'forbidden.txt').exists())
                self.assertTrue(sibling.is_alive())
                if not background:
                    from module.runtime.worker_events import ExitEvent
                    self.assertIsInstance(queue.get(timeout=5), ExitEvent)
                queue.close()
                queue.join_thread()


    def test_backend_rechecks_live_switch_before_next_attempt(self):
        def fail_once():
            self.settings(HandleError=False)
            raise ConnectionResetError('运行中关闭')
        device = Mock(config=self.script.config)
        device.operation.side_effect = fail_once
        recover = Mock()
        @retry_backend(recover=recover, label='test')
        def read(target):
            return target.operation()
        with self.assertRaises(RecoveryStopped):
            read(device)
        recover.assert_not_called()
        device.operation.assert_called_once_with()

    def test_daily_summary_can_be_enabled_and_recreated_without_task_reload(self):
        del self.script.__dict__['_sync_background_services']
        self.script._start_daily_summary_scheduler = Mock()
        # 快速连续保存可能具有相同文件时间，不能永久沿用关闭状态。
        with patch('alas.os.stat', return_value=SimpleNamespace(st_mtime_ns=1)):
            self.script._sync_background_services()
            self.script._start_daily_summary_scheduler.assert_not_called()
            self.data['Alas']['DailySummary']['Enable'] = True
            self.write()
            self.script._sync_background_services()
            self.script._sync_background_services()
        self.assertEqual(self.script._start_daily_summary_scheduler.call_count, 2)
        self.script.config.load.assert_not_called()
        self.script.config.bind.assert_not_called()

    def test_live_watchdog_loop_rereads_master_before_each_detection(self):
        self.script._watchdog_active = True
        self.script._watchdog_task_start = 1
        self.script._watchdog_task_name = 'Commission'
        self.script._watchdog_recover = Mock()
        checks = iter((False, True, False, None))
        def wait(interval):
            enabled = next(checks)
            if enabled is None:
                return True
            self.settings(WatchdogEnable=enabled)
            return False
        self.script._watchdog_stop = Mock()
        self.script._watchdog_stop.wait.side_effect = wait
        with patch('alas.time.monotonic', return_value=100):
            self.script._watchdog_loop()
        self.script._watchdog_recover.assert_called_once_with(99, reason='task_timeout', task_name='Commission')
        self.script.config.load.assert_not_called()

    def test_daily_summary_real_thread_is_recreated_after_disable(self):
        del self.script.__dict__['_stop_daily_summary_scheduler']
        del self.script.__dict__['_sync_background_services']
        self.script._get_daily_summary_service = Mock()
        self.script._check_daily_summary = Mock()
        self.script._daily_summary_interval = Mock(return_value=0.01)
        self.data['Alas']['DailySummary']['Enable'] = True
        self.write()
        self.script._sync_background_services()
        old = self.script._daily_summary_thread
        self.addCleanup(self.script._stop_daily_summary_scheduler)
        self.assertTrue(old.is_alive())
        self.data['Alas']['DailySummary']['Enable'] = False
        self.write()
        old.join(2)
        self.assertFalse(old.is_alive())
        self.data['Alas']['DailySummary']['Enable'] = True
        self.write()
        self.script._sync_background_services()
        self.assertIsNot(old, self.script._daily_summary_thread)
        self.assertTrue(self.script._daily_summary_thread.is_alive())

    def test_active_game_start_and_stop_are_preserved_with_recovery_disabled(self):
        from module.device.device import Device
        from module.device.app_control import AppControl
        device = Device.__new__(Device)
        device.config = SimpleNamespace(Error_HandleError=False, Emulator_GameSettings=False, config_name='isolated')
        device.stuck_record_clear = Mock()
        device.click_record_clear = Mock()
        with (patch.object(AppControl, 'app_start') as start,
              patch.object(AppControl, 'app_stop') as stop,
              patch('module.api.account_service.restore_worker')):
            device.app_start()
            device.app_stop()
        start.assert_called_once_with()
        stop.assert_called_once_with()

    def test_manual_login_start_is_allowed_but_failed_attempt_is_not_retried(self):
        from module.handler.login import LoginHandler
        login = LoginHandler.__new__(LoginHandler)
        login.config = self.script.config
        login.device = Mock()
        login.handle_app_login = Mock()
        self.settings(HandleError=False)
        login.device.app_is_running_bounded.return_value = True
        login.app_restart()
        login.device.app_stop.assert_called_once_with()
        login.device.app_start.assert_called_once_with()
        login.device.reset_mock()
        login.device.app_is_running_bounded.return_value = False
        with self.assertRaises(RecoveryStopped):
            login.app_restart()
        login.device.app_stop.assert_called_once_with()
        login.device.app_start.assert_called_once_with()

    def test_manual_start_failure_enters_revocable_recovery_scope_and_cleans_it(self):
        from module.config.recovery import check_pending_recovery
        from module.handler.login import LoginHandler
        login = LoginHandler.__new__(LoginHandler)
        login.config = self.script.config
        login.device = self.script.device
        login.handle_app_login = Mock()
        self.script.device.config = self.script.config
        self.script.device.app_is_running_bounded.side_effect = [False, True]
        starts = []

        def start():
            check_pending_recovery(self.script.device)
            starts.append(True)

        def wait(seconds):
            if '_recovery_error' in self.script.device.__dict__:
                self.settings(HandleError=False)

        self.script.device.app_start.side_effect = start
        self.script.device.sleep.side_effect = wait
        with self.assertRaises(RecoveryStopped):
            login.app_restart()
        self.assertEqual(starts, [True])
        self.script.device.app_is_running_bounded.assert_called_once_with()
        login.handle_app_login.assert_not_called()
        self.assertNotIn('_recovery_error', self.script.device.__dict__)

    def test_platform_internal_retry_cannot_start_after_stop_failure_when_disabled(self):
        from module.device.platform.platform_windows import PlatformWindows
        from module.device.platform.platform_mac import PlatformMac
        self.settings(HandleError=False)
        for method in (PlatformWindows.emulator_stop.__wrapped__, PlatformMac.emulator_stop):
            platform = Mock(config=self.script.config)
            platform._emulator_function_wrapper.return_value = False
            with self.assertRaises(RecoveryStopped):
                method(platform)
            self.assertEqual(platform._emulator_function_wrapper.call_count, 1)
            platform._emulator_function_wrapper.assert_called_once_with(platform._emulator_stop)

    def test_adb_service_restart_honors_latest_own_switch(self):
        from module.device.connection import Connection
        self.data['Alas']['Emulator'] = {'AdbRestart': False}
        self.write()
        client = Mock(config=self.script.config)
        self.assertFalse(Connection.adb_restart(client))
        client.adb_client.server_kill.assert_not_called()

    def test_disabling_during_recovery_stops_before_next_device_action_and_restores_scope(self):
        from module.config.recovery import recovery_scope
        from module.device.device import Device
        from module.device.app_control import AppControl
        device = Device.__new__(Device)
        device.config = self.script.config
        device.stuck_record_clear = Mock()
        device.click_record_clear = Mock()
        with patch.object(AppControl, 'app_stop') as stop:
            with self.assertRaises(RecoveryStopped):
                with recovery_scope(self.script.config, device, GameStuckError('已进入恢复')):
                    self.settings(HandleError=False)
                    device.app_stop()
            stop.assert_not_called()
        self.assertNotIn('_recovery_error', device.__dict__)

    def test_settings_observer_stops_pending_recovery_even_without_timeout_monitoring(self):
        self.settings(HandleError=False, WatchdogEnable=False)
        self.script._pending_recovery = ('Commission', GameNotRunningError('等待恢复'))
        self.script._watchdog_active = False
        self.script._watchdog_stop = Mock()
        self.script._watchdog_stop.wait.return_value = False
        with self.assertRaises(SystemExit):
            self.script._watchdog_loop()
        self.script.device.emulator_stop.assert_not_called()
        self.script.config.task_call.assert_not_called()

    def test_game_specific_fog_recovery_cannot_bypass_master(self):
        from module.os.map import OSMap
        owner = Mock(config=self.script.config, device=self.script.device)
        owner.appear.return_value = True
        self.settings(HandleError=False)
        with self.assertRaises(RecoveryStopped):
            OSMap.handle_fog_block(owner)
        self.script.device.app_stop.assert_not_called()
        self.script.device.app_start.assert_not_called()

    def test_local_ship_change_failure_cannot_mutate_or_reschedule_when_disabled(self):
        from module.campaign.fleet_selection import FleetSelectionMixin
        owner = Mock(config=self.script.config, change_vanguard_equip=False)
        owner.vanguard_change_execute.side_effect = RequestHumanTakeover('换船失败')
        self.settings(HandleError=False)
        before = self.path.read_bytes()
        with self.assertRaises(RecoveryStopped):
            FleetSelectionMixin._change_ship(owner, 'vanguard')
        owner.config.task_stop.assert_not_called()
        self.assertEqual(before, self.path.read_bytes())

    def test_sp_local_exception_cannot_delay_fault_task_when_disabled(self):
        from module.event.campaign_sp import CampaignSP
        from module.event.base import EventBase
        owner = CampaignSP.__new__(CampaignSP)
        owner.config = self.script.config
        self.settings(HandleError=False)
        with (patch('module.event.campaign_sp.os.path.exists', return_value=True),
              patch.object(EventBase, 'run', side_effect=RequestHumanTakeover('未知进入错误'))):
            with self.assertRaises(RecoveryStopped):
                owner.run()
        self.script.config.task_delay.assert_not_called()

    def test_app_status_does_not_turn_device_fault_into_game_not_running(self):
        from module.device.app_control import AppControl
        for error in (EmulatorNotRunningError('离线'), ConnectionResetError('ADB 断开'), RequestHumanTakeover('未授权')):
            target = Mock(config=self.script.config)
            target.adb_shell.side_effect = error
            with self.assertRaises(type(error)) as caught:
                AppControl.app_is_running_bounded(target)
            self.assertIs(caught.exception, error)

    def test_mcp_manual_restart_works_offline_with_all_error_switches_disabled(self):
        from module.mcp.device_worker import perform
        self.settings(HandleError=False, AdbOfflineRestart=False, GameStuckRestart=False)
        with (patch('module.config.config.AzurLaneConfig', return_value=self.script.config),
              patch('module.device.device.Device') as device_class,
              patch('module.device.platform.Platform') as platform):
            platform.return_value.emulator_stop.return_value = True
            platform.return_value.emulator_start.return_value = True
            self.assertIn('Success', perform('restart_emulator', 'isolated-test')['text'])
        device_class.assert_not_called()
        platform.assert_called_once_with(self.script.config, connect=False)

    def test_mcp_manual_restart_does_not_report_false_platform_result_as_success(self):
        from module.mcp.device_worker import perform
        with (patch('module.config.config.AzurLaneConfig', return_value=self.script.config),
              patch('module.device.platform.Platform') as platform):
            platform.return_value.emulator_stop.return_value = False
            with self.assertRaises(RuntimeError):
                perform('restart_emulator', 'isolated-test')
        platform.return_value.emulator_start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
