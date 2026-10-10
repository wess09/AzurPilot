"""仓库统计：真实截图、虚拟滚动设备和临时数据库，绝不操作真实账号。"""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.exception import StorageStatisticsError
from module.statistics.storage_snapshot import get_storage_timeline, latest_snapshot, save_snapshot
from module.storage.statistics_recognition import (StorageCard, StorageCatalog, StorageRecognitionError,
    StorageTraversal, detect_rows, recognize_rows, same_card, same_row)

FIXTURES = Path(__file__).parent / 'fixtures/storage_statistics'


class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = StorageCatalog()
        cls.images = [load_image(str(FIXTURES / f'page_{n}.png')) for n in range(1, 5)]
        cls.cases = json.loads((FIXTURES / 'expected.json').read_text(encoding='utf-8'))

    def test_all_four_pages_have_only_the_25_marked_items(self):
        pages = [recognize_rows(image, self.catalog) for image in self.images]
        expected = {(case['page'], case['row'], case['column']): case for case in self.cases}
        self.assertEqual(len(expected), 25)
        for page, rows in enumerate(pages, 1):
            for row, cards in enumerate(rows):
                for column, card in enumerate(cards):
                    case = expected.get((page, row, column))
                    with self.subTest(page=page, row=row, column=column):
                        self.assertEqual(card.identifier, case['id'] if case else None)
                        self.assertEqual(card.amount, case['amount'] if case else None)

    def test_items_can_move_between_columns_and_rows(self):
        image = self.images[3].copy()
        rows = detect_rows(image)
        a, b = rows[0][0].area, rows[1][6].area
        x1, y1, x2, y2 = a
        u1, v1, u2, v2 = b
        first, second = image[y1:y2, x1:x2].copy(), image[v1:v2, u1:u2].copy()
        image[y1:y2, x1:x2], image[v1:v2, u1:u2] = second, first
        result = recognize_rows(image, self.catalog)
        self.assertIsNone(result[0][0].identifier)
        self.assertEqual((result[1][6].identifier, result[1][6].amount), ('GearDesignPlanGunT4', 699))

    def test_directed_parts_are_not_a_general_part_variant(self):
        # 定向部件是未使用的选择道具，不能折算或合并成通用强化部件。
        icon = load_image(str(FIXTURES / 'live_directed_parts_t4.png'))
        self.assertIsNone(self.catalog.identify(icon))
        general = recognize_rows(self.images[2], self.catalog)[0][5]
        directed = StorageCard((0, 0, 128, 128), icon)
        items = {item['id']: item['amount'] for item in self.catalog.snapshot_items([[general, directed]])}
        self.assertEqual(items['PlateGeneralT4'], 881)

    def test_live_clipped_viewport_keeps_only_complete_rows_and_reads_new_glyphs(self):
        image = load_image(str(FIXTURES / 'partial_rows.png'))
        rows = recognize_rows(image, self.catalog)
        self.assertEqual(len(rows), 2)
        self.assertEqual([(card.identifier, card.amount) for row in rows for card in row if card.identifier],
                         [('CognitiveChips', 32791), ('CognitiveChipsII', 1204)])
        self.assertTrue(all(65 <= card.area[1] and card.area[3] < 637 for row in rows for card in row))

    def test_live_scroll_and_rainbow_animation_preserve_unique_overlap(self):
        before, after = [recognize_rows(load_image(str(FIXTURES / name)), self.catalog)
                         for name in ['live_scroll_start.png', 'live_scroll_overlap.png']]
        self.assertTrue(same_row(before[-1], after[0]))
        self.assertFalse(same_row(before[1], after[0]))
        scan = StorageTraversal()
        scan.append(before)
        scan.append(after)
        self.assertEqual(len(scan.rows), 5)
        self.assertEqual(scan.rows[3][1].amount, 153)

    def test_live_glowing_item_remains_the_same_card(self):
        first, second = [StorageCard((0, 0, 128, 128), load_image(str(FIXTURES / f'live_glow_{n}.png')))
                         for n in [1, 2]]
        self.assertTrue(same_card(first, second))
        other = detect_rows(self.images[0])[0][0]
        self.assertFalse(same_card(first, other))

    def test_unknown_blueprints_match_across_subpixel_scroll_but_remain_distinct(self):
        samples = load_image(str(FIXTURES / 'live_subpixel_rows.png'))
        rows = [[StorageCard((column * 128, row * 128, (column + 1) * 128, (row + 1) * 128),
                             samples[row * 128:(row + 1) * 128, column * 128:(column + 1) * 128])
                 for column in range(7)] for row in range(2)]
        self.assertTrue(same_row(*rows))
        self.assertFalse(same_row(rows[0], list(reversed(rows[1]))))
        for first, a in enumerate(rows[0]):
            for second, b in enumerate(rows[1]):
                with self.subTest(first=first, second=second):
                    self.assertEqual(same_card(a, b), first == second)

    def test_live_antialiased_amount_and_erased_digit(self):
        icon = load_image(str(FIXTURES / 'live_amount_46.png'))
        self.assertEqual(self.catalog.read_amount(icon), 46)
        icon[103:115, 96:108] = (32, 36, 50)
        with self.assertRaises(StorageRecognitionError):
            self.catalog.read_amount(icon)

    def test_live_five_digit_quantity_and_additional_glyph_phases(self):
        for amount in [10598, 9657]:
            with self.subTest(amount=amount):
                icon = load_image(str(FIXTURES / f'live_amount_{amount}.png'))
                self.assertEqual(self.catalog.read_amount(icon), amount)

    def test_native_scrolled_digit_samples_keep_every_digit(self):
        samples = load_image(str(FIXTURES / 'live_digits.png'))
        cases = json.loads((FIXTURES / 'live_digits.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(row=case['row'], item=case['id']):
                icon = np.zeros((128, 128, 3), dtype=np.uint8)
                start = case['row'] * 27
                icon[99:126, 25:127] = samples[start:start + 27]
                self.assertEqual(self.catalog.read_amount(icon), case['amount'])

    def test_vertical_scroll_offset_and_clipped_rows(self):
        image = self.images[3].copy()
        image[65:637] = (32, 36, 50)
        image[88:637] = self.images[3][65:614]
        rows = recognize_rows(image, self.catalog)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0].amount, 699)
        self.assertGreater(rows[0][0].area[1], 90)

    def test_unreadable_amount_never_becomes_zero(self):
        icon = detect_rows(self.images[0])[0][1].image.copy()
        icon[99:126, 25:127] = (255, 255, 255)
        with self.assertRaises(StorageRecognitionError):
            self.catalog.read_amount(icon)

    def test_partially_erased_leading_digit_is_not_silently_dropped(self):
        icon = detect_rows(self.images[0])[0][1].image.copy()
        icon[104:118, 87:95] = (32, 36, 50)
        with self.assertRaises(StorageRecognitionError):
            self.catalog.read_amount(icon)

    def test_untrained_quantities_and_repeated_digits_from_other_items(self):
        rows = detect_rows(self.images[1])
        for row, column, amount in [(0, 0, 215), (0, 2, 143), (0, 5, 142),
                                    (2, 0, 77), (2, 1, 43), (2, 5, 854)]:
            with self.subTest(amount=amount):
                self.assertEqual(self.catalog.read_amount(rows[row][column].image), amount)

    def test_other_items_with_connected_icon_debris_are_rejected(self):
        rows = detect_rows(self.images[1])
        for column in [2, 6]:
            with self.subTest(column=column), self.assertRaises(StorageRecognitionError):
                self.catalog.read_amount(rows[1][column].image)

    def test_128_pixel_contour_at_bottom_is_still_a_clipped_row(self):
        device = InventoryDevice()
        device.position = .971
        self.assertEqual(len(detect_rows(device.screenshot())), 2)

    def test_overlap_is_deduplicated_and_missing_overlap_rejected(self):
        rows = [row for image in self.images[:2] for row in recognize_rows(image, self.catalog)]
        scan = StorageTraversal()
        scan.append(rows[:3])
        scan.append(rows[2:5])
        self.assertEqual(len(scan.rows), 5)
        quantities = {item['id']: item['amount'] for item in self.catalog.snapshot_items(scan.rows)}
        self.assertEqual(quantities['PrototypeGearPartsT5'], 153)
        with self.assertRaises(StorageRecognitionError):
            scan.append(rows[:2])

    def test_ambiguous_repeating_rows_are_rejected(self):
        row = recognize_rows(self.images[0], self.catalog)[0]
        scan = StorageTraversal()
        scan.append([row, row])
        with self.assertRaises(StorageRecognitionError):
            scan.append([row, row, row])

    def test_final_overlapping_page_is_not_counted_twice(self):
        rows = recognize_rows(self.images[0], self.catalog)
        scan = StorageTraversal()
        scan.append(rows)
        scan.append(rows[-2:], at_bottom=True)
        self.assertEqual(len(scan.rows), 3)
        self.assertEqual(scan.pages, 2)
        with self.assertRaises(StorageRecognitionError):
            scan.append(rows[-2:])

    def test_last_partial_row_has_consecutive_empty_slots(self):
        image = self.images[3].copy()
        image[422:604, 296:1235] = (32, 36, 50)
        rows = detect_rows(image)
        self.assertEqual(len(rows), 3)
        self.assertEqual([card.present for card in rows[-1]], [True, False, False, False, False, False, False])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.temp) / 'config/azurpilot.db'
        self.items = [dict(id='chips', name='心智单元', group='材料', amount=13393),
                      dict(id='absent', name='未发现物品', group='材料', amount=None)]

    def save(self, instance='alpha', items=None):
        return save_snapshot(instance, 'cn', items or self.items, started_at=datetime.now().isoformat(),
                             pages=6, catalog_version='test', database=self.path)

    def test_read_before_run_does_not_create_any_file(self):
        self.assertIsNone(latest_snapshot('alpha', database=self.path))
        self.assertEqual(get_storage_timeline('alpha', database=self.path), [])
        self.assertFalse(self.path.parent.exists())

    def test_latest_snapshot_isolated_by_instance_and_read_only(self):
        self.save()
        self.save('beta', [dict(self.items[0], amount=4)])
        before = self.path.read_bytes()
        result = latest_snapshot('alpha', database=self.path)
        self.assertEqual(result['items'][0]['amount'], 13393)
        self.assertIsNone(result['items'][1]['amount'])
        self.assertEqual(before, self.path.read_bytes())
        self.assertIsNone(latest_snapshot('gamma', database=self.path))

    def test_history_filters_window_instance_and_limit_without_filling_unknowns(self):
        identifiers = [self.save(), self.save(items=[dict(self.items[0], amount=14), self.items[1]]), self.save()]
        self.save('beta')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            for identifier, timestamp in zip(identifiers, ['2026-09-01 00:00:00', '2026-10-01 00:00:00', '2026-10-03 00:00:00']):
                connection.execute('UPDATE storage_scans SET finished_at=? WHERE id=?', (timestamp, identifier))
        before = self.path.read_bytes()
        rows = get_storage_timeline('alpha', since='2026-10-01 00:00:00', database=self.path)
        self.assertEqual([row['chips'] for row in rows], [14, 13393])
        self.assertTrue(all(row['absent'] is None for row in rows))
        bounded = get_storage_timeline('alpha', through_id=identifiers[1], database=self.path)
        self.assertEqual([row['chips'] for row in bounded], [13393, 14])
        self.assertEqual(get_storage_timeline('alpha', limit=1, database=self.path)[0]['chips'], 13393)
        self.assertEqual(get_storage_timeline('gamma', database=self.path), [])
        self.assertEqual(before, self.path.read_bytes())

    def test_history_until_drops_scans_after_window(self):
        """窗口上界同样下推到 SQL：看历史月份时不得混入其后的扫描。"""
        identifiers = [self.save(), self.save(items=[dict(self.items[0], amount=14), self.items[1]]), self.save()]
        with closing(sqlite3.connect(self.path)) as connection, connection:
            for identifier, timestamp in zip(identifiers, ['2026-09-01 00:00:00', '2026-10-01 00:00:00', '2026-10-03 00:00:00']):
                connection.execute('UPDATE storage_scans SET finished_at=? WHERE id=?', (timestamp, identifier))

        rows = get_storage_timeline('alpha', since='2026-09-01 00:00:00', until='2026-10-01 00:00:00',
                                    database=self.path)

        self.assertEqual([row['chips'] for row in rows], [13393, 14])

    def test_storage_trends_only_use_completed_known_counts_and_preserve_icons(self):
        from module.api.statistics_service import compact_axis, report
        catalog = StorageCatalog()
        items = [dict(id=item['id'], name=item['name'], group=item['group'], amount=1) for item in catalog.items]
        self.save(items=items)
        items[6]['amount'] = 32791
        items[7]['amount'] = None
        self.save(items=items)
        before = self.path.read_bytes()
        configs = SimpleNamespace(directory=self.path.parent, path=Mock(return_value=self.path.parent / 'alpha.json'))
        result = report(configs, 'alpha', 'storage', None, 7, 'month')
        chips = next(item for item in result['series'] if item['key'] == 'CognitiveChips')
        absent = next(item for item in result['series'] if item['key'] == 'CognitiveChipsII')
        self.assertEqual([point['v'] for point in chips['points']], [1, 32791])
        self.assertEqual([point['v'] for point in absent['points']], [1])
        self.assertTrue(chips['icon'].startswith('storage:'))
        compressed = compact_axis([chips])
        self.assertEqual(compressed['series'][0]['icon'], chips['icon'])
        self.assertEqual(before, self.path.read_bytes())

    def test_storage_report_month_window_excludes_scans_after_the_month(self):
        """仓库趋势按选定月份取窗口：月内的扫描全在，月外的不带。"""
        from module.api.statistics_service import report
        catalog = StorageCatalog()
        base = [dict(id=item['id'], name=item['name'], group=item['group'], amount=1) for item in catalog.items]
        first = self.save(items=base)
        second = self.save(items=[dict(base[0], amount=9)] + base[1:])
        third = self.save(items=[dict(base[0], amount=99)] + base[1:])
        with closing(sqlite3.connect(self.path)) as connection, connection:
            for identifier, timestamp in ((first, '2026-01-05 00:00:00'),
                                          (second, '2026-01-20 00:00:00'),
                                          (third, '2026-03-02 00:00:00')):
                connection.execute('UPDATE storage_scans SET finished_at=? WHERE id=?', (timestamp, identifier))

        configs = SimpleNamespace(directory=self.path.parent, path=Mock(return_value=self.path.parent / 'alpha.json'))
        result = report(configs, 'alpha', 'storage', '2026-01', 7, 'month')
        chips = next(item for item in result['series'] if item['key'] == base[0]['id'])

        self.assertEqual([point['v'] for point in chips['points']], [1.0, 9.0])

    def test_invalid_counts_and_partial_transaction_keep_old_snapshot(self):
        scan_id = self.save()
        for value in [0, -1, True, 1.5]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.save(items=[dict(self.items[0], amount=value)])
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TRIGGER abort_item BEFORE INSERT ON storage_items BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save()
        self.assertEqual(latest_snapshot('alpha', database=self.path)['id'], scan_id)

    def test_report_only_reads_saved_counts(self):
        from module.api.statistics_service import report
        configs = SimpleNamespace(directory=self.path.parent, path=Mock(return_value=self.path.parent / 'alpha.json'))
        first = report(configs, 'alpha', 'storage', None, 7, 'month')
        self.assertTrue(all(row[3] is None for row in first['tables'][0]['rows']))
        self.assertFalse(self.path.exists())
        self.save()
        before = self.path.read_bytes()
        result = report(configs, 'alpha', 'storage', None, 7, 'month')
        self.assertEqual(result['tables'][0]['rows'][0][3], 13393)
        self.assertEqual(before, self.path.read_bytes())


