"""心智单元算法、导入互通、实例保存与离线扫描回归。"""
import base64
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image
from openpyxl import Workbook

from module.api.config_service import ConfigService
from module.api.dock_service import DockService
from module.runtime.fleet_database import FleetDatabase, FleetDatabaseConflict
from module.runtime import dock_data, mind_calculator
from module.api.mind_calculator_service import MindCalculatorService, import_ships
from module.api.protocol import ApiError, MindShip
from module.runtime.mind_calculator import catalog, highest_ships, recognize
from module.runtime.mind_recognition import Card, ScanMerger, color_rows, estimate_scroll, level_vote, recognize_cards
from tests.test_api import fixture


def ship(name='测试舰', level=100, rarity='SSR', **kwargs):
    return MindShip(name=name, level=level, rarity=rarity, **kwargs).model_dump()


def encoded(raw):
    return base64.b64encode(raw).decode()


class CalculatorTests(unittest.TestCase):


    def test_public_catalog_integrity(self):
        for name, info in catalog()['ships'].items():
            self.assertEqual(name, info['name'])
            self.assertIn(info['base_rarity'], ('N', 'R', 'SR', 'SSR', 'UR'))
        self.assertGreater(len(catalog()['ships']), 800)


    def test_shared_data_extractor_attaches_resolved_retrofits_to_playable_ship(self):
        from dev_tools.ship_data_extractor import extract_ship_data
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'CN'
            (root / 'sharecfg').mkdir(parents=True)
            (root / 'sharecfgdata').mkdir()
            (root / 'sharecfg/ship_data_by_type.lua').write_text('', encoding='utf-8')
            (root / 'sharecfg/name_code.lua').write_text('[1] = {\n name = "舰名",\n}\n', encoding='utf-8')
            (root / 'sharecfgdata/ship_data_statistics.lua').write_text(
                '[11] = {\n name = "舰名",\n rarity = 5,\n tag_list = {"Little-series"},\n}\n'
                '[900001] = {\n name = "剧情舰",\n rarity = 6,\n}\n', encoding='utf-8')
            (root / 'sharecfgdata/ship_data_template.lua').write_text(
                '[11] = {\n group_type = 1,\n}\n[900001] = {\n group_type = 1,\n}\n', encoding='utf-8')
            (root / 'sharecfg/ship_skin_template.lua').write_text(
                '[19] = {\n name = "{namecode:1}.改",\n skin_type = 2,\n ship_group = 1,\n}\n',
                encoding='utf-8')
            with patch('sys.stdout', io.StringIO()):
                data = extract_ship_data(directory)
            self.assertEqual(data['11']['retrofit_names'], ['舰名.改'])
            self.assertTrue(data['11']['is_child'])
            self.assertNotIn('retrofit_names', data['900001'])
            (root / 'sharecfg/ship_skin_template.lua').rename(root / 'sharecfgdata/ship_skin_template.lua')
            with patch('sys.stdout', io.StringIO()):
                data = extract_ship_data(directory)
            self.assertEqual(data['11']['retrofit_names'], ['舰名.改'])
            self.assertNotIn('retrofit_names', data['900001'])

    def test_collaboration_catalog_has_original_rarity_without_frame_guessing(self):
        for name in ('帕特莉夏·阿贝尔海姆', 'DEAD MASTER', '雪泉', '雫', '穗香', '环', '八舞耶俱矢·八舞夕弦'):
            with self.subTest(name=name):
                info = catalog()['ships'][name]
                self.assertEqual(info['base_rarity'], 'SSR')
                self.assertEqual(info['group'], '联动')

    def test_retrofit_identity_keeps_highest_and_prefers_retrofit_only_on_ties(self):
        for rows in ([ship('卡辛'), ship('卡辛.改')], [ship('卡辛.改'), ship('卡辛')]):
            self.assertEqual([row['name'] for row in highest_ships(rows)], ['卡辛.改'])
        self.assertEqual(highest_ships([ship('卡辛', 105), ship('卡辛.改', 100)])[0]['name'], '卡辛')
        self.assertEqual(highest_ships([ship('卡辛', 100), ship('卡辛.改', 105)])[0]['name'], '卡辛.改')
        rows = highest_ships([ship('约克城'), ship('约克城II'), ship('皇家方舟'), ship('皇家方舟·META')])
        self.assertEqual(len(rows), 4)

    def test_review_positions_survive_unknown_levels_and_same_name_merge(self):
        rows = [ship('拉菲', 100), ship('拉菲', 0, review=True), ship('拉菲', 120, review=True),
                ship('重复误读', review=True), ship('重复误读', review=True)]
        self.assertEqual(highest_ships(rows), rows)


    def test_upload_keeps_local_level_failure_and_other_confirmed_cards(self):
        image = Image.open(Path(__file__).parent / 'fixtures/mind_dock_fleet_priority.png').convert('RGB')
        cards = [Card(93, 76, 0, ship('拉菲', 0, review=True), 4, False),
                 Card(258, 76, 1, ship('卡辛', 100), 6, True)]
        with patch('module.runtime.mind_recognition.recognize_cards', return_value=cards):
            rows = recognize(image, '局部识别失败.png')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['level'], 0)
        self.assertTrue(rows[0]['review'])
        self.assertIn('第 1 行第 1 列', rows[0]['source'])


    def test_offline_screenshot_uses_ap_models_and_bills_confirmed_results(self):
        image = Image.open(Path(__file__).parent / 'fixtures/fleet_names_vanguard.png').convert('RGB')
        # 舰队夹具已匿名遮盖页头；这里只验证卡片 OCR，上传布局校验使用完整船坞夹具。
        rows = [card.ship for card in recognize_cards(image)]
        self.assertEqual(len(rows), 21)
        self.assertEqual(rows[5]['name'], '灵敏·META')
        self.assertEqual(rows[13]['name'], '热心.改')
        self.assertEqual(rows[13]['level'], 105)
        self.assertEqual([row['name'] for row in rows if row['review']], ['新月'])
        self.assertIn('同名同舰种', rows[7]['source'])
        self.assertEqual([row['level'] for row in rows], [125, 100, 125, 105, 125, 63, 99, 99, 117, 122, 99, 98, 105, 105,
                                                       120, 105, 105, 120, 120, 120, 120])
        with self.assertRaises(ValueError):
            recognize(Image.new('RGB', (2560, 1440)))


