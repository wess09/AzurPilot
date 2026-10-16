"""心智计算器的三行范围扫描、真实截图和传输层回归。"""
import base64
import io
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageOps
import numpy as np

from module.api.app import create_app
from module.api.config_service import ConfigService
from module.api.mind_calculator_service import MindCalculatorService
from module.api.protocol import ApiError, ConfigChange
from module.runtime.mind_calculator import calculate
from module.runtime.mind_recognition import Card, ScanMerger, ScanPolicy, _match_name, normalize_screenshot, recognize_cards
from tests.test_api import fixture


# 真实截图已遮盖顶部容量，保留船坞标识和三行卡片用于识别回归。
FIXTURES = Path(__file__).parent / 'fixtures'


def cards_for_levels(levels, fleet=0):
    return [Card(93 + col * 165, 65 + row * 227, col,
                 dict(name='拉菲', level=level, rarity='SR', source='', review=False), 6, True, fleet)
            for index, level in enumerate(levels) for row, col in [divmod(index, 7)]]


class ScrollEvidenceTests(unittest.TestCase):
    def test_fresh_confirmed_overlap_replaces_unknown_zero_level_without_a_false_conflict(self):
        frame = Image.new('RGB', (1280, 720), (80, 80, 80))
        merger = ScanMerger()
        old = cards_for_levels([0])[0]
        old.quality, old.level_reliable, old.ship['review'] = 4, False, True
        merger.add(frame, [old])
        merger.add(frame, cards_for_levels([1]))
        self.assertEqual(merger.ships()[0]['level'], 1)
        self.assertFalse(merger.ships()[0]['review'])

    def test_signed_displacements_at_sampling_and_search_boundaries(self):
        from module.runtime.mind_recognition import estimate_scroll
        # 包含暗背景与采样阈值两侧的纹理，正反位移都须由图像而非触控距离得出。
        content = np.random.default_rng(20261011).integers(0, 230, (1030, 1140, 3), dtype=np.uint8)
        def frame(offset):
            pixels = np.zeros((720, 1280, 3), dtype=np.uint8)
            pixels[65:640, 85:1225] = content[offset:offset + 575]
            return pixels
        first = frame(0)
        for shift in (0, 1, 9, 227, 454):
            with self.subTest(shift=shift):
                second = frame(shift)
                self.assertEqual(estimate_scroll(first, second), shift)
                self.assertEqual(estimate_scroll(second, first), -shift)
        with self.assertRaisesRegex(ValueError, '没有明确'):
            estimate_scroll(first, frame(455))

    def test_equal_nonzero_scores_are_ambiguous(self):
        from module.runtime.mind_recognition import estimate_scroll
        before = np.full((720, 1280, 3), 100, dtype=np.uint8)
        after = np.full_like(before, 110)
        with self.assertRaisesRegex(ValueError, '没有明确'):
            estimate_scroll(before, after)


