"""用真实渔场排产、补购和需求扣减，配合假 UI 检查鱼苗数量。"""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.island.island import Island, ISLAND_SELECT_PRODUCT_CHECK
from module.island.island_fishery import IslandFishery


NOW = datetime(2026, 9, 20, 12)


class FisheryUI:
    def __init__(self, demand=None, fry_stock=None, positions=3, default_posts=0, working=None):
        config = SimpleNamespace(
            IslandFishery_Positions=positions, IslandFishery_PlantYellowfinTuna=default_posts,
            IslandFishery_RancherFilter='WorkerJuu', task_delay=Mock(),
        )
        for name in ('Bass', 'YellowfinTuna', 'Shell', 'Shrimp', 'Crab', 'Crayfish', 'Squid', 'SeaCucumber',
                     'KoiCarp', 'Mackerel'):
            setattr(config, 'IslandFishery_Min' + name, 0)

        def init_island(fishery, config):
            fishery.config = config
            fishery.device = Mock()

        with patch.object(Island, '__init__', init_island):
            self.fishery = IslandFishery(config)
        fishery = self.fishery
        for product, quantity in (demand or {}).items():
            fishery.fishery_threshold[product] = quantity * fishery.name_to_config[product]['yield']
        self.stock = dict(fry_stock or {})
        self.working = dict(working or {})
        self.buys = []
        self.orders = []
        self.targets = []
        self.limits = {}
        self.failed_posts = set()
        self.buy_limit = None
        self.buy_success = True
        self.current_product = None
        self.current_post = None
        self.actual_runs = 0
        fishery.warehouse_inventory = Mock(return_value={})
        fishery.decided_lists = self.scan_post
        for name in ('goto_postmanage', 'post_manage_mode', 'post_close',
                     'back_to_postmanage_from_dispatch', 'back_to_select_product_after_shop'):
            setattr(fishery, name, Mock())
        fishery.post_open = self.open_post
        fishery.loop = Mock(side_effect=lambda **kwargs: iter(range(10)))
        fishery.appear = lambda button, **kwargs: button is ISLAND_SELECT_PRODUCT_CHECK
        fishery.appear_then_click = Mock(return_value=False)
        fishery.select_product = self.select_product
        fishery.ocr_select_product_material_detail = self.read_material
        fishery.goto_shop_from_select_product = Mock(return_value=True)
        fishery.buy_shop_item = self.buy
        fishery.confirm_post_add_order = self.confirm

    def scan_post(self, button, post_id, index):
        post = self.fishery.posts[post_id]
        if index in self.working:
            product, number = self.working[index]
            post.update(state='working', crop=product, runs=number)
            self.fishery.fishery_times[index] = NOW + timedelta(hours=2)
        else:
            post.update(state='idle', crop=None, runs=0)
        return False

    def open_post(self, button):
        self.current_post = next(index for index, post in enumerate(self.fishery.posts.values())
                                 if post['button'] is button)

    def select_product(self, selection, selection_check):
        self.current_product = next(item['name'] for item in self.fishery.FISHERY_ITEMS
                                    if item['selection'] is selection)
        return True

    def read_material(self, expected_quantity):
        quantity = self.stock.get(self.current_product, 0)
        self.target_quantity = expected_quantity
        return quantity, f'{quantity}/1'

    def buy(self, quantity, **kwargs):
        if not self.buy_success:
            return False
        quantity = quantity if self.buy_limit is None else min(quantity, self.buy_limit)
        self.buys.append((self.current_product, quantity))
        self.stock[self.current_product] = self.stock.get(self.current_product, 0) + quantity
        return True

    def confirm(self, context):
        self.targets.append((self.current_product, self.target_quantity))
        if self.current_post in self.failed_posts:
            return False
        capacity = self.fishery.name_to_config[self.current_product]['buy_max'] + 1
        self.actual_runs = min(capacity, self.stock[self.current_product],
                               self.limits.get(self.current_post, capacity))
        self.stock[self.current_product] -= self.actual_runs
        self.orders.append((self.current_product, self.actual_runs))
        return True

    def run(self):
        with patch('module.island.island_fishery.Digit') as digit, \
                patch('module.island.island_fishery.Duration') as duration, \
                patch('module.island.island_fishery.current_time', return_value=NOW):
            digit.return_value.ocr.side_effect = lambda image: self.actual_runs
            duration.return_value.ocr.return_value = timedelta(hours=1)
            self.fishery.run()


