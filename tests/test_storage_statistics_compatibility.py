"""其他账号的独立失败截图及强虹彩标定回归，不连接游戏设备。"""

from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.statistics.storage_snapshot import latest_snapshot, save_snapshot
from module.storage.statistics import StorageStatistics
from module.storage.statistics_recognition import (StorageCard, StorageCatalog, StorageRecognitionError,
    calibrate_scroll, detect_rows, recognize_rows, same_targets, verify_targets)
from tests.test_storage_statistics import FrameTimer, InventoryDevice

FIXTURES = Path(__file__).parent / 'fixtures/storage_statistics'


class OtherAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = StorageCatalog()

    def test_four_gifts_native_frame_reads_complete_thirty_without_new_templates(self):
        image = load_image(str(FIXTURES / 'other_account_four_gifts.png'))
        rows = recognize_rows(image, self.catalog, target_only=True)
        self.assertEqual([(card.identifier, card.amount) for row in rows for card in row if card.identifier],
                         [('PrototypeGearPartsT5', 100), ('GearDesignPlanGunT5', 18),
                          ('GearDesignPlanTorpedoT5', 24), ('GearDesignPlanAntiAirT5', 17),
                          ('GearDesignPlanPlaneT5', 30), ('SecretDesignPlanT5', 5)])
        self.assertTrue(all(same_targets(a, b)
                            for a, b in zip(rows, verify_targets(detect_rows(image), rows, self.catalog))))

    def test_no_gifts_rainbow_corner_does_not_hide_antiair_plan(self):
        image = load_image(str(FIXTURES / 'other_account_no_gifts.png'))
        rows = recognize_rows(image, self.catalog, target_only=True)
        self.assertEqual([(card.identifier, card.amount) for row in rows for card in row if card.identifier],
                         [('GearDesignPlanGunT5', 3), ('GearDesignPlanTorpedoT5', 3),
                          ('GearDesignPlanAntiAirT5', 1), ('SecretDesignPlanT5', 3)])

    def test_damaged_first_or_last_digit_of_thirty_is_rejected(self):
        card = detect_rows(load_image(str(FIXTURES / 'other_account_four_gifts.png')))[0][5]
        for left, right in ((96, 107), (109, 120)):
            with self.subTest(left=left):
                icon = card.image.copy()
                icon[103:115, left:right] = (32, 36, 50)
                with self.assertRaises(StorageRecognitionError):
                    self.catalog.read_amount(icon)


class RawCalibrationTests(unittest.TestCase):
    def setUp(self):
        image = load_image(str(FIXTURES / 'live_rainbow_brightness.png'))
        self.before = []
        self.after = []
        for index in range(4):
            y = 264 + 178 * index if index < 2 else 86 + 178 * (index - 2)
            row = [StorageCard((140 + 159 * column, y, 268 + 159 * column, y + 128),
                               image[index * 128:(index + 1) * 128, column * 128:(column + 1) * 128])
                   for column in range(7)]
            (self.before if index < 2 else self.after).append(row)

    def test_raw_rainbow_rows_calibrate_without_quantity_recognition(self):
        pitch, scale = calibrate_scroll(self.before, self.after, 16)
        self.assertEqual(pitch, 178)
        self.assertEqual(scale, 178 / 16)
        self.assertTrue(all(card.amount is None and card.comparison_amount is None
                            for row in self.before + self.after for card in row))

    def test_different_portraits_and_repeated_rows_cannot_confirm_displacement(self):
        with self.assertRaises(StorageRecognitionError):
            calibrate_scroll(self.before, [list(reversed(row)) for row in self.after], 16)
        self.before[1] = [StorageCard(card.area, self.before[0][column].image)
                          for column, card in enumerate(self.before[1])]
        self.after[1] = [StorageCard(card.area, self.after[0][column].image)
                         for column, card in enumerate(self.after[1])]
        with self.assertRaisesRegex(StorageRecognitionError, '缺少唯一完整重叠行'):
            calibrate_scroll(self.before, self.after, 16)


class AccountTraversalTests(unittest.TestCase):
    def test_native_account_rows_scan_once_and_commit_all_counts_in_temporary_database(self):
        additions = {
            'other_account_four_gifts.png': {
                'PrototypeGearPartsT5': 100, 'GearDesignPlanGunT5': 18, 'GearDesignPlanTorpedoT5': 24,
                'GearDesignPlanAntiAirT5': 17, 'GearDesignPlanPlaneT5': 30, 'SecretDesignPlanT5': 5},
            'other_account_no_gifts.png': {
                'GearDesignPlanGunT5': 3, 'GearDesignPlanTorpedoT5': 3,
                'GearDesignPlanAntiAirT5': 1, 'SecretDesignPlanT5': 3}}
        original = json.loads((FIXTURES / 'expected.json').read_text(encoding='utf-8'))
        module = __import__('module.storage.statistics', fromlist=['StorageStatistics'])
        for name, amounts in additions.items():
            with self.subTest(frame=name), tempfile.TemporaryDirectory() as directory:
                device = InventoryDevice()
                image = load_image(str(FIXTURES / name))
                strips = [image[row[0].area[1] - 6:row[0].area[1] + 172, 130:1235]
                          for row in detect_rows(image)]
                # 只拼接原生行，保留真实识别、标定、分页及原子提交；不连接真实设备。
                device.content = np.concatenate(strips + [device.content])
                device.length = max(72, round(572 / len(device.content) * 496))
                task = StorageStatistics.__new__(StorageStatistics)
                task.device = device
                task.config = SimpleNamespace(config_name='compatibility_test', Emulator_ControlMethod='MaaTouch',
                                              StorageStatistics_RunIntervalDays=7, task_delay=Mock())
                task.ui_goto_storage = Mock()
                task._storage_enter_material = Mock()
                task._storage_in_material = Mock(return_value=True)
                task.handle_info_bar = Mock(return_value=False)

                def frames(**kwargs):
                    for _ in range(100):
                        yield device.screenshot()
                    raise AssertionError('扫描未在有限帧内完成')

                task.loop = frames
                database = Path(directory) / 'azurpilot.db'
                with patch.object(module, 'Timer', FrameTimer), patch.object(module, 'logger'), \
                     patch.object(module, 'save_snapshot',
                                  side_effect=lambda *args, **kwargs: save_snapshot(*args, **kwargs, database=database)), \
                     patch.object(task, '_scan_pass', wraps=task._scan_pass) as scan:
                    task.run()
                scan.assert_called_once()
                expected = {case['id']: case['amount'] + amounts.get(case['id'], 0) for case in original}
                snapshot = latest_snapshot('compatibility_test', database=database)
                self.assertEqual({item['id']: item['amount'] for item in snapshot['items']}, expected)
                task.config.task_delay.assert_called_once_with(minute=7 * 1440)


if __name__ == '__main__':
    unittest.main()
