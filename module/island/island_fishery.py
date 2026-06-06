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
    ISLAND_FISH_FRY_SHOP_SEAWATER,
    ISLAND_FISH_FRY_SHOP_SEAWATER_CHECK,
    ISLAND_FRY_SHOP_CHECK,
    ISLAND_SHOP_GOTO_FISHERY_GEAR,
    SHOP_FRY_BASS,
    SHOP_FRY_YELLOWFIN_TUNA,
    SHOP_FRY_SHELL,
    SHOP_FRY_SHRIMP,
    SHOP_FRY_CRAB,
    SHOP_FRY_SQUID,
    SHOP_FRY_SEA_CUCUMBER,
)
from module.island.warehouse import *
from datetime import datetime, timedelta
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
            'squid': self.config.IslandFishery_MinSquid,
            'sea_cucumber': self.config.IslandFishery_MinSeaCucumber,
        }
        self.plant_yellowfin_tuna = self.config.IslandFishery_PlantYellowfinTuna
        self.rancher_filter = self.config.IslandFishery_RancherFilter

        # 产品配置
        self.FISHERY_ITEMS = [
            {'name': 'bass', 'template': TEMPLATE_BASS, 'var_name': 'bass',
             'selection': SELECT_BASS, 'selection_check': SELECT_BASS_CHECK,
             'post_action': POST_BASS, 'category': 'fishery',
             'shop': SHOP_FRY_BASS, 'tab': 'freshwater', 'yield': 6, 'buy_max': 4},
            {'name': 'yellowfin_tuna', 'template': TEMPLATE_YELLOWFIN_TUNA, 'var_name': 'yellowfin_tuna',
             'selection': SELECT_YELLOWFIN_TUNA, 'selection_check': SELECT_YELLOWFIN_TUNA_CHECK,
             'post_action': POST_YELLOWFIN_TUNA, 'category': 'fishery',
             'shop': SHOP_FRY_YELLOWFIN_TUNA, 'tab': 'seawater', 'yield': 2, 'buy_max': 4},
            {'name': 'shell', 'template': TEMPLATE_SHELL, 'var_name': 'shell',
             'selection': SELECT_SHELL, 'selection_check': SELECT_SHELL_CHECK,
             'post_action': POST_SHELL, 'category': 'fishery',
             'shop': SHOP_FRY_SHELL, 'tab': 'other', 'yield': 10, 'buy_max': 4},
            {'name': 'shrimp', 'template': TEMPLATE_SHRIMP, 'var_name': 'shrimp',
             'selection': SELECT_SHRIMP, 'selection_check': SELECT_SHRIMP_CHECK,
             'post_action': POST_SHRIMP, 'category': 'fishery',
             'shop': SHOP_FRY_SHRIMP, 'tab': 'other', 'yield': 12, 'buy_max': 7},
            {'name': 'crab', 'template': TEMPLATE_CRAB, 'var_name': 'crab',
             'selection': SELECT_CRAB, 'selection_check': SELECT_CRAB_CHECK,
             'post_action': POST_CRAB, 'category': 'fishery',
             'shop': SHOP_FRY_CRAB, 'tab': 'other', 'yield': 4, 'buy_max': 4},
            {'name': 'squid', 'template': TEMPLATE_SQUID, 'var_name': 'squid',
             'selection': SELECT_SQUID, 'selection_check': SELECT_SQUID_CHECK,
             'post_action': POST_SQUID, 'category': 'fishery',
             'shop': SHOP_FRY_SQUID, 'tab': 'other', 'yield': 4, 'buy_max': 4},
            {'name': 'sea_cucumber', 'template': TEMPLATE_SEA_CUCUMBER, 'var_name': 'sea_cucumber',
             'selection': SELECT_SEA_CUCUMBER, 'selection_check': SELECT_SEA_CUCUMBER_CHECK,
             'post_action': POST_SEA_CUCUMBER, 'category': 'fishery',
             'shop': SHOP_FRY_SEA_CUCUMBER, 'tab': 'other', 'yield': 2, 'buy_max': 4},
        ]

        self.name_to_config = {}
        for item in self.FISHERY_ITEMS:
            self.name_to_config[item['name']] = item

        # 岗位信息
        self.posts = {
            'ISLAND_FISHERY_POST1': {'button': ISLAND_FISHERY_POST1, 'crop': None},
            'ISLAND_FISHERY_POST2': {'button': ISLAND_FISHERY_POST2, 'crop': None},
            'ISLAND_FISHERY_POST3': {'button': ISLAND_FISHERY_POST3, 'crop': None},
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
                logger.info(f"{item_name}: 库存{count}<阈值{threshold}, 缺{deficit}, "
                            f"每苗产{yield_amount}, 需购买{fry_needed}个鱼苗")
                for _ in range(fry_needed):
                    self.to_plant_list.append(item_name)

    def warehouse_inventory(self):
        """获取仓库库存信息"""
        self.warehouse_filter('fishery')
        image = self.device.screenshot()
        results = {}
        for item_config in self.FISHERY_ITEMS:
            count = self.ocr_item_quantity(image, item_config['template'])
            results[item_config['name']] = count
            setattr(self, item_config['var_name'], count)
            logger.info(f"{item_config['name']}: {count}")
        return results

    def post_plant_check(self):
        """检查岗位正在生产什么"""
        for item in self.FISHERY_ITEMS:
            if self.appear(item['post_action']):
                return item['name']
        return None

    def switch_tab(self, target_tab):
        """切换到指定页签（freshwater/seawater/other）"""
        if target_tab == 'freshwater':
            target_tab_check = ISLAND_FISH_FRY_SHOP_FRESHWATER_CHECK
            target_tab_button = ISLAND_FISH_FRY_SHOP_FRESHWATER
        elif target_tab == 'seawater':
            target_tab_check = ISLAND_FISH_FRY_SHOP_SEAWATER_CHECK
            target_tab_button = ISLAND_FISH_FRY_SHOP_SEAWATER
        elif target_tab == 'other':
            target_tab_check = ISLAND_FISH_FRY_SHOP_OTHER_CHECK
            target_tab_button = ISLAND_FISH_FRY_SHOP_OTHER
        else:
            logger.warning(f"未知页签: {target_tab}")
            return

        while 1:
            self.device.screenshot()
            if self.appear(target_tab_check):
                break
            if self.appear_then_click(target_tab_button, interval=0.3):
                pass

    def decided_lists(self, post_button, post_id, post_index):
        """检查岗位状态并更新列表，同时记录完成时间"""
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()
        if self.appear(ISLAND_WORK_COMPLETE, offset=1):
            self.posts[post_id]['crop'] = None
            if post_index < len(self.fishery_times):
                self.fishery_times[post_index] = None
        elif self.appear(ISLAND_WORKING):
            product_name = self.post_plant_check()
            if product_name in self.to_plant_list:
                self.to_plant_list.remove(product_name)
            self.posts[post_id]['crop'] = product_name or 'unknown'
            # 记录正在工作中的岗位的完成时间
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            finish_time = datetime.now() + time_value
            if post_index < len(self.fishery_times):
                self.fishery_times[post_index] = finish_time
        elif self.appear(ISLAND_POST_SELECT, offset=1):
            self.posts[post_id]['crop'] = None
            if post_index < len(self.fishery_times):
                self.fishery_times[post_index] = None
        self.post_get_and_close()

    def post_plant(self, post_button, product, post_index):
        """在指定岗位种植指定产品，并记录完成时间"""
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()
        selection = self.name_to_config[product]['selection']
        selection_check = self.name_to_config[product]['selection_check']
        while 1:
            self.device.screenshot()
            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.select_character():
                    self.device.sleep(0.5)
                    self.device.click(SELECT_UI_CONFIRM)
                    self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                if self.select_product(selection, selection_check):
                    self.device.sleep(0.3)
                    self.device.click(POST_MAX)
                    self.device.sleep(0.3)
                    self.device.click(POST_ADD_ORDER)
                    self.device.sleep(0.5)
                    break

        self.post_open(post_button)
        self.device.sleep(0.5)
        self.device.screenshot()
        # OCR并记录完成时间
        time_work = Duration(ISLAND_WORKING_TIME)
        time_value = time_work.ocr(self.device.image)
        finish_time = datetime.now() + time_value
        if post_index < len(self.fishery_times):
            self.fishery_times[post_index] = finish_time

        # 更新岗位作物信息
        for post_id, post_info in self.posts.items():
            if post_info['button'] == post_button:
                post_info['crop'] = product
                break
        return True

    def goto_fishery_gear_shop(self):
        """
        导航到渔具商店页签。
        渔具商店是渔场独有的左侧栏页签，入口在商店页面的左侧边栏（鱼苗图标按钮，y~467）。
        """
        self.ui_goto(page_island_shop, get_ship=False)
        self.device.sleep(0.5)
        self.device.click(ISLAND_SHOP_GOTO_FISHERY_GEAR)
        while 1:
            self.device.screenshot()
            # 等待渔具商店页面加载完成（此处可用特定检测按钮替换）
            if self.appear(ISLAND_SHOP_GOTO_FISHERY_GEAR, offset=(5, 5, 5, 5)):
                # 简单检测：点击后按钮颜色可能会变化表示已选中
                self.device.sleep(0.5)
                break
            self.device.click(ISLAND_SHOP_GOTO_FISHERY_GEAR)
            self.device.sleep(0.5)
        logger.info("已进入渔具商店页签")

    def buy_fry(self, product, quantity=1):
        """购买鱼苗，一次购买 quantity 个（不超过 buy_max 上限）

        对齐种子商店 buy_seeds 的简洁风格。
        """
        item_config = self.name_to_config[product]
        target_tab = item_config['tab']
        shop_button = item_config['shop']
        buy_max = item_config.get('buy_max', 4)
        buy_qty = min(quantity, buy_max)

        # 切换到对应页签（淡水/海水/其他）
        self.switch_tab(target_tab)

        logger.info(f"购买 {product} x{buy_qty}")

        # 点击商品，等待购物弹窗出现
        while 1:
            self.device.screenshot()
            if self.appear(ISLAND_SHOPPING_CHECK):
                break
            if self.appear_then_click(shop_button, interval=1.2):
                pass

        # 设置购买数量
        if self.appear(ISLAND_SHOPPING_CHECK):
            self.set_buy_number(buy_qty)

        # 确认购买
        while 1:
            self.device.screenshot()
            if self.appear(ISLAND_FRY_SHOP_CHECK, offset=1):
                break
            if self.appear_then_click(ISLAND_SHOP_CONFIRM):
                self.device.sleep(0.5)
                self.device.click(ISLAND_SHOP_CONFIRM)
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SHOP_GET):
                self.device.click(ISLAND_SHOP_CONFIRM)
                continue
        if self.appear(ISLAND_SHOP_GET):
            self.device.click(ISLAND_SHOP_CONFIRM)

    def run(self, ranch_finish_times=None):
        self.island_error = False
        self.check_inventory_and_prepare_list()

        logger.info("\n当前库存统计:")
        logger.info(f"渔场库存: {self.inventory_counts}")

        # 重置渔场时间追踪列表
        self.fishery_times = [None] * self.fishery_positions

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

        # 检查所有岗位
        for i in range(self.fishery_positions):
            post_id = f'ISLAND_FISHERY_POST{i + 1}'
            button = post_id_to_button[post_id]

            self.decided_lists(button, post_id, i)

            if self.posts[post_id]['crop'] is None:
                idle_posts.append({
                    'post_id': post_id,
                    'button': button,
                    'index': i,
                })

        logger.info(f"\n空闲岗位统计: {len(idle_posts)}个空闲岗位")

        if not idle_posts:
            logger.info("没有空闲岗位，跳过养殖")
        else:
            # 确定需要养殖的产品
            products_to_buy = []

            # 1. 从补种列表中选取
            num_from_list = min(len(self.to_plant_list), len(idle_posts))
            for i in range(num_from_list):
                products_to_buy.append(self.to_plant_list[i])

            # 2. 空闲岗位剩余数
            remaining_idle = len(idle_posts) - num_from_list

            # 3. 计算已种植黄鳍金枪鱼的数量
            already_planted_default = 0
            for i in range(self.fishery_positions):
                post_id = f'ISLAND_FISHERY_POST{i + 1}'
                if self.posts[post_id]['crop'] == 'yellowfin_tuna':
                    already_planted_default += 1

            logger.info(f"已有{already_planted_default}个岗位养殖了黄鳍金枪鱼，配置要求{self.plant_yellowfin_tuna}个")

            need_default = max(0, self.plant_yellowfin_tuna - already_planted_default)

            if remaining_idle > 0 and need_default > 0:
                actual_default = min(remaining_idle, need_default)
                for _ in range(actual_default):
                    products_to_buy.append('yellowfin_tuna')

            if products_to_buy:
                logger.info(f"\n需要购买的产品: {products_to_buy}")

                # 前往鱼苗商店（不是种子商店），鱼苗商店有独立的页签
                self.ui_goto(page_island_shop, get_ship=False)
                self.device.sleep(0.5)
                self.device.click(ISLAND_SHOP_GOTO_FISHERY_GEAR)
                while 1:
                    self.device.screenshot()
                    if self.appear(ISLAND_FISH_FRY_SHOP_FRESHWATER_CHECK, offset=1):
                        break
                    if self.appear_then_click(ISLAND_SHOP_GOTO_FISHERY_GEAR, interval=0.3):
                        pass
                    self.device.click(ISLAND_SHOP_GOTO_FISHERY_GEAR)
                    self.device.sleep(0.5)

                # 计算每种产品需要购买的数量
                product_counts = {}
                for product_name in products_to_buy:
                    product_counts[product_name] = product_counts.get(product_name, 0) + 1

                for product, count in product_counts.items():
                    buy_max = self.name_to_config[product].get('buy_max', 4)
                    total_demand = len([p for p in self.to_plant_list if p == product])
                    logger.info(f"购买{product}鱼苗，需求{total_demand}个，空闲{count}岗，每岗上限{buy_max}个")
                    remaining = total_demand
                    for _ in range(count):
                        if remaining <= 0:
                            break
                        buy_qty = min(buy_max, remaining)
                        self.buy_fry(product, quantity=buy_qty)
                        remaining -= buy_qty

                while 1:
                    self.device.screenshot()
                    if self.appear(ISLAND_CHECK):
                        break
                    self.device.click(ISLAND_BACK)
                    self.device.sleep(0.5)

                # 返回岗位管理页面进行养殖
                self.goto_management()
                self.ui_goto(page_island_postmanage, get_ship=False)
                self.post_manage_mode(POST_MANAGE_PRODUCTION)
                self.post_close()
                self.device.sleep(1)

                # 养殖
                for i, post_info in enumerate(idle_posts):
                    if i >= len(products_to_buy):
                        logger.info(f"跳过渔场岗位{post_info['post_id']}: 没有需要养殖的产品")
                        continue

                    product_to_plant = products_to_buy[i]
                    logger.info(f"尝试养殖渔场岗位{post_info['post_id']}: {product_to_plant}")

                    success = self.post_plant(post_info['button'], product_to_plant, post_info['index'])

                    if success:
                        logger.info(f"养殖渔场岗位{post_info['post_id']}成功: {product_to_plant}")
                        if product_to_plant in self.to_plant_list:
                            self.to_plant_list.remove(product_to_plant)

        logger.info("\n渔场管理完成！")

        # 设置下次运行时间：合并牧场和渔场的计时器，取最早的时间
        future_finish = []
        six_hours_later = datetime.now() + timedelta(hours=6)
        future_finish.append(six_hours_later)
        # 合并牧场的结束时间（如果传入了的话）
        if ranch_finish_times:
            future_finish.extend(ranch_finish_times)
            logger.info(f'合并牧场 {len(ranch_finish_times)} 个计时器')
        # === 修复：添加渔场自身的完成时间 ===
        fishery_finish_times = [t for t in self.fishery_times if t is not None]
        if fishery_finish_times:
            future_finish.extend(fishery_finish_times)
            logger.info(f'合并渔场 {len(fishery_finish_times)} 个计时器')
        future_finish.sort()
        self.config.task_delay(target=future_finish)
        logger.info(f'渔场任务完成，合并后总共 {len(future_finish)} 个计时器，下次运行时间: {future_finish[0]}')

        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")
