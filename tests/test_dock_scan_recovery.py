"""局部扫描恢复、原生重复卡片和独立滚动证据；不连接设备。"""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.exception import MindCalculatorScanError
from module.retire.assets import DOCK_EMPTY, DOCK_SEARCH_CLOSED
from module.retire.dock_scan import DockScan
from module.runtime.mind_recognition import ScanMerger, ScanPolicy, ScrollMotion, estimate_scroll
from tests import test_mind_scan_stuck as regression

FIXTURES = Path(__file__).parent / 'fixtures'


def repeat_frame(offset):
    row = np.array(Image.open(FIXTURES / 'mind_dock_repeat_row.png').convert('RGB'))
    pixels = np.zeros((720, 1280, 3), np.uint8)
    pixels[65:640, 85:1225] = np.tile(row, (14, 1, 1))[offset:offset + 575]
    return pixels


class ScanStartupTests(unittest.TestCase):
    def run_startup(self, pixels, count):
        scanner = DockScan.__new__(DockScan)
        scanner.config = SimpleNamespace(config_name='testpilot', Dock_MinLevel=1, Dock_MaxLevel=125)
        scanner.device = Mock(image=pixels)
        scanner.ui_ensure = scanner._close_search = scanner.dock_reset = Mock()
        scanner.dock_sort_method_dsc_set = scanner._prune_scan_evidence = Mock()
        scanner.appear = lambda button, **kwargs: (
            DockScan.appear(scanner, button, **kwargs) if button is DOCK_EMPTY else button is DOCK_SEARCH_CLOSED)

        def read_pages(*_):
            scanner._scan_slots = [dict(name='拉菲', group_type=10117, level=100, review=False)]
            scanner._scan_metadata = dict(reached_bottom=True, physical_count=1)

        scanner._scan_pages = Mock(side_effect=read_pages)
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / 'testpilot.json'
            config_path.write_text('{}', encoding='utf-8')
            with patch('module.config.utils.filepath_config', return_value=str(config_path)), \
                    patch('module.retire.dock_scan.server.server', 'cn'), \
                    patch('module.retire.dock_scan.DOCK_SCROLL') as scroll, \
                    patch('module.retire.dock_scan.FleetDatabase') as database, \
                    patch('module.ocr.al_ocr.AlOcr'), \
                    patch('module.retire.enhancement.OCR_DOCK_AMOUNT.ocr', return_value=(count, 10 - count, 10)):
                scroll.appear.return_value = scroll.at_top.return_value = True
                database.return_value.load.return_value = dict(snapshot=None, technology={})
                scanner.run()
                saved = database.return_value.save_scan.call_args.args[0]
        return scanner, saved

    def test_native_ship_art_cannot_finish_scan_as_an_empty_dock(self):
        # 用户故障帧只保留空提示检测区及 20px 搜索边缘，不包含容量或账号信息。
        pixels = np.zeros((720, 1280, 3), dtype=np.uint8)
        pixels[327:398, 75:408] = np.array(Image.open(FIXTURES / 'dock_empty_false_positive.png').convert('RGB'))
        self.assertTrue(DOCK_EMPTY.appear_on(pixels))
        self.assertFalse(DOCK_EMPTY.match(pixels, offset=(20, 20)))
        scanner, saved = self.run_startup(pixels, 1)
        scanner._scan_pages.assert_called_once()
        self.assertEqual(len(saved['ships']), 1)
        self.assertEqual(saved['physical_count'], 1)
        self.assertTrue(saved['complete'])

    def test_empty_text_still_finishes_without_reading_cards(self):
        # 用现有原生空提示模板合成正例，核对真正空船坞的原有分支。
        pixels = np.zeros((720, 1280, 3), dtype=np.uint8)
        x1, y1, x2, y2 = DOCK_EMPTY.area
        with Image.open(DOCK_EMPTY.file) as template:
            pixels[y1:y2, x1:x2] = np.array(template.convert('RGB').crop(DOCK_EMPTY.area))
        scanner, saved = self.run_startup(pixels, 0)
        scanner._scan_pages.assert_not_called()
        self.assertEqual(saved['ships'], [])
        self.assertTrue(saved['reached_bottom'])
        self.assertTrue(saved['complete'])


