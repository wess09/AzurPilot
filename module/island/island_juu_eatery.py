"""岛屿 JUU 餐厅模块。

继承 IslandShopBase，配置餐厅的商品列表与岗位参数。
包含苹果派、玉米杯、橙子派、香蕉可丽饼等餐品的模板、选择与制作流程定义。
"""
from module.island_juu_eatery.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.ui.page import *
from module.logger import logger
SEASONAL_JUU_EATERY_ITEMS = {
    'water_chestnut_cake': {
        'name': 'water_chestnut_cake', 'template': TEMPLATE_WATER_CHESTNUT_CAKE,
        'var_name': 'water_chestnut_cake',
        'selection': SELECT_WATER_CHESTNUT_CAKE,
        'selection_check': SELECT_WATER_CHESTNUT_CAKE_CHECK,
        'post_action': POST_WATER_CHESTNUT_CAKE,
    },
    'sugar_tangerine_daifuku': {
        'name': 'sugar_tangerine_daifuku', 'template': TEMPLATE_SUGAR_TANGERINE_DAIFUKU,
        'var_name': 'sugar_tangerine_daifuku',
        'selection': SELECT_SUGAR_TANGERINE_DAIFUKU,
        'selection_check': SELECT_SUGAR_TANGERINE_DAIFUKU_CHECK,
        'post_action': POST_SUGAR_TANGERINE_DAIFUKU,
    },
}


