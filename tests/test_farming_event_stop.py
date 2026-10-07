"""活动收尾按低耗任务的配置切换主线，或停用并保留活动关卡。"""

import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from module.campaign.campaign_event import CampaignEvent
from module.campaign.gems_farming import GemsFarming
from module.config.config import TaskEnd
from module.config.deep import deep_set
from module.config.utils import DEFAULT_TIME, read_file
from tests.test_farming_combat_config import make_config


class FarmingEventStopTests(unittest.TestCase):
    def make_campaign(self, command='ThreeOilLowCost', stage='C2', limit=100000, pt=100000, gems_stage='D3',
                      fallback=0, gems_fallback=0):
        config = make_config(command)
        config.data['ThreeOilLowCost']['Campaign'].update(Name=stage, Event='event_20241219_cn')
        config.data['ThreeOilLowCost']['Scheduler']['Enable'] = True
        config.data['GemsFarming']['Campaign'].update(Name=gems_stage, Event='event_20241219_cn')
        config.data['GemsFarming']['Scheduler']['Enable'] = True
        config.data['ThreeOilLowCost']['GemsFarming']['EventFallbackStage'] = fallback
        config.data['GemsFarming']['GemsFarming']['EventFallbackStage'] = gems_fallback
        config.override(
            Campaign_Name=stage if command == 'ThreeOilLowCost' else gems_stage,
            EventGeneral_PtLimit=limit,
        )
        config.modified.clear()
        campaign = CampaignEvent(config=config, device=Mock())
        campaign.get_event_pt = Mock(return_value=pt)
        return campaign

    def assert_farming_stopped_without_stage_change(self, campaign):
        changes = campaign.config.modified
        for task in ('ThreeOilLowCost', 'GemsFarming'):
            self.assertIs(changes.get(f'{task}.Scheduler.Enable'), False)
            self.assertNotIn(f'{task}.Campaign.Name', changes)
            self.assertNotIn(f'{task}.Campaign.Event', changes)

    def test_pt_limit_disables_three_oil_event_without_rewriting_stage(self):
        for command in ('ThreeOilLowCost', 'Event', 'GemsFarming'):
            for pt in (100000, 100120):
                with self.subTest(command=command, pt=pt):
                    campaign = self.make_campaign(command=command, pt=pt)
                    self.assertTrue(campaign.event_pt_limit_triggered())
                    changes = campaign.config.modified
                    self.assert_farming_stopped_without_stage_change(campaign)
                    self.assertEqual(campaign.config.cross_get('ThreeOilLowCost.Campaign.Name'), 'C2')
                    self.assertIs(changes['Event.Scheduler.Enable'], False)
                    self.assertEqual(changes['EventGeneral.EventGeneral.TimeLimit'], DEFAULT_TIME)

    def test_other_event_reaching_limit_preserves_main_three_oil(self):
        for stage in ('2-4', 'campaign_2_4', ' 7_2 '):
            with self.subTest(stage=stage):
                campaign = self.make_campaign(command='Event', stage=stage)
                self.assertTrue(campaign.event_pt_limit_triggered())
                self.assertFalse(any(key.startswith('ThreeOilLowCost.') for key in campaign.config.modified))

    def test_three_oil_runner_returns_without_starting_another_battle(self):
        campaign = self.make_campaign()
        campaign.config.override(EventGeneral_TimeLimit=DEFAULT_TIME)
        campaign.auto_search_oil_limit_triggered = False
        campaign.is_in_map = Mock(return_value=False)
        campaign.is_in_auto_search_menu = Mock(return_value=False)
        campaign.ensure_campaign_ui = Mock()
        campaign.ensure_auto_search_exit = Mock()
        campaign.run = Mock()
        runner = GemsFarming(config=campaign.config, device=campaign.device)
        runner.campaign = campaign
        runner.stage = 'c2'
        runner.load_campaign = Mock()
        runner.ui_page_appear = Mock(return_value=False)
        runner.disable_raid_on_event = Mock()
        runner.handle_commission_notice = Mock()
        runner.status_get_gems = Mock()
        runner.get_coin = Mock(return_value=10000)
        runner.get_oil = Mock(return_value=10000)
        with patch.object(GemsFarming, '_initial_flagship_check_done', True):
            runner.run('C2', folder='event_20241219_cn')
        campaign.run.assert_not_called()
        campaign.ensure_auto_search_exit.assert_called_once_with()
        runner.load_campaign.assert_called_once_with('c2', folder='event_20241219_cn')
        self.assertIs(campaign.config.modified.get('ThreeOilLowCost.Scheduler.Enable'), False)

    def test_main_three_oil_does_not_read_event_pt(self):
        campaign = self.make_campaign(stage='2-4')
        self.assertFalse(campaign.event_pt_limit_triggered())
        campaign.get_event_pt.assert_not_called()
        self.assertEqual(campaign.config.modified, {})

    def test_below_limit_and_disabled_limit_leave_tasks_unchanged(self):
        for limit, pt in ((100000, 99999), (0, 100000)):
            with self.subTest(limit=limit, pt=pt):
                campaign = self.make_campaign(limit=limit, pt=pt)
                self.assertFalse(campaign.event_pt_limit_triggered())
                self.assertEqual(campaign.config.modified, {})

    def test_gems_farming_event_also_stops_at_pt_limit(self):
        campaign = self.make_campaign()
        self.assertTrue(campaign.event_pt_limit_triggered())
        self.assert_farming_stopped_without_stage_change(campaign)

    def test_time_limit_stops_farming_without_rewriting_stage(self):
        campaign = self.make_campaign()
        now = datetime(2026, 9, 20, 12)
        campaign.config.override(EventGeneral_TimeLimit=now - timedelta(seconds=1))
        with patch('module.campaign.campaign_event.current_time', return_value=now):
            self.assertTrue(campaign.event_time_limit_triggered())
        self.assert_farming_stopped_without_stage_change(campaign)

    def test_default_and_legacy_time_limits_are_disabled(self):
        args = read_file('module/config/argument/args.json')
        self.assertEqual(
            datetime.fromisoformat(args['EventGeneral']['EventGeneral']['TimeLimit']['value']),
            DEFAULT_TIME,
        )

        campaign = self.make_campaign()
        now = datetime(2026, 9, 22, 12)
        for limit in (DEFAULT_TIME, datetime(2020, 1, 1)):
            with self.subTest(limit=limit):
                campaign.config.override(EventGeneral_TimeLimit=limit)
                with patch('module.campaign.campaign_event.current_time', return_value=now):
                    self.assertFalse(campaign.event_time_limit_triggered())
        self.assertEqual(campaign.config.modified, {})

    def test_missing_event_entrance_stops_without_rewriting_stage(self):
        campaign = self.make_campaign()
        campaign.appear = Mock(return_value=True)
        campaign.config.task_stop = Mock(side_effect=TaskEnd)
        with self.assertRaises(TaskEnd):
            campaign.is_event_entrance_available()
        self.assert_farming_stopped_without_stage_change(campaign)
        campaign.config.task_stop.assert_called_once_with()

    def test_new_activity_stops_old_farming_without_rewriting_stage(self):
        for command in ('Raid', 'Coalition', 'MaritimeEscort'):
            for other_event_enabled in (False, True):
                with self.subTest(command=command, other_event_enabled=other_event_enabled):
                    campaign = self.make_campaign(command=command)
                    enabled = {'ThreeOilLowCost', 'GemsFarming'}
                    if other_event_enabled:
                        enabled.add('Event')
                    campaign.config.is_task_enabled = Mock(side_effect=lambda task: task in enabled)
                    self.assertTrue(campaign.disable_event_on_raid())
                    self.assert_farming_stopped_without_stage_change(campaign)

    def test_all_event_cleanup_paths_leave_main_farming_unchanged(self):
        for stage in ('2-4', 'campaign_2_4', ' 7_2 '):
            for trigger in ('pt', 'time', 'entrance', 'activity'):
                with self.subTest(stage=stage, trigger=trigger):
                    campaign = self.make_campaign(command='Raid', stage=stage, gems_stage=stage)
                    if trigger == 'pt':
                        self.assertTrue(campaign.event_pt_limit_triggered())
                    elif trigger == 'time':
                        now = datetime(2026, 9, 20, 12)
                        campaign.config.override(EventGeneral_TimeLimit=now - timedelta(seconds=1))
                        with patch('module.campaign.campaign_event.current_time', return_value=now):
                            self.assertTrue(campaign.event_time_limit_triggered())
                    elif trigger == 'entrance':
                        campaign.appear = Mock(return_value=True)
                        campaign.config.task_stop = Mock(side_effect=TaskEnd)
                        with self.assertRaises(TaskEnd):
                            campaign.is_event_entrance_available()
                    else:
                        campaign.config.is_task_enabled = Mock(
                            side_effect=lambda task: task in ('ThreeOilLowCost', 'GemsFarming'))
                        self.assertFalse(campaign.disable_event_on_raid())
                        self.assertEqual(campaign.config.modified, {})
                    for task in ('ThreeOilLowCost', 'GemsFarming'):
                        self.assertFalse(any(key.startswith(f'{task}.') for key in campaign.config.modified))

    def test_old_configs_default_to_2_4_and_explicit_stop_survives_reload(self):
        args = read_file('module/config/argument/args.json')
        for task in ('ThreeOilLowCost', 'GemsFarming'):
            with self.subTest(task=task):
                self.assertNotIn(args[task]['GemsFarming']['EventFallbackStage'].get('display'),
                                 ('hide', 'disabled'))
                config = make_config(task)
                self.assertEqual(config.GemsFarming_EventFallbackStage, '2-4')
                for stage in (0, '0', '7-2'):
                    config = make_config(task, GemsFarming={'EventFallbackStage': stage})
                    config.data = config.config_update(config.data)
                    config.bind(task)
                    self.assertEqual(str(config.GemsFarming_EventFallbackStage), str(stage))
        self.assertEqual(args['Ambush11']['GemsFarming']['EventFallbackStage']['display'], 'hide')

    def test_all_event_cleanup_paths_use_each_farming_tasks_fallback(self):
        for trigger in ('pt', 'time', 'entrance', 'activity'):
            with self.subTest(trigger=trigger):
                campaign = self.make_campaign(command='Raid', fallback='2-4', gems_fallback='7-2')
                if trigger == 'pt':
                    self.assertTrue(campaign.event_pt_limit_triggered())
                elif trigger == 'time':
                    now = datetime(2026, 9, 20, 12)
                    campaign.config.override(EventGeneral_TimeLimit=now - timedelta(seconds=1))
                    with patch('module.campaign.campaign_event.current_time', return_value=now):
                        self.assertTrue(campaign.event_time_limit_triggered())
                elif trigger == 'entrance':
                    campaign.appear = Mock(return_value=True)
                    campaign.config.task_stop = Mock(side_effect=TaskEnd)
                    with self.assertRaises(TaskEnd):
                        campaign.is_event_entrance_available()
                else:
                    campaign.config.is_task_enabled = Mock(
                        side_effect=lambda task: task in ('ThreeOilLowCost', 'GemsFarming'))
                    self.assertTrue(campaign.disable_event_on_raid())
                for task, stage in (('ThreeOilLowCost', '2-4'), ('GemsFarming', '7-2')):
                    changes = campaign.config.modified
                    self.assertEqual(changes[f'{task}.Campaign.Name'], stage)
                    self.assertEqual(changes[f'{task}.Campaign.Event'], 'campaign_main')
                    self.assertNotIn(f'{task}.Scheduler.Enable', changes)
                    self.assertNotIn(f'{task}.Scheduler.NextRun', changes)
                    self.assertNotIn(f'{task}.Emotion.Fleet1Onsen', changes)

    def test_fallback_and_stop_can_be_configured_independently(self):
        for fallback, gems_fallback in (('7-2', 0), (0, '2-4')):
            with self.subTest(fallback=fallback, gems_fallback=gems_fallback):
                campaign = self.make_campaign(fallback=fallback, gems_fallback=gems_fallback)
                self.assertTrue(campaign.event_pt_limit_triggered())
                changes = campaign.config.modified
                for task, stage in (('ThreeOilLowCost', fallback), ('GemsFarming', gems_fallback)):
                    if stage == 0:
                        self.assertIs(changes[f'{task}.Scheduler.Enable'], False)
                        self.assertNotIn(f'{task}.Campaign.Name', changes)
                    else:
                        self.assertNotIn(f'{task}.Scheduler.Enable', changes)
                        self.assertEqual(changes[f'{task}.Campaign.Name'], stage)

    def test_invalid_fallback_stops_without_rewriting_event_stage(self):
        for stage in ('C2', '99-1', '2-5', '2-4oops', '../2-4', '', None, -1):
            with self.subTest(stage=stage):
                campaign = self.make_campaign(fallback=stage, gems_fallback=stage)
                self.assertTrue(campaign.event_pt_limit_triggered())
                self.assert_farming_stopped_without_stage_change(campaign)

    def test_fallback_normalizes_main_stage_aliases(self):
        for stage in ('2-4', 'campaign_2_4', ' 2_4 '):
            with self.subTest(stage=stage):
                campaign = self.make_campaign(fallback=stage)
                self.assertTrue(campaign.event_pt_limit_triggered())
                self.assertEqual(campaign.config.modified['ThreeOilLowCost.Campaign.Name'], '2-4')

    def test_fallback_does_not_enable_disabled_tasks(self):
        campaign = self.make_campaign(command='Event', fallback='2-4', gems_fallback='7-2')
        for task in ('ThreeOilLowCost', 'GemsFarming'):
            campaign.config.data[task]['Scheduler']['Enable'] = False
        self.assertTrue(campaign.event_pt_limit_triggered())
        for task in ('ThreeOilLowCost', 'GemsFarming'):
            self.assertNotIn(f'{task}.Scheduler.Enable', campaign.config.modified)
            self.assertIs(campaign.config.cross_get(f'{task}.Scheduler.Enable'), False)

    def test_next_dispatch_loads_main_campaign_and_ignores_event_limits(self):
        for task in ('ThreeOilLowCost', 'GemsFarming'):
            with self.subTest(task=task):
                campaign = self.make_campaign(command=task, fallback='7-2', gems_fallback='2-4')
                self.assertTrue(campaign.event_pt_limit_triggered())
                # 模拟收尾配置保存后的下一次调度，避免沿用活动运行器的临时覆盖。
                saved = deepcopy(campaign.config.data)
                for key, value in campaign.config.modified.items():
                    deep_set(saved, key, value)
                config = make_config(task, **saved[task])
                config.override(EventGeneral_PtLimit=100000,
                                EventGeneral_TimeLimit=datetime(2026, 9, 20))
                self.assertTrue(config.Scheduler_Enable)
                self.assertEqual(config.Campaign_Name, '7-2' if task == 'ThreeOilLowCost' else '2-4')
                runner = GemsFarming(config=config, device=Mock())
                name, folder = runner.handle_stage_name(config.Campaign_Name, config.Campaign_Event)
                runner.load_campaign(name, folder=folder)
                runner.campaign.get_event_pt = Mock()
                self.assertEqual(runner.folder, 'campaign_main')
                self.assertFalse(runner.campaign.event_pt_limit_triggered())
                self.assertFalse(runner.campaign.event_time_limit_triggered())
                runner.campaign.get_event_pt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
