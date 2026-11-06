"""经营列表点进的不是目标商店时不能无限重试。

国际服 2026-11-06：啾啾简餐（Manjuu Eatery）排在列表下方不可见，它的模板只截到 "Manjuu"，
以 0.94 匹配到啾咖啡（Café Manjuu）那一行；每次点进啾咖啡、返回、回到顶部、重新扫描后
又点同一位置，2 分钟内重复了 30 多次。
"""
import unittest
from unittest.mock import Mock, patch

from module.island.island_business import IslandBusiness


def make_business():
    with patch.object(IslandBusiness, '__init__', lambda self: None):
        business = IslandBusiness()
    business.config = Mock()
    business.device = Mock()
    business.post_manage_mode = Mock()
    business._scroll_business_to_top = Mock()
    business._scroll_business_down = Mock()
    business._set_task_delay = Mock()
    business._get_batch2_shops = Mock(return_value=[])
    return business


def found(y, similarity):
    return {
        'label_rect': (222, y, 329, y + 26),
        'button_rect': (990, y + 88, 1175, y + 115),
        'remain_time_rect': (0, 0, 1, 1),
        'similarity': similarity,
    }


class SameRowTest(unittest.TestCase):
    def test_weaker_match_on_same_row_is_dropped(self):
        business = make_business()
        screen = {
            '有鱼餐馆': found(91, 1.0),
            '啾咖啡': found(269, 0.988),
            '啾啾简餐': found(268, 0.943),
            '乌鱼烤肉': found(445, 0.988),
        }
        business._find_shop_on_screen = Mock(side_effect=lambda name: screen.get(name))
        business._detect_button_at = Mock(return_value='blue')
        shops = [{'name': name} for name in ['有鱼餐馆', '啾啾简餐', '乌鱼烤肉', '啾咖啡']]

        visible = business._scan_visible_batch_shops(shops)

        self.assertEqual([r['shop']['name'] for r in visible], ['有鱼餐馆', '啾咖啡', '乌鱼烤肉'])

    def test_different_rows_are_all_kept(self):
        business = make_business()
        screen = {'乌鱼烤肉': found(172, 1.0), '白熊饮品': found(348, 1.0), '啾啾简餐': found(525, 1.0)}
        business._find_shop_on_screen = Mock(side_effect=lambda name: screen.get(name))
        business._detect_button_at = Mock(return_value='gray')
        shops = [{'name': name} for name in ['啾啾简餐', '白熊饮品', '乌鱼烤肉']]

        visible = business._scan_visible_batch_shops(shops)

        self.assertEqual([r['shop']['name'] for r in visible], ['乌鱼烤肉', '白熊饮品', '啾啾简餐'])


class WrongShopTest(unittest.TestCase):
    def test_wrong_shop_is_entered_only_once(self):
        business = make_business()
        eatery = {'name': '啾啾简餐'}
        business._scan_visible_batch_shops = Mock(return_value=[
            {'shop': eatery, 'status': 'blue', 'button_rect': (990, 356, 1175, 383)},
        ])
        # 每次点击都进到啾咖啡
        business._detect_current_shop = Mock(return_value={'name': '啾咖啡'})
        business._process_shop_entry = Mock()

        started = business._run_batch([eatery])

        self.assertEqual(business._detect_current_shop.call_count, 1)
        business._process_shop_entry.assert_not_called()
        self.assertEqual(started, set())


if __name__ == '__main__':
    unittest.main()
