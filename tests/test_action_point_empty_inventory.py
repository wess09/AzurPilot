"""空白箱格的总行动力采集回归；不连接设备或真实数据。"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import numpy as np

from module.api.stock_exchange_history import ActionHistory, history_point
from module.ocr.ocr import Ocr
from module.os_handler.action_point import ActionPointHandler
from module.scheduler.store import ProgramStore


class EmptyInventoryTests(unittest.TestCase):
    def update(self, *, fast=False, text=False, controls=True, oil_valid=True, current_valid=True,
               all_empty=False, observe=None):
        handler = ActionPointHandler.__new__(ActionPointHandler)
        handler.device = SimpleNamespace(image=np.full((720, 1280, 3), 40, dtype=np.uint8))
        if text:
            # 数量区有白色字形，但模型未能读出；不能把它当成空库存。
            handler.device.image[368:381, 579:583] = 255 if text is True else text
        handler.config = SimpleNamespace(OS_ACTION_POINT_BOX_USE=True, update=Mock(), override=Mock())
        handler.appear = Mock(return_value=controls)
        model = Mock()
        oil = '500' if oil_valid else ''
        boxes = ['', '', ''] if all_empty else ['', '1', '2']
        if fast:
            model.atomic_ocr_for_single_lines.side_effect = [[oil, *boxes], *([['']] *
                (int(not oil_valid) + boxes.count('')))]
        else:
            results = []
            for value in (oil, *boxes):
                results.append([value])
                if not value:
                    results.append([''])
            model.atomic_ocr_for_single_lines.side_effect = results
        recorder = Mock()
        if observe:
            recorder.record.side_effect = lambda name, value, **_: observe(name, value)
        with patch('module.os_handler.action_point.resource_fast_path', return_value=fast), \
                patch.object(Ocr, 'cnocr', new_callable=PropertyMock, return_value=model), \
                patch('module.os_handler.action_point.OCR_ACTION_POINT_REMAIN') as current, \
                patch('module.os_handler.action_point.LogRes', return_value=recorder), \
                patch('module.os_handler.action_point.record_resources_background') as background:
            current.ocr.return_value = 186
            current.last_valid = current_valid
            handler.action_point_update()
        if fast:
            recorded = background.call_args.args[1].get('ActionPoint') if background.called else None
        else:
            recorded = next(call.args[1] for call in recorder.record.call_args_list if call.args[0] == 'ActionPoint')
        return handler, recorded

    def test_loaded_blank_box_is_zero_on_both_paths(self):
        for fast in (False, True):
            with self.subTest(fast=fast):
                handler, row = self.update(fast=fast)
                self.assertEqual({'Value': 186, 'Total': 436}, row)
                # 只修正报价采集资格，不放宽游戏内库存缓存的校验。
                self.assertFalse(handler._ap_inventory_valid)

    def test_all_boxes_can_be_empty_on_a_loaded_panel(self):
        for fast in (False, True):
            with self.subTest(fast=fast):
                _, row = self.update(fast=fast, all_empty=True)
                self.assertEqual({'Value': 186, 'Total': 186}, row)

    def test_visible_unread_text_is_not_zero(self):
        for fast in (False, True):
            for text in (True, 100):
                with self.subTest(fast=fast, text=text):
                    _, row = self.update(fast=fast, text=text)
                    self.assertTrue(row is None or 'Total' not in row)

    def test_loading_panel_or_invalid_oil_is_not_complete_inventory(self):
        for fast in (False, True):
            for options in ({'controls': False}, {'oil_valid': False}, {'current_valid': False}):
                with self.subTest(fast=fast, **options):
                    _, row = self.update(fast=fast, **options)
                    self.assertTrue(row is None or 'Total' not in row)

    def test_november_observation_enters_authenticated_history_and_upload_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config' / 'test.json').write_text('{"Alas":{}}', encoding='utf-8')
            store = ProgramStore(root / 'config')
            store.database.ensure_ready()
            stamp = datetime(2026, 11, 1, 20, 0, 0)
            def observe(name, value):
                store.observe('test', name, value, stamp.isoformat(), 'fixture')
            self.update(observe=observe)
            journal = ActionHistory(root)
            try:
                latest = journal.capture('test', {}, store.history.path('test'))
                self.assertEqual(history_point(436, stamp.isoformat()), latest)
                connection, _ = journal._connection('test')
                self.assertEqual(('2026-11', 436, 0), connection.execute(
                    'SELECT month,total,uploaded FROM samples').fetchone())
            finally:
                journal.close()


if __name__ == '__main__':
    unittest.main()
