"""冬季季节物品、固定槽位、种子消耗与排产顺序。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import module.config.server as server

server.server = 'cn'

from module.island.island import Island  # noqa: E402
from module.island.island_business import IslandBusiness, SEASONAL_FOOD_MAP  # noqa: E402
from module.island.island_farm import (  # noqa: E402
    ISLAND_SELECT_PRODUCT_CHECK,
    MATERIAL_RESTOCKED,
    SELECT_SUGAR_TANGERINE,
    SELECT_SUGAR_TANGERINE_CHECK,
    IslandFarm,
)
from module.island.island_juu_eatery import (  # noqa: E402
    SELECT_SUGAR_TANGERINE_DAIFUKU,
    SELECT_SUGAR_TANGERINE_DAIFUKU_CHECK,
    SELECT_WATER_CHESTNUT_CAKE_CHECK,
    IslandJuuEatery,
)
from module.island.island_manufacture import (  # noqa: E402
    SELECT_PLUM_BLOSSOM_SACHET_CHECK,
    SELECT_WINTER_BOUQUET_CHECK,
    IslandManufacture,
)
from module.island.island_restaurant import (  # noqa: E402
    FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS,
    SELECT_GREEN_JUJUBE_PORRIDGE_CHECK,
    SELECT_SHIITAKE_CHICKEN_SOUP_CHECK,
    IslandRestaurant,
)
from module.island.island_season import SEASONAL_ITEMS, SeasonConfig  # noqa: E402
from module.island.island_shop_base import IslandShopBase  # noqa: E402
from module.island.island_teahouse import IslandTeahouse  # noqa: E402


RESTAURANT_SLOT_1 = FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS.button


def make_config(season='winter', seasonal=True):
    return SimpleNamespace(
        IslandRestaurant_ChefFilter='WorkerJuu',
        IslandTeahouse_ChefFilter='WorkerJuu',
        IslandJuuEatery_ChefFilter='WorkerJuu',
        IslandRestaurant_DoubleBambooShoots=seasonal,
        IslandTeahouse_Seasonal=seasonal,
        cross_get=Mock(return_value=season),
        task_delay=Mock(),
    )


def make_shop(shop_class, season='winter', products=(), seasonal=True):
    config = make_config(season, seasonal)

    def init_island(shop, config, device=None, task=None):
        shop.config = config
        shop.device = Mock()
        shop.unavailable_characters = set()

    with patch.object(Island, '__init__', init_island), patch(
        'module.island.island_shop_base.get_global_season_config',
        side_effect=SeasonConfig,
    ):
        shop = shop_class(config)
    shop.post_products = list(products)
    return shop


def make_farm(season='winter'):
    config = SimpleNamespace(
        IslandFarm_Positions=1,
        IslandOrchard_Positions=1,
        IslandNursery_Positions=1,
        IslandFarm_MinFarm=660,
        IslandOrchard_MinOrchard=300,
        IslandNursery_MinNursery=0,
        IslandFarm_CropTargets='',
        IslandOrchard_CropTargets='',
        IslandNursery_CropTargets='',
        IslandFarm_WorkerFilter='WorkerJuu',
        IslandOrchard_WorkerFilter='WorkerJuu',
        IslandNursery_WorkerFilter='WorkerJuu',
        IslandOrchard_IgnoreAvocado=True,
        IslandNursery_IgnorePineapple=True,
        IslandFarm_PlantPotatoes=0,
        IslandFarm_DefaultCrop='wheat',
        IslandOrchard_PlantRubber=0,
        IslandOrchard_DefaultCrop='rubber',
        IslandOrchard_AmagiChanRubber=False,
        IslandNursery_PlantLavender=0,
        IslandNursery_DefaultCrop='lavender',
        cross_get=Mock(return_value=season),
        task_delay=Mock(),
    )

    def init_island(farm, config, device=None, task=None):
        farm.config = config
        farm.device = Mock()

    with patch.object(Island, '__init__', init_island):
        return IslandFarm(config)


def make_manufacture(season='winter'):
    config = SimpleNamespace(
        WoodProcessing_Positions=0,
        ElectronicProcessing_Positions=0,
        Industrial_Positions=0,
        Handmade_Positions=1,
        cross_get=Mock(return_value=season),
    )

    def init_base(shop, config, device=None, task=None):
        shop.config = config
        shop.device = Mock()
        shop.posts = {}

    with patch.object(IslandShopBase, '__init__', init_base), patch(
        'module.island.island_shop_base.get_global_season_config',
        side_effect=SeasonConfig,
    ):
        return IslandManufacture(config)


def make_business(season='winter'):
    config = SimpleNamespace(
        IslandBusiness_BatchEnabled=False,
        IslandBusiness_Batch1Shops=[1],
        IslandBusiness_Batch2Shops=[],
        IslandBusiness_SeasonalReplaceEnabled=True,
        IslandBusiness_SeasonalThreshold=7,
        cross_get=Mock(return_value=season),
    )

    def init_island(business, config, device=None, task=None):
        business.config = config
        business.device = Mock()

    with patch.object(Island, '__init__', init_island):
        return IslandBusiness(config)


class WinterSeasonConfigTests(unittest.TestCase):
    def test_winter_item_groups(self):
        winter = SEASONAL_ITEMS['winter']
        self.assertEqual(
            winter['restaurant'],
            ['shiitake_chicken_soup', 'green_jujube_porridge'],
        )
        self.assertEqual(
            winter['juu_eatery'],
            ['water_chestnut_cake', 'sugar_tangerine_daifuku'],
        )
        self.assertEqual(winter['orchard'], ['sugar_tangerine', 'green_jujube'])
        self.assertEqual(
            winter['handmade'],
            ['plum_blossom_sachet', 'winter_bouquet'],
        )
        self.assertEqual(winter['teahouse'], [])

    def test_business_winter_primary_meal(self):
        self.assertEqual(
            SEASONAL_FOOD_MAP['winter']['product_name'],
            'shiitake_chicken_soup',
        )


class WinterRestaurantTests(unittest.TestCase):
    def test_winter_high_priority_uses_slot_one(self):
        shop = make_shop(IslandRestaurant)
        self.assertEqual(
            shop.seasonal_dish_slot['name'],
            'shiitake_chicken_soup',
        )
        self.assertEqual(shop.seasonal_dish_slot['selection'].button, RESTAURANT_SLOT_1)
        self.assertEqual(shop.get_priority_production()['shiitake_chicken_soup'], 7)

        selection = shop.name_to_config['shiitake_chicken_soup']['selection']
        self.assertTrue(shop.select_product(selection, selection))
        self.assertEqual(shop.device.click.call_args.args[0].button, RESTAURANT_SLOT_1)

    def test_jujube_porridge_uses_slot_two(self):
        shop = make_shop(IslandRestaurant)
        config = shop.name_to_config['green_jujube_porridge']
        self.assertEqual(config['selection'].button, (230, 291, 267, 358))
        self.assertIs(config['selection_check'], SELECT_GREEN_JUJUBE_PORRIDGE_CHECK)
        self.assertIs(
            shop.name_to_config['shiitake_chicken_soup']['selection_check'],
            SELECT_SHIITAKE_CHICKEN_SOUP_CHECK,
        )

    def test_restaurant_switches_back_to_summer_slots(self):
        spring_products = [('double_bamboo_shoots', 3), ('asparagus_shrimp', 4)]
        winter = make_shop(IslandRestaurant, 'winter', spring_products)
        winter._auto_switch_seasonal_meals()
        self.assertEqual(
            winter.post_products,
            [('shiitake_chicken_soup', 3), ('green_jujube_porridge', 4)],
        )

        summer = make_shop(IslandRestaurant, 'summer', spring_products)
        summer._auto_switch_seasonal_meals()
        self.assertEqual(
            summer.post_products,
            [('amaranth_rice_ball', 3), ('tomato_egg', 4)],
        )
        self.assertEqual(summer.seasonal_dish_slot['selection'].button, RESTAURANT_SLOT_1)

    def test_summer_switches_winter_meals_to_current_slots(self):
        shop = make_shop(
            IslandRestaurant,
            'summer',
            [('shiitake_chicken_soup', 3), ('green_jujube_porridge', 4)],
        )
        shop._auto_switch_seasonal_meals()
        self.assertEqual(
            shop.post_products,
            [('amaranth_rice_ball', 3), ('tomato_egg', 4)],
        )

    def test_teahouse_switches_back_to_summer_first_slot(self):
        shop = make_shop(
            IslandTeahouse,
            'summer',
            [('spring_flower_tea', 3), ('pineapple_juice', 4)],
        )
        shop._auto_switch_seasonal_meals()
        self.assertEqual(
            shop.post_products,
            [('watermelon_juice', 3), ('cucumber_juice', 4)],
        )
        self.assertEqual(
            shop.seasonal_high_priority_drink['selection'].button,
            (212, 143, 292, 211),
        )


class WinterJuuEateryTests(unittest.TestCase):
    def test_winter_items_and_fixed_second_slot(self):
        shop = make_shop(IslandJuuEatery)
        names = {item['name'] for item in shop.shop_items}
        self.assertIn('water_chestnut_cake', names)
        self.assertIn('sugar_tangerine_daifuku', names)

        selection = shop.name_to_config['sugar_tangerine_daifuku']['selection']
        self.assertEqual(selection.button, SELECT_SUGAR_TANGERINE_DAIFUKU.button)
        self.assertIs(
            shop.name_to_config['sugar_tangerine_daifuku']['selection_check'],
            SELECT_SUGAR_TANGERINE_DAIFUKU_CHECK,
        )
        self.assertIs(
            shop.name_to_config['water_chestnut_cake']['selection_check'],
            SELECT_WATER_CHESTNUT_CAKE_CHECK,
        )

    def test_winter_items_absent_in_summer(self):
        shop = make_shop(IslandJuuEatery, season='summer')
        names = {item['name'] for item in shop.shop_items}
        self.assertNotIn('water_chestnut_cake', names)
        self.assertNotIn('sugar_tangerine_daifuku', names)

    def test_offseason_winter_demands_are_removed(self):
        shop = make_shop(IslandJuuEatery, season='summer')
        shop.post_products = [
            ('apple_pie', 2),
            ('water_chestnut_cake', 3),
            ('sugar_tangerine_daifuku', 4),
        ]
        shop._normalize_seasonal_post_products('juu_eatery')
        self.assertEqual(shop.post_products, [('apple_pie', 2)])


class WinterOrchardTests(unittest.TestCase):
    def test_seed_counts_and_season_filter(self):
        farm = make_farm()
        items = {item['name']: item for item in farm.INVENTORY_CONFIG['orchard']['items']}
        for crop in ('pear', 'persimmon'):
            self.assertEqual(items[crop]['seed_number'], 4)
            self.assertTrue(items[crop]['batch_4x1'])
        for crop in ('sugar_tangerine', 'green_jujube'):
            self.assertEqual(items[crop]['seed_number'], 16)
            self.assertNotIn('batch_4x1', items[crop])
            self.assertTrue(farm._is_orchard_crop_in_season(crop))
        self.assertFalse(farm._is_orchard_crop_in_season('pear'))
        self.assertFalse(farm._is_orchard_crop_in_season('persimmon'))

    def test_sugar_tangerine_uses_check_template(self):
        farm = make_farm()
        config = farm.name_to_config['sugar_tangerine']
        self.assertIs(config['selection'], SELECT_SUGAR_TANGERINE)
        self.assertIs(config['selection_check'], SELECT_SUGAR_TANGERINE_CHECK)

    def test_default_crop_falls_back_when_out_of_season(self):
        summer = make_farm(season='summer')
        summer.plant_config['orchard']['default_crop'] = 'sugar_tangerine'
        self.assertEqual(summer._resolve_default_crop('orchard'), 'rubber')

        winter = make_farm(season='winter')
        winter.plant_config['orchard']['default_crop'] = 'sugar_tangerine'
        self.assertEqual(winter._resolve_default_crop('orchard'), 'sugar_tangerine')

    def test_plant_flow_uses_4x1_and_4x4_seed_requirements(self):
        expected = {'pear': 4, 'sugar_tangerine': 16}
        for crop, seed_count in expected.items():
            with self.subTest(crop=crop):
                farm = make_farm(season='autumn' if crop == 'pear' else 'winter')
                farm.post_close = Mock()
                farm.post_open = Mock(return_value=True)
                farm.loop = Mock(return_value=iter([0]))
                farm.appear_then_click = Mock(return_value=False)
                farm.appear = Mock(
                    side_effect=lambda button, **kwargs: button is ISLAND_SELECT_PRODUCT_CHECK
                )
                farm.select_product = Mock(return_value=True)
                farm.ensure_select_product_material = Mock(return_value=MATERIAL_RESTOCKED)
                farm.back_to_postmanage_from_dispatch = Mock()

                farm.post_plant(Mock(), crop, 'orchard', 'time_orchard')

                self.assertEqual(
                    farm.ensure_select_product_material.call_args.kwargs['required_quantity'],
                    seed_count,
                )


class WinterManufactureTests(unittest.TestCase):
    def test_winter_items_are_added_before_boots_and_leather(self):
        factory = make_manufacture()
        names = [item['name'] for item in factory.manufacture['handmade']['items']]
        self.assertIn('plum_blossom_sachet', names)
        self.assertIn('winter_bouquet', names)

        factory.get_idle_posts_by_category = Mock(return_value=['ISLAND_HANDMADE_POST1'])
        factory.select_product_with_material_check = Mock()
        factory.warehouse_counts = {'leather': 10}
        factory.schedule_handmade()
        items = {item['name']: item for item in factory.manufacture['handmade']['items']}
        self.assertIs(items['plum_blossom_sachet']['selection_check'], SELECT_PLUM_BLOSSOM_SACHET_CHECK)
        self.assertIs(items['winter_bouquet']['selection_check'], SELECT_WINTER_BOUQUET_CHECK)
        ordered = [
            item['name']
            for item in factory.select_product_with_material_check.call_args.args[1]
        ]
        self.assertEqual(
            ordered,
            ['plum_blossom_sachet', 'winter_bouquet', 'boot', 'leather'],
        )


class WinterBusinessTests(unittest.TestCase):
    def test_new_products_and_warehouse_templates_are_registered(self):
        business = make_business()
        restaurant = {item['name'] for item in business.shop_products['有鱼餐馆']}
        eatery = {item['name'] for item in business.shop_products['啾啾简餐']}
        self.assertTrue({'shiitake_chicken_soup', 'green_jujube_porridge'} <= restaurant)
        self.assertTrue({'water_chestnut_cake', 'sugar_tangerine_daifuku'} <= eatery)
        for product in ('shiitake_chicken_soup', 'green_jujube_porridge'):
            self.assertIsNotNone(business._get_seasonal_warehouse_template(product))

    def test_winter_product_selection_templates_exist(self):
        business = make_business()
        for shop_name, product_names in {
            '有鱼餐馆': ('shiitake_chicken_soup', 'green_jujube_porridge'),
            '啾啾简餐': ('water_chestnut_cake', 'sugar_tangerine_daifuku'),
        }.items():
            products = {item['name']: item['button'] for item in business.shop_products[shop_name]}
            for product_name in product_names:
                image_path = Path(products[product_name].file)
                self.assertTrue(image_path.is_file(), image_path)


class WinterPlannerDataTests(unittest.TestCase):
    def test_winter_items_and_recipes_are_planned(self):
        from module.island_planner import settings_map as sm
        from module.island_planner.data import (
            DIC_ISLAND_ITEM,
            DIC_ISLAND_RECIPE,
            DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE,
        )

        # 物品与配方 ID 取自游戏数据（ALAS 9485310，已与国际服 sharecfg 原表核对）
        winter_dishes = {
            'shiitake_chicken_soup': 4051,
            'green_jujube_porridge': 4052,
            'water_chestnut_cake': 4053,
            'sugar_tangerine_daifuku': 4054,
        }
        for name, item_id in winter_dishes.items():
            self.assertEqual(sm.DISH_ITEM_IDS[name], item_id)
            self.assertIn(item_id, DIC_ISLAND_ITEM)

        self.assertEqual(sm.CROP_ITEM_IDS['orchard']['sugar_tangerine'], 4047)
        self.assertEqual(sm.CROP_ITEM_IDS['orchard']['green_jujube'], 4049)
        self.assertEqual(DIC_ISLAND_RECIPE[9900025]['commission_cost'], {4048: 4})
        self.assertEqual(DIC_ISLAND_RECIPE[9900025]['commission_product'], {4047: 8})
        self.assertEqual(DIC_ISLAND_RECIPE[9900026]['commission_product'], {4049: 12})
        self.assertEqual(DIC_ISLAND_RECIPE[9900027]['commission_cost'], {4045: 2, 2602: 1})
        self.assertEqual(DIC_ISLAND_RECIPE[9900028]['commission_cost'], {4049: 2, 2002: 5})
        self.assertEqual(DIC_ISLAND_RECIPE[9900029]['commission_cost'], {4046: 2})
        self.assertEqual(DIC_ISLAND_RECIPE[9900030]['commission_cost'], {4047: 2, 3004: 3})
        self.assertEqual(DIC_ISLAND_RECIPE[9900031]['commission_cost'], {4043: 3})
        self.assertEqual(DIC_ISLAND_RECIPE[9900032]['commission_cost'], {4043: 1, 4044: 4})

        self.assertEqual(DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE[601][4051], 9900027)
        self.assertEqual(DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE[603][4054], 9900030)
        self.assertTrue({4055, 4056} <= sm.MANUFACTURE_LINES['manufacturing_crafts'][1])

    def test_winter_recipes_follow_the_season(self):
        """冬季配方只在第 5 季可用，秋季（第 4 季）不可用。"""
        from module.island_planner.calculator import ProductionPlanCalculator
        from module.island_planner.data import DIC_ISLAND_SEASON

        orchard = {330101: True}  # 果园第一个岗位
        winter = ProductionPlanCalculator(orchard, activity_list=DIC_ISLAND_SEASON[5]['activity'])
        autumn = ProductionPlanCalculator(orchard, activity_list=DIC_ISLAND_SEASON[4]['activity'])
        no_season = ProductionPlanCalculator(orchard, activity_list=None)
        for recipe_id in (9900025, 9900026):
            self.assertTrue(winter.recipe_available[recipe_id])
            self.assertFalse(autumn.recipe_available[recipe_id])
            self.assertFalse(no_season.recipe_available[recipe_id])
            self.assertEqual(winter.recipe_group[recipe_id], 'orchard')


if __name__ == '__main__':
    unittest.main()
