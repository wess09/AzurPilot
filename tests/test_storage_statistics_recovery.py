"""三行扫描的虚拟时间回归：识别错误立即退出、有限等待及失败原子性。"""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.exception import StorageStatisticsError
from module.statistics.storage_snapshot import save_snapshot
from module.storage.statistics import StorageStatistics
from module.storage.statistics_recognition import StorageRecognitionError, detect_rows
from tests.test_storage_statistics import InventoryDevice


class VirtualClock:
    def __init__(self):
        self.now = 100.

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StorageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.module = __import__('module.storage.statistics', fromlist=['StorageStatistics'])
        self.clock = VirtualClock()
        self.enterContext(patch('module.base.timer.time', self.clock))
        self.enterContext(patch.object(self.module, 'logger'))
        self.task = StorageStatistics.__new__(StorageStatistics)
        self.task.config = SimpleNamespace(
            config_name='recovery_test', Emulator_ControlMethod='MaaTouch', task_delay=Mock(),
            StorageStatistics_RunIntervalDays=7)
        self.device = self.task.device = InventoryDevice()
        self.task.handle_info_bar = Mock(return_value=False)
        self.task._storage_in_material = Mock(return_value=True)
        self.task.ui_goto_storage = Mock()
        self.task._storage_enter_material = Mock()
        self.catalog = SimpleNamespace(servers=['cn'], version='test', verify=self.verify)
        self.frames = 0
        self.read_positions = []
        self.device.position = 0.
        self.top_y = detect_rows(self.device.screenshot())[0][0].area[1]

        def screenshots(**kwargs):
            for _ in range(100):
                self.clock.advance(3)
                self.frames += 1
                yield self.device.screenshot()
            raise AssertionError('扫描必须在窗口内推进或退出')

        self.task.loop = screenshots

    def read(self, image, catalog, *, rows=None, **kwargs):
        """数量用夹具替身；行定位、滑块、标定、拼接与计时均保留真实实现。"""
        self.read_positions.append(self.device.position)
        rows = detect_rows(image) if rows is None else rows
        offset = (len(self.device.content) - 572) * self.device.position
        for row in rows:
            index = round((offset + row[0].area[1] - self.top_y) / 178)
            for column, card in enumerate(row):
                card.identifier = f'item_{index}_{column}'
                card.amount = index + 1
        return rows

    def verify(self, card, reference):
        offset = (len(self.device.content) - 572) * self.device.position
        index = round((offset + card.area[1] - self.top_y) / 178)
        card.identifier = reference.identifier
        card.amount = index + 1
        if card.amount != reference.amount:
            raise StorageRecognitionError('同页数量不一致')

    def test_first_amount_error_stops_before_any_reread_or_extra_gesture(self):
        with patch.object(self.module, 'recognize_rows',
                          side_effect=StorageRecognitionError('数量字形暂时无法确认')) as reader, \
             patch.object(self.module, 'verify_targets') as verifier:
            with self.assertRaisesRegex(StorageRecognitionError, '数量字形暂时无法确认'):
                self.task._scan_pass(self.catalog)
        reader.assert_called_once()
        verifier.assert_not_called()
        self.assertEqual(len(self.device.swipes), 2)
        self.assertEqual(self.device.position, 0.)
        self.device.click_record_clear.assert_not_called()

    def test_same_page_quantity_conflict_stops_without_restarting_recognition(self):
        with patch.object(self.module, 'recognize_rows', side_effect=self.read) as reader, \
             patch.object(self.module, 'verify_targets',
                          side_effect=StorageRecognitionError('同页数量不一致')) as verifier:
            with self.assertRaisesRegex(StorageRecognitionError, '同页数量不一致'):
                self.task._scan_pass(self.catalog)
        reader.assert_called_once()
        verifier.assert_called_once()
        self.assertEqual(len(self.device.swipes), 2)
        self.device.click_record_clear.assert_not_called()

    def test_recognition_time_counts_toward_fresh_frame_verification_interval(self):
        completed = []
        verified = []
        original_verify = self.module.verify_targets

        def screenshots(**kwargs):
            for _ in range(100):
                self.clock.advance(.2)
                yield self.device.screenshot()
            raise AssertionError('三行扫描未按顺序完成')

        def read(*args, **kwargs):
            result = self.read(*args, **kwargs)
            self.clock.advance(2)
            completed.append(self.clock.now)
            return result

        def verify(*args):
            verified.append(self.clock.now)
            return original_verify(*args)

        self.task.loop = screenshots
        with patch.object(self.module, 'recognize_rows', side_effect=read), \
             patch.object(self.module, 'verify_targets', side_effect=verify):
            result = self.task._scan_pass(self.catalog)
        self.assertEqual(result.pages, 4)
        self.assertEqual(len(result.rows), 12)
        for finish, check in zip(completed, verified):
            self.assertAlmostEqual(check - finish, .2)

    def test_persistent_failure_stops_and_preserves_snapshot_and_click_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'warehouse.db'
            save_snapshot('recovery_test', 'cn',
                          [dict(id='old', name='旧物品', group='材料', amount=99)],
                          started_at='2026-10-01', pages=2, catalog_version='old', database=database)
            database = database.parent / 'azurpilot.db'
            before = database.read_bytes()
            writer = self.enterContext(patch.object(self.module, 'save_snapshot'))
            self.enterContext(patch.object(self.module, 'StorageCatalog', return_value=self.catalog))
            self.enterContext(patch.object(self.module.server, 'server', 'cn'))
            with patch.object(self.module, 'recognize_rows', side_effect=StorageRecognitionError('残缺数量')):
                with self.assertRaisesRegex(StorageStatisticsError, '残缺数量'):
                    self.task.run()
            self.assertEqual(len(self.device.swipes), 2)
            self.assertEqual(self.device.position, 0.)
            self.device.click_record_clear.assert_not_called()
            self.assertEqual(before, database.read_bytes())
            writer.assert_not_called()
            self.task.config.task_delay.assert_called_once_with(success=False)

    def test_slow_screenshots_expire_thirty_second_window(self):
        self.task._storage_in_material.return_value = False
        start = self.clock.now
        with patch.object(self.module, 'recognize_rows') as reader:
            with self.assertRaisesRegex(StorageRecognitionError, '等待材料仓库稳定'):
                self.task._scan_pass(self.catalog)
        self.assertEqual(self.clock.now - start, 33)
        self.assertEqual(self.frames, 11)
        self.assertEqual(self.device.swipes, [])
        reader.assert_not_called()

    def test_slow_scroll_gesture_gets_a_fresh_read_window(self):
        original = self.device.drag
        slow_positions = []

        def drag(start, end, **kwargs):
            original(start, end, **kwargs)
            if len(self.device.swipes) == 3:
                self.clock.advance(31)
                slow_positions.append(self.device.position)

        self.device.drag = drag
        with patch.object(self.module, 'recognize_rows', side_effect=self.read):
            result = self.task._scan_pass(self.catalog)
        self.assertEqual(result.pages, 4)
        self.assertEqual(len(result.rows), 12)
        self.assertEqual(self.read_positions.count(slow_positions[0]), 1)

    def test_three_row_scroll_overshoot_is_rejected_without_skipping(self):
        original = self.device.drag

        def drag(start, end, **kwargs):
            original(start, end, **kwargs)
            if len(self.device.swipes) >= 3:
                self.device.position += 178 / (len(self.device.content) - 572)

        self.device.drag = drag
        with patch.object(self.module, 'recognize_rows', side_effect=self.read):
            with self.assertRaisesRegex(StorageRecognitionError, '滚动条未到达指定三行位置'):
                self.task._scan_pass(self.catalog)
        self.assertEqual(self.device.click_record_clear.call_count, 1)


if __name__ == '__main__':
    unittest.main()
