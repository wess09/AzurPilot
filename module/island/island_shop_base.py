from module.island.island import *
from collections import Counter
from datetime import datetime, timedelta
from module.handler.login import LoginHandler
from module.island.warehouse import *
from module.logger import logger
from module.island.island_season import get_global_season_config


class IslandShopBase(Island, WarehouseOCR):
    _MAX_FILL_LOOP = 10  # while 循环填岗最大迭代次数
    PRODUCT_SELECT_RETRY_LIMIT = 3  # 餐品选择识别失败后，退出重进的最大次数
    POST_PRODUCE_LIMIT = 7  # 餐馆每个岗位单次最多生产数量

    def __init__(self, config, device=None, task=None):
        # 分别初始化每个父类
        Island.__init__(self, config=config, device=device, task=task)
        WarehouseOCR.__init__(self)  # WarehouseOCR 可能不需要参数

        # 子类必须设置的属性
        self.shop_items = []  # 商品列表
        self.shop_type = ""  # 店铺类型：grill, teahouse, tailor, toolshop, furniture
        self.filter_asset = None  # 仓库筛选资产
        self.post_buttons = {}  # 岗位按钮
        self.time_prefix = "time_meal"  # 时间变量前缀
        self.special_character = False
        self.special_food = None
        # 角色选择配置
        self.chef_config = None

        # 通用属性
        self.name_to_config = {}
        self.posts = {}
        self.post_check_meal = {}  # 岗位生产中的产品
        self.post_products = []  # 有序列表，允许同名餐品出现在多个槽位
        self.warehouse_counts = {}  # 仓库识别到的产品
        self.to_post_products = {}
        self.current_totals = {}

        # 特殊材料（子类可覆盖）
        self.special_materials = {}

        # 套餐组成（子类可覆盖）
        self.meal_compositions = {}

        # 配置前缀（子类可覆盖）
        self.config_meal_prefix = "Island_Meal"
        self.config_number_prefix = "Island_MealNumber"
        self.config_away_cook = "IslandNextTask_AwayCook"
        self.config_post_number = "Island_PostNumber"

        # 滑动配置（子类可覆盖）
        self.post_manage_swipe_count = 1  # 默认滑动1次450

    # ==================== 季节配置支持 ====================

    def _init_season_config(self):
        """初始化季节配置"""
        self.season_config = get_global_season_config(self.config)
        self.current_season = self.season_config.season
        self.season_name = self.season_config.season_name

        if self.season_config.is_seasonal_enabled:
            logger.info(f"当前季节: {self.season_name}，季节限定已启用")
        else:
            logger.info("季节限定未启用")

    def is_seasonal_item_enabled(self, item_name):
        """
        判断指定物品在当前季节是否启用

        如果季节限定未启用（none），则默认所有物品可用。
        如果季节限定启用，则只返回本季节的物品列表。

        Args:
            item_name: 物品名称

        Returns:
            bool
        """
        if not hasattr(self, 'season_config') or self.season_config is None:
            return True
        if not self.season_config.is_seasonal_enabled:
            return True
        # 检查物品是否在当前季节的列表中
        seasonal_items = self.season_config.get_seasonal_items(self.shop_type)
        if item_name in seasonal_items:
            return True
        # 不在当前季节列表中的季节性物品 → 禁用
        # 检查是否是其他季节的限定物品
        for season_key in ['spring', 'summer', 'autumn', 'winter']:
            if season_key == self.season_config.season:
                continue
            from module.island.island_season import SEASONAL_ITEMS
            other_items = SEASONAL_ITEMS.get(season_key, {}).get(self.shop_type, [])
            if item_name in other_items:
                logger.info(f"物品 [{item_name}] 是 {season_key} 的限定品，当前 {self.season_name} 不可用")
                return False
        return True
    def produce_check(self):
        self.device.sleep(0.5)
        image = self.device.screenshot()
        area = (493, 597, 621, 643)
        color = get_color(image, area)
        if color_similar(color, (153, 156, 156), 80):
            return True
        else:
            return False
    def setup_config(self, config_meal_prefix, config_number_prefix,
                     config_away_cook, config_post_number):
        """从配置中读取餐品需求 - 修改为8种餐品"""
        # 设置配置前缀
        self.config_meal_prefix = config_meal_prefix
        self.config_number_prefix = config_number_prefix
        self.config_away_cook = config_away_cook
        self.config_post_number = config_post_number

        # 读取8种餐品需求
        self.post_products = []

        for i in range(1, 9):  # 1到8
            meal_key = f'{self.config_meal_prefix}{i}'
            number_key = f'{self.config_number_prefix}{i}'

            meal_name = getattr(self.config, meal_key, None)
            if meal_name is not None and meal_name != "None":
                meal_number = getattr(self.config, number_key, 0)
                self.post_products.append((meal_name, meal_number))

    def initialize_shop(self):
        """初始化店铺，子类必须在__init__中调用"""
        self.name_to_config = {item['name']: item for item in self.shop_items}

        # 初始化岗位状态
        for post_id, button in self.post_buttons.items():
            self.posts[post_id] = {'status': 'none', 'button': button}

    # ============ 通用方法 ============
    def post_check(self, post_id, time_var_name):
        """检查岗位状态（通用）"""
        post_button = self.posts[post_id]['button']
        self.post_close()
        self.post_open(post_button)
        self.device.sleep(0.5)
        image = self.device.screenshot()
        ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                alphabet='0123456789')
        if self.appear(ISLAND_WORK_COMPLETE, offset=1):
            self.posts[post_id]['status'] = 'idle'
            setattr(self, time_var_name, None)
        elif self.appear(ISLAND_WORKING):
            product = self.post_product_check()
            number = ocr_post_number.ocr(image)
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            finish_time = datetime.now() + time_value
            setattr(self, time_var_name, finish_time)
            self.posts[post_id]['status'] = 'working'
            if product is not None:
                if product in self.post_check_meal:
                    self.post_check_meal[product] += number
                else:
                    self.post_check_meal[product] = number
        elif self.appear(ISLAND_POST_SELECT):
            self.posts[post_id]['status'] = 'idle'
            setattr(self, time_var_name, None)
        self.post_get_and_close()
        self.device.sleep(0.5)

    def post_product_check(self):
        """检查岗位生产的产品（通用）"""
        for item in self.shop_items:
            if self.appear(item['post_action']):
                return item['name']
        return None

    def get_warehouse_counts(self):
        """获取仓库数量（通用）"""
        self.warehouse_filter(self.filter_asset)
        image = self.device.screenshot()

        for dish in self.shop_items:
            self.warehouse_counts[dish['name']] = self.ocr_item_quantity(image, dish['template'])
            if self.warehouse_counts[dish['name']]:
                logger.info(f"{dish['name']}: {self.warehouse_counts[dish['name']]}")
        return self.warehouse_counts
    def select_special_character(self,product):
        return self.select_character(character_list=self.chef_config)
    def produce_special_food(self):
        pass

    def retry_product_selection_from_postmanage(self, post_button, product, failed_product, failed_count):
        """餐品选择失败后退出岗位，重新进入同一岗位走完整派遣流程。"""
        if failed_count >= self.PRODUCT_SELECT_RETRY_LIMIT:
            raise GameStuckError(
                f"{product}生产选择餐品时连续{failed_count}次未识别到 {failed_product}"
            )

        logger.warning(
            f"{product}生产选择餐品时未识别到 {failed_product}，"
            f"退出岗位后重新进入 ({failed_count}/{self.PRODUCT_SELECT_RETRY_LIMIT})"
        )
        if not self.back_to_postmanage_from_dispatch():
            raise GameStuckError(f"{product}生产选择餐品失败后无法返回岗位管理页")

        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_manage_swipe(self.post_manage_swipe_count)
        if not self.post_open(post_button):
            raise GameStuckError(f"{product}生产选择餐品失败后无法重新打开岗位")
        self.device.sleep(0.5)

    def increase_product_selection_failure(self, product_select_failures, failed_product):
        """记录单个餐品的选择失败次数。"""
        failed_count = product_select_failures.get(failed_product, 0) + 1
        product_select_failures[failed_product] = failed_count
        return failed_count

    def post_produce(self, post_id, product, number, time_var_name,product2=None):
        """生产产品（通用）"""
        post_button = self.posts[post_id]['button']
        self.post_close()
        self.post_open(post_button)
        self.device.sleep(0.5)
        time_work = Duration(ISLAND_WORKING_TIME)
        selection = self.name_to_config[product]['selection']
        selection_check = self.name_to_config[product]['selection_check']
        product_select_failures = {}
        for _ in self.loop(timeout=120, skip_first=False):
            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.special_character:
                    selected = self.select_special_character(product)
                    character_filter = "special"
                else:
                    selected = self.select_character(character_list=self.chef_config)
                    character_filter = self.chef_config
                if selected:
                    if not self.confirm_selected_character(f"{product}生产派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return 0
                else:
                    logger.warning(f"{product}生产派遣无可用角色: {character_filter}")
                    self.back_to_postmanage_from_dispatch()
                    return 0
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                if self.select_product(selection, selection_check):
                    self.device.sleep(0.5)
                    if self.produce_check():
                        logger.warning(f"原料不足，无法生产 {product}")
                        self.device.sleep(0.5)
                        if product == self.special_food:
                            if product2:
                                selection2 = self.name_to_config[product2]['selection']
                                selection_check2 = self.name_to_config[product2]['selection_check']
                                if not self.select_product(selection2, selection_check2):
                                    failed_count = self.increase_product_selection_failure(
                                        product_select_failures, product2
                                    )
                                    self.retry_product_selection_from_postmanage(
                                        post_button, product, product2, failed_count
                                    )
                                    continue
                                self.device.sleep(0.5)
                                if self.produce_check():
                                    logger.warning(f"原料不足，无法生产 {product2}")
                                    self.device.click(ISLAND_BACK)
                                    self.device.sleep(0.5)
                                    return 0  # 返回0表示原料不足
                                else:
                                    self.post_add_one(number - 1)
                                    self.device.sleep(0.5)
                                    self.device.click(POST_ADD_ORDER)
                                    self.device.sleep(0.5)
                                    break
                            else:
                                self.device.click(ISLAND_BACK)
                                self.device.sleep(0.5)
                                return 0  # 返回0表示原料不足

                        else:
                            self.device.click(ISLAND_BACK)
                            self.post_close()
                            self.post_manage_swipe(self.post_manage_swipe_count)
                            self.device.sleep(0.5)
                            return 0  # 返回0表示原料不足
                    else:
                        self.post_add_one(number - 1)
                        self.device.sleep(0.5)
                        self.device.click(POST_ADD_ORDER)
                        self.device.sleep(0.5)
                        break
                else:
                    failed_count = self.increase_product_selection_failure(
                        product_select_failures, product
                    )
                    self.retry_product_selection_from_postmanage(
                        post_button, product, product, failed_count
                    )
                continue
        else:
            raise GameStuckError(f"{product}生产派遣流程超时")
        self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
        self.device.sleep(0.5)
        self.post_manage_swipe(self.post_manage_swipe_count)
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
        # 扣除前置材料（子类可覆盖）
        self.deduct_materials(product, actual_number)
        logger.info(f"已安排生产：{product} x{actual_number}")
        self.post_close()
        # 返回实际生产数量
        return actual_number

    def deduct_materials(self, product, number):
        """扣除前置材料（包括套餐原材料）"""
        # 扣除套餐原材料
        if product in self.meal_compositions:
            composition = self.meal_compositions[product]
            quantity_per = composition.get('quantity_per', 1)
            for material in composition['required']:
                material_needed = number * quantity_per
                if material in self.warehouse_counts:
                    self.warehouse_counts[material] -= material_needed
                    logger.info(f"扣除原材料：{material} -{material_needed} (用于制作 {product})")

    def get_idle_posts(self):
        """获取空闲的岗位ID列表（通用）"""
        return [post_id for post_id, post_info in self.posts.items()
                if post_info['status'] == 'idle']

    # ============ 核心逻辑 ============

    def _schedule_and_track(self, produced_pass):
        """排产并将本轮产出记录到 produced_pass。
        produced_pass 跨多次排产累加，让后续 _compute_base_demands 的 current_totals
        能看到刚生产但未入库的量（不修改 warehouse_counts——仓库里确实还没有）。
        """
        if not self.to_post_products:
            return
        to_post_snapshot = dict(self.to_post_products)
        self.schedule_production()
        for name in to_post_snapshot:
            remaining = self.to_post_products.get(name, 0)
            produced_qty = to_post_snapshot[name] - remaining
            if produced_qty > 0:
                produced_pass[name] = produced_pass.get(name, 0) + produced_qty

    def _compute_base_demands(self, check_materials=False, force_skip=None):
        """计算基础需求：严格按槽位顺序处理，找到第一个有缺口的槽位
        即停止，后续槽位本轮不处理。

        保留线：取本轮已迭代槽位中各产品的最高目标（无缺口时覆盖全部
        槽位，全部达标时保留线取最大目标），扣除后 current_totals 为
        超额库存，可作为原料被后续槽位消费。

        Args:
            check_materials: False（默认）需求计算，原料为0不阻断，留给
                             process_meal_requirements 分解。
                             True 排产失败后使用，严格检查零库存来跳过缺口。
            force_skip: 强制跳过的产品名集合。排产多次失败（非原料原因如
                        角色被占）时使用，让本轮不再停留在这个缺口上。
        """
        # ============ 基础需求计算 ============
        logger.info("阶段：基础需求" + ("（严格模式）" if check_materials else ""))

        self.to_post_products = {}
        virtual_totals = dict(self.current_totals)
        force_skip = force_skip or set()

        # 遍历槽位，找到第一个有缺口且可生产的就只处理它
        break_idx = len(self.post_products)
        for idx, (name, target) in enumerate(self.post_products):
            current = virtual_totals.get(name, 0)
            if current < target:
                if name in force_skip:
                    logger.info(f"槽位{idx + 1} {name} 本轮已尝试失败，强制跳过")
                    continue
                deficit = target - current
                # check_materials=True 时严格检查零库存，用于跳过无法生产的缺口
                if self.get_max_producible(
                        name, min(self.POST_PRODUCE_LIMIT, deficit),
                        skip_zero_materials=not check_materials) <= 0:
                    logger.info(f"槽位{idx + 1} {name} 材料完全不足，本轮跳过")
                    continue
                self.to_post_products[name] = deficit
                virtual_totals[name] = target
                break_idx = idx
                break

        # 保留线：只取已迭代槽位（含 break 点）中的最高目标
        max_targets = {}
        for name, target in self.post_products[:break_idx + 1]:
            max_targets[name] = max(max_targets.get(name, 0), target)
        for name, max_target in max_targets.items():
            current = self.current_totals.get(name, 0)
            if current < max_target:
                self.current_totals[name] = 0
            else:
                self.current_totals[name] = current - max_target

    def run(self):
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

            # 保存原始库存，retry 时恢复
            _orig_totals = dict(self.current_totals)
            self._compute_base_demands()

            logger.info(f"待完成备餐: {self.to_post_products}")
            logger.info(f"当前剩余库存: {self.current_totals}")
            # ============ 处理套餐分解 ============
            if self.to_post_products:
                self.to_post_products = self.process_meal_requirements(self.to_post_products)
                logger.info(f"基础需求生产计划: {self.to_post_products}")

            # ============ 安排基础需求生产（循环直到无空岗或无缺口） ============
            _produced_pass = {}  # 本次 run() 调用中已生产的累计
            _force_skip_run = set()  # 排产多次无法生产的缺口（非原料原因），本轮强制跳过
            _loop_count = 0

            self._schedule_and_track(_produced_pass)

            while self.get_idle_posts():
                _loop_count += 1
                if _loop_count > self._MAX_FILL_LOOP:
                    logger.warning(f"[循环] 已达最大迭代次数 {self._MAX_FILL_LOOP}，强制退出")
                    break
                self.current_totals = dict(_orig_totals)
                for name, qty in _produced_pass.items():
                    self.current_totals[name] = self.current_totals.get(name, 0) + qty

                self._compute_base_demands(force_skip=_force_skip_run)
                if not self.to_post_products:
                    logger.info("所有槽位需求已满足")
                    break

                self.to_post_products = self.process_meal_requirements(self.to_post_products)
                logger.info(f"基础需求生产计划: {self.to_post_products}")

                prev_pass_total = sum(_produced_pass.values())
                self._schedule_and_track(_produced_pass)

                if sum(_produced_pass.values()) == prev_pass_total and self.to_post_products:
                    # 先切严格模式（绕"原料真没有"的坎儿）
                    logger.info("[循环] 当前缺口排产失败，切换严格模式扫描")
                    self.to_post_products = {}
                    self.current_totals = dict(_orig_totals)
                    for name, qty in _produced_pass.items():
                        self.current_totals[name] = self.current_totals.get(name, 0) + qty
                    self._compute_base_demands(check_materials=True)
                    if not self.to_post_products:
                        break
                    self.to_post_products = self.process_meal_requirements(self.to_post_products)
                    logger.info(f"基础需求生产计划（严格模式）: {self.to_post_products}")

                    strict_prev_total = sum(_produced_pass.values())
                    self._schedule_and_track(_produced_pass)

                    if sum(_produced_pass.values()) == strict_prev_total and self.to_post_products:
                        # 严格模式也无产出 → 非原料原因（角色被占等），强制跳过
                        stuck_now = set(self.to_post_products.keys())
                        logger.info(f"[循环] 严格模式也无产出，强制跳过: {stuck_now}")
                        _force_skip_run.update(stuck_now)
                        self.to_post_products = {}
                    continue

            # ============ 检查是否还有空闲岗位，安排特殊餐品或常驻餐品 ============
            # 重新检查空闲岗位（因为可能部分岗位被基础需求占用）
            idle_posts_after_basic = self.get_idle_posts()

            # 获取特殊餐品和常驻餐品配置
            special_food = self.special_food
            away_cook = getattr(self.config, self.config_away_cook, None)

            # 检查特殊餐品是否为有效值（不为None且不为"None"）
            has_special_food = (special_food and special_food != "None" and
                                special_food in self.name_to_config)

            # 检查常驻餐品是否为有效值（不为None且不为"None"）
            has_away_cook = (away_cook and away_cook != "None" and
                             away_cook in self.name_to_config)

            if idle_posts_after_basic and (has_special_food or has_away_cook):
                logger.info(f"基础需求完成后，还有 {len(idle_posts_after_basic)} 个空闲岗位")

                # 根据不同情况安排生产
                for post_id in idle_posts_after_basic:
                    post_num = post_id[-1]
                    time_var_name = f'{self.time_prefix}{post_num}'

                    if has_special_food and has_away_cook:
                        # 情况1：既有特殊餐品又有常驻餐品
                        logger.info(f"同时有特殊餐品 {special_food} 和常驻餐品 {away_cook}")
                        logger.info(f"优先尝试生产特殊餐品，如果原料不足则生产常驻餐品")

                        # 尝试生产特殊餐品（如果原料不足会自动尝试常驻餐品）
                        result = self.post_produce(
                            post_id,
                            product=special_food,
                            number=self.POST_PRODUCE_LIMIT,
                            time_var_name=time_var_name,
                            product2=away_cook
                        )

                        if result == 0:
                            # 特殊餐品和常驻餐品都原料不足
                            logger.info(f"特殊餐品 {special_food} 和常驻餐品 {away_cook} 都原料不足，保持岗位空闲")
                            break
                        else:
                            logger.info(f"已为岗位 {post_id} 安排生产")

                    elif has_special_food and not has_away_cook:
                        # 情况2：只有特殊餐品，没有常驻餐品
                        logger.info(f"只有特殊餐品 {special_food}，没有常驻餐品")

                        result = self.post_produce(
                            post_id,
                            product=special_food,
                            number=self.POST_PRODUCE_LIMIT,
                            time_var_name=time_var_name
                        )

                        if result == 0:
                            # 特殊餐品原料不足
                            logger.info(f"特殊餐品 {special_food} 原料不足，保持岗位空闲")
                            break
                        else:
                            logger.info(f"已为岗位 {post_id} 安排生产特殊餐品")

                    elif not has_special_food and has_away_cook:
                        # 情况3：只有常驻餐品，没有特殊餐品
                        logger.info(f"只有常驻餐品 {away_cook}，没有特殊餐品")

                        # 检查材料限制
                        batch_size = self.POST_PRODUCE_LIMIT
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

                    else:
                        # 情况4：既没有特殊餐品也没有常驻餐品
                        logger.info("未设置特殊餐品或常驻餐品，保持空闲")
                        break  # 退出循环，不再处理其他空闲岗位

            elif idle_posts_after_basic:
                # 有空闲岗位但没有设置特殊餐品或常驻餐品
                logger.info(f"有 {len(idle_posts_after_basic)} 个空闲岗位，但未设置特殊餐品或常驻餐品，保持空闲")

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

    def process_meal_requirements(self, source_products):
        """处理套餐需求（修正版）"""
        logger.info(f"=== 进入process_meal_requirements ===")
        logger.info(f"传入的需求: {source_products}")

        result = {}

        # 1. 将需求分为套餐需求和基础餐品需求
        meal_demands = {}
        base_demands = {}

        for product, quantity in source_products.items():
            if quantity <= 0:
                continue
            if product in self.meal_compositions:
                meal_demands[product] = quantity
                logger.info(f"  识别为套餐: {product} x{quantity}")
            else:
                base_demands[product] = quantity
                logger.info(f"  识别为基础餐品: {product} x{quantity}")

        logger.info(f"套餐需求: {meal_demands}")
        logger.info(f"基础需求: {base_demands}")

        # 2. 处理套餐需求 - 直接加入结果（套餐可以直接生产）
        # 注意：这里传入的已经是净需求，不需要再扣除库存
        for meal, meal_quantity in meal_demands.items():
            if meal_quantity > 0:
                result[meal] = meal_quantity
                logger.info(f"  套餐直接生产: {meal} x{meal_quantity}")

        # 3. 处理基础需求（这些可能是套餐的原材料）
        material_needs = {}

        # 计算所有套餐需要的原材料总量
        for meal, meal_quantity in meal_demands.items():
            if meal_quantity > 0 and meal in self.meal_compositions:
                composition = self.meal_compositions[meal]
                for material in composition['required']:
                    needed = meal_quantity * composition.get('quantity_per', 1)
                    material_needs[material] = material_needs.get(material, 0) + needed
                    logger.info(f"  套餐 {meal} 需要原材料: {material} x{needed}")

        logger.info(f"原材料总需求: {material_needs}")

        # 4. 处理基础需求，并考虑原材料需求
        for base_product, base_quantity in base_demands.items():
            logger.info(f"  处理基础餐品 {base_product}: 基础需求={base_quantity}")

            # 总需求 = 基础需求（已经是净需求） + 套餐原材料需求
            total_needed = base_quantity

            # 如果这个基础餐品也是套餐的原材料，需要加上原材料需求
            if base_product in material_needs:
                # 注意：原材料需求需要扣除库存（因为之前没扣过）
                raw_material_needed = material_needs[base_product]

                # 检查原材料库存
                current_stock = self.current_totals.get(base_product, 0)
                logger.info(f"    原材料需求: +{raw_material_needed}, 当前库存: {current_stock}")

                # 计算原材料净需求
                net_raw_needed = max(0, raw_material_needed - current_stock)
                total_needed += net_raw_needed

                logger.info(f"    原材料净需求: {net_raw_needed}, 总需求: {total_needed}")

                # 从material_needs中移除，避免重复计算
                del material_needs[base_product]
            else:
                # 不是原材料，直接使用基础需求
                logger.info(f"    总需求: {total_needed}")

            if total_needed > 0:
                result[base_product] = total_needed
                logger.info(f"    添加到生产计划: {base_product} x{total_needed}")
            else:
                logger.info(f"    不需要生产")

        # 5. 处理剩余的原材料需求（这些基础餐品不在基础需求列表中）
        for material, material_quantity in material_needs.items():
            logger.info(f"  处理剩余原材料 {material}: 需求={material_quantity}")

            current_stock = self.current_totals.get(material, 0)
            logger.info(f"    当前总库存: {current_stock}")

            net_needed = max(0, material_quantity - current_stock)
            if net_needed > 0:
                result[material] = net_needed
                logger.info(f"    添加到生产计划: {material} x{net_needed}")
            else:
                logger.info(f"    库存充足，不需要生产")

        logger.info(f"无特殊材料限制下的生产计划: {result}")
        # 6. 考虑特殊材料限制
        result = self.apply_special_material_constraints(result)

        logger.info(f"最终生产计划: {result}")
        logger.info(f"=== 离开process_meal_requirements ===")

        return result

    def get_max_producible(self, product, requested_quantity, skip_zero_materials=False):
        """获取最大可生产数量。

        Args:
            product: 产品名称
            requested_quantity: 请求生产数量
            skip_zero_materials: 需求计算阶段为 True，原料库存为 0 时不阻断套餐，
                                 交给 process_meal_requirements 分解需求。
                                 排产阶段为 False，严格检查避免游戏层拒绝导致 stalled。
        """
        max_producible = requested_quantity
        logger.info(f"检查 {product} 的最大可生产数量，需求: {requested_quantity}")

        # 1. 如果是套餐，检查原材料库存
        if product in self.meal_compositions:
            composition = self.meal_compositions[product]
            for material in composition['required']:
                # 使用仓库实际库存（生产会消耗仓库库存）
                material_stock = self.warehouse_counts.get(material, 0)
                quantity_per = composition.get('quantity_per', 1)
                if quantity_per == 0:
                    continue
                max_by_material = material_stock // quantity_per
                if max_by_material <= 0:
                    if skip_zero_materials and material_stock == 0:
                        # 需求计算阶段且真零库存：不阻断，留给 process_meal_requirements 分解
                        logger.info(f"  {product} 原材料 {material} 库存为 0，需求计算阶段跳过此原料限制")
                        continue
                    else:
                        # 排产阶段 或 有但不满足一批：严格处理
                        logger.info(f"  {product} 缺少原材料: {material} (库存: {material_stock})")
                        return 0
                max_producible = min(max_producible, max_by_material)
                logger.info(f"  {product} 原材料 {material}: 库存 {material_stock}，每个需要 {quantity_per}，最大生产 {max_by_material}")

        # 2. 检查岗位数量限制
        max_producible = min(max_producible, self.POST_PRODUCE_LIMIT)
        logger.info(f"岗位限制: 最多生产{self.POST_PRODUCE_LIMIT}个，当前限制后: {max_producible}")

        # 3. 检查特殊材料（被子类覆盖）
        max_producible = self.check_special_materials(product, max_producible)
        logger.info(f"特殊材料检查后: {max_producible}")

        return max_producible

    def apply_special_material_constraints(self, requirements):
        """应用特殊材料限制（需求阶段）。子类可覆盖此方法。

        Args:
            requirements: 字典，{产品名: 需求数量}

        Returns:
            调整后的需求字典
        """
        return requirements

    def process_away_cook(self):
        """处理常驻餐品"""
        away_cook = getattr(self.config, self.config_away_cook, None)

        # 检查 away_cook 是否有效
        if away_cook and away_cook != "None" and away_cook in self.name_to_config:
            self.to_post_products = {away_cook: 9999}
            logger.info(f"常驻餐品模式：生产 {away_cook}")
        else:
            self.to_post_products = {}
            if away_cook is None or away_cook == "None":
                logger.info("未设置常驻餐品，保持空闲")
            elif away_cook not in self.name_to_config:
                logger.info(f"常驻餐品 '{away_cook}' 不在商品列表中，保持空闲")

    def schedule_production(self):
        """安排生产，利用所有空闲岗位"""
        if not self.to_post_products:
            logger.info("没有需要生产的餐品")
            return

        # 获取空闲岗位
        idle_posts = self.get_idle_posts()
        if not idle_posts:
            logger.info("没有空闲的岗位")
            return

        # 检查是否为常驻餐品模式（无限数量生产）
        is_away_cook_mode = False
        away_cook_product = None
        for product, quantity in self.to_post_products.items():
            if quantity == 9999:  # 常驻餐品模式的标识
                is_away_cook_mode = True
                away_cook_product = product
                break

        if is_away_cook_mode:
            logger.info(f"常驻餐品模式：为所有空闲岗位安排生产 {away_cook_product}")
            # 为每个空闲岗位安排生产
            for post_id in idle_posts:
                # 检查材料限制
                batch_size = self.POST_PRODUCE_LIMIT
                batch_size = self.get_max_producible(away_cook_product, batch_size)

                if batch_size <= 0:
                    logger.info(f"生产 {away_cook_product} 的前置材料不足，跳过岗位 {post_id}")
                    continue

                # 分配生产
                post_num = post_id[-1]
                time_var_name = f'{self.time_prefix}{post_num}'
                self.post_produce(post_id, away_cook_product, batch_size, time_var_name)

            logger.info("常驻餐品模式：已为所有空闲岗位安排生产")
            return

        # 非常驻餐品模式：处理所有产品需求
        products_to_process = list(self.to_post_products.items())

        # 如果有多个产品需求，按槽位顺序排序（原料优先）
        if len(products_to_process) > 1:
            # 构建槽位顺序映射
            slot_index = {}
            idx = 0
            for name, _ in self.post_products:
                if name not in slot_index:
                    slot_index[name] = idx
                    idx += 1

            # 原料取其服务套餐中最早槽位的索引
            for meal, comp in self.meal_compositions.items():
                if meal in slot_index:
                    meal_slot = slot_index[meal]
                    for mat in comp['required']:
                        if mat not in slot_index or slot_index[mat] > meal_slot:
                            slot_index[mat] = meal_slot

            # 按槽位顺序排序，同槽位内原料优先于成品
            # 从套餐组成中提取所有原料名，避免双重身份产品被误判为非原料
            material_names = set()
            for comp in self.meal_compositions.values():
                material_names.update(comp['required'])

            # 未在 slot_index 中的产品默认排在已知槽位之后
            default_slot = len(slot_index) + 1

            def slot_priority(item):
                product, _ = item
                slot = slot_index.get(product, default_slot)
                is_material = product in material_names
                return (slot, 0 if is_material else 1)

            products_to_process.sort(key=slot_priority)

        # 为每个空闲岗位分配生产任务
        _produced_any = set()  # 本轮至少产出了1个的产品
        post_index = 0
        total_idle_posts = len(idle_posts)

        for product, required_quantity in products_to_process:
            if required_quantity <= 0:
                continue

            # 获取当前还有需求的量
            remaining_need = self.to_post_products.get(product, 0)
            if remaining_need <= 0:
                continue

            logger.info(f"尝试安排生产 {product}，需求: {remaining_need}")

            # 为每个空闲岗位分配生产（直到需求满足或没有空闲岗位）
            while remaining_need > 0 and post_index < total_idle_posts:
                post_id = idle_posts[post_index]

                # 计算最大可生产数量
                max_producible = self.get_max_producible(
                    product, min(self.POST_PRODUCE_LIMIT, remaining_need))

                if max_producible <= 0:
                    logger.info(f"生产 {product} 的材料暂时不足，保留在计划中等待下一轮")
                    break  # 跳过当前产品，但保留在 to_post_products 中

                # 分配生产
                post_num = post_id[-1]
                time_var_name = f'{self.time_prefix}{post_num}'

                # 安排生产并获取实际生产数量
                actual_number = self.post_produce(post_id, product, max_producible, time_var_name)

                # 如果实际生产数量为0，说明原料不足
                if actual_number == 0:
                    logger.info(f"生产 {product} 时检测到原料不足，保留在计划中等待下一轮")
                    break  # 跳过当前产品，但保留在 to_post_products 中

                # 记录已产出（部分生产不算停滞）
                _produced_any.add(product)
                # 更新需求
                if product in self.to_post_products:
                    self.to_post_products[product] -= actual_number
                    if self.to_post_products[product] <= 0:
                        del self.to_post_products[product]

                # 更新剩余需求
                remaining_need = self.to_post_products.get(product, 0)

                # 移动到下一个岗位
                post_index += 1

            # 如果所有岗位都已分配，退出循环
            if post_index >= total_idle_posts:
                break

        if self.to_post_products:
            logger.info(f"生产安排完成，剩余需求: {self.to_post_products}")
        else:
            logger.info("所有可安排的产品已安排生产")

    def check_special_materials(self, product, batch_size):
        """检查特殊材料（子类可覆盖）"""
        # 默认实现不检查特殊材料
        return batch_size
