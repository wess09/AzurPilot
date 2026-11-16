"""作战委托使用真实地图配置与内存设备验证主线、活动及准备页难度。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.config.config import AzurLaneConfig, name_to_function
from module.handover.handover import OperationHandover
from module.map.assets import (
    FLEET_PREPARATION, HANDOVER_CHECK, HANDOVER_TAB, HANDOVER_TAB_UNSUPPORTED,
    MAP_MODE_SWITCH_HARD, MAP_MODE_SWITCH_NORMAL,
)


class HandoverStageNavigationTests(unittest.TestCase):
    def prepare_runner(self, stage='D3', folder='event_20260908_cn', current_mode='normal',
                       destination='preparation', fleet=True):
        config = AzurLaneConfig('template')
        config.auto_update = False
        config.data = config.config_update({'OperationHandover': {'Campaign': {'Name': stage}}})
        config.bind('OperationHandover')
        config.task = name_to_function('OperationHandover')
        # 固定历史地图夹具，避免测试随当前活动列表变化；配置全程留在内存。
        config.override(Campaign_Event=folder)
        runner = OperationHandover(config=config, device=Mock())
        state = dict(page='chapter', mode=current_mode, pending=None, shots=0)
        trace = []
        load_campaign = runner.load_campaign

        def load(name, folder):
            changed = load_campaign(name, folder)
            campaign = runner.campaign
            campaign.ENTRANCE = SimpleNamespace(name=runner.stage)
            campaign.ui_goto_event = Mock()
            campaign.ui_goto_sp = Mock()
            def ensure_mode(mode):
                state['mode'] = mode
                if mode == 'hard':
                    campaign.config.override(Campaign_Mode='hard')

            campaign.campaign_ensure_mode = Mock(side_effect=ensure_mode)
            campaign.campaign_ensure_mode_20241219 = Mock()
            campaign.campaign_ensure_aside_20241219 = Mock()
            campaign.campaign_ensure_aside_20260326 = Mock()
            campaign.campaign_ensure_chapter = Mock()

            def navigate(name, **kwargs):
                if folder != 'campaign_main':
                    # 真实活动导航根据 C/D 等关卡名设置地图副本的目标难度。
                    campaign.campaign_set_chapter(name)

            campaign.ensure_campaign_ui = Mock(side_effect=navigate)
            campaign.appear = Mock(side_effect=lambda button, **kwargs: (
                button is FLEET_PREPARATION and state['page'] == 'preparation' and fleet))

            def enter(button, **kwargs):
                if button is campaign.ENTRANCE and state['page'] == 'chapter':
                    trace.append('enter')
                    state['page'] = destination
                    return True
                return False

            campaign.appear_then_click = Mock(side_effect=enter)

            def prepare_fleet():
                self.assertEqual(state['mode'], campaign.config.Campaign_Mode)
                self.assertIsNone(state['pending'], '切换后必须先获取新截图')
                trace.append('fleet_' + state['mode'])

            campaign.fleet_preparation = Mock(side_effect=prepare_fleet)
            campaign.match_template_color = Mock(side_effect=lambda button, **kwargs: (
                button is MAP_MODE_SWITCH_NORMAL and state['page'] == 'preparation'
                and state['mode'] == 'normal'))
            campaign._is_mod_switch_hard_appear = Mock(side_effect=lambda **kwargs: (
                state['page'] == 'preparation' and state['mode'] == 'hard'))
            return changed

        def screenshot():
            state['shots'] += 1
            if state['shots'] > 16:
                raise RuntimeError('模拟设备截图超时')
            if state['pending']:
                state['mode'], state['pending'] = state['pending'], None

        def appear(button, **kwargs):
            if state['page'] != 'preparation':
                return False
            # 普通页不支持委托，困难页支持；必须先切换再交给支持检测。
            if button is HANDOVER_TAB:
                return state['mode'] == 'hard'
            if button is HANDOVER_TAB_UNSUPPORTED:
                return state['mode'] == 'normal'
            return False

        def view_handover(button, **kwargs):
            if button is HANDOVER_CHECK and state['page'] == 'conflict':
                state['page'] = 'ongoing'
                trace.append('view_handover')
                return True
            return False

        def click(button):
            modes = {MAP_MODE_SWITCH_NORMAL: 'normal', MAP_MODE_SWITCH_HARD: 'hard'}
            state['pending'] = modes[button]
            trace.append('switch_' + state['pending'])

        runner.load_campaign = Mock(side_effect=load)
        runner.device.screenshot.side_effect = screenshot
        runner.device.click.side_effect = click
        runner.appear = Mock(side_effect=appear)
        runner.appear_then_click = Mock(side_effect=view_handover)
        runner.handover_handle_popup = Mock(return_value=False)
        runner.handover_dialog_appear = Mock(side_effect=lambda: state['page'] in ('ongoing', 'completed'))
        return runner, state, trace

    def test_main_stage_ignores_selected_event(self):
        for stage in ('12-4', 'campaign_12_4'):
            with self.subTest(stage=stage):
                runner, _, trace = self.prepare_runner(stage=stage)
                runner.handover_enter()
                self.assertEqual(runner.folder, 'campaign_main')
                self.assertEqual(runner.name, 'campaign_12_4')
                runner.campaign.ensure_campaign_ui.assert_called_once_with(
                    name='12-4', mode='normal', skip_first_screenshot=True)
                self.assertEqual(trace, ['enter', 'fleet_normal'])

    def test_activity_aliases_load_real_maps(self):
        for stage, folder, name in (
            ('D-3', 'event_20260908_cn', 'd3'),
            ('T6', 'event_20261022_cn', 't6'),
            ('SP3', 'event_20261022_cn', 't3'),
            ('A1', 'event_20261022_cn', 't1'),
            ('VSP', 'event_20260417_cn', 'sp'),
            ('D3', 'war_archives_20230817_cn', 'd3'),
        ):
            with self.subTest(stage=stage, folder=folder):
                runner, _, _ = self.prepare_runner(stage=stage, folder=folder)
                runner.handover_enter()
                self.assertEqual(runner.folder, folder)
                self.assertEqual(runner.name, name)
                self.assertEqual(runner.module.__name__, f'campaign.{folder}.{name}')
                if folder.startswith('war_archives_'):
                    self.assertTrue(runner.campaign.config.USE_DATA_KEY)

    def test_shared_entrance_switches_to_target_difficulty_before_fleet(self):
        for stage, initial, target in (('C2', 'normal', 'hard'), ('D3', 'normal', 'hard'),
                                       ('A2', 'hard', 'normal'), ('B3', 'hard', 'normal')):
            with self.subTest(stage=stage):
                runner, state, trace = self.prepare_runner(stage=stage, current_mode=initial)
                runner.handover_enter()
                self.assertEqual(trace, ['enter', 'switch_' + target, 'fleet_' + target])
                self.assertEqual(state['mode'], target)
                self.assertEqual(runner.config.Campaign_Mode, 'normal')
                self.assertEqual(runner.campaign.config.Campaign_Mode, target)

    def test_correct_mode_and_maps_without_switch_do_not_toggle(self):
        for stage, folder, mode in (('D3', 'event_20260908_cn', 'hard'),
                                    ('T6', 'event_20261022_cn', 'normal')):
            with self.subTest(stage=stage):
                runner, _, trace = self.prepare_runner(stage=stage, folder=folder, current_mode=mode)
                runner.handover_enter()
                self.assertEqual(trace, ['enter', 'fleet_' + mode])

    def test_fleet_preparation_waits_for_difficulty_when_handover_tab_is_delayed(self):
        runner, _, trace = self.prepare_runner()
        appear = runner.appear.side_effect
        runner.appear.side_effect = lambda button, **kwargs: (
            hasattr(runner, 'campaign') and runner.campaign.map_fleet_checked and appear(button, **kwargs))
        runner.handover_enter()
        self.assertEqual(trace, ['enter', 'switch_hard', 'fleet_hard'])

    def test_existing_commission_takes_priority_over_mode_and_fleet(self):
        for destination in ('ongoing', 'completed', 'conflict'):
            with self.subTest(destination=destination):
                runner, state, trace = self.prepare_runner(destination=destination)
                runner.handover_enter()
                self.assertIn(state['page'], ('ongoing', 'completed'))
                self.assertEqual(trace, ['enter', 'view_handover'] if destination == 'conflict' else ['enter'])
                runner.campaign.fleet_preparation.assert_not_called()
                runner.device.click.assert_not_called()

    def test_unrecognized_difficulty_does_not_prepare_or_accept_stage(self):
        runner, _, trace = self.prepare_runner()
        load = runner.load_campaign.side_effect

        def unknown_mode(*args, **kwargs):
            changed = load(*args, **kwargs)
            runner.campaign.match_template_color.side_effect = None
            runner.campaign.match_template_color.return_value = False
            runner.campaign._is_mod_switch_hard_appear.side_effect = None
            runner.campaign._is_mod_switch_hard_appear.return_value = False
            return changed

        runner.load_campaign.side_effect = unknown_mode
        with self.assertRaisesRegex(RuntimeError, '模拟设备截图超时'):
            runner.handover_enter()
        self.assertEqual(trace, ['enter'])
        runner.campaign.fleet_preparation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
