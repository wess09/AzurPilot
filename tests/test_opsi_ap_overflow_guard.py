"""防止行动力溢出任务与大世界任务共享调度时的运行时隔离回归。"""

import unittest
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock, patch

from module.campaign.os_run import OSCampaignRun
from module.config.config import AzurLaneConfig
from module.config.time_source import now as current_time
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow


def make_config(tasks):
    """构造只装配调度必需字段的配置对象，不读写用户配置。

    Args:
        tasks (dict[str, tuple[bool, timedelta]]): 任务名到 (是否启用, 距现在的偏移)。

    Returns:
        AzurLaneConfig: 可直接计算任务队列的配置对象。
    """
    config = AzurLaneConfig.__new__(AzurLaneConfig)
    config.data = {
        name: {
            'Scheduler': {
                'Command': name,
                'Enable': enable,
                'NextRun': current_time() + offset,
            }
        }
        for name, (enable, offset) in tasks.items()
    }
    return config


class TestRuntimeTaskExclusion(unittest.TestCase):
    """临时排除只影响本次进程的调度队列。"""

    def setUp(self):
        self.config = make_config({
            'Main': (True, timedelta(minutes=-10)),
            'Commission': (True, timedelta(minutes=-5)),
            'Research': (True, timedelta(minutes=-1)),
        })
        hoarding = patch.object(AzurLaneConfig, 'is_hoarding_task', False)
        hoarding.start()
        self.addCleanup(hoarding.stop)

    def commands(self):
        self.config.get_next_task()
        return [func.command for func in self.config.pending_task]

    def test_excluded_task_leaves_queue_then_returns(self):
        self.assertIn('Commission', self.commands())
        self.config.exclude_task_runtime('Commission')
        self.assertTrue(self.config.is_task_excluded_runtime('Commission'))
        commands = self.commands()
        self.assertNotIn('Commission', commands)
        self.assertIn('Main', commands)
        self.assertIn('Research', commands)
        self.config.resume_task_runtime('Commission')
        self.assertFalse(self.config.is_task_excluded_runtime('Commission'))
        self.assertIn('Commission', self.commands())

    def test_excluding_every_task_leaves_no_dispatchable_task(self):
        for name in ('Main', 'Commission', 'Research'):
            self.config.exclude_task_runtime(name)

        self.config.get_next_task()

        self.assertEqual(self.config.pending_task, [])
        self.assertEqual(self.config.waiting_task, [])

    def test_excluded_waiting_task_is_not_scheduled(self):
        config = make_config({
            'Main': (True, timedelta(minutes=-10)),
            'Research': (True, timedelta(hours=2)),
        })
        config.exclude_task_runtime('Research')

        config.get_next_task()

        self.assertEqual([func.command for func in config.pending_task], ['Main'])
        self.assertEqual(config.waiting_task, [])

    def test_repeated_exclude_and_resume(self):
        self.config.exclude_task_runtime('Commission')
        self.config.exclude_task_runtime('Commission')
        self.config.resume_task_runtime('Commission')
        self.assertFalse(self.config.is_task_excluded_runtime('Commission'))
        self.config.resume_task_runtime('Commission')
        self.assertFalse(self.config.is_task_excluded_runtime('Commission'))

    def test_exclusion_does_not_touch_saved_settings(self):
        self.config.cross_set = Mock()
        self.config.update = Mock()
        self.config.exclude_task_runtime('Commission')
        self.config.resume_task_runtime('Commission')
        self.config.cross_set.assert_not_called()
        self.assertTrue(self.config.data['Commission']['Scheduler']['Enable'])
        self.assertFalse(self.config.is_task_excluded_runtime('Main'))

    def test_exclusion_without_initialized_state(self):
        config = AzurLaneConfig.__new__(AzurLaneConfig)
        self.assertFalse(config.is_task_excluded_runtime('Main'))
        config.exclude_task_runtime('Main')
        self.assertTrue(config.is_task_excluded_runtime('Main'))
        config.resume_task_runtime('Main')
        self.assertFalse(config.is_task_excluded_runtime('Main'))