class FrameTimer:
    """测试时用访问次数代替时间，保持真实任务的状态转移。"""
    def __init__(self, seconds, count=0):
        self.seconds = seconds
        self.count = 0
    def start(self):
        return self
    def reset(self):
        self.count = 0
        return self
    def clear(self):
        return self.reset()
    def reached(self):
        self.count += 1
        return self.count > 100 if self.seconds >= 20 else True


class InventoryDevice:
    """按真实滚动条几何生成完整材料列表截图，记录所有操作。"""
    def __init__(self):
        images = [load_image(str(FIXTURES / f'page_{n}.png')) for n in range(1, 5)]
        strips = []
        for image in images:
            for row in detect_rows(image):
                y = row[0].area[1] - 6
                strips.append(image[y:y + 178, 130:1235])
        self.content = np.concatenate(strips)
        self.base = images[0]
        self.position = .37
        self.length = round(572 / len(self.content) * 496)
        self.swipes = []
        self.click_record_clear = Mock()
        self.screenshot()

    def screenshot(self):
        image = self.base.copy()
        offset = round((len(self.content) - 572) * self.position)
        image[65:637, 130:1235] = self.content[offset:offset + 572]
        image[92:588, 1256:1265] = (25, 26, 38)
        y = 92 + round(self.position * (496 - self.length))
        image[y:y + self.length, 1256:1265] = (247, 211, 66)
        self.image = image
        return image

    def swipe(self, start, end, **kwargs):
        self.swipes.append((start, end))
        if start[0] < 1235:
            self.position = min(1., max(0., self.position + (start[1] - end[1]) / (len(self.content) - 572)))
        else:
            self.position = min(1., max(0., (end[1] - 92 - self.length / 2) / (496 - self.length)))

    def drag(self, start, end, **kwargs):
        self.swipe(start, end, **kwargs)


