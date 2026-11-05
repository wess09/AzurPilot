"""离线回放自律寻敌结算，验证沉船撤退、弹窗与关闭任务策略。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import module.config.server as server

server.server = 'cn'

from module.base.timer import Timer
from module.campaign.gems_farming import GemsCampaignOverride
from module.campaign.run import CampaignRun
from module.combat.assets import (
    BATTLE_STATUS_D, EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D, EXP_INFO_S, OPTS_INFO_D,
)
from module.combat.auto_search_combat import AutoSearchCombat
from module.exception import CampaignEnd, GameStuckError, RequestHumanTakeover, ScriptEnd
from module.handler.assets import (
    AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON, AUTO_SEARCH_MENU_EXIT, GET_MISSION,
    POPUP_CANCEL, POPUP_CONFIRM, FLEET_UNAVAILABLE,
)
from module.map.assets import (
    FLEET_NUM_1, FLEET_NUM_2, SWITCH_OVER, WITHDRAW,
)


def screen(*buttons):
    """拼一帧识别结果。

    每次调用代表一次独立截图，内容相同的两帧也必须分别调用；列表乘法会复用同一个
    frozenset 对象，不算新的一帧。
    """
    return frozenset(button if isinstance(button, str) else button.name for button in buttons)


class ScreenReplay:
    """只提供识别结果和虚拟时钟，点击、截图及等待均不接触模拟器。"""

    def __init__(self, frames):
        self.time = 100.0
        self.clicks = []
        self.click_frames = []
        self.device = Mock(
            has_cached_image=True, app_is_running=Mock(return_value=True),
            screenshot=Mock(side_effect=self.screenshot), click=Mock(side_effect=self.click))
        self.load(frames)

    def load(self, frames):
        self.frames = list(frames)
        self.index = 0
        self.device.image = self.frames[0]

    def screenshot(self):
        self.time += 1
        self.index += 1
        if self.index >= len(self.frames):
            raise AssertionError(f'结算未在夹具内结束，已点击：{self.clicks}')
        self.device.image = self.frames[self.index]

    def click(self, button):
        self.clicks.append(button.name)
        self.click_frames.append((self.index, button.name))

    def appear(self, button, offset=0, interval=0, **kwargs):
        """保留生产计时器的点击冷却，避免回放掩盖连击或冷却漏判。"""
        detected = button.name in self.device.image
        if interval:
            timer = self.campaign.interval_timer.setdefault(button.name, Timer(interval))
            if not timer.reached():
                return False
            if detected:
                timer.reset()
        return detected

    def make_campaign(self, cls=GemsCampaignOverride, policy='withdraw_stop'):
        campaign = object.__new__(cls)
        campaign.config = SimpleNamespace(
            Campaign_DefeatWithdraw=policy, Campaign_Mode='normal',
            FLEET_2=True, Fleet_FleetOrder='fleet1_all_fleet2_standby',
            Submarine_Fleet=0, Fleet_Fleet1Mode='combat_auto', Fleet_Fleet2Mode='combat_auto',
            BUTTON_OFFSET=(30, 30), MAP_IS_ONE_TIME_STAGE=False, modified={},
            cross_get=lambda path, default=None: default)
        campaign.device = self.device
        campaign.emotion = Mock(is_calculate=True)
        campaign.map_is_auto_search = True
        campaign.interval_timer = {}
        campaign._defeat_count = 0
        campaign._hot_fix_check_wait = Timer(6)
        campaign._auto_search_in_stage_timer = Timer(3, count=6)
        campaign.appear = Mock(side_effect=self.appear)
        # 补点 handler 用模板 + 颜色双确认，回放里只看按钮是否在画面中。
        campaign.match_template_color = Mock(
            side_effect=lambda button, offset=0, interval=0, similarity=0.85, threshold=30:
            button.name in self.device.image)
        campaign.is_combat_executing = Mock(side_effect=lambda: 'COMBAT' in self.device.image)
        campaign.is_combat_loading = Mock(side_effect=lambda: 'LOADING' in self.device.image)
        campaign.is_in_stage = Mock(side_effect=lambda: 'STAGE' in self.device.image)
        campaign.is_in_auto_search_menu = Mock(
            side_effect=lambda: AUTO_SEARCH_MENU_EXIT.name in self.device.image)

        def handle_in_stage():
            if campaign.is_in_stage():
                raise CampaignEnd('Withdraw')
            return False

        campaign.handle_in_stage = Mock(side_effect=handle_in_stage)
        # 无关的战斗控制与游戏弹窗不参与本组回放；结算、委托与自律处理使用真实代码。
        for name in (
            'handle_combat_automation_confirm', 'handle_combat_low_emotion', 'handle_retirement',
            'handle_submarine_call', 'handle_combat_auto', 'handle_combat_manual',
            'handle_popup_confirm', 'handle_story_skip', 'handle_guild_popup_cancel',
            'handle_vote_popup', 'handle_mission_popup_ack', 'handle_get_ship', 'handle_get_items',
        ):
            setattr(campaign, name, Mock(return_value=False))
        self.campaign = campaign
        return campaign

    def run(self, **kwargs):
        with patch('module.base.timer.time', side_effect=lambda: self.time):
            return self.campaign.auto_search_combat(**kwargs)


def retreat_frames(*prefix):
    """地图按钮连续稳定后点击撤退，最后用选关页正向确认退出。"""
    return [*prefix, *[screen(WITHDRAW, AUTO_SEARCH_MAP_OPTION_OFF)] * 5, screen('STAGE')]


class AutoSearchDefeatTests(unittest.TestCase):
    def test_logged_defeat_closes_commission_and_retires_instead_of_restarting(self):
        for cls in (AutoSearchCombat, GemsCampaignOverride):
            for policy in ('withdraw_continue', 'withdraw_stop'):
                with self.subTest(cls=cls.__name__, policy=policy):
                    replay = ScreenReplay(retreat_frames(
                        screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D), screen(GET_MISSION)))
                    campaign = replay.make_campaign(cls, policy)
                    with self.assertRaises(CampaignEnd):
                        replay.run(fleet_index=2)
                    self.assertIn(GET_MISSION.name, replay.clicks)
                    self.assertIn(WITHDRAW.name, replay.clicks)
                    self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                    self.assertEqual(campaign._defeat_count, int(policy == 'withdraw_stop'))
                    self.assertEqual(campaign.emotion.reduce.call_args_list, [call(2), call(2, shipwreck=True)])
                    self.assertTrue(campaign.is_in_stage())

    def test_execute_detects_shipwreck_before_experience_page(self):
        replay = ScreenReplay(retreat_frames(
            screen('COMBAT'), screen(OPTS_INFO_D), screen(EXP_INFO_D), screen(OPTS_INFO_D)))
        campaign = replay.make_campaign()
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertEqual(campaign._defeat_count, 1)
        campaign.emotion.reduce.assert_has_calls([call(1), call(1, shipwreck=True)])
        self.assertEqual(campaign.emotion.reduce.call_count, 2)

    def test_repeated_shipwreck_popup_counts_and_reduces_emotion_once(self):
        replay = ScreenReplay(retreat_frames(
            screen('COMBAT'), screen(EXP_INFO_D), *[screen(OPTS_INFO_D)] * 5))
        campaign = replay.make_campaign()
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertEqual(campaign._defeat_count, 1)
        self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(1, shipwreck=True)])
        self.assertEqual(replay.clicks.count(OPTS_INFO_D.name), 2)

    def test_gems_experience_override_records_defeat_before_dismissing_popup(self):
        for auto in (True, False):
            with self.subTest(auto=auto):
                replay = ScreenReplay([screen(OPTS_INFO_D)])
                campaign = replay.make_campaign()
                campaign.map_is_auto_search = auto
                campaign.combat_result_reset(emotion_reduce=True)
                with patch('module.base.timer.time', side_effect=lambda: replay.time):
                    self.assertTrue(campaign.handle_exp_info())
                self.assertEqual(replay.clicks, [OPTS_INFO_D.name])
                self.assertEqual(campaign._defeat_count, int(auto))
                self.assertEqual(campaign._withdraw, auto)
                self.assertEqual(campaign.emotion.reduce.call_count, 1)

    def test_shipwreck_is_recorded_even_while_click_is_on_cooldown(self):
        replay = ScreenReplay([screen(OPTS_INFO_D)])
        campaign = replay.make_campaign()
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            campaign.interval_reset(OPTS_INFO_D, interval=2)
            self.assertFalse(campaign.handle_combat_defeat())
        self.assertTrue(campaign._withdraw)
        self.assertTrue(campaign.combat_result.defeated)
        self.assertEqual(campaign._defeat_count, 1)
        self.assertEqual(replay.clicks, [])

    def test_defeat_with_ignored_emotion_still_retires(self):
        replay = ScreenReplay(retreat_frames(screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D)))
        campaign = replay.make_campaign()
        with self.assertRaises(CampaignEnd):
            replay.run(emotion_reduce=False)
        campaign.emotion.reduce.assert_not_called()
        self.assertEqual(campaign._defeat_count, 1)

    def test_non_s_emotion_is_not_reduced_again_when_shipwreck_popup_appears(self):
        for grade in (EXP_INFO_A, EXP_INFO_B, EXP_INFO_C):
            with self.subTest(grade=grade.name):
                replay = ScreenReplay(retreat_frames(screen('COMBAT'), screen(grade), screen(OPTS_INFO_D)))
                campaign = replay.make_campaign()
                with self.assertRaises(CampaignEnd):
                    replay.run()
                self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(1, shipwreck=True)])
                self.assertEqual(campaign._defeat_count, 1)

    def test_transient_d_grade_does_not_trigger_retreat_without_shipwreck_popup(self):
        for grade in (BATTLE_STATUS_D, EXP_INFO_D):
            with self.subTest(grade=grade.name):
                replay = ScreenReplay([
                    screen('COMBAT'), screen(grade), screen(EXP_INFO_S), screen(AUTO_SEARCH_MAP_OPTION_ON)])
                campaign = replay.make_campaign()
                campaign._defeat_count = 2
                replay.run()
                self.assertFalse(campaign._withdraw)
                self.assertEqual(campaign._defeat_count, 0)
                campaign.emotion.reduce.assert_called_once_with(1)
                self.assertNotIn(WITHDRAW.name, replay.clicks)

    def test_settlement_timeout_does_not_invent_defeat(self):
        replay = ScreenReplay([
            screen('COMBAT'), *[screen()] * 12, screen(EXP_INFO_S), screen(AUTO_SEARCH_MAP_OPTION_ON)])
        campaign = replay.make_campaign()
        replay.run()
        self.assertFalse(campaign._withdraw)
        self.assertEqual(campaign._defeat_count, 0)
        campaign.emotion.reduce.assert_called_once_with(1)
        self.assertNotIn(WITHDRAW.name, replay.clicks)

    def test_map_option_requires_two_frames_before_clicking_off(self):
        replay = ScreenReplay([screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)])
        campaign = replay.make_campaign()
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            # 同一张截图反复检查只累计一次确认，不能触发点击。
            for _ in range(3):
                self.assertFalse(campaign.handle_auto_search_map_option())
            self.assertEqual(replay.clicks, [])
            # 换一张截图后确认成立，按原有冷却点击一次。
            replay.time += 10
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)
            self.assertTrue(campaign.handle_auto_search_map_option())
            self.assertEqual(replay.clicks, [AUTO_SEARCH_MAP_OPTION_OFF.name])
            # 中间出现 ON 会清空累计确认，之后的第一张 OFF 只能重新被视为首帧。
            replay.time += 10
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)
            self.assertFalse(campaign.handle_auto_search_map_option())
            replay.time += 10
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_2)
            self.assertFalse(campaign.handle_auto_search_map_option())
            self.assertIsNone(campaign._auto_search_off_frame)
            replay.time += 10
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)
            self.assertFalse(campaign.handle_auto_search_map_option())
            self.assertEqual(replay.clicks.count(AUTO_SEARCH_MAP_OPTION_OFF.name), 1)
            # 第二张 OFF 才再次点击。
            replay.time += 10
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)
            self.assertTrue(campaign.handle_auto_search_map_option())
            self.assertEqual(replay.clicks.count(AUTO_SEARCH_MAP_OPTION_OFF.name), 2)

    def test_resume_guard_drops_confirmation_after_on(self):
        """续接期间识别到 ON 后重新累计，避免 OFF→ON→OFF 被当成连续两帧。"""
        replay = ScreenReplay([screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)])
        campaign = replay.make_campaign()
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            # 计时器在流程内启动，必须与回放共用同一时间源。
            campaign.prepare_auto_search_recovery('map')
            campaign.auto_search_watch_fleet = Mock()
            campaign._auto_search_fleet_confirmed = True
            replay.time += 5
            self.assertFalse(campaign.handle_auto_search_map_option())
            replay.time += 5
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_2)
            self.assertFalse(campaign.handle_auto_search_map_option())
            replay.time += 5
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)
            self.assertFalse(campaign.handle_auto_search_map_option())
            replay.time += 5
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)
            self.assertTrue(campaign.handle_auto_search_map_option())
        self.assertEqual(replay.clicks.count(AUTO_SEARCH_MAP_OPTION_OFF.name), 1)

    def test_resume_guard_drops_confirmation_after_interrupted_frame(self):
        """空白、加载和战斗帧均打断确认，包括残留 OFF 按钮的转场帧。"""
        transitions = ((), ('LOADING',), ('COMBAT',),
                       ('LOADING', AUTO_SEARCH_MAP_OPTION_OFF),
                       ('COMBAT', AUTO_SEARCH_MAP_OPTION_OFF))
        for transition in transitions:
            with self.subTest(transition=transition):
                replay = ScreenReplay([
                    screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2), screen(*transition),
                    screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2),
                    screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2),
                ])
                campaign = replay.make_campaign()
                with patch('module.base.timer.time', side_effect=lambda: replay.time):
                    campaign.prepare_auto_search_recovery('map')
                    campaign.auto_search_watch_fleet = Mock()
                    campaign._auto_search_fleet_confirmed = True
                    campaign.fleet_show_index = 2
                    replay.time += 5
                    self.assertFalse(campaign.handle_auto_search_map_option())
                    self.assertIsNotNone(campaign._auto_search_off_frame)
                    replay.screenshot()
                    self.assertFalse(campaign.handle_auto_search_map_option())
                    self.assertIsNone(campaign._auto_search_off_frame)
                    replay.screenshot()
                    self.assertFalse(campaign.handle_auto_search_map_option())
                    self.assertEqual(replay.clicks, [])
                    # 同一张截图多次检查不算新的确认。
                    self.assertFalse(campaign.handle_auto_search_map_option())
                    replay.screenshot()
                    self.assertTrue(campaign.handle_auto_search_map_option())
                self.assertEqual(replay.click_frames, [(3, AUTO_SEARCH_MAP_OPTION_OFF.name)])
                campaign.emotion.check_fleet.assert_called_once_with(2, after_restart=True)

    def test_resume_entry_drops_confirmation_from_previous_flow(self):
        """续接入口复位重启前的确认，新流程仍需两帧才点击。"""
        replay = ScreenReplay([screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)])
        campaign = replay.make_campaign()
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            self.assertFalse(campaign.handle_auto_search_map_option())
            self.assertIsNotNone(campaign._auto_search_off_frame)
            campaign.prepare_auto_search_recovery('map')
            self.assertIsNone(campaign._auto_search_off_frame)
            campaign.auto_search_watch_fleet = Mock()
            campaign._auto_search_fleet_confirmed = True
            replay.time += 5
            self.assertFalse(campaign.handle_auto_search_map_option())
            replay.time += 5
            replay.device.image = screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2)
            self.assertTrue(campaign.handle_auto_search_map_option())
        self.assertEqual(replay.clicks.count(AUTO_SEARCH_MAP_OPTION_OFF.name), 1)

    def test_matching_on_template_cannot_toggle_or_cancel_pending_retreat(self):
        for policy in ('withdraw_continue', 'withdraw_stop'):
            with self.subTest(policy=policy):
                replay = ScreenReplay(retreat_frames(
                    screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D),
                    screen(AUTO_SEARCH_MAP_OPTION_ON), screen(GET_MISSION)))
                campaign = replay.make_campaign(policy=policy)
                campaign._defeat_count = 2
                expected = ScriptEnd if policy == 'withdraw_stop' else CampaignEnd
                with self.assertRaises(expected):
                    replay.run()
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_ON.name, replay.clicks)
                self.assertIn(WITHDRAW.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                self.assertEqual(campaign._defeat_count, 3 if policy == 'withdraw_stop' else 2)

    def test_commission_after_withdraw_click_is_still_handled(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D),
            *[screen(WITHDRAW)] * 4, screen(POPUP_CANCEL, POPUP_CONFIRM),
            screen(GET_MISSION), screen('STAGE')])
        campaign = replay.make_campaign()
        del campaign.handle_popup_confirm
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertIn('POPUP_CONFIRM_WITHDRAW', replay.clicks)
        self.assertLess(replay.clicks.index(WITHDRAW.name), replay.clicks.index(GET_MISSION.name))
        self.assertTrue(campaign.is_in_stage())

    def test_withdraw_button_flicker_restarts_stability_wait(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D),
            *[screen(WITHDRAW)] * 2, screen(), *[screen(WITHDRAW)] * 4, screen('STAGE')])
        replay.make_campaign()
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertEqual([(index, name) for index, name in replay.click_frames if name == WITHDRAW.name],
                         [(9, WITHDRAW.name)])

    def test_third_defeat_stops_only_after_confirmed_exit(self):
        for exit_screen in ('withdraw', 'menu', 'stage'):
            with self.subTest(exit=exit_screen):
                prefix = [screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D)]
                frames = retreat_frames(*prefix) if exit_screen == 'withdraw' else [
                    *prefix, *([screen(AUTO_SEARCH_MENU_EXIT)] if exit_screen == 'menu' else []), screen('STAGE')]
                replay = ScreenReplay(frames)
                campaign = replay.make_campaign()
                campaign._defeat_count = 2
                with self.assertRaisesRegex(ScriptEnd, 'DefeatWithdraw=withdraw_stop'):
                    replay.run()
                self.assertTrue(campaign.is_in_stage())
                self.assertEqual(campaign._defeat_count, 3)
                self.assertFalse(campaign._withdraw)

    def test_switch_policy_resumes_only_when_requested(self):
        for handoff in ('stopped', 'running'):
            with self.subTest(handoff=handoff):
                frames = [screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D), screen(GET_MISSION),
                          screen(FLEET_UNAVAILABLE, GET_MISSION)]
                if handoff == 'stopped':
                    # 补点需要两帧确认，OFF 必须连续出现在两张截图上。
                    # 两次 screen() 各生成一个对象，复用同一对象不算第二帧。
                    frames.extend([screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2) for _ in range(2)])
                replay = ScreenReplay([*frames, screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_2)])
                campaign = replay.make_campaign(policy='switch_fleet')
                campaign._defeat_count = 2
                del campaign.handle_popup_confirm
                replay.run()
                self.assertIn(FLEET_UNAVAILABLE.name, replay.clicks)
                if handoff == 'stopped':
                    self.assertIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                self.assertNotIn(WITHDRAW.name, replay.clicks)
                self.assertNotIn(SWITCH_OVER.name, replay.clicks)
                campaign.emotion.check_fleet.assert_called_once_with(2)
                self.assertFalse(campaign._withdraw)
                self.assertEqual(campaign._defeat_count, 2)

    def test_switch_policy_retires_when_only_one_fleet_survives(self):
        replay = ScreenReplay(retreat_frames(screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D)))
        campaign = replay.make_campaign(policy='switch_fleet')
        campaign.config.FLEET_2 = False
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertIn(WITHDRAW.name, replay.clicks)
        self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)

    def test_automatic_handoff_ignores_manual_switch_controls_and_handles_commission(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D), screen(FLEET_UNAVAILABLE),
            *[screen(WITHDRAW, FLEET_NUM_1, SWITCH_OVER)] * 5, screen(GET_MISSION),
            screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2), screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_2),
            screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_2)])
        campaign = replay.make_campaign(policy='switch_fleet')
        replay.run()
        self.assertNotIn(SWITCH_OVER.name, replay.clicks)
        self.assertIn(GET_MISSION.name, replay.clicks)
        self.assertIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
        self.assertNotIn(WITHDRAW.name, replay.clicks)
        self.assertFalse(campaign._withdraw)

    def test_failed_switch_falls_back_to_retreat_without_restarting(self):
        for failure in ('no_popup', 'timeout'):
            with self.subTest(failure=failure):
                prefix = [screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D)]
                if failure == 'timeout':
                    prefix.extend([screen(FLEET_UNAVAILABLE), *[screen(WITHDRAW, FLEET_NUM_1)] * 25])
                replay = ScreenReplay(retreat_frames(*prefix, screen(AUTO_SEARCH_MAP_OPTION_ON)))
                campaign = replay.make_campaign(policy='switch_fleet')
                del campaign.handle_popup_confirm
                with self.assertRaises(CampaignEnd):
                    replay.run()
                self.assertIn(WITHDRAW.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_ON.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                self.assertNotIn('POPUP_CONFIRM_combat_status', replay.clicks)
                self.assertNotIn(SWITCH_OVER.name, replay.clicks)

    def test_victory_between_defeats_resets_consecutive_count(self):
        loss = retreat_frames(screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D))
        replay = ScreenReplay(loss)
        campaign = replay.make_campaign()
        for expected in (1, 2):
            replay.load(loss)
            with self.assertRaises(CampaignEnd):
                replay.run()
            self.assertEqual(campaign._defeat_count, expected)
        replay.load([screen('COMBAT'), screen(EXP_INFO_S), screen(AUTO_SEARCH_MAP_OPTION_ON)])
        replay.run()
        self.assertEqual(campaign._defeat_count, 0)
        replay.load(loss)
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertEqual(campaign._defeat_count, 1)

    def test_retreat_errors_reach_existing_recovery(self):
        replay = ScreenReplay(retreat_frames(screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D)))
        campaign = replay.make_campaign()
        def click(button):
            if button == WITHDRAW:
                raise GameStuckError('测试撤退异常')
            replay.click(button)

        campaign.device.click.side_effect = click
        with self.assertRaises(GameStuckError):
            replay.run()
        self.assertTrue(campaign._withdraw)

    def test_runner_disables_task_after_three_real_defeats(self):
        frames = retreat_frames(screen('COMBAT'), screen(EXP_INFO_D), screen(OPTS_INFO_D), screen(GET_MISSION))
        replay = ScreenReplay(frames)
        campaign = replay.make_campaign()

        def battle():
            replay.load(frames)
            try:
                campaign.auto_search_combat()
            except CampaignEnd:
                return True

        campaign.run = Mock(side_effect=battle)
        campaign.is_in_map = Mock(return_value=False)
        campaign.ensure_campaign_ui = Mock()
        campaign.event_time_limit_triggered = Mock(return_value=False)
        campaign.get_event_pt_limit = Mock(return_value=0)
        campaign.ensure_auto_search_exit = Mock()
        runner = object.__new__(CampaignRun)
        runner.config = SimpleNamespace(
            Scheduler_Enable=True, StopCondition_RunCount=0, StopCondition_MapAchievement='non_stop',
            modified={}, override=Mock(), task_switched=Mock(return_value=False))
        runner.device = replay.device
        runner.campaign = campaign
        runner.stage = '2-4'
        runner.handle_stage_name = Mock(return_value=('2-4', 'campaign_main'))
        runner.load_campaign = Mock()
        runner.ui_page_appear = Mock(return_value=False)
        runner.disable_raid_on_event = Mock()
        runner.handle_commission_notice = Mock()
        runner.triggered_stop_condition = Mock(return_value=False)
        runner.after_campaign_run = Mock()
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            runner._run('2-4', total=5)
        self.assertEqual(campaign.run.call_count, 3)
        self.assertFalse(runner.config.Scheduler_Enable)
        self.assertEqual(campaign._defeat_count, 3)
        self.assertTrue(campaign.is_in_stage())


class FleetHandoffTests(unittest.TestCase):
    def test_main_loop_charges_actual_successor_in_both_fleet_orders(self):
        orders = ((1, 'fleet1_all_fleet2_standby'), (2, 'fleet1_standby_fleet2_all'),
                  (1, 'fleet1_mob_fleet2_boss'), (2, 'fleet1_boss_fleet2_mob'))
        for first, order in orders:
            for resume_state in ('MAP', 'LOADING', 'COMBAT'):
                with self.subTest(order=order, resume_state=resume_state):
                    original = FLEET_NUM_1 if first == 1 else FLEET_NUM_2
                    target = FLEET_NUM_2 if first == 1 else FLEET_NUM_1
                    last = screen(target, AUTO_SEARCH_MAP_OPTION_ON) if resume_state == 'MAP' else screen(resume_state)
                    replay = ScreenReplay([
                        screen(original, AUTO_SEARCH_MAP_OPTION_ON), screen('COMBAT'),
                        screen(OPTS_INFO_D), screen(FLEET_UNAVAILABLE),
                        screen(target, AUTO_SEARCH_MAP_OPTION_OFF),
                        screen(target, AUTO_SEARCH_MAP_OPTION_OFF), last])
                    campaign = replay.make_campaign(policy='switch_fleet')
                    campaign.config.Fleet_FleetOrder = order
                    campaign.fleet_show_index = first
                    campaign.battle_count = 0
                    campaign._map_battle = 2
                    campaign.auto_search_watch_oil = Mock(return_value=True)
                    campaign.auto_search_watch_coin = Mock(return_value=True)
                    campaign.handle_map_cat_attack = Mock(return_value=False)
                    campaign.lv_get = Mock()
                    with patch('module.base.timer.time', side_effect=lambda: replay.time):
                        campaign.auto_search_execute_a_battle()
                        self.assertEqual(campaign.fleet_show_index, 3 - first)
                        replay.load([last, screen('COMBAT'), screen(EXP_INFO_S),
                                     screen(target, AUTO_SEARCH_MAP_OPTION_ON)])
                        campaign.auto_search_execute_a_battle()
                    self.assertEqual(campaign.emotion.reduce.call_args_list,
                                     [call(first), call(first, shipwreck=True), call(3 - first)])
                    campaign.emotion.check_fleet.assert_called_once_with(3 - first)
                    self.assertFalse(campaign.combat_result.fleet_unavailable)
                    self.assertEqual(campaign.battle_count, 2)

    def test_transition_without_number_preserves_last_confirmed_fleet(self):
        replay = ScreenReplay([screen()])
        campaign = replay.make_campaign()
        campaign.fleet_show_index = 2
        campaign.fleet_current_index = 2
        campaign.lv_get = Mock()
        self.assertFalse(campaign.auto_search_watch_fleet())
        self.assertEqual(campaign.fleet_show_index, 2)
        campaign.lv_get.assert_not_called()
        replay.device.image = screen(FLEET_NUM_1)
        self.assertTrue(campaign.auto_search_watch_fleet())
        self.assertEqual(campaign.fleet_show_index, 1)

    def test_usable_defeated_fleet_retires_even_if_other_number_is_visible(self):
        for cls in (AutoSearchCombat, GemsCampaignOverride):
            for displayed in (FLEET_NUM_1, FLEET_NUM_2):
                with self.subTest(cls=cls.__name__, displayed=displayed.name):
                    replay = ScreenReplay(retreat_frames(
                        screen('COMBAT'), screen(OPTS_INFO_D), screen(EXP_INFO_D),
                        screen(displayed, SWITCH_OVER, AUTO_SEARCH_MAP_OPTION_OFF)))
                    campaign = replay.make_campaign(cls, 'switch_fleet')
                    with self.assertRaises(CampaignEnd):
                        replay.run()
                    self.assertIn(WITHDRAW.name, replay.clicks)
                    self.assertNotIn(SWITCH_OVER.name, replay.clicks)
                    self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                    self.assertNotIn(AUTO_SEARCH_MAP_OPTION_ON.name, replay.clicks)
                    campaign.emotion.check_fleet.assert_not_called()

    def test_handoff_resumes_only_after_unavailable_and_current_target(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(OPTS_INFO_D), screen(FLEET_UNAVAILABLE),
            screen(FLEET_NUM_2), screen(FLEET_NUM_1, AUTO_SEARCH_MAP_OPTION_OFF, SWITCH_OVER),
            screen(FLEET_NUM_2, AUTO_SEARCH_MAP_OPTION_OFF), screen(FLEET_NUM_2, AUTO_SEARCH_MAP_OPTION_OFF),
            screen(FLEET_NUM_2, AUTO_SEARCH_MAP_OPTION_ON)])
        campaign = replay.make_campaign(policy='switch_fleet')
        replay.run()
        self.assertEqual([i for i, name in replay.click_frames if name == AUTO_SEARCH_MAP_OPTION_OFF.name], [6])
        self.assertNotIn(SWITCH_OVER.name, replay.clicks)
        self.assertTrue(campaign.combat_result.fleet_unavailable)
        campaign.emotion.check_fleet.assert_called_once_with(2)

    def test_successor_precheck_failure_retires_before_reraising(self):
        for error in (RequestHumanTakeover('接替舰队未校准'), ScriptEnd('接替舰队心情不足')):
            with self.subTest(error=type(error).__name__):
                replay = ScreenReplay(retreat_frames(
                    screen('COMBAT'), screen(OPTS_INFO_D), screen(FLEET_UNAVAILABLE),
                    screen(FLEET_NUM_2, AUTO_SEARCH_MAP_OPTION_OFF)))
                campaign = replay.make_campaign(policy='switch_fleet')
                campaign.emotion.check_fleet.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    replay.run()
                self.assertIs(caught.exception, error)
                self.assertTrue(campaign.is_in_stage())
                self.assertIn(WITHDRAW.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_ON.name, replay.clicks)
                campaign.emotion.check_fleet.assert_called_once_with(2)

    def test_execute_phase_unavailable_evidence_resets_before_next_battle(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(FLEET_UNAVAILABLE), screen(FLEET_UNAVAILABLE),
            screen(FLEET_NUM_2, AUTO_SEARCH_MAP_OPTION_OFF), screen(FLEET_NUM_2, AUTO_SEARCH_MAP_OPTION_ON)])
        campaign = replay.make_campaign(policy='switch_fleet')
        replay.run()
        self.assertTrue(campaign.combat_result.fleet_unavailable)
        prior_clicks = len(replay.clicks)
        replay.load(retreat_frames(screen('COMBAT'), screen(OPTS_INFO_D),
                                   screen(FLEET_NUM_1, AUTO_SEARCH_MAP_OPTION_OFF, SWITCH_OVER)))
        with self.assertRaises(CampaignEnd):
            replay.run(fleet_index=2)
        self.assertFalse(campaign.combat_result.fleet_unavailable)
        self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks[prior_clicks:])
        self.assertNotIn(SWITCH_OVER.name, replay.clicks[prior_clicks:])

    def test_automatic_handoff_timeout_retires_without_manual_switch(self):
        replay = ScreenReplay(retreat_frames(
            screen('COMBAT'), screen(OPTS_INFO_D), screen(FLEET_UNAVAILABLE),
            *[screen(WITHDRAW, SWITCH_OVER, FLEET_NUM_1, AUTO_SEARCH_MAP_OPTION_OFF)] * 26))
        campaign = replay.make_campaign(policy='switch_fleet')
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertIn(WITHDRAW.name, replay.clicks)
        self.assertNotIn(SWITCH_OVER.name, replay.clicks)
        self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
        self.assertTrue(campaign.combat_result.fleet_unavailable)
        campaign.emotion.check_fleet.assert_not_called()


if __name__ == '__main__':
    unittest.main()