class IslandJuuEatery(IslandShopBase):
    """岛屿啾啾简餐店自动化管理器。

    继承 IslandShopBase，管理简餐店的菜品烹饪、芝士与牛奶原料约束及岗位派遣。

    Attributes:
        shop_type (str): 店铺类型标识。
        time_prefix (str): 岗位完成时间前缀。
        chef_config (str): 厨师角色筛选配置。
        post_open_retry_swipe (bool): 打开岗位失败时是否重试滑动。
        shop_items (list): 简餐店商品配置列表。
        meal_compositions (dict): 套餐组成与所需单品数量。
        post_buttons (dict): 岗位按钮资源映射。
        filter_asset (str): 仓库筛选分类。
        cheese_stock (int): 芝士库存数量。
        milk_stock (int): 牛奶库存数量。
        special_materials (dict): 特殊材料库存映射。
    """
    def __init__(self, *args, **kwargs):
        """Initialize eatery products, seasonal slots, and special materials."""
        super().__init__(*args, **kwargs)

        # 设置店铺类型
        self.shop_type = "juu_eatery"
        self.time_prefix = "time_eatery"
        self.chef_config = self.config.IslandJuuEatery_ChefFilter
        self.post_open_retry_swipe = True

        # === 初始化全局季节配置 ===
        self._init_season_config()

        # 设置商品列表
        self.shop_items = [
            {'name': 'apple_pie', 'template': TEMPLATE_APPLE_PIE, 'var_name': 'apple_pie',
             'selection': SELECT_APPLE_PIE, 'selection_check': SELECT_APPLE_PIE_CHECK,
             'post_action': POST_APPLE_PIE},
            {'name': 'corn_cup', 'template': TEMPLATE_CORN_CUP, 'var_name': 'corn_cup',
             'selection': SELECT_CORN_CUP, 'selection_check': SELECT_CORN_CUP_CHECK,
             'post_action': POST_CORN_CUP},
            {'name': 'orange_pie', 'template': TEMPLATE_ORANGE_PIE, 'var_name': 'orange_pie',
             'selection': SELECT_ORANGE_PIE, 'selection_check': SELECT_ORANGE_PIE_CHECK,
             'post_action': POST_ORANGE_PIE},
            {'name': 'banana_crepe', 'template': TEMPLATE_BANANA_CREPE, 'var_name': 'banana_crepe',
             'selection': SELECT_BANANA_CREPE, 'selection_check': SELECT_BANANA_CREPE_CHECK,
             'post_action': POST_BANANA_CREPE},
            {'name': 'orchard_duo', 'template': TEMPLATE_ORCHARD_DUO, 'var_name': 'orchard_duo',
             'selection': SELECT_ORCHARD_DUO, 'selection_check': SELECT_ORCHARD_DUO_CHECK,
             'post_action': POST_ORCHARD_DUO},
            {'name': 'rice_mango', 'template': TEMPLATE_RICE_MANGO, 'var_name': 'rice_mango',
             'selection': SELECT_RICE_MANGO, 'selection_check': SELECT_RICE_MANGO_CHECK,
             'post_action': POST_RICE_MANGO},
            {'name': 'succulently_sweet', 'template': TEMPLATE_SUCCULENTLY_SWEET, 'var_name': 'succulently_sweet',
             'selection': SELECT_SUCCULENTLY_SWEET, 'selection_check': SELECT_SUCCULENTLY_SWEET_CHECK,
             'post_action': POST_SUCCULENTLY_SWEET},
            {'name': 'berry_orange', 'template': TEMPLATE_BERRY_ORANGE, 'var_name': 'berry_orange',
             'selection': SELECT_BERRY_ORANGE, 'selection_check': SELECT_BERRY_ORANGE_CHECK,
             'post_action': POST_BERRY_ORANGE},
            {'name': 'strawberry_charlotte', 'template': TEMPLATE_STRAWBERRY_CHARLOTTE,
             'var_name': 'strawberry_charlotte',
             'selection': SELECT_STRAWBERRY_CHARLOTTE, 'selection_check': SELECT_STRAWBERRY_CHARLOTTE_CHECK,
             'post_action': POST_STRAWBERRY_CHARLOTTE},
            {'name': 'seafood_rice', 'template': TEMPLATE_SEAFOOD_RICE, 'var_name': 'seafood_rice',
             'selection': SELECT_SEAFOOD_RICE, 'selection_check': SELECT_SEAFOOD_RICE_CHECK,
             'post_action': POST_SEAFOOD_RICE},
        ]

        # 只注入当前季节的简餐菜品，避免冬季菜品在其他季节进入识别与排产列表。
        for item_name in self.season_config.get_seasonal_items('juu_eatery') or []:
            item_config = SEASONAL_JUU_EATERY_ITEMS.get(item_name)
            if item_config and not any(item['name'] == item_name for item in self.shop_items):
                self.shop_items.append(item_config.copy())
                logger.info(f"[岛屿-啾啾简餐] 季节限定：{item_name} 已添加")

        # 设置套餐组成
        self.meal_compositions = {
            'berry_orange': {
                'required': ['strawberry_charlotte', 'orange_pie'],
                'quantity_per': 1
            },
            'orchard_duo': {
                'required': ['apple_pie', 'banana_crepe'],
                'quantity_per': 1
            },
            'succulently_sweet': {
                'required': ['corn_cup', 'rice_mango'],
                'quantity_per': 1
            }
        }

        # 设置岗位按钮
        self.post_buttons = {
            'ISLAND_JUU_EATERY_POST1': ISLAND_JUU_EATERY_POST1,
            'ISLAND_JUU_EATERY_POST2': ISLAND_JUU_EATERY_POST2
        }

        # 设置筛选资产
        self.filter_asset = 'juu_eatery'

        # 设置配置前缀
        self.setup_config(
            config_meal_prefix="IslandJuuEatery_Meal",
            config_number_prefix="IslandJuuEatery_MealNumber",
            config_away_cook="IslandJuuEateryNextTask_AwayCook",
            config_post_number="IslandJuuEatery_PostNumber"
        )
        self._normalize_seasonal_post_products('juu_eatery')

        # 特殊材料：cheese 和 milk
        self.cheese_stock = 0
        self.milk_stock = 0  # 新增牛奶库存
        self.special_materials = {
            'cheese': 0,
            'milk': 0  # 新增牛奶
        }

        # 初始化店铺
        self.initialize_shop()

    def get_warehouse_counts(self):
        """获取简餐店商品以及芝士、牛奶等特殊材料的仓库库存。

        Returns:
            dict[str, int]: 包含所有商品与特殊原料库存的映射。
        """
        # 先调用父类方法获取基础库存
        super().get_warehouse_counts()

        # 获取cheese数量

        self.warehouse_filter('juu_coffee')
        image = self.device.screenshot()
        self.cheese_stock = self.ocr_item_quantity(image, TEMPLATE_CHEESE)
        self.special_materials['cheese'] = self.cheese_stock
        logger.info(f"[岛屿-啾啾简餐] 芝士数量: {self.cheese_stock}")

        # 将cheese库存也存入warehouse_counts，便于统一处理
        self.warehouse_counts['cheese'] = self.cheese_stock

        # 获取milk数量
        self.warehouse_filter('ranch')
        image = self.device.screenshot()
        self.milk_stock = self.ocr_item_quantity(image, TEMPLATE_MILK)
        self.special_materials['milk'] = self.milk_stock
        logger.info(f"[岛屿-啾啾简餐] 牛奶数量: {self.milk_stock}")

        # 将milk库存也存入warehouse_counts，便于统一处理
        self.warehouse_counts['milk'] = self.milk_stock

        return self.warehouse_counts

    def check_special_materials(self, product, batch_size):
        """检查特殊材料（芝士和牛奶）对生产批次的限制。

        Args:
            product (str): 目标商品名称。
            batch_size (int): 计划生产的批次数。

        Returns:
            int: 考虑材料限制后允许的最大批次数。
        """
        if batch_size <= 0:
            return 0

        # strawberry_charlotte需要2个芝士
        if product == 'strawberry_charlotte':
            cheese_needed_per_batch = 2
            cheese_available = self.cheese_stock
            max_by_cheese = cheese_available // cheese_needed_per_batch
            batch_size = min(batch_size, max_by_cheese)
            logger.info(
                f"  {self._item_cn(product)} 芝士限制: 可用{cheese_available}, 每批{cheese_needed_per_batch}, 最大{max_by_cheese}")

        # corn_cup需要1个牛奶
        elif product == 'corn_cup':
            milk_needed_per_batch = 1
            milk_available = self.milk_stock
            max_by_milk = milk_available // milk_needed_per_batch
            batch_size = min(batch_size, max_by_milk)
            logger.info(f"[岛屿-啾啾简餐]   {self._item_cn(product)} 牛奶限制: 可用{milk_available}, 每批{milk_needed_per_batch}, 最大{max_by_milk}")

        return batch_size

    def deduct_materials(self, product, number):
        """扣除制作指定餐品消耗的前置材料（包括芝士、牛奶和套餐原材料）。

        Args:
            product (str): 生产的餐品名称。
            number (int): 生产的餐品批次数。
        """
        # 先调用父类方法扣除套餐原材料
        super().deduct_materials(product, number)

        # strawberry_charlotte需要扣除芝士
        if product == 'strawberry_charlotte':
            cheese_needed = number * 2
            self.cheese_stock = max(0, self.cheese_stock - cheese_needed)
            self.special_materials['cheese'] = self.cheese_stock
            if 'cheese' in self.warehouse_counts:
                self.warehouse_counts['cheese'] = self.cheese_stock
            logger.info(f"[岛屿-啾啾简餐] 扣除芝士：{self._item_cn('cheese')} -{cheese_needed} (用于制作 {self._item_cn(product)})")

        # corn_cup需要扣除牛奶
        elif product == 'corn_cup':
            milk_needed = number * 1
            self.milk_stock = max(0, self.milk_stock - milk_needed)
            self.special_materials['milk'] = self.milk_stock
            if 'milk' in self.warehouse_counts:
                self.warehouse_counts['milk'] = self.milk_stock
            logger.info(f"[岛屿-啾啾简餐] 扣除牛奶：{self._item_cn('milk')} -{milk_needed} (用于制作 {self._item_cn(product)})")

    def apply_special_material_constraints(self, requirements):
        """根据芝士和牛奶的实际库存调整各餐品的需求排产计划。

        Args:
            requirements (dict[str, int]): 各餐品的原始需求数量映射。

        Returns:
            dict[str, int]: 调整后受原料库存约束的需求数量映射。
        """
        result = requirements.copy()

        # 处理strawberry_charlotte的芝士限制
        if 'strawberry_charlotte' in result and result['strawberry_charlotte'] > 0:
            strawberry_needed = result['strawberry_charlotte']
            cheese_needed = strawberry_needed * 2
            cheese_available = self.cheese_stock

            if cheese_available < cheese_needed:
                # 调整需求
                max_strawberry = cheese_available // 2
                result['strawberry_charlotte'] = max_strawberry
                logger.info(f"[岛屿-啾啾简餐] 芝士不足：{self._item_cn('strawberry_charlotte')}需求从{strawberry_needed}调整为{max_strawberry}")

        # 处理corn_cup的牛奶限制
        if 'corn_cup' in result and result['corn_cup'] > 0:
            corn_cup_needed = result['corn_cup']
            milk_needed = corn_cup_needed * 1
            milk_available = self.milk_stock

            if milk_available < milk_needed:
                # 调整需求
                max_corn_cup = milk_available // 1
                result['corn_cup'] = max_corn_cup
                logger.info(f"[岛屿-啾啾简餐] 牛奶不足：{self._item_cn('corn_cup')}需求从{corn_cup_needed}调整为{max_corn_cup}")

        return result

    # 新增方法：处理特殊任务（如果需要）
    def process_special_task(self):
        """处理特殊任务（如芝士消耗生产等扩展逻辑）。"""
        # 这里可以添加处理芝士相关任务的逻辑
        # 例如：如果芝士过多，强制生产strawberry_charlotte来消耗芝士
        pass


if __name__ == "__main__":
    az = IslandJuuEatery('alas', task='Alas')
    az.device.screenshot()
    az.run()