class ObstructedInventoryDevice(InventoryDevice):
    """特定滚动位置的第一格被遮挡，上下微调后才出现完整边框。"""
    def screenshot(self):
        image = super().screenshot()
        if .10 < self.position < .19:
            card = detect_rows(image)[0][0]
            x1, y1, x2, _ = card.area
            image[y1 - 3:y1 + 12, x1 - 4:x2 + 4] = (32, 36, 50)
        return image


class ChangingScrollbarDevice(InventoryDevice):
    """模拟日志中的滑块长度变化，并拒绝不足 12px 的滑块手势。"""
    def swipe(self, start, end, **kwargs):
        if start[0] >= 1235 and abs(start[1] - end[1]) < 12:
            raise AssertionError('短手势会停在原处')
        previous = self.position
        super().swipe(start, end, **kwargs)
        if previous == 0. and 0. < self.position < .3 and not getattr(self, 'changed', False):
            self.length += 12
            self.changed = True


class EndpointObstructedDevice(InventoryDevice):
    """首末端首次出现遮挡，只有移开再回到端点才能可靠读取。"""
    def __init__(self):
        self.obstruct_top = self.obstruct_bottom = True
        super().__init__()

    def screenshot(self):
        image = super().screenshot()
        if self.position <= .001 and self.obstruct_top or self.position >= .999 and self.obstruct_bottom:
            rows = detect_rows(image)
            card = rows[0 if self.position <= .001 else -1][0]
            x1, y1, x2, _ = card.area
            image[y1 - 3:y1 + 12, x1 - 4:x2 + 4] = (32, 36, 50)
        return image

    def swipe(self, start, end, **kwargs):
        if start[0] < 1235:
            if self.position <= .001:
                self.obstruct_top = False
            if self.position >= .999:
                self.obstruct_bottom = False
        super().swipe(start, end, **kwargs)


