"""港口商店连续跳过买不起的物品时不重复截图识别货币，避免画面 30 秒不变被判定卡死。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.os_shop.shop import OSShop


class SkipUnaffordableTest(unittest.TestCase):
    def test_skipped_items_do_not_reread_coins(self):
        with patch.object(OSShop, '__init__', lambda self: None):
            shop = OSShop()
        shop.config = Mock()
        shop.device = Mock()
        cheap = SimpleNamespace(name='Cheap', price=10, cost='YellowCoins', shop_index=0, scroll_pos=0.0)
        expensive = [SimpleNamespace(name=f'Expensive{i}', price=10 ** 6, cost='YellowCoins',
                                     shop_index=0, scroll_pos=0.0) for i in range(40)]
        shop.os_shop_get_coins = Mock()
        shop.scan_all = Mock(return_value=[cheap] + expensive)
        shop.items_filter_in_os_shop = lambda items: items
        shop.get_currency_coins = Mock(return_value=100)
        shop.is_coins_both_not_enough = Mock(return_value=False)
        shop.os_shop_side_navbar_ensure = Mock()
        shop.os_shop_get_items_to_buy = Mock(return_value=cheap)
        shop.check_item_count = Mock(return_value=True)
        shop.os_shop_buy_execute = Mock(return_value=True)
        with patch('module.os_shop.shop.OS_SHOP_SCROLL'), patch('module.os_shop.shop.logger'):
            self.assertTrue(shop.handle_port_supply_buy())
        # 进入时识别一次，买下第一件后识别一次；之后 40 件都买不起，不再识别
        self.assertEqual(shop.os_shop_get_coins.call_count, 2)


if __name__ == '__main__':
    unittest.main()
