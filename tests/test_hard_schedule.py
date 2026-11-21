"""困难图每日调度的时间边界、旧配置兼容性与任务奖励补领。"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from module.config.config import AzurLaneConfig, TaskEnd, name_to_function
from module.config.utils import read_file
from module.hard.hard import CampaignHard


class HardScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 12)
        self.offset = timedelta()
        for target, value in (
            ('module.hard.hard.current_time', lambda: self.now),
            ('module.config.config.current_time', lambda: self.now),
            ('module.config.utils.current_time', lambda: self.now),
            ('module.hard.hard.server_time_offset', lambda: self.offset),
            ('module.config.utils.server_time_offset', lambda: self.offset),
        ):
            self.enterContext(patch(target, side_effect=value))
        self.enterContext(patch('module.hard.hard.logger'))
        self.ocr = self.enterContext(patch('module.hard.hard.OCR_HARD_REMAIN'))
        self.reward = self.enterContext(patch('module.hard.hard.Reward'))

    def runner(self, **hard):
        # 每次 runner() 都换一份 Reward 实例记录，避免同一个 Mock 跨多次调用累积。
        self.reward.reset_mock()
        self.reward.return_value = Mock()
        config = AzurLaneConfig('template')
        config.data = config.config_update({'Hard': {'Hard': hard}})
        config.bind('Hard')
        config.task = name_to_function('Hard')
        config.task_call = Mock()
        runner = object.__new__(CampaignHard)
        runner.config = config
        runner.device = Mock()
        runner.campaign = Mock()
        runner.load_campaign = Mock()
        runner.ui_goto_main = Mock()
        runner.reward_mock = self.reward.return_value
        # 模拟每次出击用时，仍走真实 task_delay 的时区计算与配置写入。
        runner.campaign.run.side_effect = lambda: setattr(self, 'now', self.now + timedelta(seconds=1))
        return runner

    def test_config_default_and_saved_choice(self):
        runner = self.runner()
        self.assertFalse(runner.config.Hard_RunAt18)
        definition = read_file('module/config/argument/args.json')['Hard']['Hard']['RunAt18']
        self.assertEqual(definition, {'type': 'checkbox', 'value': False})
        self.assertFalse(read_file('config/template.json')['Hard']['Hard']['RunAt18'])
        runner = self.runner(RunAt18=True)
        runner.config.data = runner.config.config_update(runner.config.data)
        runner.config.bind('Hard')
        self.assertTrue(runner.config.Hard_RunAt18)
        for lang in ('zh-CN', 'en-US', 'ja-JP', 'zh-TW'):
            translation = read_file(f'module/config/i18n/{lang}.json')['Hard']['RunAt18']
            self.assertTrue(all(value and not value.startswith('Hard.RunAt18.') for value in translation.values()))

    def test_before_18_defers_without_game_access(self):
        for server_now in (datetime(2026, 10, 22), datetime(2026, 10, 22, 17, 59, 59)):
            for hours in (0, -1, 16):
                with self.subTest(server_now=server_now, offset=hours):
                    self.offset = timedelta(hours=hours)
                    self.now = server_now + self.offset
                    runner = self.runner(RunAt18=True)
                    with self.assertRaises(TaskEnd):
                        runner.run()
                    self.assertEqual(runner.config.modified['Hard.Scheduler.NextRun'],
                                     server_now.replace(hour=18, minute=0, second=0) + self.offset)
                    runner.load_campaign.assert_not_called()
                    self.assertEqual(runner.device.mock_calls, [])
                    self.assertEqual(runner.campaign.mock_calls, [])
                    runner.config.task_call.assert_not_called()
                    runner.ui_goto_main.assert_not_called()
                    self.reward.assert_not_called()

    def test_at_or_after_18_runs_and_schedules_next_evening(self):
        for hour in (18, 23):
            for hours in (0, -1, 16):
                with self.subTest(hour=hour, offset=hours):
                    self.offset = timedelta(hours=hours)
                    self.now = datetime(2026, 10, 22, hour) + self.offset
                    self.ocr.ocr.return_value = 3
                    runner = self.runner(RunAt18=True)
                    runner.run()
                    self.assertEqual(runner.campaign.run.call_count, 3)
                    runner.campaign.ensure_auto_search_exit.assert_called_once_with()
                    self.assertEqual(runner.config.modified['Hard.Scheduler.NextRun'],
                                     datetime(2026, 10, 23, 18) + self.offset)
                    runner.config.task_call.assert_called_once_with('Reward', force_call=False)
                    # 18 点运行打完困难图后原地补领一次任务奖励
                    runner.ui_goto_main.assert_called_once_with()
                    self.reward.assert_called_once_with(runner.config, runner.device)
                    runner.reward_mock.reward_mission.assert_called_once_with(daily=True, weekly=False)

    def test_claim_mission_reward_happens_after_battles(self):
        self.now = datetime(2026, 10, 22, 18, 30)
        self.ocr.ocr.return_value = 1
        runner = self.runner(RunAt18=True)
        order = []
        runner.campaign.ensure_auto_search_exit.side_effect = lambda: order.append('exit_auto_search')
        runner.ui_goto_main.side_effect = lambda: order.append('claim_mission')
        runner.run()
        self.assertEqual(order, ['exit_auto_search', 'claim_mission'])
        runner.reward_mock.reward_mission.assert_called_once_with(daily=True, weekly=False)

    def test_claim_mission_reward_follows_reward_options(self):
        self.now = datetime(2026, 10, 22, 18, 30)
        self.ocr.ocr.return_value = 1
        runner = self.runner(RunAt18=True)
        # 任务 Reward 的 Reward 组：data[<Task>][<Group>][<Argument>]
        runner.config.data['Reward']['Reward']['CollectMission'] = False
        runner.config.data['Reward']['Reward']['CollectWeeklyMission'] = True
        runner.run()
        runner.reward_mock.reward_mission.assert_called_once_with(daily=False, weekly=True)

    def test_claim_mission_reward_skipped_when_reward_options_disabled(self):
        self.now = datetime(2026, 10, 22, 18, 30)
        self.ocr.ocr.return_value = 1
        runner = self.runner(RunAt18=True)
        runner.config.data['Reward']['Reward']['CollectMission'] = False
        runner.config.data['Reward']['Reward']['CollectWeeklyMission'] = False
        runner.run()
        runner.ui_goto_main.assert_not_called()
        self.reward.assert_not_called()

    def test_default_still_runs_before_18_and_schedules_midnight(self):
        self.ocr.ocr.return_value = 3
        runner = self.runner()
        runner.run()
        self.assertEqual(runner.campaign.run.call_count, 3)
        self.assertEqual(runner.config.modified['Hard.Scheduler.NextRun'], datetime(2026, 10, 23))
        runner.config.task_call.assert_called_once_with('Reward', force_call=False)
        # 零点调度沿用原有行为：由 Reward 任务领取，困难图自己不再额外领取
        runner.ui_goto_main.assert_not_called()
        self.reward.assert_not_called()

    def test_no_remaining_attempts_still_schedules_next_evening(self):
        self.now = datetime(2026, 10, 22, 18, 1)
        self.ocr.ocr.return_value = 0
        runner = self.runner(RunAt18=True)
        runner.run()
        runner.campaign.run.assert_not_called()
        self.assertEqual(runner.config.modified['Hard.Scheduler.NextRun'], datetime(2026, 10, 23, 18))
        # 次数已用完（例如手动打完）时仍然补领，避免当天奖励没人领
        runner.ui_goto_main.assert_called_once_with()
        runner.reward_mock.reward_mission.assert_called_once_with(daily=True, weekly=False)


if __name__ == '__main__':
    unittest.main()
