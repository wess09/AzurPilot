"""心智阵营限定、容量提示与科技严格复核的语义。"""
import unittest
from pathlib import Path
from PIL import Image
import numpy as np
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config import TaskEnd
from module.retire.mind_scan import MindCalculatorScan
from module.runtime.mind_calculator import enrich
from module.runtime.mind_identity import MindIdentity
from module.runtime.mind_recognition import ScanPolicy
from module.exception import MindCalculatorScanError


def row(name, level, gid=None):
    return enrich(dict(name=name, level=level, group_type=gid, excluded=False, review=False, source='原帧'))


class FactionIdentityTests(unittest.TestCase):
    def scanner(self):
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        scanner._identity = MindIdentity()
        scanner._policy = ScanPolicy(90, 125, sorted_desc=True)
        scanner._scan_metadata = dict(reached_bottom=False, physical_count=42)
        scanner._scan_raw_ships = [row('约克', 120), row('新月', 105), row('拉菲', 100)]
        scanner._set_identity_faction = Mock()
        scanner.ui_ensure = Mock()
        scanner.dock_reset = Mock()
        scanner.dock_sort_method_dsc_set = Mock()
        scanner.appear = Mock(return_value=False)
        scanner.device = Mock()
        scanner._close_search = Mock()
        return scanner

    def run_resolution(self, scanner, results):
        def read(*args):
            scanner._scan_raw_ships = results[scanner._set_identity_faction.call_args.args[0]]
            scanner._scan_metadata = dict(reached_bottom=True, physical_count=len(scanner._scan_raw_ships))
            return scanner._scan_raw_ships
        scanner._scan_pages = read
        with patch('module.retire.mind_scan.DOCK_SCROLL') as scroll:
            scroll.appear.return_value = scroll.at_top.return_value = True
            return scanner._resolve_group_reviews(list(scanner._scan_raw_ships), Mock(), Mock())

    def test_positive_faction_evidence_resolves_york_crescent_and_preserves_primary_scope(self):
        scanner = self.scanner()
        output = self.run_resolution(scanner, {'iron': [row('约克', 120, 40311)],
            'royal': [row('约克', 56, 20307), row('新月', 105, 20109)], 'sakura': []})
        self.assertEqual([(ship['name'], ship['group_type']) for ship in output], [('约克', 40311), ('新月', 20109), ('拉菲', 10117)])
        self.assertFalse(any(ship['review'] for ship in output))
        self.assertEqual(scanner._policy.min_level, 90)
        self.assertEqual(scanner._scan_metadata, dict(reached_bottom=False, physical_count=42))

    def test_count_level_or_identity_disagreement_retains_independent_review(self):
        for found in ([row('约克', 119, 40311)], [row('约克', 120, 40311)] * 2, [row('约克', 120)]):
            scanner = self.scanner()
            output = self.run_resolution(scanner, {'iron': found, 'royal': [row('新月', 105, 20109)], 'sakura': []})
            york = next(ship for ship in output if ship['name'] == '约克')
            self.assertIsNone(york['group_type'])
            self.assertTrue(york['review'])

    def test_cancellation_does_not_continue_input_or_commit_and_restores_memory_state(self):
        scanner = self.scanner()
        original = scanner._scan_raw_ships
        scanner._scan_pages = Mock(side_effect=TaskEnd())
        with patch('module.retire.mind_scan.DOCK_SCROLL') as scroll:
            scroll.appear.return_value = scroll.at_top.return_value = True
            with self.assertRaises(TaskEnd):
                scanner._resolve_group_reviews(list(original), Mock(), Mock())
        self.assertIs(scanner._scan_raw_ships, original)
        self.assertEqual(scanner._policy.min_level, 90)
        scanner.ui_ensure.assert_not_called()

    def test_verified_faction_is_part_of_identity_evidence_and_cannot_accept_other_faction(self):
        royal = MindIdentity({2})
        self.assertEqual(royal.match(['约克', '约克'])[0]['group_type'], 20307)
        self.assertEqual(royal.match(['新月', '新月'])[0]['group_type'], 20109)
        self.assertIsNone(royal.match(['拉菲'])[0])
        self.assertIsNone(royal.match(['拉菲', '拉菲'], fuzzy=True)[0])

    def test_faction_filter_requires_a_fresh_confirmed_panel_and_every_button_state(self):
        scanner = self.scanner()
        del scanner._set_identity_faction
        scanner.device = Mock()
        scanner.dock_filter_enter = Mock()
        scanner.dock_filter_confirm = Mock()
        scanner.dock_filter = Mock()
        selected, unselected = object(), object()
        scanner.dock_filter._product_setting_status.return_value = {selected: True, unselected: False}
        scanner.dock_filter.is_option_active.side_effect = lambda button: button is selected
        scanner.appear.return_value = True
        scanner._set_identity_faction('royal')
        scanner.device.screenshot.assert_called_once()
        scanner.dock_filter_confirm.assert_called_once()
        scanner.dock_filter_confirm.reset_mock()
        scanner.appear.return_value = False
        with patch('module.retire.mind_scan.Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            with self.assertRaises(MindCalculatorScanError):
                scanner._set_identity_faction('royal')
        scanner.dock_filter_confirm.assert_not_called()

    def test_catalog_initialization_failure_does_not_touch_device_or_old_list(self):
        for task, target in ((MindCalculatorScan, 'module.retire.mind_scan.MindIdentity'),):
            scanner = task.__new__(task)
            scanner.config = SimpleNamespace(config_name='testpilot', MindCalculator_MinLevel=90,
                MindCalculator_MaxLevel=125, data={}, modified={})
            scanner.device = Mock()
            scanner.ui_ensure = Mock()
            with patch(target, side_effect=MemoryError), self.assertRaises(MindCalculatorScanError):
                scanner.run()
            scanner.device.screenshot.assert_not_called()
            scanner.ui_ensure.assert_not_called()
            self.assertEqual(scanner.config.modified, {})

    def test_scan_entry_closes_known_filter_but_unknown_page_never_restarts_game(self):
        from module.exception import GamePageUnknownError
        scanner = self.scanner()
        scanner.dock_filter_confirm = Mock()
        scanner.appear.return_value = True
        scanner._enter_scan_dock()
        scanner.device.screenshot.assert_called_once()
        scanner.dock_filter_confirm.assert_called_once()
        self.assertTrue(all(call.kwargs == {'recover_unknown': False} for call in scanner.ui_ensure.call_args_list))
        scanner.ui_ensure.side_effect = GamePageUnknownError('unknown')
        with self.assertRaises(MindCalculatorScanError):
            scanner._enter_scan_dock()
        scanner.device.app_stop.assert_not_called()
        scanner.device.app_start.assert_not_called()

    def test_native_faction_panel_uses_real_no_limit_default_and_rejects_wrong_faction(self):
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        scanner.config = SimpleNamespace(SERVER='cn')
        scanner.device = SimpleNamespace(image=np.array(Image.open(Path(__file__).parent / 'fixtures/mind_faction_panel.png')))
        setting = scanner.dock_filter
        expected = setting._product_setting_status(faction='iron', index='all', rarity='all', extra='no_limit', sort='level')
        self.assertTrue(all(setting.is_option_active(button) == active for button, active in expected.items()))
        wrong = setting._product_setting_status(faction='royal', index='all', rarity='all', extra='no_limit', sort='level')
        self.assertFalse(all(setting.is_option_active(button) == active for button, active in wrong.items()))
        scanner.dock_filter_enter = Mock()
        scanner.dock_filter_confirm = Mock()
        scanner.dock_sort_method_dsc_set = Mock()
        scanner.appear = Mock(return_value=True)
        scanner.device.screenshot = Mock()
        setting.set = Mock()
        scanner._set_identity_faction('iron')
        scanner.dock_filter_confirm.assert_called_once()

    def test_full_scan_count_mismatch_is_a_warning_instead_of_a_fatal_error(self):
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        for expected, metadata in ((None, dict(reached_bottom=True, physical_count=1759)),
                                   (1759, dict(reached_bottom=False, physical_count=1759)),
                                   (1759, dict(reached_bottom=True, physical_count=1758))):
            scanner._scan_metadata = metadata
            self.assertFalse(scanner._verify_full_count(expected))
        scanner._scan_metadata = dict(reached_bottom=True, physical_count=1759)
        scanner._identity = MindIdentity()
        scanner._scan_raw_ships = [row('拉菲', 100)] * 1759
        scanner._verify_full_count(1759)

    def test_dock_count_rejects_prefixed_or_over_capacity_text_instead_of_clamping(self):
        from module.runtime.scan_dock_amount import ScanDockAmount
        reader = ScanDockAmount()
        for raw in ('2510/550', '量:510/550', '510/550X', '510/0', '510', ''):
            with self.subTest(raw=raw), patch('module.runtime.scan_dock_amount.Ocr.ocr', return_value=raw):
                self.assertEqual(reader.ocr(None), (0, 0, 0))
        with patch('module.runtime.scan_dock_amount.Ocr.ocr', return_value='510/550'):
            self.assertEqual(reader.ocr(None), (510, 40, 550))

    def test_full_count_distinguishes_capacity_from_all_physical_meta_cards(self):
        scanner = self.scanner()
        scanner._scan_metadata = dict(reached_bottom=True, physical_count=3)
        scanner._scan_raw_ships = [row('拉菲', 100), row('拉菲', 100), row('拉·加利索尼埃·META', 120)]
        scanner._verify_full_count(2)
        self.assertEqual(scanner._scan_metadata['occupied_count'], 2)
        self.assertEqual(scanner._scan_metadata['meta_count'], 1)
        self.assertFalse(scanner._verify_full_count(3))
        scanner._scan_raw_ships[2] = dict(row('拉·加利索尼埃', 120), group_type=None, candidates=[90201, 970204])
        self.assertFalse(scanner._verify_full_count(2))

    def test_meta_prefix_resolution_preserves_duplicate_physical_count_and_normal_identity(self):
        scanner = self.scanner()
        unknown = dict(row('拉·加利索尼埃', 120), group_type=None, candidates=[90201, 970204], review=True)
        scanner._scan_raw_ships = [row('拉·加利索尼埃', 120), unknown, dict(unknown)]
        output = self.run_resolution(scanner, {'vichya': [row('拉·加利索尼埃', 120)],
            'meta': [row('拉·加利索尼埃·META', 120), row('拉·加利索尼埃·META', 120)]})
        self.assertEqual({ship['group_type'] for ship in output}, {90201, 970204})
        self.assertEqual(len(output), 2)
        self.assertEqual(len(scanner._scan_raw_ships), 3)
        self.assertEqual(sum(ship['group_type'] == 970204 for ship in scanner._scan_raw_ships), 2)
