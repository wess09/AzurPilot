"""验证潜艇高级规则的资源约束、地图接入和召唤确认。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import yaml

from module.combat.assets import (
    SUBMARINE_AVAILABLE_CHECK_1,
    SUBMARINE_AVAILABLE_CHECK_2,
)
from module.combat.submarine import SubmarineCall
from module.combat.submarine_advanced import SubmarineAdvancedConfig, SubmarinePlan
from module.config.config_generated import GeneratedConfig
from module.exception import CampaignEnd, ScriptError
from module.map.fleet import Fleet
from module.map.map_base import CampaignMap


def make_config(rules=None, **overrides):
    """使用仅覆盖中心和右邻格的范围，显式验证横纵坐标与方向。"""
    data = {
        'ammo': 3, 'support': 1,
        'range': ['OOOOOOO', 'OOOOOOO', 'OOOOOOO', 'OOOHNOO', 'OOOOOOO', 'OOOOOOO', 'OOOOOOO'],
        'rules': rules if rules is not None else {'battle_0': {'type': 'call'}},
    }
    data.update(overrides)
    return yaml.safe_dump(data)


class TestSubmarineRules(unittest.TestCase):
    def choose(self, state, **overrides):
        args = {'battle': 1, 'total': 6, 'enemy': '3M', 'target': (4, 3), 'origin': (3, 3)}
        args.update(overrides)
        return state.choose(**args)

    def test_default_and_legacy_example_are_valid(self):
        text = GeneratedConfig.Submarine_AdvancedConfig
        yaml.safe_load(text)
        for example in (text, text.replace('">=2" #', '">=2"\t#')):
            state = SubmarineAdvancedConfig(example)
            self.assertEqual((state.ammo, state.support), (7, 1))
            self.assertEqual(len(state.rules), 3)

    def test_invalid_config_is_rejected_before_actions(self):
        invalid = [
            '', '[]', '!!python/object:builtins.object {}',
            make_config(ammo=True), make_config(ammo=-1), make_config(support='1'),
            make_config(range=['NNNNNNN'] * 7), make_config(range=['H'] * 7),
            make_config({'battle_one': {'type': 'call'}}),
            make_config({'battle_0': {'type': 'unknown'}}),
            make_config({'battle_0': {'type': 'call', 'move': 'false'}}),
            make_config({'battle_0': {'type': 'call', 'condition': {'amoo': '>2'}}}),
            make_config({'battle_0': {'type': 'call', 'condition': {'ammo': '__import__("os")'}}}),
            make_config({'battle_0': {'type': 'call', 'condition': {'enemy': ['3X']}}}),
            make_config({'battle_0': {'type': 'call', 'condition': {'in_range': 'false'}}}),
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ScriptError):
                SubmarineAdvancedConfig(text)

    def test_asymmetric_range_includes_center(self):
        state = SubmarineAdvancedConfig(make_config())
        self.assertTrue(state.in_range((3, 3), (3, 3)))
        self.assertTrue(state.in_range((4, 3), (3, 3)))
        self.assertFalse(state.in_range((2, 3), (3, 3)))
        self.assertFalse(state.in_range((3, 4), (3, 3)))
        self.assertFalse(state.in_range((3, 3), ()))

    def test_battle_indices_and_call_priority(self):
        state = SubmarineAdvancedConfig(make_config({
            'battle_0': {'type': 'hunt'},
            'battle_2': {'type': 'call'},
            'battle_-2': {'type': 'call'},
            'battle_-1': {'type': 'call'},
        }))
        for battle, mode in [(1, 'hunt'), (2, 'call'), (3, 'hunt'), (5, 'call'), (6, 'call')]:
            self.assertEqual(self.choose(state, battle=battle).mode, mode)
        self.assertEqual(self.choose(state, battle=5, total=None).mode, 'hunt')

    def test_comparisons_and_enemy_wildcards(self):
        for expression, matched in [('>2', True), ('>=3', True), ('<3', False),
                                    ('<=3', True), ('=3', True), ('!=3', False)]:
            state = SubmarineAdvancedConfig(make_config({'battle_0': {
                'type': 'call', 'condition': {'ammo': expression, 'support': '!=0', 'enemy': ['3*', '*T']},
            }}))
            with self.subTest(expression=expression):
                self.assertEqual(self.choose(state) is not None, matched)
                self.assertEqual(self.choose(state, enemy='1T') is not None, matched)
                self.assertIsNone(self.choose(state, enemy='2C'))
                state.support = 0
                self.assertIsNone(self.choose(state))

    def test_hunt_cannot_use_ocean_support(self):
        state = SubmarineAdvancedConfig(make_config({'battle_0': {'type': 'hunt'}}))
        self.assertIsNone(self.choose(state, target=(6, 3)))
        self.assertEqual((state.ammo, state.support), (3, 1))

    def test_support_precedes_movement_and_then_runs_out(self):
        state = SubmarineAdvancedConfig(make_config({'battle_0': {'type': 'call', 'move': True}}, ammo=2))
        args = {'target': (6, 3), 'positions': [((5, 3), 2), ((6, 3), 3)]}
        state.set_plan(self.choose(state, **args))
        self.assertEqual(state.plan, SubmarinePlan('call', support=True))
        self.assertTrue(state.consume('call'))
        self.assertFalse(state.consume('call'))
        self.assertEqual((state.ammo, state.support), (1, 0))
        state.set_plan(self.choose(state, **args))
        self.assertEqual(state.plan, SubmarinePlan('call', location=(5, 3)))
        self.assertTrue(state.consume('call'))
        self.assertEqual((state.ammo, state.support), (0, 0))
        self.assertIsNone(self.choose(state))

    def test_move_hunt_and_range_required_call_without_using_support(self):
        for mode in ('hunt', 'call'):
            state = SubmarineAdvancedConfig(make_config({'battle_0': {
                'type': mode, 'move': True, 'condition': {'in_range': True},
            }}))
            with self.subTest(mode=mode):
                self.assertIsNone(self.choose(state, target=(6, 3)))
                plan = self.choose(state, target=(6, 3), positions=[((6, 3), 4), ((5, 3), 2)])
                self.assertEqual(plan, SubmarinePlan(mode, location=(5, 3)))
                state.set_plan(plan)
                state.consume(mode)
                self.assertEqual((state.ammo, state.support), (2, 1))

    def test_false_range_condition_allows_covered_targets(self):
        state = SubmarineAdvancedConfig(make_config({'battle_0': {
            'type': 'call', 'condition': {'in_range': False},
        }}))
        self.assertEqual(self.choose(state), SubmarinePlan('call'))

    def test_zero_ammo_and_missing_position_never_dispatch(self):
        for ammo, origin in [(0, (3, 3)), (3, ())]:
            state = SubmarineAdvancedConfig(make_config(ammo=ammo))
            self.assertIsNone(self.choose(state, origin=origin))

    def test_unknown_enemy_and_legacy_support_opt_out(self):
        state = SubmarineAdvancedConfig(make_config({'battle_0': {
            'type': 'call', 'support': False, 'condition': {'enemy': ['0E']},
        }}))
        self.assertEqual(self.choose(state, enemy='0E'), SubmarinePlan('call'))
        self.assertIsNone(self.choose(state, enemy='0E', target=(6, 3)))


class TestSubmarineMapIntegration(unittest.TestCase):
    def setUp(self):
        """使用真实地图寻路和规则，仅替换屏幕操作。"""
        self.fleet = object.__new__(Fleet)
        self.fleet.config = SimpleNamespace(Submarine_Fleet=1, Submarine_Mode='advanced',
                                            Submarine_AdvancedConfig=make_config())
        self.fleet.map_is_auto_search = False
        self.fleet.battle_count = 0
        self.fleet.submarine_advanced_reset()
        self.fleet.fleet_submarine_location = (3, 3)
        self.fleet.map = CampaignMap('潜艇规则测试')
        self.fleet.map.shape = 'G7'
        self.fleet.map.map_data = '\n'.join([' '.join(['--'] * 7)] * 7)
        self.fleet.map.load_map_data()
        self.fleet.map.grid_connection_initial()
        self.fleet.map.spawn_data = [{'battle': 0, 'enemy': 5}, {'battle': 5, 'boss': 1}]
        self.fleet.map[(6, 3)].is_enemy = True
        self.fleet.map[(6, 3)].enemy_scale = 3
        self.fleet.map[(6, 3)].enemy_genre = 'Main'
        self.fleet.strategy_open = Mock()
        self.fleet.strategy_close = Mock()
        self.fleet.strategy_set_execute = Mock(side_effect=self.set_strategy)
        self.fleet.submarine_goto = Mock(side_effect=self.move)
        self.fleet.find_path_initial = Mock(side_effect=self.restore_paths)

    def set_strategy(self, sub_view=None, sub_hunt=None):
        if sub_hunt is not None:
            self.fleet.submarine_hunt_enabled = sub_hunt

    def move(self, location):
        self.fleet.fleet_submarine_location = location
        return True

    def restore_paths(self):
        self.fleet.map.find_path_initial((0, 0), has_ambush=False)

    def configure(self, rules, **overrides):
        self.fleet.config.Submarine_AdvancedConfig = make_config(rules, **overrides)
        self.fleet.submarine_advanced_reset()

    def test_support_then_cheapest_move_and_restore_surface_paths(self):
        self.configure({'battle_0': {'type': 'call', 'move': True}})
        fleet = self.fleet
        fleet.submarine_advanced_prepare((6, 3), 'combat')
        self.assertEqual(fleet._submarine_mode('combat'), 'advanced_call')
        fleet.submarine_goto.assert_not_called()
        fleet.submarine_advanced.consume('call')
        fleet.battle_count += 1
        fleet.submarine_advanced_prepare((6, 3), 'combat')
        fleet.submarine_goto.assert_called_once_with((5, 3))
        self.assertEqual(fleet.map[(0, 0)].cost, 0)
        self.assertFalse(fleet.submarine_hunt_enabled)

    def test_hunt_switches_off_and_consumes_once(self):
        self.configure({'battle_1': {'type': 'hunt', 'move': True}}, ammo=1)
        fleet = self.fleet
        fleet.submarine_advanced_prepare((6, 3), 'combat')
        self.assertTrue(fleet.submarine_hunt_enabled)
        self.assertEqual(fleet._submarine_mode('combat'), 'do_not_use')
        fleet.submarine_advanced_prepare((6, 3), 'combat')
        fleet.submarine_goto.assert_called_once()
        self.assertEqual(fleet.submarine_advanced.ammo, 1)
        fleet.submarine_advanced_combat_start()
        fleet.submarine_advanced_combat_start()
        self.assertEqual(fleet.submarine_advanced.ammo, 0)
        self.assertEqual(fleet.submarine_advanced.support, 1)
        fleet.battle_count += 1
        fleet.submarine_advanced_prepare((6, 3), 'combat')
        self.assertFalse(fleet.submarine_hunt_enabled)

    def test_unreachable_movement_does_not_dispatch(self):
        self.configure({'battle_0': {'type': 'hunt', 'move': True}})
        for y in range(7):
            self.fleet.map[(4, y)].is_land = True
        self.fleet.submarine_advanced_prepare((6, 3), 'combat')
        self.fleet.submarine_goto.assert_not_called()
        self.assertIsNone(self.fleet.submarine_advanced.plan)

    def test_failed_move_does_not_enable_hunt_or_call(self):
        self.configure({'battle_0': {'type': 'hunt', 'move': True}})
        self.fleet.submarine_goto.side_effect = None
        self.fleet.submarine_goto.return_value = False
        self.fleet.submarine_advanced_prepare((6, 3), 'combat')
        self.assertIsNone(self.fleet.submarine_advanced.plan)
        self.assertFalse(self.fleet.submarine_hunt_enabled)

    def test_unknown_hunt_switch_stops_before_enemy_click(self):
        self.fleet.strategy_set_execute.side_effect = None
        with self.assertRaises(ScriptError):
            self.fleet.submarine_advanced_prepare((6, 3), 'combat')

    def test_negative_index_uses_boss_spawn_and_actual_boss(self):
        self.configure({'battle_-2': {'type': 'call'}, 'battle_-1': {'type': 'call'}})
        for count, expected, mode in [(0, 'combat', 'do_not_use'), (4, 'combat', 'advanced_call'),
                                       (7, 'combat_boss', 'advanced_call')]:
            self.fleet.battle_count = count
            self.fleet.submarine_advanced_prepare((6, 3), expected)
            self.assertEqual(self.fleet._submarine_mode(expected), mode)

    def test_clear_all_counts_remaining_enemies_before_boss(self):
        self.configure({'battle_-2': {'type': 'call'}})
        self.fleet.config.MAP_CLEAR_ALL_THIS_TIME = True
        self.fleet.map.spawn_data = [{'battle': 0, 'enemy': 8}, {'battle': 5, 'boss': 1}]
        for count, mode in [(4, 'do_not_use'), (7, 'advanced_call')]:
            self.fleet.battle_count = count
            self.fleet.submarine_advanced_prepare((6, 3), 'combat')
            self.assertEqual(self.fleet._submarine_mode('combat'), mode)

    def test_goto_applies_strategy_before_enemy_click_and_accounts_hunt(self):
        self.configure({'battle_0': {'type': 'hunt', 'move': True}})
        fleet = self.fleet
        fleet.config.MAP_HAS_LAND_BASED = False
        fleet.config.Campaign_UseFleetLock = False
        fleet.fleet_current_index = 1
        fleet.device = Mock()
        fleet.view = Mock()
        fleet.hp_retreat_triggered = Mock(return_value=False)
        fleet.fleet_ensure = Mock()
        fleet.in_sight = Mock()
        fleet.focus_to_grid_center = Mock()
        fleet.convert_global_to_local = Mock(return_value=Mock())
        fleet.ambush_color_initial = Mock()
        fleet.enemy_searching_color_initial = Mock()
        fleet.combat_appear = Mock(return_value=True)
        fleet.combat = Mock(side_effect=CampaignEnd)

        def check_before_click(button):
            self.assertTrue(fleet.submarine_hunt_enabled)
            self.assertEqual(fleet.fleet_submarine_location, (5, 3))
            self.assertEqual(fleet.submarine_advanced.ammo, 3)

        fleet.device.click.side_effect = check_before_click
        with (patch.object(Fleet, 'round_wait', new_callable=PropertyMock, return_value=0),
              self.assertRaises(CampaignEnd)):
            fleet._goto((6, 3), expected='combat')
        self.assertEqual(fleet.submarine_advanced.ammo, 2)
        self.assertEqual(fleet.combat.call_args.kwargs['submarine_mode'], 'do_not_use')

    def test_submarine_goto_updates_location_after_confirmation_or_cancellation(self):
        fleet = self.fleet
        fleet.strategy_submarine_move_enter = Mock()
        fleet.strategy_submarine_move_confirm = Mock()
        fleet.strategy_submarine_move_cancel = Mock()
        for moved in (True, False):
            fleet.fleet_submarine_location = (3, 3)
            fleet._submarine_goto = Mock(return_value=moved)
            self.assertEqual(Fleet.submarine_goto(fleet, (5, 3)), moved)
            self.assertEqual(fleet.fleet_submarine_location, (5, 3))

    def test_reset_and_auto_search_do_not_reuse_previous_map(self):
        self.fleet.submarine_advanced.ammo = 0
        self.fleet.submarine_advanced_reset()
        self.assertEqual(self.fleet.submarine_advanced.ammo, 3)
        self.fleet.map_is_auto_search = True
        self.fleet.submarine_advanced_reset()
        self.assertIsNone(self.fleet.submarine_advanced)
        self.assertEqual(self.fleet._submarine_mode('combat_boss'), 'do_not_use')
        self.fleet.map_is_auto_search = False
        self.fleet.config.Submarine_Fleet = 0
        self.fleet.submarine_advanced_reset()
        self.assertIsNone(self.fleet.submarine_advanced)


class TestSubmarineCallConfirmation(unittest.TestCase):
    def setUp(self):
        self.combat = object.__new__(SubmarineCall)
        self.combat.device = Mock()
        self.combat.submarine_advanced = SubmarineAdvancedConfig(make_config())
        self.combat.submarine_advanced.set_plan(SubmarinePlan('call', support=True))
        self.combat.submarine_call_reset()
        self.combat.appear = Mock(side_effect=lambda button: button in (
            SUBMARINE_AVAILABLE_CHECK_1, SUBMARINE_AVAILABLE_CHECK_2))
        self.combat.appear_then_click = Mock(return_value=True)

    def test_only_confirmed_call_consumes_ammo_and_support(self):
        combat = self.combat
        self.assertTrue(combat.handle_submarine_call('advanced_call'))
        self.assertEqual(combat.submarine_advanced.ammo, 3)
        combat.appear.side_effect = None
        combat.appear.return_value = True
        combat.submarine_call_timer = Mock(reached=Mock(return_value=True))
        self.assertFalse(combat.handle_submarine_call('advanced_call'))
        self.assertFalse(combat.handle_submarine_call('advanced_call'))
        self.assertEqual((combat.submarine_advanced.ammo, combat.submarine_advanced.support), (2, 0))

    def test_unavailable_ready_button_is_never_blindly_clicked(self):
        self.combat.appear_then_click.return_value = False
        self.assertFalse(self.combat.handle_submarine_call('advanced_call'))
        self.combat.device.click.assert_not_called()
        self.assertEqual(self.combat.submarine_advanced.ammo, 3)

    def test_timeout_without_confirmation_preserves_resources(self):
        self.combat.submarine_call_timer = Mock(reached=Mock(return_value=True))
        self.assertFalse(self.combat.handle_submarine_call('advanced_call'))
        self.assertEqual((self.combat.submarine_advanced.ammo, self.combat.submarine_advanced.support), (3, 1))

    def test_raw_advanced_and_old_non_call_modes_never_call(self):
        for mode in ('advanced', 'hunt_only', 'hunt_and_boss', 'boss_only', 'do_not_use'):
            with self.subTest(mode=mode):
                self.combat.submarine_call_reset()
                self.assertFalse(self.combat.handle_submarine_call(mode))
        self.combat.appear_then_click.assert_not_called()

    def test_combat_timers_are_not_shared_between_instances(self):
        other = object.__new__(SubmarineCall)
        other.submarine_call_reset()
        self.assertIsNot(self.combat.submarine_call_timer, other.submarine_call_timer)
        self.assertIsNot(self.combat.submarine_call_click_timer, other.submarine_call_click_timer)


if __name__ == '__main__':
    unittest.main()
