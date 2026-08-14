"""岛屿制造工坊模块。

继承 IslandShopBase，实现制造工坊的产品配置与岗位管理。
支持固定位置按钮（如荠菜）、滑动配置及制造时间前缀设置，管理工坊自动化生产流程。
"""
from module.island.island import *
from module.island_manufacture.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.ui.page import *
from datetime import timedelta

from module.config.time_source import now as current_time
from module.logger import logger
from module.base.button import Button


# 固定位置按钮 — 在产品选择界面不滑动时，荠菜的固定位置
FIXED_SELECT_SHEPHERD_PURSE = Button(
    area=(), color=(), button=(224, 151, 274, 209),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)


# 季节限定手工产品配置（按 SEASONAL_ITEMS['handmade'] 的键引用）
# 注意：清单中的部分物品（如夏季茉莉精油、秋季花束）有意不在此配置内，
# 即季节定义保留但工厂不实际制作。
SEASONAL_HANDMADE_ITEMS = {
    'shepherd_purse': {
        'name': 'shepherd_purse', 'template': TEMPLATE_SHEPHERD_PURSE,
        'var_name': 'shepherd_purse', 'selection': FIXED_SELECT_SHEPHERD_PURSE,
        'selection_check': FIXED_SELECT_SHEPHERD_PURSE, 'post_action': POST_SHEPHERD_PURSE,
    },
    'summer_bouquet': {
        'name': 'summer_bouquet', 'template': TEMPLATE_SUMMER_BOUQUET,
        'var_name': 'summer_bouquet', 'selection': SELECT_SUMMER_BOUQUET,
        'selection_check': SELECT_SUMMER_BOUQUET_CHECK, 'post_action': POST_SUMMER_BOUQUET,
    },
}


