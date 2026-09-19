"""岛屿餐厅模块。

继承 IslandShopBase，实现餐厅的菜品配置、季节性菜品管理与岗位运营。
包含凉拌双笋、芦笋炒虾仁等时令菜品定义，支持固定位置按钮与菜品种类统计。
"""
from module.island_restaurant.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.logger import logger

from module.base.button import Button
from module.island.island_season import SEASONAL_ITEMS


# 固定位置按钮 — 在委派界面不滑动时，双笋的固定位置
FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS = Button(
    area=(), color=(), button=(212, 143, 292, 211),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

# 秋季高优先级菜品（松茸鸡汤，槽位2）的固定位置——固定第二格，
# 与春/夏季高优先级菜品（凉拌双笋/苋菜饭团）所在格不同
FIXED_SELECT_MATSUTAKE_CHICKEN_SOUP = Button(
    area=(), color=(), button=(212, 300, 292, 360),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

RESTAURANT_SEASONAL_DISHES = {
    'double_bamboo_shoots': {
        'name': 'double_bamboo_shoots', 'template': TEMPLATE_DOUBLE_BAMBOO_SHOOTS,
        'selection': SELECT_DOUBLE_BAMBOO_SHOOTS, 'selection_check': SELECT_DOUBLE_BAMBOO_SHOOTS_CHECK,
        'post_action': POST_DOUBLE_BAMBOO_SHOOTS, 'cn_name': '凉拌双笋'
    },
    'asparagus_shrimp': {
        'name': 'asparagus_shrimp', 'template': TEMPLATE_ASPARAGUS_SHRIMP,
        'selection': SELECT_ASPARAGUS_SHRIMP, 'selection_check': SELECT_ASPARAGUS_SHRIMP_CHECK,
        'post_action': POST_ASPARAGUS_SHRIMP, 'cn_name': '芦笋炒虾仁'
    },
    'amaranth_rice_ball': {
        'name': 'amaranth_rice_ball', 'template': TEMPLATE_AMARANTH_RICE_BALL,
        'selection': SELECT_AMARANTH_RICE_BALL, 'selection_check': SELECT_AMARANTH_RICE_BALL_CHECK,
        'post_action': POST_AMARANTH_RICE_BALL, 'cn_name': '苋菜饭团'
    },
    'tomato_egg': {
        'name': 'tomato_egg', 'template': TEMPLATE_TOMATO_EGG,
        'selection': SELECT_TOMATO_EGG, 'selection_check': SELECT_TOMATO_EGG_CHECK,
        'post_action': POST_TOMATO_EGG, 'cn_name': '番茄炒蛋'
    },
    'matsutake_chicken_soup': {
        'name': 'matsutake_chicken_soup', 'template': TEMPLATE_MATSUTAKE_CHICKEN_SOUP,
        'selection': SELECT_MATSUTAKE_CHICKEN_SOUP, 'selection_check': SELECT_MATSUTAKE_CHICKEN_SOUP_CHECK,
        'post_action': POST_MATSUTAKE_CHICKEN_SOUP, 'cn_name': '松茸鸡汤'
    },
    'persimmon_cake': {
        'name': 'persimmon_cake', 'template': TEMPLATE_PERSIMMON_CAKE,
        'selection': SELECT_PERSIMMON_CAKE, 'selection_check': SELECT_PERSIMMON_CAKE_CHECK,
        'post_action': POST_PERSIMMON_CAKE, 'cn_name': '柿子饼'
    },
}

HIGH_PRIORITY_SEASONAL_DISHES = {
    name: {
        **RESTAURANT_SEASONAL_DISHES[name],
        'selection': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS,
        'selection_check': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS,
    }
    for name in ('double_bamboo_shoots', 'amaranth_rice_ball')
}
# 秋季高优先级为松茸鸡汤，位于固定第二格（与春/夏季高优先级菜品不同格）
HIGH_PRIORITY_SEASONAL_DISHES['matsutake_chicken_soup'] = {
    **RESTAURANT_SEASONAL_DISHES['matsutake_chicken_soup'],
    'selection': FIXED_SELECT_MATSUTAKE_CHICKEN_SOUP,
    'selection_check': FIXED_SELECT_MATSUTAKE_CHICKEN_SOUP,
}


class IslandRestaurant(IslandShopBase):
    # 季节菜品只在优先阶段生产，余岗仅安排用户配置的常驻餐品。
    FILL_SPECIAL_FOOD = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 设置店铺类型
        self.shop_type = "restaurant"
        self.time_prefix = "time_restaurant"
        self.chef_config = self.config.IslandRestaurant_ChefFilter

        # === 初始化全局季节配置 ===
        self._init_season_config()

        # === 高优先级季节菜品映射 ===
        self.seasonal_dish_slot = self._get_high_priority_seasonal_dish()

        if self.seasonal_dish_slot:
            logger.info(f"[岛屿-有鱼餐馆] 高优先级季节菜品: {self.seasonal_dish_slot['cn_name']}")

        # 设置商品列表（根据季节自动选择对应菜品）
        self.shop_items = self._get_current_seasonal_shop_items()
        # ---- 常规菜品 ----
        self.shop_items.extend([
            {'name': 'tofu', 'template': TEMPLATE_TOFU, 'var_name': 'tofu',
             'selection': SELECT_TOFU, 'selection_check': SELECT_TOFU_CHECK,
             'post_action': POST_TOFU},
            {'name': 'omurice', 'template': TEMPLATE_OMURICE, 'var_name': 'omurice',
             'selection': SELECT_OMURICE, 'selection_check': SELECT_OMURICE_CHECK,
             'post_action': POST_OMURICE},
            {'name': 'cabbage_tofu', 'template': TEMPLATE_CABBAGE_TOFU, 'var_name': 'cabbage_tofu',
             'selection': SELECT_CABBAGE_TOFU, 'selection_check': SELECT_CABBAGE_TOFU_CHECK,
             'post_action': POST_CABBAGE_TOFU},
            {'name': 'salad', 'template': TEMPLATE_SALAD, 'var_name': 'salad',
             'selection': SELECT_SALAD, 'selection_check': SELECT_SALAD_CHECK,
             'post_action': POST_SALAD},
            {'name': 'tofu_meat', 'template': TEMPLATE_TOFU_MEAT, 'var_name': 'tofu_meat',
             'selection': SELECT_TOFU_MEAT, 'selection_check': SELECT_TOFU_MEAT_CHECK,
             'post_action': POST_TOFU_MEAT},
            {'name': 'tofu_combo', 'template': TEMPLATE_TOFU_COMBO, 'var_name': 'tofu_combo',
             'selection': SELECT_TOFU_COMBO, 'selection_check': SELECT_TOFU_COMBO_CHECK,
             'post_action': POST_TOFU_COMBO},
            {'name': 'hearty_meal', 'template': TEMPLATE_HEARTY_MEAL, 'var_name': 'hearty_meal',
             'selection': SELECT_HEARTY_MEAL, 'selection_check': SELECT_HEARTY_MEAL_CHECK,
             'post_action': POST_HEARTY_MEAL},
            {'name': 'fish_chip', 'template': TEMPLATE_FISH_CHIP, 'var_name': 'fish_chip',
             'selection': SELECT_FISH_CHIP, 'selection_check': SELECT_FISH_CHIP_CHECK,
             'post_action': POST_FISH_CHIP},
            {'name': 'fo_tiao', 'template': TEMPLATE_FO_TIAO, 'var_name': 'fo_tiao',
             'selection': SELECT_FO_TIAO, 'selection_check': SELECT_FO_TIAO_CHECK,
             'post_action': POST_FO_TIAO},
            {'name': 'onion_fish', 'template': TEMPLATE_ONION_FISH, 'var_name': 'onion_fish',
             'selection': SELECT_ONION_FISH, 'selection_check': SELECT_ONION_FISH_CHECK,
             'post_action': POST_ONION_FISH},
        ])

        # 设置套餐组成
        self.meal_compositions = {
            'hearty_meal': {
                'required': ['tofu', 'omurice'],
                'quantity_per': 1
            },
            'tofu_combo': {
                'required': ['cabbage_tofu', 'tofu_meat'],
                'quantity_per': 1
            }
        }

        # 特殊材料：豆腐（用于特殊餐品制作）
        self.special_materials = {}

        # 设置岗位按钮
        self.post_buttons = {
            'ISLAND_RESTAURANT_POST1': ISLAND_RESTAURANT_POST1,
            'ISLAND_RESTAURANT_POST2': ISLAND_RESTAURANT_POST2
        }

        # 设置筛选资产
        self.filter_asset = 'restaurant'

        # 设置配置前缀
        self.setup_config(
            config_meal_prefix="IslandRestaurant_Meal",
            config_number_prefix="IslandRestaurant_MealNumber",
            config_away_cook="IslandRestaurantNextTask_AwayCook",
            config_post_number="IslandRestaurant_PostNumber"
        )

        # === 季节餐品自动切换 ===
        # 若用户在 Meal1~Meal8 中配置了 spring 限定餐品（double_bamboo_shoots / asparagus_shrimp），
        # 但当前季节不是 spring，则自动替换为当前季节对应槽位的餐品
        self._auto_switch_seasonal_meals()

        # 初始化店铺
        self.initialize_shop()

    def _is_seasonal_priority_enabled(self):
        return getattr(self.config, 'IslandRestaurant_DoubleBambooShoots', False)

    def _get_current_seasonal_shop_items(self):
        if not hasattr(self, 'season_config') or not self.season_config:
            return []

        seasonal_items = self.season_config.get_seasonal_items('restaurant') or []
        result = []
        for item_name in seasonal_items:
            dish = RESTAURANT_SEASONAL_DISHES.get(item_name)
            if dish:
                result.append(dish.copy())
        return result

    def _get_high_priority_seasonal_dish(self):
        if not self._is_seasonal_priority_enabled():
            return None
        if not hasattr(self, 'season_config') or not self.season_config:
            return None

        seasonal_items = self.season_config.get_seasonal_items('restaurant') or []
        for item_name in seasonal_items:
            dish = HIGH_PRIORITY_SEASONAL_DISHES.get(item_name)
            if dish:
                return dish.copy()
        return None

    def _auto_switch_seasonal_meals(self):
        """
        自动切换用户配置中的春季限定餐品到当前季节对应餐品。
        """
        SEASONAL_MEAL_SWITCH = {
            'double_bamboo_shoots': 0,
            'asparagus_shrimp': 1,
        }
        if not hasattr(self, 'season_config') or not self.season_config:
            return
        current_season = self.season_config.season
        current_restaurant_items = SEASONAL_ITEMS.get(current_season, {}).get('restaurant', [])
        for spring_item, slot_idx in SEASONAL_MEAL_SWITCH.items():
            if not any(name == spring_item for name, _ in self.post_products):
                continue
            spring_name = '凉拌双笋' if spring_item == 'double_bamboo_shoots' else '芦笋炒虾仁'
            if slot_idx < len(current_restaurant_items):
                seasonal_item = current_restaurant_items[slot_idx]
                if seasonal_item != spring_item:
                    self.post_products = [
                        (seasonal_item, target) if name == spring_item else (name, target)
                        for name, target in self.post_products
                    ]
                    logger.info(
                        f"季节餐品自动切换: {self._item_cn(spring_item)}({spring_name}) -> {self._item_cn(seasonal_item)}"
                        f"（当前季节: {self.season_config.season_name}）"
                    )
            else:
                self.post_products = [
                    (name, target) for name, target in self.post_products
                    if name != spring_item
                ]
                logger.info(
                    f"季节餐品自动移除: {self._item_cn(spring_item)}({spring_name})"
                    f"（{self.season_config.season_name} 无对应槽位的季节餐品）"
                )

    def select_product(self, product_selection, product_selection_check):
        """
        覆盖父类 select_product：
        高优先级季节菜品使用固定坐标点击，不进行模板匹配和滑动。
        其他餐品走父类逻辑。
        """
        if self.seasonal_dish_slot:
            dish_name = self.seasonal_dish_slot['name']
            fixed_selection = self.seasonal_dish_slot['selection']
            normal_selection = self.name_to_config.get(dish_name, {}).get('selection')
            if product_selection in (fixed_selection, normal_selection):
                self.device.click(self.seasonal_dish_slot['selection'])
                self.device.sleep(0.5)
                return True
        return super().select_product(product_selection, product_selection_check)

    def check_special_materials(self, product, batch_size):
        """覆盖：检查特殊材料（豆腐）限制"""
        if batch_size <= 0:
            return 0

        # cabbage_tofu需要1个豆腐
        if product == 'cabbage_tofu':
            tofu_needed_per_batch = 1
            tofu_available = self.warehouse_counts.get('tofu', 0)
            max_by_tofu = tofu_available // tofu_needed_per_batch
            return min(batch_size, max_by_tofu)

        # tofu_meat需要2个豆腐
        if product == 'tofu_meat':
            tofu_needed_per_batch = 2
            tofu_available = self.warehouse_counts.get('tofu', 0)
            max_by_tofu = tofu_available // tofu_needed_per_batch
            return min(batch_size, max_by_tofu)

        return batch_size

    def deduct_materials(self, product, number):
        """覆盖：扣除前置材料，包括豆腐"""
        # 先调用父类方法扣除套餐原材料
        super().deduct_materials(product, number)

        # cabbage_tofu需要扣除豆腐
        if product == 'cabbage_tofu':
            tofu_needed = number * 1
            if 'tofu' in self.warehouse_counts:
                self.warehouse_counts['tofu'] -= tofu_needed
                logger.info(f"[岛屿-有鱼餐馆] 扣除豆腐：{self._item_cn('tofu')} -{tofu_needed} (用于制作 {self._item_cn(product)})")

        # tofu_meat需要扣除豆腐
        if product == 'tofu_meat':
            tofu_needed = number * 2
            if 'tofu' in self.warehouse_counts:
                self.warehouse_counts['tofu'] -= tofu_needed
                logger.info(f"[岛屿-有鱼餐馆] 扣除豆腐：{self._item_cn('tofu')} -{tofu_needed} (用于制作 {self._item_cn(product)})")

    def apply_special_material_constraints(self, requirements):
        """覆盖：根据豆腐库存调整需求，豆腐不足时自动补入生产计划"""
        result = requirements.copy()

        # 获取豆腐库存
        tofu_stock = self.warehouse_counts.get('tofu', 0)

        # 处理cabbage_tofu的需求
        if 'cabbage_tofu' in result and result['cabbage_tofu'] > 0:
            cabbage_needed = result['cabbage_tofu']
            tofu_needed = cabbage_needed * 1  # 每个cabbage_tofu需要1个豆腐

            if tofu_stock < tofu_needed:
                max_cabbage = tofu_stock // 1
                deficit = cabbage_needed - max_cabbage
                result['cabbage_tofu'] = max_cabbage
                # 豆腐本店可生产，限产的同时补入豆腐需求
                if 'tofu' in self.name_to_config:
                    result['tofu'] = result.get('tofu', 0) + deficit
                    logger.info(f"[岛屿-有鱼餐馆] 豆腐不足：{self._item_cn('cabbage_tofu')} {cabbage_needed}→{max_cabbage}，补入 {self._item_cn('tofu')} x{deficit}")
                tofu_stock -= max_cabbage

        # 处理tofu_meat的需求
        if 'tofu_meat' in result and result['tofu_meat'] > 0:
            tofu_meat_needed = result['tofu_meat']
            tofu_needed = tofu_meat_needed * 2  # 每个tofu_meat需要2个豆腐

            if tofu_stock < tofu_needed:
                max_tofu_meat = tofu_stock // 2
                deficit = tofu_meat_needed - max_tofu_meat
                result['tofu_meat'] = max_tofu_meat
                if 'tofu' in self.name_to_config:
                    result['tofu'] = result.get('tofu', 0) + deficit * 2
                    logger.info(f"[岛屿-有鱼餐馆] 豆腐不足：{self._item_cn('tofu_meat')} {tofu_meat_needed}→{max_tofu_meat}，补入 {self._item_cn('tofu')} x{deficit * 2}")
                tofu_stock -= max_tofu_meat * 2

        return result

    def get_priority_production(self):
        """季节菜品先排额外一批，并合并当前基础需求中的同名缺口。"""
        if not self.seasonal_dish_slot:
            return {}
        name = self.seasonal_dish_slot['name']
        return {name: self.POST_PRODUCE_LIMIT + self.to_post_products.get(name, 0)}

    def test(self):
        chef_config = getattr(self.config, "IslandRestaurant_Chef", "WorkerJuu")
        logger.info(chef_config)


if __name__ == "__main__":
    az = IslandRestaurant('alas', task='Alas')
    az.device.screenshot()
    az.test()