class RecognitionTests(unittest.TestCase):
    def test_digit_count_rejects_lost_hundreds_and_conflicting_readings(self):
        self.assertEqual(level_vote(['Lv.25', 'Lv.125', '125'], 3)[0], 125)
        self.assertTrue(level_vote(['25', '25', '25'], 3)[1])
        self.assertEqual(level_vote(['Lv.120', 'Lv.120', '120'], 3), (120, ''))
        self.assertTrue(level_vote(['100', '101', '100'], 3)[1])
        self.assertEqual(level_vote(['noise', '126', '0'])[0], 0)

    def test_colored_header_follows_scrolling_and_unread_cards_survive(self):
        pixels = np.zeros((720, 1280, 3), dtype=np.uint8)
        pixels[103:107, 93:231] = (235, 185, 60)
        pixels[108:290, 93:231] = (80, 80, 80)
        self.assertEqual(color_rows(pixels), [103])
        ocr = Mock()
        ocr.det.return_value = []
        ocr.ocr_for_single_lines.side_effect = lambda regions: [''] * len(regions)
        cards = recognize_cards(Image.fromarray(pixels), name_ocr=ocr, level_ocr=ocr)
        self.assertEqual(len(cards), 1)
        self.assertIn('舰名未读到', cards[0].ship['name'])
        self.assertTrue(cards[0].ship['review'])
        self.assertEqual(cards[0].ship['level'], 0)

    def test_third_row_is_read_and_gray_artwork_is_not_a_card_header(self):
        pixels = np.full((720, 1280, 3), 25, dtype=np.uint8)
        for y in (76, 303, 530):
            pixels[y:y + 4, 93:231] = (235, 185, 60)
        # 实际错误现场中的灰色卡面条带位于列内部，不能生成一排虚假舰船。
        pixels[381:383, 444:535] = (190, 190, 190)
        self.assertEqual(color_rows(pixels), [76, 303, 530])
        ocr = Mock()
        ocr.det.return_value = []
        ocr.ocr_for_single_lines.side_effect = lambda regions: [''] * len(regions)
        cards = recognize_cards(Image.fromarray(pixels), name_ocr=ocr, level_ocr=ocr)
        self.assertEqual([card.y for card in cards], [76, 303, 530])

    @staticmethod
    def scroll_frames(offsets):
        rng = np.random.default_rng(20261010)
        # 随机纹理模拟不同卡面，原图提供超过一屏的内容以核对实际位移。
        content = rng.integers(30, 230, (max(offsets) + 575, 1140, 3), dtype=np.uint8)
        frames = []
        for offset in offsets:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame[65:640, 85:1225] = content[offset:offset + 575]
            frames.append(frame)
        return frames

    @staticmethod
    def scroll_images():
        return RecognitionTests.scroll_frames([0, 227])

    def test_spatial_merge_keeps_distinct_copies_and_best_overlap(self):
        first, second = self.scroll_images()
        self.assertEqual(estimate_scroll(first, second), 227)
        self.assertEqual(estimate_scroll(second, first), -227)
        merger = ScanMerger()
        merger.add(Image.fromarray(first), [Card(93, 76, 0, ship('拉菲', 100), 6, True),
                                            Card(93, 303, 0, ship('拉菲', 100), 1)])
        merger.add(Image.fromarray(second), [Card(93, 76, 0, ship('拉菲', 101), 6, True),
                                             Card(93, 303, 0, ship('拉菲', 100), 6, True)])
        self.assertEqual(len(merger.slots), 3)
        reviewed = next(row for row in merger.ships() if row['review'])
        self.assertEqual(reviewed['level'], 101)
        self.assertIn('跨屏读数不一致', reviewed['source'])
        self.assertTrue(any(row['level'] == 100 and not row['review'] for row in merger.ships()))
        # 相同截图是零位移，重试截图不增加卡片。
        merger.add(Image.fromarray(second), [Card(93, 76, 0, ship('拉菲', 101), 6, True)])
        self.assertEqual(len(merger.slots), 3)

    def test_unrelated_screens_are_not_guessed_as_a_scroll(self):
        first, _ = self.scroll_images()
        other = np.random.default_rng(42).integers(30, 230, (720, 1280, 3), dtype=np.uint8)
        with self.assertRaises(ValueError):
            estimate_scroll(first, other)

    def test_three_row_pages_merge_using_intermediate_scroll_evidence(self):
        frames = self.scroll_frames([0, 227, 454, 681])
        merger = ScanMerger()
        cards = [Card(93, y, 0, ship(f'拉菲{y}', level=100), 6, True) for y in (76, 303, 530)]
        merger.add(Image.fromarray(frames[0]), copy.deepcopy(cards))
        for frame in frames[1:]:
            merger.advance(Image.fromarray(frame))
        merger.add(Image.fromarray(frames[-1]), copy.deepcopy(cards))
        self.assertEqual(merger.offset, 681)
        self.assertEqual(len(merger.slots), 6)

    def scan_frames(self, offsets, *, bottom_offset, damaged=False, later_conflict=False, cross_conflict=False,
                    partial_last=False):
        from module.retire.dock_scan import DockScan
        from types import SimpleNamespace
        class ImmediateTimer:
            def __init__(self, limit, *args, **kwargs):
                self.limit = limit
            def start(self):
                return self
            def reset(self):
                return self
            def reached(self):
                return self.limit < 5
        images = self.scroll_frames(sorted(set(offsets)))
        by_offset = dict(zip(sorted(set(offsets)), images))
        frames = iter(offsets)
        scanner = DockScan.__new__(DockScan)
        scanner.config = SimpleNamespace(Emulator_ControlMethod='MaaTouch', config_name='testpilot')
        from module.runtime.mind_recognition import ScanPolicy
        scanner._policy = ScanPolicy(90, 115, sorted_desc=True)
        scanner.device = Mock()
        position = [0]
        def screenshot():
            position[0] = next(frames)
            scanner.device.image = by_offset[position[0]]
        scanner.device.screenshot.side_effect = screenshot
        scanner.appear = Mock(return_value=True)
        scrollbar = SimpleNamespace(appear=lambda _: True, total=565,
                                    match_color=lambda _: np.arange(565) >= 475 if position[0] == bottom_offset
                                    else (np.arange(565) >= 2) & (np.arange(565) < 92))
        captured = []
        def recognize(*args, **kwargs):
            captured.append(position[0])
            if damaged or cross_conflict:
                value = 110 if cross_conflict and position[0] == 681 else 100 if cross_conflict else 88
                cards = [Card(93 + col * 165, y, col, ship(f'舰船{round((y - 76 + position[0]) / 227)}-{col}', level=value), 6, True)
                         for y in (76, 303, 530) for col in range(7)]
                if damaged and position[0] == 0:
                    cards[0].ship.update(name='未识别舰船', level=0, review=True)
                    cards[0].level_reliable = False
                if later_conflict and position[0] == 681:
                    cards[0].ship['level'] = 87
                return cards
            # 同一实际卡位在底部重叠时必须有相同身份，不能让伪名字冲突被同名合并掩盖。
            return [Card(93 + col * 165, y, col,
                         ship(f'拉菲{round((y - 76 + position[0]) / 227) % 3}-{col}', level=100), 6, True)
                    for y in (76, 303, 530) for col in range(
                        2 if partial_last and position[0] == bottom_offset and y == 530 else 7)]
        with tempfile.TemporaryDirectory() as temp, patch('module.retire.dock_scan.logger.log_file', str(Path(temp) / 'testpilot.txt')), \
                patch('module.retire.dock_scan.Timer', ImmediateTimer), patch('module.retire.dock_scan.DOCK_SCROLL', scrollbar), \
                patch('module.retire.dock_scan.recognize_cards', side_effect=recognize):
            result = scanner._scan_pages(Mock(), Mock())
            scanner._test_saved_frames = {str(path): np.array(Image.open(path)) for path in Path(temp).rglob('*.png')}
        return scanner, captured, result

    def test_local_level_failure_recovers_early_stop_on_later_clean_page(self):
        scanner, captured, result = self.scan_frames(
            [0] * 6 + [227, 227, 454, 454, 681, 681, 908, 908], bottom_offset=908, damaged=True)
        self.assertEqual(captured, [0, 0, 0, 681])
        self.assertTrue(scanner._policy.sort_valid)
        self.assertEqual(scanner._scan_metadata, dict(reached_bottom=False, physical_count=42))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '未识别舰船')
        self.assertEqual(result[0]['level'], 0)
        self.assertTrue(result[0]['review'])

    def test_later_page_sort_conflict_still_gets_review_after_local_level_failure(self):
        scanner, captured, result = self.scan_frames(
            [0] * 6 + [227, 227, 454, 454] + [681] * 6 + [908, 908],
            bottom_offset=908, damaged=True, later_conflict=True)
        self.assertEqual(captured, [0, 0, 0, 681, 681, 681, 908])
        self.assertTrue(scanner._policy.sort_valid)
        self.assertEqual(scanner._scan_metadata, dict(reached_bottom=False, physical_count=49))
        reviewed = [row for row in scanner._scan_slots if row['review']]
        self.assertEqual(len(reviewed), 3)
        self.assertEqual([row['level'] for row in reviewed], [0, 87, 88])

    def test_cross_page_sort_review_references_the_frame_containing_each_card(self):
        scanner, captured, result = self.scan_frames(
            [0, 0, 227, 227, 454, 454] + [681] * 6 + [908, 908, 1135, 1135, 1362, 1362],
            bottom_offset=1362, cross_conflict=True)
        self.assertEqual(captured, [0, 681, 681, 681, 1362])
        reviewed = [row for row in result if row['review']]
        self.assertEqual([row['name'] for row in reviewed], ['舰船2-6', '舰船3-0'])
        for row, offset in zip(reviewed, [0, 681]):
            path = row['source'].split('；原帧：')[1].split('；')[0]
            np.testing.assert_array_equal(scanner._test_saved_frames[path], self.scroll_frames([offset])[0])

    def test_scan_moves_three_rows_and_waits_for_motion_to_settle(self):
        scanner, captured, result = self.scan_frames([0, 0, 100, 227, 227, 454, 454, 681, 681], bottom_offset=681)
        self.assertEqual(captured, [0, 681])
        self.assertEqual(len(scanner._scan_slots), 42)
        self.assertEqual(len(highest_ships(result)), 21)
        self.assertEqual(scanner._scan_metadata, dict(reached_bottom=True, physical_count=42))
        self.assertEqual(scanner.device.drag.call_count, 3)
        self.assertTrue(all(call.kwargs['hold_duration'] == .4 for call in scanner.device.drag.call_args_list))
        scanner.device.swipe.assert_not_called()

    def test_scan_corrects_overshoot_before_reading_and_allows_partial_last_page(self):
        scanner, captured, result = self.scan_frames(
            [0, 0, 240, 240, 467, 467, 690, 690, 681, 681, 908, 908], bottom_offset=908, partial_last=True)
        self.assertEqual(captured, [0, 681, 908])
        self.assertEqual(len(scanner._scan_slots), 44)
        self.assertEqual(len(highest_ships(result)), 21)
        self.assertEqual(scanner._scan_metadata, dict(reached_bottom=True, physical_count=44))
        correction = scanner.device.drag.call_args_list[3]
        self.assertGreater(correction.args[1][1], correction.args[0][1])

    def test_adb_fallback_is_slow_and_never_falls_back_to_clicking_a_ship(self):
        from module.retire.dock_scan import DockScan
        from module.exception import MindCalculatorScanError
        from types import SimpleNamespace
        scanner = DockScan.__new__(DockScan)
        scanner.config = SimpleNamespace(Emulator_ControlMethod='ADB')
        scanner.device = Mock()
        scanner._drag_rows(227)
        scanner.device.drag.assert_not_called()
        self.assertEqual(scanner.device.swipe.call_args.kwargs['duration'], .6)
        with self.assertRaises(MindCalculatorScanError):
            scanner._drag_rows(4)
        self.assertEqual(scanner.device.swipe.call_count, 1)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.configs = ConfigService(fixture(self.temp.name))
        self.service = MindCalculatorService(self.configs)

    def save_ledger(self, instance, revision, rows):
        """显式重建测试夹具；生产修改按稳定副本 ID 局部提交。"""
        database = FleetDatabase(self.configs.path(instance))
        previous = dock_data.read_snapshot(database.load())['ships']
        changes = [dict(id=row['id'], delete=True) for row in previous]
        for value in rows:
            row = {key: value[key] for key in ('name', 'level', 'rarity', 'base_rarity', 'review', 'source') if key in value}
            info = mind_calculator.find_ship(row['name'])
            row['group_type'] = info['group_type'] if info else None
            changes.append(row)
        DockService(self.configs).patch(instance, revision, changes)
        return DockService(self.configs).report(instance)


    def test_import_original_excel_header_at_row_two(self):
        book = Workbook()
        sheet = book.active
        sheet.title = '舰船明细'
        sheet.append(['搜索船名'])
        sheet.append(['序号', '船名', '舰种', '等级', '稀有度', '状态'])
        sheet.append([1, '独角兽.改', '航母', 115, '精锐', ''])
        output = io.BytesIO()
        book.save(output)
        rows = import_ships('原工具.xlsx', encoded(output.getvalue()))
        self.assertEqual((rows[0]['name'], rows[0]['level']), ('独角兽.改', 115))
        sheet['F3'] = '存疑'
        sheet['M2'], sheet['M3'] = '排除船名', '小企业'
        output = io.BytesIO()
        book.save(output)
        rows = import_ships('原工具.xlsx', encoded(output.getvalue()))
        # Historical status and excluded-name columns are not current import fields.
        self.assertFalse(rows[0]['review'])
        self.assertEqual(len(rows), 1)
        sheet['F2'], sheet['F3'] = '需核对', '是'
        output = io.BytesIO()
        book.save(output)
        self.assertTrue(import_ships('原工具.xlsx', encoded(output.getvalue()))[0]['review'])

    def test_reject_invalid_import_values(self):
        with self.assertRaises(ApiError):
            import_ships('bad.json', encoded(json.dumps([{'name': '错误', 'level': 126}]).encode()))
        with self.assertRaises(ApiError):
            import_ships('bad.csv', encoded('船名,等级\n测试,100.1'.encode()))
        with self.assertRaises(ApiError):
            import_ships('bad.json', encoded(json.dumps([{'name': '拉菲', 'level': 100, 'lavel': 1}]).encode()))

    def test_exported_json_round_trips_into_staged_import(self):
        """软件导出的舰船 JSON 原样导回：事实字段保留，未变更数据不产生待确认差异。"""
        dock = DockService(self.configs)
        self.save_ledger('testpilot', dock.report('testpilot')['revision'], [ship('拉菲', level=110)])
        report = dock.report('testpilot')
        dock.patch('testpilot', report['revision'],
                   [dict(id=report['ships'][0]['id'], form='retrofit', full_star=True, extra_exp=520)])
        report = dock.report('testpilot')
        content = encoded(json.dumps(dict(version=1, exported_at='2026-11-08T00:00:00Z', **report)).encode())
        rows = import_ships('alas-ships.json', content)
        self.assertEqual([row['name'] for row in rows], ['拉菲'])
        self.assertTrue(all('id' not in row for row in rows))
        row = rows[0]
        self.assertEqual((row['group_type'], row['full_star'], row['form'], row['extra_exp']),
                         (10117, True, 'retrofit', 520))
        staged = self.service.import_file('testpilot', 'alas-ships.json', content)
        result = dock.stage_import('testpilot', report['revision'], staged['ships'])
        self.assertEqual(result['pending_changes'], [])

    def test_completed_scan_stages_and_rejects_concurrent_canonical_edits(self):
        from module.config.config import AzurLaneConfig
        from module.exception import MindCalculatorScanError
        from module.retire.assets import DOCK_SEARCH_CLOSED
        from module.retire.dock_scan import DockScan
        for changed in (False, True):
            with self.subTest(changed=changed):
                path = str(self.configs.path('testpilot'))
                database = FleetDatabase(self.configs.path('testpilot'))
                pending = database.load(include_pending=True)
                if pending['pending_revision']:
                    database.review([dict(id=row['id'], accept=False) for row in pending['pending_changes']],
                                    pending['snapshot']['revision'], pending['pending_revision'])
                self.save_ledger('testpilot', DockService(self.configs).report('testpilot')['revision'], [ship('拉菲')])
                database = FleetDatabase(self.configs.path('testpilot'))
                original = database.load()['snapshot']
                card_id = original['ships'][0]['id']
                with patch('module.config.utils.filepath_config', return_value=path), \
                        patch('module.config.config.filepath_config', return_value=path), \
                        patch('module.config.config_updater.filepath_config', return_value=path), \
                        patch('module.retire.dock_scan.DOCK_SCROLL') as scrollbar, \
                        patch('module.retire.dock_scan.server.server', 'cn'), \
                        patch('module.retire.enhancement.OCR_DOCK_AMOUNT.ocr', return_value=(1, 0, 1)), \
                        patch('module.ocr.al_ocr.AlOcr'):
                    config = AzurLaneConfig.__new__(AzurLaneConfig)
                    config.config_name = 'testpilot'
                    config.data = config.read_file('testpilot')
                    config._loaded_data = copy.deepcopy(config.data)
                    config.modified = {}
                    config.Dock_MinLevel, config.Dock_MaxLevel = 1, 125
                    scanner = DockScan.__new__(DockScan)
                    scanner.config, scanner.device = config, Mock()
                    scanner.ui_ensure = scanner.dock_reset = scanner.dock_sort_method_dsc_set = Mock()
                    scanner._close_search = Mock()
                    scanner.appear = lambda button: button is DOCK_SEARCH_CLOSED
                    scanner._prune_scan_evidence = Mock()
                    scrollbar.appear.return_value = scrollbar.at_top.return_value = True
                    def collect(*args):
                        if changed:
                            database.patch_cards([dict(id=card_id, review=True)], original['revision'])
                        scanner._scan_slots = [dict(ship('拉菲', level=110), group_type=10117)]
                        scanner._scan_metadata = dict(reached_bottom=True, physical_count=1)
                    scanner._scan_pages = Mock(side_effect=collect)
                    if changed:
                        with self.assertRaises(MindCalculatorScanError) as error:
                            scanner.run()
                        self.assertIsInstance(error.exception.__cause__, FleetDatabaseConflict)
                        scanner._prune_scan_evidence.assert_not_called()
                    else:
                        scanner.run()
                        scanner._prune_scan_evidence.assert_called_once_with()
                    state = database.load(include_pending=True)
                    self.assertEqual(state['snapshot']['ships'][0]['level'], 100)
                    self.assertEqual(state['snapshot']['ships'][0]['review'], changed)
                    if not changed:
                        proposal = next(row for row in state['pending_changes'] if row['kind'] == 'ship')
                        self.assertEqual(proposal['after']['level'], 110)


if __name__ == '__main__':
    unittest.main()
