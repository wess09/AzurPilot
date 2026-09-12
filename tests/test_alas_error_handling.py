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
        script.__dict__['config'] = Mock()
        script.config.cross_get.return_value = False
        # 上游渠道服悬浮球检查需要的字段：空配置与最小 device 桩
        script.config.data = {}
        script.__dict__['device'] = Mock()
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
