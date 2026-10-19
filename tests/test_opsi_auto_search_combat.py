"""使用脱敏结算截图回放大世界自律战斗，不连接真实游戏。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.base.utils import load_image
from module.base.base import ModuleBase
from module.combat.assets import EXP_INFO_S
from module.exception import CampaignEnd
from module.os.map import OSMap
from module.os_combat.combat import Combat
from module.os_handler.assets import (
    AUTO_SEARCH_OS_MAP_OPTION_OFF, AUTO_SEARCH_OS_MAP_OPTION_ON, AUTO_SEARCH_REWARD,
)
from module.os_handler.map_event import MapEventHandler
from tests.test_opsi_cl1_speed import VirtualClock


FIXTURES = Path(__file__).parent / 'fixtures' / 'opsi_auto_search'


class TestOpsiAutoSearchCombat(unittest.TestCase):
    def make_handler(self, repair_threshold=0, command='OpsiHazard1Leveling', cls=Combat):
        handler = cls.__new__(cls)
        handler.config = SimpleNamespace(
            SERVER='cn', task=SimpleNamespace(command=command),
            Submarine_Fleet=0, OpsiGeneral_RepairThreshold=repair_threshold,
        )
        handler.device = Mock(image=load_image(str(FIXTURES / 'exp_info_s.png')))
        handler.interval_timer = {}
        handler.handle_background_coin_interrupt = Mock(return_value=False)
        handler.handle_combat_automation_confirm = Mock(return_value=False)
        handler.handle_os_auto_search_map_option = Mock(return_value=False)
        handler.handle_submarine_call = Mock(return_value=False)
        handler.handle_map_event = Mock(return_value=False)
        handler.submarine_call_reset = Mock()
        return handler

    def test_exp_info_advances_to_map_when_repair_is_disabled(self):
        for command in ('OpsiHazard1Leveling', 'OpsiMeowfficerFarming'):
            for threshold in (-1, 0, 0.4):
                with self.subTest(command=command, repair_threshold=threshold):
                    handler = self.make_handler(threshold, command)
                    state = SimpleNamespace(frame=0, confirmed=False, in_map=False)

                    def screenshot():
                        state.frame += 1
                        if state.frame > 8:
                            self.fail('经验结算页未确认，战斗无法返回地图')
                        state.in_map = state.confirmed

                    def click(button):
                        self.assertIs(button, EXP_INFO_S)
                        state.confirmed = True

                    handler.device.screenshot.side_effect = screenshot
                    handler.device.click.side_effect = click
                    handler.is_in_map = lambda: state.in_map
                    handler.is_combat_executing = lambda: (
                        state.frame == 1 or Combat.is_combat_executing(handler)
                    )
                    with patch('module.os_combat.combat.start_battle_timer', return_value=None), \
                            patch('module.os_combat.combat.finish_battle_timer') as finish:
                        self.assertIsNone(handler.auto_search_combat())
                    handler.device.click.assert_called_once_with(EXP_INFO_S)
                    self.assertTrue(state.in_map)
                    handler.device.screenshot_interval_set.assert_any_call()
                    finish.assert_called_once_with(handler.config, None)

    def test_active_battle_does_not_poll_or_click_map_auto_search(self):
        handler = self.make_handler()
        state = SimpleNamespace(frame=0)

        def screenshot():
            state.frame += 1
            if state.frame > 3:
                self.fail('战斗未按预期返回地图')

        def check_map_option(**kwargs):
            self.assertGreaterEqual(state.frame, 3, '战斗执行中不应检查地图自律开关')
            return False

        handler.device.screenshot.side_effect = screenshot
        handler.is_combat_executing = lambda: state.frame < 3
        handler.is_in_map = lambda: state.frame == 3
        handler.handle_os_auto_search_map_option.side_effect = check_map_option
        with patch('module.os_combat.combat.start_battle_timer', return_value=None), \
                patch('module.os_combat.combat.finish_battle_timer'):
            self.assertTrue(handler.auto_search_combat())

    def test_exp_info_uses_click_cooldown_and_fresh_screenshots(self):
        handler = self.make_handler()
        clock = VirtualClock()
        with patch('module.base.timer.time', clock):
            self.assertTrue(handler.handle_auto_search_exp_info())
            clock.now += 0.5
            self.assertFalse(handler.handle_auto_search_exp_info())
            clock.now += 2
            self.assertTrue(handler.handle_auto_search_exp_info())
        self.assertEqual(handler.device.click.call_count, 2)

    def test_siren_battles_are_all_settled_before_search_finishes_and_next_round_starts(self):
        for command in ('OpsiHazard1Leveling', 'OpsiMeowfficerFarming'):
            with self.subTest(command=command):
                handler = self.make_handler(command=command, cls=OSMap)
                handler.config.OpsiGeneral_AutoSearchTimeLimit = 10
                handler.config.stop_event = None
                handler.config.OpsiHazard1Leveling_SkipHpCheck = True
                handler.on_auto_search_battle_count_reset = Mock()
                handler.on_auto_search_battle_count_add = Mock()
                handler.hp_reset = Mock()
                handler.hp_get = Mock()
                handler.need_repair = [False] * 6
                handler.handle_retirement = Mock(return_value=False)
                handler.info_bar_count = Mock(return_value=0)
                handler.os_auto_search_quit = Mock(return_value=True)
                handler.handle_os_auto_search_map_option = (
                    MapEventHandler.handle_os_auto_search_map_option.__get__(handler)
                )
                state = SimpleNamespace(phase='stopped', settled=0, screenshots=0)
                clock = VirtualClock()

                def loop():
                    for _ in range(12):
                        clock.now += 3.1
                        if state.phase == 'battle_map':
                            state.phase = 'reward' if state.settled == 2 else 'stopped'
                        yield
                    self.fail('剩余敌人未完成结算或搜索未结束')

                def screenshot():
                    state.screenshots += 1
                    if state.screenshots > 12:
                        self.fail('战斗卡在经验结算页')
                    state.phase = {'searching': 'combat', 'combat': 'exp'}.get(state.phase, state.phase)

                def click(button):
                    if button is AUTO_SEARCH_OS_MAP_OPTION_OFF:
                        self.assertEqual(state.phase, 'stopped')
                        state.phase = 'searching'
                    else:
                        self.assertIs(button, EXP_INFO_S)
                        self.assertEqual(state.phase, 'exp')
                        state.settled += 1
                        state.phase = 'battle_map'

                def appear(button, **kwargs):
                    if state.phase == 'exp':
                        return ModuleBase.appear(handler, button, **kwargs)
                    return state.phase == 'reward' and button is AUTO_SEARCH_REWARD

                handler.loop = loop
                handler.device.screenshot.side_effect = screenshot
                handler.device.click.side_effect = click
                handler.appear = appear
                handler.is_in_map = lambda: state.phase in ('stopped', 'searching', 'battle_map')
                handler.is_combat_executing = lambda: state.phase == 'combat'
                handler.combat_appear = lambda: state.phase == 'searching'
                handler.match_template_color = lambda button, **kwargs: (
                    (state.phase == 'stopped' and button is AUTO_SEARCH_OS_MAP_OPTION_OFF)
                    or (state.phase == 'searching' and button is AUTO_SEARCH_OS_MAP_OPTION_ON)
                )

                with patch('module.base.timer.time', clock), \
                        patch('module.os_combat.combat.start_battle_timer', return_value=None), \
                        patch('module.os_combat.combat.finish_battle_timer'):
                    for _ in range(2):
                        state.phase, state.settled, state.screenshots = 'stopped', 0, 0
                        with self.assertRaises(CampaignEnd):
                            handler.os_auto_search_daemon()
                        self.assertEqual(state.settled, 2)
                self.assertEqual(handler.on_auto_search_battle_count_add.call_count, 4)
                self.assertEqual(
                    [entry.args[0] for entry in handler.device.click.call_args_list],
                    [AUTO_SEARCH_OS_MAP_OPTION_OFF, EXP_INFO_S] * 4,
                )


if __name__ == '__main__':
    unittest.main()
