"""七种培养组合、可靠实读、逐船记录与中断恢复，不连接账号。"""

from copy import deepcopy
from datetime import timedelta
from itertools import product
from pathlib import Path
import json
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.api.protocol import ConfigChange, ApiError, RevisionParams
from module.campaign.fleet_rotation import preflight_rotation
from module.campaign.fleet_training import after_battle_due, recover_reading
from module.combat.emotion import Emotion
from module.config.config import AzurLaneConfig
from module.config.time_source import now
from module.exception import CampaignEnd, FleetManagementError, GameStuckError, ScriptEnd
from module.os.ship_exp import ShipLevel
from module.awaken.assets import OCR_SHIP_LEVEL
from module.retire.fleet_training import AffinityReader, FleetTrainingReader, TrainingExp, parse_affinity, training_level
from module.os.ship_exp_data import LIST_SHIP_EXP
from module.runtime.fleet_rotation import ROTATION_PATH
from module.runtime.fleet_training import (LEVEL_PATH, AFFINITY_PATH, TRAINING_PATH, INTERVAL_PATH, completed,
                                           FULL_RECORD_PATH, excluded, goals, due,
                                           identity, interval, observe, state)
from module.runtime.mind_calculator import catalog
from types import SimpleNamespace
from unittest.mock import Mock
import tests.test_fleet_rotation as rotation_cases


class TrainingRuleTests(unittest.TestCase):
    def test_confirmed_long_name_uses_the_same_bounded_correction_as_formation_scanning(self):
        name = '阿尔弗雷多·奥里亚尼'
        ship = dict(name=name, raw_name='阿尔弗雷多·奥里亚', level=105, slot=4, review=False)
        result = {'vanguard': {'1': [ship]}}
        for raw in ('阿尔弗雷多·奥里亚', '阿尔弗雷多·奥..', 'J尔弗雷多·奥里亚尼', name):
            with self.subTest(raw=raw):
                ship['raw_name'] = raw
                self.assertEqual(name, identity(ship, result))
        for raw in ('花月', '阿', '完全未知舰船'):
            with self.subTest(raw=raw):
                ship['raw_name'] = raw
                self.assertIsNone(identity(ship, result))
        ship.update(raw_name=name, review=True)
        self.assertIsNone(identity(ship, result))
        ship['review'] = False
        result['vanguard']['4'] = [dict(ship)]
        self.assertIsNone(identity(ship, result))
        self.assertEqual(name, identity(ship, result, allow_duplicates=True))

    def test_inventory_always_reads_names_and_morale_from_dock_before_training(self):
        from module.retire.fleet_management import FleetManagement
        saved = {}
        config = SimpleNamespace(cross_get=lambda path, default=None: saved.get(path, default))
        manager = Mock(config=config, RESULT_PATH='FleetInfo.FleetInfo.Result')
        manager._save_result.side_effect = lambda result: saved.update({manager.RESULT_PATH: deepcopy(result)})
        manager._capture_formation.return_value = (object(), {}, {})
        formation = {slot: dict(slot=slot, occupied=slot in (1, 4), name=f'参考舰船{slot}', level=100)
                     for slot in range(1, 7)}
        def scan(category, **kwargs):
            for ship in saved[manager.RESULT_PATH][category]['5']:
                ship.update(name=f'已确认舰船{ship["slot"]}', emotion=145)
        manager._formation_visible.return_value = False
        manager._scan_rotation_category.side_effect = scan
        manager.prepare_rotation.side_effect = lambda fleet, **kwargs: FleetManagement.prepare_rotation(manager, fleet, **kwargs)
        reader = FleetTrainingReader.__new__(FleetTrainingReader)
        reader.manager, reader.config = manager, config
        with patch('module.retire.fleet_training.FormationDetailScanner') as scanner:
            scanner.return_value.scan.return_value = formation
            result = reader.inventory({5})
        manager.prepare_rotation.assert_called_once_with(5, slots=None, fleets={5})
        self.assertEqual([((4,), {}), ((1,), {})], manager._open_slot.call_args_list)
        manager.finish_rotation.assert_called_once()
        self.assertEqual('已确认舰船1', result['main']['5'][0]['name'])
        self.assertEqual(145, result['vanguard']['5'][0]['emotion'])

    def test_observe_keeps_confirmed_position_and_zero_morale_without_changing_completion(self):
        saved = {'records': {}}
        self.assertTrue(observe(saved, '舰船A', {'level': 120}, {'level': 120}, fleet=2, slot=6, emotion=0))
        record = saved['records']['舰船A']
        self.assertEqual((2, 6, 0), (record['fleet'], record['slot'], record['emotion']))
        observe(saved, '舰船A', {'affinity': 50}, {'affinity': 100})
        record = saved['records']['舰船A']
        self.assertEqual((2, 6, 0), (record['fleet'], record['slot'], record['emotion']))
        observe(saved, '舰船A', {'level': 120}, {'level': 120}, fleet=3, slot=6, emotion=None)
        self.assertEqual(3, saved['records']['舰船A']['fleet'])
        self.assertIsNone(saved['records']['舰船A']['emotion'])
        self.assertEqual({'level': 120}, saved['records']['舰船A']['completed_for'])

    def test_unbounded_hours_do_not_overflow_when_no_candidate_delays_the_task(self):
        from datetime import datetime
        from module.campaign.fleet_training import TrainingSession
        session = TrainingSession.__new__(TrainingSession)
        session.config = Mock()
        session.context, session.targets = {}, {}
        session.checking_targets = False
        session.config.cross_get.side_effect = lambda path, default: True if path.endswith('.Enabled') else 1e20
        session.save = Mock()
        with self.assertRaises(ScriptEnd), patch('module.campaign.fleet_training.mark_checked'):
            session.delay('候补不足')
        session.config.task_delay.assert_called_once_with(target=datetime.max)

    def test_training_exp_distinguishes_unknown_from_actual_zero_without_changing_shared_reader(self):
        from module.awaken.assets import OCR_SHIP_EXP
        reader = TrainingExp(OCR_SHIP_EXP)
        for text, expected in (('0/Max', 0), ('23456/120000', 23456), ('3000000/M', 3000000),
                               ('无法识别', None), ('', None), ([], None)):
            with self.subTest(text=text), patch('module.retire.fleet_training.Ocr.ocr', return_value=text):
                self.assertEqual(expected, reader.ocr(None))

    def test_effective_level_reuses_opsi_experience_table_for_the_reported_locked_ships(self):
        for exp in (1917866, 1930058, 1919750):
            with self.subTest(exp=exp):
                self.assertEqual(120, training_level(105, exp))
                self.assertGreaterEqual(LIST_SHIP_EXP[104] + exp, LIST_SHIP_EXP[119])
        for target in (105, 110, 120, 125):
            required = LIST_SHIP_EXP[target - 1] - LIST_SHIP_EXP[99]
            self.assertEqual(target, training_level(100, required))
            self.assertEqual(target - 1, training_level(100, required - 1))
        for exp in (None, -1, True, '1917866'):
            self.assertEqual(105, training_level(105, exp))
        self.assertEqual(105, training_level(105, 0))
        self.assertEqual(125, training_level(125, 3000000))
        for level in (0, 126, None, True):
            self.assertIsNone(training_level(level, 3000000))

    def test_detail_reader_confirms_exp_twice_and_keeps_displayed_level_for_reference(self):
        reader = FleetTrainingReader.__new__(FleetTrainingReader)
        reader.manager = SimpleNamespace(RESULT_PATH='FleetInfo.FleetInfo.Result')
        reader.config = SimpleNamespace(SERVER='cn', cross_get=Mock(return_value={
            'vanguard': {'1': [{'slot': 4, 'level': 105}]}}))
        reader.device = SimpleNamespace(image=None)
        reader._details = reader._back_to_details = reader._back_to_formation = Mock()
        reader._ship = reader.appear = Mock(return_value=True)
        reader.loop = Mock(return_value=iter(range(3)))
        with (patch('module.retire.fleet_training.ShipLevel') as levels,
              patch('module.retire.fleet_training.TrainingExp') as experience):
            levels.return_value.ocr.return_value = 105
            experience.return_value.ocr.side_effect = [3000000, 1917866, 1917866]
            self.assertEqual({4: {'level': 120, 'display_level': 105, 'exp': 1917866}},
                             reader.read(1, [4], {'level': 120}))
            self.assertEqual(3, experience.return_value.ocr.call_count)

    def test_observe_persists_exact_experience_without_changing_completion(self):
        saved = {'records': {}}
        self.assertFalse(observe(saved, '舰船A', {'level': 119, 'exp': 23456, 'affinity': 98},
                                 {'level': 120, 'affinity': 100}))
        self.assertEqual(23456, saved['records']['舰船A']['exp'])
        self.assertTrue(observe(saved, '舰船A', {'level': 120, 'exp': 0, 'affinity': 100},
                                {'level': 120, 'affinity': 100}))
        self.assertEqual(0, saved['records']['舰船A']['exp'])
        self.assertEqual({'level': 120, 'affinity': 100}, saved['records']['舰船A']['completed_for'])
        observe(saved, '舰船A', {'affinity': 101}, {'affinity': 120})
        self.assertEqual(0, saved['records']['舰船A']['exp'])
        observe(saved, '舰船B', {'level': 99}, {'level': 120})
        self.assertIsNone(saved['records']['舰船B']['exp'])

    def test_same_batch_candidate_reads_return_to_details_and_leave_formation_once(self):
        reader = FleetTrainingReader.__new__(FleetTrainingReader)
        reader.config = SimpleNamespace(SERVER='cn')
        reader._details, reader._back_to_details, reader._back_to_formation = Mock(), Mock(), Mock()
        reader._ship, reader.appear = Mock(return_value=True), Mock(return_value=True)
        with reader.reuse_details():
            reader.read(3, [4], {})
            reader.read(3, [5], {})
            reader._back_to_formation.assert_not_called()
        self.assertEqual([((4,), {}), ((5,), {})], reader._ship.call_args_list)
        self.assertEqual(2, reader._back_to_details.call_count)
        reader._back_to_formation.assert_called_once()
        reader.read(3, [6], {})
        self.assertEqual(2, reader._back_to_formation.call_count)

    def test_affinity_navigation_waits_for_two_fresh_matching_values(self):
        reader = FleetTrainingReader.__new__(FleetTrainingReader)
        reader.device = SimpleNamespace(image=None, click=Mock())
        reader.loop = Mock(return_value=iter(range(3)))
        reader.appear = Mock(side_effect=[True, False])
        reader.ui_click = Mock()
        with patch('module.retire.fleet_training.AffinityReader') as factory:
            factory.return_value.read.side_effect = [None, 50, 50]
            self.assertEqual(50, reader._affinity())
        reader.device.click.assert_called_once()
        reader.ui_click.assert_called_once()

    def test_recover_known_affinity_and_detail_pages(self):
        reader = FleetTrainingReader.__new__(FleetTrainingReader)
        reader.config = SimpleNamespace(cross_get=lambda *args: {})
        reader.device = SimpleNamespace(image=None, has_cached_image=True)
        reader.appear = Mock(side_effect=[False, True, True])
        reader.ui_click = Mock()
        reader._back_to_details = Mock()
        reader._back_to_formation = Mock()
        with patch('module.retire.fleet_training.AffinityReader') as factory:
            factory.return_value.read.return_value = 100
            reader.recover_page()
        reader.ui_click.assert_called_once()
        reader._back_to_details.assert_called_once()
        reader._back_to_formation.assert_called_once()

    def test_seven_modes_and_all_conditions_belong_to_one_ship(self):
        for mood, level, affinity in product((False, True), repeat=3):
            if not (mood or level or affinity):
                continue
            targets = dict(([('level', 120)] if level else []) + ([('affinity', 100)] if affinity else []))
            self.assertEqual(bool(targets), completed({'level': 120, 'affinity': 100}, targets))
            if level:
                self.assertFalse(completed({'level': 119, 'affinity': 100}, targets))
            if affinity:
                self.assertFalse(completed({'level': 125, 'affinity': 99}, targets))

    def test_unknown_or_old_affinity_cannot_combine_with_new_level(self):
        saved = {'records': {}}
        targets = {'level': 120, 'affinity': 100}
        self.assertFalse(observe(saved, '舰船A', {'level': 119, 'affinity': 100}, targets))
        self.assertFalse(observe(saved, '舰船A', {'level': 120}, targets))
        self.assertIsNone(saved['records']['舰船A']['affinity'])
        self.assertFalse(observe(saved, '舰船B', {'level': 1, 'affinity': 200}, targets))
        self.assertTrue(observe(saved, '舰船A', {'level': 120, 'affinity': 100}, targets))
        self.assertFalse(excluded(saved['records']['舰船B'], targets))
        self.assertTrue(excluded(saved['records']['舰船A'], dict(targets, level=125)))

    def test_affinity_parser_never_reads_the_fixed_100_as_current_value(self):
        for value in (0, 8, 37, 50, 99, 100, 200):
            self.assertEqual(value, parse_affinity(f'好感度达到100（当前{value}）'))
        for text in ('已达成', '好感度达到100', '当前100', '好感度达到100(当前201)', '好感度达到100(当前1'):
            self.assertIsNone(parse_affinity(text))
        self.assertEqual(91, parse_affinity('正好感度达到100(当前91)'))
        self.assertIsNone(parse_affinity('好感度达到100(当前60)好感度达到100(当前91)'))

    def test_original_affinity_crops_include_white_gold_and_alternate_certificate(self):
        reader = AffinityReader()
        for value in (8, 37, 50, 60, 91, 100, 200):
            with self.subTest(value=value):
                pixels = np.asarray(Image.open(Path('tests/fixtures/fleet_training') / f'affinity_{value}.png'))
                self.assertEqual(value, reader.read(pixels))

    def test_original_level_crops_reuse_opsi_reader(self):
        reader = ShipLevel(OCR_SHIP_LEVEL)
        for value in (56, 99, 100, 105, 120, 125):
            with self.subTest(value=value):
                pixels = np.asarray(Image.open(Path('tests/fixtures/fleet_training') / f'level_{value}.png'))
                self.assertEqual(value, reader.ocr(pixels))


