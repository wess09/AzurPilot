"""滚动条三行标定、行号完整性与金/彩识别范围的真实截图回归。"""

from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from module.base.utils import load_image
from module.storage.statistics_recognition import (StorageCard, StorageCatalog, StorageRecognitionError,
    StorageTraversal, calibrate_scroll, detect_rows, is_purple, recognize_rows, same_targets, verify_targets)

FIXTURES = Path(__file__).parent / 'fixtures/storage_statistics'


class ThreeRowPagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = StorageCatalog()

    def test_float_matching_keeps_legacy_uint8_scores_and_confidence(self):
        for name in ('page_3.png', 'page_4.png', 'live_rainbow_plan_phase.png'):
            with self.subTest(image=name):
                card = detect_rows(load_image(str(FIXTURES / name)))[0][0]
                actual = self.catalog._scores(card.image, card.context)
                color = cv2.resize(card.image, (96, 96), interpolation=cv2.INTER_AREA)[5:13, 5:13].mean(axis=(0, 1))
                phases = [cv2.resize(card.context[y:y + 128, x:x + 128], (96, 96),
                                     interpolation=cv2.INTER_AREA)
                          for y in range(1, 4) for x in range(1, 4)]
                legacy = {}
                for identifier, template, background in self.catalog.templates:
                    if np.max(np.abs(color - background)) > 45:
                        continue
                    score = max(cv2.minMaxLoc(cv2.matchTemplate(phase[:74], template.astype(np.uint8),
                                                               cv2.TM_CCOEFF_NORMED))[1] for phase in phases)
                    legacy[identifier] = max(legacy.get(identifier, -1.), score)
                self.assertEqual(actual.keys(), legacy.keys())
                for identifier in legacy:
                    self.assertAlmostEqual(actual[identifier], legacy[identifier], delta=.00001)
                ranks = sorted(legacy, key=legacy.get, reverse=True)
                expected = ranks[0] if legacy[ranks[0]] >= .90 else None
                self.assertEqual(self.catalog.identify(card.image, card.context), expected)

    def test_native_overlap_calibrates_three_row_distance(self):
        before = detect_rows(load_image(str(FIXTURES / 'scrollbar_top.png')))
        after = detect_rows(load_image(str(FIXTURES / 'scrollbar_calibration.png')))
        pitch, scale = calibrate_scroll(before, after, 17)
        self.assertEqual(pitch, 178)
        self.assertAlmostEqual(scale, 181 / 17)
        self.assertAlmostEqual(3 * pitch / scale, 50.1547, places=3)

    def test_wrong_direction_and_ambiguous_calibration_are_rejected(self):
        rows = detect_rows(load_image(str(FIXTURES / 'scrollbar_top.png')))
        with self.assertRaises(StorageRecognitionError):
            calibrate_scroll(rows, rows, -1)
        with self.assertRaises(StorageRecognitionError):
            calibrate_scroll(rows, list(reversed(rows)), 17)

    def test_rainbow_calibration_requires_five_matching_columns_and_unique_offset(self):
        before = detect_rows(load_image(str(FIXTURES / 'scrollbar_rainbow_top.png')))
        after = detect_rows(load_image(str(FIXTURES / 'scrollbar_rainbow_calibration.png')))
        pitch, scale = calibrate_scroll(before, after, 15)
        self.assertEqual(pitch, 178)
        self.assertAlmostEqual(scale, 238 / 15)
        self.assertAlmostEqual(3 * pitch / scale, 33.6555, places=3)
        with patch('module.storage.statistics_recognition.same_card', return_value=False), \
             patch('module.storage.statistics_recognition._same_calibration_card',
                   side_effect=lambda a, b: a is before[2][0] or a is before[2][1]
                   or a is before[2][2] or a is before[2][3]):
            with self.assertRaisesRegex(StorageRecognitionError, '缺少唯一完整重叠行'):
                calibrate_scroll(before, after, 15)
        with patch('module.storage.statistics_recognition.same_card', return_value=False), \
             patch('module.storage.statistics_recognition._same_calibration_card', return_value=True):
            with self.assertRaisesRegex(StorageRecognitionError, '缺少唯一完整重叠行'):
                calibrate_scroll(before, after, 15)

    def test_target_only_preserves_all_original_25_counts(self):
        for number in range(1, 5):
            image = load_image(str(FIXTURES / f'page_{number}.png'))
            full = recognize_rows(image, self.catalog)
            targets = recognize_rows(image, self.catalog, target_only=True)
            self.assertTrue(all(same_targets(a, b) for a, b in zip(full, targets)))
            self.assertTrue(all(card.comparison_amount is None for row in targets for card in row))

    def test_purple_boundary_skips_identity_and_amount_matching(self):
        image = load_image(str(FIXTURES / 'purple_boundary.png'))
        raw = detect_rows(image)
        self.assertTrue(is_purple(raw[-1][0].image))
        with patch.object(self.catalog, 'identify', wraps=self.catalog.identify) as identify, \
             patch.object(self.catalog, 'read_amount', wraps=self.catalog.read_amount) as amount:
            rows = recognize_rows(image, self.catalog, target_only=True)
        self.assertTrue(all(card.identifier is None and card.amount is None for card in rows[-1]))
        self.assertEqual(identify.call_count, 14)
        amount.assert_not_called()
        self.assertTrue(all(not is_purple(call.args[0]) for call in identify.call_args_list))

    def test_early_purple_gifts_do_not_hide_later_rainbow_targets(self):
        rows = recognize_rows(load_image(str(FIXTURES / 'scrollbar_top.png')),
                              self.catalog, target_only=True)
        self.assertEqual(rows[1][-1].identifier, 'PrototypeGearPartsT5')
        self.assertEqual(rows[1][-1].amount, 16)
        self.assertEqual(rows[2][2].identifier, 'SecretDesignPlanT5')
        self.assertEqual(rows[2][2].amount, 9)

    def test_same_page_verification_only_matches_confirmed_targets(self):
        image = load_image(str(FIXTURES / 'page_3.png'))
        previous = recognize_rows(image, self.catalog, target_only=True)
        with patch.object(self.catalog, 'identify', side_effect=AssertionError('不能重跑全目录')), \
             patch.object(self.catalog, 'read_amount', wraps=self.catalog.read_amount) as reader, \
             patch.object(self.catalog, '_scores', wraps=self.catalog._scores) as scores:
            rows = verify_targets(detect_rows(image), previous, self.catalog)
        self.assertTrue(all(same_targets(a, b) for a, b in zip(rows, previous)))
        targets = [card for row in previous for card in row if card.identifier]
        self.assertEqual(reader.call_count, len(targets))
        self.assertEqual(scores.call_count, len(targets))
        self.assertEqual([call.args[2] for call in scores.call_args_list],
                         [card.identifier for card in targets])

    def test_same_page_amount_conflict_and_different_icon_are_rejected(self):
        image = load_image(str(FIXTURES / 'page_3.png'))
        previous = recognize_rows(image, self.catalog, target_only=True)
        old = next(card for row in previous for card in row if card.identifier)
        with patch.object(self.catalog, 'read_amount', return_value=old.amount + 1) as reader:
            card = StorageCard(old.area, old.image, old.context)
            with self.assertRaisesRegex(StorageRecognitionError, '同页数量不一致'):
                self.catalog.verify(card, old)
        reader.assert_called_once()
        other = next(card for row in previous for card in row
                     if card.identifier and card.identifier != old.identifier)
        card = StorageCard(old.area, other.image, other.context)
        with self.assertRaisesRegex(StorageRecognitionError, '同页图标变化'):
            self.catalog.verify(card, old)

    def test_same_page_missing_columns_are_rejected(self):
        image = load_image(str(FIXTURES / 'scrollbar_top.png'))
        previous = recognize_rows(image, self.catalog, target_only=True)
        rows = detect_rows(image)
        rows[0].pop()
        with self.assertRaisesRegex(StorageRecognitionError, '同页材料列数变化'):
            verify_targets(rows, previous, self.catalog)

    def test_same_page_horizontal_contour_jitter_preserves_native_counts(self):
        image = load_image(str(FIXTURES / 'page_3.png'))
        previous = recognize_rows(image, self.catalog, target_only=True)
        for offset in (-2, -1, 1, 2):
            with self.subTest(offset=offset):
                rows = detect_rows(image)
                for row in rows:
                    for card in row:
                        x0, y0, x1, y1 = card.area
                        card.area = (x0 + offset, y0, x1 + offset, y1)
                        card.image = image[y0:y1, x0 + offset:x1 + offset].copy()
                        card.context = image[y0 - 2:y1 + 4, x0 + offset - 2:x1 + offset + 4].copy()
                confirmed = verify_targets(rows, previous, self.catalog)
                self.assertTrue(all(same_targets(a, b) for a, b in zip(confirmed, previous)))

    def test_same_page_actual_movement_or_empty_slot_change_stops_immediately(self):
        image = load_image(str(FIXTURES / 'page_3.png'))
        previous = recognize_rows(image, self.catalog, target_only=True)
        for dx, dy, present in ((-3, 0, True), (3, 0, True), (0, -1, True),
                                (0, 1, True), (0, 0, False)):
            with self.subTest(dx=dx, dy=dy, present=present):
                rows = detect_rows(image)
                card = rows[0][0]
                x0, y0, x1, y1 = card.area
                card.area = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
                card.present = present
                with patch.object(self.catalog, 'verify', wraps=self.catalog.verify) as verifier:
                    with self.assertRaisesRegex(StorageRecognitionError, '同页材料位置或空格变化：第 1 行第 1 列'):
                        verify_targets(rows, previous, self.catalog)
                verifier.assert_not_called()

    def test_native_rainbow_plan_phase_preserves_identity_and_complete_counts(self):
        image = load_image(str(FIXTURES / 'live_rainbow_plan_phase.png'))
        rows = recognize_rows(image, self.catalog, target_only=True)
        self.assertEqual({card.identifier: card.amount for row in rows for card in row if card.identifier},
                         {'GearDesignPlanTorpedoT5': 21, 'GearDesignPlanAntiAirT5': 47,
                          'GearDesignPlanPlaneT5': 59, 'SecretDesignPlanT5': 1})
        confirmed = verify_targets(detect_rows(image), rows, self.catalog)
        self.assertTrue(all(same_targets(a, b) for a, b in zip(rows, confirmed)))

    def test_numbered_three_row_pages_accept_contiguous_rows_and_reject_a_gap(self):
        image = np.zeros((128, 128, 3), dtype=np.uint8)
        rows = [[StorageCard((140, 86, 268, 214), image, identifier=f'item_{index}', amount=index + 1)]
                for index in range(9)]
        traversal = StorageTraversal()
        traversal.append(rows[:3], row_start=0)
        traversal.append(rows[3:6], row_start=3)
        self.assertEqual(len(traversal.rows), 6)
        with self.assertRaisesRegex(StorageRecognitionError, '缺行'):
            traversal.append(rows[6:], row_start=7)
        self.assertEqual(len(traversal.rows), 6)
        self.assertEqual(traversal.pages, 2)
        traversal.append(rows[4:7], row_start=4, at_bottom=True)
        self.assertEqual(len(traversal.rows), 7)
        with self.assertRaisesRegex(StorageRecognitionError, '不一致'):
            traversal.append(rows[5:8], row_start=4, at_bottom=True)


if __name__ == '__main__':
    unittest.main()