class ScanFailureTests(unittest.TestCase):
    def test_full_scan_count_mismatch_does_not_discard_results(self):
        from module.retire.mind_scan import MindCalculatorScan
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        scanner._scan_metadata = dict(reached_bottom=True, physical_count=2)
        scanner._scan_raw_ships = [dict(name='拉菲', level=120, group_type=10117)]
        self.assertFalse(scanner._verify_full_count(2))
        self.assertEqual(scanner._scan_raw_ships[0]['level'], 120)

    def test_failed_scan_keeps_old_list_and_disables_only_its_ocr_debug(self):
        import copy
        from module.exception import MindCalculatorScanError
        from module.retire.mind_scan import MindCalculatorScan
        from unittest.mock import call
        config = SimpleNamespace(MindCalculator_MinLevel=95, MindCalculator_MaxLevel=120,
                                 data={'MindCalculatorScan': {'MindCalculator': {'Result': {'ships': [
                                     {'name': '拉菲', 'level': 100, 'source': '旧清单'}]}}}}, modified={})
        previous = copy.deepcopy(config.data)
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        scanner.config, scanner.device = config, Mock()
        scanner.ui_ensure, scanner.dock_reset, scanner.dock_sort_method_dsc_set = Mock(), Mock(), Mock()
        scanner._close_search = Mock()
        scanner._prune_scan_evidence = Mock()
        scanner.appear = Mock(return_value=False)
        for error, message in ((MindCalculatorScanError('离线中止'), '离线中止'),):
            with self.subTest(error=type(error).__name__):
                scanner._scan_factions = Mock(side_effect=error)
                with patch('module.retire.mind_scan.server.server', 'cn'), \
                        patch('module.retire.mind_scan.DOCK_SCROLL') as scroll, patch('module.ocr.al_ocr.AlOcr') as ocr:
                    scroll.appear.return_value = scroll.at_top.return_value = True
                    with self.assertRaisesRegex(MindCalculatorScanError, message):
                        scanner.run()
                self.assertEqual(config.data, previous)
                self.assertEqual(config.modified, {})
                scanner._prune_scan_evidence.assert_not_called()
                self.assertEqual(ocr.call_args_list, [call(config=config, name='ppocr_v6', save_debug_images=False),
                                                      call(config=config, name='azur_lane', save_debug_images=False)])

    def check_suffix_reread(self, recovered, signatures=None, extra_screenshots=0, kind='suffix', capture_error=False):
        import copy
        from module.retire.mind_scan import MindCalculatorScan
        from module.exception import MindCalculatorScanError
        class ImmediateTimer:
            def __init__(self, limit, *args, **kwargs): self.limit = limit
            def start(self): return self
            def reset(self): return self
            def reached(self): return self.limit < 5
        uncertain = Card(93, 65, 0, dict(name='列克星敦I', level=93, rarity='SSR', base_rarity='',
                                       excluded=False, review=True, source='后缀未确认'), 2, True)
        confirmed = copy.deepcopy(uncertain)
        confirmed.ship.update(name='列克星敦II', rarity='UR', base_rarity='UR', review=False)
        confirmed.quality = 6
        reason = 'II 型后缀'
        if kind != 'suffix':
            uncertain.ship = copy.deepcopy(confirmed.ship)
            uncertain.fleet = -1 if kind == 'unknown_fleet' else 1
            reason = '编队/排序'
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        scanner.config, scanner.device = SimpleNamespace(Emulator_ControlMethod='MaaTouch', config_name='testpilot'), Mock()
        scanner.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        scanner.appear = Mock(return_value=True)
        scanner._stable_pixels = Mock(return_value=np.zeros((2, 2), dtype=np.uint8), side_effect=signatures)
        scanner._policy = ScanPolicy(90, 115, True)
        merger = Mock(slots=[], offset=0)
        if kind == 'order':
            previous = copy.deepcopy(confirmed)
            previous.y, previous.ship['level'] = -162, 100
            merger.slots = [[previous, previous.y]]
        merger.advance.return_value = 0
        merger.ships.return_value = [confirmed.ship]
        thumb = np.ones(565)
        scroll = SimpleNamespace(appear=lambda _: True, total=565, match_color=lambda _: thumb)
        with tempfile.TemporaryDirectory() as temp, \
                patch('module.retire.mind_scan.logger.log_file', str(Path(temp) / 'testpilot.txt')), \
                patch('module.retire.mind_scan.Timer', ImmediateTimer), patch('module.retire.mind_scan.DOCK_SCROLL', scroll), \
                patch('module.retire.mind_scan.ScanMerger', return_value=merger), \
                patch('module.retire.mind_scan.grid_rows', return_value=[65, 292, 519]), \
                patch('module.retire.mind_scan.recognize_cards') as recognize:
            if capture_error:
                self.enterContext(patch.object(Image.Image, 'save', side_effect=OSError('模拟诊断目录不可写')))
            if recovered:
                recognize.side_effect = [[uncertain], [confirmed]]
                self.assertEqual(scanner._scan_pages(Mock(), Mock()), [confirmed.ship])
                self.assertEqual(recognize.call_count, 2)
                merger.add.assert_called_once()
            else:
                recognize.return_value = [uncertain]
                self.assertEqual(scanner._scan_pages(Mock(), Mock()), [confirmed.ship])
                self.assertEqual(recognize.call_count, 3)
                merger.add.assert_called_once()
                self.assertTrue(uncertain.ship['review'])
                self.assertIn('待人工核对', uncertain.ship['source'])
                if kind != 'suffix':
                    self.assertFalse(scanner._policy.can_stop([uncertain], merger.slots))
            self.assertEqual(scanner.device.screenshot.call_count, recognize.call_count * 2 + extra_screenshots)
            captures = int(kind != 'suffix') + int(not recovered) + int(recovered and kind != 'suffix')
            self.assertEqual(len(list(Path(temp).rglob('*.png'))), captures if not capture_error else 0)
        scanner.device.drag.assert_not_called()
        scanner.device.save_screenshot.assert_not_called()

    def test_uncertain_second_type_takes_new_frame_before_merge(self):
        self.check_suffix_reread(recovered=True)

    def test_uncertain_second_type_is_marked_review_after_three_frames(self):
        self.check_suffix_reread(recovered=False)

    def test_fleet_and_order_conflicts_take_new_frame_before_merge(self):
        for kind in ('unknown_fleet', 'order'):
            with self.subTest(kind=kind):
                self.check_suffix_reread(recovered=True, kind=kind)

    def test_fleet_and_order_conflicts_are_marked_review_after_three_frames(self):
        for kind in ('unknown_fleet', 'order'):
            with self.subTest(kind=kind):
                self.check_suffix_reread(recovered=False, kind=kind)

    def test_unwritable_diagnostic_does_not_break_fresh_frame_recheck(self):
        self.check_suffix_reread(recovered=True, kind='order', capture_error=True)

    def test_stability_requires_new_frame_only_above_full_pixel_threshold(self):
        # 覆盖原平均差阈值两侧及等号；新增稳定等待不能跳过识别前的新截图。
        before = np.zeros((720, 1280), dtype=np.uint8)
        for delta in (-1, 0, 1):
            with self.subTest(delta=delta):
                after = np.ones_like(before)
                after[0, 0] = 1 + delta
                self.check_suffix_reread(recovered=True, signatures=[before] + [after] * 8,
                                        extra_screenshots=int(delta > 0))