class TrainingIntegrationTests(unittest.TestCase):
    def test_morale_candidate_read_failure_does_not_reset_the_graduation_clock(self):
        self.configure(mood=True, affinity=True)
        self.config.cross_set_many({ROTATION_PATH + '.SelectedOnly': True,
                                   'Main.Emotion.Fleet1Control': 'keep_exp_bonus'})
        preflight_rotation(self.runner, 5, 'normal')
        checked = self.runner._fleet_rotation_context['training_checked_at']
        self.campaign.emotion.calibrate_selected({1: dict.fromkeys(range(1, 7), 130)})
        self.live[1][4] = 130
        self.profile[self.names[3, 4]]['affinity'] = None
        with self.assertRaises(ScriptEnd):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(checked, self.runner._fleet_rotation_context['training_checked_at'])
        self.manager.rotate_slot.assert_not_called()

    def test_morale_reaching_reserve_triggers_full_scan_without_waiting_for_graduation(self):
        self.configure(mood=True, level=True, affinity=True)
        self.config.cross_set_many({ROTATION_PATH + '.SelectedOnly': True,
                                   'Main.Emotion.Fleet1Control': 'keep_exp_bonus'})
        preflight_rotation(self.runner, 5, 'normal')
        checked = self.runner._fleet_rotation_context['training_checked_at']
        self.campaign.emotion.calibrate_selected({1: dict.fromkeys(range(1, 7), 130)})
        self.live[1][4] = 130
        self.read_calls.clear()
        self.manager.run.reset_mock()
        self.campaign._map_battle = 5
        self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
        self.assertTrue(after_battle_due(self.runner, 'normal'))
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_called_once_with(update_emotion=True)
        self.manager.rotate_slot.assert_called_once_with(3, 4, 1)
        self.assertTrue(all(fleet == 3 for fleet, _, _ in self.read_calls))
        self.assertEqual(checked, self.runner._fleet_rotation_context['training_checked_at'])
        self.assertFalse(excluded(state(self.config)['records'][self.initial_names[1, 4]], goals(self.config)))

    def test_each_graduation_swap_full_scans_even_when_the_previous_scan_was_recent(self):
        self.configure()
        self.config.cross_set(ROTATION_PATH + '.Rules', json.dumps({'1': {'slots': [4], 'sources': [3, 4]}}))
        for _ in range(2):
            self.profile[self.names[1, 4]]['level'] = 120
            context = self.runner.__dict__.get('_fleet_rotation_context', {})
            if 'training_checked_at' in context:
                context['training_checked_at'] -= timedelta(hours=6, seconds=1)
            self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual(2, self.manager.run.call_count)
        self.assertEqual(2, self.manager.rotate_slot.call_count)
        self.assertEqual([3, 4], [call.args[0] for call in self.manager.rotate_slot.call_args_list])

    def test_refresh_state_clears_all_display_data_and_keeps_user_settings(self):
        from module.api.router import Router
        self.configure(affinity=True)
        preflight_rotation(self.runner, 5, 'normal')
        before = self.service.get('testpilot')
        router = Router(self.service, SimpleNamespace(manager=lambda _: SimpleNamespace(alive=False)))
        result = router.reset_fleet_training(RevisionParams(instance='testpilot', revision=before['revision']))
        fleet, original = result['values']['FleetInfo'], before['values']['FleetInfo']
        self.assertEqual({}, fleet['FleetTraining']['State'])
        self.assertEqual({}, fleet['FleetInfo']['Result'])
        self.assertEqual({}, fleet['FleetRotation']['State'])
        self.assertEqual('2020-01-01 00:00:00', fleet['FleetTraining']['FullScanRecord'])
        for group in ('FleetLevelTraining', 'FleetAffinityTraining', 'FleetEquipment'):
            self.assertEqual(original[group], fleet[group])
        for field in ('Enabled', 'SelectedOnly', 'Rules'):
            self.assertEqual(original['FleetRotation'][field], fleet['FleetRotation'][field])
        self.assertEqual(original['FleetTraining']['CheckIntervalHours'], fleet['FleetTraining']['CheckIntervalHours'])
        self.assertTrue(router.methods['fleetTraining.reset'].mutates)
        with self.assertRaises(ApiError):
            self.service.patch('testpilot', result['revision'], [ConfigChange(path=TRAINING_PATH, value={})])

    def test_first_graduation_after_refresh_rechecks_duplicate_identity_in_the_full_scan(self):
        self.configure()
        name = self.names[1, 4]
        self.profile[name]['level'] = 120
        self.names[4, 4] = name
        self.service.reset_fleet_training('testpilot', self.service.get('testpilot')['revision'])
        self.restart_task()
        with self.assertRaisesRegex(ScriptEnd, '身份无法唯一确认'):
            preflight_rotation(self.runner, 5, 'normal')
        self.manager.run.assert_called_once_with(update_emotion=True)
        self.manager.rotate_slot.assert_not_called()
        self.assertFalse(excluded(state(self.config)['records'][name], goals(self.config)))

    def test_refresh_state_rejects_running_and_stale_requests_without_writes(self):
        from module.api.router import Router
        self.configure()
        router = Router(self.service, SimpleNamespace(manager=lambda _: SimpleNamespace(alive=True)))
        before = self.path.read_bytes()
        with self.assertRaises(ApiError) as error:
            router.reset_fleet_training(RevisionParams(instance='testpilot', revision=self.service.get('testpilot')['revision']))
        self.assertEqual('INSTANCE_RUNNING', error.exception.code)
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(ApiError) as error:
            self.service.reset_fleet_training('testpilot', '过期版本')
        self.assertEqual('CONFLICT', error.exception.code)
        self.assertEqual(before, self.path.read_bytes())

    def test_refresh_state_clears_interrupted_operations_without_recovering_them(self):
        self.configure()
        for path, pending in ((TRAINING_PATH, {'pending': {'1:4': {'fleet': 1}}}),
                              (TRAINING_PATH, {'reading': {'fleet': 1}}),
                              ('FleetInfo.FleetEquipment.State', {'1:4': {'fleet': 1, 'slot': 4}}),
                              (ROTATION_PATH + '.State', {'1': {'source': 3}}),
                              (ROTATION_PATH + '.State', {'1': {'pending': {'slot': 4}}})):
            clean = {TRAINING_PATH: {}, ROTATION_PATH + '.State': {}, 'FleetInfo.FleetEquipment.State': {}}
            clean[path] = pending
            self.config.cross_set_many(clean)
            before = self.service.get('testpilot')
            with self.subTest(path=path, pending=pending):
                result = self.service.reset_fleet_training('testpilot', before['revision'])
                fleet, original = result['values']['FleetInfo'], before['values']['FleetInfo']
                for group in ('FleetTraining', 'FleetRotation', 'FleetEquipment'):
                    self.assertEqual({}, fleet[group]['State'])
                    self.assertEqual({key: value for key, value in original[group].items()
                                      if key not in ('State', 'FullScanRecord')},
                                     {key: value for key, value in fleet[group].items()
                                      if key not in ('State', 'FullScanRecord')})
                self.assertEqual({}, fleet['FleetInfo']['Result'])
                self.assertEqual(result, self.service.get('testpilot'))
        self.manager.rotate_slot.assert_not_called()

    def setUp(self):
        rotation_cases.RotationIntegrationTests.setUp(self)
        self.stack.enter_context(patch('module.campaign.fleet_training.FleetManagement', return_value=self.manager))
        self.initial_names = {(fleet, slot): name for (fleet, slot), name in zip(
            ((f, s) for f in range(1, 7) for s in range(1, 7)), catalog()['ships'])}
        self.names = dict(self.initial_names)
        self.profile = {name: dict(level=80, affinity=50) for name in self.names.values()}
        self.manager.RESULT_PATH = 'FleetInfo.FleetInfo.Result'
        self.read_calls = []
        self.inventory_calls = []
        self.training_events = []
        outer = self

        class Reader:
            def __init__(self, manager):
                self.manager = manager

            def reuse_details(self):
                from contextlib import nullcontext
                return nullcontext()

            def inventory(self, fleets, **kwargs):
                outer.training_events.append(('inventory', set(fleets)))
                outer.inventory_calls.append(set(fleets))
                outer.full_scan(fleets=fleets)
                return outer.config.cross_get(self.manager.RESULT_PATH)

            def read(self, fleet, slots, targets):
                outer.training_events.append(('read', fleet, list(slots)))
                outer.read_calls.append((fleet, list(slots), dict(targets)))
                readings = {}
                for slot in slots:
                    profile = outer.profile[outer.names[fleet, slot]]
                    reading = {metric: profile.get(metric) for metric in targets}
                    if 'level' in targets:
                        reading.update(level=training_level(profile['level'], profile.get('exp')),
                                       display_level=profile['level'], exp=profile.get('exp'))
                    readings[slot] = reading
                return readings
        self.reader_factory = self.stack.enter_context(patch('module.campaign.fleet_training.FleetTrainingReader', Reader))

    def full_scan(self, fleets=range(1, 7), **kwargs):
        result = deepcopy(self.config.cross_get(self.manager.RESULT_PATH, {}))
        for category, slots in (('main', (1, 2, 3)), ('vanguard', (4, 5, 6))):
            result.setdefault(category, {}).update({str(fleet): [dict(slot=slot, name=self.names[fleet, slot],
                   level=self.profile[self.names[fleet, slot]]['level'], occupied=True, review=False,
                   emotion=self.live[fleet][slot]) for slot in slots] for fleet in fleets})
        self.config.cross_set('FleetInfo.FleetInfo.Result', result)

    def snapshots(self):
        self.full_scan()
        return deepcopy(self.live)

    def rotate(self, source, slot, fleet):
        self.names[source, slot], self.names[fleet, slot] = self.names[fleet, slot], self.names[source, slot]
        self.live[source][slot], self.live[fleet][slot] = self.live[fleet][slot], self.live[source][slot]
        return self.snapshots()

    readings = rotation_cases.RotationIntegrationTests.readings

    def configure(self, mood=False, level=True, affinity=False, slots=(4,)):
        self.config.cross_set_many({ROTATION_PATH + '.Enabled': mood,
                                   ROTATION_PATH + '.Rules': json.dumps({'1': {'slots': list(slots), 'sources': [3]}}),
                                   ROTATION_PATH + '.State': {}, TRAINING_PATH: {}, FULL_RECORD_PATH: now(),
                                   INTERVAL_PATH: 6,
                                   LEVEL_PATH + '.Enabled': level, LEVEL_PATH + '.Target': 120,
                                   AFFINITY_PATH + '.Enabled': affinity, AFFINITY_PATH + '.Target': 100})
        self.names = dict(self.initial_names)
        self.profile = {name: dict(level=80, affinity=50) for name in self.names.values()}
        self.live = {fleet: dict.fromkeys(range(1, 7), 150) for fleet in range(1, 7)}
        self.runner.__dict__.pop('_fleet_rotation_context', None)
        self.campaign.emotion = Emotion(self.config)
        self.manager.rotate_slot.reset_mock()
        self.read_calls.clear()
        self.inventory_calls.clear()
        self.full_scan()

    def test_seven_modes_execute_completion_or_temporary_swap_without_conflating_them(self):
        for mood, level, affinity in product((False, True), repeat=3):
            if not (mood or level or affinity):
                continue
            with self.subTest(mood=mood, level=level, affinity=affinity):
                self.configure(mood, level, affinity)
                name = self.names[1, 4]
                self.profile[name] = dict(level=120, affinity=100)
                if mood:
                    self.live[1][4] = 2
                preflight_rotation(self.runner, 5, 'normal')
                self.manager.rotate_slot.assert_called_once_with(3, 4, 1)
                saved = state(self.config)['records'].get(name, {})
                self.assertEqual(level or affinity, excluded(saved, goals(self.config)))
                if not level and not affinity:
                    self.assertNotIn('completed_for', saved)

    def test_reading_keeps_position_and_fresh_morale_without_global_scan_or_swap(self):
        self.configure()
        self.live[1][4] = 77
        preflight_rotation(self.runner, 5, 'normal')
        record = state(self.config)['records'][self.names[1, 4]]
        self.assertEqual((1, 4, 77), (record['fleet'], record['slot'], record['emotion']))
        self.manager.run.assert_not_called()
        self.manager.prepare_rotation.assert_not_called()
        self.manager.rotate_slot.assert_not_called()

    def test_only_one_of_two_goals_does_not_swap(self):
        for level, affinity in ((119, 100), (120, 99), (80, 50)):
            self.configure(level=True, affinity=True)
            self.profile[self.names[1, 4]] = dict(level=level, affinity=affinity)
            preflight_rotation(self.runner, 5, 'normal')
            self.manager.rotate_slot.assert_not_called()
            self.assertFalse(excluded(state(self.config)['records'][self.names[1, 4]], goals(self.config)))

    def test_multiple_ships_complete_independently_and_fixed_ships_are_not_marked(self):
        self.configure(level=True, affinity=True, slots=(4, 5))
        first, second, fixed = self.names[1, 4], self.names[1, 5], self.names[1, 1]
        self.profile[first] = self.profile[fixed] = dict(level=125, affinity=200)
        self.profile[second] = dict(level=120, affinity=99)
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_called_once_with(3, 4, 1)
        records = state(self.config)['records']
        self.assertTrue(excluded(records[first], goals(self.config)))
        self.assertFalse(excluded(records[second], goals(self.config)))
        self.assertNotIn(fixed, records)

    def test_level_only_calibrates_actual_morale_before_profile_without_a_temporary_swap(self):
        self.configure()
        self.config.set_record(Emotion_Fleet1Value=150)
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.run.assert_not_called()
        self.manager.prepare_rotation.assert_not_called()
        self.assertEqual([(1, [4], {'level': 120})], self.read_calls)
        self.assertEqual(150, self.campaign.emotion.training_lower(1))
        self.assertEqual(150, self.config.Emotion_Fleet1Value)
        self.campaign.emotion.check_reduce(5)

    def test_unknown_reading_delays_without_marking_completion(self):
        self.configure(affinity=True)
        name = self.names[1, 4]
        self.profile[name] = dict(level=120, affinity=None)
        with self.assertRaises(ScriptEnd):
            preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_not_called()
        self.assertNotIn(name, state(self.config)['records'])

    def test_no_candidate_and_completed_candidate_delay_without_repeating_swaps(self):
        self.configure()
        self.profile[self.names[1, 4]]['level'] = 120
        self.profile[self.names[3, 4]]['level'] = 125
        with self.assertRaises(ScriptEnd):
            preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_not_called()
        self.assertTrue(excluded(state(self.config)['records'][self.names[1, 4]], goals(self.config)))

    def test_temporary_morale_swap_preserves_progress_and_can_select_the_ship_again(self):
        self.configure(mood=True, level=True, affinity=True)
        original = self.names[1, 4]
        self.live[1][4] = 2
        preflight_rotation(self.runner, 5, 'normal')
        self.assertFalse(excluded(state(self.config)['records'][original], goals(self.config)))
        self.assertEqual(80, state(self.config)['records'][original]['level'])
        self.live[3][4], self.live[1][4] = 150, 2
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(original, self.names[1, 4])

    def test_restart_after_confirmed_swap_does_not_swap_again_and_keeps_completion_on_disk(self):
        self.configure(mood=True)
        original = self.names[1, 4]
        self.profile[original]['level'] = 120
        def interrupt(source, slot, fleet):
            self.rotate(source, slot, fleet)
            raise GameStuckError('模拟确认后进程中断')
        self.manager.rotate_slot.side_effect = interrupt
        with self.assertRaises(FleetManagementError):
            preflight_rotation(self.runner, 5, 'normal')
        saved = self.service.read_json(self.path)['FleetInfo']['FleetTraining']['State']
        self.assertTrue(saved['pending'])
        self.assertIn('completed_for', saved['records'][original])
        self.runner.__dict__.pop('_fleet_rotation_context', None)
        self.manager.rotate_slot.side_effect = self.rotate
        self.manager.rotate_slot.reset_mock()
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_not_called()
        self.assertFalse(state(self.config)['pending'])

    def test_training_only_restart_rescans_both_sides_after_game_confirm_before_save(self):
        self.configure()
        original = self.names[1, 4]
        self.profile[original]['level'] = 120
        def interrupt(source, slot, fleet):
            self.names[source, slot], self.names[fleet, slot] = self.names[fleet, slot], self.names[source, slot]
            raise GameStuckError('模拟游戏确认后、结果保存前中断')
        self.manager.rotate_slot.side_effect = interrupt
        with self.assertRaises(GameStuckError):
            preflight_rotation(self.runner, 5, 'normal')
        self.runner.__dict__.pop('_fleet_rotation_context', None)
        self.manager.rotate_slot.side_effect = self.rotate
        self.manager.rotate_slot.reset_mock()
        self.inventory_calls.clear()
        preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual({1, 3}, self.inventory_calls[0])
        self.manager.rotate_slot.assert_not_called()
        self.assertFalse(state(self.config)['pending'])
        self.assertTrue(excluded(state(self.config)['records'][original], goals(self.config)))

    def test_switching_training_off_mid_swap_preserves_unexecuted_job_for_restart(self):
        self.configure(slots=(4, 5))
        for slot in (4, 5):
            self.profile[self.names[1, slot]]['level'] = 120
        def disable(source, slot, fleet):
            readings = self.rotate(source, slot, fleet)
            self.config.cross_set(LEVEL_PATH + '.Enabled', False)
            return readings
        self.manager.rotate_slot.side_effect = disable
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_called_once_with(3, 4, 1)
        self.assertEqual({'1:5'}, set(state(self.config)['pending']))
        self.config.cross_set(LEVEL_PATH + '.Enabled', True)
        self.runner.__dict__.pop('_fleet_rotation_context', None)
        self.manager.rotate_slot.side_effect = self.rotate
        self.manager.rotate_slot.reset_mock()
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_called_once_with(3, 5, 1)
        self.assertFalse(state(self.config)['pending'])

    def test_completion_swap_uses_existing_optional_equipment_flow(self):
        self.configure(mood=True)
        self.profile[self.names[1, 4]]['level'] = 120
        self.config.cross_set('FleetInfo.FleetEquipment.Enabled', True)
        with patch('module.campaign.fleet_training.FleetRotationEquipment') as equipment:
            preflight_rotation(self.runner, 5, 'normal')
        equipment.return_value.clear_outgoing.assert_called_once_with(1, [4])
        equipment.return_value.apply_pending.assert_called_once()
        self.manager._commit_formation.assert_called_once()

    def test_interval_defers_reads_even_after_goal_changes_and_task_restart(self):
        self.configure()
        preflight_rotation(self.runner, 5, 'normal')
        self.read_calls.clear()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.assertFalse(self.read_calls)
        self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
        self.config.cross_set(LEVEL_PATH + '.Target', 125)
        self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
        self.campaign._map_battle = 5
        self.assertFalse(after_battle_due(self.runner, 'normal'))
        self.restart_task()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.assertFalse(self.read_calls)
        self.campaign.emotion.check_reduce(5)
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        self.assertTrue(after_battle_due(self.runner, 'normal'))
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual([(1, [4], {'level': 125})], self.read_calls)

    def test_config_flags_targets_are_independent_and_interval_is_shared_with_read_only_state(self):
        changes = [ConfigChange(path=LEVEL_PATH + '.Enabled', value=True),
                   ConfigChange(path=LEVEL_PATH + '.Target', value=125),
                   ConfigChange(path=INTERVAL_PATH, value=0),
                   ConfigChange(path=AFFINITY_PATH + '.Enabled', value=True),
                   ConfigChange(path=AFFINITY_PATH + '.Target', value=200)]
        values = self.service.patch('testpilot', None, changes)['values']['FleetInfo']
        self.assertEqual(125, values['FleetLevelTraining']['Target'])
        self.assertEqual(200, values['FleetAffinityTraining']['Target'])
        self.assertEqual(0, values['FleetTraining']['CheckIntervalHours'])
        self.assertNotIn('CheckIntervalHours', values['FleetLevelTraining'])
        self.assertNotIn('CheckIntervalHours', values['FleetAffinityTraining'])
        for path, value in ((LEVEL_PATH + '.Target', 126), (AFFINITY_PATH + '.Target', 201),
                            (INTERVAL_PATH, -1), (TRAINING_PATH, {'records': {}})):
            with self.assertRaises(ApiError):
                self.service.patch('testpilot', None, [ConfigChange(path=path, value=value)])

    def test_hours_accept_fractional_and_large_intervals_and_due_uses_hours(self):
        self.configure()
        preflight_rotation(self.runner, 5, 'normal')
        context = self.runner._fleet_rotation_context
        for hours in (0, 0.25, 48, 1000000, 1e20):
            values = self.service.patch('testpilot', None, [
                ConfigChange(path=INTERVAL_PATH, value=hours)])['values']
            self.assertEqual(hours, values['FleetInfo']['FleetTraining']['CheckIntervalHours'])
        self.config.update()
        self.assertEqual(1e20, interval(self.config))
        self.assertFalse(due(self.config, context))
        self.config.cross_set(INTERVAL_PATH, 48)
        context['training_checked_at'] -= timedelta(hours=47)
        self.assertFalse(due(self.config, context))
        context['training_checked_at'] -= timedelta(hours=1, seconds=1)
        self.assertTrue(due(self.config, context))
        self.config.cross_set_many({INTERVAL_PATH: 0.25, AFFINITY_PATH + '.Enabled': True})
        self.assertEqual(0.25, interval(self.config))

    def test_old_intervals_merge_in_read_only_api_and_runtime_without_losing_records(self):
        from module.config.config_updater import ConfigUpdater
        original = self.service.read_json(self.path)
        original_state = {'records': {'旧舰船': {'level': 119, 'affinity': 99, 'exp': 123}}}
        for level, affinity, shared, expected in (
            ({'Enabled': True, 'CheckInterval': 30}, {'Enabled': False, 'CheckInterval': 0}, None, 0.5),
            ({'Enabled': True, 'CheckIntervalHours': 6}, {'Enabled': True, 'CheckIntervalHours': 6}, None, 6),
            ({'Enabled': True, 'CheckIntervalHours': 48}, {'Enabled': True, 'CheckIntervalHours': 0.25}, None, 0.25),
            ({'Enabled': True, 'CheckIntervalHours': 48}, {'Enabled': False, 'CheckIntervalHours': 0.25}, None, 48),
            ({'Enabled': False, 'CheckIntervalHours': 6}, {'Enabled': False, 'CheckIntervalHours': 12}, None, 6),
            ({}, {'Enabled': True, 'CheckInterval': 60}, None, 1),
            ({'Enabled': True, 'CheckIntervalHours': 6}, {}, 72, 72),
            ({}, {}, None, 6),
            ({}, {}, 12, 12),
        ):
            with self.subTest(level=level, affinity=affinity, shared=shared):
                raw = deepcopy(original)
                fleet = raw['FleetInfo']
                fleet['FleetLevelTraining'], fleet['FleetAffinityTraining'] = level, affinity
                fleet['FleetTraining'] = {'State': deepcopy(original_state)}
                if shared is not None:
                    fleet['FleetTraining']['CheckIntervalHours'] = shared
                self.path.write_text(json.dumps(raw), encoding='utf-8')
                before = self.path.read_bytes()
                values = self.service.get('testpilot')['values']
                self.assertEqual(before, self.path.read_bytes())
                migrated = ConfigUpdater().config_update(raw)
                for result in (values, migrated):
                    self.assertEqual(expected, result['FleetInfo']['FleetTraining']['CheckIntervalHours'])
                    self.assertEqual(original_state, result['FleetInfo']['FleetTraining']['State'])
                    for group in ('FleetLevelTraining', 'FleetAffinityTraining'):
                        self.assertNotIn('CheckIntervalHours', result['FleetInfo'][group])
                        self.assertNotIn('CheckInterval', result['FleetInfo'][group])

    def test_configuration_without_fleet_groups_remains_readable(self):
        raw = self.service.read_json(self.path)
        raw.pop('FleetInfo', None)
        self.service.template.pop('FleetInfo', None)
        self.path.write_text(json.dumps(raw), encoding='utf-8')
        before = self.path.read_bytes()
        values, _ = self.service.read('testpilot')
        self.assertNotIn('FleetInfo', values)
        self.assertEqual(before, self.path.read_bytes())

    def test_graduation_modes_use_the_interval_while_healthy_morale_only_ignores_it(self):
        for mood, level, affinity in product((False, True), repeat=3):
            if not (mood or level or affinity):
                continue
            with self.subTest(mood=mood, level=level, affinity=affinity):
                self.configure(mood=mood, level=level, affinity=affinity)
                self.config.cross_set(INTERVAL_PATH, 6)
                preflight_rotation(self.runner, 5, 'normal')
                context = self.runner._fleet_rotation_context
                self.assertFalse(due(self.config, context))
                self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
                context['training_checked_at'] -= timedelta(hours=6, seconds=1)
                self.campaign._map_battle = 5
                self.assertEqual(level or affinity, after_battle_due(self.runner, 'normal'))
                self.assertEqual(level or affinity, preflight_rotation(self.runner, 5, 'normal'))
                self.assertFalse(due(self.config, context))
                self.manager.rotate_slot.assert_not_called()

    def test_graduation_without_morale_mode_waits_the_full_interval_despite_low_morale(self):
        for mood, level, affinity in product((False, True), repeat=3):
            if mood or not (level or affinity):
                continue
            with self.subTest(mood=mood, level=level, affinity=affinity):
                self.configure(mood=mood, level=level, affinity=affinity)
                preflight_rotation(self.runner, 5, 'normal')
                self.config.cross_set(FULL_RECORD_PATH, now() - timedelta(days=4))
                self.campaign.emotion.calibrate_selected({1: dict.fromkeys(range(1, 7), 2)})
                self.campaign.emotion.reduce(1)
                self.config.set_record(Emotion_Fleet1Value=2)
                self.read_calls.clear()
                self.inventory_calls.clear()
                self.manager.run.reset_mock()
                self.manager.prepare_rotation.reset_mock()
                self.restart_task()
                self.campaign._map_battle = 5
                self.assertFalse(after_battle_due(self.runner, 'normal'))
                self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
                self.assertFalse(self.read_calls)
                self.assertFalse(self.inventory_calls)
                self.manager.run.assert_not_called()
                self.manager.prepare_rotation.assert_not_called()
                self.manager.rotate_slot.assert_not_called()
                with self.assertRaises(ScriptEnd):
                    self.campaign.emotion.check_reduce(5)

    def test_completion_checks_target_then_full_scan_then_ranks_reserves_and_swaps_once(self):
        self.configure(mood=True, affinity=True, slots=(5,))
        self.config.cross_set_many({FULL_RECORD_PATH: now() - timedelta(days=4),
            ROTATION_PATH + '.Rules': json.dumps({'1': {'slots': [5], 'sources': [3, 4]}})})
        outgoing = self.names[1, 5]
        self.profile[outgoing] = dict(level=120, affinity=100)
        self.live[3] = dict.fromkeys(range(1, 7), 140)
        self.live[4] = dict.fromkeys(range(1, 7), 150)
        self.training_events.clear()
        original_scan, original_swap = self.manager.run.side_effect, self.manager.rotate_slot.side_effect
        def full_scan(**kwargs):
            self.training_events.append(('full',))
            return original_scan(**kwargs)
        def swap(source, slot, fleet):
            self.training_events.append(('swap', source, slot, fleet))
            return original_swap(source, slot, fleet)
        self.manager.run.side_effect, self.manager.rotate_slot.side_effect = full_scan, swap
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual([('inventory', {1}), ('read', 1, [5]), ('full',), ('read', 4, [5]),
                          ('swap', 4, 5, 1)], self.training_events)
        self.assertEqual([{1}], self.inventory_calls)
        self.manager.run.assert_called_once_with(update_emotion=True)
        self.manager.prepare_rotation.assert_called_once_with(1, slots=[5], scan=False)
        self.manager.rotate_slot.assert_called_once_with(4, 5, 1)
        incoming = state(self.config)['records'][self.names[1, 5]]
        self.assertEqual((1, 5, 80, 50), (incoming['fleet'], incoming['slot'], incoming['level'], incoming['affinity']))
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_called_once()

    def test_unconfirmed_read_also_preserves_the_interval_after_restart(self):
        self.configure(affinity=True)
        self.profile[self.names[1, 4]]['affinity'] = None
        with self.assertRaises(ScriptEnd):
            preflight_rotation(self.runner, 5, 'normal')
        self.read_calls.clear()
        self.inventory_calls.clear()
        self.restart_task()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.assertFalse(self.read_calls)
        self.assertFalse(self.inventory_calls)
        self.manager.rotate_slot.assert_not_called()

    def test_equipment_recovery_does_not_trigger_an_extra_training_check(self):
        from module.runtime.fleet_equipment import EQUIPMENT_PATH
        self.configure()
        preflight_rotation(self.runner, 5, 'normal')
        self.config.cross_set_many({EQUIPMENT_PATH + '.Enabled': True,
                                   EQUIPMENT_PATH + '.State': {'1:4': {'fleet': 1, 'slot': 4}}})
        self.read_calls.clear()
        self.inventory_calls.clear()
        with patch('module.campaign.fleet_training.FleetRotationEquipment') as equipment:
            self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        equipment.return_value.recover_page.assert_called_once()
        equipment.return_value.apply_pending.assert_called_once()
        self.assertFalse(self.read_calls)
        self.assertFalse(self.inventory_calls)
        self.manager.rotate_slot.assert_not_called()

    def test_healthy_morale_does_not_retrigger_due_to_a_short_graduation_interval(self):
        self.configure(mood=True, level=False)
        self.config.cross_set(INTERVAL_PATH, 0.01)
        self.live[1][4] = 2
        clock = [now()]
        original = self.manager.rotate_slot.side_effect
        def swap(source, slot, fleet):
            clock[0] += timedelta(minutes=2)
            return original(source, slot, fleet)
        self.manager.rotate_slot.side_effect = swap
        with patch('module.runtime.fleet_training.now', side_effect=lambda: clock[0]):
            self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
            self.assertEqual(clock[0], self.runner._fleet_rotation_context['training_checked_at'])
            self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
            self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.rotate_slot.assert_called_once_with(3, 4, 1)

    def test_completion_full_scan_recalibrates_other_fleets_from_fresh_references(self):
        self.configure()
        self.profile[self.names[1, 4]]['level'] = 120
        self.config.cross_set_many({'Event.Fleet.Fleet1': 4, 'Event.Emotion.Fleet1Value': 40,
                                   'Event.Campaign.Mode': 'normal', 'Event.Campaign.Name': 'a1',
                                   'Event.Fleet.FleetOrder': 'fleet1_all_fleet2_standby'})
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.rotate_slot.assert_called_once_with(3, 4, 1)
        self.assertEqual([{1}], self.inventory_calls)
        self.assertEqual(150, self.config.cross_get('Event.Emotion.Fleet1Value'))

    def test_morale_only_ignores_zero_graduation_interval_when_morale_is_healthy(self):
        self.configure(mood=True, level=False)
        self.config.cross_set(INTERVAL_PATH, 0)
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.run.reset_mock()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_not_called()
        self.assertEqual([{1}], self.inventory_calls)
        self.manager.rotate_slot.assert_not_called()

    def restart_task(self):
        self.config = AzurLaneConfig('testpilot', task='Main')
        self.campaign.config = self.runner.config = self.config
        self.campaign.emotion = Emotion(self.config)
        self.runner.__dict__.pop('_fleet_rotation_context', None)

    def test_full_scan_interval_is_removed_and_scan_time_remains_read_only(self):
        values = self.service.get('testpilot')['values']['FleetInfo']['FleetTraining']
        self.assertEqual(6, values['CheckIntervalHours'])
        self.assertNotIn('FullScanIntervalDays', values)
        for path, value in (('FleetInfo.FleetTraining.FullScanIntervalDays', 3),
                            (FULL_RECORD_PATH, '2026-10-27 00:00:00')):
            with self.assertRaises(ApiError):
                self.service.patch('testpilot', None, [ConfigChange(path=path, value=value)])

    def test_unfinished_targets_do_not_full_scan_until_due_and_graduated(self):
        for mood in (False, True):
            with self.subTest(mood=mood):
                self.configure(mood=mood)
                self.manager.run.reset_mock()
                old = now() - timedelta(days=3, seconds=1)
                self.config.cross_set(FULL_RECORD_PATH, old)
                self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
                self.manager.run.assert_not_called()
                self.assertEqual(old, self.config.cross_get(FULL_RECORD_PATH))
                self.read_calls.clear()
                self.inventory_calls.clear()
                self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
                self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
                self.assertEqual([{1}], self.inventory_calls)
                self.assertEqual([(1, [4], {'level': 120})], self.read_calls)
                self.assertEqual(old, self.config.cross_get(FULL_RECORD_PATH))
                self.manager.run.assert_not_called()
                self.profile[self.names[1, 4]]['level'] = 120
                self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
                self.campaign._map_battle = 5
                self.assertFalse(after_battle_due(self.runner, 'normal'))
                self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
                self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
                self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
                self.manager.run.assert_called_once_with(update_emotion=True)
                self.assertGreater(self.config.cross_get(FULL_RECORD_PATH), old)

    def test_all_seven_modes_restore_the_clock_and_consumed_morale_after_task_restart(self):
        for mood, level, affinity in product((False, True), repeat=3):
            if not (mood or level or affinity):
                continue
            with self.subTest(mood=mood, level=level, affinity=affinity):
                self.configure(mood=mood, level=level, affinity=affinity)
                self.config.cross_set_many({INTERVAL_PATH: 6, ROTATION_PATH + '.SelectedOnly': True})
                preflight_rotation(self.runner, 5, 'normal')
                self.campaign.emotion.reduce(1)
                checked = self.runner._fleet_rotation_context['training_checked_at']
                self.assertEqual(148, self.campaign.emotion.training_lower(1))
                self.read_calls.clear()
                self.inventory_calls.clear()
                self.restart_task()
                self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
                self.assertEqual(checked, self.runner._fleet_rotation_context['training_checked_at'])
                self.assertEqual(148, self.campaign.emotion.training_lower(1))
                self.assertFalse(self.read_calls)
                self.assertFalse(self.inventory_calls)
                self.manager.run.assert_not_called()

    def test_persisted_interval_expiry_reads_only_the_selected_active_fleet(self):
        self.configure(affinity=True)
        self.config.cross_set(INTERVAL_PATH, 6)
        preflight_rotation(self.runner, 5, 'normal')
        saved = state(self.config)
        saved['checks']['Main']['checked_at'] = (now() - timedelta(hours=6, seconds=1)).isoformat()
        self.config.cross_set(TRAINING_PATH, saved)
        self.read_calls.clear()
        self.inventory_calls.clear()
        self.restart_task()
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual([{1}], self.inventory_calls)
        self.assertEqual([(1, [4], {'level': 120, 'affinity': 100})], self.read_calls)
        self.manager.run.assert_not_called()

    def test_targeted_read_does_not_recalibrate_an_unscanned_fleet_from_old_snapshots(self):
        self.configure(mood=True)
        preflight_rotation(self.runner, 5, 'normal')
        self.config.cross_set_many({'Event.Fleet.Fleet1': 3, 'Event.Emotion.Fleet1Value': 40})
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual(40, self.config.cross_get('Event.Emotion.Fleet1Value'))
        self.manager.run.assert_not_called()

    def test_full_scan_reuses_current_reserve_references_for_completion(self):
        self.configure(mood=True)
        self.profile[self.names[1, 4]]['level'] = 120
        self.config.cross_set(FULL_RECORD_PATH, now() - timedelta(days=3, seconds=1))
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.manager.run.assert_called_once()
        self.assertEqual([{1}], self.inventory_calls)
        self.manager.rotate_slot.assert_called_once_with(3, 4, 1)

    def test_morale_reserve_waits_without_an_early_scan_with_only_level_enabled(self):
        self.configure()
        self.config.cross_set_many({ROTATION_PATH + '.SelectedOnly': True,
                                   'Main.Emotion.Fleet1Control': 'keep_exp_bonus',
                                   'Main.Emotion.Fleet1Recover': 'dormitory_floor_1'})
        self.live[1][1] = 0
        preflight_rotation(self.runner, 5, 'normal')
        # 5战预留10点：128仍高于120，但已不满足本张地图的130点要求。
        for _ in range(11):
            self.campaign.emotion.reduce(1)
        self.live[1][4] = 128
        self.read_calls.clear()
        self.inventory_calls.clear()
        self.restart_task()
        self.campaign._map_battle = 5
        self.assertFalse(due(self.config, self.runner.__dict__.setdefault('_fleet_rotation_context', {})))
        self.assertFalse(after_battle_due(self.runner, 'normal'))
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.assertFalse(self.inventory_calls)
        self.assertFalse(self.read_calls)
        self.manager.run.assert_not_called()
        self.manager.rotate_slot.assert_not_called()
        self.restart_task()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.assertFalse(self.inventory_calls)
        with self.assertRaises(ScriptEnd):
            self.campaign.emotion.check_reduce(5)
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual([{1}], self.inventory_calls)

    def test_failed_full_scan_does_not_advance_the_scan_time(self):
        self.configure()
        self.profile[self.names[1, 4]]['level'] = 120
        old = now() - timedelta(days=3, seconds=1)
        self.config.cross_set(FULL_RECORD_PATH, old)
        self.manager.run.side_effect = GameStuckError('全舰队扫描中断')
        with self.assertRaises(GameStuckError):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(old, self.config.cross_get(FULL_RECORD_PATH))

    def test_recorded_reading_is_recovered_before_stage_navigation_even_after_disable(self):
        self.configure(level=False)
        with patch('module.campaign.fleet_training.FleetTrainingReader') as reader:
            recover_reading(self.runner, 'normal')
            reader.assert_not_called()
            self.config.cross_set(TRAINING_PATH, {'reading': {'fleet': 1, 'slots': [4]}})
            recover_reading(self.runner, 'normal')
            reader.return_value.recover_page.assert_called_once()
            reader.reset_mock()
            recover_reading(self.runner, 'hard')
            reader.assert_not_called()

    def test_after_temporary_swap_uses_task_morale_and_selected_only_switch(self):
        for selected_only in (False, True):
            self.configure(mood=True, level=True, affinity=True)
            self.config.cross_set(ROTATION_PATH + '.SelectedOnly', selected_only)
            self.live[1][1], self.live[1][4] = 0, 2
            preflight_rotation(self.runner, 5, 'normal')
            self.manager.rotate_slot.assert_called_once()
            if selected_only:
                self.campaign.emotion.check_reduce(5)
            else:
                with self.assertRaises(ScriptEnd):
                    self.campaign.emotion.check_reduce(5)

    def test_level_or_affinity_only_low_morale_delays_without_temporary_swap(self):
        for level, affinity in ((True, False), (False, True), (True, True)):
            self.configure(level=level, affinity=affinity)
            self.config.set_record(Emotion_Fleet1Value=2)
            self.live[1][4] = 2
            preflight_rotation(self.runner, 5, 'normal')
            self.manager.rotate_slot.assert_not_called()
            with self.assertRaises(ScriptEnd):
                self.campaign.emotion.check_reduce(5)

    def test_selected_only_is_shared_with_level_affinity_and_both_without_enabling_morale_swaps(self):
        for level, affinity in ((True, False), (False, True), (True, True)):
            self.configure(level=level, affinity=affinity)
            self.config.cross_set(ROTATION_PATH + '.SelectedOnly', True)
            self.live[1][1] = 0
            preflight_rotation(self.runner, 5, 'normal')
            self.assertTrue(self.campaign.emotion.selected_only)
            self.assertEqual(0, self.config.Emotion_Fleet1Value)
            self.assertEqual(150, self.campaign.emotion.training_lower(1))
            self.campaign.emotion.check_reduce(5)
            self.manager.rotate_slot.assert_not_called()
            self.campaign.emotion.calibrate_selected({1: {1: 0, 4: 2}})
            with self.assertRaises(ScriptEnd):
                self.campaign.emotion.check_reduce(5)
            self.manager.rotate_slot.assert_not_called()

    def test_enabling_shared_morale_option_preserves_the_remaining_interval(self):
        self.configure()
        preflight_rotation(self.runner, 5, 'normal')
        self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
        self.manager.prepare_rotation.reset_mock()
        self.inventory_calls.clear()
        self.config.cross_set(ROTATION_PATH + '.SelectedOnly', True)
        self.live[1][1] = 0
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.assertFalse(self.inventory_calls)
        self.manager.prepare_rotation.assert_not_called()
        self.campaign.emotion.check_reduce(5)
        self.manager.rotate_slot.assert_not_called()
        self.assertFalse(preflight_rotation(self.runner, 5, 'normal'))
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual([{1}], self.inventory_calls)

    def test_combined_training_keeps_fixed_red_confirmation_and_training_unknown_protection(self):
        for mood, (level, affinity) in product((False, True), ((True, False), (False, True), (True, True))):
            self.configure(mood=mood, level=level, affinity=affinity)
            self.config.cross_set(ROTATION_PATH + '.SelectedOnly', True)
            self.live[1][1] = 0
            preflight_rotation(self.runner, 5, 'normal')
            emotion = self.campaign.emotion
            handler = rotation_cases.RotationIntegrationTests.popup_handler(self, emotion)
            self.assertTrue(rotation_cases.InfoHandler.handle_combat_low_emotion(handler))
            handler.handle_popup_confirm.assert_called_once_with('IGNORE_LOW_EMOTION')
            self.assertEqual(150, emotion.training_lower(1))
            self.assertFalse(excluded(state(self.config)['records'][self.names[1, 4]], goals(self.config)))
            emotion.context['training'][1]['state'] = None
            handler = rotation_cases.RotationIntegrationTests.popup_handler(self, emotion)
            with self.assertRaises(ScriptEnd):
                rotation_cases.InfoHandler.handle_combat_low_emotion(handler)
            handler.handle_popup_confirm.assert_not_called()
            handler.handle_popup_cancel.assert_called_once()

    def test_oil_shortage_uses_existing_task_delay_without_disabling_scheduler(self):
        from module.campaign.run import CampaignRun
        self.configure()
        self.config.StopCondition_ReachLevel = 0
        enabled = self.config.Scheduler_Enable
        runner = SimpleNamespace(config=self.config, campaign=self.campaign, run_limit=False,
                                 status_get_gems=Mock(), get_coin=Mock(), get_oil=Mock(return_value=100))
        self.assertTrue(CampaignRun.triggered_stop_condition(runner))
        self.assertEqual(enabled, self.config.Scheduler_Enable)
        self.manager.rotate_slot.assert_not_called()

    def test_changed_goals_drop_unexecuted_pending_job_and_recheck_current_ship(self):
        self.configure()
        self.profile[self.names[1, 4]]['level'] = 120
        saved = state(self.config)
        saved['pending']['1:4'] = dict(fleet=1, slot=4, source=3, outgoing=self.names[1, 4],
                                       incoming=self.names[3, 4], targets={'level': 120})
        self.config.cross_set_many({TRAINING_PATH: saved, LEVEL_PATH + '.Target': 125})
        preflight_rotation(self.runner, 5, 'normal')
        self.manager.rotate_slot.assert_not_called()
        self.assertFalse(state(self.config)['pending'])

    def test_duplicate_names_and_corrupt_records_do_not_mark_completion(self):
        self.configure()
        self.names[3, 4] = self.names[1, 4]
        self.full_scan()
        self.profile[self.names[1, 4]]['level'] = 125
        with self.assertRaises(ScriptEnd):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertFalse(state(self.config)['records'])
        corrupt = {'records': [], 'pending': {}}
        self.config.cross_set(TRAINING_PATH, corrupt)
        with self.assertRaises(FleetManagementError):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(corrupt, self.config.cross_get(TRAINING_PATH))

    def test_duplicate_bulin_reading_is_kept_by_slot_and_unfinished_training_continues(self):
        self.configure(level=True, affinity=True)
        name = '泛用型布里'
        self.names[1, 4] = self.names[6, 4] = name
        self.profile[name] = dict(level=100, affinity=60)
        self.live[1][4] = 119
        self.full_scan()
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        saved = state(self.config)
        self.assertNotIn(name, saved['records'])
        reading = saved['readings']['1:4']
        self.assertEqual((name, 1, 4, 100, 60, 119),
                         tuple(reading[key] for key in ('name', 'fleet', 'slot', 'level', 'affinity', 'emotion')))
        self.assertNotIn('completed_for', reading)
        self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
        self.manager.rotate_slot.assert_not_called()

    def test_level_only_keeps_all_three_readings_after_confirmed_truncated_name(self):
        self.configure(level=True, affinity=False, slots=(4, 5, 6))
        names = {4: '阿尔弗雷多·奥里亚尼', 5: '花月', 6: '文琴佐·焦贝蒂'}
        for slot, name in names.items():
            self.names[1, slot] = name
            self.profile[name] = dict(level=105)
        self.names[4, 4] = names[4]
        self.full_scan()
        scan = self.full_scan

        def scan_with_raw(*args, **kwargs):
            scan(*args, **kwargs)
            result = self.config.cross_get(self.manager.RESULT_PATH)
            result['vanguard']['1'][0]['raw_name'] = '阿尔弗雷多·奥里亚'
            self.config.cross_set(self.manager.RESULT_PATH, result)

        self.full_scan = scan_with_raw
        readings = {slot: dict(level=training_level(105, exp), display_level=105, exp=exp)
                    for slot, exp in ((4, 1582026), (5, 1594218), (6, 1583910))}
        with patch.object(self.reader_factory, 'read', return_value=readings) as read:
            self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        read.assert_called_once_with(1, [4, 5, 6], {'level': 120})
        saved = state(self.config)
        self.assertNotIn(names[4], saved['records'])
        for slot, name in names.items():
            record = saved['readings']['1:4'] if slot == 4 else saved['records'][name]
            self.assertEqual((118, 105, readings[slot]['exp']),
                             (record['level'], record['display_level'], record['exp']))
            self.assertTrue(record['checked_at'])
            self.assertNotIn('affinity', record)
            self.assertNotIn('completed_for', record)
        self.assertFalse(due(self.config, self.runner._fleet_rotation_context))
        self.manager.rotate_slot.assert_not_called()

    def test_locked_105_ships_at_effective_120_complete_and_swap_without_awakening(self):
        self.configure(slots=(4, 5, 6))
        names = {slot: self.names[1, slot] for slot in (4, 5, 6)}
        experience = {4: 1917866, 5: 1930058, 6: 1919750}
        for slot, name in names.items():
            self.profile[name] = dict(level=105, exp=experience[slot], affinity=50)
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        self.assertEqual([(3, 4, 1), (3, 5, 1), (3, 6, 1)],
                         [call.args for call in self.manager.rotate_slot.call_args_list])
        for slot, name in names.items():
            record = state(self.config)['records'][name]
            self.assertEqual((120, 105, experience[slot]),
                             (record['level'], record['display_level'], record['exp']))
            self.assertEqual({'level': 120}, record['completed_for'])

    def test_stored_experience_cannot_replace_an_unmet_affinity_goal_or_an_unknown_read(self):
        self.configure(affinity=True)
        name = self.names[1, 4]
        self.profile[name] = dict(level=105, exp=1917866, affinity=99)
        self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
        record = state(self.config)['records'][name]
        self.assertEqual(120, record['level'])
        self.assertNotIn('completed_for', record)
        self.manager.rotate_slot.assert_not_called()
        self.configure()
        name = self.names[1, 4]
        self.profile[name] = dict(level=105, exp=None)
        preflight_rotation(self.runner, 5, 'normal')
        self.assertNotIn('completed_for', state(self.config)['records'][name])
        self.manager.rotate_slot.assert_not_called()

    def test_duplicate_bulin_at_all_goals_keeps_reading_but_still_requires_unique_identity(self):
        self.configure(level=True, affinity=True)
        name = '泛用型布里'
        self.names[1, 4] = self.names[6, 4] = name
        self.profile[name] = dict(level=120, affinity=100)
        self.full_scan()
        with self.assertRaisesRegex(ScriptEnd, '同名'):
            preflight_rotation(self.runner, 5, 'normal')
        saved = state(self.config)
        self.assertEqual(100, saved['readings']['1:4']['affinity'])
        self.assertNotIn(name, saved['records'])
        self.assertFalse(saved['pending'])
        self.manager.rotate_slot.assert_not_called()

    def test_duplicate_ships_never_share_position_readings_with_legacy_name_records(self):
        self.configure(level=True, affinity=True)
        name = '泛用型布里'
        self.names[1, 4] = self.names[6, 4] = name
        self.profile[name] = dict(level=100, affinity=60)
        legacy = dict(level=125, affinity=200, completed_for={'level': 120, 'affinity': 100},
                      fleet=6, slot=4, checked_at='2026-10-26T01:00:00')
        self.config.cross_set(TRAINING_PATH, {'records': {name: legacy}, 'pending': {}})
        self.full_scan()
        preflight_rotation(self.runner, 5, 'normal')
        saved = state(self.config)
        self.assertEqual(legacy, saved['records'][name])
        self.assertEqual(60, saved['readings']['1:4']['affinity'])
        self.manager.rotate_slot.assert_not_called()

    def test_duplicate_unfinished_readings_work_with_each_training_mode(self):
        for mood, level, affinity in product((False, True), repeat=3):
            if not (level or affinity):
                continue
            with self.subTest(mood=mood, level=level, affinity=affinity):
                self.configure(mood=mood, level=level, affinity=affinity)
                name = '泛用型布里'
                self.names[1, 4] = self.names[6, 4] = name
                self.profile[name] = dict(level=100, affinity=60)
                self.full_scan()
                self.assertTrue(preflight_rotation(self.runner, 5, 'normal'))
                saved = state(self.config)
                self.assertEqual(name, saved['readings']['1:4']['name'])
                self.assertFalse(saved['records'])
                self.manager.rotate_slot.assert_not_called()

    def test_duplicate_unknown_affinity_is_not_saved_as_a_verified_value(self):
        self.configure(level=True, affinity=True)
        name = '泛用型布里'
        self.names[1, 4] = self.names[6, 4] = name
        self.profile[name] = dict(level=100, affinity=None)
        self.full_scan()
        with self.assertRaisesRegex(ScriptEnd, '好感'):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertFalse(state(self.config).get('readings'))
        self.manager.rotate_slot.assert_not_called()

    def test_corrupt_position_readings_are_preserved_and_rejected(self):
        self.configure()
        corrupt = {'records': {}, 'pending': {}, 'readings': []}
        self.config.cross_set(TRAINING_PATH, corrupt)
        with self.assertRaises(FleetManagementError):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertEqual(corrupt, self.config.cross_get(TRAINING_PATH))

    def test_stop_option_waits_for_every_ship_and_every_enabled_goal_without_replacing(self):
        from module.config.config import TaskEnd
        self.configure(mood=True, level=True, affinity=True, slots=(4, 5))
        self.config.cross_set_many({'FleetInfo.FleetTraining.StopOnComplete': True,
                                    'Main.Scheduler.Enable': True})
        first, second = self.names[1, 4], self.names[1, 5]
        self.profile[first] = dict(level=120, affinity=100)
        self.profile[second] = dict(level=120, affinity=99)
        self.live[1][4] = 2
        preflight_rotation(self.runner, 5, 'normal')
        self.assertTrue(self.config.Scheduler_Enable)
        self.manager.rotate_slot.assert_not_called()
        self.profile[second]['affinity'] = 100
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        with self.assertRaises(TaskEnd):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertFalse(self.config.Scheduler_Enable)
        self.manager.rotate_slot.assert_not_called()
        self.assertEqual(first, self.names[1, 4])
        self.assertEqual(second, self.names[1, 5])
        self.manager._commit_formation.assert_called()

    def test_stop_needs_no_reserves_and_checks_both_active_fleets(self):
        from module.config.config import TaskEnd
        self.configure(level=True)
        self.config.cross_set_many({'FleetInfo.FleetTraining.StopOnComplete': True,
            ROTATION_PATH + '.Rules': json.dumps({'1': {'slots': [4], 'sources': []},
                                                 '2': {'slots': [4], 'sources': []}}),
            'Main.Fleet.FleetOrder': 'fleet1_mob_fleet2_boss', 'Main.Fleet.Fleet2': 2,
            'Main.Scheduler.Enable': True})
        self.profile[self.names[1, 4]]['level'] = 120
        preflight_rotation(self.runner, 5, 'normal')
        self.assertTrue(self.config.Scheduler_Enable)
        self.profile[self.names[2, 4]]['level'] = 120
        self.runner._fleet_rotation_context['training_checked_at'] -= timedelta(hours=6, seconds=1)
        with self.assertRaises(TaskEnd):
            preflight_rotation(self.runner, 5, 'normal')
        self.assertFalse(self.config.Scheduler_Enable)
        self.manager.rotate_slot.assert_not_called()

    def test_favourite_is_used_only_after_all_selected_reserves_graduate(self):
        self.configure()
        self.config.cross_set(ROTATION_PATH + '.Rules', json.dumps({'1': {
            'slots': [4], 'sources': [3, 4, 5], 'favourite': True}}))
        self.profile[self.names[1, 4]]['level'] = 120
        with patch('module.retire.fleet_favourite.FavouriteShips') as common:
            preflight_rotation(self.runner, 5, 'normal')
            common.assert_not_called()
        self.manager.rotate_slot.assert_called_once_with(3, 4, 1)
        self.configure()
        self.config.cross_set(ROTATION_PATH + '.Rules', json.dumps({'1': {
            'slots': [4], 'sources': [3, 4, 5], 'favourite': True}}))
        for fleet in (1, 3, 4, 5):
            self.profile[self.names[fleet, 4]]['level'] = 120
        name = next(name for name in catalog()['ships'] if name not in self.names.values())
        candidate = dict(name=name, level=80, emotion=150, review=False)
        self.profile[name] = dict(level=80, affinity=50)

        def find(*args, observe, **kwargs):
            observe(name, {'level': 80}, 150)
            return candidate

        def replace(fleet, slot, ship):
            self.names[fleet, slot] = ship['name']
            return self.snapshots()

        with patch('module.retire.fleet_favourite.FavouriteShips') as common:
            common.return_value.find.side_effect = find
            common.return_value.replace.side_effect = replace
            preflight_rotation(self.runner, 5, 'normal')
            common.return_value.find.assert_called_once()
            common.return_value.replace.assert_called_once_with(1, 4, candidate)
        self.manager.rotate_slot.assert_not_called()
        self.assertEqual(name, self.names[1, 4])
        self.assertEqual({}, state(self.config)['pending'])

    def test_common_pending_recovery_does_not_repeat_a_confirmed_replacement(self):
        from module.campaign.fleet_training import TrainingSession
        self.configure()
        incoming, outgoing = self.names[1, 4], self.names[3, 4]
        self.config.cross_set(TRAINING_PATH, {'records': {}, 'pending': {'1:4': dict(
            fleet=1, slot=4, source=0, incoming=incoming, outgoing=outgoing, targets={'level': 120})}})
        session = TrainingSession(self.runner, self.manager, {}, {'1': {'slots': [4], 'sources': []}}, {1: 1})
        session.recover()
        self.assertEqual({}, state(self.config)['pending'])
        self.manager.rotate_slot.assert_not_called()

    def test_training_notification_reports_current_ships_and_confirmed_swaps_and_is_optional(self):
        from module.campaign.fleet_training_notify import notify_training
        self.configure()
        name = self.names[1, 4]
        rules = {'1': {'slots': [4], 'sources': [3]}}
        with (patch('module.campaign.fleet_training_notify.Thread') as thread,
              patch('module.campaign.fleet_training_notify.notify_webui') as local,
              patch('module.campaign.fleet_training_notify.handle_notify') as remote):
            thread.side_effect = lambda target, daemon: SimpleNamespace(start=target)
            notify_training(self.config, rules, {1: 1})
            thread.assert_not_called()
            self.config.cross_set_many({'FleetInfo.FleetTraining.Notify': True,
                                        'General.Error.OnePushConfig': 'provider: test'})
            change = dict(fleet=1, slot=4, source=0, outgoing='已换出舰船', incoming=name)
            notify_training(self.config, rules, {1: 1}, [change])
            content = local.call_args.kwargs['content']
            for text in (name, '等级80', '好感未读取', '心情150', '已换出舰船', '来源：常用'):
                self.assertIn(text, content)
            remote.assert_called_once()
            self.assertEqual(content, remote.call_args.kwargs['content'])

    def test_due_check_finishes_current_map_without_withdraw_or_extra_battles(self):
        from module.campaign.campaign_base import CampaignBase
        campaign = CampaignBase.__new__(CampaignBase)
        campaign.__dict__.update(vars(self.campaign))
        campaign._map_battle = 5
        campaign.ENTRANCE = SimpleNamespace(area=None, button=(1, 2, 3, 4))
        campaign.map_is_auto_search = True
        campaign.map_get_info = Mock()
        campaign.enter_map = Mock()
        campaign.emotion = SimpleNamespace(check_reduce=Mock())
        campaign.MAP = object()
        campaign.lv_reset = campaign.lv_get = Mock()
        campaign.auto_search_execute_a_battle = Mock(side_effect=[None, None, CampaignEnd])
        campaign.auto_search_withdraw = Mock()
        campaign.AUTO_SEARCH_WITHDRAW = False
        campaign._fleet_training_after_battle = Mock(return_value=True)
        self.assertTrue(campaign.run())
        self.assertEqual(3, campaign.auto_search_execute_a_battle.call_count)
        campaign.auto_search_withdraw.assert_not_called()
        self.assertEqual(3, campaign._fleet_training_after_battle.call_count)
