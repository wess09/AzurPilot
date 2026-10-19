"""使用虚拟时钟验证大世界剧情及侵蚀1、短猫交互提速，不连接真实游戏。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.exception import CampaignEnd, GameTooManyClickError
from module.handler.assets import STORY_SKIP_3
from module.handler.info_handler import InfoHandler
from module.os.fleet import OSFleet
from module.os.map import OSMap
from module.os_handler.assets import (
    AUTO_SEARCH_OS_MAP_OPTION_OFF,
    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
    AUTO_SEARCH_OS_MAP_OPTION_ON,
)
from module.os_handler.map_event import MapEventHandler
from module.os_shop.assets import PORT_SUPPLY_CHECK
from tests.test_story_option_click import FakeDevice, StoryHandlerStub, make_options


class VirtualClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FastStoryStub(StoryHandlerStub, MapEventHandler):
    appear = ModuleBase.appear

    def __init__(self, options):
        super().__init__(options=options)
        self.device.image = None
        self.device.stuck_record_add = Mock()
        self._story_option_buttons_3 = Mock(return_value=[])
        self.handle_popup_confirm = Mock(return_value=False)
        self.story_popup_timeout = Timer(10)


class TestFastWorldStory(unittest.TestCase):
    def setUp(self):
        self.clock = VirtualClock()
        self.time_patch = patch('module.base.timer.time', self.clock)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    def test_dialogue_uses_skip_even_when_os_initialization_disabled_it(self):
        handler = FastStoryStub(options=[])
        with patch.object(STORY_SKIP_3, 'match', side_effect=lambda *a, **k: handler.story_present):
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
            self.clock.now += 0.35
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
            handler.story_present = False
            self.clock.now += 0.35
            self.assertFalse(handler.story_skip())
        self.assertEqual(handler.device.count_of('STORY_SKIP'), 2)
        self.assertEqual(handler.device.count_of('CLICK_SAFE_AREA'), 0)
        self.assertFalse(handler.config.STORY_ALLOW_SKIP)

    def test_visible_options_are_confirmed_before_clicking_and_never_blank_clicked(self):
        handler = FastStoryStub(options=make_options())
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
            self.clock.now += 0.35
            self.assertFalse(handler.story_skip())
        self.assertEqual(handler.device.count_of('STORY_OPTION_2_OF_3'), 1)
        self.assertEqual(handler.device.count_of('CLICK_SAFE_AREA'), 0)
        self.assertEqual(handler.device.count_of('STORY_SKIP'), 0)

    def test_required_choice_after_skip_is_still_selected(self):
        handler = FastStoryStub(options=[])
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
            handler._options = make_options()
            self.clock.now += 0.35
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
        self.assertEqual(handler.device.count_of('STORY_SKIP'), 1)
        self.assertEqual(handler.device.count_of('STORY_OPTION_2_OF_3'), 1)
        self.assertEqual(handler.device.count_of('CLICK_SAFE_AREA'), 0)

    def test_skip_confirmation_is_processed_before_retrying_skip(self):
        handler = FastStoryStub(options=[])
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            handler.story_skip()
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
            handler.handle_popup_confirm.side_effect = (
                lambda *args, **kwargs: StoryHandlerStub.handle_popup_confirm(handler, *args, **kwargs)
            )
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
        handler.handle_popup_confirm.assert_called_once_with('STORY_SKIP', interval=0.5)
        self.assertEqual(handler.device.count_of('STORY_SKIP'), 1)
        self.assertEqual(handler.device.count_of('POPUP_CONFIRM_STORY_SKIP'), 1)

    def test_switching_world_tasks_keeps_skip_and_fast_cadence(self):
        handler = FastStoryStub(options=[])
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            handler.story_skip()
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
            handler.config.task.command = 'OpsiMeowfficerFarming'
            self.clock.now += 0.35
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
        self.assertEqual(handler.device.count_of('STORY_SKIP'), 2)
        self.assertEqual(handler.device.count_of('CLICK_SAFE_AREA'), 0)
        self.assertFalse(handler.config.STORY_ALLOW_SKIP)

    def test_enabled_skip_uses_skip_button_with_fast_cadence(self):
        handler = FastStoryStub(options=[])
        handler.config.STORY_ALLOW_SKIP = True
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
            self.clock.now += 0.35
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
        self.assertEqual(handler.device.count_of('STORY_SKIP'), 2)
        self.assertEqual(handler.device.count_of('CLICK_SAFE_AREA'), 0)

    def test_all_world_tasks_use_skip_without_mutating_global_config(self):
        for command in ('OpsiExplore', 'OpsiObscure', 'OpsiAbyssal', 'OpsiStronghold', 'OpsiMeowfficerFarming'):
            with self.subTest(command=command):
                handler = FastStoryStub(options=[])
                handler.config.task.command = command
                with patch.object(STORY_SKIP_3, 'match', return_value=True):
                    self.assertFalse(handler.story_skip())
                    self.clock.now += 0.35
                    self.assertTrue(handler.story_skip())
                self.assertEqual(handler.device.history, ['STORY_SKIP'])
                self.assertFalse(handler.config.STORY_ALLOW_SKIP)

    def test_explicit_abyssal_choice_keeps_first_option(self):
        handler = FastStoryStub(options=make_options())
        handler.config.task.command = 'OpsiAbyssal'
        handler.config.STORY_OPTION = 0
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            self.assertFalse(handler.story_skip())
            self.clock.now += 0.35
            self.assertTrue(handler.story_skip())
        self.assertEqual(handler.device.history, ['STORY_OPTION_1_OF_3'])

    def test_generic_story_handler_keeps_original_config_and_interval(self):
        handler = FastStoryStub(options=[])
        handler._story_confirm = Timer(0.5, count=1).start()
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            self.assertFalse(InfoHandler.story_skip(handler))
            self.clock.now += 0.35
            self.assertFalse(InfoHandler.story_skip(handler))
            self.clock.now += 0.35
            self.assertTrue(InfoHandler.story_skip(handler))
            self.clock.now += 0.6
            self.assertFalse(InfoHandler.story_skip(handler))
        self.assertEqual(handler.device.count_of('STORY_SKIP'), 0)
        self.assertEqual(handler.device.count_of('CLICK_SAFE_AREA'), 1)
        self.assertEqual(handler.interval_timer['STORY_SKIP_3'].limit, 2)

    def test_pending_option_record_does_not_skip_fresh_confirmation(self):
        handler = FastStoryStub(options=make_options())
        handler._story_option_record = 3
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            self.assertFalse(handler.story_skip())
        self.assertEqual(handler.device.count_of('STORY_OPTION_'), 0)

    def test_fast_option_retries_still_detect_real_stall(self):
        handler = FastStoryStub(options=make_options())
        with patch.object(STORY_SKIP_3, 'match', return_value=True):
            with self.assertRaisesRegex(GameTooManyClickError, '剧情'):
                for _ in range(45):
                    handler.story_skip()
                    self.clock.now += 0.35


class TestCl1RewardCompletion(unittest.TestCase):
    command = 'OpsiHazard1Leveling'

    def make_handler(self, command=None):
        handler = MapEventHandler.__new__(MapEventHandler)
        handler.config = SimpleNamespace(task=SimpleNamespace(command=command or self.command))
        handler.device = Mock()
        handler.match_template_color = Mock(return_value=False)
        handler.appear = Mock(return_value=True)
        handler.os_auto_search_quit = Mock(return_value=False)
        handler._os_auto_search_started = True
        return handler

    def test_normal_cl1_reward_finishes_without_empty_restart(self):
        handler = self.make_handler()
        with self.assertRaises(CampaignEnd):
            handler.handle_os_auto_search_map_option()
        handler.os_auto_search_quit.assert_called_once()
        handler.device.click.assert_not_called()

    def test_delayed_old_reward_without_current_start_keeps_restart_path(self):
        handler = self.make_handler()
        handler._os_auto_search_started = False
        self.assertTrue(handler.handle_os_auto_search_map_option())
        handler.os_auto_search_quit.assert_called_once()

    def test_daemon_confirms_current_start_and_resets_it_between_runs(self):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(
            OpsiGeneral_AutoSearchTimeLimit=1,
            task=SimpleNamespace(command=self.command),
        )
        handler.device = Mock()
        handler.on_auto_search_battle_count_reset = Mock()
        handler.hp_reset = Mock()
        handler.is_in_map = Mock(return_value=True)
        handler.appear = Mock(return_value=True)
        handler.loop = Mock(side_effect=lambda: iter([None]))
        observed = []

        def reward(**kwargs):
            observed.append(handler._os_auto_search_started)
            raise CampaignEnd

        handler.handle_os_auto_search_map_option = reward
        handler._os_auto_search_started = True
        for state in (
            AUTO_SEARCH_OS_MAP_OPTION_OFF,
            AUTO_SEARCH_OS_MAP_OPTION_ON,
            AUTO_SEARCH_OS_MAP_OPTION_OFF,
        ):
            handler.match_template_color = Mock(side_effect=lambda button, **k: button is state)
            with self.assertRaises(CampaignEnd):
                handler.os_auto_search_daemon()
        self.assertEqual(observed, [False, True, False])

    def test_failed_or_uncertain_search_keeps_original_path(self):
        for enable in (False, None):
            with self.subTest(enable=enable):
                handler = self.make_handler()
                self.assertTrue(handler.handle_os_auto_search_map_option(enable=enable))

    def test_other_tasks_keep_original_path(self):
        handler = self.make_handler('OpsiExplore')
        self.assertTrue(handler.handle_os_auto_search_map_option())

    def test_meta_interruption_still_resumes_from_outer_search_loop(self):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(
            temporary=Mock(return_value=SimpleNamespace(recover=Mock())),
            is_task_enabled=Mock(return_value=False),
        )
        handler.info_bar_count = Mock(return_value=0)
        calls = []

        def daemon(**kwargs):
            calls.append(kwargs)
            handler.ash_popup_canceled = len(calls) == 1
            raise CampaignEnd

        handler.os_auto_search_daemon = daemon
        handler.os_auto_search_run()
        self.assertEqual(len(calls), 2)


class TestMeowRewardCompletion(TestCl1RewardCompletion):
    command = 'OpsiMeowfficerFarming'


class AutoSearchStateStub(MapEventHandler):
    """使用真实按钮冷却，模拟当前截图中的自律和剧情状态。"""

    def __init__(self):
        self.config = SimpleNamespace(task=SimpleNamespace(command='OpsiHazard1Leveling'))
        self.device = Mock(image=None)
        self.interval_timer = {}
        self.state = AUTO_SEARCH_OS_MAP_OPTION_OFF
        self.story_present = False
        self.in_map = True
        self.info_bar_count = Mock(return_value=0)

    def appear(self, button, **kwargs):
        return button is STORY_SKIP_3 and self.story_present

    def is_in_map(self):
        return self.in_map


class GuardedAutoSearchDevice(FakeDevice):
    """复刻真实防连点规则，并补上 match_template_color 需要的最小接口。"""

    def __init__(self):
        super().__init__()
        self.image = None

    def stuck_record_add(self, button):
        pass


class TestCl1AutoSearchRetry(unittest.TestCase):
    command = 'OpsiHazard1Leveling'

    def setUp(self):
        self.clock = VirtualClock()
        self.handler = AutoSearchStateStub()
        self.handler.config.task.command = self.command
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

    def test_stopped_auto_search_is_started_on_first_frame(self):
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_called_once_with(AUTO_SEARCH_OS_MAP_OPTION_OFF)

    def test_battle_transition_does_not_toggle_again_after_half_second(self):
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        # 开启操作已受理，但战后按钮动画仍短暂保留关闭外观。
        self.clock.now += 0.6
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.clock.now += 0.3
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_ON
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_called_once()

    def test_running_state_wins_when_off_appearance_also_matches(self):
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_ON
        with patch.object(AUTO_SEARCH_OS_MAP_OPTION_OFF, 'match_template_color', return_value=True):
            self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_not_called()

    def test_unregistered_click_retries_after_safe_toggle_cooldown(self):
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        for elapsed in (0.2, 0.6, 2.9):
            self.clock.now = 100 + elapsed
            self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.clock.now = 103.1
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.assertEqual(self.handler.device.click.call_count, 2)

    def test_started_auto_search_is_not_clicked_again(self):
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_ON
        self.clock.now += 0.6
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.assertEqual(self.handler.device.click.call_count, 1)

    def test_resource_search_retries_at_half_second_with_shared_off_state_cooldown(self):
        self.handler._os_auto_search_siren_resource = True
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        for state in (AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, AUTO_SEARCH_OS_MAP_OPTION_OFF):
            self.handler.state = state
            self.clock.now += 0.49
            self.assertFalse(self.handler.handle_os_auto_search_map_option())
            self.clock.now += 0.02
            self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.assertEqual(self.handler.device.click.call_count, 3)

    def test_resource_search_stops_clicking_as_soon_as_on_is_visible(self):
        self.handler._os_auto_search_siren_resource = True
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_ON
        self.clock.now += 0.51
        with patch.object(AUTO_SEARCH_OS_MAP_OPTION_OFF, 'match_template_color', return_value=True):
            self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_called_once()

    def test_resource_search_in_other_tasks_waits_for_story_and_map(self):
        self.handler.config.task.command = 'OpsiExplore'
        self.handler._os_auto_search_siren_resource = True
        self.handler.story_present = True
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.story_present = False
        self.handler.in_map = False
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_not_called()
        self.handler.in_map = True
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.clock.now += 0.51
        self.assertTrue(self.handler.handle_os_auto_search_map_option())

    def test_resource_retry_budget_survives_frames_inside_the_click_cooldown(self):
        self.handler._os_auto_search_siren_resource = True
        device = self.use_fake_device()
        with self.assertRaisesRegex(GameTooManyClickError, '自律寻敌'):
            for frame in range(231):
                self.clock.now = 100 + frame * 0.2
                self.handler.handle_os_auto_search_map_option()
        self.assertGreater(len(device.history), 60)
        self.assertLess(self.clock.now, 146)

    def test_resource_scope_is_restored_after_auto_search_returns_or_raises(self):
        self.handler.config.temporary = Mock(return_value=SimpleNamespace(recover=Mock()))
        self.handler.config.is_task_enabled = Mock(return_value=False)
        self.handler.ash_popup_canceled = False

        def search(**kwargs):
            self.assertTrue(self.handler._os_auto_search_siren_resource)
            return 2

        self.handler.os_auto_search_daemon = Mock(side_effect=search)
        self.assertEqual(OSMap.os_auto_search_run(self.handler, siren_resource=True), 2)
        self.assertFalse(self.handler._os_auto_search_siren_resource)
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.clock.now += 0.51
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.os_auto_search_daemon.side_effect = RuntimeError('search interrupted')
        with self.assertRaisesRegex(RuntimeError, 'search interrupted'):
            OSMap.os_auto_search_run(self.handler, siren_resource=True)
        self.assertFalse(self.handler._os_auto_search_siren_resource)

    def test_resource_pause_keeps_safe_toggle_cooldown(self):
        self.handler.handle_os_auto_search_map_option()
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_ON
        self.clock.now += 0.2
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_OFF
        self.clock.now += 0.9
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.clock.now += 2
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.assertEqual(self.handler.device.click.call_count, 2)

    def test_story_is_handled_before_enabling_auto_search(self):
        self.handler.story_present = True
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_not_called()
        self.handler.story_present = False
        self.clock.now += 0.2
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_called_once_with(AUTO_SEARCH_OS_MAP_OPTION_OFF)

    def test_non_map_frame_is_not_clicked(self):
        self.handler.in_map = False
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.device.click.assert_not_called()

    def test_normal_and_disabled_states_share_retry_cooldown(self):
        for first, second in (
            (AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED),
            (AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, AUTO_SEARCH_OS_MAP_OPTION_OFF),
        ):
            with self.subTest(first=first.name):
                self.handler = AutoSearchStateStub()
                self.handler.config.task.command = self.command
                self.handler.state = first
                self.handler.get_interval_timer(second, interval=3).reset()
                self.assertTrue(self.handler.handle_os_auto_search_map_option())
                self.handler.state = second
                self.clock.now += 0.2
                self.assertFalse(self.handler.handle_os_auto_search_map_option())
                self.clock.now += 3
                self.assertTrue(self.handler.handle_os_auto_search_map_option())
                self.assertEqual(
                    [call.args[0] for call in self.handler.device.click.call_args_list],
                    [first, second],
                )

    def test_other_task_keeps_three_second_retry(self):
        self.handler.config.task.command = 'OpsiExplore'
        self.assertTrue(self.handler.handle_os_auto_search_map_option())
        self.clock.now += 0.6
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.clock.now += 2.5
        self.assertTrue(self.handler.handle_os_auto_search_map_option())

    def test_request_to_stop_keeps_three_second_retry(self):
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_ON
        self.assertTrue(self.handler.handle_os_auto_search_map_option(enable=False))
        self.clock.now += 0.6
        self.assertFalse(self.handler.handle_os_auto_search_map_option(enable=False))
        self.clock.now += 2.5
        self.assertTrue(self.handler.handle_os_auto_search_map_option(enable=False))

    def test_uncertain_search_does_not_restart(self):
        self.assertFalse(self.handler.handle_os_auto_search_map_option(enable=None))
        self.handler.device.click.assert_not_called()

    def use_fake_device(self):
        """换用复刻真实防连点规则的假设备，验证重试不会触发全局阈值。"""
        device = GuardedAutoSearchDevice()
        self.handler.device = device
        return device

    def test_long_enable_storm_does_not_trip_click_guard(self):
        """装置演出期间按安全间隔重试约 43 秒，不应触发共用防连点阈值。"""
        device = self.use_fake_device()
        for _ in range(14):
            self.assertTrue(self.handler.handle_os_auto_search_map_option())
            self.clock.now += 3.1
        self.assertEqual(len(device.history), 14)
        self.assertEqual(device.count_of('AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED'), 0)
        # 每次点击后都清空点击记录，防连点阈值不会被重试累积触发
        self.assertGreaterEqual(device.clears, 14)

    def test_alternating_off_states_do_not_trip_curve_guard(self):
        """两种关闭外观交替重试也不触发「两个按钮各 ≥6 次」的防连点规则。"""
        device = self.use_fake_device()
        for n in range(14):
            self.handler.state = (
                AUTO_SEARCH_OS_MAP_OPTION_OFF if n % 2 == 0
                else AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED
            )
            self.assertTrue(self.handler.handle_os_auto_search_map_option())
            self.clock.now += 3.1
        self.assertEqual(len(device.history), 14)

    def test_stuck_enable_storm_reports_after_budget(self):
        """界面持续停在关闭外观超过预算后，按点击无效上报而不是无限重试。"""
        self.use_fake_device()
        with self.assertRaisesRegex(GameTooManyClickError, '自律寻敌'):
            for _ in range(100):
                self.handler.handle_os_auto_search_map_option()
                self.clock.now += 3.1

    def test_retry_budget_resets_between_battles(self):
        """自律开启后预算清零，下一场战斗的重试重新计时，不跨轮累积。"""
        self.use_fake_device()
        for _ in range(14):
            self.assertTrue(self.handler.handle_os_auto_search_map_option())
            self.clock.now += 3.1
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_ON
        self.clock.now += 0.6
        self.assertFalse(self.handler.handle_os_auto_search_map_option())
        self.handler.state = AUTO_SEARCH_OS_MAP_OPTION_OFF
        self.clock.now += 3.1
        for _ in range(5):
            self.assertTrue(self.handler.handle_os_auto_search_map_option())
            self.clock.now += 3.1

    def test_retry_budget_resets_when_frame_is_interrupted(self):
        """剧情或非地图画面打断重试时预算清零，恢复点击后重新计时。"""
        for interrupt in ('story', 'not_map'):
            with self.subTest(interrupt=interrupt):
                self.handler = AutoSearchStateStub()
                self.handler.config.task.command = self.command
                self.use_fake_device()
                for _ in range(14):
                    self.assertTrue(self.handler.handle_os_auto_search_map_option())
                    self.clock.now += 3.1
                if interrupt == 'story':
                    self.handler.story_present = True
                else:
                    self.handler.in_map = False
                self.clock.now += 0.6
                self.assertFalse(self.handler.handle_os_auto_search_map_option())
                self.handler.story_present = False
                self.handler.in_map = True
                self.clock.now += 3.1
                for _ in range(5):
                    self.assertTrue(self.handler.handle_os_auto_search_map_option())
                    self.clock.now += 3.1


class TestMeowAutoSearchRetry(TestCl1AutoSearchRetry):
    command = 'OpsiMeowfficerFarming'


class WalkStateStub(OSFleet):
    """真实移动等待循环的依赖桩，提供连续地图画面及指定时刻的事件。"""

    def __init__(self, clock, *, command='OpsiHazard1Leveling', shop=False, events=None, resource=False):
        self.clock = clock
        self.config = SimpleNamespace(task=SimpleNamespace(command=command))
        self.device = Mock()
        self.view = SimpleNamespace(backend=SimpleNamespace(homo_loca=(52, 58)))
        self.frame = -1
        self.shop = shop
        self.events = events or {}
        self.resource = resource
        self.is_siren_device_confirmed = False
        self.siren_device_mode = None
        for name in (
            'handle_retirement', 'handle_walk_out_of_step', 'handle_popup_confirm',
            'handle_manjuu', 'is_in_globe', 'is_in_storage', 'is_in_os_mission',
            'handle_os_game_tips', 'is_in_map_order', 'combat_appear',
            'appear_then_click', 'enemy_searching_appear',
        ):
            setattr(self, name, Mock(return_value=False))
        self.update_os = Mock()
        self.interval_clear = Mock()
        self.handle_akashi_supply_buy = Mock()
        self.enemy_searching_color_initial = Mock()
        self.is_in_map = Mock(return_value=True)
        self.match_template_color = Mock(return_value=True)

    def loop(self, **kwargs):
        for frame in range(40):
            self.frame = frame
            self.clock.now = 100 + 0.35 * frame
            yield None
        raise AssertionError('移动等待没有在连续稳定地图上结束')

    def handle_map_event(self, **kwargs):
        event = self.events.get(self.frame, '')
        if self.resource and event == 'story_skip':
            self.is_siren_device_confirmed = True
            self.siren_device_mode = 'resource'
        return event

    def appear(self, button, **kwargs):
        return button is PORT_SUPPLY_CHECK and self.shop and self.frame == 0


class TestCl1EventWalkConfirmation(unittest.TestCase):
    command = 'OpsiHazard1Leveling'

    def setUp(self):
        self.clock = VirtualClock()
        self.time_patch = patch('module.base.timer.time', self.clock)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    def run_wait(self, handler, duration=3.9):
        return handler.wait_until_walk_stable(confirm_timer=Timer(duration, count=4))

    def make_handler(self, **kwargs):
        kwargs.setdefault('command', self.command)
        return WalkStateStub(self.clock, **kwargs)

    def test_shop_return_uses_short_stability_confirmation(self):
        handler = self.make_handler(shop=True)
        self.assertIn('akashi', self.run_wait(handler))
        self.assertLess(self.clock.now, 101.5)
        handler.handle_akashi_supply_buy.assert_called_once()

    def test_initial_travel_without_event_keeps_original_wait(self):
        handler = self.make_handler()
        self.run_wait(handler)
        self.assertGreater(self.clock.now, 103.9)

    def test_other_task_shop_return_keeps_original_wait(self):
        handler = self.make_handler(shop=True, command='OpsiExplore')
        self.run_wait(handler)
        self.assertGreater(self.clock.now, 103.9)

    def test_resource_selection_can_return_to_auto_search_promptly(self):
        handler = self.make_handler(events={0: 'story_skip'}, resource=True)
        self.run_wait(handler, duration=3)
        self.assertLess(self.clock.now, 101.5)

    def test_enemy_device_selection_keeps_original_walk_confirmation(self):
        handler = self.make_handler()

        def enemy_event(**kwargs):
            if handler.frame == 0:
                handler.is_siren_device_confirmed = True
                handler.siren_device_mode = 'enemy'
                return 'story_skip'
            return ''

        handler.handle_map_event = enemy_event
        self.run_wait(handler)
        self.assertGreater(self.clock.now, 103.9)

    def test_old_resource_flag_does_not_shorten_unrelated_story_wait(self):
        handler = self.make_handler(events={0: 'story_skip'})
        handler.is_siren_device_confirmed = True
        handler.siren_device_mode = 'resource'
        self.run_wait(handler)
        self.assertGreater(self.clock.now, 103.9)

    def test_information_device_waits_for_second_dialogue_and_reward(self):
        handler = self.make_handler(events={0: 'story_skip', 3: 'story_skip', 9: 'map_get_items'})
        self.run_wait(handler, duration=3)
        self.assertGreaterEqual(handler.frame, 9)
        self.assertLess(self.clock.now, 104.7)


class TestMeowEventWalkConfirmation(TestCl1EventWalkConfirmation):
    command = 'OpsiMeowfficerFarming'


if __name__ == '__main__':
    unittest.main()