class TaskTests(unittest.TestCase):
    def setUp(self):
        from module.storage.statistics import StorageStatistics
        self.module = __import__('module.storage.statistics', fromlist=['StorageStatistics'])
        self.task = StorageStatistics.__new__(StorageStatistics)
        self.task.config = SimpleNamespace(config_name='test', task_delay=Mock(), Emulator_ControlMethod='MaaTouch',
                                           StorageStatistics_RunIntervalDays=7)
        self.task.device = InventoryDevice()
        self.task.ui_goto_storage = Mock()
        self.task._storage_enter_material = Mock()
        self.task._storage_in_material = Mock(return_value=True)
        self.task.handle_info_bar = Mock(return_value=False)
        def frames(**kwargs):
            for _ in range(250):
                yield self.task.device.screenshot()
        self.task.loop = frames
        self.enterContext(patch.object(self.module, 'Timer', FrameTimer))
        self.enterContext(patch.object(self.module.logger, 'attr'))
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.temp) / 'azurpilot.db'
        self.enterContext(patch.object(self.module, 'save_snapshot',
            side_effect=lambda *args, **kwargs: save_snapshot(*args, **kwargs, database=self.path)))

    def test_task_navigates_and_scans_once_before_atomic_commit(self):
        with patch.object(self.task, '_scan_pass', wraps=self.task._scan_pass) as scanner, \
             patch.object(self.module, 'recognize_rows', wraps=recognize_rows) as reader:
            self.task.run()
        scanner.assert_called_once()
        self.task.ui_goto_storage.assert_called_once()
        self.task._storage_enter_material.assert_called_once()
        snapshot = latest_snapshot('test', database=self.path)
        expected = json.loads((FIXTURES / 'expected.json').read_text(encoding='utf-8'))
        self.assertEqual({item['id']: item['amount'] for item in snapshot['items']},
                         {item['id']: item['amount'] for item in expected})
        self.assertEqual(snapshot['pages'], 4)
        self.assertEqual(reader.call_count, snapshot['pages'])
        self.assertGreater(len(self.task.device.swipes), 4)
        self.assertEqual(self.task.device.click_record_clear.call_count, snapshot['pages'])
        self.task.config.task_delay.assert_called_once_with(minute=10080)

    def test_failed_next_page_stops_immediately_without_partial_commit_or_second_pass(self):
        def read(*args, **kwargs):
            if reader.call_count == 2:
                raise StorageRecognitionError('数量不确定')
            return recognize_rows(*args, **kwargs)
        with patch.object(self.task, '_scan_pass', wraps=self.task._scan_pass) as scanner, \
             patch.object(self.module, 'recognize_rows', side_effect=read) as reader:
            with self.assertRaisesRegex(StorageStatisticsError, '数量不确定'):
                self.task.run()
        scanner.assert_called_once()
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(self.task.device.click_record_clear.call_count, 1)
        self.assertFalse(self.path.exists())
        self.task.config.task_delay.assert_called_once_with(success=False)

    def test_same_page_movement_stops_without_repeating_confirmed_data(self):
        def frames(**kwargs):
            for _ in range(100):
                if reader.call_count:
                    self.task.device.position += .02
                yield self.task.device.screenshot()
        self.task.loop = frames
        with patch.object(self.module, 'recognize_rows', wraps=recognize_rows) as reader, \
             patch.object(self.module, 'verify_targets') as verifier:
            with self.assertRaisesRegex(StorageStatisticsError, '同页核对期间滚动条位置变化'):
                self.task.run()
        reader.assert_called_once()
        verifier.assert_not_called()
        self.assertFalse(self.path.exists())
        self.assertEqual(len(self.task.device.swipes), 3)
        self.task.device.click_record_clear.assert_not_called()

    def test_adb_scan_avoids_drag_fallback_clicks_and_preserves_all_items(self):
        self.task.config.Emulator_ControlMethod = 'ADB'
        self.task.device.drag = Mock(side_effect=AssertionError('不支持拖拽的后端不能触发点击回退'))
        self.task.run()
        self.task.device.drag.assert_not_called()
        snapshot = latest_snapshot('test', database=self.path)
        expected = json.loads((FIXTURES / 'expected.json').read_text(encoding='utf-8'))
        self.assertEqual({item['id']: item['amount'] for item in snapshot['items']},
                         {item['id']: item['amount'] for item in expected})

    def test_pages_use_only_the_scrollbar_and_preserve_all_items(self):
        self.task.device = ObstructedInventoryDevice()
        self.task.run()
        snapshot = latest_snapshot('test', database=self.path)
        expected = json.loads((FIXTURES / 'expected.json').read_text(encoding='utf-8'))
        self.assertEqual({item['id']: item['amount'] for item in snapshot['items']},
                         {item['id']: item['amount'] for item in expected})
        self.assertTrue(all(start[0] == end[0] == 1260 for start, end in self.task.device.swipes))

    def test_persistent_recognition_failure_keeps_old_snapshot_without_nudges(self):
        save_snapshot('test', 'cn', [dict(id='old', name='旧记录', group='材料', amount=99)],
                      started_at='2026-10-01', pages=2, catalog_version='old', database=self.path)
        before = self.path.read_bytes()
        with patch.object(self.module, 'recognize_rows', side_effect=StorageRecognitionError('残缺数量')) as reader:
            with self.assertRaisesRegex(StorageStatisticsError, '残缺数量'):
                self.task.run()
        reader.assert_called_once()
        nudges = [start for start, _ in self.task.device.swipes if start[0] < 1235]
        self.assertEqual(len(nudges), 0)
        self.task.device.click_record_clear.assert_not_called()
        self.assertEqual(before, self.path.read_bytes())

    def test_changing_scrollbar_rejects_invalid_calibration(self):
        self.task.device = ChangingScrollbarDevice()
        self.task._storage_in_material = Mock(side_effect=[False] + [True] * 249)
        with self.assertRaisesRegex(StorageRecognitionError, '标定期间滚动条长度变化'):
            self.task._scan_pass(StorageCatalog())
        self.assertTrue(self.task.device.changed)

    def test_obstructed_endpoint_fails_without_skipping_first_row(self):
        self.task.device = EndpointObstructedDevice()
        with self.assertRaisesRegex(StorageRecognitionError, '材料行被遮挡或边框不完整'):
            self.task._scan_pass(StorageCatalog())
        self.assertTrue(all(start[0] == 1260 for start, _ in self.task.device.swipes))
        self.assertEqual(self.task.device.position, 0.)

    def test_single_page_with_full_scroll_handle_is_complete(self):
        device = self.task.device
        padding = np.full((38, device.content.shape[1], 3), (32, 36, 50), dtype=np.uint8)
        device.content = np.concatenate([device.content[:534], padding])
        device.length = 496
        self.task.run()
        snapshot = latest_snapshot('test', database=self.path)
        quantities = {item['id']: item['amount'] for item in snapshot['items']}
        self.assertEqual(quantities['PrototypeGearPartsT5'], 153)
        self.assertIsNone(quantities['CognitiveChips'])
        self.assertEqual(snapshot['pages'], 1)
        self.assertEqual(device.swipes, [])


