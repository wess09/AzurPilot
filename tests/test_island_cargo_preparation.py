import unittest

from module.island.island_cargo_preparation import cargo_can_start


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


if __name__ == '__main__':
    unittest.main()
