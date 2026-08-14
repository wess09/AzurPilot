"""岛屿渔业模块。

管理岛屿渔业系统的自动化操作，包括鱼苗商店的分类浏览（淡水/海水/其他）与采购。
支持渔场库存检测、鱼苗购买与鱼获处理，与仓库 OCR 联动获取物品数量。
"""
from module.island_fishery.assets import *
from module.island_rancher.assets import *
from module.island.island import *
from module.base.button import Button

def _click_area(device, area):
    """从区域坐标创建临时Button并点击，避免多服务器Button兼容问题"""
    a = area.get('cn', area) if isinstance(area, dict) else area
    btn = Button(area=a, color=(0,0,0), button=a, file='')
    device.click(btn)
# 重新导入鱼苗商店专用按钮（覆盖 island.assets 中的同名旧定义）
from module.island_fishery.assets import (
    ISLAND_FISH_FRY_SHOP_FRESHWATER,
    ISLAND_FISH_FRY_SHOP_FRESHWATER_CHECK,
    ISLAND_FISH_FRY_SHOP_OTHER,
    ISLAND_FISH_FRY_SHOP_OTHER_CHECK,
    ISLAND_FISH_FRY_SHOP_SEAWATER,
    ISLAND_FISH_FRY_SHOP_SEAWATER_CHECK,
    ISLAND_FRY_SHOP_CHECK,
    SHOP_FRY_BASS,
    SHOP_FRY_YELLOWFIN_TUNA,
    SHOP_FRY_SHELL,
    SHOP_FRY_SHRIMP,
    SHOP_FRY_CRAB,
    SHOP_FRY_SQUID,
    SHOP_FRY_SEA_CUCUMBER,
)
from module.island.warehouse import *
from datetime import timedelta

from module.config.time_source import now as current_time
from module.handler.login import LoginHandler
from module.logger import logger


