from module.island_restaurant.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.logger import logger
from collections import Counter
from datetime import datetime, timedelta
from module.base.button import Button
from module.island.island_season import SEASONAL_ITEMS


# 固定位置按钮 — 在委派界面不滑动时，双笋的固定位置
FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS = Button(
    area=(), color=(), button=(212, 143, 292, 211),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)


class IslandRestaurant(IslandShopBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 设置店铺类型
        self.shop_type = "restaurant"
        self.time_prefix = "time_restaurant"
        self.chef_config = self.config.IslandRestaurant_ChefFilter

        # === 初始化全局季节配置 ===
        self._init_season_config()
        # 兼容旧配置
        old_double_enabled = getattr(self.config, 'IslandRestaurant_DoubleBambooShoots', False)

        # === 高优先级季节菜品映射 ===
        self.seasonal_dish_slot = None
        seasonal_items = self.season_config.get_seasonal_items('restaurant') if hasattr(self, 'season_config') else []

        if 'double_bamboo_shoots' in seasonal_items:
            self.seasonal_dish_slot = {
                'name': 'double_bamboo_shoots', 'template': TEMPLATE_DOUBLE_BAMBOO_SHOOTS,
                'selection': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS, 'selection_check': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS,
                'post_action': POST_DOUBLE_BAMBOO_SHOOTS, 'cn_name': '凉拌双笋'
            }
        elif 'amaranth_rice_ball' in seasonal_items:
            self.seasonal_dish_slot = {
                'name': 'amaranth_rice_ball', 'template': TEMPLATE_AMARANTH_RICE_BALL,
                'selection': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS, 'selection_check': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS,
                'post_action': POST_AMARANTH_RICE_BALL, 'cn_name': '苋菜饭团'
            }
        elif old_double_enabled:
            self.seasonal_dish_slot = {
                'name': 'double_bamboo_shoots', 'template': TEMPLATE_DOUBLE_BAMBOO_SHOOTS,
                'selection': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS, 'selection_check': FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS,
                'post_action': POST_DOUBLE_BAMBOO_SHOOTS, 'cn_name': '凉拌双笋'
            }

        if self.seasonal_dish_slot:
            logger.info(f"高优先级季节菜品: {self.seasonal_dish_slot['cn_name']}")

        # 设置商品列表（根据季节自动选择对应菜品）
        self.shop_items = []
        if self.seasonal_dish_slot:
            self.shop_items.append(self.seasonal_dish_slot)
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
            # 季节限定菜品（需在 shop_items 中注册，以支持季节自动切换和配置读取）
            {'name': 'asparagus_shrimp', 'template': TEMPLATE_ASPARAGUS_SHRIMP, 'var_name': 'asparagus_shrimp',
             'selection': SELECT_ASPARAGUS_SHRIMP, 'selection_check': SELECT_ASPARAGUS_SHRIMP_CHECK,
             'post_action': POST_ASPARAGUS_SHRIMP},
            {'name': 'tomato_egg', 'template': TEMPLATE_TOMATO_EGG, 'var_name': 'tomato_egg',
             'selection': SELECT_TOMATO_EGG, 'selection_check': SELECT_TOMATO_EGG_CHECK,
             'post_action': POST_TOMATO_EGG},
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
                        f"季节餐品自动切换: {spring_item}({spring_name}) -> {seasonal_item}"
                        f"（当前季节: {self.season_config.season_name}）"
                    )
            else:
                self.post_products = [
                    (name, target) for name, target in self.post_products
                    if name != spring_item
                ]
                logger.info(
                    f"季节餐品自动移除: {spring_item}({spring_name})"
                    f"（{self.season_config.season_name} 无对应槽位的季节餐品）"
                )

    def select_product(self, product_selection, product_selection_check):
        """
        覆盖父类 select_product：
        高优先级季节菜品使用固定坐标点击，不进行模板匹配和滑动。
        其他餐品走父类逻辑。
        """
        if self.seasonal_dish_slot and product_selection == self.seasonal_dish_slot['selection']:
            self.device.click(FIXED_SELECT_DOUBLE_BAMBOO_SHOOTS)
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
                logger.info(f"扣除豆腐：tofu -{tofu_needed} (用于制作 {product})")

        # tofu_meat需要扣除豆腐
        if product == 'tofu_meat':
            tofu_needed = number * 2
            if 'tofu' in self.warehouse_counts:
                self.warehouse_counts['tofu'] -= tofu_needed
                logger.info(f"扣除豆腐：tofu -{tofu_needed} (用于制作 {product})")

    def apply_special_material_constraints(self, requirements):
        """覆盖：根据豆腐库存调整需求"""
        result = requirements.copy()

        # 获取豆腐库存
        tofu_stock = self.warehouse_counts.get('tofu', 0)

        # 处理cabbage_tofu的需求
        if 'cabbage_tofu' in result and result['cabbage_tofu'] > 0:
            cabbage_needed = result['cabbage_tofu']
            tofu_needed = cabbage_needed * 1  # 每个cabbage_tofu需要1个豆腐

            if tofu_stock < tofu_needed:
                # 调整需求
                max_cabbage = tofu_stock // 1
                result['cabbage_tofu'] = max_cabbage
                logger.info(f"豆腐不足：cabbage_tofu需求从{cabbage_needed}调整为{max_cabbage}")
                tofu_stock -= max_cabbage  # 更新剩余豆腐

        # 处理tofu_meat的需求
        if 'tofu_meat' in result and result['tofu_meat'] > 0:
            tofu_meat_needed = result['tofu_meat']
            tofu_needed = tofu_meat_needed * 2  # 每个tofu_meat需要2个豆腐

            if tofu_stock < tofu_needed:
                # 调整需求
                max_tofu_meat = tofu_stock // 2
                result['tofu_meat'] = max_tofu_meat
                logger.info(f"豆腐不足：tofu_meat需求从{tofu_meat_needed}调整为{max_tofu_meat}")

        return result

    def run(self):
        """
        覆盖父类的run方法，实现季节菜品的优先级控制：
          - 凉拌双笋（菜品1）：最高优先级，在基础需求前生产
          - 芦笋炒虾仁（菜品2）：最低优先级，等所有其他菜品（包括菜品1）都完成且系统空闲时才生产
        """
        self.island_error = False
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()
        self.post_manage_swipe(self.post_manage_swipe_count)

        # 检查岗位状态
        post_count = getattr(self.config, self.config_post_number, 2)
        time_vars = []
        for i in range(post_count):
            time_var_name = f'{self.time_prefix}{i + 1}'
            time_vars.append(time_var_name)
            setattr(self, time_var_name, None)
            post_id = f'ISLAND_{self.shop_type.upper()}_POST{i + 1}'
            self.post_check(post_id, time_var_name)

        # 获取空闲岗位
        idle_posts = self.get_idle_posts()

        if idle_posts:
            self.get_warehouse_counts()
            self.goto_postmanage()
            self.post_manage_mode(POST_MANAGE_PRODUCTION)
            self.post_close()
            self.post_manage_swipe(self.post_manage_swipe_count)

            # 计算当前总库存
            self.current_totals = {}
            all_product_names = set(name for name, _ in self.post_products)
            for item in all_product_names | set(self.post_check_meal.keys()) | set(
                    self.warehouse_counts.keys()):
                self.current_totals[item] = self.post_check_meal.get(item, 0) + self.warehouse_counts.get(item, 0)

            # ============ 调试信息 ============
            logger.info(f"=== 调试信息 ===")
            logger.info(f"仓库库存: {self.warehouse_counts}")
            logger.info(f"生产中库存: {self.post_check_meal}")
            logger.info(f"当前总库存: {self.current_totals}")
            logger.info(f"基础需求配置（共{len(self.post_products)}个槽位）: {self.post_products}")
            logger.info("===============")

            self._compute_base_demands()

            logger.info(f"待完成备餐: {self.to_post_products}")
            logger.info(f"当前剩余库存: {self.current_totals}")

            # ============ 处理套餐分解 ============
            if self.to_post_products:
                self.to_post_products = self.process_meal_requirements(self.to_post_products)
                logger.info(f"基础需求生产计划: {self.to_post_products}")

            # ================================================================
            #  高优先级季节菜品
            #  在所有基础需求之前单独生产，确保最高优先级
            # ================================================================
            if self.seasonal_dish_slot:
                dish_name = self.seasonal_dish_slot['name']
                dish_cn = self.seasonal_dish_slot['cn_name']
                logger.info(f"阶段：高优先级季节菜品 — {dish_cn}")

                # 从生产计划中提取，单独安排生产
                slot1_qty = 6
                if dish_name in self.to_post_products:
                    slot1_qty += self.to_post_products.pop(dish_name)

                # 临时只安排位置1的生产
                temp_products = self.to_post_products.copy()
                self.to_post_products = {dish_name: slot1_qty}
                logger.info(f"单独安排{dish_cn}生产: {self.to_post_products}")

                self.schedule_production()

                # 恢复剩余的基础需求生产计划
                self.to_post_products = temp_products
                logger.info(f"剩余基础需求生产计划: {self.to_post_products}")

            # ============ 安排基础需求生产 ============
            if self.to_post_products:
                self.schedule_production()
            else:
                logger.info("基础需求已满足")

            # ============ 检查是否还有空闲岗位，安排常驻餐品 ============
            idle_posts_after_basic = self.get_idle_posts()

            # 获取常驻餐品配置（不再使用特殊餐品special_food，因为季节菜品已独立控制）
            away_cook = getattr(self.config, self.config_away_cook, None)

            # 检查常驻餐品是否为有效值
            has_away_cook = (away_cook and away_cook != "None" and
                             away_cook in self.name_to_config)

            if idle_posts_after_basic and has_away_cook:
                logger.info(f"基础需求完成后，还有 {len(idle_posts_after_basic)} 个空闲岗位")

                for post_id in idle_posts_after_basic:
                    post_num = post_id[-1]
                    time_var_name = f'{self.time_prefix}{post_num}'

                    logger.info(f"尝试生产常驻餐品 {away_cook}")

                    # 检查材料限制
                    batch_size = min(6, 9999)
                    batch_size = self.get_max_producible(away_cook, batch_size)

                    if batch_size > 0:
                        result = self.post_produce(
                            post_id,
                            product=away_cook,
                            number=batch_size,
                            time_var_name=time_var_name
                        )

                        if result == 0:
                            logger.info(f"常驻餐品 {away_cook} 原料不足，保持岗位空闲")
                            break
                        else:
                            logger.info(f"已为岗位 {post_id} 安排常驻餐品 {away_cook} x{batch_size}")
                    else:
                        logger.info(f"生产 {away_cook} 的材料不足，跳过岗位 {post_id}")
                        break

            elif idle_posts_after_basic:
                logger.info(f"有 {len(idle_posts_after_basic)} 个空闲岗位，但未设置常驻餐品，保持空闲")

        # ============ 设置任务延迟 ============
        finish_times = []
        for var in time_vars:
            time_value = getattr(self, var)
            if time_value is not None:
                finish_times.append(time_value)
        hours_later = datetime.now() + timedelta(hours=6)
        finish_times.append(hours_later)
        finish_times.sort()
        self.config.task_delay(target=finish_times)
        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")

    def test(self):
        chef_config = getattr(self.config, "IslandRestaurant_Chef", "WorkerJuu")
        logger.info(chef_config)


if __name__ == "__main__":
    az = IslandRestaurant('alas', task='Alas')
    az.device.screenshot()
    az.test()