class ApiIntegrationTests(unittest.TestCase):
    def test_storage_report_over_websocket_and_nested_static_icon(self):
        import shutil
        from starlette.testclient import TestClient
        from module.api.app import create_app
        from module.api.config_service import ROOT
        from tests.test_api import fixture
        temp = self.enterContext(tempfile.TemporaryDirectory())
        root = fixture(temp)
        relative = 'assets/stats/opsi_items/PrototypeGearPartsT5.png'
        destination = root / relative
        destination.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / relative, destination)
        app = create_app(root=root, password='', manage_runtime=False, mount_mcp=False)
        client = TestClient(app)
        before = (root / 'config/testpilot.json').read_bytes()
        with client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            ws.send_json({'v': 1, 'type': 'request', 'id': 'storage', 'method': 'statistics.report',
                          'params': {'instance': 'testpilot', 'category': 'storage'}})
            response = ws.receive_json()
            self.assertTrue(response['ok'], response)
            rows = response['result']['tables'][0]['rows']
            self.assertEqual(len(rows), 25)
            self.assertTrue(all(row[3] is None and row[4] == '未扫描' for row in rows))
            self.assertFalse((root / 'config/azurpilot.db').exists())
            catalog = StorageCatalog()
            items = [dict(id=item['id'], name=item['name'], group=item['group'], amount=index + 1)
                     for index, item in enumerate(catalog.items)]
            save_snapshot('testpilot', 'cn', items, started_at='2026-10-03', pages=12,
                          catalog_version=catalog.version, database=root / 'config/azurpilot.db')
            ws.send_json({'v': 1, 'type': 'request', 'id': 'history', 'method': 'statistics.report',
                          'params': {'instance': 'testpilot', 'category': 'storage', 'days': 30}})
            response = ws.receive_json()
            self.assertTrue(response['ok'], response)
            series = response['result']['series']
            self.assertEqual(len(response['result']['axis']), 1)
            self.assertEqual(series[6]['values'], [7])
            self.assertEqual(series[7]['icon'], 'storage:storage_items/CognitiveChipsII')
        self.assertEqual(before, (root / 'config/testpilot.json').read_bytes())
        icon = client.get('/storage-items/opsi_items/PrototypeGearPartsT5.png')
        self.assertEqual(icon.status_code, 200)
        self.assertEqual(icon.content, destination.read_bytes())

    def test_manual_storage_task_uses_existing_instance_mutex(self):
        from module.api.protocol import ApiError
        from module.api.runtime_service import RuntimeService
        runtime = RuntimeService(SimpleNamespace(path=lambda _: None))
        manager = SimpleNamespace(alive=False)
        manager.start = Mock(side_effect=lambda *args, **kwargs: setattr(manager, 'alive', True))
        stop_event = object()
        with patch.object(runtime, 'manager', return_value=manager), \
             patch.object(runtime, 'overview', return_value={}), \
             patch.object(runtime, '_record_running_now'), \
             patch('module.runtime.updater.updater', SimpleNamespace(event=stop_event)):
            runtime.start('testpilot', 'StorageStatistics')
            with self.assertRaises(ApiError) as raised:
                runtime.start('testpilot', 'StorageStatistics')
        self.assertEqual(raised.exception.code, 'INSTANCE_RUNNING')
        manager.start.assert_called_once_with('StorageStatistics', ev=stop_event)


if __name__ == '__main__':
    unittest.main()
