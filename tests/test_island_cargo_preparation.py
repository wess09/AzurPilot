import os
import unittest

import numpy as np
from PIL import Image

from module.base.button import ButtonGrid
from module.island.island_cargo_preparation import (
    CargoPreparationTransportItem,
    cargo_can_start,
    classify_job_list_rows,
    should_replace_unfillable,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'island_cargo')


def load_fixture(name):
    return np.array(Image.open(os.path.join(FIXTURE_DIR, name)).convert('RGB'))


class CargoPreparationStartTests(unittest.TestCase):
    """验证货物槽为空时不会阻止货运委托启动。"""

    def test_trailing_empty_slots_do_not_block_start(self):
        self.assertTrue(
            cargo_can_start(
                available_item_count=1,
                action_button_active=True,
                refresh=False,
            )
        )

    def test_unloaded_available_items_delegate_loading_to_button(self):
        # 实际货物格是否存在才是启动条件；未装载由“全部装载”按钮补齐。
        self.assertTrue(
            cargo_can_start(
                available_item_count=2,
                action_button_active=True,
                refresh=False,
            )
        )

    def test_no_available_item_blocks_start(self):
        self.assertFalse(
            cargo_can_start(
                available_item_count=0,
                action_button_active=True,
                refresh=False,
            )
        )

    def test_blacklisted_cargo_blocks_start(self):
        self.assertFalse(
            cargo_can_start(
                available_item_count=2,
                action_button_active=True,
                refresh=True,
            )
        )

    def test_inactive_action_button_blocks_start(self):
        self.assertFalse(
            cargo_can_start(
                available_item_count=2,
                action_button_active=False,
                refresh=False,
            )
        )


class CargoPreparationReplaceTests(unittest.TestCase):
    """更换委托会扣除运输次数且不退还已提交货物，只更换尚未提交、仍缺货的委托。"""

    def test_untouched_short_commission_is_replaced(self):
        self.assertTrue(should_replace_unfillable(short=True, delivered=False, refresh=False))

    def test_partly_delivered_commission_is_kept(self):
        self.assertFalse(should_replace_unfillable(short=True, delivered=True, refresh=False))

    def test_fillable_commission_is_kept(self):
        self.assertFalse(should_replace_unfillable(short=False, delivered=False, refresh=False))

    def test_blacklisted_commission_uses_blacklist_path(self):
        self.assertFalse(should_replace_unfillable(short=True, delivered=False, refresh=True))


class CargoPreparationTransportItemTests(unittest.TestCase):
    """用国际服运输页面截图校验已提交与缺货格子的识别。"""

    def _cells(self, image, index):
        grids = ButtonGrid(origin=(481, 174 + 176 * index), delta=(105, 0), button_shape=(86, 86),
                           grid_shape=(3, 1))
        return [CargoPreparationTransportItem(image, button, []) for button in grids.buttons]

    def test_completed_and_short_cells(self):
        image = load_fixture('en_transport_short.png')
        # 委托 1：肉类 6/16 缺货，另两格已提交；委托 2：只有肉类 6/26 缺货；委托 3：草莓缺货，另两格已提交
        expected = [
            [('short', False), ('completed', True), ('completed', True)],
            [('short', False), ('empty', False), ('empty', False)],
            [('completed', True), ('short', False), ('completed', True)],
        ]
        for index, cells in enumerate(expected):
            for cell, (kind, completed) in zip(self._cells(image, index), cells):
                with self.subTest(commission=index, kind=kind):
                    self.assertEqual(cell.completed, completed)
                    self.assertEqual(cell.valid, kind == 'short')
                    self.assertFalse(cell.load)


class CargoPreparationJobListTests(unittest.TestCase):
    """用国际服更换委托列表截图校验每行能否凑齐货物。"""

    def test_top_of_list_skips_short_selected_row(self):
        rows = classify_job_list_rows(load_fixture('en_job_list_top.png'))
        # 第 1 行肉类 6/16 不足（且处于选中高亮），其余 3 行全部足够
        self.assertEqual([fillable for _, fillable in rows], [False, True, True, True])

    def test_scrolled_list_without_selection(self):
        rows = classify_job_list_rows(load_fixture('en_job_list_scrolled.png'))
        self.assertEqual([fillable for _, fillable in rows], [True, True, True, True])
        self.assertTrue(all(150 < y < 580 for y, _ in rows))


class CargoPreparationLeaveJobListTests(unittest.TestCase):
    """刷新后仍没有可完成的委托时要关闭 Job List 弹窗：弹窗下方露出的货运页面会让
    island_in_transport() 误判已返回，返回手机页时又一直卡在弹窗上（国际服 2026-11-05 23:28）。"""

    def make(self, frames):
        from unittest.mock import Mock, patch
        from module.island import island_cargo_preparation as cargo_module
        from module.island.island_cargo_preparation import IslandCargoPreparation

        with patch.object(IslandCargoPreparation, '__init__', lambda self: None):
            cargo = IslandCargoPreparation()
        cargo.device = Mock()
        state = {'popup': True}
        cargo.device.click = Mock(side_effect=lambda button: state.update(
            popup=False) if button is cargo_module.REPLACE_PAGE_CANCEL else None)
        cargo.appear = Mock(side_effect=lambda button, **kwargs:
                            button is cargo_module.REPLACE_PAGE_CHECK and state['popup'])
        cargo.island_in_transport = Mock(return_value=True)   # 弹窗下方露出货运页面
        cargo.loop = lambda **kwargs: iter(range(frames))
        cargo.appear_then_click = Mock(return_value=False)
        cargo.ui_additional = Mock(return_value=False)
        return cargo, state, cargo_module

    def test_back_to_transport_closes_job_list_first(self):
        cargo, state, cargo_module = self.make(frames=5)
        self.assertTrue(cargo._back_to_transport())
        cargo.device.click.assert_called_once_with(cargo_module.REPLACE_PAGE_CANCEL)
        self.assertFalse(state['popup'])

    def test_back_to_island_phone_closes_job_list(self):
        cargo, state, cargo_module = self.make(frames=5)
        cargo.ui_page_appear = lambda page: not state['popup']
        cargo._back_to_island_phone()
        cargo.device.click.assert_called_once_with(cargo_module.REPLACE_PAGE_CANCEL)

    def test_job_list_check_matches_only_the_popup(self):
        # 只在 Job List 弹窗上匹配，货运页面本身不匹配，避免在货运页误点「取消」位置
        import cv2
        asset = np.array(Image.open(os.path.join(
            os.path.dirname(__file__), '..', 'assets', 'en', 'island_cargo_preparation',
            'REPLACE_PAGE_CHECK.png')).convert('RGB'))
        ys, xs = np.where(asset.max(axis=2) > 0)
        x1, y1, x2, y2 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        template = asset[y1:y2, x1:x2]

        def score(name):
            image = load_fixture(name)[y1 - 20:y2 + 20, x1 - 20:x2 + 20]
            return cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED).max()

        self.assertGreater(score('en_job_list_top.png'), 0.85)
        self.assertLess(score('en_transport_short.png'), 0.85)


if __name__ == '__main__':
    unittest.main()