class RangeTests(unittest.TestCase):
    def test_inclusive_boundaries_exclude_zero_and_outside_levels(self):
        merger = ScanMerger()
        cards = cards_for_levels([118, 115, 115, 90, 89, 0])
        for index, card in enumerate(cards):
            card.ship['name'] = f'舰船{index}'
        merger.slots = [[card, card.y] for card in cards]
        self.assertEqual([ship['level'] for ship in merger.ships(90, 115)], [115, 115, 90])

    def test_later_higher_level_replaces_entire_same_name_record(self):
        merger = ScanMerger()
        cards = cards_for_levels([100, 105, 99])
        cards[1].ship['source'] = '后面的更高等级'
        merger.slots = [[card, card.y] for card in cards]
        self.assertEqual(merger.ships(90, 115), [cards[1].ship])

    def test_pixel_registration_error_does_not_accumulate_duplicate_rows(self):
        merger = ScanMerger()
        image = Image.new('RGB', (1280, 720), (80, 80, 80))
        for page in range(30):
            with patch('module.runtime.mind_recognition.estimate_scroll', return_value=228):
                merger.add(image, cards_for_levels([100] * 21))
        self.assertEqual(len(merger.slots), 7 * 32)
        self.assertEqual(merger.offset, 227 * 29)

    def test_uncertain_level_is_retained_as_unknown_review_without_billing(self):
        card = cards_for_levels([89])[0]
        card.level_reliable = False
        merger = ScanMerger(); merger.slots = [[card, card.y]]
        rows = merger.ships(90, 115)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['level'], 0)
        self.assertTrue(rows[0]['review'])
        self.assertEqual(calculate(rows)['mind'], 0)

    def test_review_cards_outside_range_remain_visible_and_never_bill(self):
        cards = cards_for_levels([118, 89, 100])
        for card in cards[:2]:
            card.ship['review'] = True
        merger = ScanMerger(); merger.slots = [[card, card.y] for card in cards]
        rows = merger.ships(90, 115)
        self.assertEqual([row['level'] for row in rows], [118, 89, 100])
        self.assertEqual(calculate(rows)['review'], 2)
        self.assertEqual(calculate(rows)['included'], 1)

    def test_name_disagreement_does_not_invalidate_matching_levels(self):
        image = Image.new('RGB', (1280, 720), (80, 80, 80))
        merger = ScanMerger()
        merger.add(image, cards_for_levels([118]))
        retry = cards_for_levels([118])
        retry[0].ship['name'] = '未知舰船'
        merger.add(image, retry)
        self.assertTrue(merger.slots[0][0].level_reliable)
        self.assertIn('跨屏读数不一致', merger.slots[0][0].ship['source'])
        self.assertEqual(merger.ships(90, 115)[0]['level'], 118)
        self.assertEqual(calculate(merger.ships(90, 115))['mind'], 0)
        retry[0].ship['level'] = 18
        merger.add(image, retry)
        self.assertFalse(merger.slots[0][0].level_reliable)
        self.assertEqual(merger.ships(90, 115)[0]['level'], 0)
        self.assertTrue(merger.ships(90, 115)[0]['review'])

    def test_three_rows_without_minimum_but_with_eligible_ships_continue(self):
        cards = cards_for_levels([115] * 7 + [100] * 7 + [91] * 7)
        policy = ScanPolicy(90, 115, sorted_desc=True)
        self.assertFalse(policy.can_stop(cards, [[card, card.y] for card in cards]))

    def test_complete_three_rows_below_minimum_stop(self):
        cards = cards_for_levels([89] * 7 + [80] * 7 + [70] * 7)
        self.assertTrue(ScanPolicy(90, 115, True).can_stop(cards, [[card, card.y] for card in cards]))

    def test_sort_preview_does_not_poison_confirmed_cumulative_order(self):
        cards = cards_for_levels([89] * 21)
        slots = [[card, card.y] for card in cards]
        policy = ScanPolicy(90, 115, True)
        cards[1].fleet = 1
        self.assertIn('普通舰之后', policy.sort_issue(slots))
        self.assertTrue(policy.sort_valid)
        cards[1].fleet = -1
        self.assertIn('未确认', policy.sort_issue(slots))
        self.assertFalse(policy.can_stop(cards, slots))
        self.assertFalse(policy.sort_valid)
        cards[1].fleet = 0
        self.assertEqual(policy.sort_issue(slots), '')
        self.assertTrue(policy.can_stop(cards, slots))

    def test_missing_uncertain_unsorted_and_fleet_priority_cannot_stop(self):
        for kind in ('missing', 'unknown_level', 'unknown_fleet', 'fleet', 'unsorted', 'unconfirmed_sort'):
            with self.subTest(kind=kind):
                current = cards_for_levels([89] * 21)
                policy = ScanPolicy(90, 115, kind != 'unconfirmed_sort')
                if kind == 'missing': current.pop()
                if kind == 'unknown_level': current[0].level_reliable = False
                if kind == 'unknown_fleet': current[0].fleet = -1
                if kind == 'fleet':
                    for card in current: card.fleet = 1
                if kind == 'unsorted': current[1].ship['level'] = 90
                self.assertFalse(policy.can_stop(current, [[card, card.y] for card in current]))
        # 置顶编队的低等级后面接普通高等级是正常游戏排序。
        fleet = cards_for_levels([70] * 21, fleet=1)
        ordinary = cards_for_levels([125] * 21)
        policy = ScanPolicy(90, 115, True)
        self.assertFalse(policy.can_stop(ordinary, [[c, c.y] for c in fleet] + [[c, c.y + 681] for c in ordinary]))
        self.assertTrue(policy.sort_valid)

    def test_name_review_does_not_prevent_confirmed_level_stop(self):
        cards = cards_for_levels([89] * 21)
        cards[0].quality = 2
        self.assertTrue(ScanPolicy(90, 115, True).can_stop(cards, [[card, card.y] for card in cards]))

    def test_range_validation(self):
        for low, high in [(0, 120), (95, 126), (115, 90), (True, 120)]:
            with self.assertRaises(ValueError): ScanPolicy(low, high)

    def test_range_config_defaults_and_api_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            configs = ConfigService(fixture(temp))
            service = MindCalculatorService(configs)
            report = service.report('testpilot')
            self.assertEqual((report['min_level'], report['max_level']), (95, 125))
            configs.patch('testpilot', configs.get('testpilot')['revision'], [
                ConfigChange(path='MindCalculatorScan.MindCalculator.MinLevel', value=90),
                ConfigChange(path='MindCalculatorScan.MindCalculator.MaxLevel', value=115),
            ])
            report = service.report('testpilot')
            self.assertEqual((report['min_level'], report['max_level']), (90, 115))
            with self.assertRaises(ApiError):
                configs.patch('testpilot', configs.get('testpilot')['revision'], [
                    ConfigChange(path='MindCalculatorScan.MindCalculator.MaxLevel', value=126),
                ])


