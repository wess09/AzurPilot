"""装备码输入确认流程的回归测试。"""

import unittest
from unittest.mock import Mock

from module.equipment.assets import EQUIPMENT_CODE_ENTER
from module.equipment.equipment_code import EquipmentCodeHandler


class TestEquipmentCodePreviewWait(unittest.TestCase):
    """等待循环应当先判断正向退出状态，再处理点击。"""

    @staticmethod
    def _handler():
        return object.__new__(EquipmentCodeHandler)

    def test_loaded_preview_exits_without_clicking_visible_confirm(self):
        handler = self._handler()
        handler.loop = Mock(return_value=iter([None]))
        handler.appear_then_click = Mock()
        handler.is_code_preview_loaded = Mock(return_value=True)

        self.assertTrue(handler._code_wait_preview_loaded())
        handler.appear_then_click.assert_not_called()
        handler.is_code_preview_loaded.assert_called_once_with()

    def test_confirm_is_clicked_until_preview_loads(self):
        handler = self._handler()
        handler.loop = Mock(return_value=iter([None, None]))
        handler.appear_then_click = Mock(return_value=True)
        handler.is_code_preview_loaded = Mock(side_effect=[False, True])

        self.assertTrue(handler._code_wait_preview_loaded())
        handler.appear_then_click.assert_called_once_with(
            EQUIPMENT_CODE_ENTER, offset=(5, 5), interval=3
        )
        self.assertEqual(handler.is_code_preview_loaded.call_count, 2)

    def test_unknown_preview_times_out(self):
        handler = self._handler()
        handler.loop = Mock(return_value=iter([None, None]))
        handler.appear_then_click = Mock(return_value=False)
        handler.is_code_preview_loaded = Mock(return_value=False)

        self.assertFalse(handler._code_wait_preview_loaded())
        self.assertEqual(handler.is_code_preview_loaded.call_count, 2)
        self.assertEqual(handler.appear_then_click.call_count, 2)


class TestEquipmentCodePreviewState(unittest.TestCase):
    """装备预览只能通过已知的正向状态确认。"""

    @staticmethod
    def _handler(empty_states, occupied_states, special=False):
        handler = object.__new__(EquipmentCodeHandler)
        handler.appear = Mock(side_effect=empty_states)
        handler._code_preview_slot_occupied = Mock(side_effect=occupied_states)
        handler._code_special_equip_occupied = Mock(return_value=special)
        return handler

    def test_regular_occupied_slot_confirms_loaded_preview(self):
        handler = self._handler(
            empty_states=[False, True, True, True, True],
            occupied_states=[True, False, False, False, False],
        )

        self.assertTrue(handler.is_code_preview_loaded())
        handler._code_special_equip_occupied.assert_not_called()

    def test_unknown_regular_slot_does_not_confirm_preview(self):
        handler = self._handler(empty_states=[False], occupied_states=[False])

        self.assertFalse(handler.is_code_preview_loaded())

    def test_ambiguous_regular_slot_does_not_confirm_preview(self):
        handler = self._handler(empty_states=[True], occupied_states=[True])

        self.assertFalse(handler.is_code_preview_loaded())

    def test_special_slot_is_checked_after_five_empty_slots(self):
        handler = self._handler(
            empty_states=[True, True, True, True, True, False, False],
            occupied_states=[False, False, False, False, False],
            special=True,
        )

        self.assertTrue(handler.is_code_preview_loaded())
        handler._code_special_equip_occupied.assert_called_once_with()

    def test_known_empty_or_locked_special_slot_is_not_loaded(self):
        for sixth_states in ([True], [False, True]):
            with self.subTest(sixth_states=sixth_states):
                handler = self._handler(
                    empty_states=[True, True, True, True, True, *sixth_states],
                    occupied_states=[False, False, False, False, False],
                    special=True,
                )

                self.assertFalse(handler.is_code_preview_loaded())
                handler._code_special_equip_occupied.assert_not_called()

    def test_empty_preview_uses_positive_slot_matches(self):
        for sixth_states in ([True], [False, True]):
            with self.subTest(sixth_states=sixth_states):
                handler = object.__new__(EquipmentCodeHandler)
                handler.appear = Mock(
                    side_effect=[True, True, True, True, True, *sixth_states]
                )

                self.assertTrue(handler.is_code_preview_empty())

    def test_clear_loop_exits_only_on_positive_empty_preview(self):
        handler = object.__new__(EquipmentCodeHandler)
        handler.loop = Mock(return_value=iter([None]))
        handler.is_code_preview_empty = Mock(return_value=True)
        handler.appear_then_click = Mock()

        self.assertTrue(handler._code_preview_clear())
        handler.appear_then_click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
