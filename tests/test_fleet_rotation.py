"""智能换船规则、真实配置事务、出击前联动与中断恢复；不连接设备。"""

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.campaign.fleet_rotation import preflight_rotation
from module.campaign.fleet_rotation_emotion import selected_morale
from module.combat.emotion import Emotion
from module.config.config import AzurLaneConfig
from module.exception import CampaignEnd, FleetManagementError, GameStuckError, ScriptEnd
from module.handler.info_handler import InfoHandler
from module.runtime.fleet_rotation import (ROTATION_PATH, begin_round, calibration_changes,
                                         minimum_morale, parse_rules, rank_sources, recorded_morale, supported)
from module.runtime.fleet_equipment import EQUIPMENT_PATH
from tests.test_api import fixture


RULE = {'slots': [4, 5, 6], 'sources': [3, 4, 5, 6]}


class RuleTests(unittest.TestCase):
    def test_common_source_is_optional_and_boolean_without_reordering_reserves(self):
        rule = {'1': {'slots': [4], 'sources': [5, 3, 4], 'favourite': True}}
        self.assertEqual(parse_rules(rule)['1'], dict(slots=[4], sources=[3, 4, 5], favourite=True))
        for value in (1, 'true', None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_rules({'1': {'slots': [4], 'sources': [], 'favourite': value}})

    def test_defaults_and_strict_rule_validation(self):
        self.assertEqual(parse_rules('{}'), {})
        self.assertEqual(parse_rules({'1': {'slots': [5, 3], 'sources': [6, 3]}}),
                         {'1': {'slots': [3, 5], 'sources': [3, 6]}})
        for value in ('[]', 'invalid', {'7': RULE}, {'1': {'slots': [True]}},
                      {'1': {'sources': [1]}}, {'1': {'slots': [3, 3]}}, {'1': {'unknown': []}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_rules(value)

    def test_morale_rank_is_4_5_6_3_and_unfinished_round_keeps_its_source(self):
        readings = {fleet: dict.fromkeys(range(1, 7), 150) for fleet in RULE['sources']}
        readings[3][4] = 138
        order = rank_sources(RULE, readings, 120)
        self.assertEqual(order, [4, 5, 6, 3])
        progress = begin_round(RULE, {'last_source': 6}, order)
        progress['done'] = [4, 5]
        self.assertEqual(begin_round(RULE, progress, [3])['source'], 4)
        self.assertEqual(begin_round(RULE, progress)['done'], [4, 5])
        progress['pending'] = {'slot': 6}
        with self.assertRaises(ValueError):
            begin_round(RULE, progress)

    def test_scope_excludes_difficult_other_task_and_archives(self):
        for task in ('Main', 'Main2', 'Main3', 'Event', 'Event2', 'EventA', 'EventD'):
            self.assertTrue(supported(task, 'normal', 'campaign_main' if task.startswith('Main') else 'event_20261022_cn'))
        for task, mode, folder in (('Main', 'hard', 'campaign_main'), ('GemsFarming', 'normal', 'campaign_main'),
                                   ('WarArchives', 'normal', 'war_archives_20261022_cn'), ('OpsiDaily', 'normal', 'event_a')):
            self.assertFalse(supported(task, mode, folder))
        for stage in ('c1', 'd3_3', 'ht2', 'ex', 'ex_ex'):
            self.assertFalse(supported('Event', 'normal', 'event_20261022_cn', stage))
        for stage in ('sp', 'sp3', 'ex_sp'):
            self.assertTrue(supported('Event', 'normal', 'event_20261022_cn', stage))

    def test_calibration_keeps_unknown_as_unknown_and_does_not_map_hard_event_default_mode(self):
        fields = {'Fleet1Recover': 'not_in_dormitory', 'Fleet1Oath': False, 'Fleet1Onsen': False}
        data = {task: {'Campaign': {'Mode': 'normal', 'Name': name}, 'Fleet': {'Fleet1': 1},
                       'Emotion': fields} for task, name in (('Main', '12-4'), ('Event', 'a1'), ('EventD', 'd3'))}
        changes = calibration_changes(data, {1: {3: None, 4: 150}}, datetime(2026, 10, 22))
        self.assertIsNone(changes['Main.Emotion.Fleet1RecoveryState'])
        self.assertNotIn('Main.Emotion.Fleet1Value', changes)
        self.assertNotIn('EventD.Emotion.Fleet1RecoveryState', changes)
        valid = calibration_changes(data, {1: {3: 100, 4: 0}}, datetime(2026, 10, 22))
        self.assertEqual(valid['Main.Emotion.Fleet1Value'], 0)
        self.assertEqual(valid['Event.Emotion.Fleet1Value'], 0)

    def test_minimum_includes_unchanged_slots_zero_and_unknown(self):
        self.assertEqual(minimum_morale({1: 150, 3: 2, 4: 149}), 2)
        self.assertEqual(minimum_morale({4: 0, 5: 150}), 0)
        self.assertIsNone(minimum_morale({3: None, 4: 150}))
        self.assertIsNone(minimum_morale({}))

    def test_missing_unknown_or_low_source_slots_are_not_chosen(self):
        readings = {3: {4: 150, 5: 150}, 4: {4: 150, 5: None, 6: 150},
                    5: dict.fromkeys(range(1, 7), 2), 6: dict.fromkeys(range(1, 7), 149)}
        self.assertEqual(rank_sources(RULE, readings, 120), [6])
        self.assertIsNone(begin_round(RULE, {}, []))
        result = {'vanguard': {'1': [{'slot': 6, 'emotion': 150}, {'slot': 4, 'emotion': 2}]}}
        self.assertEqual(recorded_morale(result, 1), {6: 150, 4: 2})
        self.assertEqual(recorded_morale('旧版数据', 1), {})
        with self.assertRaisesRegex(ValueError, '旧版轮换记录'):
            begin_round(RULE, dict(source=3, done=[4], rule=RULE))


class RotationIntegrationTests(unittest.TestCase):
    def test_stop_option_without_training_goals_does_not_activate_an_empty_rotation_rule(self):
        self.config.cross_set_many({'FleetInfo.FleetTraining.StopOnComplete': True,
                                    ROTATION_PATH + '.Rules': json.dumps({'1': {'slots': [4], 'sources': []}})})
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_not_called()
        self.manager.rotate_slot.assert_not_called()
        self.inventory_reader.inventory.assert_not_called()

    def test_partial_reserves_precede_common_for_each_morale_slot(self):
        self.config.cross_set_many({ROTATION_PATH + '.Rules': json.dumps({'1': {
            'slots': [4, 5], 'sources': [3, 4, 5], 'favourite': True}}),
            ROTATION_PATH + '.SelectedOnly': True})
        self.manager.RESULT_PATH = 'FleetInfo.FleetInfo.Result'
        for fleet in (3, 4, 5):
            self.live[fleet][5] = 2
        self.live[3][4] = 150
        candidate = dict(name='拉菲', level=80, emotion=150, review=False)

        def replace(fleet, slot, ship):
            self.live[fleet][slot] = 150
            snapshots = self.snapshots()
            result = self.config.cross_get(self.manager.RESULT_PATH)
            result['vanguard'][str(fleet)][slot - 4]['name'] = ship['name']
            self.config.cross_set(self.manager.RESULT_PATH, result)
            return snapshots

        with patch('module.retire.fleet_favourite.FavouriteShips') as common:
            common.return_value.find.return_value = candidate
            common.return_value.replace.side_effect = replace
            preflight_rotation(self.runner, 5, 'normal')
            self.manager.rotate_slot.assert_called_once_with(3, 4, 1)
            common.return_value.find.assert_called_once()
            self.assertEqual((1, 5), common.return_value.find.call_args.args[:2])
            common.return_value.replace.assert_called_once_with(1, 5, candidate)
        self.assertEqual(150, self.live[1][4])
        self.assertEqual(150, self.live[1][5])
        self.assertTrue(self.state()['1']['favourite'])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.service = ConfigService(fixture(directory))
        self.path = self.service.path('testpilot')
        for target in ('module.config.config.filepath_config', 'module.config.config_updater.filepath_config'):
            self.stack.enter_context(patch(target, return_value=str(self.path)))
        self.config = AzurLaneConfig('testpilot', task='Main')
        self.config.cross_set_many({ROTATION_PATH + '.Enabled': True, ROTATION_PATH + '.Rules': json.dumps({'1': RULE}),
                                    'Main.Fleet.FleetOrder': 'fleet1_all_fleet2_standby'})
        self.config.set_record(Emotion_Fleet1Value=2, Emotion_Fleet2Value=150)
        self.campaign = SimpleNamespace(config=self.config, emotion=Emotion(self.config),
                                        ensure_campaign_ui=Mock(), map_get_info=Mock())
        self.runner = SimpleNamespace(config=self.config, campaign=self.campaign, folder='campaign_main',
                                      stage='12-4', device=object())
        self.manager = Mock()
        self.live = {fleet: dict.fromkeys(range(1, 7), 150) for fleet in range(1, 7)}
        self.live[1][4] = 2
        self.live[3][4] = 138
        def full_scan(**kwargs):
            from module.runtime.fleet_training import mark_full_scan
            self.full_scan(**kwargs)
            mark_full_scan(self.config)
        self.manager.run.side_effect = full_scan
        self.manager.rotate_slot.side_effect = self.rotate
        self.manager.prepare_rotation.side_effect = lambda fleet, **kwargs: self.snapshots()
        self.factory = self.stack.enter_context(patch('module.campaign.fleet_rotation.FleetManagement', return_value=self.manager))
        reader = self.stack.enter_context(patch('module.campaign.fleet_training.FleetTrainingReader'))
        reader.return_value.inventory.side_effect = lambda fleets, **kwargs: self.full_scan(fleets=fleets)
        self.inventory_reader = reader.return_value

    def full_scan(self, **kwargs):
        result = {category: {str(fleet): [dict(slot=slot, name='', level=100, occupied=True,
                   emotion=self.live[fleet][slot]) for slot in slots] for fleet in range(1, 7)}
                  for category, slots in (('main', (1, 2, 3)), ('vanguard', (4, 5, 6)))}
        self.config.cross_set('FleetInfo.FleetInfo.Result', result)

    def readings(self, fleet, **kwargs):
        self.full_scan()
        return deepcopy(self.live[fleet])

    def snapshots(self):
        self.full_scan()
        return deepcopy(self.live)

    def rotate(self, source, slot, fleet):
        self.swap(source, slot, fleet, slot)
        return self.snapshots()

    def swap(self, source, source_slot, fleet, slot):
        self.assertEqual(source_slot, slot)
        self.live[source][source_slot], self.live[fleet][slot] = self.live[fleet][slot], self.live[source][source_slot]

    def state(self):
        return self.service.read_json(self.path)['FleetInfo']['FleetRotation']['State']

    def morale_policy(self, selected_only=True, fixed=70, training=150):
        self.config.cross_set_many({ROTATION_PATH + '.SelectedOnly': selected_only,
                                    'Main.Emotion.Fleet1Control': 'keep_exp_bonus',
                                    'Main.Emotion.Fleet1Recover': 'dormitory_floor_1'})
        self.live[1] = {1: fixed, 2: 150, 3: 150, 4: training, 5: 150, 6: 150}
        context = self.runner.__dict__.get('_fleet_rotation_context', {})
        if 'training_checked_at' in context:
            context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        preflight_rotation(self.runner, 5, 'normal')
        return self.campaign.emotion

    def popup_handler(self, emotion):
        return SimpleNamespace(emotion=emotion, config=self.config, _map_battle=5,
                               _popup_offset=(3, 30), appear=Mock(return_value=True),
                               handle_use_data_key=Mock(return_value=False),
                               handle_popup_cancel=Mock(return_value=True),
                               handle_popup_confirm=Mock(return_value=True),
                               _emotion_emergency_exit=Mock(), interval_reset=Mock())

    def test_selected_150_fixed_70_does_not_rotate_and_keeps_full_fleet_ledger(self):
        emotion = self.morale_policy()
        self.manager.rotate_slot.assert_not_called()
        self.assertEqual(70, self.config.Emotion_Fleet1Value)
        self.assertEqual(150, emotion.training_lower(1))
        emotion.check_reduce(5)
        emotion.reduce(1)
        self.assertEqual(68, emotion.fleet_1.lower)
        self.assertEqual(148, emotion.training_lower(1))
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.prepare_rotation.assert_not_called()
        self.manager.run.assert_not_called()

    def test_switch_off_waits_for_fixed_70_instead_of_swapping_training_150(self):
        emotion = self.morale_policy(selected_only=False)
        self.manager.rotate_slot.assert_not_called()
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(5)
        self.assertGreater(self.config.Scheduler_NextRun, datetime.now())
        self.assertEqual({}, self.state())

    def test_multiple_training_slots_use_their_minimum_and_missing_stays_unknown(self):
        self.assertEqual(135, selected_morale({1: 0, 4: 150, 5: 135, 6: 140}, [4, 5, 6]))
        self.assertEqual(150, selected_morale({1: 0, 4: 150}, [4, 5]))
        self.assertIsNone(selected_morale({1: 150, 4: 150, 5: None}, [4, 5]))
        self.assertIsNone(selected_morale({1: 150}, [4, 5]))
        emotion = self.morale_policy(training=150)
        self.live[1][5] = 135
        emotion.calibrate_selected(self.snapshots())
        self.assertEqual(135, emotion.training_lower(1))
        emotion.reduce(1)
        self.assertEqual(133, emotion.training_lower(1))

    def test_low_training_rotates_despite_fixed_low_and_only_ranks_selected_reserve_slots(self):
        self.live[4][1] = 0
        before = deepcopy(self.config.cross_get('MindCalculator', {}))
        emotion = self.morale_policy(training=120)
        self.manager.rotate_slot.assert_called()
        self.assertEqual([4, 4, 4], [call.args[0] for call in self.manager.rotate_slot.call_args_list])
        self.assertEqual(150, emotion.training_lower(1))
        self.assertEqual(70, self.config.Emotion_Fleet1Value)
        emotion.check_reduce(5)
        self.assertEqual(before, self.config.cross_get('MindCalculator', {}))
        self.assertEqual({'last_source', 'completed_at'}, set(self.state()['1']))

    def test_selected_only_ignores_fixed_low_morale_but_disabled_mode_waits(self):
        for fixed in (20, 45):
            with self.subTest(fixed=fixed):
                emotion = self.morale_policy(fixed=fixed)
                self.manager.rotate_slot.assert_not_called()
                emotion.check_reduce(5)
                emotion = self.morale_policy(selected_only=False, fixed=fixed)
                with self.assertRaises(ScriptEnd):
                    emotion.check_reduce(5)
                self.assertEqual(150, emotion.training_lower(1))

    def test_no_ready_reserve_waits_for_training_instead_of_bypassing_its_threshold(self):
        for fleet in RULE['sources']:
            self.live[fleet] = dict.fromkeys(range(1, 7), 100)
        emotion = self.morale_policy(training=100)
        self.manager.rotate_slot.assert_not_called()
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(5)

    def test_selected_only_confirms_fixed_red_without_changing_training_morale(self):
        emotion = self.morale_policy(fixed=0)
        emotion.check_reduce(5)
        handler = self.popup_handler(emotion)
        self.assertTrue(InfoHandler.handle_combat_low_emotion(handler))
        handler.handle_popup_confirm.assert_called_once_with('IGNORE_LOW_EMOTION')
        handler.handle_popup_cancel.assert_not_called()
        self.assertEqual(150, emotion.training_lower(1))
        self.assertEqual(0, emotion.fleet_1.lower)

    def test_switch_off_retains_original_red_fallback_and_delay(self):
        emotion = self.morale_policy(selected_only=False, fixed=0)
        handler = self.popup_handler(emotion)
        with self.assertRaises(ScriptEnd):
            InfoHandler.handle_combat_low_emotion(handler)
        handler.handle_popup_confirm.assert_not_called()
        handler.handle_popup_cancel.assert_called_once()
        handler._emotion_emergency_exit.assert_called_once()
        self.assertGreater(self.config.Scheduler_NextRun, datetime.now())
        self.assertEqual({}, self.state())
        self.assertFalse(self.runner._fleet_rotation_context['scanned'])

    def test_training_red_or_unknown_popup_cancels_and_rescans_instead_of_confirming(self):
        emotion = self.morale_policy(fixed=0)
        for value in (0, None):
            with self.subTest(value=value):
                emotion.calibrate_selected({1: {4: value, 5: 150, 6: 150}})
                handler = self.popup_handler(emotion)
                with self.assertRaises(ScriptEnd):
                    InfoHandler.handle_combat_low_emotion(handler)
                handler.handle_popup_confirm.assert_not_called()
                self.assertLess(self.config.Scheduler_NextRun - datetime.now(), timedelta(seconds=2))
                self.assertFalse(self.runner._fleet_rotation_context['scanned'])

    def test_task_ignore_mode_cannot_skip_training_calculation_in_either_switch_mode(self):
        self.config.cross_set('Main.Emotion.Mode', 'ignore')
        emotion = self.morale_policy(fixed=20)
        self.assertTrue(emotion.is_calculate)
        emotion.reduce(1)
        self.assertEqual(148, emotion.training_lower(1))
        emotion.check_reduce(1)
        emotion = self.morale_policy(selected_only=False, fixed=20)
        self.assertTrue(emotion.is_calculate)
        self.assertFalse(emotion.is_ignore)
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(1)

    def test_unknown_fixed_morale_does_not_block_known_training_or_its_consumption(self):
        emotion = self.morale_policy(fixed=None)
        emotion.check_reduce(5)
        emotion.reduce(1)
        self.assertEqual(148, emotion.training_lower(1))
        self.assertIsNone(emotion.fleet_1.state)

    def test_unknown_fixed_morale_does_not_block_a_known_training_swap(self):
        self.live[4][1] = None
        emotion = self.morale_policy(fixed=None, training=120)
        self.assertEqual(3, self.manager.rotate_slot.call_count)
        self.assertEqual(150, emotion.training_lower(1))
        emotion.check_reduce(5)

    def test_data_key_popup_stays_ahead_of_rotation_morale_checks(self):
        emotion = self.morale_policy(fixed=0)
        handler = self.popup_handler(emotion)
        handler.handle_use_data_key.return_value = True
        self.assertTrue(InfoHandler.handle_combat_low_emotion(handler))
        handler.handle_popup_confirm.assert_not_called()
        handler.handle_popup_cancel.assert_not_called()

    def test_selected_calculation_preserves_double_book_and_shipwreck_penalty_settings(self):
        emotion = self.morale_policy(fixed=0)
        emotion.map_is_2x_book = True
        emotion.reduce(1)
        self.assertEqual(146, emotion.training_lower(1))
        self.config.Emotion_IgnoreShipwreck = True
        emotion.reduce(1, shipwreck=True)
        self.assertEqual(146, emotion.training_lower(1))
        self.config.Emotion_IgnoreShipwreck = False
        emotion.reduce(1, shipwreck=True)
        self.assertEqual(136, emotion.training_lower(1))

    def test_selected_only_reuses_recovery_reserve_when_no_reserve_ship_is_ready(self):
        for fleet in RULE['sources']:
            self.live[fleet] = dict.fromkeys(range(1, 7), 100)
        self.config.Emotion_MinReserve = 150
        emotion = self.morale_policy(training=100)
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(5)
        self.assertEqual(['1'], self.config.Emotion_RecoveryWait)
        self.assertGreater(self.config.Scheduler_NextRun - datetime.now(), timedelta(minutes=70))

    def test_zero_battle_training_role_does_not_block_selected_only_popup(self):
        self.config.cross_set_many({ROTATION_PATH + '.SelectedOnly': True,
                                    ROTATION_PATH + '.Rules': json.dumps({'1': RULE, '2': RULE}),
                                    'Main.Fleet.FleetOrder': 'fleet1_mob_fleet2_boss'})
        self.live[2][1] = 0
        preflight_rotation(self.runner, 1, 'normal')
        self.assertEqual({2: 2}, self.campaign.emotion.selected)
        self.campaign.emotion.check_reduce(1)
        handler = self.popup_handler(self.campaign.emotion)
        self.assertTrue(InfoHandler.handle_combat_low_emotion(handler))
        handler.handle_popup_cancel.assert_not_called()
        self.manager.rotate_slot.assert_not_called()

    def test_disabling_selected_only_restores_original_task_wait_without_an_early_scan(self):
        self.morale_policy()
        self.config.cross_set(ROTATION_PATH + '.SelectedOnly', False)
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_not_called()
        self.inventory_reader.inventory.assert_called_once_with({1}, slots={1: RULE['slots']})
        self.manager.rotate_slot.assert_not_called()
        with self.assertRaises(ScriptEnd):
            self.campaign.emotion.check_reduce(5)

    def test_equipment_disabled_preserves_original_rotation_even_with_old_equipment_jobs(self):
        job = {'1:4': {'fleet': 1, 'slot': 4}}
        self.config.cross_set(EQUIPMENT_PATH + '.State', job)
        with patch('module.campaign.fleet_rotation.FleetRotationEquipment') as equipment:
            preflight_rotation(self.runner, 5, 'normal')
        equipment.assert_not_called()
        self.assertEqual(self.manager.rotate_slot.call_count, 3)
        self.manager._commit_formation.assert_not_called()
        self.assertEqual(self.config.cross_get(EQUIPMENT_PATH + '.State'), job)

    def test_equipment_order_is_scan_clear_all_swap_all_equip_then_home(self):
        self.config.cross_set(EQUIPMENT_PATH + '.Enabled', True)
        events = []
        self.manager.prepare_rotation.side_effect = lambda fleet, **kwargs: events.append('scan') or self.snapshots()
        self.manager.rotate_slot.side_effect = lambda source, slot, fleet: events.append(('swap', slot)) or self.rotate(source, slot, fleet)
        self.manager._commit_formation.side_effect = lambda: events.append('home')
        equipment = Mock()
        equipment.clear_outgoing.side_effect = lambda fleet, slots: events.append(('clear', fleet, slots))
        equipment.apply_pending.side_effect = lambda: events.append('equip')
        with patch('module.campaign.fleet_rotation.FleetRotationEquipment', return_value=equipment):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(events, ['scan', ('clear', 1, [4, 5, 6]), ('swap', 4), ('swap', 5), ('swap', 6),
                                  'equip', 'home'])

    def test_equipment_pending_is_completed_even_when_actual_morale_is_already_full(self):
        self.live[1] = dict.fromkeys(range(1, 7), 150)
        self.config.cross_set_many({EQUIPMENT_PATH + '.Enabled': True,
                                    EQUIPMENT_PATH + '.State': {'1:4': {'fleet': 1, 'slot': 4}}})
        equipment = Mock()
        equipment.apply_pending.side_effect = lambda: self.config.cross_set(EQUIPMENT_PATH + '.State', {})
        with patch('module.campaign.fleet_rotation.FleetRotationEquipment', return_value=equipment):
            preflight_rotation(self.runner, 5, 'normal')
        equipment.recover_page.assert_called_once()
        equipment.apply_pending.assert_called_once()
        equipment.clear_outgoing.assert_not_called()
        self.manager.rotate_slot.assert_not_called()
        self.manager._commit_formation.assert_called_once()

    def test_equipment_failure_keeps_its_jobs_and_next_run_does_not_swap_healthy_ships(self):
        self.config.cross_set(EQUIPMENT_PATH + '.Enabled', True)
        job = {'1:4': {'fleet': 1, 'slot': 4}}
        equipment = Mock()
        equipment.clear_outgoing.side_effect = lambda *args: self.config.cross_set(EQUIPMENT_PATH + '.State', job)
        equipment.apply_pending.side_effect = FleetManagementError('装备失败')
        with patch('module.campaign.fleet_rotation.FleetRotationEquipment', return_value=equipment):
            with self.assertRaises(FleetManagementError):
                preflight_rotation(self.runner, 5, 'normal')
            self.assertEqual(self.config.cross_get(EQUIPMENT_PATH + '.State'), job)
            self.assertTrue(self.state()['1']['rescan'])
            self.manager.rotate_slot.reset_mock()
            equipment.clear_outgoing.reset_mock()
            equipment.apply_pending.side_effect = lambda: self.config.cross_set(EQUIPMENT_PATH + '.State', {})
            preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_not_called()
        equipment.clear_outgoing.assert_not_called()
        self.assertEqual(self.config.cross_get(EQUIPMENT_PATH + '.State'), {})

    def test_equipment_is_not_touched_when_actual_morale_is_sufficient(self):
        self.config.cross_set(EQUIPMENT_PATH + '.Enabled', True)
        self.live[1] = dict.fromkeys(range(1, 7), 150)
        with patch('module.campaign.fleet_rotation.FleetRotationEquipment') as equipment:
            preflight_rotation(self.runner, 5, 'normal')
        equipment.assert_not_called()

    def test_pausing_rotation_still_finishes_equipment_for_previously_cleared_slots(self):
        self.config.cross_set(EQUIPMENT_PATH + '.Enabled', True)
        equipment = Mock()
        def pause(source, slot, fleet):
            result = self.rotate(source, slot, fleet)
            self.config.cross_set(ROTATION_PATH + '.Enabled', False)
            return result
        self.manager.rotate_slot.side_effect = pause
        with patch('module.campaign.fleet_rotation.FleetRotationEquipment', return_value=equipment):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(self.manager.rotate_slot.call_count, 1)
        equipment.clear_outgoing.assert_called_once_with(1, [4, 5, 6])
        equipment.apply_pending.assert_called_once()
        self.assertTrue(self.state()['1']['paused'])

    def test_real_config_round_saves_three_swaps_and_only_one_reserve_then_calibrates(self):
        self.config.cross_set_many({'Event.Fleet.Fleet1': 1, 'Event.Campaign.Mode': 'normal', 'Event.Campaign.Name': 'a1',
                                    'Main2.Fleet.Fleet1': 4, 'Main2.Campaign.Mode': 'normal',
                                    'Main3.Fleet.Fleet1': 1, 'Main3.Campaign.Mode': 'hard'})
        hard_before = deepcopy(self.service.read_json(self.path)['Main3']['Emotion'])
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual(self.manager.rotate_slot.call_args_list[0].args, (4, 4, 1))
        self.assertEqual([call.args for call in self.manager.rotate_slot.call_args_list],
                         [(4, 4, 1), (4, 5, 1), (4, 6, 1)])
        self.manager.highest_morale_slot.assert_not_called()
        self.manager.prepare_rotation.assert_called_once_with(1, slots=RULE['slots'], scan=False)
        self.manager.read_fleet_morale.assert_not_called()
        self.manager.swap_slots.assert_not_called()
        self.assertEqual(self.state()['1']['last_source'], 4)
        data = self.service.read_json(self.path)
        self.assertEqual(data['Main']['Emotion']['Fleet1Value'], 150)
        self.assertEqual(data['Event']['Emotion']['Fleet1Value'], 150)
        self.assertEqual(data['Main2']['Emotion']['Fleet1Value'], 2)
        self.assertEqual(data['Main3']['Emotion'], hard_before)
        self.assertIsInstance(data['Main']['Emotion']['Fleet1RecoveryState'], dict)
        self.campaign.ensure_campaign_ui.assert_called_once_with(name='12-4', mode='normal', skip_first_screenshot=False)
        self.campaign.map_get_info.assert_called_once()
        # 回到出击流程后仍执行真实 Emotion 的预检，而不是绕过情绪控制。
        self.campaign.emotion.check_reduce(5)

    def test_repeated_low_morale_resorts_actual_source_morale_each_round(self):
        order = []
        for index in range(5):
            self.live[1][4] = 2
            if index == 4:
                self.live[4][4] = 150
            self.config.set_record(Emotion_Fleet1Value=2)
            self.manager.rotate_slot.reset_mock()
            if index:
                self.campaign.emotion.calibrate_selected({1: self.live[1]})
            preflight_rotation(self.runner, 5, 'normal')
            order.append(self.manager.rotate_slot.call_args_list[0].args[0])
            self.assertEqual(self.manager.rotate_slot.call_count, 3)
        self.assertEqual(order, [4, 5, 6, 3, 4])

    def test_new_event_morale_swap_also_full_scans_before_ranking(self):
        preflight_rotation(self.runner, 5, 'normal')
        self.config.cross_set_many({'Event.Campaign.Mode': 'normal', 'Event.Campaign.Name': 'a1',
                                    'Event.Fleet.FleetOrder': 'fleet1_all_fleet2_standby'})
        event_config = AzurLaneConfig('testpilot', task='Event')
        event_config.set_record(Emotion_Fleet1Value=2)
        self.campaign.config = event_config
        self.campaign.emotion = Emotion(event_config)
        self.runner.config = event_config
        self.runner.folder, self.runner.stage = 'event_20261022_cn', 'a1'
        self.manager.rotate_slot.reset_mock()
        self.config = event_config
        self.live[1][4] = 2
        preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(self.manager.rotate_slot.call_args_list[0].args[0], 5)
        self.assertEqual(self.state()['1']['last_source'], 5)
        self.assertEqual(2, self.manager.run.call_count)
        self.assertEqual(2, self.inventory_reader.inventory.call_count)
        self.inventory_reader.inventory.assert_called_with({1}, slots={1: RULE['slots']})

    def test_one_round_still_low_waits_in_original_emotion_check_instead_of_swapping_again(self):
        def rotate(source, slot, fleet):
            self.live[fleet][1] = 2
            return self.rotate(source, slot, fleet)
        self.manager.rotate_slot.side_effect = rotate
        preflight_rotation(self.runner, 5, 'normal')
        with self.assertRaises(ScriptEnd):
            self.campaign.emotion.check_reduce(5)
        self.assertEqual(self.manager.rotate_slot.call_count, 3)
        self.assertEqual(self.state()['1']['last_source'], 4)

    def test_real_campaign_run_and_rotation_service_share_the_actual_emotion_preflight(self):
        from module.campaign.campaign_base import CampaignBase
        campaign = CampaignBase.__new__(CampaignBase)
        campaign.__dict__.update(vars(self.campaign))
        self.runner.campaign = campaign
        campaign._map_battle = 5
        campaign.ENTRANCE = SimpleNamespace(area=None, button=(1, 2, 3, 4))
        campaign._fleet_rotation_preflight = lambda battle: preflight_rotation(self.runner, battle, 'normal')
        campaign.enter_map = Mock()
        campaign.map_is_auto_search = True
        campaign.MAP = object()
        campaign.lv_reset = campaign.lv_get = Mock()
        campaign.auto_search_execute_a_battle = Mock(side_effect=CampaignEnd)
        campaign.AUTO_SEARCH_WITHDRAW = False
        self.assertTrue(campaign.run())
        self.assertEqual(self.manager.rotate_slot.call_count, 3)
        self.assertEqual(campaign.emotion.fleet_1.value, 150)
        campaign.enter_map.assert_called_once()

    def test_disabled_and_hard_modes_do_not_construct_game_controller(self):
        self.config.cross_set(ROTATION_PATH + '.Enabled', False)
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.config.cross_set(ROTATION_PATH + '.Enabled', True)
        self.assertFalse(preflight_rotation(self.runner, 5, 'hard'))
        self.runner.folder = 'war_archives_20261022_cn'
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.factory.assert_not_called()

    def test_healthy_morale_keeps_fleet_and_does_not_advance_reserve(self):
        self.config.set_record(Emotion_Fleet1Value=150)
        self.live[1][4] = 150
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.rotate_slot.assert_not_called()
        self.manager.read_fleet_morale.assert_not_called()
        self.assertEqual(self.state(), {})
        self.manager.run.assert_not_called()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_not_called()

    def test_low_ledger_with_actual_150_calibrates_without_swapping(self):
        self.live[1][4] = 150
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.rotate_slot.assert_not_called()
        self.assertEqual(self.service.read_json(self.path)['Main']['Emotion']['Fleet1Value'], 150)
        self.campaign.emotion.check_reduce(5)

    def test_low_full_fleet_ledger_does_not_trigger_swapping_healthy_selected_slots(self):
        self.live[1][4] = 150
        preflight_rotation(self.runner, 5, 'normal')
        self.config.set_record(Emotion_Fleet1Value=2)
        self.manager.prepare_rotation.reset_mock()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.prepare_rotation.assert_not_called()
        self.inventory_reader.inventory.assert_called_once_with({1}, slots={1: RULE['slots']})
        self.manager.rotate_slot.assert_not_called()
        self.manager.run.assert_not_called()
        with self.assertRaises(ScriptEnd):
            self.campaign.emotion.check_reduce(5)
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.assertLess(self.service.read_json(self.path)['Main']['Emotion']['Fleet1Value'], 150)

    def test_dispatching_other_task_preserves_the_main_scan_clock(self):
        from alas import AzurLaneAutoScript

        self.live[1][4] = 150
        script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        script.config = self.config
        script.device = Mock()
        script._channel_float_done = True
        script.commission = Mock()
        self.runner.run = Mock(side_effect=lambda **kwargs: preflight_rotation(self.runner, 5, 'normal'))
        with (patch('module.runtime.preview.set_task'),
              patch('module.campaign.run.CampaignRun', return_value=self.runner)):
            self.assertTrue(script._run('main', skip_first_screenshot=True))
            self.assertTrue(script._run('main', skip_first_screenshot=True))
            self.manager.run.assert_not_called()
            self.assertTrue(script._run('commission', skip_first_screenshot=True))
            self.assertTrue(script._run('main', skip_first_screenshot=True))
        self.assertEqual(self.manager.run.call_count, 0)
        self.assertIs(self.runner._fleet_rotation_context, script._fleet_rotation_context)
        self.manager.rotate_slot.assert_not_called()

    def test_no_selected_slots_does_not_trigger_an_automatic_scan(self):
        self.config.cross_set(ROTATION_PATH + '.Rules', '{}')
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_not_called()
        self.manager.rotate_slot.assert_not_called()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_not_called()

    def test_unknown_optional_reference_in_ignore_mode_does_not_block_original_farming(self):
        self.config.cross_set('Main.Emotion.Mode', 'ignore')
        self.config.set_record(Emotion_Fleet1Value=150)
        self.live[1][4] = None
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.rotate_slot.assert_not_called()
        self.campaign.emotion.check_reduce(5)

    def test_ignore_calculation_mode_uses_fresh_measurement_instead_of_stale_healthy_value(self):
        self.config.cross_set('Main.Emotion.Mode', 'ignore')
        self.config.set_record(Emotion_Fleet1Value=150)
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual(self.manager.rotate_slot.call_count, 3)

    def test_double_book_cost_and_runtime_book_flag_survive_emotion_refresh(self):
        self.config.cross_set('Main.Emotion.Fleet1Control', 'prevent_red_face')
        self.config.set_record(Emotion_Fleet1Value=15)
        self.live[1][4] = 15
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.rotate_slot.assert_not_called()
        self.campaign.emotion.map_is_2x_book = True
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertTrue(self.campaign.emotion.map_is_2x_book)

    def test_zero_battle_role_does_not_rotate_even_if_its_morale_is_low(self):
        self.config.cross_set('Main.Fleet.FleetOrder', 'fleet1_mob_fleet2_boss')
        self.assertFalse(preflight_rotation(self.runner, 1, 'normal'))
        self.manager.run.assert_not_called()
        self.manager.read_fleet_morale.assert_not_called()
        self.manager.rotate_slot.assert_not_called()

    def test_interrupted_swap_auto_clears_error_and_rescans_without_repeating_recovered_slot(self):
        def interrupted(source, slot, fleet):
            self.rotate(source, slot, fleet)
            raise GameStuckError('模拟互换后核对中断')
        self.manager.rotate_slot.side_effect = interrupted
        with self.assertRaises(FleetManagementError):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(self.state()['1'], {'rescan': True})
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_called_once()
        self.assertEqual(self.manager.run.call_count, 1)
        self.assertEqual(2, self.inventory_reader.inventory.call_count)
        self.inventory_reader.inventory.assert_called_with({1}, slots={1: RULE['slots']})
        self.assertEqual(self.state(), {})

    def test_recovery_only_swaps_still_low_slots_and_does_not_repeat_the_completed_one(self):
        self.live[1][5] = 2

        def interrupted(source, slot, fleet):
            self.rotate(source, slot, fleet)
            raise GameStuckError('第一位互换已生效，刷新期间中断')

        self.manager.rotate_slot.side_effect = interrupted
        with self.assertRaises(FleetManagementError):
            preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.reset_mock()
        self.manager.rotate_slot.side_effect = self.rotate
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_called_once_with(5, 5, 1)
        self.assertNotIn('rescan', self.state()['1'])

    def test_morale_recovery_includes_slots_exactly_at_the_reserve(self):
        self.config.cross_set_many({ROTATION_PATH + '.SelectedOnly': True,
                                   ROTATION_PATH + '.State': {'1': {'rescan': True}},
                                   'Main.Emotion.Fleet1Control': 'keep_exp_bonus'})
        self.live[1][4] = 130
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_called_once_with(update_emotion=True)
        self.manager.rotate_slot.assert_called_once_with(4, 4, 1)

    def test_fleet_six_with_morale_twelve_uses_one_snapshot_and_swaps_slots_one_then_four(self):
        self.live[1] = dict.fromkeys(range(1, 7), 150)
        self.live[6][1] = self.live[6][4] = 12
        self.config.cross_set_many({'Main.Fleet.Fleet1': 6,
            ROTATION_PATH + '.Rules': json.dumps({'6': {'slots': [1, 4], 'sources': [1, 3, 4, 5]}})})
        self.campaign.emotion = Emotion(self.config)
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.prepare_rotation.assert_called_once_with(6, slots=[1, 4], scan=False)
        self.assertEqual([call.args for call in self.manager.rotate_slot.call_args_list], [(1, 1, 6), (1, 4, 6)])
        self.manager.read_fleet_morale.assert_not_called()
        self.manager.swap_slots.assert_not_called()
        self.assertEqual(self.config.Emotion_Fleet1Value, 150)

    def test_other_task_using_an_unfinished_reserve_refreshes_instead_of_staying_blocked(self):
        progress = begin_round(RULE, {})
        progress['pending'] = {'slot': 3, 'source_slot': 1}
        self.config.cross_set_many({ROTATION_PATH + '.State': {'1': progress}, 'Main.Fleet.Fleet1': 3})
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.run.assert_not_called()
        self.manager.rotate_slot.assert_not_called()
        self.assertEqual(self.config.Emotion_Fleet1Value, 138)
        self.assertEqual(self.state(), {})

    def test_disabling_during_a_round_stops_after_current_swap_and_saves_completed_slots(self):
        def disable(*args):
            snapshots = self.rotate(*args)
            self.config.cross_set(ROTATION_PATH + '.Enabled', False)
            return snapshots
        self.manager.rotate_slot.side_effect = disable
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_called_once_with(4, 4, 1)
        self.assertEqual(self.state()['1']['done'], [4])
        self.assertEqual(self.state()['1']['source'], 4)
        self.assertIsNone(self.state()['1']['pending'])

    def test_completed_swaps_with_unknown_final_morale_auto_rescan_without_replacing_again(self):
        def unknown(source, slot, fleet):
            snapshots = self.rotate(source, slot, fleet)
            if slot == 6:
                snapshots[fleet][1] = None
            return snapshots
        self.manager.rotate_slot.side_effect = unknown
        with self.assertRaises(FleetManagementError):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(self.state()['1'], {'rescan': True})
        self.manager.rotate_slot.reset_mock()
        self.manager.rotate_slot.side_effect = self.rotate
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_not_called()
        self.assertEqual(self.state(), {})

    def test_api_persists_switch_rules_and_reset_but_rejects_invalid_rule_or_state_write(self):
        changes = [ConfigChange(path=ROTATION_PATH + '.Enabled', value=False),
                   ConfigChange(path=ROTATION_PATH + '.SelectedOnly', value=True),
                   ConfigChange(path=ROTATION_PATH + '.Rules', value=json.dumps({'1': RULE}))]
        saved = self.service.patch('testpilot', None, changes)['values']['FleetInfo']['FleetRotation']
        self.assertFalse(saved['Enabled'])
        self.assertTrue(saved['SelectedOnly'])
        self.assertEqual(json.loads(saved['Rules'])['1'], RULE)
        for path, value in ((ROTATION_PATH + '.Rules', '{"1":{"sources":[1]}}'),
                            (ROTATION_PATH + '.State', {'1': {'last_source': 6}})):
            with self.assertRaises(ApiError):
                self.service.patch('testpilot', None, [ConfigChange(path=path, value=value)])
        self.service.patch('testpilot', None, [ConfigChange(path=ROTATION_PATH + '.State', value={})])
        self.assertEqual(self.state(), {})
        self.assertNotIn('FleetRotation', self.service.args)


class CampaignEntryTests(unittest.TestCase):
    def test_real_campaign_base_checks_rotation_before_emotion_and_enter_map(self):
        from module.campaign.campaign_base import CampaignBase
        campaign = CampaignBase.__new__(CampaignBase)
        campaign.config = SimpleNamespace(Campaign_Mode='normal')
        campaign.ENTRANCE = SimpleNamespace(area=None, button=(1, 2, 3, 4))
        campaign._map_battle = 5
        order = []
        campaign.map_get_info = lambda: order.append('map')
        campaign._fleet_rotation_preflight = lambda battle: order.append(('rotate', battle))
        campaign.emotion = SimpleNamespace(check_reduce=lambda battle: order.append(('emotion', battle)))
        campaign.enter_map = lambda *args, **kwargs: order.append('enter')
        campaign.map_is_auto_search = True
        campaign.MAP = object()
        campaign.lv_reset = campaign.lv_get = Mock()
        campaign.auto_search_execute_a_battle = Mock(side_effect=CampaignEnd)
        campaign.AUTO_SEARCH_WITHDRAW = False
        self.assertTrue(campaign.run())
        self.assertEqual(order, ['map', ('rotate', 5), ('emotion', 5), 'enter'])


if __name__ == '__main__':
    unittest.main()