class TestApOverflowGuard(unittest.TestCase):
    """运行大世界任务期间不改写防溢出任务的持久化开关。"""

    def make_runner(self, enabled_states):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = Mock()
        runner.config.is_task_enabled.side_effect = list(enabled_states)
        runner.campaign = Mock()
        runner.load_campaign = Mock(return_value=runner.campaign)
        return runner

    def test_guard_only_uses_runtime_exclusion(self):
        runner = self.make_runner([True, True])
        result = runner._run_opsi_task_with_ap_overflow_guard(lambda campaign: 'done')
        self.assertEqual(result, 'done')
        runner.config.exclude_task_runtime.assert_called_once_with('OpsiPreventActionPointOverflow')
        runner.config.resume_task_runtime.assert_called_once_with('OpsiPreventActionPointOverflow')
        runner.config.cross_set.assert_not_called()
        runner.campaign.update_prevent_action_point_overflow_schedule.assert_called_once_with(enable=None)

    def test_guard_keeps_user_disable_during_run(self):
        runner = self.make_runner([True, False])
        runner._run_opsi_task_with_ap_overflow_guard(lambda campaign: None)
        runner.campaign.update_prevent_action_point_overflow_schedule.assert_not_called()
        runner.config.load.assert_called_once_with()
        runner.config.cross_set.assert_not_called()
        runner.config.resume_task_runtime.assert_called_once_with('OpsiPreventActionPointOverflow')

    def test_guard_restores_dispatch_on_failure(self):
        runner = self.make_runner([True, True])

        def runner_func(campaign):
            raise RuntimeError('游戏失败')

        with self.assertRaisesRegex(RuntimeError, '游戏失败'):
            runner._run_opsi_task_with_ap_overflow_guard(runner_func)
        runner.config.resume_task_runtime.assert_called_once_with('OpsiPreventActionPointOverflow')
        runner.config.cross_set.assert_not_called()

    def test_guard_skips_schedule_update_when_campaign_load_fails(self):
        runner = self.make_runner([True])
        runner.load_campaign = Mock(side_effect=RuntimeError('加载失败'))

        with self.assertRaisesRegex(RuntimeError, '加载失败'):
            runner._run_opsi_task_with_ap_overflow_guard(lambda campaign: None)

        runner.config.resume_task_runtime.assert_called_once_with('OpsiPreventActionPointOverflow')
        runner.campaign.update_prevent_action_point_overflow_schedule.assert_not_called()
        runner.config.cross_set.assert_not_called()

    def test_guard_survives_schedule_update_failure(self):
        runner = self.make_runner([True, True])
        runner.campaign.update_prevent_action_point_overflow_schedule.side_effect = RuntimeError('写配置失败')

        self.assertEqual(runner._run_opsi_task_with_ap_overflow_guard(lambda campaign: 7), 7)

        runner.config.resume_task_runtime.assert_called_once_with('OpsiPreventActionPointOverflow')
        runner.config.cross_set.assert_not_called()

    def test_guard_skips_when_task_disabled(self):
        runner = self.make_runner([False])
        self.assertEqual(runner._run_opsi_task_with_ap_overflow_guard(lambda campaign: 1), 1)
        runner.config.exclude_task_runtime.assert_not_called()
        runner.config.resume_task_runtime.assert_not_called()
        runner.campaign.update_prevent_action_point_overflow_schedule.assert_not_called()


class TestUpdateScheduleEnableOptional(unittest.TestCase):
    """更新排期时可以不改动用户开关。"""

    def make_runner(self):
        runner = OpsiPreventActionPointOverflow.__new__(OpsiPreventActionPointOverflow)
        runner.config = Mock()
        runner.config.multi_set.return_value = nullcontext()
        runner._get_prevent_action_point_overflow_thresholds = Mock(return_value=(200, 100))
        runner._set_prevent_action_point_overflow_enabled = Mock()
        return runner

    def test_none_keeps_current_switch(self):
        runner = self.make_runner()
        runner.update_prevent_action_point_overflow_schedule(current_ap=120, enable=None)
        runner._set_prevent_action_point_overflow_enabled.assert_not_called()
        runner.config.task_delay.assert_called_once()

    def test_bool_still_updates_switch(self):
        runner = self.make_runner()
        runner.update_prevent_action_point_overflow_schedule(current_ap=120, enable=True)
        runner._set_prevent_action_point_overflow_enabled.assert_called_once_with(True)
        runner.config.task_delay.assert_called_once()


if __name__ == '__main__':
    unittest.main()