class ScrollRecoveryTests(unittest.TestCase):
    def test_native_corner_sampling_phase_is_accepted_without_moving_endpoints(self):
        from module.retire.dock import DOCK_SCROLL
        scanner = DockScan.__new__(DockScan)
        pixels = np.zeros((720, 1280, 3), np.uint8)
        x1, y1, x2, y2 = DOCK_SCROLL.area
        pixels[y1:y2, x1:x2] = np.array(Image.open(FIXTURES / 'mind_dock_scroll_phase.png').convert('RGB'))
        scanner.device = SimpleNamespace(image=pixels)
        strict = np.flatnonzero(DOCK_SCROLL.match_color(scanner))
        self.assertEqual(strict.tolist(), list(range(1, 76)) + [77])
        np.testing.assert_array_equal(scanner._dock_scroll_thumb(), np.arange(1, 78))

    def test_periodic_cards_use_independent_thumb_evidence_for_partial_and_whole_rows(self):
        for shift in (206, 227):
            with self.subTest(shift=shift):
                before, after = repeat_frame(0), repeat_frame(shift)
                with self.assertRaisesRegex(ValueError, '重叠位移'):
                    estimate_scroll(before, after, check_zero=True)
                motion = ScrollMotion()
                motion.accept(np.arange(10, 90), 0)
                thumb = np.arange(20, 100)
                bounds = motion.bounds(thumb, (227, True))
                merger = ScanMerger()
                merger.advance(Image.fromarray(before))
                self.assertEqual(merger.advance(Image.fromarray(after), bounds=bounds, after_drag=True), shift)
                self.assertEqual(merger.offset, shift)
                self.assertTrue(merger.motion_hint_used)

    def test_ambiguous_zero_after_drag_is_not_accepted_without_thumb_evidence(self):
        merger = ScanMerger()
        before = Image.fromarray(repeat_frame(0))
        merger.advance(before)
        with self.assertRaises(ValueError):
            merger.advance(Image.fromarray(repeat_frame(227)), after_drag=True)
        self.assertEqual(merger.offset, 0)
        np.testing.assert_array_equal(merger.previous, np.array(before))

    def test_small_held_correction_uses_symmetric_image_bounds_without_guessing_zero(self):
        bounds = ScrollMotion().bounds(None, (37, True))
        self.assertEqual(bounds, (-43, 43))
        for actual in (0, 27):
            with self.subTest(actual=actual):
                merger = ScanMerger()
                merger.advance(Image.fromarray(repeat_frame(0)))
                self.assertEqual(merger.advance(Image.fromarray(repeat_frame(actual)), bounds=bounds,
                                               after_drag=True), actual)
        ambiguous = np.full((720, 1280, 3), 100, np.uint8)
        with self.assertRaises(ValueError):
            estimate_scroll(ambiguous, ambiguous, bounds=bounds, check_zero=True)

    def test_thumb_jitter_direction_conflicts_and_unsupported_strokes_do_not_supply_bounds(self):
        motion = ScrollMotion()
        self.assertIsNone(motion.bounds(np.arange(20, 100), (227, True)))
        motion.accept(np.arange(10, 90), 0)
        self.assertIsNone(motion.bounds(np.arange(10, 100), (227, True)))
        self.assertIsNone(motion.bounds(np.arange(20, 100), (-227, True)))
        self.assertIsNone(motion.bounds(np.arange(20, 100), (227, False)))
        self.assertIsNone(motion.bounds(None, (227, True)))
        self.assertEqual(motion.bounds(np.arange(0, 80), (-227, True)), (-233, -1))

    def test_only_strict_coherent_motion_calibrates_unsupported_strokes(self):
        motion = ScrollMotion()
        motion.accept(np.arange(10, 90), 0)
        motion.accept(np.arange(20, 100), 200)
        motion.accept(np.arange(30, 110), 200)
        self.assertEqual(len(motion.ratios), 2)
        bounds = motion.bounds(np.arange(40, 120), (227, False))
        self.assertLessEqual(bounds[0], 206)
        self.assertGreaterEqual(bounds[1], 206)
        self.assertLess(bounds[1], 433)
        self.assertIsNone(motion.bounds(np.arange(100, 180), (227, True)))
        motion.accept(np.arange(40, 130), 200)
        self.assertEqual(len(motion.ratios), 2)
        motion.accept(np.arange(50, 140), 200, hinted=True)
        self.assertEqual(len(motion.ratios), 2)

    def test_strictly_unique_motion_conflicting_with_thumb_does_not_choose_another_shift(self):
        from tests.test_mind_calculator import RecognitionTests
        before, after = RecognitionTests.scroll_frames([0, 227])
        merger = ScanMerger()
        merger.advance(Image.fromarray(before))
        with self.assertRaisesRegex(ValueError, '独立滚动证据'):
            merger.advance(Image.fromarray(after), bounds=(-233, -1), after_drag=True)
        self.assertEqual(merger.offset, 0)


