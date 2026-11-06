"""离线验证大世界自动搜索战斗的经验结算与自律开关过渡保护，不连接真实游戏。"""

import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.timer import Timer
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
    OPTS_INFO_D,
)
from module.exception import CampaignEnd, GameStuckError, GameTooManyClickError
from module.os.fleet import BossFleet, OSFleet
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
C_TIMEOUT_PAGE = load_image(str(FIXTURE_DIR / 'battle_status_c_timeout.png'))


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


class TestBattleStatusTiming(unittest.TestCase):
    """深渊、月度 Boss 直接结算；自动搜索和其他任务保持延迟兜底。"""

    def setUp(self):
        self.clock = VirtualClock()
        time_patch = patch('module.base.timer.time', self.clock)
        time_patch.start()
        self.addCleanup(time_patch.stop)
        for button in (BATTLE_STATUS_S, BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D):
            image_patch = patch.object(
                button, 'appear_on', side_effect=lambda image, button=button, **kwargs: image is button,
            )
            image_patch.start()
            self.addCleanup(image_patch.stop)

    def make_combat(self, task='OpsiAbyssal', bound_task=None, status=BATTLE_STATUS_S):
        combat = Combat.__new__(Combat)
        combat.config = SimpleNamespace(task=SimpleNamespace(command=task), _bind_task_override=bound_task)
        combat.device = Mock(image=status)
        combat.interval_timer = {}
        combat.is_combat_executing = Mock(return_value=False)
        return combat

    def test_boss_s_page_is_clicked_on_first_observation(self):
        for task in ('OpsiAbyssal', 'OpsiMonthBoss'):
            with self.subTest(task=task):
                combat = self.make_combat(task)
                self.assertTrue(combat.handle_battle_status())
                combat.device.click.assert_called_once_with(BATTLE_STATUS_S)

    def test_delegated_boss_uses_the_bound_task(self):
        for task in ('OpsiAbyssal', 'OpsiMonthBoss'):
            with self.subTest(task=task):
                combat = self.make_combat('OpsiScheduling', bound_task=task)
                combat.handle_battle_status()
                combat.device.click.assert_called_once_with(BATTLE_STATUS_S)

    def test_boss_click_keeps_existing_cooldown(self):
        for interval in (2, 7):
            with self.subTest(interval=interval):
                combat = self.make_combat()
                combat.battle_status_click_interval = interval
                self.assertTrue(combat.handle_battle_status())
                self.clock.now += 0.5
                self.assertFalse(combat.handle_battle_status())
                self.assertEqual(combat.device.click.call_count, 1)
                self.clock.now += interval
                self.assertTrue(combat.handle_battle_status())
                self.assertEqual(combat.device.click.call_count, 2)

    def test_boss_drop_is_captured_before_click(self):
        combat = self.make_combat()
        actions = []
        drop = Mock(handle_add=Mock(side_effect=lambda *args: actions.append('capture')))
        combat.device.click.side_effect = lambda *args: actions.append('click')
        combat.handle_battle_status(drop=drop)
        self.assertEqual(actions, ['capture', 'click'])
        drop.handle_add.assert_called_once_with(combat)

    def test_boss_battle_or_unrecognized_frame_is_not_clicked(self):
        combat = self.make_combat()
        combat.is_combat_executing.return_value = True
        self.assertFalse(combat.handle_battle_status())
        combat.is_combat_executing.return_value = False
        combat.device.image = BLANK_IMAGE
        self.assertFalse(combat.handle_battle_status())
        combat.device.click.assert_not_called()

    def test_other_tasks_keep_twenty_second_s_delay(self):
        for task, bound_task in (('OpsiObscure', None), ('OpsiStronghold', None),
                                 ('OpsiScheduling', 'OpsiObscure')):
            with self.subTest(task=task, bound_task=bound_task):
                combat = self.make_combat(task, bound_task)
                self.assertTrue(combat.handle_battle_status())
                self.clock.now += 19.9
                self.assertTrue(combat.handle_battle_status())
                combat.device.click.assert_not_called()
                self.clock.now += 0.2
                self.assertTrue(combat.handle_battle_status())
                combat.device.click.assert_called_once_with(BATTLE_STATUS_S)

    def test_auto_search_keeps_twenty_second_s_delay_for_all_tasks(self):
        for task in ('OpsiAbyssal', 'OpsiMonthBoss', 'OpsiHazard1Leveling'):
            with self.subTest(task=task):
                combat = self.make_combat(task)
                timer = Timer(combat.battle_status_s_autoclick_delay)
                self.assertFalse(combat.handle_auto_search_battle_status(battle_status_s_timer=timer))
                self.clock.now += 19.9
                self.assertFalse(combat.handle_auto_search_battle_status(battle_status_s_timer=timer))
                combat.device.click.assert_not_called()
                self.clock.now += 0.2
                self.assertTrue(combat.handle_auto_search_battle_status(battle_status_s_timer=timer))
                combat.device.click.assert_called_once_with(BATTLE_STATUS_S)

    def test_other_ranks_remain_immediate(self):
        for task in ('OpsiAbyssal', 'OpsiMonthBoss', 'OpsiObscure'):
            for status in (BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D):
                with self.subTest(task=task, status=status.name):
                    combat = self.make_combat(task, status=status)
                    self.assertTrue(combat.handle_battle_status())
                    combat.device.click.assert_called_once_with(status)


