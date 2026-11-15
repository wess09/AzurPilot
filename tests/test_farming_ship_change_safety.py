"""无候选舰船时遵循推迟开关，换船与装备交接异常仍须停止任务。"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from module.campaign.gems_farming import GemsEmotion, GemsFarming
from module.campaign.run import CampaignRun
from module.config.config import TaskEnd
from module.config.deep import deep_set
from module.exception import (
    CampaignEnd, EmulatorNotRunningError, GameStuckError, GameTooManyClickError, HardNotSatisfied, RequestHumanTakeover,
)
from tests.test_farming_combat_config import make_config
from tests.test_fleet_selection import TASKS, runner


class ShipChangeSafetyTests(unittest.TestCase):
    def test_hard_normal_hard_roundtrip_restores_all_navigation_methods(self):
        for task in TASKS:
            instance = runner(task)
            methods = ('_fleet_detail_enter', '_ship_detail_enter', '_fleet_back')
            normal = {method: getattr(instance, method).__func__ for method in methods}
            for mode in ('hard', 'normal', 'hard', 'normal'):
                instance.campaign.config.Campaign_Mode = mode
                instance.hard_mode_override()
                self.assertEqual(instance.hard_mode, mode == 'hard')
                for method in methods:
                    if mode == 'normal':
                        self.assertIs(getattr(instance, method).__func__, normal[method])
                    else:
                        self.assertIs(getattr(instance, method).__func__, getattr(instance, method + '_hard').__func__)

    def test_dock_tip_is_handled_before_waiting_for_confirmed_dock(self):
        for task in TASKS:
            instance = runner(task)
            instance.page_fleet_check_button = object()
            instance.loop = Mock(return_value=iter(range(3)))
            instance.appear = Mock(side_effect=[False, False, True])
            instance.handle_game_tips = Mock(return_value=True)
            self.assertTrue(instance.dock_enter('slot'))
            instance.handle_game_tips.assert_called_once_with()

    def test_dock_timeout_is_not_success(self):
        for task in TASKS:
            instance = runner(task)
            instance.page_fleet_check_button = object()
            instance.loop = Mock(return_value=iter(range(2)))
            instance.appear = Mock(return_value=False)
            instance.handle_game_tips = Mock(return_value=False)
            self.assertFalse(instance.dock_enter('slot'))

    def test_failed_entry_cannot_claim_ship_was_changed(self):
        for task in TASKS:
            for position in ('flagship', 'vanguard'):
                for hard, entry_results in ((False, [False]), (True, [False]), (True, [True, False])):
                    with self.subTest(task=task.__name__, position=position, hard=hard, entries=entry_results):
                        instance = runner(task)
                        instance.campaign.config.Campaign_Mode = 'hard' if hard else 'normal'
                        instance.hard_mode_override()
                        instance.dock_enter = Mock(side_effect=entry_results)
                        instance.ship_down_hard = Mock()
                        with self.assertRaises(RequestHumanTakeover):
                            getattr(instance, position + '_change_execute')()

    def test_equipment_or_selection_failure_disables_task_without_retry(self):
        for task in TASKS:
            for position in ('flagship', 'vanguard'):
                for failed_step in ('clear_all_equip', position + '_change_execute', 'apply_equip_code'):
                    with self.subTest(task=task.__name__, position=position, failed=failed_step):
                        instance = runner(task, GemsFarming_ChangeFlagship='ship_equip', GemsFarming_ChangeVanguard='ship_equip',
                                          GemsFarming_DelayTaskIFNoFlagship=False)
                        instance.hard_mode_override()
                        instance.config.Scheduler_Enable = True
                        instance.config.task_stop = Mock(side_effect=TaskEnd)
                        events = Mock()
                        methods = ('_fleet_detail_enter', '_ship_detail_enter', 'clear_all_equip',
                                   '_fleet_back', position + '_change_execute', 'apply_equip_code')
                        for method in methods:
                            setattr(instance, method, getattr(events, method))
                        getattr(events, failed_step).side_effect = RequestHumanTakeover('测试失败')
                        instance.last_code = '旧缓存'
                        with self.assertRaises(TaskEnd):
                            getattr(instance, position + '_change')()
                        self.assertFalse(instance.config.Scheduler_Enable)
                        instance.config.task_stop.assert_called_once_with()
                        self.assertIsNone(instance.last_code)
                        if failed_step == 'clear_all_equip':
                            getattr(events, position + '_change_execute').assert_not_called()
                        if failed_step != 'apply_equip_code':
                            events.apply_equip_code.assert_not_called()

    def farming_runner(self, delay):
        instance = runner(GemsFarming, StopCondition_RunCount=0, GemsFarming_DelayTaskIFNoFlagship=delay)
        instance.config.task_switched = Mock(return_value=False)
        instance.config.task_delay = Mock()
        instance.config.task_stop = Mock(side_effect=TaskEnd)
        instance.get_emotion = Mock(return_value=100)
        instance.vanguard_change = Mock(return_value=True)
        instance.flagship_change = Mock(return_value=False)
        instance.campaign.ensure_auto_search_exit = Mock()
        return instance

    def test_no_low_level_replacement_delays_when_enabled(self):
        instance = self.farming_runner(delay=True)
        with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                patch.object(CampaignRun, 'run') as campaign_run:
            with self.assertRaises(TaskEnd):
                instance.run('C2', folder='event_test')
            self.assertFalse(GemsFarming._initial_flagship_check_done)
        campaign_run.assert_called_once()
        instance.config.task_delay.assert_called_once_with(minute=60)
        instance.campaign.ensure_auto_search_exit.assert_called_once_with()

    def test_no_low_level_replacement_continues_and_retries_after_battles(self):
        instance = self.farming_runner(delay=False)
        instance.flagship_change.side_effect = [False, False, True]
        battles = []

        def run_campaign(**kwargs):
            if not battles:
                # 启动时先检查旗舰，还没有出击。
                self.assertTrue(instance.triggered_stop_condition())
            else:
                # 找不到替换船也允许下一次出击；战后等级检测再次触发换船。
                self.assertFalse(instance.triggered_stop_condition())
                if len(battles) < 3:
                    instance.campaign.config.LV32_TRIGGERED = True
                    self.assertTrue(instance.triggered_stop_condition())
            battles.append(True)

        with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                patch.object(CampaignRun, 'triggered_stop_condition', return_value=False), \
                patch.object(CampaignRun, 'run', side_effect=run_campaign) as campaign_run:
            instance.run('C2', folder='event_test')
            self.assertTrue(GemsFarming._initial_flagship_check_done)
        self.assertEqual(campaign_run.call_count, 4)
        self.assertEqual(instance.flagship_change.call_count, 3)
        instance.config.task_delay.assert_not_called()
        instance.config.task_stop.assert_not_called()
        instance.campaign.ensure_auto_search_exit.assert_not_called()

    def test_continue_without_replacement_keeps_next_scheduled_initial_check(self):
        instance = self.farming_runner(delay=False)
        with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                patch.object(CampaignRun, 'run') as campaign_run:
            instance.run('C2', folder='event_test')
            self.assertFalse(GemsFarming._initial_flagship_check_done)
            instance.run('C2', folder='event_test')
        self.assertEqual(campaign_run.call_count, 4)
        self.assertEqual(instance.flagship_change.call_count, 2)
        instance.config.task_delay.assert_not_called()
        instance.config.task_stop.assert_not_called()

    def test_no_replacement_with_low_emotion_still_delays_when_disabled(self):
        instance = self.farming_runner(delay=False)
        with patch.object(GemsFarming, '_initial_flagship_check_done', True), \
                patch.object(CampaignRun, 'run', side_effect=CampaignEnd('Emotion control')) as campaign_run:
            with self.assertRaises(TaskEnd):
                instance.run('C2', folder='event_test')
        campaign_run.assert_called_once()
        instance.config.task_delay.assert_called_once_with(minute=60)
        instance.campaign.ensure_auto_search_exit.assert_called_once_with()

    def test_successful_ship_change_rechecks_pending_emotion_reserve(self):
        stamp = datetime(2026, 11, 8, 20, 21)
        for flagship_emotion, should_delay in ((47, True), (60, False)):
            with self.subTest(flagship_emotion=flagship_emotion):
                instance = self.farming_runner(delay=False)
                config = make_config('GemsFarming', Emotion={'MinReserve': 40})
                instance.campaign.config = config
                instance.campaign._map_battle = 4
                instance.campaign.emotion = GemsEmotion(config)

                def update_config():
                    for path, value in config.modified.items():
                        deep_set(config.data, path, value)
                    config.modified.clear()
                    config.bind(config.task)

                def change_flagship():
                    self.assertEqual(['1'], config.Emotion_RecoveryWait)
                    config.Emotion_MinReserve = 60
                    instance.set_emotion(flagship_emotion)
                    return True

                def run_campaign(**kwargs):
                    self.assertLessEqual(campaign_run.call_count, 1 if should_delay else 2)
                    instance.campaign.emotion.check_reduce(instance.campaign._map_battle)

                config.update = update_config
                config.auto_update = True
                instance.flagship_change.side_effect = change_flagship
                with patch('module.config.config.current_time', return_value=stamp), \
                        patch('module.combat.emotion.current_time', return_value=stamp), \
                        patch.object(GemsFarming, '_initial_flagship_check_done', True), \
                        patch.object(CampaignRun, 'run', side_effect=run_campaign) as campaign_run:
                    instance.set_emotion(5)
                    if should_delay:
                        with self.assertRaises(TaskEnd):
                            instance.run('2-4')
                        campaign_run.assert_called_once()
                        instance.config.task_delay.assert_called_once_with(target=stamp + timedelta(minutes=42))
                        instance.campaign.ensure_auto_search_exit.assert_called_once_with()
                        self.assertEqual(['1'], config.Emotion_RecoveryWait)
                    else:
                        instance.run('2-4')
                        self.assertEqual(2, campaign_run.call_count)
                        instance.config.task_delay.assert_not_called()
                        self.assertIsNone(config.Emotion_RecoveryWait)
                instance.flagship_change.assert_called_once_with()

    def test_hard_fleet_recovery_preserves_stop_and_does_not_ignore_failed_selection(self):
        for error in (HardNotSatisfied(), RequestHumanTakeover('Hard not satisfied')):
            for stops in (True, False):
                with self.subTest(error=type(error).__name__, stops=stops):
                    instance = runner(GemsFarming, StopCondition_RunCount=0, GemsFarming_DelayTaskIFNoFlagship=False)
                    instance.config.task_delay = Mock()
                    instance.config.task_stop = Mock(side_effect=TaskEnd)
                    instance.campaign.ensure_auto_search_exit = Mock()
                    instance.vanguard_change = Mock(side_effect=TaskEnd) if stops else Mock(return_value=False)
                    instance.flagship_change = Mock(return_value=True)
                    with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                            patch.object(CampaignRun, 'run', side_effect=error):
                        with self.assertRaises(TaskEnd):
                            instance.run('C2', folder='event_test')
                    if stops:
                        instance.flagship_change.assert_not_called()
                    else:
                        instance.config.task_delay.assert_called_once_with(minute=60)

    def test_interrupted_equipment_transfer_is_not_automatically_restarted(self):
        for error in (GameStuckError, GameTooManyClickError, EmulatorNotRunningError):
            instance = runner(GemsFarming, GemsFarming_ChangeFlagship='ship_equip')
            instance.hard_mode_override()
            instance.config.task_stop = Mock(side_effect=TaskEnd)
            instance._fleet_detail_enter = Mock()
            instance._ship_detail_enter = Mock()
            instance.clear_all_equip = Mock(side_effect=error)
            instance.flagship_change_execute = Mock()
            with self.assertRaises(TaskEnd):
                instance.flagship_change()
            self.assertFalse(instance.config.Scheduler_Enable)
            instance.flagship_change_execute.assert_not_called()
            self.assertIsNone(instance.last_code)

    def test_disabled_flagship_change_does_not_consume_initial_check(self):
        instance = runner(GemsFarming, GemsFarming_ChangeFlagship='disabled', StopCondition_RunCount=0)
        with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                patch.object(CampaignRun, 'run'):
            instance.run('C2', folder='event_test')
            self.assertFalse(GemsFarming._initial_flagship_check_done)


if __name__ == '__main__':
    unittest.main()
