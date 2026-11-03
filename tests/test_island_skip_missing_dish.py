"""店铺生产：产品列表里一直找不到的商品（如科技未解锁）本轮跳过，不再判定游戏卡死重启。"""

import unittest
from unittest.mock import Mock, patch

from module.exception import GameStuckError
from module.island.island_shop_base import IslandShopBase


def make_shop():
    with patch.object(IslandShopBase, '__init__', lambda self: None):
        shop = IslandShopBase()
    shop.back_to_postmanage_from_dispatch = Mock(return_value=True)
    shop.post_manage_mode = Mock()
    shop.post_manage_swipe = Mock()
    shop.post_manage_swipe_count = 1
    shop.post_open = Mock(return_value=True)
    shop.device = Mock()
    shop._item_cn = lambda name: name
    return shop


class SkipMissingDishTest(unittest.TestCase):
    def test_retry_below_limit_reopens_post(self):
        shop = make_shop()
        self.assertTrue(shop.retry_product_selection_from_postmanage('POST', 'banana_crepe', 'banana_crepe', 1))
        shop.post_open.assert_called_once_with('POST')

    def test_limit_gives_up_without_restart(self):
        shop = make_shop()
        limit = IslandShopBase.PRODUCT_SELECT_RETRY_LIMIT
        self.assertFalse(shop.retry_product_selection_from_postmanage('POST', 'banana_crepe', 'banana_crepe', limit))
        shop.back_to_postmanage_from_dispatch.assert_called_once()
        shop.post_open.assert_not_called()

    def test_still_stuck_when_cannot_leave_dispatch(self):
        shop = make_shop()
        shop.back_to_postmanage_from_dispatch.return_value = False
        limit = IslandShopBase.PRODUCT_SELECT_RETRY_LIMIT
        with self.assertRaises(GameStuckError):
            shop.retry_product_selection_from_postmanage('POST', 'banana_crepe', 'banana_crepe', limit)


if __name__ == '__main__':
    unittest.main()