class TestPreparationResultHandoff(unittest.TestCase):
    """漏识别战斗执行界面时，准备阶段仍能把明确战果页交给原结算流程。"""

    def make_combat(self, image=C_TIMEOUT_PAGE):
        combat = Combat.__new__(Combat)
        combat.config = SimpleNamespace(
            SERVER='cn', task=SimpleNamespace(command='OpsiAbyssal'),
            campaign_name='opsi-preparation-test', DropRecord_CombatRecord='do_not',
        )
        combat.device = Mock(image=image)
        combat.interval_timer = {}
        combat.stat = Mock()
        combat.stat.new.return_value = nullcontext(None)
        for name in (
            'handle_retirement', 'handle_popup_confirm', 'handle_combat_automation_confirm',
            'handle_story_skip', 'handle_combat_auto', 'handle_combat_manual',
            'handle_submarine_call', 'handle_urgent_commission', 'handle_guild_popup_cancel',
            'handle_vote_popup', 'handle_mission_popup_ack', 'handle_get_ship',
            'handle_auto_search_exit', 'handle_combat_mis_click', 'handle_in_stage',
        ):
            setattr(combat, name, Mock(return_value=False))
        for name in ('submarine_call_reset', 'combat_auto_reset', 'combat_manual_reset'):
            setattr(combat, name, Mock())
        pending_frames = []
        combat.device.click.side_effect = lambda button: pending_frames.append(BLANK_IMAGE)

        def screenshot():
            if pending_frames:
                combat.device.image = pending_frames.pop(0)

        combat.device.screenshot.side_effect = screenshot

        def frames():
            yield
            for _ in range(2):
                combat.device.screenshot()
                yield
            raise AssertionError('已显示战果页或返回地图，状态循环仍未交接')

        combat.loop = frames
        return combat

    def test_actual_c_page_is_recognized_without_a_running_battle(self):
        combat = self.make_combat()
        self.assertTrue(BATTLE_STATUS_C.appear_on(C_TIMEOUT_PAGE))
        self.assertFalse(combat.is_combat_executing())
        self.assertFalse(combat.appear(OPTS_INFO_D, offset=(30, 30)))

    def test_preparation_hands_off_c_page_without_clicking_it(self):
        combat = self.make_combat()
        combat.combat_preparation()
        combat.device.click.assert_not_called()
        combat.device.screenshot.assert_not_called()

    def test_actual_c_page_completes_full_combat_after_missing_running_state(self):
        combat = self.make_combat()
        combat.combat(
            balance_hp=False, emotion_reduce=False, auto_mode='combat_auto',
            submarine_mode='do_not_use', save_get_items=False,
            expected_end=lambda: combat.device.image is BLANK_IMAGE,
        )
        combat.device.click.assert_called_once_with(BATTLE_STATUS_C)
        self.assertIs(combat.device.image, BLANK_IMAGE)
        self.assertIsNone(combat.combat_result.rank)

    def test_existing_defeat_page_also_hands_off_and_keeps_failure(self):
        image = load_image(str(FIXTURE_DIR.parent / 'combat_defeat' / 'defeat.png'))
        combat = self.make_combat(image)
        combat.combat(
            balance_hp=False, emotion_reduce=False, auto_mode='combat_auto',
            submarine_mode='do_not_use', save_get_items=False,
            expected_end=lambda: combat.device.image is BLANK_IMAGE,
        )
        combat.device.click.assert_called_once_with(OPTS_INFO_D)
        self.assertTrue(combat.combat_result.defeated)

    def test_c_result_keeps_boss_fleet_rotation_until_map_confirms_clear(self):
        combat = self.make_combat()
        combat.config.DropRecord_OpsiAbyssal = 'do_not'
        drop = SimpleNamespace(count=0)
        combat.stat.new.side_effect = lambda **kwargs: nullcontext(drop)
        fleets = [BossFleet(1), BossFleet(2)]
        fleets[0].standby_loca = (-1, -1)
        combat.parse_fleet_filter = Mock(return_value=fleets)
        combat.handle_os_map_fleet_lock = Mock()
        combat.fleet_low_resolve_appear = Mock(return_value=False)
        combat.predict_radar = Mock()
        combat.radar = Mock(select=Mock(return_value=[]))
        combat.boss_leave = Mock()
        combat.map_exit = Mock()
        current_fleet = [0]
        attacked = []

        def switch(index):
            current_fleet[0] = index
            return True

        def attack(location, **kwargs):
            if location != (0, 0):
                return
            attacked.append(current_fleet[0])
            if current_fleet[0] == 1:
                combat.combat(
                    balance_hp=False, emotion_reduce=False, auto_mode='combat_auto',
                    submarine_mode='do_not_use', save_get_items=False,
                    expected_end=lambda: combat.device.image is BLANK_IMAGE,
                )
            else:
                combat.radar.select.return_value = [object()]

        combat.fleet_set = Mock(side_effect=switch)
        combat.boss_goto = Mock(side_effect=attack)
        self.assertTrue(OSFleet.boss_clear(combat, allow_submarine_call=False))
        self.assertEqual(attacked, [1, 2])
        combat.device.click.assert_called_once_with(BATTLE_STATUS_C)
        combat.boss_leave.assert_called_once_with()
        combat.map_exit.assert_called_once_with(drop=drop)

    def test_normal_running_state_still_ends_preparation(self):
        combat = self.make_combat(BLANK_IMAGE)
        combat.is_combat_executing = Mock(return_value=True)
        combat.combat_preparation()
        combat.device.click.assert_not_called()
        combat.device.screenshot.assert_not_called()

    def test_map_and_popup_frames_do_not_end_preparation(self):
        fixture_paths = [
            *(FIXTURE_DIR.parent / 'opsi_abyssal_resume').glob('*.png'),
            FIXTURE_DIR.parent / 'combat_defeat' / 'map_fleet2.png',
            FIXTURE_DIR.parent / 'combat_defeat' / 'unavailable.png',
        ]
        for path in fixture_paths:
            with self.subTest(frame=path.name):
                combat = self.make_combat(load_image(str(path)))
                combat.is_combat_executing = Mock(side_effect=[False, True])
                combat.combat_preparation()
                self.assertEqual(combat.is_combat_executing.call_count, 2)

    def test_c_colored_transition_is_not_a_result_page(self):
        image = np.full((720, 1280, 3), BATTLE_STATUS_C.color, dtype=np.uint8)
        self.assertTrue(BATTLE_STATUS_C.appear_on(image))
        combat = self.make_combat(image)
        combat.is_combat_executing = Mock(side_effect=[False, True])
        combat.combat_preparation()
        self.assertEqual(combat.is_combat_executing.call_count, 2)


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
            stop_event=None,
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

    def test_cooldown_frames_do_not_clear_failed_enable_budget(self):
        for command in ('OpsiExplore', 'OpsiHazard1Leveling', 'OpsiMeowfficerFarming'):
            for state in (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED):
                with self.subTest(command=command, state=state.name):
                    handler = self.make_map(command, state)
                    started = self.clock.now

                    def frames():
                        for _ in range(300):
                            yield
                            self.clock.now += 0.2

                    handler.loop = frames
                    with self.assertRaisesRegex(GameTooManyClickError, '连续点击 45 秒仍未生效'):
                        handler.os_auto_search_daemon()
                    self.assertGreater(self.clock.now - started, 45)
                    self.assertLess(self.clock.now - started, 49)
                    self.assertGreater(handler.device.click.call_count, 1)

    def test_brief_unrecognized_frames_do_not_restart_enable_budget(self):
        handler = self.make_map('OpsiHazard1Leveling')
        started = self.clock.now

        def frames():
            for frame in range(300):
                handler.state = None if frame % 5 == 4 else AUTO_SEARCH_OS_MAP_OPTION_OFF
                yield
                self.clock.now += 0.2

        handler.loop = frames
        with self.assertRaisesRegex(GameTooManyClickError, '连续点击 45 秒仍未生效'):
            handler.os_auto_search_daemon()
        self.assertLess(self.clock.now - started, 47)

    def test_five_minute_limit_also_checks_frames_that_click_auto_search(self):
        for frame_interval in (0.2, 3.1):
            with self.subTest(frame_interval=frame_interval):
                handler = self.make_map('OpsiHazard1Leveling')
                handler.config.OpsiGeneral_AutoSearchTimeLimit = 5
                # 单独验证五分钟保护，不让更短的开启重试预算先结束本轮。
                handler._os_auto_search_enable_timeout = 600
                started = self.clock.now

                def frames():
                    for _ in range(1600):
                        yield
                        self.clock.now += frame_interval

                handler.loop = frames
                with self.assertRaisesRegex(GameStuckError, '自律寻敌卡死'):
                    handler.os_auto_search_daemon()
                self.assertGreater(self.clock.now - started, 300)
                self.assertLess(self.clock.now - started, 304)
                self.assertGreater(handler.device.click.call_count, 1)

    def test_real_progress_still_resets_search_time_limit(self):
        for progress in ('combat', 'retirement', 'map_event'):
            with self.subTest(progress=progress):
                handler = self.make_map(state=AUTO_SEARCH_OS_MAP_OPTION_ON)
                handler.config.OpsiGeneral_AutoSearchTimeLimit = 5
                handler.on_auto_search_battle_count_add = Mock()
                handler.auto_search_combat = Mock(return_value=True)
                started = self.clock.now
                progressed = False

                def has_progress(*args, **kwargs):
                    nonlocal progressed
                    if not progressed and self.clock.now - started >= 240:
                        progressed = True
                        return True
                    return False

                target = {
                    'combat': 'combat_appear',
                    'retirement': 'handle_retirement',
                    'map_event': 'handle_map_event',
                }[progress]
                setattr(handler, target, Mock(side_effect=has_progress))

                def frames():
                    for _ in range(120):
                        yield
                        self.clock.now += 3.1

                handler.loop = frames
                self.assertEqual(handler.os_auto_search_daemon(), int(progress == 'combat'))
                self.assertTrue(progressed)
                self.assertGreater(self.clock.now - started, 300)

    def test_delayed_reward_still_resets_both_search_and_enable_budgets(self):
        handler = self.make_map('OpsiHazard1Leveling')
        handler.config.OpsiGeneral_AutoSearchTimeLimit = 5

        def close_reward(**kwargs):
            handler.state = AUTO_SEARCH_OS_MAP_OPTION_OFF
            return False

        handler.os_auto_search_quit = Mock(side_effect=close_reward)

        def frames():
            yield
            self.clock.now += 301
            handler.state = AUTO_SEARCH_REWARD
            yield
            self.clock.now += 1
            yield

        handler.loop = frames
        self.assertEqual(handler.os_auto_search_daemon(), 0)
        handler.os_auto_search_quit.assert_called_once_with(drop=None)
        self.assertEqual(handler.device.click.call_count, 2)


if __name__ == '__main__':
    unittest.main()
