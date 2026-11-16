"""Island Business: optionally fill empty shelves with other dishes in stock.

EN 2026-11-16 14:18: the Grill (silver, 2 shelves) was set to Steak Bowl + Double Energy Combo.
Double Energy Combo was at 0, so only Steak Bowl went on sale and one shelf stayed empty while the
Grill had The Carne-val 16, Crayfish Stir-Fry 15, Stir-Fried Chicken 7 and Coal-Roasted Skewer 6.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.island.island_business import IslandBusiness

GRILL = '乌鱼烤肉'
GRILL_DISHES = ['roasted_skewer', 'stir_fried_chicken', 'steak_bowl', 'crayfish_stir_fry', 'carnival',
                'double_energy']


def make_business(in_stock, fill=True, grade='silver', configured=('steak_bowl', 'double_energy')):
    with patch.object(IslandBusiness, '__init__', lambda self: None):
        business = IslandBusiness()
    data = {'IslandProductionPlanner': {'IslandProductionPlanner': {'GrillGrade': grade}}}
    business.config = SimpleNamespace(
        IslandBusiness_FillEmptySlots=fill,
        cross_get=lambda keys, default=None: data['IslandProductionPlanner']['IslandProductionPlanner'].get(
            keys.split('.')[-1], default),
    )
    business.device = Mock()
    business.shop_products = {GRILL: [{'name': name, 'button': Mock(file='x')} for name in GRILL_DISHES]}
    business.active_products = {GRILL: [p for p in business.shop_products[GRILL] if p['name'] in configured]}
    clicked = []

    def click(self, p):
        if p['name'] in in_stock:
            clicked.append(p['name'])
            return True
        return False

    return business, clicked, click


class FillEmptyShelvesTest(unittest.TestCase):
    def setUp(self):
        logger = patch('module.island.island_business.logger')
        logger.start()
        self.addCleanup(logger.stop)

    def run_select(self, business, click):
        with patch.object(IslandBusiness, '_click_business_product', click):
            return business._select_business_product(GRILL)

    def test_empty_shelf_gets_the_most_expensive_dish_in_stock(self):
        stock = {'steak_bowl', 'carnival', 'crayfish_stir_fry', 'stir_fried_chicken', 'roasted_skewer'}
        business, clicked, click = make_business(stock)
        self.assertEqual(self.run_select(business, click), 2)
        # planned dishes first, then The Carne-val (760) over Crayfish Stir-Fry (720)
        self.assertEqual(clicked, ['steak_bowl', 'carnival'])

    def test_option_off_keeps_the_old_behaviour(self):
        business, clicked, click = make_business({'steak_bowl', 'carnival'}, fill=False)
        self.assertEqual(self.run_select(business, click), 1)
        self.assertEqual(clicked, ['steak_bowl'])

    def test_full_shelves_add_nothing(self):
        business, clicked, click = make_business({'steak_bowl', 'double_energy', 'carnival'})
        self.assertEqual(self.run_select(business, click), 2)
        self.assertEqual(clicked, ['steak_bowl', 'double_energy'])

    def test_gold_shop_has_three_shelves(self):
        business, clicked, click = make_business({'steak_bowl', 'carnival', 'crayfish_stir_fry'}, grade='gold')
        self.assertEqual(self.run_select(business, click), 3)
        self.assertEqual(clicked, ['steak_bowl', 'carnival', 'crayfish_stir_fry'])

    def test_no_planned_dish_in_stock_still_opens_the_shop(self):
        # 07:40 the Grill didn't open at all ("no dishes to sell") although it had other dishes
        business, clicked, click = make_business({'carnival', 'roasted_skewer'})
        self.assertEqual(self.run_select(business, click), 2)
        self.assertEqual(clicked, ['carnival', 'roasted_skewer'])

    def test_unknown_grade_adds_nothing(self):
        business, clicked, click = make_business({'steak_bowl', 'carnival'}, grade=None)
        self.assertEqual(self.run_select(business, click), 1)

    def test_shelf_count_by_grade(self):
        business, _, _ = make_business(set())
        for grade, shelves in (('bronze', 2), ('silver', 2), ('gold', 3), ('diamond', 4)):
            business.config.cross_get = lambda keys, default=None, g=grade: g
            self.assertEqual(business._shop_shelf_count(GRILL), shelves)
        self.assertIsNone(business._shop_shelf_count('not a shop'))


if __name__ == '__main__':
    unittest.main()