class IslandManufacture(IslandShopBase):
    def __init__(self, *args, **kwargs):
        # 先初始化基类
        IslandShopBase.__init__(self, *args, **kwargs)

        # 设置店铺类型
        self.shop_type = "manufacture"
        self.time_prefix = "time_manufacture"

        # 设置滑动配置（岗位管理界面需要两次滑动）
        self.post_manage_swipe_count = 2

        # === 初始化全局季节配置 ===
        self._init_season_config()

        # 设置筛选资产
        self.filter_asset = 'factory'

        # 制造业产品配置
        self.manufacture = {
            'wood_processing': {
                'items': [
                    {'name': 'file_cabinet', 'template': TEMPLATE_FILE_CABINET,
                     'var_name': 'file_cabinet', 'selection': SELECT_FILE_CABINET,
                     'selection_check': SELECT_FILE_CABINET_CHECK, 'post_action': POST_FILE_CABINET},
                ]
            },
            #TEMPLATE_FILTER_ELEMENT 未添加
            'electronic_processing': {
                'items': [
                    {'name': 'filter_element', 'template': TEMPLATE_FILE_CABINET,
                     'var_name': 'filter_element', 'selection': SELECT_FILTER_ELEMENT,
                     'selection_check': SELECT_FILTER_ELEMENT_CHECK, 'post_action': POST_FILTER_ELEMENT},
                ]
            },
            'industrial_production': {
                'items': [
                    {'name': 'iron_nail', 'template': TEMPLATE_IRON_NAIL,
                     'var_name': 'iron_nail', 'selection': SELECT_IRON_NAIL,
                     'selection_check': SELECT_IRON_NAIL_CHECK, 'post_action': POST_IRON_NAIL},
                    {'name': 'cutlery', 'template': TEMPLATE_CUTLERY,
                     'var_name': 'cutlery', 'selection': SELECT_CUTLERY,
                     'selection_check': SELECT_CUTLERY_CHECK, 'post_action': POST_CUTLERY},
                ]
            },
            'handmade': {
                'items': [
                    {'name': 'leather', 'template': TEMPLATE_LEATHER,
                     'var_name': 'leather', 'selection': SELECT_LEATHER,
                     'selection_check': SELECT_LEATHER_CHECK, 'post_action': POST_LEATHER},
                    {'name': 'boot', 'template': TEMPLATE_BOOT,
                     'var_name': 'boot', 'selection': SELECT_BOOT,
                     'selection_check': SELECT_BOOT_CHECK, 'post_action': POST_BOOT},
                    {'name': 'peanut_oil', 'template': TEMPLATE_PEANUT_OIL,
                     'var_name': 'peanut_oil', 'selection': SELECT_PEANUT_OIL,
                     'selection_check': SELECT_PEANUT_OIL_CHECK, 'post_action': POST_PEANUT_OIL},
                ]
            }
        }
        # 季节限定：手工类产品（荠菜干、秋季花束等，按当前季节配置）
        if hasattr(self, 'season_config') and self.season_config.is_seasonal_enabled:
            for item_name in (self.season_config.get_seasonal_items('handmade') or []):
                item_config = SEASONAL_HANDMADE_ITEMS.get(item_name)
                if not item_config:
                    continue
                if any(it['name'] == item_name for it in self.manufacture['handmade']['items']):
                    # 花生油等基础产品已常驻，无需重复添加
                    continue
                self.manufacture['handmade']['items'].append(item_config.copy())
                logger.info(f"[岛屿-制造业] 季节限定：{self._item_cn(item_name)} 已添加到手工产品列表")

        # 根据配置初始化岗位按钮
        self.post_buttons = self._init_post_buttons()

        # 将所有产品展平到一个列表中，供基类使用
        self.shop_items = []
        for category in self.manufacture.values():
            self.shop_items.extend(category['items'])

        # 初始化需求列表（制造业不需要外部配置的需求）
        self.post_products = []

        # 设置配置（使用4个参数，删除任务相关配置）
        self.setup_config(
            config_meal_prefix="IslandManufacture_Meal",
            config_number_prefix="IslandManufacture_MealNumber",
            config_away_cook="IslandManufactureNextTask_AwayCook",
            config_post_number="IslandManufacture_PostNumber"
        )

        # 初始化店铺
        self.initialize_shop()

        # 本批生产已确认材料不足的物品（同一批内后续岗位直接跳过）
        self.unavailable_products = set()

    def _init_post_buttons(self):
        """根据配置初始化岗位按钮"""
        post_buttons = {}
        if self.config.WoodProcessing_Positions >= 1:
            post_buttons['ISLAND_WOOD_PROCESSING_POST1'] = ISLAND_WOOD_PROCESSING_POST1
        if self.config.WoodProcessing_Positions >= 2:
            post_buttons['ISLAND_WOOD_PROCESSING_POST2'] = ISLAND_WOOD_PROCESSING_POST2

        if self.config.ElectronicProcessing_Positions >= 1:
            post_buttons['ISLAND_ELECTRONIC_PROCESSING_POST1'] = ISLAND_ELECTRONIC_PROCESSING_POST1
        if self.config.ElectronicProcessing_Positions >= 2:
            post_buttons['ISLAND_ELECTRONIC_PROCESSING_POST2'] = ISLAND_ELECTRONIC_PROCESSING_POST2

        if self.config.Industrial_Positions >= 1:
            post_buttons['ISLAND_INDUSTRIAL_POST1'] = ISLAND_INDUSTRIAL_POST1
        if self.config.Industrial_Positions >= 2:
            post_buttons['ISLAND_INDUSTRIAL_POST2'] = ISLAND_INDUSTRIAL_POST2

        if self.config.Handmade_Positions >= 1:
            post_buttons['ISLAND_HANDMADE_POST1'] = ISLAND_HANDMADE_POST1
        if self.config.Handmade_Positions >= 2:
            post_buttons['ISLAND_HANDMADE_POST2'] = ISLAND_HANDMADE_POST2

        return post_buttons

    def get_idle_posts_by_category(self, category):
        """获取指定类别的空闲岗位ID列表"""
        category_posts = []
        if category == 'wood_processing':
            category_posts = ['ISLAND_WOOD_PROCESSING_POST1', 'ISLAND_WOOD_PROCESSING_POST2']
        elif category == 'electronic_processing':
            category_posts = ['ISLAND_ELECTRONIC_PROCESSING_POST1', 'ISLAND_ELECTRONIC_PROCESSING_POST2']
        elif category == 'industrial_production':
            category_posts = ['ISLAND_INDUSTRIAL_POST1', 'ISLAND_INDUSTRIAL_POST2']
        elif category == 'handmade':
            category_posts = ['ISLAND_HANDMADE_POST1', 'ISLAND_HANDMADE_POST2']

        # 只返回实际存在的空闲岗位
        return [post_id for post_id in category_posts
                if post_id in self.posts and self.posts[post_id]['status'] == 'idle']

    def select_product(self, product_selection, product_selection_check):
        """
        覆盖父类 select_product：
        荠菜使用固定坐标点击；其他产品走父类逻辑（向下滑动搜索查找）。
        靴子等产品位于列表下方，必须向下滑动列表才能找到。
        """
        # 荠菜 → 直接点击固定位置
        if product_selection == FIXED_SELECT_SHEPHERD_PURSE:
            self.device.click(FIXED_SELECT_SHEPHERD_PURSE)
            self.device.sleep(0.5)
            return True

        # 其他产品使用父类逻辑（模板匹配 + 向下滑动查找）
        return super().select_product(product_selection, product_selection_check)

    def select_product_with_material_check(self, post_id, product_list):
        """选择产品并检查材料是否充足（覆盖基类方法）

        靴子等产品位于列表下方，靠父类向下滑动搜索查找。
        产品无法制作（材料不足或找不到）时，退出岗位重新进入，
        重置列表滚动进度后再检测下一个产品。
        本批内已确认材料不足的物品会记忆下来，后续岗位直接跳过。
        """
        post_button = self.posts[post_id]['button']

        for product_info in product_list:
            product_name = product_info['name']
            selection = product_info['selection']
            selection_check = product_info['selection_check']

            # 同一批内前面岗位已确认材料不足的物品，直接跳过
            if product_name in self.unavailable_products:
                logger.info(f"[岛屿-制造业] {self._item_cn(product_name)} 本批已确认材料不足，直接跳过")
                continue

            # 每个产品：进入岗位搜索并选择；找不到则退出岗位重进重试
            for attempt in range(self.PRODUCT_SELECT_RETRY_LIMIT):
                # 打开岗位（首次或重进）
                self.post_close()
                self.post_open(post_button)
                self.device.sleep(0.5)

                entered_product_page = False
                while True:
                    self.device.screenshot()
                    if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                        self.device.sleep(0.5)
                        continue
                    if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                        if self.select_character():
                            if not self.confirm_selected_character(f"{post_id}制造派遣"):
                                self.back_to_postmanage_from_dispatch()
                                return None
                        else:
                            logger.warning(f"[岛屿-制造业] {post_id}制造派遣无可用角色")
                            self.back_to_postmanage_from_dispatch()
                            return None
                        continue
                    if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                        entered_product_page = True
                        logger.info(f"[岛屿-制造业] 尝试选择产品: {self._item_cn(product_name)}")
                        selected = self.select_product(selection, selection_check)
                        self.device.sleep(0.5)
                        break

                if not entered_product_page:
                    return None

                if not selected:
                    # 搜索失败：退出岗位重新进入（重置列表滚动进度），重试同一产品
                    logger.warning(
                        f"[岛屿-制造业] 未能识别到产品选择项: {self._item_cn(product_name)}，"
                        f"退出岗位重进重试 ({attempt + 1}/{self.PRODUCT_SELECT_RETRY_LIMIT})"
                    )
                    self.device.click(SELECT_UI_BACK)
                    self.device.sleep(0.3)
                    self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
                    self.device.sleep(0.5)
                    self.post_close()
                    for _ in range(self.post_manage_swipe_count):
                        self.post_manage_up_swipe(450)
                    continue  # 下一轮重进重试同一产品

                # 检查确认按钮状态
                image = self.device.screenshot()
                color = get_color(image, (493, 597, 621, 643))

                # 如果确认按钮是灰色（153, 156, 156），表示材料不足
                if color_similar(color, (153, 156, 156), 80):
                    # 记忆本批材料不足的物品，后续岗位不再重复尝试
                    self.unavailable_products.add(product_name)
                    logger.info(f"[岛屿-制造业] 材料不足，跳过产品: {self._item_cn(product_name)}")
                    # 退出岗位，下一个产品重新进入时列表滚动进度已重置
                    self.device.click(SELECT_UI_BACK)
                    self.device.sleep(0.3)
                    self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
                    self.device.sleep(0.5)
                    self.post_close()
                    for _ in range(self.post_manage_swipe_count):
                        self.post_manage_up_swipe(450)
                    break  # 跳出重试循环 -> 下一个产品

                # 材料充足，派遣生产
                self.appear_then_click(POST_MAX)
                self.device.click(POST_ADD_ORDER)
                logger.info(f"[岛屿-制造业] 选择产品成功: {self._item_cn(product_name)}")
                self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
                self.device.sleep(0.5)
                self.post_close()
                for _ in range(self.post_manage_swipe_count):
                    self.post_manage_up_swipe(450)

                # 获取生产时间和数量
                self.post_open(post_button)
                image = self.device.screenshot()
                ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                        alphabet='0123456789')
                actual_number = ocr_post_number.ocr(image)
                time_work = Duration(ISLAND_WORKING_TIME)
                time_value = time_work.ocr(self.device.image)
                finish_time = current_time() + time_value

                # 设置时间变量
                import re
                match = re.search(r'POST(\d+)', post_id)
                if match:
                    post_num = match.group(1)
                    time_var_name = f'{self.time_prefix}{post_num}'
                    setattr(self, time_var_name, finish_time)

                self.posts[post_id]['status'] = 'working'
                logger.info(f"[岛屿-制造业] 已安排生产：{self._item_cn(product_name)} x{actual_number}")
                self.post_close()
                return product_info

        # 所有产品都无法选择或材料不足
        logger.info("[岛屿-制造业] 所有产品都无法选择或材料不足")
        return None

    def schedule_manufacture(self):
        """安排制造业生产（覆盖基类方法）"""
        self.schedule_wood_processing()

        self.schedule_electronic_processing()

        self.schedule_industrial_production()

        self.schedule_handmade()

    def schedule_wood_processing(self):
        """安排木料加工生产"""
        idle_posts = self.get_idle_posts_by_category('wood_processing')
        if not idle_posts:
            return
        # 木料加工只生产file_cabinet
        product_list = self.manufacture['wood_processing']['items']
        for post_id in idle_posts:
            self.select_product_with_material_check(post_id, product_list)

    def schedule_electronic_processing(self):
        """安排电子加工生产"""
        idle_posts = self.get_idle_posts_by_category('electronic_processing')
        if not idle_posts:
            return
        # 木料加工只生产file_cabinet
        product_list = self.manufacture['electronic_processing']['items']
        for post_id in idle_posts:
            self.select_product_with_material_check(post_id, product_list)

    def schedule_industrial_production(self):
        """安排工业生产"""
        idle_posts = self.get_idle_posts_by_category('industrial_production')
        if not idle_posts:
            return
        # 检查库存iron_nail
        iron_nail_stock = self.warehouse_counts.get('iron_nail', 0)
        # 根据规则选择产品
        if iron_nail_stock >= 20:
            product_list = [item for item in self.manufacture['industrial_production']['items']
                            if item['name'] == 'cutlery']
        else:
            product_list = [item for item in self.manufacture['industrial_production']['items']
                            if item['name'] == 'iron_nail']

        for post_id in idle_posts:
            self.select_product_with_material_check(post_id, product_list)

    def schedule_handmade(self):
        """安排手工生产"""
        idle_posts = self.get_idle_posts_by_category('handmade')
        if not idle_posts:
            return
        # 检查库存leather
        leather_stock = self.warehouse_counts.get('leather', 0)
        # 构建产品选择列表（按优先级）
        product_list = []
        # 优先生产当前季节的限定手工品（荠菜干、夏季花束等）
        seasonal_names = []
        if hasattr(self, 'season_config') and self.season_config.is_seasonal_enabled:
            seasonal_names = self.season_config.get_seasonal_items('handmade') or []
        for item in self.manufacture['handmade']['items']:
            if item['name'] in seasonal_names:
                product_list.append(item)

        # 如果leather库存>=10，则生产boot
        if leather_stock >= 10:
            boot_item = [item for item in self.manufacture['handmade']['items']
                         if item['name'] == 'boot'][0]
            product_list.append(boot_item)

        # 最后生产leather
        leather_item = [item for item in self.manufacture['handmade']['items']
                        if item['name'] == 'leather'][0]
        product_list.append(leather_item)

        for post_id in idle_posts:
            self.select_product_with_material_check(post_id, product_list)

    def run(self):
        """运行制造业逻辑（完全覆盖基类方法）"""
        self.island_error = False
        # 每批生产开始时清空“材料不足”记忆，避免跨批沿用旧库存状态
        self.unavailable_products = set()

        # 第一步：检查岗位状态
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()

        # 滑动以看到岗位
        for _ in range(self.post_manage_swipe_count):
            self.post_manage_up_swipe(450)

        # 检查岗位状态
        time_vars = []
        post_index = 1

        # 按顺序检查所有岗位
        for post_id in self.post_buttons.keys():
            time_var_name = f'{self.time_prefix}{post_index}'
            time_vars.append(time_var_name)
            setattr(self, time_var_name, None)
            self.post_check(post_id, time_var_name)
            post_index += 1


        # 判断是否有需要安排的任务
        idle_posts = self.get_idle_posts()
        if idle_posts:
            self.get_warehouse_counts()
            # 如果有空闲岗位，重新进入岗位管理界面安排生产
            logger.info(f"[岛屿-制造业] 有 {len(idle_posts)} 个空闲岗位，开始安排生产")

            # 重新进入岗位管理界面
            self.goto_postmanage()
            self.post_manage_mode(POST_MANAGE_PRODUCTION)
            self.post_close()

            # 滑动以看到岗位
            for _ in range(self.post_manage_swipe_count):
                self.post_manage_up_swipe(450)

            # 安排生产
            self.schedule_manufacture()
        else:
            logger.info("[岛屿-制造业] 没有空闲岗位，跳过生产安排")

        # 设置任务延迟
        finish_times = []
        for var in time_vars:
            time_value = getattr(self, var)
            if time_value is not None:
                finish_times.append(time_value)
        hours_later = current_time() + timedelta(hours=6)
        finish_times.append(hours_later)
        finish_times.sort()
        self.config.task_delay(target=finish_times)

        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")

    # 以下方法重写以适配基类
    def process_meal_requirements(self, source_products):
        """制造业不需要处理套餐需求"""
        return source_products

    def schedule_production(self):
        """覆盖：制造业使用自己的生产调度"""
        self.schedule_manufacture()

    def process_away_cook(self):
        """覆盖：制造业不需要常驻餐品模式"""
        # 制造业有自己的生产规则，不依赖常驻餐品
        self.to_post_products = {}
        logger.info("[岛屿-制造业] 制造业使用内置生产规则，不设置常驻餐品")

    def get_max_producible(self, product, requested_quantity, skip_zero_materials=False):
        """覆盖：制造业的生产数量由材料检查决定"""
        return requested_quantity

    def check_special_materials(self, product, batch_size):
        """覆盖：制造业没有特殊材料检查"""
        return batch_size

    def apply_special_material_constraints(self, requirements):
        """覆盖：制造业没有特殊材料限制"""
        return requirements

    def test(self):
        if self.config.Industrial_Positions > 1:
            logger.info(2)


if __name__ == "__main__":
    az = IslandManufacture('alas', task='Alas')
    az.device.screenshot()
    az.run()
