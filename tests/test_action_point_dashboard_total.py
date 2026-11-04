"""行动力仪表盘口径回归测试。

防止行动力溢出任务会在 temporary(OS_ACTION_POINT_BOX_USE=False) 上下文中代跑
大世界子任务。若此时把受开关影响的 total 写进 Dashboard.ActionPoint.Total，
WebUI 的「总行动力」会退化成当前行动力，整段时间都不显示。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from module.os_handler.action_point import ActionPointHandler


class TestActionPointDashboardTotal(unittest.TestCase):
    """action_point_update() 写入仪表盘的总行动力必须恒含体力箱。"""

    current = 186
    # OIL_ITEM 一格雷 500 + ACTION_POINT_ITEMS 三格 0/1/2，按 ACTION_POINT_BOX 折算共 250
    box = (0, 1, 2)
    box_sum = 250

    def update(self, box_use, oil=500, oil_validity=(True,), box_validity=(True, True, True)):
        handler = ActionPointHandler.__new__(ActionPointHandler)
        handler.device = SimpleNamespace(image=None)
        handler.config = SimpleNamespace(
            OS_ACTION_POINT_BOX_USE=box_use,
            update=MagicMock(),
            override=MagicMock(),
        )
        log_res = MagicMock()
        # 两个物品网格在运行时共用数量 OCR，后一批会覆盖前一批校验结果。
        shared_ocr = SimpleNamespace(last_batch_validity=())

        def read_oil(*args, **kwargs):
            shared_ocr.last_batch_validity = oil_validity
            return [SimpleNamespace(amount=oil)]

        def read_boxes(*args, **kwargs):
            shared_ocr.last_batch_validity = box_validity
            return [SimpleNamespace(amount=amount) for amount in self.box]

        with patch('module.os_handler.action_point.resource_fast_path', return_value=False), \
                patch('module.os_handler.action_point.LogRes', return_value=log_res), \
                patch('module.os_handler.action_point.OIL_ITEM') as oil_item, \
                patch('module.os_handler.action_point.ACTION_POINT_ITEMS') as items, \
                patch('module.os_handler.action_point.OCR_ACTION_POINT_REMAIN') as ocr:
            oil_item.amount_ocr = items.amount_ocr = shared_ocr
            oil_item.predict.side_effect = read_oil
            items.predict.side_effect = read_boxes
            ocr.ocr.return_value = self.current
            ocr.last_valid = True
            handler.action_point_update()
        return handler, log_res

    def test_total_includes_box_when_box_use_enabled(self):
        handler, log_res = self.update(box_use=True)

        log_res.record.assert_any_call('ActionPoint', {'Value': self.current, 'Total': self.current + self.box_sum}, observed=True)
        self.assertEqual(handler._action_point_total, self.current + self.box_sum)

    def test_unloaded_oil_does_not_write_observation(self):
        for oil in (0, 1, 2, 100):
            with self.subTest(oil=oil):
                _, log_res = self.update(box_use=True, oil=oil)
                self.assertFalse(any(call.args[0] == 'Oil' for call in log_res.record.call_args_list))

    def test_stable_oil_writes_observation(self):
        _, log_res = self.update(box_use=True, oil=101)
        log_res.record.assert_any_call('Oil', 101, observed=True)

    def test_total_still_includes_box_when_box_use_disabled(self):
        # 防溢出任务临时关闭开箱开关，业务判据照旧不含箱，但仪表盘口径不应随之退化
        handler, log_res = self.update(box_use=False)

        log_res.record.assert_any_call('ActionPoint', {'Value': self.current, 'Total': self.current + self.box_sum}, observed=True)
        self.assertEqual(handler._action_point_total, self.current)

    def test_unverified_inventory_keeps_current_without_a_total(self):
        for oil_validity, box_validity in (
            ((False,), (True, True, True)),
            ((True,), (False, True, True)),
            ((True,), (True, False, True)),
            ((True,), (True, True, False)),
            ((), (True, True, True)),
            ((True,), (True, True)),
        ):
            with self.subTest(oil=oil_validity, boxes=box_validity):
                _, log_res = self.update(True, oil_validity=oil_validity, box_validity=box_validity)
                log_res.record.assert_any_call('ActionPoint', {'Value': self.current}, observed=True)


if __name__ == '__main__':
    unittest.main()