class LocalLoopTests(unittest.TestCase):
    def loop(self):
        loop = regression.ScanLoopRegressionTests('test_continuously_unstable_frames_have_a_deadline')
        loop.setUp()
        self.addCleanup(loop.doCleanups)
        return loop

    def test_repeated_native_cards_reach_bottom_without_skipping_or_merging_rows(self):
        loop = self.loop()
        loop.images = {offset: repeat_frame(offset) for offset in loop.images}
        loop.scanner._policy = ScanPolicy(1, 125, True)

        def thumb(_):
            start = 2 + round(loop.position / loop.bottom * 473)
            return (np.arange(565) >= start) & (np.arange(565) < start + 90)

        scrollbar = SimpleNamespace(appear=lambda _: True, total=565, match_color=thumb)
        with patch('module.retire.dock_scan.DOCK_SCROLL', scrollbar):
            ships = loop.scan()
        self.assertEqual(loop.reads, [0, 681, 1362, 2043])
        self.assertEqual(len(ships), 84)
        self.assertEqual(loop.scanner._scan_metadata, dict(reached_bottom=True, physical_count=84))

    def test_one_ambiguous_frame_retries_only_current_motion(self):
        loop = self.loop()
        merger = ScanMerger()
        advance = merger.advance
        failed = False

        def transient(*args, **kwargs):
            nonlocal failed
            if loop.position == 227 and not failed:
                failed = True
                raise ValueError('模拟单帧位移未确认')
            return advance(*args, **kwargs)

        merger.advance = transient
        loop.scanner._make_merger = lambda: merger
        self.assertEqual(len(loop.scan()), 42)
        self.assertTrue(failed)
        self.assertEqual(loop.reads, [0, 681, 1362])

    def test_same_type_name_ambiguity_keeps_each_slot_without_repeated_page_ocr(self):
        loop = self.loop()
        recognize = loop.recognize

        def ambiguous(*args, **kwargs):
            cards = recognize(*args, **kwargs)
            if loop.position == 0:
                for card in cards[:2]:
                    card.ship.update(name='约克', review=True)
                    card.identity_ambiguous = True
            return cards

        with patch('module.retire.dock_scan.recognize_cards', side_effect=ambiguous):
            ships = loop.scan()
        self.assertEqual(loop.reads, [0, 681, 1362])
        reviews = [ship for ship in ships if ship['review']]
        self.assertEqual([ship['name'] for ship in reviews], ['约克', '约克'])

    def test_slow_page_ocr_is_not_charged_to_the_next_scroll_timeout(self):
        loop = self.loop()
        recognize = loop.recognize

        def slow(*args, **kwargs):
            loop.now += 45
            return recognize(*args, **kwargs)

        with patch('module.retire.dock_scan.recognize_cards', side_effect=slow):
            self.assertEqual(len(loop.scan()), 42)
        self.assertEqual(loop.reads, [0, 681, 1362])

    def test_missing_card_retries_then_preserves_only_that_slot_as_unknown(self):
        from module.retire.dock_scan import DockScan
        loop = self.loop()
        loop.scanner._check_scan_page = DockScan._check_scan_page.__get__(loop.scanner)
        recognize = loop.recognize

        def missing(*args, **kwargs):
            cards = recognize(*args, **kwargs)
            return cards[:11] + cards[12:] if loop.position == 0 else cards

        with patch('module.retire.dock_scan.recognize_cards', side_effect=missing):
            ships = loop.scan()
        unknown = [ship for ship in ships if ship['review']]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]['level'], 0)
        self.assertIn('未加载', unknown[0]['source'])
        self.assertEqual(loop.reads, [0, 0, 0, 681, 1362])
        self.assertLess(loop.position, loop.bottom)

    def test_entire_missing_page_is_not_fabricated_from_grid_positions(self):
        from module.retire.dock_scan import DockScan
        loop = self.loop()
        loop.scanner._check_scan_page = DockScan._check_scan_page.__get__(loop.scanner)
        with patch('module.retire.dock_scan.recognize_cards', return_value=[]):
            with self.assertRaises(MindCalculatorScanError):
                loop.scan()
        loop.scanner.device.drag.assert_not_called()

    def test_current_bad_level_cannot_trigger_early_stop_but_next_clean_page_can(self):
        from tests.test_mind_scan import cards_for_levels
        cards = cards_for_levels([94] * 21)
        cards[10].level_reliable = False
        cards[10].ship.update(level=0, review=True)
        slots = [[card, card.y] for card in cards]
        policy = ScanPolicy(95, 125, True)
        self.assertFalse(policy.can_stop(cards, slots))
        fresh = cards_for_levels([93] * 21)
        slots += [[card, card.y + 681] for card in fresh]
        self.assertTrue(policy.can_stop(fresh, slots))
        self.assertEqual(slots[10][0].ship['level'], 0)
        fresh[0].ship['level'] = 100
        self.assertFalse(policy.can_stop(fresh, slots))