class NativeLevelTests(unittest.TestCase):
    def test_real_blue_frames_are_not_unknown_fleet_badges(self):
        from module.retire.scanner import FleetScanner
        from module.runtime.mind_recognition import fleet_status
        pixels = np.array(Image.open(FIXTURES / 'mind_fleet_blue.png').convert('RGB'))
        reader = FleetScanner()
        for y in range(0, pixels.shape[0], 45):
            self.assertEqual(fleet_status(pixels[y:y + 45], reader), 0)

    def test_fleet_text_preserves_uncertainty_when_number_is_missing(self):
        from module.retire.scanner import FleetScanner
        from module.runtime.mind_recognition import fleet_status, grid_rows
        from module.retire.dock import CARD_GRIDS
        pixels = np.array(Image.open(FIXTURES / 'mind_dock_fleet_priority.png').convert('RGB'))
        y, x = grid_rows(pixels)[0], round(float(CARD_GRIDS.origin[0]))
        reader = FleetScanner()
        with patch('module.runtime.mind_recognition._fleet_number', return_value=0):
            self.assertEqual(fleet_status(pixels[y + 117:y + 162, x:x + 35], reader), -1)

    def test_independent_real_glyphs_never_accept_another_level(self):
        from module.runtime.mind_level import dock_level_reader
        reader = dock_level_reader()
        cases = json.loads((FIXTURES / 'mind_levels.json').read_text(encoding='utf-8'))
        pixels = np.array(Image.open(FIXTURES / 'mind_levels.png'))
        confirmed = 0
        for page, case in enumerate(cases):
            if case['training']:
                continue
            for index, expected in enumerate(case['levels']):
                row, col = divmod(index, 7)
                raw = pixels[(page * 3 + row) * 32:(page * 3 + row + 1) * 32, col * 64:(col + 1) * 64]
                glyphs, _, _ = reader.prepare(raw)
                value = reader.read(glyphs)
                self.assertIn(value, (0, expected), (index, expected, value))
                confirmed += bool(value)
        self.assertGreaterEqual(confirmed, 15)

    def test_blank_level_has_no_digit_identity(self):
        from module.runtime.mind_level import dock_level_reader
        reader = dock_level_reader()
        glyphs, _, _ = reader.prepare(np.full((32, 64, 3), 255, dtype=np.uint8))
        self.assertEqual(glyphs, [])
        self.assertEqual(reader.read(glyphs), 0)

    def test_short_gesture_accounts_for_game_activation_distance(self):
        from module.retire.mind_scan import MindCalculatorScan
        scanner = MindCalculatorScan.__new__(MindCalculatorScan)
        scanner.config = SimpleNamespace(Emulator_ControlMethod='MaaTouch')
        scanner.device = Mock()
        scanner._drag_rows(13)
        self.assertEqual(scanner.device.drag.call_args.args, ((1170, 470), (1170, 437)))
        self.assertEqual(scanner.device.drag.call_args.kwargs['hold_duration'], .4)


class ScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = Image.open(FIXTURES / 'mind_dock_fleet_priority.png').convert('RGB')
        cls.cards = recognize_cards(cls.image)

    def test_real_three_rows_and_exact_levels(self):
        self.assertEqual([c.ship['level'] for c in self.cards],
                         [120, 110, 110, 110, 105, 105, 105, 105, 100, 100, 100, 100, 99, 99, 97, 84, 79, 76, 71, 70, 70])
        self.assertEqual(len({c.y for c in self.cards}), 3)
        self.assertTrue(all(c.level_reliable for c in self.cards))
        self.assertTrue(all(c.fleet != 0 for c in self.cards))
        self.assertEqual(self.cards[8].ship['name'], '杓鹬.改')
        self.assertEqual(self.cards[13].ship['name'], '阿尔弗雷多·奥里亚尼')
        # 名单、等级和基础稀有度已确认的原始结果直接计费，无需修改核对字段。
        selected = [c.ship for c in self.cards if 90 <= c.ship['level'] <= 115]
        report = calculate(selected)
        self.assertEqual([ship['name'] for ship in selected if ship['review']], ['新月'])
        self.assertEqual(report['review'], 1)
        self.assertEqual(report['included'], len(selected) - 2)
        self.assertEqual(report['excluded'], 1)  # 帕特莉夏为联动舰，保存但不计费。
        self.assertGreater(report['mind'], 0)

    def test_upload_defaults_skip_debug_io_and_explicit_reader_can_collect(self):
        from dataclasses import asdict
        from module.ocr.al_ocr import AlOcr, OcrSettings
        with patch.object(AlOcr, '_save_debug_image') as save:
            silent = recognize_cards(self.image)
            save.assert_not_called()
            names = AlOcr(name='ppocr_v6', settings=OcrSettings('onnx', 'cpu', False, 'standard'))
            diagnostic = recognize_cards(self.image, name_ocr=names)
            self.assertGreater(save.call_count, 0)
        self.assertEqual([asdict(c) for c in silent], [asdict(c) for c in diagnostic])
        self.assertEqual([asdict(c) for c in silent], [asdict(c) for c in self.cards])

    def test_scaled_and_black_border_images_share_layout(self):
        cases = [self.image.resize((1920, 1080)), self.image.resize((960, 540)),
                 ImageOps.expand(self.image, (80, 45, 80, 45)), ImageOps.expand(self.image, (0, 40, 0, 40))]
        expected = [c.ship['level'] for c in self.cards]
        for image in cases:
            with self.subTest(size=image.size):
                normalized = normalize_screenshot(image)
                self.assertEqual(normalized.size, (1280, 720))
                self.assertEqual([c.ship['level'] for c in recognize_cards(normalized)], expected)

    def test_duplicate_names_remain_separate_cards(self):
        cards = recognize_cards(Image.open(FIXTURES / 'mind_dock_duplicates.png'))
        names = [c.ship['name'] for c in cards]
        self.assertEqual(len(cards), 21)
        for name in ['加拉蒂亚', '牙买加', '苏塞克斯', '阳炎']:
            self.assertEqual(names.count(name), 2)

    def test_retries_correct_only_unique_catalog_names(self):
        self.assertEqual(_match_name(['小猎免犬', '小猎兔犬'], 'R')[0]['name'], '小猎兔犬')
        self.assertIsNone(_match_name(['未知的舰船', '完全陌生'], 'SSR')[0])
        self.assertIsNone(_match_name(['皇家方舟·META', '皇家方舟'], 'SSR')[0])
        self.assertIsNone(_match_name(['拉菲', '标枪'], 'SR')[0])

    def test_unknown_name_keeps_review_when_level_is_confirmed(self):
        ocr = Mock()
        ocr.ocr_for_single_lines.side_effect = lambda regions: ['不存在的舰船'] * len(regions)
        cards = recognize_cards(self.image, name_ocr=ocr)
        self.assertTrue(all(card.level_reliable for card in cards))
        self.assertTrue(all(card.ship['review'] for card in cards))
        self.assertEqual(calculate([card.ship for card in cards])['mind'], 0)

    def test_native_name_crops_use_fleet_preprocessing(self):
        from module.ocr.al_ocr import AlOcr, OcrSettings
        from module.runtime.mind_recognition import _name_image, _scanners
        atlas = np.array(Image.open(FIXTURES / 'mind_names.png').convert('RGB'))
        labels = json.loads((FIXTURES / 'mind_names.json').read_text(encoding='utf-8'))
        regions = [atlas[index * 30:(index + 1) * 30] for index in range(len(labels))]
        prepared = [_name_image(region) for region in regions]
        for region, clean in zip(regions, prepared):
            np.testing.assert_array_equal(clean, _scanners()[1].pre_process(region))
            self.assertEqual(clean.shape, (19, 148))
        ocr = AlOcr(name='ppocr_v6', settings=OcrSettings('onnx', 'cpu', False, 'standard'))
        reads = ocr.ocr_for_single_lines(prepared)
        for raw, label in zip(reads, labels):
            self.assertEqual(_match_name([raw], 'SSR')[0]['name'], label['name'], raw)

    def test_verified_name_errors_preserve_second_type_identity(self):
        self.assertEqual(_match_name(['约克城ⅡI'], 'SSR')[0]['name'], '约克城II')
        self.assertEqual(_match_name(['列克星敦ⅡI'], 'SSR')[0]['name'], '列克星敦II')
        self.assertEqual(_match_name(['列克星敦', '列克星敦ⅡI', '列克星敦ⅡI'], 'SSR')[0]['name'], '列克星敦II')
        self.assertIsNone(_match_name(['列克星敦', '列克星敦II'], 'SSR')[0])
        for raw, name in [('酒句', '酒匂'), ('条鱼', '鲦鱼'), ('绦鱼', '鲦鱼'), ('四系乃', '四糸乃'), ('百雪', '白雪')]:
            self.assertEqual(_match_name([raw], 'SSR')[0]['name'], name)

    def test_second_type_family_requests_evidence_without_guessing_identity(self):
        from module.runtime.mind_recognition import second_type_family
        self.assertTrue(second_type_family(['列克星敦I']))
        self.assertTrue(second_type_family(['列克星敦', '列克星敦ⅡI']))
        self.assertFalse(second_type_family(['不存在的舰船I', '倫敦']))
        self.assertIsNone(_match_name(['列克星敦I'], 'SSR')[0])
        self.assertIsNone(_match_name(['北安普敦I'], 'SSR')[0])
        self.assertEqual(_match_name(['北安普敦ⅡI'], 'SSR')[0]['name'], '北安普敦II')

    def test_only_unconfirmed_second_type_gets_nearest_neighbor_retry(self):
        ocr = Mock()
        ocr.ocr_for_single_lines.side_effect = [
            ['列克星敦I'] + ['伦敦.改'] * 20,
            ['列克星敦', '列克星敦II'], ['列克星敦II', '列克星敦II']]
        cards = recognize_cards(self.image, name_ocr=ocr)
        self.assertEqual(cards[0].ship['name'], '列克星敦II')
        self.assertFalse(cards[0].ship['review'])
        self.assertEqual(ocr.ocr_for_single_lines.call_count, 3)
        variants = ocr.ocr_for_single_lines.call_args.args[0]
        self.assertEqual([image.shape for image in variants], [(38, 296), (57, 444)])
        ocr.ocr_for_single_lines.reset_mock(side_effect=True)
        ocr.ocr_for_single_lines.return_value = ['伦敦.改'] * 21
        recognize_cards(self.image, name_ocr=ocr)
        ocr.ocr_for_single_lines.assert_called_once()

    def test_failed_suffix_retry_remains_review(self):
        ocr = Mock()
        def unknown_suffix(images):
            if ocr.ocr_for_single_lines.call_count == 1:
                return ['列克星敦I'] + ['伦敦.改'] * 20
            return ['列克星敦I'] * len(images)
        ocr.ocr_for_single_lines.side_effect = unknown_suffix
        card = recognize_cards(self.image, name_ocr=ocr)[0]
        self.assertTrue(card.ship['review'])
        self.assertEqual(card.ship['name'], '列克星敦I')
        self.assertLessEqual(ocr.ocr_for_single_lines.call_count, 6)

    def test_real_second_type_crops_keep_suffix_under_nearest_scaling(self):
        import cv2
        from module.ocr.al_ocr import AlOcr, OcrSettings
        from module.runtime.mind_recognition import _name_image
        atlas = np.array(Image.open(FIXTURES / 'mind_names_second_types.png').convert('RGB'))
        labels = json.loads((FIXTURES / 'mind_names_second_types.json').read_text(encoding='utf-8'))
        reader = AlOcr(name='ppocr_v6', settings=OcrSettings('onnx', 'cpu', False, 'standard'), save_debug_images=False)
        images = [cv2.resize(_name_image(atlas[top:bottom, left:right]), None,
                             fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
                  for label in labels for left, top, right, bottom in [label['atlas_region']] for scale in (2, 3)]
        reads = reader.ocr_for_single_lines(images)
        for index, label in enumerate(labels):
            info, _ = _match_name(reads[index * 2:index * 2 + 2], 'SSR')
            self.assertIsNotNone(info, reads[index * 2:index * 2 + 2])
            self.assertEqual(info['name'], label['name'])

    def test_invalid_images_have_specific_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            service = MindCalculatorService(ConfigService(fixture(temp)))
            def recognize(image):
                stream = io.BytesIO(); image.save(stream, format='PNG')
                return service.recognize('testpilot', 'wrong.png', base64.b64encode(stream.getvalue()).decode())
            for image, message in [(Image.new('RGB', (1280, 720)), '全黑'),
                                   (Image.new('RGB', (1000, 720), 'white'), '16:9'),
                                   (Image.new('RGB', (1280, 720), 'white'), '船坞界面')]:
                with self.subTest(message=message):
                    with self.assertRaises(ApiError) as error:
                        recognize(image)
                    self.assertIn(message, error.exception.message)
            with self.assertRaises(ApiError) as error:
                service.recognize('testpilot', 'broken.png', base64.b64encode(b'not an image').decode())
            self.assertIn('截图识别失败', error.exception.message)


class TransportTests(unittest.TestCase):
    def test_actual_server_accepts_large_screenshot_and_rejects_large_regular_request(self):
        """使用 gui 的真实 Uvicorn 配置，不能仅由 TestClient 绕过帧大小检查。"""
        import gui
        import uvicorn
        from websockets.sync.client import connect
        state = SimpleNamespace(deploy_config=SimpleNamespace(WebuiHost='127.0.0.1', WebuiPort=0,
                                                              WebuiSSLKey=None, WebuiSSLCert=None))
        with patch.object(gui, 'State', state), patch('sys.argv', ['gui.py']), \
                patch('deploy.frontend.ensure_frontend'), patch('module.logger.set_file_logger'), \
                patch('module.logger.set_console_logger'), patch('gui._run_uvicorn_server') as run:
            gui.func(None)
        config = run.call_args.args[0]
        self.assertEqual(config.ws_max_size, 8 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as temp, socket.socket() as listener:
            app = create_app(root=fixture(temp), password='', manage_runtime=False, mount_mcp=False)
            listener.bind(('127.0.0.1', 0)); listener.listen()
            config.app, config.factory, config.log_level = app, False, 'error'
            config.loaded = False
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            thread.start()
            try:
                until = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < until:
                    time.sleep(.01)
                self.assertTrue(server.started)
                with connect(f'ws://127.0.0.1:{listener.getsockname()[1]}/api/v1/ws', max_size=8 * 1024 * 1024) as ws:
                    ws.recv(timeout=5)  # 连接握手通知
                    content = base64.b64encode((FIXTURES / 'mind_dock_fleet_priority.png').read_bytes()).decode()
                    self.assertGreater(len(content), 1024 * 1024)
                    ws.send(json.dumps(dict(v=1, type='request', id='dock', method='mind.recognize', params=dict(instance='testpilot', filename='dock.png', content=content))))
                    reply = json.loads(ws.recv(timeout=30))
                    self.assertTrue(reply['ok'], reply)
                    self.assertEqual(len(reply['result']['ships']), 21)
                    ws.send(json.dumps(dict(v=1, type='request', id='oversize', method='mind.report', params=dict(instance='testpilot', junk='x' * (1024 * 1024)))))
                    rejected = json.loads(ws.recv(timeout=5))
                    self.assertEqual(rejected['error']['code'], 'INVALID_REQUEST')
                    # 拒绝普通超大请求后，连接依然可用。
                    ws.send(json.dumps(dict(v=1, type='request', id='alive', method='mind.report', params=dict(instance='testpilot'))))
                    self.assertTrue(json.loads(ws.recv(timeout=5))['ok'])
            finally:
                server.should_exit = True
                thread.join(timeout=10)
            self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
