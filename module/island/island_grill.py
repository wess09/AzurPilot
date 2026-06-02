from module.island_grill.assets import *
from module.island.island_shop_base import IslandShopBase
from module.logger import logger

class IslandGrill(IslandShopBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 设置店铺类型
        self.shop_type = "grill"
        self.time_prefix = "time_meal"
        self.chef_config = self.config.IslandGrill_ChefFilter

        # 设置商品列表
        self.shop_items = [
            {'name': 'roasted_skewer', 'template': TEMPLATE_ROASTED_SKEWER, 'var_name': 'roasted_skewer',
             'selection': SELECT_ROASTED_SKEWER, 'selection_check': SELECT_ROASTED_SKEWER_CHECK,
             'post_action': POST_ROASTED_SKEWER},
            {'name': 'chicken_potato', 'template': TEMPLATE_CHICKEN_POTATO, 'var_name': 'chicken_potato',
             'selection': SELECT_CHICKEN_POTATO, 'selection_check': SELECT_CHICKEN_POTATO_CHECK,
             'post_action': POST_CHICKEN_POTATO},
            {'name': 'carrot_omelette', 'template': TEMPLATE_CARROT_OMELETTE, 'var_name': 'carrot_omelette',
             'selection': SELECT_CARROT_OMELETTE, 'selection_check': SELECT_CARROT_OMELETTE_CHECK,
             'post_action': POST_CARROT_OMELETTE},
            {'name': 'stir_fried_chicken', 'template': TEMPLATE_STIR_FRIED_CHICKEN, 'var_name': 'stir_fried_chicken',
             'selection': SELECT_STIR_FRIED_CHICKEN, 'selection_check': SELECT_STIR_FRIED_CHICKEN_CHECK,
             'post_action': POST_STIR_FRIED_CHICKEN},
            {'name': 'steak_bowl', 'template': TEMPLATE_STEAK_BOWL, 'var_name': 'steak_bowl',
             'selection': SELECT_STEAK_BOWL, 'selection_check': SELECT_STEAK_BOWL_CHECK,
             'post_action': POST_STEAK_BOWL},
            {'name': 'carnival', 'template': TEMPLATE_CARNIVAL, 'var_name': 'carnival',
             'selection': SELECT_CARNIVAL, 'selection_check': SELECT_CARNIVAL_CHECK,
             'post_action': POST_CARNIVAL},
            {'name': 'double_energy', 'template': TEMPLATE_DOUBLE_ENERGY, 'var_name': 'double_energy',
             'selection': SELECT_DOUBLE_ENERGY, 'selection_check': SELECT_DOUBLE_ENERGY_CHECK,
             'post_action': POST_DOUBLE_ENERGY},
        ]

        # 设置套餐组成
        self.meal_compositions = {
            'double_energy': {
                'required': ['stir_fried_chicken', 'steak_bowl'],
                'quantity_per': 1
            },
            'carnival': {
                'required': ['chicken_potato', 'roasted_skewer'],
                'quantity_per': 1
            }
        }

        # 设置岗位按钮
        self.post_buttons = {
            'ISLAND_GRILL_POST1': ISLAND_GRILL_POST1,
            'ISLAND_GRILL_POST2': ISLAND_GRILL_POST2
        }

        # 设置筛选资产
        self.filter_asset = 'grill'

        # 设置配置前缀
        self.setup_config(
            config_meal_prefix="IslandGrill_Meal",
            config_number_prefix="IslandGrill_MealNumber",
            config_away_cook="IslandGrillNextTask_AwayCook",
            config_post_number="IslandGrill_PostNumber"
        )

        self.post_manage_swipe_count = 2

        # 初始化店铺
        self.initialize_shop()

    def test(self):
        self.island_error = False
        self.post_get_and_close()
        if self.island_error:
            logger.info('error1')


if __name__ == "__main__":
    az = IslandGrill('alas', task='Alas')
    az.device.screenshot()
    az.test()