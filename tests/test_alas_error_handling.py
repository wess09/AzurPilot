import logging
import unittest
from unittest.mock import Mock, patch

from alas import AzurLaneAutoScript
from module.exception import GameNotRunningError
from module.logger import error_context


class TestErrorContext(unittest.TestCase):
    def test_can_log_exception_summary_without_traceback(self):
        error = GameNotRunningError('Game not running')

        with patch('module.logger.logger.log') as log:
            error_context(
                title='游戏进程未运行',
                reason='任务执行前未检测到碧蓝航线游戏进程。',
                impact='当前任务跳过。',
                action='自动重启游戏。',
                exc=error,
                level=logging.WARNING,
                with_traceback=False,
            )

        self.assertFalse(log.call_args.kwargs['exc_info'])
        self.assertIn('异常：GameNotRunningError: Game not running', log.call_args.args[1])


class TestGameNotRunningErrorHandling(unittest.TestCase):
    def test_schedules_restart_without_requesting_traceback(self):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.config_name = 'test'
        # 跳过与本测试无关的启动浮窗处理，直接验证任务异常边界。
        script._channel_float_done = True
        script.__dict__['config'] = Mock()
        script.config.cross_get.return_value = False
        script.config.Error_LowPushMode = False
        script.config.Error_GameStuckRestart = True
        script.config.Error_GameStuckThreshold = 3
        script.consecutive_game_not_running = 0
        error = GameNotRunningError('Game not running')
        script.__dict__['commission'] = Mock(side_effect=error)

        with (
            patch('alas.logger.error_context') as error_context_mock,
            patch('alas.handle_notify'),
            patch('alas.notify_webui'),
        ):
            result = script.run('commission', skip_first_screenshot=True)

        self.assertEqual('recoverable', result)
        script.config.task_call.assert_called_once_with('Restart')
        error_context_mock.assert_called_once_with(
            title='游戏进程未运行',
            reason='任务执行前未检测到碧蓝航线游戏进程。',
            impact='当前任务跳过，调度器将自动安排 Restart 任务。',
            action='通常无需处理；若反复发生，请检查游戏包名、模拟器状态和登录流程。',
            exc=error,
            level=30,
            with_traceback=False,
        )


class TestLowPushMode(unittest.TestCase):
    def build_script(self, low_push_mode):
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.config_name = 'test'
        script.__dict__['config'] = Mock()
        script.config.cross_get.return_value = False
        script.config.Error_LowPushMode = low_push_mode
        script.config.Error_GameStuckRestart = True
        script.config.Error_GameStuckThreshold = 3
        script.consecutive_game_not_running = 0
        return script

    def test_recoverable_error_is_pushed_when_mode_disabled(self):
        script = self.build_script(low_push_mode=False)

        with (
            patch('alas.handle_notify') as handle_notify_mock,
            patch('alas.notify_webui') as notify_webui_mock,
        ):
            pushed = script._notify_recoverable(
                title='title', content='content',
                webui_title='webui title', webui_content='webui content',
            )

        self.assertTrue(pushed)
        handle_notify_mock.assert_called_once_with(
            script.config.Error_OnePushConfig, title='title', content='content',
        )
        notify_webui_mock.assert_called_once_with(
            'test', title='webui title', content='webui content',
        )

    def test_recoverable_error_is_skipped_when_mode_enabled(self):
        script = self.build_script(low_push_mode=True)

        with (
            patch('alas.handle_notify') as handle_notify_mock,
            patch('alas.notify_webui') as notify_webui_mock,
        ):
            pushed = script._notify_recoverable(
                title='title', content='content',
                webui_title='webui title', webui_content='webui content',
            )

        self.assertFalse(pushed)
        handle_notify_mock.assert_not_called()
        notify_webui_mock.assert_not_called()

    def test_game_not_running_still_recovers_in_low_push_mode(self):
        """低推送量模式只减少推送，自动重启恢复不受影响。"""
        script = self.build_script(low_push_mode=True)
        script._channel_float_done = True
        script.__dict__['commission'] = Mock(
            side_effect=GameNotRunningError('Game not running')
        )

        with (
            patch('alas.logger.error_context'),
            patch('alas.handle_notify') as handle_notify_mock,
            patch('alas.notify_webui') as notify_webui_mock,
        ):
            result = script.run('commission', skip_first_screenshot=True)

        self.assertEqual('recoverable', result)
        script.config.task_call.assert_called_once_with('Restart')
        handle_notify_mock.assert_not_called()
        notify_webui_mock.assert_not_called()


class TestLowPushModeConfigWiring(unittest.TestCase):
    """用真实配置对象验证键名。

    上面的用例都用 Mock 假配置，键名写错也会静默返回 Mock 属性；
    这一组走真实的 config_update + bind，确保配置项真的叫 Error_LowPushMode。
    """

    def make_config(self, **error):
        from module.config.config import AzurLaneConfig

        config = AzurLaneConfig('template')
        config.auto_update = False
        config.data = config.config_update({'Alas': {'Error': error}})
        config.bind('Alas')
        return config

    def test_default_is_disabled(self):
        self.assertFalse(self.make_config().Error_LowPushMode)

    def test_reads_value_from_real_config(self):
        self.assertTrue(self.make_config(LowPushMode=True).Error_LowPushMode)


class TestRestartBootstrap(unittest.TestCase):
    def test_restart_skips_pre_task_screenshot(self):
        """Restart 必须能在游戏未运行、虚拟屏尚无首帧时先执行启动逻辑。"""
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.config_name = 'test'
        script._channel_float_done = True
        script.__dict__['device'] = Mock()
        script.__dict__['restart'] = Mock()

        result = script.run('restart')

        self.assertTrue(result)
        script.device.screenshot.assert_not_called()
        script.restart.assert_called_once_with()
        self.assertFalse(script._channel_float_done)
