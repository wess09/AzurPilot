"""舰种模板、装备码配置和智能换船装备交接的离线回归。"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.equipment.fleet_rotation import FleetRotationEquipment
from module.exception import FleetManagementError
from module.runtime.fleet_equipment import EQUIPMENT_PATH, SHIP_TYPES, TYPE_AREA, parse_codes, recognize_ship_type


ROOT = Path(__file__).parent / 'fixtures/fleet_equipment'
TYPES = ['DD', 'CVL', 'DD', 'BC', 'BB', 'SSV', 'SS', 'CA', 'CVL', 'CV', 'IX', 'DD',
         'CB', 'CB', 'CL', 'CL', 'CL', 'AR', 'AR', 'BBV', 'BM', 'AE', 'AE', 'BB']
CODE = 'MTExLzIyMi8zMzMvMC8wXDA='


def badge(index):
    image = np.zeros((720, 1280, 3), np.uint8)
    atlas = np.array(Image.open(ROOT / 'type_badges.png'))
    left, top, right, bottom = TYPE_AREA
    x, y = index % 6 * 55, index // 6 * 31
    image[top:bottom, left:right] = atlas[y:y + 31, x:x + 55]
    return image


class FleetEquipmentConfigTests(unittest.TestCase):
    def test_native_ship_types_include_all_provided_variants(self):
        self.assertEqual(set(TYPES), set(SHIP_TYPES))
        for index, expected in enumerate(TYPES):
            with self.subTest(index=index, expected=expected):
                self.assertEqual(recognize_ship_type(badge(index)), expected)

    def test_blank_wrong_resolution_and_ambiguous_types_are_unknown(self):
        self.assertIsNone(recognize_ship_type(np.zeros((720, 1280, 3), np.uint8)))
        self.assertIsNone(recognize_ship_type(np.zeros((360, 640, 3), np.uint8)))
        mixed = np.maximum(badge(4), badge(3))
        self.assertIsNone(recognize_ship_type(mixed))

    def test_code_validation_and_empty_type_skip(self):
        self.assertEqual(parse_codes('{}'), {})
        self.assertEqual(parse_codes({'DD': ' ', 'CV': ' '+CODE+' '}), {'CV': [CODE, '', '']})
        self.assertEqual(parse_codes({'DD': ['', CODE, '']}), {'DD': ['', CODE, '']})
        for raw in ('{', '[]', {'unknown': CODE}, {'DD': 123}, {'DD': 'invalid'},
                    {'DD': [CODE] * 4}, {'DD': [CODE, None]}, {'DD': [CODE, 'invalid']}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_codes(raw)

    def test_config_defaults_and_api_persistence(self):
        import tempfile
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            config = service.get('testpilot')
            values = config['values']['FleetInfo']['FleetEquipment']
            self.assertIs(values['Enabled'], False)
            self.assertEqual(parse_codes(values['Codes']), {})
            updated = service.patch('testpilot', config['revision'], [
                ConfigChange(path=EQUIPMENT_PATH + '.Enabled', value=True),
                ConfigChange(path=EQUIPMENT_PATH + '.Codes', value=json.dumps({'DD': CODE, 'CV': ''}))])
            self.assertTrue(updated['values']['FleetInfo']['FleetEquipment']['Enabled'])
            self.assertEqual(parse_codes(service.get('testpilot')['values']['FleetInfo']['FleetEquipment']['Codes']),
                             {'DD': [CODE, '', '']})
            triplet = [CODE, '', 'Nzc3Lzg4OC85OTkvMC8wXDA=']
            latest = service.get('testpilot')
            service.patch('testpilot', latest['revision'], [
                ConfigChange(path=EQUIPMENT_PATH + '.Codes', value=json.dumps({'DD': triplet}))])
            self.assertEqual(parse_codes(service.get('testpilot')['values']['FleetInfo']['FleetEquipment']['Codes']),
                             {'DD': triplet})
            with self.assertRaisesRegex(ApiError, '装备码'):
                service.patch('testpilot', updated['revision'], [
                    ConfigChange(path=EQUIPMENT_PATH + '.Codes', value='{"DD":"invalid"}')])
            self.assertEqual(parse_codes(service.get('testpilot')['values']['FleetInfo']['FleetEquipment']['Codes']),
                             {'DD': triplet})


class FleetEquipmentFlowTests(unittest.TestCase):
    def setUp(self):
        self.store = {EQUIPMENT_PATH + '.State': {}}
        self.events = []
        self.handler = FleetRotationEquipment.__new__(FleetRotationEquipment)
        self.handler.config = SimpleNamespace(cross_get=lambda path, default=None: deepcopy(self.store.get(path, default)),
                                              cross_set=lambda path, value: self.store.update({path: deepcopy(value)}))
        self.handler.manager = Mock()
        self.handler.codes = {'DD': [CODE, '', '']}
        self.occupied = {1, 4}
        self.handler.device = SimpleNamespace(image=badge(0), has_cached_image=True)
        self.handler._details = lambda fleet: self.events.append(('details', fleet))
        self.handler._ship = lambda slot: self.events.append(('ship', slot)) or slot in self.occupied
        self.handler._back_to_details = lambda: self.events.append('details-back')
        self.handler._back_to_formation = lambda: self.events.append('formation-back')
        self.handler._code_enter = lambda: self.events.append('code-page')
        self.handler._code_apply = lambda code: self.events.append(('apply', code)) or True
        self.handler.loop = lambda **kwargs: iter([None, None, None])
        self.handler.appear = Mock(return_value=True)

    def pending(self):
        return self.store[EQUIPMENT_PATH + '.State']

    def test_clear_all_outgoing_before_any_incoming_equipment(self):
        self.handler.clear_outgoing(6, [1, 4])
        self.assertEqual(self.pending(), {'6:1': {'fleet': 6, 'slot': 1}, '6:4': {'fleet': 6, 'slot': 4}})
        self.assertEqual([event for event in self.events if isinstance(event, tuple) and event[0] == 'apply'],
                         [('apply', None), ('apply', None)])
        self.events.append('swaps-finished')
        self.handler.apply_pending()
        actions = [event for event in self.events if event == 'swaps-finished' or
                   isinstance(event, tuple) and event[0] == 'apply']
        self.assertEqual(actions, [('apply', None), ('apply', None), 'swaps-finished',
                                   ('apply', None), ('apply', CODE), ('apply', None), ('apply', CODE)])
        self.assertEqual(self.pending(), {})

    def test_missing_code_keeps_incoming_equipment_and_continues(self):
        self.handler.codes = {}
        self.handler.clear_outgoing(6, [4])
        self.events.clear()
        self.handler.apply_pending()
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'apply' for event in self.events))
        self.assertEqual(self.pending(), {})

    def test_clear_failure_keeps_all_pending_jobs_and_does_not_swap(self):
        self.handler._code_apply = Mock(return_value=False)
        with self.assertRaises(FleetManagementError):
            self.handler.clear_outgoing(6, [1, 4])
        self.assertEqual(set(self.pending()), {'6:1', '6:4'})
        self.handler.manager.rotate_slot.assert_not_called()

    def test_failed_apply_recovers_only_remaining_slot(self):
        self.handler.clear_outgoing(6, [1, 4])
        self.handler._code_apply = Mock(side_effect=[True, True, True, False])
        with self.assertRaises(FleetManagementError):
            self.handler.apply_pending()
        self.assertEqual(self.pending(), {'6:4': {'fleet': 6, 'slot': 4, 'kind': 'DD', 'code_index': 0}})
        self.events.clear()
        self.handler._code_apply = Mock(return_value=True)
        self.handler.apply_pending()
        self.assertIn(('ship', 4), self.events)
        self.assertNotIn(('ship', 1), self.events)
        self.assertEqual(self.pending(), {})

    def test_unknown_ship_type_does_not_clear_incoming_or_discard_pending(self):
        self.handler.clear_outgoing(6, [4])
        self.handler.device.image = np.zeros((720, 1280, 3), np.uint8)
        self.handler._code_apply = Mock()
        with self.assertRaisesRegex(FleetManagementError, '舰种'):
            self.handler.apply_pending()
        self.handler._code_apply.assert_not_called()
        self.assertIn('6:4', self.pending())

    def test_code_failure_after_clear_keeps_pending(self):
        self.handler.clear_outgoing(6, [4])
        self.handler._code_apply = Mock(side_effect=[True, False])
        with self.assertRaises(FleetManagementError):
            self.handler.apply_pending()
        self.assertIn('6:4', self.pending())

    def test_ship_type_transition_requires_two_matching_new_frames(self):
        self.handler.codes['CV'] = ['NDQ0LzU1NS82NjYvMC8wXDA=', '', '']
        self.handler.clear_outgoing(6, [4])
        self.handler._code_apply = Mock(return_value=True)
        with patch('module.equipment.fleet_rotation.recognize_ship_type', side_effect=['DD', 'CV', 'CV']):
            self.handler.apply_pending()
        self.assertEqual(self.handler._code_apply.call_args_list[-1].kwargs['code'], self.handler.codes['CV'][0])

    def test_three_same_types_use_three_distinct_codes_in_slot_order(self):
        self.occupied = {4, 5, 6}
        codes = [CODE, 'NDQ0LzU1NS82NjYvMC8wXDA=', 'Nzc3Lzg4OC85OTkvMC8wXDA=']
        self.handler.codes = {'DD': codes}
        self.handler.clear_outgoing(6, [6, 4, 5])
        self.handler._code_apply = Mock(return_value=True)
        self.handler.apply_pending()
        self.assertEqual([call.kwargs['code'] for call in self.handler._code_apply.call_args_list
                          if call.kwargs['code'] is not None], codes)

    def test_recovery_counts_completed_same_type_instead_of_reusing_first_code(self):
        self.occupied = {4, 5, 6}
        codes = [CODE, 'NDQ0LzU1NS82NjYvMC8wXDA=', 'Nzc3Lzg4OC85OTkvMC8wXDA=']
        self.handler.codes = {'DD': codes}
        self.handler.clear_outgoing(6, [4, 5, 6])
        self.handler._code_apply = Mock(side_effect=[True, True, True, False])
        with self.assertRaises(FleetManagementError):
            self.handler.apply_pending()
        self.assertNotIn('6:4', self.pending())
        self.assertEqual(self.pending()['6:5']['code_index'], 1)
        self.handler._code_apply = Mock(return_value=True)
        self.handler.apply_pending()
        self.assertEqual([call.kwargs['code'] for call in self.handler._code_apply.call_args_list
                          if call.kwargs['code'] is not None], codes[1:])

    def test_unchanged_ship_occupies_first_code_and_blank_second_does_not_fall_back(self):
        self.occupied = {4, 5, 6}
        self.handler.codes = {'DD': [CODE, '', 'Nzc3Lzg4OC85OTkvMC8wXDA=']}
        self.handler.clear_outgoing(6, [5, 6])
        self.handler._code_apply = Mock(return_value=True)
        self.handler.apply_pending()
        self.assertEqual(self.handler._code_apply.call_count, 2)
        self.assertEqual(self.handler._code_apply.call_args.kwargs['code'], self.handler.codes['DD'][2])

    def test_different_rows_and_fleets_start_from_their_own_first_code(self):
        self.occupied = {1, 2, 4, 5}
        codes = [CODE, 'NDQ0LzU1NS82NjYvMC8wXDA=', '']
        self.handler.codes = {'DD': codes}
        self.handler.clear_outgoing(1, [1, 2, 4, 5])
        self.handler.clear_outgoing(6, [1, 2, 4, 5])
        self.handler._code_apply = Mock(return_value=True)
        self.handler.apply_pending()
        applied = [call.kwargs['code'] for call in self.handler._code_apply.call_args_list
                   if call.kwargs['code'] is not None]
        self.assertEqual(applied, codes[:2] * 4)

    def test_mixed_types_have_independent_occurrences(self):
        self.occupied = {4, 5, 6}
        self.handler.codes = {'DD': [CODE, 'NDQ0LzU1NS82NjYvMC8wXDA=', ''], 'CL': [CODE, '', '']}
        self.handler.clear_outgoing(6, [4, 5, 6])
        self.handler._code_apply = Mock(return_value=True)
        with patch('module.equipment.fleet_rotation.recognize_ship_type', side_effect=['DD'] * 2 + ['CL'] * 2 + ['DD'] * 2):
            self.handler.apply_pending()
        applied = [call.kwargs['code'] for call in self.handler._code_apply.call_args_list
                   if call.kwargs['code'] is not None]
        self.assertEqual(applied, [CODE, CODE, self.handler.codes['DD'][1]])

    def test_real_config_keeps_second_code_index_after_partial_failure(self):
        import tempfile
        from module.config.config import AzurLaneConfig
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            path = str(service.path('testpilot'))
            with patch('module.config.config.filepath_config', return_value=path), \
                    patch('module.config.config_updater.filepath_config', return_value=path):
                self.handler.config = AzurLaneConfig('testpilot', task='Main')
                self.occupied = {4, 5}
                self.handler.codes = {'DD': [CODE, 'NDQ0LzU1NS82NjYvMC8wXDA=', '']}
                self.handler.clear_outgoing(6, [4, 5])
                self.handler._code_apply = Mock(side_effect=[True, True, True, False])
                with self.assertRaises(FleetManagementError):
                    self.handler.apply_pending()
                saved = service.get('testpilot')['values']['FleetInfo']['FleetEquipment']['State']
                self.assertEqual(saved, {'6:5': {'fleet': 6, 'slot': 5, 'kind': 'DD', 'code_index': 1}})

    def test_detail_ship_click_waits_for_the_expected_occupied_slot(self):
        from module.equipment.assets import EQUIPMENT_CODE_ENTRANCE

        self.handler._equipment_fleet = 6
        self.handler.manager.RESULT_PATH = 'FleetInfo.FleetInfo.Result'
        self.store[self.handler.manager.RESULT_PATH] = {'vanguard': {'6': [{'slot': 4}]}}
        self.handler.ui_click = Mock()
        loaded = np.array(Image.open(Path(__file__).parent / 'fixtures/fleet_formation/detail_surface.png'))
        def frames(**kwargs):
            for image in (np.zeros_like(loaded), loaded):
                self.handler.device.image = image
                yield None
        self.handler.loop = frames
        self.assertTrue(FleetRotationEquipment._ship(self.handler, 4))
        self.handler.ui_click.assert_called_once()
        self.assertIs(self.handler.ui_click.call_args.kwargs['check_button'], EQUIPMENT_CODE_ENTRANCE)

    def test_detail_navigation_checks_actual_fleet_instead_of_a_cached_fleet_marker(self):
        self.handler.device.image = np.array(Image.open(Path(__file__).parent / 'fixtures/fleet_formation/closed_surface.png'))
        self.handler.manager._formation_visible.return_value = True
        self.handler.ui_click = Mock()
        FleetRotationEquipment._details(self.handler, 4)
        self.handler.manager.fleet_enter.assert_not_called()
        self.handler.manager._rotation_fleet = 6
        FleetRotationEquipment._details(self.handler, 6)
        self.handler.manager.fleet_enter.assert_called_once_with(6)

    def test_current_detail_page_reuses_its_actual_fleet_without_back_or_reentry(self):
        from module.runtime.fleet_formation import bottom_fleet_index

        self.handler.device.image = np.array(Image.open(Path(__file__).parent / 'fixtures/fleet_formation/detail_surface_native.png'))
        self.handler.appear = lambda button: button.appear_on(self.handler.device.image)
        fleet = bottom_fleet_index(self.handler.device.image)
        self.assertEqual(3, fleet)
        self.handler._equipment_fleet = 6 if fleet != 6 else 1
        self.handler.ui_click = Mock()
        FleetRotationEquipment._details(self.handler, fleet)
        self.handler.ui_click.assert_not_called()
        self.handler.manager.finish_rotation.assert_not_called()
        self.handler.manager.fleet_enter.assert_not_called()
        self.assertEqual(fleet, self.handler._equipment_fleet)
        self.assertEqual([], self.events)

    def test_detail_reuse_restores_the_scope_and_returns_to_formation_on_error(self):
        self.handler._back_to_formation = Mock()
        with self.assertRaisesRegex(ValueError, 'test'):
            with self.handler.reuse_details():
                self.assertTrue(self.handler._reuse_details)
                raise ValueError('test')
        self.assertFalse(self.handler._reuse_details)
        self.handler._back_to_formation.assert_called_once()

    def test_resume_leaves_known_code_and_ship_pages_before_a_fresh_scan(self):
        self.handler._code_exit = Mock()
        self.handler.recover_page()
        self.handler._code_exit.assert_called_once()
        self.handler.manager._commit_formation.assert_called_once()
        self.assertEqual(self.events, ['details-back', 'formation-back'])

    def test_constructor_rejects_invalid_codes_before_equipment_actions(self):
        manager = SimpleNamespace(config=SimpleNamespace(cross_get=lambda *args: '{"DD":"bad"}'), device=object())
        with patch.object(FleetRotationEquipment, '_code_enter') as enter:
            with self.assertRaisesRegex(FleetManagementError, '装备码'):
                FleetRotationEquipment(manager)
        enter.assert_not_called()


if __name__ == '__main__':
    unittest.main()
