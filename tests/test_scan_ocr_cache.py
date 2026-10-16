"""有界字图复用的正确性、配置隔离、失败和同步退出验证。"""
import unittest
from unittest.mock import Mock

import numpy as np

from module.runtime.scan_metrics import CachedOcr, ScanMetrics
from module.exception import MindCalculatorScanError


class ScanOcrCacheTests(unittest.TestCase):
    def reader(self, **kwargs):
        reader = Mock(save_debug_images=False)
        reader._get_settings.return_value = ('onnx', 'cpu', 'standard')
        reader.ocr_for_single_lines.side_effect = lambda images: [str(image.sum()) for image in images]
        return reader, CachedOcr(reader, ScanMetrics(), 'names', **kwargs)

    def test_exact_images_reuse_in_original_order_but_one_pixel_changes_do_not(self):
        reader, cache = self.reader()
        first, second = np.zeros((19, 128), np.uint8), np.ones((19, 128), np.uint8)
        self.assertEqual(cache.ocr_for_single_lines([first, second, first.copy()]), ['0', '2432', '0'])
        self.assertEqual(len(reader.ocr_for_single_lines.call_args.args[0]), 2)
        self.assertEqual(cache.ocr_for_single_lines([second, first]), ['2432', '0'])
        self.assertEqual(reader.ocr_for_single_lines.call_count, 1)
        first[0, 0] = 1
        self.assertEqual(cache.ocr_for_single_lines([first]), ['1'])
        self.assertEqual(reader.ocr_for_single_lines.call_count, 2)

    def test_settings_and_readers_are_independent_and_cache_has_hard_resource_bounds(self):
        reader, cache = self.reader(max_entries=2, max_bytes=20)
        for number in range(10):
            cache.ocr_for_single_lines([np.full((4, 4), number, np.uint8)])
            self.assertLessEqual(len(cache.cache), 2)
            self.assertLessEqual(cache.bytes, 20)
        image = np.full((4, 4), 9, np.uint8)
        count = reader.ocr_for_single_lines.call_count
        reader._get_settings.return_value = ('ncnn', 'cpu', 'pro')
        cache.ocr_for_single_lines([image])
        self.assertEqual(reader.ocr_for_single_lines.call_count, count + 1)
        other_reader, other = self.reader()
        other.ocr_for_single_lines([image])
        other_reader.ocr_for_single_lines.assert_called_once()

    def test_model_failure_has_no_partial_cache_or_background_work(self):
        reader, cache = self.reader()
        reader.ocr_for_single_lines.side_effect = RuntimeError('模型失败')
        with self.assertRaises(MindCalculatorScanError):
            cache.ocr_for_single_lines([np.zeros((19, 128), np.uint8)])
        self.assertEqual(len(cache.cache), 0)
        reader.ocr_for_single_lines.assert_called_once()

    def test_detection_and_diagnostic_model_failures_use_the_same_controlled_scan_error(self):
        reader, cache = self.reader()
        reader.det.side_effect = Exception('检测模型失败')
        with self.assertRaises(MindCalculatorScanError):
            cache.det(np.zeros((720, 1280, 3), np.uint8))
        reader.save_debug_images = True
        reader.ocr_for_single_lines.side_effect = Exception('诊断模型失败')
        with self.assertRaises(MindCalculatorScanError):
            cache.ocr_for_single_lines([np.zeros((19, 128), np.uint8)])

    def test_diagnostic_io_uses_original_path_and_bad_model_card_count_is_rejected(self):
        reader, cache = self.reader()
        reader.save_debug_images = True
        image = np.zeros((19, 128), np.uint8)
        cache.ocr_for_single_lines([image, image])
        self.assertEqual(len(reader.ocr_for_single_lines.call_args.args[0]), 2)
        reader.save_debug_images = False
        reader.ocr_for_single_lines.side_effect = lambda images: []
        with self.assertRaises(RuntimeError):
            cache.ocr_for_single_lines([image])
