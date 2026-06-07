from module.island_teahouse.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.ui.page import *
from collections import Counter
from datetime import datetime, timedelta
from module.logger import logger
from module.base.button import Button
from module.island.island_season import SEASONAL_ITEMS
from module.ocr.ocr import Duration, Digit


# 固定位置按钮 — 迎春花茶使用固定坐标，不检测图标颜色，不向下滑动
FIXED_SELECT_SPRING_FLOWER_TEA = Button(
    area=(), color=(), button=(212, 300, 292, 360),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)


class IslandTeahouse(IslandShopBase):
    def __init__(self, config, device=None, task=None):
        super().__init__(config=config, device=device, task=task)

        # 设置店铺类型
        self.shop_type = "teahouse"
        self.time_prefix = "time_tea"
        self.chef_config = self.config.IslandTeahouse_ChefFilter

        # === 初始化全局季节配置 ===
        self._init_season_config()
        old_seasonal_enabled = getattr(self.config, 'IslandTeahouse_Seasonal', False)

        # === 根据季节确定高优先级限定饮品 ===
        self.seasonal_high_priority_drink = None  # 对标迎春花茶/西瓜汁
        seasonal_items = self.season_config.get_seasonal_items('teahouse') if hasattr(self, 'season_config') else []

        if old_seasonal_enabled:
            # 仅当「迎春花茶」开关开启时，才设置高优先级季节饮品
            # 位置1饮品（对标迎春花茶）：高优先级，固定坐标点
            if 'spring_flower_tea' in seasonal_items:
                self.seasonal_high_priority_drink = {
                    'name': 'spring_flower_tea', 'cn_name': '迎春花茶',
                    'template': TEMPLATE_APPLE_JUICE, 'post_action': POST_APPLE_JUICE,
                    'selection': FIXED_SELECT_SPRING_FLOWER_TEA, 'selection_check': FIXED_SELECT_SPRING_FLOWER_TEA,
                }
            elif 'watermelon_juice' in seasonal_items:
                self.seasonal_high_priority_drink = {
                    'name': 'watermelon_juice', 'cn_name': '西瓜汁',
                    'template': TEMPLATE_APPLE_JUICE, 'post_action': POST_APPLE_JUICE,
                    'selection': FIXED_SELECT_SPRING_FLOWER_TEA, 'selection_check': FIXED_SELECT_SPRING_FLOWER_TEA,
                }

            if self.seasonal_high_priority_drink:
                self.special_food = self.seasonal_high_priority_drink['name']
                logger.info(f"季节高优先级饮品: {self.seasonal_high_priority_drink['cn_name']}")
            else:
                self.special_food = 'spring_flower_tea'
        else:
            logger.info("迎春花茶优先生产已关闭，跳过季节限定饮品")

        # 设置商品列表
        self.shop_items = []
        # ---- 季节饮品（固定位置） ----
        if self.seasonal_high_priority_drink:
            self.shop_items.append(self.seasonal_high_priority_drink)
        # ---- 常规菜品 ----
        self.shop_items.extend([
            {'name': 'apple_juice', 'template': TEMPLATE_APPLE_JUICE, 'var_name': 'apple_juice',
             'selection': SELECT_APPLE_JUICE, 'selection_check': SELECT_APPLE_JUICE_CHECK,
             'post_action': POST_APPLE_JUICE},
            {'name': 'banana_mango', 'template': TEMPLATE_BANANA_MANGO, 'var_name': 'banana_mango',
             'selection': SELECT_BANANA_MANGO, 'selection_check': SELECT_BANANA_MANGO_CHECK,
             'post_action': POST_BANANA_MANGO},
            {'name': 'honey_lemon', 'template': TEMPLATE_HONEY_LEMON, 'var_name': 'honey_lemon',
             'selection': SELECT_HONEY_LEMON, 'selection_check': SELECT_HONEY_LEMON_CHECK,
             'post_action': POST_HONEY_LEMON},
            {'name': 'strawberry_lemon', 'template': TEMPLATE_STRAWBERRY_LEMON, 'var_name': 'strawberry_lemon',
             'selection': SELECT_STRAWBERRY_LEMON, 'selection_check': SELECT_STRAWBERRY_LEMON_CHECK,
             'post_action': POST_STRAWBERRY_LEMON},
            {'name': 'strawberry_honey', 'template': TEMPLATE_STRAWBERRY_HONEY, 'var_name': 'strawberry_honey',
             'selection': SELECT_STRAWBERRY_HONEY, 'selection_check': SELECT_STRAWBERRY_HONEY_CHECK,
             'post_action': POST_STRAWBERRY_HONEY},
            {'name': 'floral_fruity', 'template': TEMPLATE_FLORAL_FRUITY, 'var_name': 'floral_fruity',
             'selection': SELECT_FLORAL_FRUITY, 'selection_check': SELECT_FLORAL_FRUITY_CHECK,
             'post_action': POST_FLORAL_FRUITY},
            {'name': 'fruit_paradise', 'template': TEMPLATE_FRUIT_PARADISE, 'var_name': 'fruit_paradise',
             'selection': SELECT_FRUIT_PARADISE, 'selection_check': SELECT_FRUIT_PARADISE_CHECK,
             'post_action': POST_FRUIT_PARADISE},
            {'name': 'lavender_tea', 'template': TEMPLATE_LAVENDER_TEA, 'var_name': 'lavender_tea',
             'selection': SELECT_LAVENDER_TEA, 'selection_check': SELECT_LAVENDER_TEA_CHECK,
             'post_action': POST_LAVENDER_TEA},
            {'name': 'sunny_honey', 'template': TEMPLATE_SUNNY_HONEY, 'var_name': 'sunny_honey',
             'selection': SELECT_SUNNY_HONEY, 'selection_check': SELECT_SUNNY_HONEY_CHECK,
             'post_action': POST_SUNNY_HONEY},
        ])
        # 设置套餐组成
        self.meal_compositions = {
            'floral_fruity': {
                'required': ['lavender_tea', 'apple_juice'],
                'quantity_per': 1
            },
            'fruit_paradise': {
                'required': ['banana_mango', 'strawberry_honey'],
                'quantity_per': 1
            },
            'sunny_honey': {
                'required': ['strawberry_lemon', 'honey_lemon'],
                'quantity_per': 1
            }
        }

        # 设置岗位按钮
        self.post_buttons = {
            'ISLAND_TEAHOUSE_POST1': ISLAND_TEAHOUSE_POST1,
            'ISLAND_TEAHOUSE_POST2': ISLAND_TEAHOUSE_POST2
        }

        # 设置筛选资产
        self.filter_asset = 'teahouse'

        # 设置配置前缀（更新为4个参数，删除任务相关配置）
        self.setup_config(
            config_meal_prefix="IslandTeahouse_Meal",
            config_number_prefix="IslandTeahouse_MealNumber",
            config_away_cook="IslandTeahouseNextTask_AwayCook",
            config_post_number="IslandTeahouse_PostNumber"
        )

        # === 季节餐品自动切换 ===
        # 若用户在 Meal 中配置了春季限定餐品（pineapple_juice），
        # 但当前季节不是 spring，则自动替换为当前季节对应槽位的餐品
        self._auto_switch_seasonal_meals()

        # 特殊材料：蜂蜜（仅用于库存检查和限制，不再有强制消耗任务）
        self.fresh_honey = 0
        self.initialize_shop()

    def _auto_switch_seasonal_meals(self):
        """
        自动切换用户配置中的春季限定餐品到当前季节对应餐品。
        迎春花茶(spring_flower_tea) -> 春季保持，夏季切换为西瓜汁(watermelon_juice)，秋冬移除。
        鲜榨菠萝汁(pineapple_juice) -> 春季保持，夏季切换为黄瓜汁(cucumber_juice)，秋冬移除。
        """
        SEASONAL_TEAHOUSE_SWITCH = {
            'spring_flower_tea': 0,  # 迎春花茶 -> 槽位0
            'pineapple_juice': 1,    # 鲜榨菠萝汁 -> 槽位1
        }
        CN_NAMES = {
            'spring_flower_tea': '迎春花茶',
            'pineapple_juice': '鲜榨菠萝汁',
        }
        if not hasattr(self, 'season_config') or not self.season_config:
            return
        current_season = self.season_config.season
        current_teahouse_items = SEASONAL_ITEMS.get(current_season, {}).get('teahouse', [])
        for spring_item, slot_idx in SEASONAL_TEAHOUSE_SWITCH.items():
            if not any(name == spring_item for name, _ in self.post_products):
                continue
            cn_name = CN_NAMES.get(spring_item, spring_item)
            if slot_idx < len(current_teahouse_items):
                seasonal_item = current_teahouse_items[slot_idx]
                if seasonal_item != spring_item:
                    self.post_products = [
                        (seasonal_item, target) if name == spring_item else (name, target)
                        for name, target in self.post_products
                    ]
                    logger.info(
                        f"季节餐品自动切换: {spring_item}({cn_name}) -> {seasonal_item}"
                        f"（当前季节: {self.season_config.season_name}）"
                    )
            else:
                self.post_products = [
                    (name, target) for name, target in self.post_products
                    if name != spring_item
                ]
                logger.info(
                    f"季节餐品自动移除: {spring_item}({cn_name})"
                    f"（{self.season_config.season_name} 无对应槽位的季节餐品）"
                )

    def get_warehouse_counts(self):
        """覆盖：获取仓库数量，包括蜂蜜"""
        # 先调用父类方法获取基础库存
        super().get_warehouse_counts()

        # 额外获取蜂蜜数量（用于库存限制）
        self.warehouse_filter('basic','other_from')
        image = self.device.screenshot()
        self.fresh_honey = self.ocr_item_quantity(image, TEMPLATE_FRESH_HONEY)
        logger.info(f"蜂蜜数量: {self.fresh_honey}")

        # 将蜂蜜库存存入warehouse_counts，便于统一处理
        self.warehouse_counts['fresh_honey'] = self.fresh_honey

        return self.warehouse_counts

    def check_special_materials(self, product, batch_size):
        """覆盖：检查特殊材料（蜂蜜）限制"""
        if batch_size <= 0:
            return 0

        # sunny_honey需要honey_lemon或蜂蜜
        if product == 'sunny_honey':
            # 计算可用原材料：蜂蜜 + honey_lemon库存
            honey_available = self.fresh_honey
            honey_lemon_available = self.warehouse_counts.get('honey_lemon', 0)
            total_available = honey_available + honey_lemon_available

            max_by_material = min(batch_size, total_available)
            return max_by_material

        # honey_lemon需要蜂蜜
        if product == 'honey_lemon':
            max_by_honey = min(batch_size, self.fresh_honey)
            return max_by_honey

        return batch_size

    def post_produce(self, post_id, product, number, time_var_name, product2=None):
        """
        覆盖父类 post_produce：
        季节高优先级饮品（迎春花茶/西瓜汁等）：点击岗位 → ISLAND_POST_SELECT进入选择 → 处理选人 → 点击固定坐标。
        不调用父类select_product（跳过图像匹配和滑动）。
        其他餐品走父类逻辑。
        """
        seasonal_drink_name = self.seasonal_high_priority_drink['name'] if self.seasonal_high_priority_drink else ''
        if product == seasonal_drink_name:
            post_button = self.posts[post_id]['button']
            self.post_close()
            self.post_open(post_button)
            self.device.sleep(0.5)
            time_work = Duration(ISLAND_WORKING_TIME)
            # 进入商品选择界面（处理选人 + 选商品）
            while 1:
                self.device.screenshot()
                if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                    # 选择厨师
                    if self.select_character(character_list=self.chef_config):
                        self.device.sleep(0.5)
                        self.appear_then_click(SELECT_UI_CONFIRM)
                        self.device.sleep(0.5)
                    continue
                if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                    # 在商品列表界面，点击固定位置，不检测图标
                    self.device.click(FIXED_SELECT_SPRING_FLOWER_TEA)
                    self.device.sleep(0.5)
                    break
                # 点击进入选择
                if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                    self.device.sleep(0.3)
                    continue
                self.device.sleep(0.3)
            # 检查材料并下单
            if self.produce_check():
                logger.warning(f"原料不足，无法生产 spring_flower_tea")
                self.device.click(ISLAND_BACK)
                self.device.sleep(0.5)
                return 0
            else:
                for _ in range(number - 1):
                    self.device.click(POST_ADD_ONE)
                self.device.sleep(0.5)
                self.device.click(POST_ADD_ORDER)
                self.device.sleep(0.5)
            self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
            self.device.sleep(0.5)
            logger.info(post_button)
            self.post_open(post_button)
            self.device.sleep(0.5)
            image = self.device.screenshot()
            ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                    alphabet='0123456789')
            actual_number = ocr_post_number.ocr(image)
            time_value = time_work.ocr(self.device.image)
            finish_time = datetime.now() + time_value
            setattr(self, time_var_name, finish_time)
            self.posts[post_id]['status'] = 'working'
            self.deduct_materials(product, actual_number)
            logger.info(f"已安排生产：{product} x{actual_number}")
            self.post_close()
            return actual_number

        return super().post_produce(post_id, product, number, time_var_name, product2)

    def run(self):
        """
        覆盖父类的run方法，实现迎春花茶的优先级控制：
        迎春花茶为最高优先级，在基础需求前单独生产。
        其他逻辑沿用父类流程。
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
            #  阶段：高优先级季节饮品（受「迎春花茶」开关控制）
            #  开关开启时：在基础需求之前单独生产季节饮品，确保最高优先级
            #  开关关闭时：直接进入基础需求生产
            # ================================================================
            if self.seasonal_high_priority_drink:
                drink_name = self.seasonal_high_priority_drink['name']
                drink_cn = self.seasonal_high_priority_drink['cn_name']
                logger.info(f"阶段：高优先级季节饮品 — {drink_cn}")
                temp_products = self.to_post_products.copy()
                self.to_post_products = {drink_name: 6}
                logger.info(f"单独安排{drink_cn}生产: {self.to_post_products}")

                self.schedule_production()

                # 恢复剩余的基础需求生产计划
                self.to_post_products = temp_products
                logger.info(f"剩余基础需求生产计划: {self.to_post_products}")
            else:
                logger.info("迎春花茶优先生产已关闭，直接处理基础需求")

            # ============ 安排基础需求生产 ============
            if self.to_post_products:
                self.schedule_production()
            else:
                logger.info("基础需求已满足")

            # ============ 检查是否还有空闲岗位，安排特殊餐品或常驻餐品 ============
            idle_posts_after_basic = self.get_idle_posts()
            away_cook = getattr(self.config, self.config_away_cook, None)
            has_away_cook = (away_cook and away_cook != "None" and
                             away_cook in self.name_to_config)

            if idle_posts_after_basic and has_away_cook:
                logger.info(f"基础需求完成后，还有 {len(idle_posts_after_basic)} 个空闲岗位")
                for post_id in idle_posts_after_basic:
                    post_num = post_id[-1]
                    time_var_name = f'{self.time_prefix}{post_num}'
                    logger.info(f"尝试生产常驻餐品 {away_cook}")
                    batch_size = min(6, 9999)
                    batch_size = self.get_max_producible(away_cook, batch_size)
                    if batch_size > 0:
                        result = self.post_produce(
                            post_id, product=away_cook, number=batch_size,
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

    def deduct_materials(self, product, number):
        """覆盖：扣除前置材料，包括蜂蜜和套餐原材料"""
        # 先调用父类方法扣除套餐原材料
        super().deduct_materials(product, number)

        # sunny_honey套餐需要扣除原材料
        if product == 'sunny_honey':
            # sunny_honey需要honey_lemon和strawberry_lemon各1个
            # honey_lemon可以通过蜂蜜制作，所以优先扣除蜂蜜，不够再扣除honey_lemon

            honey_needed = number
            honey_lemon_needed = number

            # 优先扣除蜂蜜
            if self.fresh_honey >= honey_needed:
                self.fresh_honey -= honey_needed
                logger.info(f"扣除蜂蜜：fresh_honey -{honey_needed} (用于制作sunny_honey)")
            else:
                # 蜂蜜不足，扣除honey_lemon
                remaining_needed = honey_needed - self.fresh_honey
                if self.fresh_honey > 0:
                    logger.info(f"扣除蜂蜜：fresh_honey -{self.fresh_honey} (用于制作sunny_honey)")
                    self.fresh_honey = 0

                # 扣除honey_lemon库存
                if 'honey_lemon' in self.warehouse_counts:
                    available_honey_lemon = min(remaining_needed, self.warehouse_counts['honey_lemon'])
                    if available_honey_lemon > 0:
                        self.warehouse_counts['honey_lemon'] -= available_honey_lemon
                        logger.info(f"扣除honey_lemon：honey_lemon -{available_honey_lemon} (用于制作sunny_honey)")

    def apply_special_material_constraints(self, requirements):
        """覆盖：根据蜂蜜库存调整需求"""
        result = requirements.copy()

        # 首先处理honey_lemon的需求
        if 'honey_lemon' in result and result['honey_lemon'] > 0:
            honey_lemon_needed = result['honey_lemon']
            max_honey_lemon = min(honey_lemon_needed, self.fresh_honey)

            if max_honey_lemon < honey_lemon_needed:
                logger.info(f"蜂蜜不足：honey_lemon需求从{honey_lemon_needed}调整为{max_honey_lemon}")

            result['honey_lemon'] = max_honey_lemon

        # 处理sunny_honey的需求
        if 'sunny_honey' in result and result['sunny_honey'] > 0:
            sunny_honey_needed = result['sunny_honey']

            # sunny_honey需要honey_lemon，每个需要1个蜂蜜
            # 但honey_lemon的需求可能已经在上面调整过
            honey_lemon_for_sunny = sunny_honey_needed

            # 计算可用于sunny_honey的蜂蜜
            # 减去已经分配给honey_lemon的蜂蜜
            honey_allocated = result.get('honey_lemon', 0)
            honey_remaining = max(0, self.fresh_honey - honey_allocated)

            max_sunny_honey = min(sunny_honey_needed, honey_remaining)

            if max_sunny_honey < sunny_honey_needed:
                logger.info(f"蜂蜜不足：sunny_honey需求从{sunny_honey_needed}调整为{max_sunny_honey}")

            result['sunny_honey'] = max_sunny_honey

        return result


if __name__ == "__main__":
    az = IslandTeahouse('alas', task='Alas')
    az.device.screenshot()
    az.run()