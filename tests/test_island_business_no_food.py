"""商店没有可出售的餐品时经营不能开始：不能无限重复进店点「开始经营」。

国际服 2026-11-05 冬季首日，有鱼餐馆「You have no food items to sell.」，开始经营按钮为灰色，
传统模式每 16 秒进店、选角色、点开始、返回，5 个半小时重复约 700 次。
"""
import unittest
from unittest.mock import Mock, patch

from module.island.island_business import IslandBusiness


def make_business(statuses, selected):
    """statuses: _check_start_button_status 依次返回的状态；selected: 每次选品返回的数量。"""
    with patch.object(IslandBusiness, '__init__', lambda self: None):
        business = IslandBusiness()
    business.config = Mock()
    business.device = Mock()
    status_iter = iter(statuses)
    business._check_start_button_status = Mock(side_effect=lambda: next(status_iter))
    business._detect_current_shop = Mock(return_value={'name': '有鱼餐馆'})
    business._load_shop_characters = Mock()
    business._select_business_characters = Mock()
    business._select_business_product = Mock(side_effect=list(selected))
    business._confirm_business_start = Mock()
    business._leave_shop_without_start = Mock()
    business.post_manage_mode = Mock()
    business._trigger_shop_refill = Mock()
    business._set_task_delay = Mock()
    return business


class LegacyNoFoodTest(unittest.TestCase):
    def test_no_food_skips_shop_and_checks_the_others(self):
        business = make_business(['blue'], selected=[0])
        business._run_remaining_shops = Mock()
        business._run_legacy_mode()
        business._confirm_business_start.assert_not_called()
        business._leave_shop_without_start.assert_called_once()
        business._run_remaining_shops.assert_called_once_with(skip_shops={'有鱼餐馆'})

    def test_start_that_did_not_take_stops_the_loop(self):
        # 选到了餐品，但确认后同一商店仍是蓝色（经营没有开始）：第二次进店时跳过该店，检查其他商店
        business = make_business(['blue', 'blue', 'blue'], selected=[2, 2, 2])
        business._run_remaining_shops = Mock()
        business._run_legacy_mode()
        business._confirm_business_start.assert_called_once()
        business._run_remaining_shops.assert_called_once_with(skip_shops={'有鱼餐馆'})

    def test_remaining_shops_scan_all_shops_and_skip_the_blocked_one(self):
        business = make_business([], selected=[])
        business.shops = [{'name': '有鱼餐馆'}, {'name': '白熊饮品'}]
        business._run_batch = Mock(return_value={'白熊饮品'})
        business._run_remaining_shops({'有鱼餐馆'})
        business._run_batch.assert_called_once_with(business.shops, skip_shops={'有鱼餐馆'}, final=True)
        business._trigger_shop_refill.assert_called_once_with({'白熊饮品'})
        # 其他商店开始了经营：延时由逐店扫描按经营时间设置，这里不改成 60 分钟
        business.config.task_delay.assert_not_called()

    def test_remaining_shops_retry_later_when_nothing_started(self):
        business = make_business([], selected=[])
        business.shops = [{'name': '有鱼餐馆'}]
        business._run_batch = Mock(return_value=set())
        business._run_remaining_shops({'有鱼餐馆'})
        business.config.task_delay.assert_called_once_with(minute=IslandBusiness.NO_FOOD_RETRY_MINUTES)

    def test_normal_start_still_exits_when_running(self):
        business = make_business(['blue', 'darkblue'], selected=[2])
        business._run_legacy_mode()
        business._confirm_business_start.assert_called_once()
        business._set_task_delay.assert_called_once()
        business.config.task_delay.assert_not_called()

    def test_shop_without_configured_products_keeps_old_behaviour(self):
        business = make_business(['blue', 'darkblue'], selected=[None])
        business._run_legacy_mode()
        business._confirm_business_start.assert_called_once()


class BatchNoFoodTest(unittest.TestCase):
    def test_process_shop_entry_reports_no_start(self):
        with patch.object(IslandBusiness, '__init__', lambda self: None):
            business = IslandBusiness()
        business._load_shop_characters = Mock()
        business._check_and_replace_boosted_product = Mock()
        business._select_business_characters = Mock()
        business._confirm_business_start = Mock()
        business._leave_shop_without_start = Mock()
        business.post_manage_mode = Mock()
        business.device = Mock()

        business._select_business_product = Mock(return_value=0)
        self.assertFalse(business._process_shop_entry({'name': '有鱼餐馆'}))
        business._confirm_business_start.assert_not_called()

        business._select_business_product = Mock(return_value=1)
        self.assertTrue(business._process_shop_entry({'name': '有鱼餐馆'}))
        business._confirm_business_start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