class IslandFisheryQuantityTests(unittest.TestCase):
    def setUp(self):
        for module in ('module.island.island_fishery', 'module.island.island'):
            logger_patch = patch(module + '.logger')
            logger_patch.start()
            self.addCleanup(logger_patch.stop)

    def test_capacity_boundary_uses_existing_fry_and_buys_only_difference(self):
        for product, capacity in (('bass', 5), ('shrimp', 8)):
            for stock in (0, 1, capacity, capacity + 2):
                with self.subTest(product=product, stock=stock):
                    ui = FisheryUI({product: capacity}, {product: stock}, positions=1)
                    ui.run()
                    self.assertEqual(ui.targets, [(product, capacity)])
                    self.assertEqual(ui.orders, [(product, capacity)])
                    self.assertEqual(sum(quantity for _, quantity in ui.buys), max(0, capacity - stock))
                    self.assertEqual(ui.fishery.to_plant_list, [])

    def test_multiple_posts_target_exact_remaining_demand(self):
        for demand, quantities in ((1, [1]), (6, [5, 1]), (10, [5, 5]), (11, [5, 5, 1]),
                                   (16, [5, 5, 5])):
            with self.subTest(demand=demand):
                ui = FisheryUI({'bass': demand})
                ui.run()
                self.assertEqual(ui.orders, [('bass', quantity) for quantity in quantities])
                self.assertEqual(ui.fishery.to_plant_list, ['bass'] * max(0, demand - 15))

    def test_round_robin_product_priority_is_preserved(self):
        ui = FisheryUI({'bass': 6, 'shrimp': 9})
        ui.run()
        self.assertEqual(ui.orders, [('bass', 5), ('shrimp', 8), ('bass', 1)])
        self.assertEqual(ui.fishery.to_plant_list, ['shrimp'])

    def test_default_posts_remain_full_after_small_supply_order(self):
        ui = FisheryUI({'yellowfin_tuna': 1}, default_posts=2)
        ui.run()
        self.assertEqual(ui.orders, [('yellowfin_tuna', 1), ('yellowfin_tuna', 5), ('yellowfin_tuna', 5)])

    def test_working_fry_reduce_demand_and_count_toward_default_posts(self):
        ui = FisheryUI({'yellowfin_tuna': 6}, default_posts=1,
                       working={0: ('yellowfin_tuna', 5)})
        ui.run()
        self.assertEqual(ui.orders, [('yellowfin_tuna', 1)])
        self.assertEqual(ui.fishery.to_plant_list, [])

    def test_partial_dispatch_recomputes_next_target_using_actual_runs(self):
        ui = FisheryUI({'bass': 6}, positions=2)
        ui.limits[0] = 3
        ui.run()
        self.assertEqual(ui.targets, [('bass', 5), ('bass', 3)])
        self.assertEqual(ui.orders, [('bass', 3), ('bass', 3)])
        self.assertEqual(ui.buys, [('bass', 5), ('bass', 1)])
        self.assertEqual(ui.fishery.to_plant_list, [])

    def test_failed_dispatch_preserves_demand_for_next_post(self):
        ui = FisheryUI({'bass': 6}, positions=2)
        ui.failed_posts.add(0)
        ui.run()
        self.assertEqual(ui.targets, [('bass', 5), ('bass', 5)])
        self.assertEqual(ui.orders, [('bass', 5)])
        self.assertEqual(ui.buys, [('bass', 5)])
        self.assertEqual(ui.fishery.to_plant_list, ['bass'])

    def test_partial_purchase_rechecks_stock_until_target_is_met(self):
        ui = FisheryUI({'bass': 5}, positions=1)
        ui.buy_limit = 2
        ui.run()
        self.assertEqual(ui.buys, [('bass', 2), ('bass', 2), ('bass', 1)])
        self.assertEqual(ui.orders, [('bass', 5)])

    def test_failed_purchase_never_confirms_or_reduces_demand(self):
        ui = FisheryUI({'bass': 5}, positions=1)
        ui.buy_success = False
        ui.run()
        self.assertEqual(ui.targets, [])
        self.assertEqual(ui.orders, [])
        self.assertEqual(ui.fishery.to_plant_list, ['bass'] * 5)
        self.assertEqual(ui.fishery.posts['ISLAND_FISHERY_POST1']['state'], 'idle')


if __name__ == '__main__':
    unittest.main()
