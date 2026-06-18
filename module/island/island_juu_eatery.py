from module.island_juu_eatery.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.ui.page import *
from module.logger import logger


class IslandJuuEatery(IslandShopBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 设置店铺类型
        self.shop_type = "juu_eatery"
        self.time_prefix = "time_eatery"
        self.chef_config = self.config.IslandJuuEatery_ChefFilter

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
        """覆盖：获取仓库数量，包括cheese和milk"""
        # 先调用父类方法获取基础库存
        super().get_warehouse_counts()

        # 获取cheese数量

        self.warehouse_filter('juu_coffee')
        image = self.device.screenshot()
        self.cheese_stock = self.ocr_item_quantity(image, TEMPLATE_CHEESE)
        self.special_materials['cheese'] = self.cheese_stock
        logger.info(f"芝士数量: {self.cheese_stock}")

        # 将cheese库存也存入warehouse_counts，便于统一处理
        self.warehouse_counts['cheese'] = self.cheese_stock

        # 获取milk数量
        self.warehouse_filter('ranch')
        image = self.device.screenshot()
        self.milk_stock = self.ocr_item_quantity(image, TEMPLATE_MILK)
        self.special_materials['milk'] = self.milk_stock
        logger.info(f"牛奶数量: {self.milk_stock}")

        # 将milk库存也存入warehouse_counts，便于统一处理
        self.warehouse_counts['milk'] = self.milk_stock

        return self.warehouse_counts

    def check_special_materials(self, product, batch_size):
        """覆盖：检查特殊材料（芝士和牛奶）限制"""
        if batch_size <= 0:
            return 0

        # strawberry_charlotte需要2个芝士
        if product == 'strawberry_charlotte':
            cheese_needed_per_batch = 2
            cheese_available = self.cheese_stock
            max_by_cheese = cheese_available // cheese_needed_per_batch
            batch_size = min(batch_size, max_by_cheese)
            logger.info(
                f"  {product} 芝士限制: 可用{cheese_available}, 每批{cheese_needed_per_batch}, 最大{max_by_cheese}")

        # corn_cup需要1个牛奶
        elif product == 'corn_cup':
            milk_needed_per_batch = 1
            milk_available = self.milk_stock
            max_by_milk = milk_available // milk_needed_per_batch
            batch_size = min(batch_size, max_by_milk)
            logger.info(f"  {product} 牛奶限制: 可用{milk_available}, 每批{milk_needed_per_batch}, 最大{max_by_milk}")

        return batch_size

    def deduct_materials(self, product, number):
        """覆盖：扣除前置材料，包括芝士、牛奶和套餐原材料"""
        # 先调用父类方法扣除套餐原材料
        super().deduct_materials(product, number)

        # strawberry_charlotte需要扣除芝士
        if product == 'strawberry_charlotte':
            cheese_needed = number * 2
            self.cheese_stock = max(0, self.cheese_stock - cheese_needed)
            self.special_materials['cheese'] = self.cheese_stock
            if 'cheese' in self.warehouse_counts:
                self.warehouse_counts['cheese'] = self.cheese_stock
            logger.info(f"扣除芝士：cheese -{cheese_needed} (用于制作 {product})")

        # corn_cup需要扣除牛奶
        elif product == 'corn_cup':
            milk_needed = number * 1
            self.milk_stock = max(0, self.milk_stock - milk_needed)
            self.special_materials['milk'] = self.milk_stock
            if 'milk' in self.warehouse_counts:
                self.warehouse_counts['milk'] = self.milk_stock
            logger.info(f"扣除牛奶：milk -{milk_needed} (用于制作 {product})")

    def apply_special_material_constraints(self, requirements):
        """覆盖：根据芝士和牛奶库存调整需求"""
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
                logger.info(f"芝士不足：strawberry_charlotte需求从{strawberry_needed}调整为{max_strawberry}")

        # 处理corn_cup的牛奶限制
        if 'corn_cup' in result and result['corn_cup'] > 0:
            corn_cup_needed = result['corn_cup']
            milk_needed = corn_cup_needed * 1
            milk_available = self.milk_stock

            if milk_available < milk_needed:
                # 调整需求
                max_corn_cup = milk_available // 1
                result['corn_cup'] = max_corn_cup
                logger.info(f"牛奶不足：corn_cup需求从{corn_cup_needed}调整为{max_corn_cup}")

        return result

    # 新增方法：处理特殊任务（如果需要）
    def process_special_task(self):
        """处理特殊任务（如芝士消耗）"""
        # 这里可以添加处理芝士相关任务的逻辑
        # 例如：如果芝士过多，强制生产strawberry_charlotte来消耗芝士
        pass


if __name__ == "__main__":
    az = IslandJuuEatery('alas', task='Alas')
    az.device.screenshot()
    az.run()