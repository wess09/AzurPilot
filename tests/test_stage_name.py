"""关卡名称纯规则与运行器编排顺序回归，不连接游戏。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.campaign.run import CampaignRun
from module.campaign.stage_name import normalize_event_stage, normalize_post_loop_stage


class StageNameRuleTests(unittest.TestCase):
    """纯规则的输入均已是地图文件名，原始用户输入另走集成测试。"""

    def test_special_sp_names_are_scoped_to_the_event(self):
        for folder, aliases in (
            ('event_20201126_cn', ('vsp',)),
            ('event_20210723_cn', ('vsp',)),
            ('event_20220324_cn', ('esp',)),
            ('event_20220818_cn', ('esp',)),
            ('event_20221124_cn', ('asp', 'a.sp')),
            ('event_20240425_cn', ('μsp', 'usp', 'iisp')),
            ('event_20240724_cn', ('ysp', 'y.sp')),
        ):
            for name in aliases:
                with self.subTest(folder=folder, name=name):
                    self.assertEqual(normalize_event_stage(name, folder), 'sp')
                    self.assertEqual(normalize_event_stage(name, 'event_unknown'), name)

    def test_isp_typo_replacements_follow_exact_sp_aliases(self):
        for name, expected in (
            ('iisp', 'sp'), ('μsp', 'sp'), ('isp', 'isp1'),
            ('lsp', 'isp1'), ('1sp', 'isp1'), ('lsp2', 'isp2'),
            ('1sp2', 'isp2'), ('iisp1', 'iisp1'), ('xlsp', 'xisp'),
            ('campaign_1sp', 'campaign_isp'),
        ):
            with self.subTest(name=name):
                self.assertEqual(normalize_event_stage(name, 'event_20240425_cn'), expected)

    def test_six_stage_t_events_accept_a_and_sp_aliases(self):
        for folder in (
            'event_20211125_cn', 'event_20231026_cn', 'event_20241024_cn',
            'event_20250424_cn', 'event_20250724_cn', 'event_20250814_cn',
            'event_20251023_cn', 'event_20260326_cn', 'event_20260625_cn',
            'war_archives_20230525_cn', 'war_archives_20231026_cn', 'war_archives_20240725_cn',
        ):
            for prefix in ('a', 'sp'):
                for index in range(1, 7):
                    with self.subTest(folder=folder, prefix=prefix, index=index):
                        self.assertEqual(normalize_event_stage(f'{prefix}{index}', folder), f't{index}')
            self.assertEqual(normalize_event_stage('a7', folder), 'a7')
            self.assertEqual(normalize_event_stage('sp7', folder), 'sp7')

    def test_abcd_and_t_ht_conversion_in_both_directions(self):
        pairs = (
            ('a1', 't1'), ('a2', 't2'), ('a3', 't3'),
            ('b1', 't4'), ('b2', 't5'), ('b3', 't6'),
            ('c1', 'ht1'), ('c2', 'ht2'), ('c3', 'ht3'),
            ('d1', 'ht4'), ('d2', 'ht5'), ('d3', 'ht6'),
        )
        for folder in (
            'event_20200917_cn', 'event_20230525_cn', 'war_archives_20200917_cn',
            'event_20231123_cn', 'event_20240725_cn', 'event_20240829_cn',
            'event_20241121_cn', 'event_20211125_cn', 'war_archives_20240725_cn',
        ):
            for abcd, t_ht in pairs:
                with self.subTest(folder=folder, abcd=abcd):
                    self.assertEqual(normalize_event_stage(abcd, folder), t_ht)
                    self.assertEqual(normalize_event_stage(t_ht, folder), t_ht)
        for folder in ('event_unknown', 'campaign_main', 'event_20260908_cn', None):
            for abcd, t_ht in pairs:
                with self.subTest(folder=folder, t_ht=t_ht):
                    self.assertEqual(normalize_event_stage(t_ht, folder), abcd)
                    self.assertEqual(normalize_event_stage(abcd, folder), abcd)

    def test_th_sp_and_story_rules_keep_their_order(self):
        for name, folder, expected in (
            ('c1', 'event_20221124_cn', 'th1'),
            ('d3', 'event_20221124_cn', 'th6'),
            ('ht3', 'event_20221124_cn', 'th3'),
            ('xht', 'event_20221124_cn', 'xth'),
            ('a4', 'event_20221124_cn', 'a4'),
            ('sp1', 'event_20221124_cn', 'sp1'),
            ('e0', 'event_20230817_cn', 'a1'),
            ('e01', 'event_20230817_cn', 'a1'),
            ('e1', 'event_20230817_cn', 'e1'),
            ('tp', 'event_20240829_cn', 'sp'),
            ('tp1', 'event_20240829_cn', 'tp1'),
            ('vsp', 'event_20260417_cn', 'vsp'),
        ):
            with self.subTest(name=name, folder=folder):
                self.assertEqual(normalize_event_stage(name, folder), expected)
        self.assertEqual(normalize_post_loop_stage('vsp', 'event_20260417_cn'), 'sp')
        self.assertEqual(normalize_post_loop_stage('vsp', 'event_20201126_cn'), 'vsp')
        self.assertEqual(normalize_post_loop_stage('ht1', 'event_unknown'), 'ht1')


class StageNameIntegrationTests(unittest.TestCase):
    """仅替换配置、文件探测和随机选择，保留真实名称处理流程。"""

    def make_runner(self, command='Event', achievement='map_3_stars', aliases=None, count=1):
        runner = object.__new__(CampaignRun)
        runner.config = SimpleNamespace(
            task=SimpleNamespace(command=command),
            Campaign_Event=None,
            STAGE_LOOP_ALIAS=aliases or {},
            StopCondition_RunCount=count,
            StopCondition_MapAchievement=achievement,
            cross_get=Mock(return_value='event_latest'),
        )

        def override(**kwargs):
            for name, value in kwargs.items():
                setattr(runner.config, name, value)

        runner.config.override = Mock(side_effect=override)
        return runner

    def test_user_input_normalization_precedes_event_rules(self):
        runner = self.make_runner()
        for name, folder, expected in (
            (' 7-2\t\n', 'campaign_main', 'campaign_7_2'),
            ('CAMPAIGN_12_4', 'campaign_main', 'campaign_12_4'),
            ('A-1', 'event_20260326_cn', 't1'),
            ('D3', 'event_20260908_cn', 'd3'),
            ('ΜSP', 'event_20240425_cn', 'sp'),
            ('LSP', 'event_20240425_cn', 'isp1'),
            # 数字开头会先加 campaign_，不能在拆分时直接把它改成 isp1。
            ('1sp', 'event_20240425_cn', 'campaign_isp'),
        ):
            with self.subTest(name=name):
                self.assertEqual(runner.handle_stage_name(name, folder), (expected, folder))

    def test_farming_folder_precedence(self):
        for command in ('GemsFarming', 'ThreeOilLowCost'):
            for configured, supplied, fallback, expected in (
                ('event_configured', 'event_supplied', 'event_latest', 'event_configured'),
                ('campaign_main', 'event_supplied', 'event_latest', 'event_supplied'),
                (None, 'campaign_main', 'event_latest', 'event_latest'),
                (None, None, None, 'campaign_main'),
                (None, None, '', ''),
            ):
                with self.subTest(command=command, configured=configured, supplied=supplied):
                    runner = self.make_runner(command=command)
                    runner.config.Campaign_Event = configured
                    runner.config.cross_get.return_value = fallback
                    self.assertEqual(runner.handle_stage_name('D3', supplied), ('d3', expected))
                    self.assertEqual(runner.handle_stage_name('7-2', supplied), ('campaign_7_2', 'campaign_main'))
        runner = self.make_runner()
        runner.config.Campaign_Event = 'event_configured'
        self.assertEqual(runner.handle_stage_name('D3', 'event_supplied'), ('d3', 'event_supplied'))
        runner.config.cross_get.assert_not_called()

    def test_d3_retreat_alias_uses_selected_folder_and_actual_file(self):
        for exists in (False, True):
            with self.subTest(exists=exists):
                runner = self.make_runner(command='ThreeOilLowCost')
                runner.config.Campaign_Event = 'event_selected'
                with patch('module.campaign.run.os.path.exists', return_value=exists) as probe:
                    self.assertEqual(
                        runner.handle_stage_name('D3-3', 'campaign_main'),
                        ('d3_3' if exists else 'd3-3', 'event_selected'),
                    )
                probe.assert_called_once_with('./campaign/event_selected/d3_3.py')
        with patch('module.campaign.run.os.path.exists') as probe:
            self.assertEqual(runner.handle_stage_name('D3', 'event_selected'), ('d3', 'event_selected'))
        probe.assert_not_called()

    def test_ordered_loop_uses_remaining_run_count(self):
        for count, expected in ((1, 'd3'), (2, 'd2'), (3, 'd1'), (4, 'd3'), ('5', 'd2'), (-1, 'd2')):
            with self.subTest(count=count):
                runner = self.make_runner(aliases={('event_unknown', 'LOOP'): ' D1 > D2\t> D3\n'}, count=count)
                self.assertEqual(runner.handle_stage_name('loop', 'event_unknown'), (expected, 'event_unknown'))
                self.assertTrue(runner.is_stage_loop)
                self.assertEqual(runner.config.StopCondition_MapAchievement, 'non_stop')
                self.assertFalse(runner.config.StopCondition_StageIncrease)

    def test_random_loop_does_not_renormalize_selected_stage(self):
        runner = self.make_runner(aliases={('event_unknown', 'LOOP'): ' 7-2 > HT1 '}, count=0)
        with patch('module.campaign.run.random.choice', return_value='HT1') as choose:
            self.assertEqual(runner.handle_stage_name('loop', 'event_unknown'), ('ht1', 'event_unknown'))
        choose.assert_called_once_with(['7-2', 'HT1'])
        # 同一个运行器后来处理普通关卡时，原有循环状态不会被主动清空。
        self.assertEqual(runner.handle_stage_name('a1', 'event_unknown'), ('a1', 'event_unknown'))
        self.assertTrue(runner.is_stage_loop)

    def test_loop_results_can_match_later_aliases(self):
        runner = self.make_runner(aliases={
            ('event_unknown', 'START'): 'NEXT',
            ('event_unknown', 'NEXT'): 'HT1',
        })
        self.assertEqual(runner.handle_stage_name('start', 'event_unknown'), ('ht1', 'event_unknown'))
        self.assertEqual(runner.config.override.call_args_list, [
            call(StopCondition_MapAchievement='non_stop'), call(StopCondition_StageIncrease=False),
            call(StopCondition_MapAchievement='non_stop'), call(StopCondition_StageIncrease=False),
        ])

    def test_pre_loop_and_post_loop_aliases_are_not_interchanged(self):
        for name, folder, alias, stages, expected in (
            ('vsp', 'event_20201126_cn', 'SP', 'D3', 'd3'),
            ('vsp', 'event_20260417_cn', 'VSP', 'D3', 'd3'),
            ('loop', 'event_20260417_cn', 'LOOP', 'VSP', 'sp'),
            ('e0', 'event_20230817_cn', 'A1', 'HT1', 'ht1'),
            ('tp', 'event_20240829_cn', 'SP', 'D3', 'd3'),
        ):
            with self.subTest(name=name, folder=folder):
                runner = self.make_runner(aliases={(folder, alias): stages})
                self.assertEqual(runner.handle_stage_name(name, folder), (expected, folder))
                self.assertTrue(runner.is_stage_loop)

    def test_hard_mode_requires_file_and_checks_selected_loop_name(self):
        for name, folder, mode, files, expected_folder in (
            ('7-2', 'campaign_main', 'hard', ['campaign_7_2'], 'campaign_hard'),
            ('7-2', 'campaign_main', 'hard', [], 'campaign_main'),
            ('7-2', 'campaign_main', 'normal', ['campaign_7_2'], 'campaign_main'),
            ('d3', 'event_unknown', 'hard', ['d3'], 'event_unknown'),
        ):
            with self.subTest(name=name, folder=folder, mode=mode):
                runner = self.make_runner()
                with patch('module.campaign.run.map_files', return_value=files) as probe:
                    self.assertEqual(runner.handle_stage_name(name, folder, mode)[1], expected_folder)
                if mode == 'hard' and folder == 'campaign_main':
                    probe.assert_called_once_with('campaign_hard')
                else:
                    probe.assert_not_called()
        for selected, expected_folder in (('campaign_7_2', 'campaign_hard'), ('7-2', 'campaign_main')):
            runner = self.make_runner(aliases={('campaign_main', 'LOOP'): selected})
            with patch('module.campaign.run.map_files', return_value=['campaign_7_2']):
                self.assertEqual(runner.handle_stage_name('loop', 'campaign_main', 'hard'), (selected, expected_folder))

    def test_th_and_ts_achievement_overrides_precede_loop_override(self):
        for folder, name, prefix in (
            ('event_20221124_cn', 'HT', 'TH'), ('event_20250724_cn', 'TS', 'TS'),
        ):
            for achievement in ('map_3_stars', 'non_stop', 'non_stop_clear_all'):
                with self.subTest(folder=folder, achievement=achievement):
                    runner = self.make_runner(achievement=achievement, aliases={(folder, prefix): f'{prefix}1'})
                    self.assertEqual(runner.handle_stage_name(name, folder), (f'{prefix.lower()}1', folder))
                    calls = [] if achievement.startswith('non_stop') else [call(StopCondition_MapAchievement='threat_safe')]
                    self.assertEqual(runner.config.override.call_args_list, calls + [
                        call(StopCondition_MapAchievement='non_stop'), call(StopCondition_StageIncrease=False),
                    ])

    def test_tss_overrides_all_timed_stage_restrictions(self):
        runner = self.make_runner()
        self.assertEqual(runner.handle_stage_name('xtss2', 'event_20211125_cn'), ('xtss2', 'event_20211125_cn'))
        runner.config.override.assert_called_once_with(
            StopCondition_OilLimit=0,
            StopCondition_MapAchievement='100_percent_clear',
            StopCondition_StageIncrease=True,
            Emotion_Mode='ignore',
            Fleet_Fleet2=0,
            Submarine_Fleet=0,
        )

    def test_achievement_fallback_runs_after_loop_constraints(self):
        folder = 'event_20240912_cn'
        for achievement, expected in (
            ('threat_safe', 'map_3_stars'),
            ('threat_safe_without_3_stars', '100_percent_clear'),
            ('non_stop', 'non_stop'),
        ):
            with self.subTest(achievement=achievement):
                runner = self.make_runner(achievement=achievement)
                runner.handle_stage_name('d3', folder)
                self.assertEqual(runner.config.StopCondition_MapAchievement, expected)
        runner = self.make_runner(achievement='threat_safe', aliases={(folder, 'LOOP'): 'D3'})
        runner.handle_stage_name('loop', folder)
        self.assertEqual(runner.config.override.call_args_list, [
            call(StopCondition_MapAchievement='non_stop'), call(StopCondition_StageIncrease=False),
        ])
