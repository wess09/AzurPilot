"""离线验证大世界自动搜索战斗的经验结算与自律开关过渡保护，不连接真实游戏。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.combat.assets import (
    BATTLE_STATUS_A,
    BATTLE_STATUS_B,
    BATTLE_STATUS_C,
    BATTLE_STATUS_D,
    BATTLE_STATUS_S,
    EXP_INFO_A,
    EXP_INFO_B,
    EXP_INFO_C,
    EXP_INFO_D,
    EXP_INFO_S,
)
from module.exception import CampaignEnd, GameTooManyClickError
from module.os.map import OSMap
from module.os_combat.combat import Combat
from module.os_handler.assets import (
    AUTO_SEARCH_OS_MAP_OPTION_OFF,
    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
    AUTO_SEARCH_OS_MAP_OPTION_ON,
    AUTO_SEARCH_REWARD,
)
from tests.test_opsi_cl1_speed import AutoSearchStateStub, VirtualClock

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'opsi_auto_search'
EXPERIENCE_PAGE = load_image(str(FIXTURE_DIR / 'exp_info_s.png'))
BLANK_IMAGE = np.zeros((720, 1280, 3), dtype=np.uint8)


class TestExperiencePageFixture(unittest.TestCase):
    """确认脱敏故障截图仍被正式识别器当成经验结算页。"""

    def test_fixture_is_recognized_as_experience_information(self):
        self.assertTrue(EXP_INFO_S.appear_on(EXPERIENCE_PAGE))
        for button in (EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D):
            with self.subTest(button=button.name):
                self.assertFalse(button.appear_on(EXPERIENCE_PAGE))

    def test_fixture_is_not_recognized_as_battle_status(self):
        for button in (
            BATTLE_STATUS_S,
            BATTLE_STATUS_A,
            BATTLE_STATUS_B,
            BATTLE_STATUS_C,
            BATTLE_STATUS_D,
        ):
            with self.subTest(button=button.name):
                self.assertFalse(button.appear_on(EXPERIENCE_PAGE))


class TestAutoSearchExperienceClick(unittest.TestCase):
    """验证经验结算页的点击冷却，避免同一页面被连点或长时间休眠。"""

    def setUp(self):
        self.clock = VirtualClock()
        time_patch = patch('module.base.timer.time', self.clock)
        time_patch.start()
        self.addCleanup(time_patch.stop)

    def make_combat(self, image):
        combat = Combat.__new__(Combat)
        combat.device = Mock()
        combat.device.image = image
        combat.interval_timer = {}
        combat._clear_battle_status_s_timer = Mock()
        return combat

    def test_experience_page_is_confirmed_by_click(self):
        combat = self.make_combat(EXPERIENCE_PAGE)
        self.assertTrue(combat.handle_auto_search_exp_info())
        combat.device.click.assert_called_once_with(EXP_INFO_S)
        combat._clear_battle_status_s_timer.assert_called_once_with()

    def test_same_page_is_not_clicked_twice_within_cooldown(self):
        combat = self.make_combat(EXPERIENCE_PAGE)
        self.assertTrue(combat.handle_auto_search_exp_info())
        self.clock.now += 0.5
        self.assertFalse(combat.handle_auto_search_exp_info())
        self.assertEqual(combat.device.click.call_count, 1)
        # 冷却结束后页面仍在时允许再次确认，由下一张截图判断是否已关闭
        self.clock.now += 2.0
        self.assertTrue(combat.handle_auto_search_exp_info())
        self.assertEqual(combat.device.click.call_count, 2)

    def test_blank_frame_is_not_clicked(self):
        combat = self.make_combat(BLANK_IMAGE)
        self.assertFalse(combat.handle_auto_search_exp_info())
        combat.device.click.assert_not_called()


class TestAutoSearchCombatExperienceSettlement(unittest.TestCase):
    """验证战斗结算页在关闭自动修理时仍会被确认并回到地图。"""

    def setUp(self):
        self.clock = VirtualClock()
        time_patch = patch('module.base.timer.time', self.clock)
        time_patch.start()
        self.addCleanup(time_patch.stop)
        start_timer_patch = patch('module.os_combat.combat.start_battle_timer', return_value='cl1')
        start_timer_patch.start()
        self.addCleanup(start_timer_patch.stop)
        finish_timer_patch = patch('module.os_combat.combat.finish_battle_timer')
        finish_timer_patch.start()
        self.addCleanup(finish_timer_patch.stop)

    def make_combat(self, repair_threshold):
        combat = Combat.__new__(Combat)
        combat.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiHazard1Leveling'),
            OpsiGeneral_RepairThreshold=repair_threshold,
            Submarine_Fleet=0,
        )
        frames = [BLANK_IMAGE, EXPERIENCE_PAGE, BLANK_IMAGE]
        combat.device = Mock(image=BLANK_IMAGE)

        def screenshot():
            combat.device.image = frames.pop(0) if frames else BLANK_IMAGE

        combat.device.screenshot.side_effect = screenshot
        combat.interval_timer = {}
        combat.handle_background_coin_interrupt = Mock(return_value=False)
        combat.handle_combat_automation_confirm = Mock(return_value=False)
        combat.handle_os_auto_search_map_option = Mock(side_effect=[True, False, False])
        combat.handle_submarine_call = Mock(return_value=False)
        combat.submarine_call_reset = Mock()
        combat.is_combat_executing = Mock(return_value=False)
        combat.is_in_map = Mock(side_effect=[False, True])
        combat.handle_auto_search_battle_status = Mock(return_value=False)
        combat.handle_map_event = Mock(return_value=False)
        combat._clear_battle_status_s_timer = Mock()
        return combat

    def test_experience_page_is_settled_when_repair_is_disabled(self):
        for threshold in (0, -1):
            with self.subTest(threshold=threshold):
                combat = self.make_combat(threshold)
                self.assertIsNone(combat.auto_search_combat())
                combat.device.click.assert_called_once_with(EXP_INFO_S)
                self.assertIn('_os_auto_search_battle_settle_timer', combat.__dict__)

    def test_experience_page_is_still_settled_when_repair_is_enabled(self):
        combat = self.make_combat(0.4)
        self.assertIsNone(combat.auto_search_combat())
        combat.device.click.assert_called_once_with(EXP_INFO_S)


class TestPostBattleSettleWindow(unittest.TestCase):
    """验证战斗结算回到地图的过渡窗口内不操作自律开关。"""

    def setUp(self):
        self.clock = VirtualClock()
        self.handler = AutoSearchStateStub()
        time_patch = patch('module.base.timer.time', self.clock)
        time_patch.start()
        self.addCleanup(time_patch.stop)
        for button in (
            AUTO_SEARCH_OS_MAP_OPTION_OFF,
            AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
            AUTO_SEARCH_OS_MAP_OPTION_ON,
        ):
            state_patch = patch.object(
                button, 'match_template_color',
                side_effect=lambda *a, button=button, **k: self.handler.state is button,
            )
            state_patch.start()
            self.addCleanup(state_patch.stop)

    def test_toggle_is_not_clicked_until_settle_window_ends(self):
        # 故障日志：战斗结束后 0.5 秒内两次点击同一开关，第二次把自律寻敌点停。
        self.handler._os_auto_search_battle_settle_start()
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_not_called()
        self.clock.now += 0.5
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_not_called()
        self.clock.now += 1.6
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_called_once_with(AUTO_SEARCH_OS_MAP_OPTION_OFF)

    def test_settle_window_is_rearmed_by_the_next_battle(self):
        self.handler._os_auto_search_battle_settle_start()
        self.clock.now += 1.5
        self.handler._os_auto_search_battle_settle_start()
        self.clock.now += 1.0
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.clock.now += 1.1
        self.assertTrue(self.handler.handle_os_auto_search_map_option())

    def test_initial_search_start_is_still_immediate(self):
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_called_once_with(AUTO_SEARCH_OS_MAP_OPTION_OFF)

    def test_settle_window_keeps_enable_budget_running(self):
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        budget = self.handler.__dict__['_os_auto_search_enable_timer']
        self.assertTrue(budget.started())
        self.handler._os_auto_search_battle_settle_start()
        self.clock.now += 1.0
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.assertTrue(budget.started())

    def test_settle_window_does_not_block_reward_confirmation(self):
        self.handler.appear = Mock(
            side_effect=lambda button, **kwargs: button is AUTO_SEARCH_REWARD)
        self.handler.os_auto_search_quit = Mock(return_value=False)
        self.handler._os_auto_search_battle_settle_start()
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.handler.os_auto_search_quit.assert_called_once()


class TestAutoSearchRetryBudgetScope(unittest.TestCase):
    """重试预算只属于本次搜索，不累积上一海域的领奖和切图时间。"""

    def setUp(self):
        self.clock = VirtualClock()
        time_patch = patch('module.base.timer.time', self.clock)
        time_patch.start()
        self.addCleanup(time_patch.stop)

    def make_map(self, command='OpsiExplore', state=AUTO_SEARCH_OS_MAP_OPTION_OFF):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(
            task=SimpleNamespace(command=command), OpsiGeneral_AutoSearchTimeLimit=10,
        )
        handler.device = Mock(image=None)
        handler.interval_timer = {}
        handler.state = state
        handler.on_auto_search_battle_count_reset = Mock()
        handler.hp_reset = Mock()
        handler.handle_background_coin_interrupt = Mock(return_value=False)
        handler.is_in_map = Mock(return_value=True)
        handler.info_bar_count = Mock(return_value=0)
        handler.appear = Mock(side_effect=lambda button, **kwargs: button is handler.state)
        handler.os_auto_search_quit = Mock(return_value=True)
        handler.handle_retirement = Mock(return_value=False)
        handler.combat_appear = Mock(return_value=False)
        handler.handle_map_event = Mock(return_value=False)
        handler.loop = Mock(side_effect=lambda: iter([None]))
        for button in (
            AUTO_SEARCH_OS_MAP_OPTION_OFF,
            AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
            AUTO_SEARCH_OS_MAP_OPTION_ON,
        ):
            state_patch = patch.object(
                button, 'match_template_color',
                side_effect=lambda *a, button=button, **k: handler.state is button,
            )
            state_patch.start()
            self.addCleanup(state_patch.stop)
        return handler

    def test_new_search_does_not_inherit_expired_retry_budget(self):
        for command in ('OpsiExplore', 'OpsiObscure', 'OpsiHazard1Leveling', 'OpsiMeowfficerFarming'):
            for state in (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED):
                with self.subTest(command=command, state=state.name):
                    handler = self.make_map(command, state)
                    handler.os_auto_search_daemon()
                    self.clock.now += 60
                    handler.device.click.reset_mock()
                    handler.os_auto_search_daemon()
                    handler.device.click.assert_called_once_with(state)

    def test_next_zone_starts_after_previous_reward(self):
        handler = self.make_map()
        handler.os_auto_search_daemon()
        self.clock.now += 8
        handler.state = AUTO_SEARCH_REWARD
        with self.assertRaises(CampaignEnd):
            handler.handle_os_auto_search_map_option()
        handler.os_auto_search_quit.assert_called_once_with(drop=None)
        self.clock.now += 44
        handler.state = AUTO_SEARCH_OS_MAP_OPTION_OFF
        handler.device.click.reset_mock()
        handler.os_auto_search_daemon()
        handler.device.click.assert_called_once_with(AUTO_SEARCH_OS_MAP_OPTION_OFF)

    def test_continuous_failed_clicks_still_exhaust_current_budget(self):
        handler = self.make_map()

        def frames():
            for _ in range(20):
                yield
                self.clock.now += 3.1

        handler.loop = frames
        with self.assertRaisesRegex(GameTooManyClickError, '自律寻敌连续点击 45 秒仍未生效'):
            handler.os_auto_search_daemon()
        self.assertGreater(handler.device.click.call_count, 1)


if __name__ == '__main__':
    unittest.main()