class IslandFishery(Island, WarehouseOCR, LoginHandler):
    def __init__(self, *args, **kwargs):
        Island.__init__(self, *args, **kwargs)
        WarehouseOCR.__init__(self)
        self.fishery_positions = self.config.IslandFishery_Positions
        self.fishery_threshold = {
            'bass': self.config.IslandFishery_MinBass,
            'yellowfin_tuna': self.config.IslandFishery_MinYellowfinTuna,
            'shell': self.config.IslandFishery_MinShell,
            'shrimp': self.config.IslandFishery_MinShrimp,
            'crab': self.config.IslandFishery_MinCrab,
            'crayfish': self.config.IslandFishery_MinCrayfish,
            'squid': self.config.IslandFishery_MinSquid,
            'sea_cucumber': self.config.IslandFishery_MinSeaCucumber,
        }
        self.plant_yellowfin_tuna = self.config.IslandFishery_PlantYellowfinTuna
        self.rancher_filter = self.config.IslandFishery_RancherFilter

        # 产品配置
        self.FISHERY_ITEMS = [
            {'cn_name': '鲈鱼', 'name': 'bass', 'template': TEMPLATE_BASS, 'var_name': 'bass',
             'selection': SELECT_BASS, 'selection_check': SELECT_BASS_CHECK,
             'post_action': POST_BASS, 'category': 'fishery',
             'shop': SHOP_FRY_BASS, 'tab': 'freshwater', 'yield': 6, 'buy_max': 4},
            {'cn_name': '黄鳍金枪鱼', 'name': 'yellowfin_tuna', 'template': TEMPLATE_YELLOWFIN_TUNA, 'var_name': 'yellowfin_tuna',
             'selection': SELECT_YELLOWFIN_TUNA, 'selection_check': SELECT_YELLOWFIN_TUNA_CHECK,
             'post_action': POST_YELLOWFIN_TUNA, 'category': 'fishery',
             'shop': SHOP_FRY_YELLOWFIN_TUNA, 'tab': 'seawater', 'yield': 2, 'buy_max': 4},
            {'cn_name': '贝壳', 'name': 'shell', 'template': TEMPLATE_SHELL, 'var_name': 'shell',
             'selection': SELECT_SHELL, 'selection_check': SELECT_SHELL_CHECK,
             'post_action': POST_SHELL, 'category': 'fishery',
             'shop': SHOP_FRY_SHELL, 'tab': 'other', 'yield': 10, 'buy_max': 4},
            {'cn_name': '小河虾', 'name': 'shrimp', 'template': TEMPLATE_SHRIMP, 'var_name': 'shrimp',
             'selection': SELECT_SHRIMP, 'selection_check': SELECT_SHRIMP_CHECK,
             'post_action': POST_SHRIMP, 'category': 'fishery',
             'shop': SHOP_FRY_SHRIMP, 'tab': 'other', 'yield': 12, 'buy_max': 7},
            {'cn_name': '小龙虾', 'name': 'crayfish', 'template': TEMPLATE_CRAYFISH, 'var_name': 'crayfish',
             'selection': SELECT_CRAYFISH, 'selection_check': SELECT_CRAYFISH_CHECK,
             'post_action': POST_CRAYFISH, 'category': 'fishery',
             'shop': SHOP_FRY_CRAYFISH, 'tab': 'other', 'yield': 8, 'buy_max': 4},
            {'cn_name': '螃蟹', 'name': 'crab', 'template': TEMPLATE_CRAB, 'var_name': 'crab',
             'selection': SELECT_CRAB, 'selection_check': SELECT_CRAB_CHECK,
             'post_action': POST_CRAB, 'category': 'fishery',
             'shop': SHOP_FRY_CRAB, 'tab': 'other', 'yield': 4, 'buy_max': 4},
            {'cn_name': '鱿鱼', 'name': 'squid', 'template': TEMPLATE_SQUID, 'var_name': 'squid',
             'selection': SELECT_SQUID, 'selection_check': SELECT_SQUID_CHECK,
             'post_action': POST_SQUID, 'category': 'fishery',
             'shop': SHOP_FRY_SQUID, 'tab': 'other', 'yield': 4, 'buy_max': 4},
            {'cn_name': '海参', 'name': 'sea_cucumber', 'template': TEMPLATE_SEA_CUCUMBER, 'var_name': 'sea_cucumber',
             'selection': SELECT_SEA_CUCUMBER, 'selection_check': SELECT_SEA_CUCUMBER_CHECK,
             'post_action': POST_SEA_CUCUMBER, 'category': 'fishery',
             'shop': SHOP_FRY_SEA_CUCUMBER, 'tab': 'other', 'yield': 2, 'buy_max': 4},
        ]

        self.name_to_config = {}
        for item in self.FISHERY_ITEMS:
            self.name_to_config[item['name']] = item

        # 岗位信息
        self.posts = {
            'ISLAND_FISHERY_POST1': {'button': ISLAND_FISHERY_POST1, 'crop': None, 'runs': 0, 'state': 'unknown'},
            'ISLAND_FISHERY_POST2': {'button': ISLAND_FISHERY_POST2, 'crop': None, 'runs': 0, 'state': 'unknown'},
            'ISLAND_FISHERY_POST3': {'button': ISLAND_FISHERY_POST3, 'crop': None, 'runs': 0, 'state': 'unknown'},
        }

        self.to_plant_list = []
        self.inventory_counts = {}
        self.fishery_times = [None] * self.fishery_positions

    def check_inventory_and_prepare_list(self):
        """检查库存并准备需要补种的列表（根据产量计算需购买鱼苗数）"""
        inventory = self.warehouse_inventory()
        self.inventory_counts = inventory
        self.to_plant_list = []

        for item_config in self.FISHERY_ITEMS:
            item_name = item_config['name']
            count = inventory.get(item_name, 0)
            threshold = self.fishery_threshold.get(item_name, 50)
            yield_amount = item_config.get('yield', 1)
            if count < threshold:
                deficit = threshold - count
                fry_needed = (deficit + yield_amount - 1) // yield_amount  # 向上取整
                logger.info(f"[岛屿-渔场] {self._item_cn(item_name)}: 库存{count}<阈值{threshold}, 缺{deficit}, "
                            f"每苗产{yield_amount}, 需购买{fry_needed}个鱼苗")
                for _ in range(fry_needed):
                    self.to_plant_list.append(item_name)

    def _remove_plant_demand(self, product, quantity):
        """从补种需求中扣除已在岗位中的鱼苗数量。"""
        removed = 0
        for _ in range(max(0, quantity)):
            try:
                self.to_plant_list.remove(product)
                removed += 1
            except ValueError:
                break
        return removed

    def _build_supply_plant_products(self, idle_count):
        """按库存升序轮转分配岗位，未达标物品优先补足（如 A B C A B ...）。"""
        # 收集未达标产品及其所需岗位数，按当前库存升序排序（库存最少的最优先）
        demand = []
        for item_config in self.FISHERY_ITEMS:
            product = item_config['name']
            fry_needed = self.to_plant_list.count(product)
            if fry_needed <= 0:
                continue
            buy_max = item_config.get('buy_max', 4)
            post_capacity = buy_max + 1
            post_needed = (fry_needed + post_capacity - 1) // post_capacity
            stock = self.inventory_counts.get(product, 0)
            demand.append((product, post_needed, stock))
            logger.info(
                f"{self._item_cn(product)}: 需养殖{fry_needed}个鱼苗，每岗容量{post_capacity}，"
                f"库存{stock}，需要{post_needed}个岗位"
            )

        demand.sort(key=lambda x: x[2])
        products_to_plant = []
        supply_post_counts = {}
        assigned = {product: 0 for product, _, _ in demand}
        remaining_idle = idle_count
        idx = 0

        # 轮转分配：按库存升序循环，每个未达标产品至少一岗，岗位充足时继续补最少的
        while remaining_idle > 0 and demand and any(assigned[p] < n for p, n, _ in demand):
            product, post_needed, _ = demand[idx % len(demand)]
            if assigned[product] < post_needed:
                products_to_plant.append(product)
                supply_post_counts[product] = supply_post_counts.get(product, 0) + 1
                assigned[product] += 1
                remaining_idle -= 1
            idx += 1

        return products_to_plant, remaining_idle, supply_post_counts

    def _remove_working_fishery_demand(self):
        """从补养殖需求中扣除首轮岗位扫描发现的工作中鱼苗数量。"""
        for post_id, post_info in self.posts.items():
            product_name = post_info.get('crop')
            if product_name not in self.name_to_config:
                continue
            post_number = post_info.get('runs') or 1
            removed = self._remove_plant_demand(product_name, post_number)
            if removed:
                logger.info(f"[岛屿-渔场] 已在养殖中的{self._item_cn(product_name)}扣除补种需求: {removed}/{post_number} ({post_id})")

    @staticmethod
    def _post_available_for_dispatch(post_info):
        """只有检测后处于空闲状态的岗位才可在本轮派遣。"""
        return post_info.get('state') == 'idle'

    def _planned_fry_purchase_quantity(self, product, post_count, supply_post_counts, default_post_counts):
        """计算本轮需要购买的鱼苗数量，保证每个同类岗位至少能下单。"""
        buy_max = self.name_to_config[product].get('buy_max', 4)
        post_capacity = buy_max + 1
        supply_posts = supply_post_counts.get(product, 0)
        default_posts = default_post_counts.get(product, 0)
        supply_demand = len([p for p in self.to_plant_list if p == product])
        max_purchase = post_count * buy_max
        base_purchase = min(supply_demand, supply_posts * buy_max) + default_posts * buy_max
        min_purchase_for_posts = min(max_purchase, post_capacity * (post_count - 1) + 1)
        total_purchase = min(max_purchase, max(base_purchase, min_purchase_for_posts))
        return total_purchase, supply_demand, buy_max

    def warehouse_inventory(self):
        """获取仓库库存信息"""
        self.warehouse_filter('fishery')
        image = self.device.screenshot()
        results = {}
        for item_config in self.FISHERY_ITEMS:
            count = self.ocr_item_quantity(image, item_config['template'])
            results[item_config['name']] = count
            setattr(self, item_config['var_name'], count)
            logger.info(f"{item_config.get('cn_name', item_config['name'])}: {count}")
        return results

    def post_plant_check(self):
        """检查岗位正在生产什么"""
        for item in self.FISHERY_ITEMS:
            if self.appear(item['post_action']):
                return item['name']
        return None

    def _fishery_tab_buttons(self, target_tab):
        if target_tab == 'freshwater':
            return ISLAND_FISH_FRY_SHOP_FRESHWATER_CHECK, ISLAND_FISH_FRY_SHOP_FRESHWATER
        if target_tab == 'seawater':
            return ISLAND_FISH_FRY_SHOP_SEAWATER_CHECK, ISLAND_FISH_FRY_SHOP_SEAWATER
        if target_tab == 'other':
            return ISLAND_FISH_FRY_SHOP_OTHER_CHECK, ISLAND_FISH_FRY_SHOP_OTHER
        logger.warning(f"[岛屿-渔场] 未知页签: {target_tab}")
        return None, None

    def decided_lists(self, post_button, post_id, post_index):
        """检查岗位状态并更新列表，同时记录完成时间"""
        collected = False
        was_complete = False
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()
        was_complete = self.appear(ISLAND_WORK_COMPLETE, offset=1)
        if was_complete or self.appear(POST_GET, offset=(50, 0)):
            collected = True
            self.post_get_stay()
            self.device.screenshot()

        if self.appear(ISLAND_WORKING):
            product_name = self.post_plant_check()
            ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                    alphabet='0123456789')
            post_number = ocr_post_number.ocr(self.device.image) or 1
            self.posts[post_id]['crop'] = product_name or 'unknown'
            self.posts[post_id]['runs'] = post_number
            self.posts[post_id]['state'] = 'working'
            # 记录正在工作中的岗位的完成时间
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            finish_time = current_time() + time_value
            if post_index < len(self.fishery_times):
                self.fishery_times[post_index] = finish_time
        elif self.appear(ISLAND_POST_SELECT, offset=1):
            self.posts[post_id]['crop'] = None
            self.posts[post_id]['runs'] = 0
            self.posts[post_id]['state'] = 'idle'
            if post_index < len(self.fishery_times):
                self.fishery_times[post_index] = None
        else:
            if was_complete:
                self.posts[post_id]['crop'] = None
                self.posts[post_id]['runs'] = 0
                self.posts[post_id]['state'] = 'idle'
                if post_index < len(self.fishery_times):
                    self.fishery_times[post_index] = None
                logger.warning(f"[岛屿-渔场] {post_id}: 收取后状态未识别，按收取前完成态视为空闲")
            else:
                self.posts[post_id]['crop'] = 'unknown'
                self.posts[post_id]['runs'] = 0
                self.posts[post_id]['state'] = 'working'
                logger.warning(f"[岛屿-渔场] {post_id}: 岗位状态未识别，按工作中处理")
        self.post_close()
        return collected

    def post_plant(self, post_button, product, post_index, required_quantity=1):
        """在指定岗位种植指定产品，并记录完成时间"""
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()
        item_config = self.name_to_config[product]
        selection = item_config['selection']
        selection_check = item_config['selection_check']
        tab_check, tab_button = self._fishery_tab_buttons(item_config['tab'])
        while 1:
            self.device.screenshot()
            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.select_character(character_list=self.rancher_filter):
                    if not self.confirm_selected_character(f"{product}养殖派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return False
                else:
                    logger.warning(f"[岛屿-渔场] {self._item_cn(product)}养殖派遣无可用角色: {self.rancher_filter}")
                    self.back_to_postmanage_from_dispatch()
                    return False
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                if self.select_product(selection, selection_check):
                    if self.ensure_select_product_material(
                            item_button=item_config['shop'],
                            required_quantity=required_quantity,
                            shop_check=ISLAND_FRY_SHOP_CHECK,
                            item_name=f"{self._item_cn(product)}鱼苗",
                            tab_check=tab_check,
                            tab_button=tab_button,
                    ):
                        continue
                    self.device.sleep(0.3)
                    if not self.confirm_post_add_order(f"{product}养殖派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return False
                    break
                else:
                    return self._handle_select_product_failure(product)

        self.post_open(post_button)
        self.device.sleep(0.5)
        self.device.screenshot()
        # OCR并记录完成时间
        time_work = Duration(ISLAND_WORKING_TIME)
        time_value = time_work.ocr(self.device.image)
        finish_time = current_time() + time_value
        ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                alphabet='0123456789')
        post_number = ocr_post_number.ocr(self.device.image) or 1
        if post_index < len(self.fishery_times):
            self.fishery_times[post_index] = finish_time

        # 更新岗位作物信息
        for post_id, post_info in self.posts.items():
            if post_info['button'] == post_button:
                post_info['crop'] = product
                post_info['runs'] = post_number
                post_info['state'] = 'working'
                break
        if product in self.to_plant_list:
            removed = self._remove_plant_demand(product, post_number)
            logger.info(f"[岛屿-渔场] 已安排养殖{self._item_cn(product)}扣除补种需求: {removed}/{post_number}")

        # 关闭详情弹窗，防止后续操作被弹窗遮挡
        self.post_close()
        return True

    def _build_fry_quantity_queue(self, products_to_plant, supply_post_counts, default_post_counts):
        """按岗位顺序分配本轮每个渔场岗位需要补足的鱼苗数量。"""
        product_counts = {}
        for product_name in products_to_plant:
            product_counts[product_name] = product_counts.get(product_name, 0) + 1

        product_quantities = {}
        for product, count in product_counts.items():
            total_purchase, supply_demand, buy_max = self._planned_fry_purchase_quantity(
                product, count, supply_post_counts, default_post_counts
            )
            logger.info(
                f"{product}鱼苗补货计划，补种需求{supply_demand}个，排产{count}岗，"
                f"本轮目标{total_purchase}个，每岗上限{buy_max}个"
            )
            remaining = total_purchase
            quantities = []
            for _ in range(count):
                buy_qty = min(buy_max, remaining) if remaining > 0 else 1
                quantities.append(max(1, buy_qty))
                remaining -= buy_qty
            product_quantities[product] = quantities

        quantity_queue = []
        used_counts = {}
        for product in products_to_plant:
            used_index = used_counts.get(product, 0)
            used_counts[product] = used_index + 1
            quantity_queue.append(product_quantities[product][used_index])
        return quantity_queue

    def run(self, ranch_finish_times=None):
        self.island_error = False

        # 重置渔场时间追踪列表
        self.fishery_times = [None] * self.fishery_positions

        # 首轮先检查岗位并收取已完成鱼获，确保随后读取的仓库库存包含本轮收获。
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()

        post_buttons = [
            self.posts['ISLAND_FISHERY_POST1']['button'],
            self.posts['ISLAND_FISHERY_POST2']['button'],
            self.posts['ISLAND_FISHERY_POST3']['button'],
        ]

        post_button_mapping = post_buttons[:self.fishery_positions]

        post_id_to_button = {}
        for i, button in enumerate(post_button_mapping):
            post_id = f'ISLAND_FISHERY_POST{i + 1}'
            post_id_to_button[post_id] = button

        idle_posts = []
        collected_posts = []

        logger.info("[岛屿-渔场] 首轮检查渔场岗位，收取已完成鱼获并记录工作中岗位")
        for i in range(self.fishery_positions):
            post_id = f'ISLAND_FISHERY_POST{i + 1}'
            button = post_id_to_button[post_id]

            if self.decided_lists(button, post_id, i):
                collected_posts.append(post_id)

            if self._post_available_for_dispatch(self.posts[post_id]):
                idle_posts.append({
                    'post_id': post_id,
                    'button': button,
                    'index': i,
                })

        if collected_posts:
            logger.info(f"[岛屿-渔场] 首轮渔场岗位检查已收取完成鱼获: {collected_posts}")
        else:
            logger.info("[岛屿-渔场] 首轮渔场岗位检查没有发现可收取鱼获")

        self.check_inventory_and_prepare_list()
        self._remove_working_fishery_demand()

        logger.info("[岛屿-渔场] \n当前库存统计:")
        logger.info(f"[岛屿-渔场] 渔场库存: {self._inv_cn(self.inventory_counts)}")

        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()

        logger.info(f"[岛屿-渔场] \n空闲岗位统计: {len(idle_posts)}个空闲岗位")

        if not idle_posts:
            logger.info("[岛屿-渔场] 没有空闲岗位，跳过养殖")
        else:
            # 确定需要养殖的产品
            products_to_plant, remaining_idle, supply_post_counts = self._build_supply_plant_products(len(idle_posts))
            default_post_counts = {}

            # 继续用剩余空闲岗位满足默认黄鳍金枪鱼岗位数
            already_planted_default = 0
            for i in range(self.fishery_positions):
                post_id = f'ISLAND_FISHERY_POST{i + 1}'
                if self.posts[post_id]['crop'] == 'yellowfin_tuna':
                    already_planted_default += 1

            logger.info(f"[岛屿-渔场] 已有{already_planted_default}个岗位养殖了黄鳍金枪鱼，配置要求{self.plant_yellowfin_tuna}个")

            need_default = max(0, self.plant_yellowfin_tuna - already_planted_default)

            if remaining_idle > 0 and need_default > 0:
                actual_default = min(remaining_idle, need_default)
                for _ in range(actual_default):
                    products_to_plant.append('yellowfin_tuna')
                    default_post_counts['yellowfin_tuna'] = default_post_counts.get('yellowfin_tuna', 0) + 1

            if products_to_plant:
                logger.info(f"[岛屿-渔场] \n需要养殖的产品: {products_to_plant}")
                fry_quantity_queue = self._build_fry_quantity_queue(
                    products_to_plant,
                    supply_post_counts,
                    default_post_counts,
                )

                # 养殖
                for i, post_info in enumerate(idle_posts):
                    if i >= len(products_to_plant):
                        logger.info(f"[岛屿-渔场] 跳过渔场岗位{post_info['post_id']}: 没有需要养殖的产品")
                        continue

                    product_to_plant = products_to_plant[i]
                    required_quantity = fry_quantity_queue[i]
                    logger.info(f"[岛屿-渔场] 尝试养殖渔场岗位{post_info['post_id']}: {product_to_plant}")

                    success = self.post_plant(
                        post_info['button'],
                        product_to_plant,
                        post_info['index'],
                        required_quantity=required_quantity,
                    )

                    if success:
                        logger.info(f"[岛屿-渔场] 养殖渔场岗位{post_info['post_id']}成功: {product_to_plant}")

        logger.info("[岛屿-渔场] \n渔场管理完成！")

        # 设置下次运行时间：合并牧场和渔场的计时器，取最早的时间
        future_finish = []
        six_hours_later = current_time() + timedelta(hours=6)
        future_finish.append(six_hours_later)
        # 合并牧场的结束时间（如果传入了的话）
        if ranch_finish_times:
            future_finish.extend(ranch_finish_times)
            logger.info(f'[岛屿-渔场] 合并牧场 {len(ranch_finish_times)} 个计时器')
        # === 修复：添加渔场自身的完成时间 ===
        fishery_finish_times = [t for t in self.fishery_times if t is not None]
        if fishery_finish_times:
            future_finish.extend(fishery_finish_times)
            logger.info(f'[岛屿-渔场] 合并渔场 {len(fishery_finish_times)} 个计时器')
        future_finish.sort()
        self.config.task_delay(target=future_finish)
        logger.info(f'[岛屿-渔场] 渔场任务完成，合并后总共 {len(future_finish)} 个计时器，下次运行时间: {future_finish[0]}')

        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")
