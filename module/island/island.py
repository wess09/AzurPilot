"""岛屿系统基类模块。

提供岛屿自动化操作的核心基础功能，包括岛屿导航、岗位管理、产品选择与派遣。
继承自 InfoHandler 和 LoginHandler，组合仓库 OCR 与角色选择能力。
定义岛屿地图确认等待时间、产品选择安全区域及材料数量 OCR 区域等公共常量。
"""
from module.island.assets import *
from module.ui.page import *
from module.base.timer import Timer
from module.handler.info_handler import InfoHandler
from module.ocr.ocr import *
from datetime import datetime
from module.island.island_select_character import *
from module.island.warehouse import *
from module.handler.login import LoginHandler
from module.ui.ui import *
from module.exception import GameStuckError, ScriptError
from module.logger import logger
from module.base.runtime_params import (
    ISLAND_CHARACTER_CONFIRM_RETRY_WAIT,
    ISLAND_ENTRY_RETRY_WAIT,
    ISLAND_MAP_CONFIRM_RETRY_WAIT,
    ISLAND_MAP_CONFIRM_WAIT,
    ISLAND_MAP_DESTINATION_WAIT,
)
from module.config.utils import read_run_param
from module.island.island_walk import (
    ISLAND_WALK_ACTIONS,
    ISLAND_WALK_MAX_HOLD,
    ISLAND_WALK_MIN_HOLD,
    ISLAND_WALK_ROUTES,
    format_walk_rule,
    parse_walk_rule,
)
import re

# 等待/重试参数走 WebUI「运行参数」页（RunParams.UiWait），兜底默认值与
# 帧数类内部常量集中在 module/base/runtime_params.py（界面等待域）。
# 角色确认最多补点次数。次数用尽后不再点击，只观察页面是否切换，避免死循环点击。
ISLAND_CHARACTER_CONFIRM_MAX_CLICKS = 8
# 岗位列表定位滑动：单步距离、回顶部滑动距离与补滑上限。
# 模拟器/云手机上一次滑动实际滚动的距离会明显小于期望值（滑动距离不够），
# 固定 2 次 450 经常停在中途，因此定位改为“滑动→检测锚点→继续补滑”的闭环。
# 低端机帧率低，快滑会被压缩进一两帧、单次实际滚动进一步缩水（惯性被停止点击
# 掐掉后每步只剩 450 拖拽），补滑上限必须能覆盖整份列表。
ISLAND_POST_SWIPE_STEP = 450
ISLAND_POST_SWIPE_DISTANCE = 550
ISLAND_POST_SWIPE_TO_TOP_MAX = 5
ISLAND_POST_SWIPE_SEARCH_MAX = 8

# 岛屿走位路线与规则解析集中在 module/island/island_walk.py；可以用岛屿计划的
# 全局配置 `IslandPlan.IslandWalk.<路线名>` 覆盖整条规则（所有控制方式都生效，
# 桥接 swipe 的位移随负载漂移，按机器各配一套规则最稳）。

# 岗位产品选择滑动惯性消除安全区域
SELECT_PRODUCT_INERTIA_STOP = Button(
    area=(), color=(),
    button=(468, 400, 476, 500),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

# 角色页确认按钮的安全点击段（按钮右侧区域）。角色页确认按钮 SELECT_UI_CONFIRM
# (944, 585, 1236, 632) 与选餐页确认按钮 POST_ADD_ORDER (491, 595, 1090, 647) 坐标重叠，
# 云手机转场较慢时补点确认会落到已经切换过去的选餐页上，把列表里默认的第一个餐品
# 直接下单。该安全段在角色页仍完整落在确认按钮内，在选餐页则是空白，误点无副作用。
SELECT_UI_CONFIRM_SAFE = Button(
    area=(), color=(),
    button=(
        SELECT_UI_CONFIRM.button[0] + (SELECT_UI_CONFIRM.button[2] - SELECT_UI_CONFIRM.button[0]) * 3 // 5,
        SELECT_UI_CONFIRM.button[1] + 8,
        SELECT_UI_CONFIRM.button[2] - 8,
        SELECT_UI_CONFIRM.button[3] - 4,
    ),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''},
    name='SELECT_UI_CONFIRM_SAFE',
)

# 岗位派遣页底部材料卡片上的数量文本，例如 150/2 或 150/(2+6)。
OCR_SELECT_PRODUCT_MATERIAL_AMOUNT = Button(
    area=(742, 536, 850, 562), color=(),
    button=(742, 536, 850, 562),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

# 同一张材料卡片中“当前库存/”所在的左侧前缀区域。
# 完整宽区域容易把 0/9 识别成 09、把 110/(2+6) 识别成 1102，
# 因此当前库存优先从斜杠左侧前缀读取。
OCR_SELECT_PRODUCT_MATERIAL_CURRENT_AREAS = (
    (742, 536, 800, 562),
    (742, 536, 792, 562),
    (745, 536, 795, 562),
    (750, 536, 800, 562),
    (755, 536, 800, 562),
    (765, 536, 805, 562),
)

OCR_SELECT_PRODUCT_MATERIAL_COUNTER_AREAS = (
    (770, 536, 850, 562),
    (775, 536, 850, 562),
)

# select_product 中滑动操作的点击记录名称，提取为常量避免硬编码多处不一致
SELECTION_UP_SWIPE_NAME = "SelectionUpSwipe"
# select_product 最大滑动尝试次数，覆盖列表底部产品（海参等位于列表末尾）
_SELECT_PRODUCT_MAX_SWIPES = 8

# 岛屿物品英文 key -> 中文名映射，仅用于日志输出本地化。
# 名称来源：module/config/i18n/zh-CN.json 的餐品选项、各模块配置中的 cn_name 与既有中文注释。
ISLAND_ITEM_CN_NAMES = {
    # 农田作物
    'wheat': '小麦', 'corn': '玉米', 'rice': '水稻', 'chinese_cabbage': '白菜',
    'potato': '土豆', 'soybean': '大豆', 'pasture': '牧草', 'coffee_bean': '咖啡豆',
    'apple': '苹果', 'citrus': '柑橘', 'banana': '香蕉', 'mango': '芒果',
    'lemon': '柠檬', 'avocado': '牛油果', 'rubber': '橡胶', 'pear': '秋月梨',
    'persimmon': '柿子', 'carrot': '胡萝卜', 'onion': '洋葱', 'flax': '亚麻',
    'strawberry': '草莓', 'cotton': '棉花', 'tea': '茶叶', 'lavender': '薰衣草',
    'pineapple': '菠萝', 'asparagus': '芦笋',
    # 渔场
    'bass': '鲈鱼', 'yellowfin_tuna': '黄鳍金枪鱼', 'shell': '贝壳', 'shrimp': '小河虾',
    'crayfish': '小龙虾', 'crab': '螃蟹', 'squid': '鱿鱼', 'sea_cucumber': '海参',
    # 矿山/林场
    'Copper': '铜矿', 'Aluminium': '铝矿', 'Iron': '铁矿', 'Sulphur': '硫磺',
    'Silver': '银矿', 'Elegant': '典雅之木', 'Practical': '实用之木', 'Selected': '精选之木',
    # 牧场/磨坊
    'chicken_feed': '鸡饲料', 'pig_feed': '猪饲料', 'cattle_feed': '牛饲料',
    'sheep_feed': '羊饲料', 'wheat_flour': '面粉', 'chicken': '鸡肉', 'pork': '猪肉',
    # 原材料
    'milk': '牛奶', 'cheese': '芝士', 'tofu': '豆腐', 'fresh_honey': '蜂蜜',
    # 烧烤店
    'roasted_skewer': '碳烤肉串', 'chicken_potato': '禽肉土豆拼盘',
    'carrot_omelette': '胡萝卜厚蛋烧', 'stir_fried_chicken': '爆炒禽肉',
    'steak_bowl': '汉堡肉饭', 'crayfish_stir_fry': '爆炒小龙虾',
    'carnival': '烤肉狂欢', 'double_energy': '能量双拼套餐',
    # 有鱼餐馆（常规菜品 + 季节菜品）
    'omurice': '蛋包饭', 'cabbage_tofu': '白菜豆腐汤', 'salad': '蔬菜沙拉',
    'tofu_meat': '肉末烧豆腐', 'tofu_combo': '经典豆腐套餐', 'hearty_meal': '绵玉定食',
    'fish_chip': '炸鱼薯条', 'fo_tiao': '佛跳墙', 'onion_fish': '洋葱蒸鱼',
    'double_bamboo_shoots': '凉拌双笋', 'asparagus_shrimp': '芦笋炒虾仁',
    'amaranth_rice_ball': '苋菜饭团', 'tomato_egg': '番茄炒蛋',
    'matsutake_chicken_soup': '松茸鸡汤', 'persimmon_cake': '柿子饼',
    # 白熊饮品（季节饮品 + 常规饮品）
    'spring_flower_tea': '迎春花茶', 'carrot_pear_juice': '胡萝卜秋梨汁',
    'chrysanthemum_tea': '菊花茶', 'watermelon_juice': '西瓜汁',
    'cucumber_juice': '黄瓜汁', 'pineapple_juice': '鲜榨菠萝汁',
    'apple_juice': '苹果汁', 'banana_mango': '香蕉芒果汁', 'honey_lemon': '蜂蜜柠檬水',
    'strawberry_lemon': '草莓蜜沁', 'strawberry_honey': '草莓蜂蜜冰沙',
    'floral_fruity': '花香果韵', 'fruit_paradise': '缤纷果乐园',
    'lavender_tea': '薰衣草茶', 'sunny_honey': '阳光蜜水',
    # 啾咖啡
    'iced_coffee': '冰咖啡', 'omelette': '欧姆蛋', 'latte': '拿铁',
    'citrus_coffee': '柑橘咖啡', 'strawberry_milkshake': '草莓奶绿',
    'morning_light': '晨光活力组合', 'wake_up_call': '醒神套餐',
    'fruity_fruitier': '果香双杯乐',
    # 啾啾简餐
    'apple_pie': '苹果派', 'corn_cup': '玉米杯', 'orange_pie': '香橙派',
    'banana_crepe': '香蕉可丽饼', 'orchard_duo': '果园二重奏',
    'rice_mango': '芒果糯米饭', 'succulently_sweet': '香甜组合',
    'berry_orange': '莓果香橙甜点组', 'strawberry_charlotte': '草莓夏洛特',
    'seafood_rice': '海鲜饭',
    # 制造业（工坊）
    'file_cabinet': '文件柜', 'filter_element': '净水滤芯', 'iron_nail': '铁钉',
    'cutlery': '刀叉餐具', 'leather': '皮革', 'boot': '靴子', 'peanut_oil': '花生油',
    'shepherd_purse': '荠菜干', 'spring_bouquet': '春季花束', 'summer_bouquet': '夏季花束',
    'autumn_bouquet': '秋季花束', 'jasmine_oil': '茉莉精油',
}

class Island(SelectCharacter):
    def __init__(self, *args, **kwargs):
        # 调用两个父类的初始化
        UI.__init__(self, *args, **kwargs)
        SelectCharacter.__init__(self, *args, **kwargs)
        self.island_error = False
        self.warehouse_filter_kind = ButtonGrid(
            origin=(261, 260),
            delta=(155, 56),
            button_shape=(137, 42),
            grid_shape=(5, 1),
            name="WAREHOUSE_FILTER_KIND"
        )
        self.warehouse_filter_from = ButtonGrid(
            origin=(261, 355),
            delta=(155, 56),
            button_shape=(137, 42),
            grid_shape=(5, 3),
            name="WAREHOUSE_FILTER_FROM"
        )
        self.warehouse_area_relative = (116, 4, 133, 39)
        self.post_open_retry_swipe = False
        # 低端机上单轮补滑可能仍差一步，放宽到两轮；完整重试同样多给一次机会。
        self.post_open_retry_swipe_limit = 2
        self.post_open_full_retry_limit = 2

    def _item_cn(self, name):
        """返回岛屿物品英文 key 对应的中文名；无映射时原样返回。"""
        if not isinstance(name, str):
            return name
        if name in ISLAND_ITEM_CN_NAMES:
            return ISLAND_ITEM_CN_NAMES[name]
        config = getattr(self, 'name_to_config', {}).get(name)
        if config and config.get('cn_name'):
            return config['cn_name']
        return name

    def _inv_cn(self, mapping):
        """将库存字典的键翻译为中文，仅用于日志输出，不修改原字典。"""
        return {self._item_cn(key): value for key, value in mapping.items()}

    def _products_cn(self, products):
        """将 (名称, 数量) 配置列表翻译为中文，仅用于日志输出，不修改原列表。"""
        return [(self._item_cn(name), number) for name, number in products]

    def post_add_one(self, count, interval=0):
        """按 A/B/C 轮转点击生产数量 +1 按钮。

        Args:
            count (int): 点击次数。
            interval (float): 点击间隔时间（秒）。
        """
        buttons = (POST_ADD_ONE_A, POST_ADD_ONE_B, POST_ADD_ONE_C)
        for index in range(max(0, count)):
            self.device.click(buttons[index % len(buttons)])
            if interval:
                self.device.sleep(interval)

    def warehouse_absolute_area(self, button, relative_area):
        """将相对坐标转换为绝对坐标。

        Args:
            button (Button): 基准按钮。
            relative_area (tuple): 相对区域坐标 (x1, y1, x2, y2)。

        Returns:
            tuple: 绝对区域坐标 (x1, y1, x2, y2)。
        """
        x1 = button.area[0] + relative_area[0]
        y1 = button.area[1] + relative_area[1]
        x2 = button.area[0] + relative_area[2]
        y2 = button.area[1] + relative_area[3]
        return (x1, y1, x2, y2)

    def warehouse_filter_button_selected(self, button):
        """检查仓库筛选按钮是否处于选中状态。

        Args:
            button (Button): 待检测的筛选按钮。

        Returns:
            bool: 按钮是否已被选中。
        """
        warehouse_area = self.warehouse_absolute_area(button, self.warehouse_area_relative)
        warehouse_color = get_color(self.device.image, warehouse_area)
        return color_similar(warehouse_color, (60, 61, 63), 80)

    def warehouse_filter(self, button1, button2=None):
        """设置仓库的分类和来源筛选器。

        Args:
            button1 (str): 第一个筛选分类名称（如 'basic', 'product' 等）。
            button2 (str, optional): 第二个筛选来源名称（如 'farm', 'ranch' 等）。

        Raises:
            ValueError: 传入未知的筛选按钮名称。
            GameStuckError: 筛选器重置或按钮选择超时。
        """
        self.ui_goto(page_island_warehouse_filter, get_ship=False)
        # 定义按钮名称到网格坐标的映射
        kind_map = {
            'all_kind': (0, 0),
            'basic': (1, 0),
            'processed': (2, 0),
            'product': (3, 0),
            'other_kind': (4, 0)
        }
        from_map = {
            'all_from': (0, 0),
            'farm': (1, 0),
            'ranch': (2, 0),
            'mine': (3, 0),
            'forest': (4, 0),
            'orchard': (0, 1),
            'nursery': (1, 1),
            'fishery': (2, 1),
            'juu_coffee': (3, 1),
            'restaurant': (4, 1),
            'teahouse': (0, 2),
            'juu_eatery': (1, 2),
            'grill': (2, 2),
            'factory': (3, 2),
            'other_from': (4, 2)
        }
        all_kind_button = self.warehouse_filter_kind[kind_map['all_kind']]
        all_from_button = self.warehouse_filter_from[from_map['all_from']]
        # 等待并重置筛选器，直到两个全选按钮都被选中
        for _ in self.loop(timeout=8, skip_first=False):
            all_kind_selected = self.warehouse_filter_button_selected(all_kind_button)
            all_from_selected = self.warehouse_filter_button_selected(all_from_button)

            if all_kind_selected and all_from_selected:
                break
            if self.appear_then_click(FILTER_RESET, interval=1):
                continue
        else:
            raise GameStuckError("仓库筛选器重置超时")

        # 处理第一个按钮
        # 确定按钮属于哪个网格并获取按钮对象
        if button1 in kind_map:
            button_obj = self.warehouse_filter_kind[kind_map[button1]]
        elif button1 in from_map:
            button_obj = self.warehouse_filter_from[from_map[button1]]
        else:
            raise ValueError(f"未知的按钮名称: {button1}")

        click_timer = Timer(1)
        for _ in self.loop(timeout=8, skip_first=False):
            button_selected = self.warehouse_filter_button_selected(button_obj)

            if button_selected:
                break
            if click_timer.reached():
                self.device.click(button_obj)
                click_timer.reset()
                continue
        else:
            raise GameStuckError(f"仓库筛选按钮选择超时: {button1}")

        # 处理第二个按钮（如果有）
        if button2:
            # 确定按钮属于哪个网格并获取按钮对象
            if button2 in kind_map:
                button2_obj = self.warehouse_filter_kind[kind_map[button2]]
            elif button2 in from_map:
                button2_obj = self.warehouse_filter_from[from_map[button2]]
            else:
                raise ValueError(f"未知的按钮名称: {button2}")

            click_timer = Timer(1)
            for _ in self.loop(timeout=8, skip_first=False):
                button2_selected = self.warehouse_filter_button_selected(button2_obj)

                if button2_selected:
                    break
                if click_timer.reached():
                    self.device.click(button2_obj)
                    click_timer.reset()
                    continue
            else:
                raise GameStuckError(f"仓库筛选按钮选择超时: {button2}")
        self.appear_then_click(FILTER_CONFIRM)
        self.device.sleep(1)

    def goto_postmanage(self):
        """导航进入岗位管理页面。"""
        page = self.ui_get_current_page()
        valid_pages = ['page_island_management', 'page_island_postmanage', 'page_island', 'page_island_warehouse', 'page_island_visit', 'page_island_season']
        if page.name in valid_pages:
            self.ui_goto(page_island_postmanage, get_ship=False)
        else:
            self.goto_management()
            self.ui_goto(page_island_postmanage, get_ship=False)

    def goto_management(self):
        """导航进入岛屿管理页面。

        Raises:
            GameStuckError: 进入岛屿管理页面超时。
        """
        page = self.ui_get_current_page()
        valid_pages = ['page_island_management', 'page_island_postmanage', 'page_island', 'page_island_warehouse',
                       'page_island_visit', 'page_island_season']
        if page.name in valid_pages:
            self.ui_goto(page_island_management, get_ship=False)
        else:
            self.ui_goto(page_island, get_ship=False)
            # 入口按钮点击后岛屿场景需要转场，这里限制两次点击的间隔，
            # 避免云机上因为画面还没切走而反复点击同一个入口按钮
            entry_timer = Timer(read_run_param(
                self.config, 'UiWait_IslandEntryRetryWait', ISLAND_ENTRY_RETRY_WAIT, 1, 60)).clear()
            for _ in self.loop(timeout=20, skip_first=False):
                if self.appear(ISLAND_MANAGEMENT_CHECK, offset=1):
                    break
                in_island = self.appear(ISLAND_CHECK, offset=1)
                in_season = self.appear(ISLAND_SEASON_CHECK, offset=1)
                if (in_island or in_season) and entry_timer.reached():
                    self.device.click(
                        ISLAND_GOTO_MANAGEMENT if in_island else ISLAND_SEASON_GOTO_ISLAND
                    )
                    entry_timer.reset()
                    continue
                if self.ui_additional(get_ship=False):
                    continue
            else:
                raise GameStuckError("进入岛屿管理页面超时")
            if self.appear(ISLAND_SEASON_CHECK, offset=1):
                self.ui_goto(page_island_management, get_ship=False)

    def is_in_friend_island(self):
        """检测当前是否处于好友岛屿场景中。

        Returns:
            bool: 是否在好友岛屿。
        """
        leave = self.appear(AIR_DROP_RUN_AWAY, offset=(20, 20))
        access_map = self.appear(ISLAND_ACCESS_MAP, offset=(20, 20))
        return leave and access_map

    def check_visit_friend_island(self, visit_button):
        """点击好友拜访按钮并等待进入好友岛屿。

        检测逻辑分为两个阶段：
        1. 等待 ISLAND_ACCESS_MAP（右上角地图入口）出现，表示已开始加载好友岛。
        2. 等待 AIR_DROP_RUN_AWAY（顶部"离开"按钮）也出现，确认场景完全加载完毕。
        只有两者同时出现（is_in_friend_island() 为 True），才视为成功进入好友岛屿。

        Args:
            visit_button (Button): 好友拜访按钮。

        Returns:
            bool: 是否成功进入好友岛屿。
        """
        click_timer = Timer(3).start()
        self.device.click(visit_button)
        self.device.sleep(3)
        for _ in self.loop(timeout=30, skip_first=False):
            if self.is_in_friend_island():
                logger.info("[岛屿] 二次检测拜访状态......")
                # 在等待的过程中, 先后会出现黑底黄鸡loading、UI(一闪而过)、白底沙漏loading
                # 因此等待1s后进行二次确认, 避免中间UI一闪而过时出现误判
                self.device.sleep(1)
                self.device.screenshot()
                if self.is_in_friend_island():
                    self._island_expect_friend = True
                    logger.info("[岛屿] 成功进入好友岛屿")
                    return True
            if self.appear(CANT_ACCESS, offset=(20, 20)):
                logger.info("[岛屿] 好友不可访问")
                return False
            if click_timer.reached():
                self.device.click(visit_button)
                click_timer.reset()
            if self.ui_additional():
                continue
        logger.warning("[岛屿] 拜访好友超时")
        return False

    def exit_friend_island(self):
        """退出好友岛屿。

        Returns:
            bool: 退出成功返回 True，超时返回 False。
        """
        logger.info("[岛屿] 退出好友岛屿")
        self._island_expect_friend = False
        for _ in self.loop(timeout=30):
            if self.appear_then_click(AIR_DROP_RUN_AWAY, offset=(20, 20), interval=2):
                continue
            if self.appear(ISLAND_GOTO_MAP):
                logger.info("[岛屿] 成功退出好友岛屿")
                return True
            if self.ui_additional():
                continue
        logger.warning("[岛屿] 退出好友岛屿超时")
        return False

    def _wait_island_map_entry(self, timeout=3):
        """等待并检测岛屿地图入口相关按钮的状态。

        Args:
            timeout (int): 等待超时时间（秒）。

        Returns:
            dict: 包含各入口按钮出现状态的字典。
        """
        last_status = None
        for _ in self.loop(timeout=timeout, skip_first=False):
            in_map = self.appear(ISLAND_MAP_CHECK)
            leave = self.appear(AIR_DROP_RUN_AWAY, offset=(20, 20))
            access_map = self.appear(ISLAND_ACCESS_MAP, offset=(20, 20))
            home_map = self.appear(ISLAND_GOTO_MAP)
            in_friend = leave and access_map
            last_status = {
                "in_map": in_map,
                "in_friend": in_friend,
                "home_map": home_map,
                "access_map": access_map,
                "leave": leave,
            }
            if in_map or in_friend or home_map or access_map:
                return last_status
            if self.ui_additional(get_ship=False):
                continue
        return last_status or {
            "in_map": False,
            "in_friend": False,
            "home_map": False,
            "access_map": False,
            "leave": False,
        }

    def goto_island_map(self):
        """导航进入岛屿地图页面。

        Returns:
            bool: 进入成功返回 True，超时返回 False。
        """
        logger.hr("岛屿-前往地图", level=2)
        expect_friend = bool(getattr(self, "_island_expect_friend", False))
        status = self._wait_island_map_entry(timeout=10 if expect_friend else 3)
        in_map = status["in_map"]
        in_friend = status["in_friend"]
        home_map = status["home_map"]
        access_map = status["access_map"]
        if not in_map and not in_friend and not home_map and not access_map:
            if expect_friend:
                logger.warning("[岛屿] 预期已进入好友岛，但暂未识别到地图入口，继续等待好友岛入口")
            else:
                logger.info("[岛屿] 当前不在岛屿地图或好友岛，先导航到本岛")
                self.ui_goto(page_island, get_ship=False)

        for _ in self.loop(timeout=30 if expect_friend else 20, skip_first=False):
            if self.appear(ISLAND_MAP_CHECK):
                logger.info("[岛屿] 已进入岛屿地图")
                return True
            if self.appear_then_click(ISLAND_GOTO_MAP):
                logger.info("[岛屿] 点击本岛地图入口")
                continue
            if self.appear_then_click(ISLAND_ACCESS_MAP, offset=(20, 20)):
                logger.info("[岛屿] 点击好友岛右上角地图入口")
                continue
        else:
            logger.warning("[岛屿] 进入岛屿地图超时")
            return False

    def island_map_goto(self, destination):
        """在岛屿地图中点击目的地并确认前往。

        Args:
            destination (str): 目的地名称（如 'farm', 'port', 'mine_forest' 等）。

        Returns:
            bool: 是否成功到达目的地。

        Raises:
            ValueError: 传入未知的目的地名称。
        """
        def get_destination_buttons(name):
            if name == 'mine_forest':
                return ISLAND_MAP_MINE_FOREST, ISLAND_MAP_MINE_FOREST_CHECK
            if name == 'farm':
                return ISLAND_MAP_FARM, ISLAND_MAP_FARM_CHECK
            if name == 'nursery':
                return ISLAND_MAP_NURSERY, ISLAND_MAP_NURSERY_CHECK
            if name == 'assembly':
                return ISLAND_MAP_ASSEMBLY, ISLAND_MAP_ASSEMBLY_CHECK
            if name == 'port':
                return ISLAND_MAP_PORT, ISLAND_MAP_PORT_CHECK
            if name == 'port_business':
                return ISLAND_MAP_PORT_BUSINESS, ISLAND_MAP_PORT_BUSINESS_CHECK
            raise ValueError(f"未知的岛屿地图目的地: {name}")

        def get_friend_destination_check_button(name):
            if name == 'assembly':
                return ISLAND_MAP_ASSEMBLY_FRIEND_CHECK
            if name == 'port':
                return ISLAND_MAP_PORT_FRIEND_CHECK
            raise ValueError(f"好友岛地图不支持目的地: {name}")

        destination_button, check_button = get_destination_buttons(destination)
        in_friend = bool(getattr(self, "_island_expect_friend", False))
        if in_friend:
            check_button = get_friend_destination_check_button(destination)
        if not self.goto_island_map():
            return False
        destination_clicked = False
        confirmed = False
        for _ in self.loop(timeout=20, skip_first=False):
            if not destination_clicked:
                if self.appear_then_click(destination_button, interval=1):
                    logger.info(f"[岛屿] 点击岛屿地图目的地: {destination}")
                    destination_clicked = True
                continue

            if self.appear(check_button, offset=(20, 20)):
                logger.info(
                    f"[岛屿] 岛屿地图目的地详情已识别: {destination} "
                    f"({check_button.name})"
                )
                self.device.click(ISLAND_MAP_CONFIRM)
                confirmed = True
                break
            if self.appear_then_click(destination_button, interval=1):
                continue

        if not confirmed:
            logger.warning(f"[岛屿] 岛屿地图目的地选择超时: {destination}")
            return False

        confirm_wait = Timer(read_run_param(
            self.config, 'UiWait_IslandMapConfirmWait', ISLAND_MAP_CONFIRM_WAIT, 1, 60)).start()
        confirm_retry = Timer(read_run_param(
            self.config, 'UiWait_IslandMapConfirmRetryWait',
            ISLAND_MAP_CONFIRM_RETRY_WAIT, 1, 60)).start()
        for _ in self.loop(timeout=read_run_param(
                self.config, 'UiWait_IslandMapDestinationWait',
                ISLAND_MAP_DESTINATION_WAIT, 10, 600), skip_first=False):
            if self.ui_additional(get_ship=False):
                continue

            # 确认按钮通常会在场景加载开始后消失；若仍可见则在前 10s 内补点，
            # 超时窗口后不再点击，避免确认弹窗卡住时触发单按钮点击过多保护。
            if not confirm_retry.reached() and self.appear_then_click(
                    ISLAND_MAP_CONFIRM, interval=2):
                confirm_wait.reset()
                continue

            if self.ui_page_appear(page_island_map):
                continue

            if confirm_wait.reached() and (
                    self.appear(ISLAND_CHECK, offset=(20, 20))
                    or (in_friend and self.is_in_friend_island())
            ):
                self.device.sleep(1)
                logger.info(f"[岛屿] 岛屿地图进入成功: {destination}")
                return True

        logger.warning(f"[岛屿] 岛屿地图进入目的地超时: {destination}")
        return False
    def post_manage_mode(self, post_manage_mode):
        """切换岗位管理的模式页签（生产/经营）。

        Args:
            post_manage_mode (Button): 目标模式的标识按钮（如 POST_MANAGE_PRODUCTION 或 POST_MANAGE_BUSINESS）。

        Returns:
            bool: 切换成功返回 True。

        Raises:
            GameStuckError: 切换岗位管理页签超时。
        """
        post_manage_button = POST_MANAGE_BUSINESS if post_manage_mode == POST_MANAGE_PRODUCTION else POST_MANAGE_PRODUCTION
        direct_click_timer = Timer(1)
        for _ in self.loop(timeout=15, skip_first=False):
            if self.appear_then_click(post_manage_button, interval=1):
                continue
            elif self.appear(post_manage_mode):
                return True
            elif self.appear(ISLAND_GATHER_COLLECT_CHECK, offset=30):
                # 当前在采集页签，appear_then_click 无法匹配到生产和经营页签
                # 直接点击目标页签按钮（Button.button 返回点击坐标 tuple）
                if direct_click_timer.reached():
                    self.device.click(post_manage_button)
                    direct_click_timer.reset()
                    continue
        raise GameStuckError(f"切换岗位管理页签超时: {post_manage_mode}")

    def post_manage_mode_collection(self):
        """切换到采集页签（管理页面左侧第三个页签）。

        如果已经在采集页签则跳过，否则从当前页签切换过去。

        Returns:
            bool: 切换成功返回 True。

        Raises:
            GameStuckError: 切换采集页签超时。
        """
        for _ in self.loop(timeout=15, skip_first=False):
            if self.appear(ISLAND_GATHER_COLLECT_CHECK):
                return True
            if self.appear_then_click(ISLAND_GATHER_COLLECT, interval=1):
                continue
        raise GameStuckError("切换采集页签超时")

    def select_product(self, product_selection, product_selection_check):
        """在产品选择列表中寻找并选择指定产品。

        Args:
            product_selection (Button): 待点击的产品选择按钮模板。
            product_selection_check (Button): 选中状态确认按钮模板。

        Returns:
            bool: 是否成功选中目标产品。
        """
        # 清理之前可能残留的滑动记录，避免多次调用累积触发单按钮死循环检测
        # （click_record maxlen=15，两次调用各 _SELECT_PRODUCT_MAX_SWIPES 条 >12 阈值）
        self.device.click_record_remove(SELECTION_UP_SWIPE_NAME)

        for _ in range(_SELECT_PRODUCT_MAX_SWIPES):
            self.device.screenshot()

            # 使用形状+颜色双重验证来识别 product_selection_check
            if self.match_template_color(product_selection_check, offset=20, similarity=0.85, threshold=10):
                return True

            # 使用形状+颜色双重验证来识别 product_selection 并点击
            if self.match_template_color(product_selection, offset=300, similarity=0.85, threshold=10):
                self.device.click(product_selection)
                continue

            # 如果都不匹配，则滑动寻找
            self.device.swipe_vector(vector=(0, -200), box=(333, 142, 431, 602), name=SELECTION_UP_SWIPE_NAME)
            self.device.sleep(0.3)
            # 点击安全区域消除滑动惯性，使用 control_check=False 避免与 swipe 交替
            # 触发 GameTooManyClickError（两个按钮各 ≥6 次即报错）。
            # swipe 本身仍记录在 click_record 中，8 次滑动 < 12 次单按钮阈值，安全。
            self.device.click(SELECT_PRODUCT_INERTIA_STOP, control_check=False)
            self.device.sleep(0.2)

        return False

    def _handle_select_product_failure(self, product):
        """处理选择产品失败的后续操作：记录警告、关闭岗位面板、返回 False。

        Args:
            product (str): 产品标识。

        Returns:
            bool: 始终返回 False。
        """
        logger.warning(f"[岛屿] select_product 失败：未能找到产品 {self._item_cn(product)} 的选择项")
        self.device.click(POST_CLOSE)
        return False

    def post_close(self):
        """关闭岗位详情弹窗，回到岗位管理主界面。

        Returns:
            bool: 关闭成功返回 True，超时返回 False。
        """
        for _ in self.loop(timeout=15, skip_first=False):
            if self.ui_page_appear(page_island_postmanage) and not self.is_post_detail_visible():
                return True
            if self.appear(ISLAND_GET, offset=30):
                self.device.click(ISLAND_POST_SAFE_AREA)
                continue
            if self.is_post_detail_visible():
                self.device.click(POST_CLOSE)
                continue
        logger.warning("[岛屿] 关闭岗位详情超时")
        return False

    def is_post_detail_visible(self):
        """判断岗位详情弹窗是否仍覆盖在岗位管理页上。

        Returns:
            bool: 岗位详情相关按钮是否可见。
        """
        return (
                self.appear(ISLAND_POST_CHECK, offset=1)
                or self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
                or self.appear(ISLAND_POST_SELECT, offset=1)
                or self.appear(ISLAND_WORKING, offset=1)
                or self.appear(POST_ADD)
                or self.appear(POST_GET, offset=(50, 0))
        )

    def post_get_and_close(self):
        """收取当前岗位产物并关闭岗位详情弹窗。

        Returns:
            bool: 收取并关闭成功返回 True，超时返回 False。
        """
        for _ in self.loop(timeout=20, skip_first=False):
            if self.ui_page_appear(page_island_postmanage) and not self.is_post_detail_visible():
                return True
            if self.appear(ERROR1, offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                continue
            if self.appear(ISLAND_GET, offset=30):
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                continue
            if self.appear_then_click(POST_GET, offset=(50, 0)):
                self.device.sleep(0.5)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                continue
            if self.is_post_detail_visible() and not self.appear(POST_GET, offset=(50, 0)):
                self.device.click(POST_CLOSE)
                continue
        logger.warning("[岛屿] 收取并关闭岗位详情超时")
        return False

    def post_get_stay(self):
        """收取当前岗位产物并停留在岗位详情界面，供后续直接复检状态。

        Returns:
            bool: 收取成功返回 True，超时返回 False。
        """
        for _ in self.loop(timeout=20, skip_first=False):
            if self.appear(ERROR1, offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                continue
            if self.appear(ISLAND_GET, offset=30):
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                continue
            if self.appear_then_click(POST_GET, offset=(50, 0)):
                self.device.sleep(0.5)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                continue
            if (self.is_post_detail_visible() or self.ui_page_appear(page_island_postmanage)):
                return True
        logger.warning("[岛屿] 收取当前岗位产物超时")
        return False

    def post_get_and_add(self, product_selection, product_selection_check):
        """收取产物并追加派遣生产。

        Args:
            product_selection (Button): 目标产品的选择按钮。
            product_selection_check (Button): 目标产品的选中确认标识。

        Returns:
            bool: 成功追加派遣返回 True，失败或超时返回 False。
        """
        for _ in self.loop(timeout=30, skip_first=False):
            if self.appear(ERROR1,offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                return False
            if self.appear(ISLAND_GET,offset=1):
                self.device.click(ISLAND_POST_SAFE_AREA)
                continue
            if self.appear_then_click(POST_ADD,offset=1):
                continue
            if self.appear_then_click(POST_GET,offset=(50,0)):
                self.device.sleep(0.5)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                continue
            if self.appear_then_click(ISLAND_POST_SELECT,offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK,offset=1):
                if self.select_character():
                    if not self.confirm_selected_character("岗位追加派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return False
                else:
                    logger.warning("[岛屿] 岗位追加派遣无可用角色")
                    self.back_to_postmanage_from_dispatch()
                    return False
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK,offset=1):
                if self.select_product(product_selection,product_selection_check):
                    self.device.sleep(0.3)
                    if not self.confirm_post_add_order("岗位派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return False
                else:
                    self.device.click(POST_CLOSE)
                    return False
                continue
            if (
                    (self.appear(ISLAND_POST_CHECK, offset=30) or self.appear(ISLAND_POST_VACANT_CHECK, offset=30))
                    and not self.appear(POST_GET, offset=(50, 0))
                    and not self.appear(POST_ADD)
                    and not self.appear(ISLAND_POST_SELECT, offset=30)
            ):
                self.device.click(POST_CLOSE)
                return True
            if (
                    self.ui_page_appear(page_island_postmanage)
                    and not self.is_post_detail_visible()
            ):
                return True
        logger.warning("[岛屿] 收取并追加岗位派遣超时")
        return False

    def back_to_postmanage_from_dispatch(self):
        """从角色选择或产品选择流程退回岗位管理页。

        Returns:
            bool: 是否成功退回岗位管理页。
        """
        self.interval_clear([SELECT_UI_BACK, POST_CLOSE])
        for _ in self.loop(timeout=15, skip_first=False):
            if (
                    self.ui_page_appear(page_island_postmanage)
                    and not self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1)
                    and not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1)
                    and not self.is_post_detail_visible()
            ):
                return True
            if self.appear(ISLAND_GET, offset=30):
                self.device.click(ISLAND_POST_SAFE_AREA)
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                self.device.click(SELECT_UI_BACK)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                self.device.click(SELECT_UI_BACK)
                continue
            if self.is_post_detail_visible():
                self.device.click(POST_CLOSE)
                continue

        logger.warning("[岛屿] 从派遣流程返回岗位管理页超时")
        return False

    def confirm_post_add_order(self, context="岗位派遣"):
        """材料确认足够后，点击最大数量并确认派遣。

        Args:
            context (str): 操作上下文描述（用于日志记录）。

        Returns:
            bool: 确认派遣是否成功。
        """
        clicked = False
        max_clicked = False
        button_seen = False
        left_product_timer = Timer(0.8, count=2).start()
        retry_confirm_timer = Timer(2, count=4).start()
        unavailable_timer = Timer(3, count=6).start()

        for _ in self.loop(timeout=10, skip_first=False):
            if self.appear(ERROR1, offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                return False

            in_select_product = self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1)
            if not in_select_product:
                if left_product_timer.reached():
                    return True
                continue
            left_product_timer.reset()

            if not clicked and not max_clicked and self.appear(POST_MAX):
                self.device.click(POST_MAX)
                max_clicked = True
                unavailable_timer.reset()
                self.device.sleep(0.3)
                continue

            if self.appear(POST_ADD_ORDER):
                button_seen = True
                unavailable_timer.reset()
                if not clicked or retry_confirm_timer.reached():
                    if clicked:
                        logger.info(f"[岛屿] {context}确认后仍停留在产品选择页，重试确认")
                    self.device.click(POST_ADD_ORDER)
                    clicked = True
                    retry_confirm_timer.reset()
                continue

            if not clicked and unavailable_timer.reached():
                current, required = self.ocr_select_product_material_counter()
                if required and current < required:
                    logger.warning(f"[岛屿] {context}材料不足，确认按钮不可用: {current}/{required}")
                else:
                    logger.warning(f"[岛屿] {context}材料已确认足够，但确认按钮不可用，可能角色体力不足")
                return False

        if clicked or button_seen:
            logger.warning(f"[岛屿] {context}确认后仍停留在产品选择页")
            return False

        current, required = self.ocr_select_product_material_counter()
        if required and current < required:
            logger.warning(f"[岛屿] {context}材料不足，确认按钮不可用: {current}/{required}")
        else:
            logger.warning(f"[岛屿] {context}材料已确认足够，但确认按钮不可用，可能角色体力不足")
        return False

    def is_character_page_visible(self):
        """重新截取一帧，判断角色选择页是否仍然可见。

        确认按钮补点前调用：云手机的截图与点击都有明显延迟，用上一帧的识别结果
        点击时，点击可能在页面已经切换之后才送达，从而打到下一页同位置的按钮上
        （选餐页确认按钮与角色页确认按钮坐标重叠）。因此每次补点前都基于最新
        截图复核一次。

        Returns:
            bool: 最新截图上角色选择页标题或确认按钮是否可见。
        """
        self.device.screenshot()
        if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
            return True
        return self.appear(SELECT_UI_CONFIRM)

    def confirm_selected_character(self, context="岗位派遣"):
        """确认角色选择，并等待角色选择页切换到下一步。

        采用“点击→复检→重试”的状态循环：只有在本帧确实识别到角色选择页
        （页面标题或确认按钮）时才补点确认，点击前还会重新截取一帧复核，
        避免云手机转场较慢时把确认按钮点到下一页同位置的按钮上（选餐页确认
        按钮坐标重叠，误点会把默认餐品直接下单）。角色页迟迟没有关闭时按
        ISLAND_CHARACTER_CONFIRM_RETRY_WAIT 秒间隔重试，最多点击
        ISLAND_CHARACTER_CONFIRM_MAX_CLICKS 次；次数用尽后只观察页面是否切换，
        仍无进展则记录次数并返回 False，交由调用方回退岗位管理页，避免卡死。

        Args:
            context (str): 操作上下文描述（用于日志记录）。

        Returns:
            bool: 是否成功进入下一步。
        """
        self.interval_clear([SELECT_UI_CONFIRM])
        # 首次确认立即点击，之后每次补点至少间隔 ISLAND_CHARACTER_CONFIRM_RETRY_WAIT 秒
        retry_timer = Timer(read_run_param(
            self.config, 'UiWait_IslandCharacterConfirmRetryWait',
            ISLAND_CHARACTER_CONFIRM_RETRY_WAIT, 1, 60)).clear()
        confirm_clicks = 0
        skipped_clicks = 0
        role_seen = False
        for _ in self.loop(timeout=25, skip_first=False):
            in_role_page = self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1)
            confirm_visible = self.appear(SELECT_UI_CONFIRM)
            role_seen = role_seen or in_role_page or confirm_visible

            # 已进入已知的下一步：产品选择页
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                return True
            # 角色页已关闭，且岗位详情/空缺卡已出现
            if (
                    (self.appear(ISLAND_POST_CHECK, offset=1)
                     or self.appear(ISLAND_POST_VACANT_CHECK, offset=1))
                    and not in_role_page
            ):
                return True
            # 整个确认流程中从未识别到角色选择页，说明无需确认或已离开
            if (
                    not role_seen
                    and self.ui_page_appear(page_island_postmanage)
                    and not self.is_post_detail_visible()
            ):
                return True

            # 未进入任何已知下一步：只有本帧仍识别到角色页时才允许补点确认。
            # 识别不到角色页（页面正在转场或已经切页）时不点击，避免把确认按钮
            # 点到下一页同位置的按钮上。
            if not in_role_page and not confirm_visible:
                continue
            if confirm_clicks >= ISLAND_CHARACTER_CONFIRM_MAX_CLICKS:
                continue
            if not retry_timer.reached():
                continue
            retry_timer.reset()
            # 点击前基于最新截图复核，把“用旧画面点击”的时间差压到最小
            if not self.is_character_page_visible():
                if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                    return True
                skipped_clicks += 1
                continue
            self.device.click(SELECT_UI_CONFIRM_SAFE)
            confirm_clicks += 1

        logger.warning(
            f"[岛屿] {context}确认后未进入下一步"
            f"（已重试点击 {confirm_clicks} 次，跳过误点 {skipped_clicks} 次）"
        )
        return False

    def confirm_selected_character_closed(self, context="角色选择", timeout=8):
        """确认角色选择，并等待角色选择页关闭。

        补点规则与 confirm_selected_character 保持一致：只有本帧仍识别到角色页时
        才补点，点击前重新截图复核，且两次点击间隔不小于
        ISLAND_CHARACTER_CONFIRM_RETRY_WAIT（需大于云手机的页面转场时间），
        避免上一次点击已经生效、页面正在切换时把确认按钮点到下一页同位置的按钮上。

        Args:
            context (str): 操作上下文描述。
            timeout (int): 等待超时时间（秒）。

        Returns:
            bool: 角色选择页是否成功关闭。
        """
        if not self.click_selected_character_confirm(context=context):
            return False

        retry_timer = Timer(read_run_param(
            self.config, 'UiWait_IslandCharacterConfirmRetryWait',
            ISLAND_CHARACTER_CONFIRM_RETRY_WAIT, 1, 60)).start()
        for _ in self.loop(timeout=timeout, skip_first=False):
            if not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                return True
            if not retry_timer.reached():
                continue
            retry_timer.reset()
            # 点击前基于最新截图复核，避免用旧画面点击已经切换过去的页面
            if not self.is_character_page_visible():
                if not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                    return True
                continue
            self.device.click(SELECT_UI_CONFIRM_SAFE)

        logger.warning(f"[岛屿] {context}确认后仍停留在角色选择页")
        return False

    def click_selected_character_confirm(self, context="角色选择", timeout=5):
        """等待角色确认按钮出现并点击安全段。

        点击前重新截取一帧复核，并只点击确认按钮右侧安全段（与选餐页确认按钮等
        其它页面按钮不重叠），避免云手机转场较慢时误点到下一页同位置的按钮。

        Args:
            context (str): 操作上下文描述。
            timeout (int): 等待超时时间（秒）。

        Returns:
            bool: 是否成功点击确认。
        """
        self.interval_clear([SELECT_UI_CONFIRM])
        for _ in self.loop(timeout=timeout, skip_first=False):
            if not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                return True
            # threshold 与原 appear_then_click(threshold=30) 保持一致，
            # 避免把“按钮可见但颜色有偏差”的机型挡在门外
            if not self.appear(SELECT_UI_CONFIRM, threshold=30):
                continue
            if not self.is_character_page_visible():
                if not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                    return True
                continue
            self.device.click(SELECT_UI_CONFIRM_SAFE)
            return True

        if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
            logger.warning(f"[岛屿] {context}确认按钮未出现")
            return False
        return True

    def post_open(self, post):
        """点击并打开指定岗位，支持重试滑动定位。

        Args:
            post (Button): 目标岗位按钮。

        Returns:
            bool: 岗位是否成功打开（未解锁返回 False）。

        Raises:
            GameStuckError: 岗位按钮未识别或打开超时。
        """
        template = TEMPLATE_POST_LOCK
        retry_swipe_timer = Timer(3, count=3).start()
        retry_swipe_used = 0
        full_retry_used = 0
        # 补滑轮次放宽后单轮可达十几秒，45 秒预算在低端机上撑不满整条重试链，
        # 放宽到 90 秒；正常路径在补滑命中时就退出，不受影响。
        for image in self.loop(timeout=90, skip_first=False):
            post_appear = self.appear(post, offset=300)
            if post_appear:
                retry_swipe_timer.reset()
                cell_image = crop(image, post.button)
                if template.match(cell_image, similarity=0.85):
                    return False
            if self.appear(ISLAND_POST_CHECK) or self.appear(ISLAND_POST_VACANT_CHECK):
                return True
            if self.appear(ISLAND_POST_SELECT, offset=1):
                return True
            if post_appear:
                self.device.sleep(0.1)
                self.device.click(post)
                self.device.sleep(0.5)
                continue
            if (
                    getattr(self, 'post_open_retry_swipe', False)
                    and retry_swipe_used < getattr(self, 'post_open_retry_swipe_limit', 1)
                    and retry_swipe_timer.reached()
            ):
                retry_swipe_used += 1
                logger.info(f"[岛屿] 未识别到岗位按钮 {post}，第{retry_swipe_used + 1}次滑动定位岗位列表")
                swipe_count = getattr(self, 'post_manage_swipe_count', 1)
                if swipe_count >= 2:
                    # 店铺岗位位于列表较深处：先回到顶部按调参步数下滑，再继续补滑
                    # 直到目标岗位出现（模拟器滑动距离不够时自动补偿）
                    self.post_manage_swipe_to_top()
                    self.post_manage_swipe_until_appear(post, min_swipes=swipe_count)
                else:
                    self.post_manage_swipe(swipe_count)
                retry_swipe_timer.reset()
                continue
            if (
                    getattr(self, 'post_open_retry_swipe', False)
                    and retry_swipe_used >= getattr(self, 'post_open_retry_swipe_limit', 1)
                    and retry_swipe_timer.reached()
            ):
                if full_retry_used < getattr(self, 'post_open_full_retry_limit', 1):
                    full_retry_used += 1
                    logger.warning(
                        f"[岛屿] 岗位按钮 {post} 连续{retry_swipe_used + 1}次滑动定位失败，重新进入岗位管理页重试"
                    )
                    self.post_close()
                    self.goto_postmanage()
                    self.post_manage_mode(POST_MANAGE_PRODUCTION)
                    self.post_manage_swipe(getattr(self, 'post_manage_swipe_count', 1))
                    retry_swipe_used = 0
                    retry_swipe_timer.reset()
                    continue
                raise GameStuckError(f"岗位按钮 {post} 完整重试后仍未识别")
        raise GameStuckError(f"打开岗位详情超时: {post}")

    def post_manage_up_swipe(self, distance):
        """在岗位列表中向上滑动指定距离。

        滑动放慢到 0.4-0.6 秒：默认 0.1-0.2 秒的快滑在低端机低帧率下会被压缩进
        一两帧，游戏侧实际滚动缩水，多滑也停在原地（老机型滑不到列表底部）。

        Args:
            distance (int): 滑动距离像素。
        """
        self.device.swipe_vector(
            vector=(0, -distance), box=(688, 69, 725, 656), name="PostUpSwipe", duration=(0.4, 0.6))
        self.device.click(POST_MANAGE_SWIPE_STOP, control_check=False)

    def post_manage_down_swipe(self, distance):
        """在岗位列表中向下滑动指定距离。

        滑动节奏与 [post_manage_up_swipe](up) 保持一致，原因同上。

        Args:
            distance (int): 滑动距离像素。
        """
        self.device.swipe_vector(
            vector=(0, distance), box=(688, 69, 725, 656), name="PostDownSwipe", duration=(0.4, 0.6))
        self.device.click(POST_MANAGE_SWIPE_STOP, control_check=False)

    def post_manage_swipe_to_top(self, max_swipes=None):
        """向下补滑，直到岗位列表回到顶部（农田/牧场岗位所在的第一行可见）。

        岗位列表的定位不能只靠固定次数：模拟器/云手机上一次滑动实际滚动的距离
        会明显小于期望值，固定 2 次 450 常常停在中途，后续 post_open 就找不到
        岗位按钮（例如牧场磨坊流程）。这里改为“滑动→检测列表首行→继续补滑”的
        闭环，向下滑动会被列表顶部截断，因此不会滑过头。

        Args:
            max_swipes (int, optional): 最大补滑次数，默认 ISLAND_POST_SWIPE_TO_TOP_MAX。

        Returns:
            bool: 列表是否已回到顶部。
        """
        max_swipes = max_swipes or ISLAND_POST_SWIPE_TO_TOP_MAX
        for i in range(max_swipes + 1):
            # 每轮重新截图：滑动后必须用最新画面判断是否已到顶部，
            # 否则会拿滑动前的旧帧判断，导致多滑或漏判
            self.device.screenshot()
            if self.appear(ISLAND_FARM_POST1, offset=100):
                return True
            if i == max_swipes:
                break
            self.post_manage_down_swipe(ISLAND_POST_SWIPE_DISTANCE)
            self.device.sleep(0.3)
        logger.warning(f"[岛屿] 岗位列表回顶部失败（已补滑 {max_swipes} 次），岗位定位可能不准")
        return False

    def post_manage_swipe(self, count):
        """按指定步数在岗位列表中执行定位滑动。

        Args:
            count (int): 滑动步数。
        """
        if count >= 2:
            # 先回到列表顶部再按固定步数下滑，避免从上一次遗留的滚动位置出发
            # 导致滑动距离不够或过头
            self.post_manage_swipe_to_top()
            for _ in range(count):
                self.post_manage_up_swipe(ISLAND_POST_SWIPE_STEP)
        elif count == 1:
            if self.appear(ISLAND_FARM_POST1, offset=100):
                for _ in range(count):
                    self.post_manage_up_swipe(ISLAND_POST_SWIPE_STEP)
            else:
                self.post_manage_swipe_to_top()
                for _ in range(count):
                    self.post_manage_up_swipe(ISLAND_POST_SWIPE_STEP)
        elif count == 0:
            self.post_manage_swipe_to_top()

    def post_manage_swipe_until_appear(self, post, min_swipes=1, max_swipes=None, offset=300):
        """向下补滑，直到目标岗位按钮出现。

        先按原有调参滑动 min_swipes 次，之后每次滑动都检测目标岗位；模拟器/云手机
        上一次滑动实际滚动的距离不够时，会自动继续补滑，避免岗位按钮停在画面外。

        Args:
            post (Button): 目标岗位按钮。
            min_swipes (int): 至少滑动的次数，保留原有调参位置。
            max_swipes (int): 最大滑动次数，默认 ISLAND_POST_SWIPE_SEARCH_MAX。
            offset (int): 岗位按钮模板匹配的搜索偏移。

        Returns:
            bool: 补滑后是否识别到目标岗位按钮。
        """
        max_swipes = max(max_swipes or ISLAND_POST_SWIPE_SEARCH_MAX, min_swipes)
        for i in range(max_swipes + 1):
            # 同上：滑动后用最新截图判断目标岗位是否出现
            self.device.screenshot()
            if i >= min_swipes and self.appear(post, offset=offset):
                return True
            if i == max_swipes:
                break
            self.post_manage_up_swipe(ISLAND_POST_SWIPE_STEP)
            self.device.sleep(0.3)
        return False

    def island_up(self, hold_time):
        """在岛屿场景中按住向上移动摇杆。

        Args:
            hold_time (int): 按住移动的时间（毫秒）。
        """
        p1 = (218, 507)
        p2 = (218, 441)
        self.device.island_swipe_hold(p1, p2, hold_time)

    def island_down(self, hold_time):
        """在岛屿场景中按住向下移动摇杆。

        Args:
            hold_time (int): 按住移动的时间（毫秒）。
        """
        p1 = (218, 507)
        p2 = (218, 572)
        self.device.island_swipe_hold(p1, p2, hold_time)

    def island_right(self, hold_time):
        """在岛屿场景中按住向右移动摇杆。

        Args:
            hold_time (int): 按住移动的时间（毫秒）。
        """
        p1 = (218, 507)
        p2 = (282, 507)
        self.device.island_swipe_hold(p1, p2, hold_time)

    def island_left(self, hold_time):
        """在岛屿场景中按住向左移动摇杆。

        Args:
            hold_time (int): 按住移动的时间（毫秒）。
        """
        p1 = (218, 507)
        p2 = (152, 507)
        self.device.island_swipe_hold(p1, p2, hold_time)

    def island_move(self, direction, hold_time):
        """按方向按住岛屿移动摇杆。

        Args:
            direction (str): 'up' / 'down' / 'left' / 'right'。
            hold_time (int): 按住移动的时间（毫秒）。
        """
        actions = {
            'up': self.island_up,
            'down': self.island_down,
            'left': self.island_left,
            'right': self.island_right,
        }
        actions[direction](hold_time)

    def island_walk_rule(self, route):
        """读取某条路线的规则（岛屿计划全局配置，跨任务生效）。

        Args:
            route (str): 路线名，对应 `IslandPlan.IslandWalk.<路线名>`。

        Returns:
            str: 用户在岛屿计划里填写的规则字符串；未配置时返回空串。
        """
        return self.config.cross_get(f'IslandPlan.IslandWalk.{route}', default='') or ''

    def island_walk_enabled(self, route):
        """该路线是否勾选了走位校验。

        Args:
            route (str): 路线名。

        Returns:
            bool: 勾选了 `IslandPlan.IslandWalk.<路线名>Enable` 时返回 True。
        """
        return bool(self.config.cross_get(f'IslandPlan.IslandWalk.{route}Enable', default=False))

    def island_walk_steps(self, route):
        """返回本次实际执行的走位步骤。

        优先使用岛屿计划全局配置里的规则字符串（所有控制方式都生效）；
        未填写或解析失败时回退到代码默认值。

        Args:
            route (str): 路线名，见 `module/island/island_walk.py`。

        Returns:
            tuple: `((方向, 毫秒), ...)`。
        """
        steps = ISLAND_WALK_ROUTES[route]
        raw = str(self.island_walk_rule(route)).strip()
        if not raw:
            return steps
        parsed = parse_walk_rule(raw)
        if parsed is None:
            logger.warning(f'[岛屿-走位] 规则 {route}={raw!r} 解析失败，本次使用代码默认值')
            return steps
        logger.attr('岛屿走位', f'{route}: {format_walk_rule(parsed)}')
        return parsed

    def island_walk_durations(self, route):
        """返回该路线所有走位步骤的时长（毫秒，跳过固定动作）。

        Args:
            route (str): 路线名。

        Returns:
            list[int]: 按执行顺序排列的毫秒时长。
        """
        return [hold for direction, hold in self.island_walk_steps(route)
                if direction not in ISLAND_WALK_ACTIONS]

    def island_walk_switch_restaurant(self):
        """规则里 `switch` 步骤：切换到啾咖啡餐厅并等待岛内可操作。

        Pages:
            page_island
        """
        from module.island_daily_interact.assets import ROUTE_TWO_OPTION_COMPLETE

        for _ in self.loop(timeout=12, skip_first=False):
            if self.appear(ISLAND_CHECK):
                return
            if self.appear(ROUTE_TWO_OPTION_COMPLETE):
                self.device.click(ROUTE_TWO_OPTION_COMPLETE)
        raise GameStuckError('切换啾咖啡餐厅超时，停止后续岛屿走位')

    def island_walk_action(self, action):
        """执行规则里的固定动作步骤。

        Args:
            action (str): `jump`（点跳跃按钮）或 `switch`（切换啾咖啡餐厅）。

        Raises:
            ScriptError: 未知动作。
        """
        if action == 'jump':
            self.device.click(ISLAND_JUMP)
        elif action == 'switch':
            self.island_walk_switch_restaurant()
        else:
            raise ScriptError(f'未知的走位动作: {action}')

    def island_walk_route(self, route):
        """按路线依次走位；`jump` / `switch` 等动作步骤不占时长。

        Args:
            route (str): 路线名，见 `module/island/island_walk.py`。

        Pages:
            page_island
        """
        for direction, hold_time in self.island_walk_steps(route):
            if direction in ISLAND_WALK_ACTIONS:
                self.island_walk_action(direction)
                continue
            self.island_move(direction, hold_time)

    def island_walk_composite_durations(self, route, count):
        """复合路线（中间夹着拾取检测等固定操作）按位置取时长。

        这类路线的方向和中间操作都由代码固定，配置只提供每一步的时长；
        个数对不上时回退代码默认值并告警，避免取到不存在的下标。

        Args:
            route (str): 路线名。
            count (int): 代码需要的走位步数。

        Returns:
            list[int]: 长度等于 count 的毫秒时长列表。
        """
        configured = [(direction, hold) for direction, hold in self.island_walk_steps(route)
                      if direction not in ISLAND_WALK_ACTIONS]
        default = [(direction, hold) for direction, hold in ISLAND_WALK_ROUTES[route]
                   if direction not in ISLAND_WALK_ACTIONS]
        if len(configured) != count or [direction for direction, _ in configured] != [
                direction for direction, _ in default]:
            logger.warning(
                f'[岛屿-走位] {route} 的步数或方向与固定补滑路线不一致，'
                '本次使用代码默认值'
            )
            return [hold for _, hold in default]
        return [hold for _, hold in configured]

    def set_buy_number(self, target):
        """设置购买弹窗中的目标购买数量。

        Args:
            target (int): 目标购买数量。
        """
        increment = target - 1
        add_ten_clicks = increment // 10
        add_one_clicks = increment % 10
        add_ten_buttons = (ADD_TEN_A, ADD_TEN_B, ADD_TEN_C)
        for index in range(add_ten_clicks):
            self.device.click(add_ten_buttons[index % len(add_ten_buttons)])

        add_one_buttons = (ADD_ONE_A, ADD_ONE_B, ADD_ONE_C)
        for index in range(add_one_clicks):
            self.device.click(add_one_buttons[index % len(add_one_buttons)])

    def switch_shop_tab(self, tab_check, tab_button):
        """切换岛屿商店内的页签。

        Args:
            tab_check (Button): 目标页签激活状态的判定按钮。
            tab_button (Button): 目标页签的点击按钮。

        Returns:
            bool: 切换成功返回 True，超时返回 False。
        """
        click_count = 0
        self.interval_clear([tab_button])
        for _ in self.loop(timeout=8, skip_first=False):
            if self.appear(tab_check, offset=1, threshold=30):
                if click_count:
                    logger.info(f"[岛屿] 商店页签检测成功: {tab_check}，点击 {click_count} 次")
                return True
            if self.appear(tab_button, threshold=30):
                click_count += 1
                logger.info(f"[岛屿] 商店页签检测失败，点击页签: {tab_button} -> {tab_check}，第 {click_count} 次")
                self.device.click(tab_button)
                self.device.sleep(1)
                continue

        logger.warning(f"[岛屿] 切换商店页签超时: tab={tab_button}, check={tab_check}, clicked={click_count}")
        return False

    def buy_shop_item(self, item_button, quantity, shop_check, item_name=None,
                      tab_check=None, tab_button=None):
        """购买岛屿商店商品，适用于种子、鱼苗等同构购买弹窗。

        Args:
            item_button (Button): 商品图标按钮。
            quantity (int): 购买数量。
            shop_check (Button): 商店界面判定按钮。
            item_name (str, optional): 商品名称。默认为 None。
            tab_check (Button, optional): 所属页签激活判定按钮。默认为 None。
            tab_button (Button, optional): 所属页签点击按钮。默认为 None。

        Returns:
            bool: 购买成功返回 True，失败或超时返回 False。
        """
        quantity = max(1, int(quantity))
        if tab_check is not None and tab_button is not None:
            if not self.switch_shop_tab(tab_check, tab_button):
                return False

        if item_name:
            logger.info(f"[岛屿] 购买 {self._item_cn(item_name)} x{quantity}")

        for _ in self.loop(timeout=10, skip_first=False):
            # 使用模板检测（offset=(1,1)）判断购买弹窗是否打开，
            # 不能退化为颜色检测，避免商店 3D 背景像素恰好匹配导致误判
            if self.appear(ISLAND_SHOPPING_CHECK, offset=(1, 1)):
                break
            if self.appear_then_click(item_button, interval=1.2):
                continue
        else:
            logger.warning(f"[岛屿] 打开购买弹窗超时: {item_name or item_button}")
            return False

        if self.appear(ISLAND_SHOPPING_CHECK, offset=(1, 1)):
            self.set_buy_number(quantity)

        for _ in self.loop(timeout=15, skip_first=False):
            shop_visible = self.appear(shop_check, offset=1)
            shopping_shown = self.appear(ISLAND_SHOPPING_CHECK, offset=(1, 1))
            if shop_visible and not shopping_shown:
                break
            if self.appear_then_click(ISLAND_SHOP_CONFIRM, interval=1):
                # 点击确认后立即复检：弹窗或确认按钮消失都视为购买完成，退出避免重复点击
                self.device.sleep(0.5)
                self.device.screenshot()
                if not self.appear(ISLAND_SHOP_CONFIRM) or not self.appear(ISLAND_SHOPPING_CHECK, offset=(1, 1)):
                    break
                continue
            # 使用模板检测判断“购买成功”弹窗，商店页大面积浅色背景的平均颜色与弹窗资源接近，
            # 纯颜色检测会误判并要求反复点击确认按钮。
            if self.appear(ISLAND_SHOP_GET, offset=(1, 1)):
                self.device.click(ISLAND_SHOP_CONFIRM)
                continue
        else:
            logger.warning(f"[岛屿] 确认购买超时: {item_name or item_button}")
            return False

        if self.appear(ISLAND_SHOP_GET, offset=(1, 1)):
            self.device.click(ISLAND_SHOP_CONFIRM)
        return True

    def goto_shop_from_select_product(self, shop_check, tab_check=None, tab_button=None):
        """从岗位产品选择页跳转到补充材料的商店页签。

        Args:
            shop_check (Button): 商店界面判定按钮。
            tab_check (Button, optional): 目标页签激活判定按钮。默认为 None。
            tab_button (Button, optional): 目标页签点击按钮。默认为 None。

        Returns:
            bool: 跳转成功返回 True，超时返回 False。
        """
        self.interval_clear([ISLAND_SELECT_GOTO_BUY_SEED, ISLAND_SELECT_SEED])
        tab_click_count = 0
        for _ in self.loop(timeout=20, skip_first=False):
            in_select_product = self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1)
            in_shop = self.appear(shop_check)
            in_tab = tab_check is not None and self.appear(tab_check, threshold=30)
            goto_buy = self.appear(ISLAND_SELECT_GOTO_BUY_SEED)

            if not in_select_product and tab_check is not None and in_tab:
                if tab_click_count:
                    logger.info(f"[岛屿] 补货商店页签检测成功: {tab_check}，点击 {tab_click_count} 次")
                return True
            if not in_select_product and tab_button is not None and in_shop:
                tab_click_count += 1
                logger.info(
                    f"[岛屿] 补货商店页签检测失败，点击页签: {tab_button} -> {tab_check}，第 {tab_click_count} 次"
                )
                self.device.click(tab_button)
                self.device.sleep(1)
                continue
            if not in_select_product and tab_check is None and in_shop:
                return True

            if goto_buy:
                self.device.click(ISLAND_SELECT_GOTO_BUY_SEED)
                continue

            if in_select_product:
                self.device.click(ISLAND_SELECT_SEED)
                self.device.sleep(0.3)
                self.device.screenshot()
                if self.appear(ISLAND_SELECT_GOTO_BUY_SEED):
                    self.device.click(ISLAND_SELECT_GOTO_BUY_SEED)
                    continue
                self.device.click(ISLAND_SELECT_GOTO_BUY_SEED)
                self.device.sleep(0.5)
                continue

        logger.warning("[岛屿] 从岗位产品选择页进入补货商店超时")
        return False

    @staticmethod
    def normalize_select_product_material_text(result):
        """规范化岗位产品选择页材料 OCR 文本，修复易混淆字符。

        Args:
            result (str | list): OCR 识别结果文本。

        Returns:
            str: 规范化后的字符串。
        """
        return str(result).replace('I', '1').replace('D', '0').replace('S', '5').replace('B', '8')

    @staticmethod
    def parse_select_product_material_current(result, require_separator=False):
        """解析岗位材料文本中的当前库存数值。

        Args:
            result (str): 材料数量文本（如 "12/20" 或 "12"）。
            require_separator (bool): 是否强制要求包含分隔符 '/'。默认为 False。

        Returns:
            int | None: 解析出的库存数量；未找到或不符合要求返回 None。
        """
        result = Island.normalize_select_product_material_text(result)
        if '/' in result:
            current_text = result.split('/', 1)[0]
            current_numbers = re.findall(r'\d+', current_text)
            if current_numbers:
                return int(current_numbers[-1])
            return None
        if require_separator:
            return None
        match = re.search(r'\d+', result)
        if match:
            return int(match.group())
        return None

    @staticmethod
    def build_select_product_material_counter_text(current, result, prefix_text=None, allow_suffix_rebuild=True):
        """构建规范化的岗位材料需求计数文本。

        Args:
            current (int): 当前材料库存数量。
            result (str): 识别到的原始材料文本。
            prefix_text (str, optional): 前缀候选文本。默认为 None。
            allow_suffix_rebuild (bool): 是否允许通过后缀重建需求数。默认为 True。

        Returns:
            str: 格式化后的材料文本（如 "current/required" 或 "current"）。
        """
        result = Island.normalize_select_product_material_text(result)
        prefix_text = Island.normalize_select_product_material_text(prefix_text or '')

        if '/' in result and Island.parse_select_product_material_current(result, require_separator=True) == current:
            return result

        texts = [prefix_text, result]
        for text in texts:
            if '/' not in text:
                continue
            current_text, required_text = text.split('/', 1)
            current_numbers = re.findall(r'\d+', current_text)
            required_numbers = re.findall(r'\d+', required_text)
            if current_numbers and int(current_numbers[-1]) == current and required_numbers:
                return f"{current}/{' + '.join(required_numbers)}".replace(' + ', '+')

        full_numbers = re.findall(r'\d+', result)
        if (allow_suffix_rebuild or current == 0) and full_numbers:
            full_text = full_numbers[0]
            current_text = str(current)
            if full_text.startswith(current_text) and len(full_text) > len(current_text):
                return f"{current}/{full_text[len(current_text):]}"

        return str(current)

    def ocr_select_product_material_text(self, button=None, show_log=True):
        """读取岗位产品选择页底部材料数量文本。

        Args:
            button (Button, optional): OCR 识别区域按钮。默认为 OCR_SELECT_PRODUCT_MATERIAL_AMOUNT。
            show_log (bool): 是否打印 OCR 日志。默认为 True。

        Returns:
            str: 规范化后的材料数量文本。
        """
        button = button or OCR_SELECT_PRODUCT_MATERIAL_AMOUNT
        ocr = Ocr(
            button,
            letter=(225, 225, 226),
            threshold=128,
            alphabet='0123456789/+()IDSB',
            name=getattr(button, 'name', None) or 'OCR_SELECT_PRODUCT_MATERIAL_AMOUNT',
        )
        ocr.SHOW_LOG = show_log
        result = ocr.ocr(self.device.image)
        if isinstance(result, list):
            result = ''.join(str(item) for item in result)
        return self.normalize_select_product_material_text(result)

    def ocr_select_product_material_detail(self, expected_quantity=None):
        """读取岗位产品选择页材料数量，返回当前库存和页面材料文本。

        Args:
            expected_quantity (int, optional): 期望或最大需要的数量，用于辅助校验 OCR 候选值。默认为 None。

        Returns:
            tuple[int, str]: (当前库存数量, 格式化后的材料文本)。
        """
        result = self.ocr_select_product_material_text()
        current = self.parse_select_product_material_current(result, require_separator=True)
        if current is not None:
            return current, self.build_select_product_material_counter_text(current, result)

        for area in OCR_SELECT_PRODUCT_MATERIAL_COUNTER_AREAS:
            button = Button(
                area=area,
                color=(),
                button=area,
                file={'cn': '', 'en': '', 'jp': '', 'tw': ''},
                name=f'OCR_SELECT_PRODUCT_MATERIAL_COUNTER_{area[0]}_{area[2]}',
            )
            counter_text = self.ocr_select_product_material_text(button, show_log=False)
            current = self.parse_select_product_material_current(counter_text, require_separator=True)
            full_numbers = re.findall(r'\d+', result)
            if (
                    current is not None
                    and (expected_quantity is None or current <= expected_quantity)
                    and (not full_numbers or full_numbers[0].startswith(str(current)))
            ):
                return current, self.build_select_product_material_counter_text(current, result, counter_text)

        slash_without_current = False
        prefix_candidates = []
        slash_prefix_text = ''
        for area in OCR_SELECT_PRODUCT_MATERIAL_CURRENT_AREAS:
            button = Button(
                area=area,
                color=(),
                button=area,
                file={'cn': '', 'en': '', 'jp': '', 'tw': ''},
                name=f'OCR_SELECT_PRODUCT_MATERIAL_CURRENT_{area[0]}_{area[2]}',
            )
            current_text = self.ocr_select_product_material_text(button, show_log=False)
            current = self.parse_select_product_material_current(current_text, require_separator=True)
            if current is not None:
                return current, self.build_select_product_material_counter_text(
                    current,
                    result,
                    current_text,
                    allow_suffix_rebuild=expected_quantity is not None and current == expected_quantity,
                )
            if '/' in current_text:
                slash_without_current = True
                slash_prefix_text = current_text
            for number in re.findall(r'\d+', current_text):
                candidate = int(number)
                if expected_quantity is None or candidate <= expected_quantity:
                    prefix_candidates.append((candidate, current_text))

        full_numbers = re.findall(r'\d+', result)
        if full_numbers and prefix_candidates:
            full_text = full_numbers[0]
            for candidate, current_text in prefix_candidates:
                candidate_text = str(candidate)
                if candidate_text != full_text and full_text.startswith(candidate_text):
                    return candidate, self.build_select_product_material_counter_text(
                        candidate,
                        result,
                        current_text,
                        allow_suffix_rebuild=expected_quantity is not None and candidate == expected_quantity,
                    )

        if slash_without_current:
            return 0, self.build_select_product_material_counter_text(
                0,
                result,
                slash_prefix_text,
                allow_suffix_rebuild=expected_quantity is not None and expected_quantity == 0,
            )

        current = self.parse_select_product_material_current(result)
        if current is not None:
            logger.warning(f"[岛屿] 岗位派遣页材料数量未识别到分隔符，使用兜底结果: {result}")
            return current, str(current)

        logger.warning(f"[岛屿] 岗位派遣页材料数量识别失败: {result}")
        return 0, '0'

    def ocr_select_product_material(self, expected_quantity=None):
        """读取岗位产品选择页中当前种子、鱼苗或饲料数量。

        Args:
            expected_quantity (int, optional): 期望数量，用于辅助校验。默认为 None。

        Returns:
            int: 当前材料库存数量。
        """
        current, _ = self.ocr_select_product_material_detail(expected_quantity=expected_quantity)
        return current

    def ocr_select_product_material_counter(self):
        """读取岗位产品选择页材料数量，返回当前库存和页面显示需求。

        Returns:
            tuple[int | None, int]: (当前库存数量, 总需求数量)。
        """
        current, result = self.ocr_select_product_material_detail()

        required = 0
        if '/' in result:
            required_text = result.split('/', 1)[1]
            required_numbers = [int(number) for number in re.findall(r'\d+', required_text)]
            required = sum(required_numbers)

        if current is None:
            logger.warning(f"[岛屿] 岗位派遣页材料数量识别失败: {result}")
        return current, required

    def back_to_select_product_after_shop(self, back_button=ISLAND_BACK):
        """从补货商店返回岗位产品选择页。

        Args:
            back_button (Button, optional): 返回按钮。默认为 ISLAND_BACK。

        Returns:
            bool: 返回成功为 True，超时为 False。
        """
        self.interval_clear([back_button])
        for _ in self.loop(timeout=15, skip_first=False):
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                return True
            if self.appear(ISLAND_POST_CHECK, offset=1) or self.appear(ISLAND_POST_VACANT_CHECK, offset=1):
                return True
            if self.appear(ISLAND_SHOP_GET, offset=(1, 1)):
                self.device.click(ISLAND_SHOP_CONFIRM)
                continue
            if self.appear_then_click(back_button, offset=(20, 20), interval=1):
                continue

        logger.warning("[岛屿] 从补货商店返回岗位产品选择页超时")
        return False

    def ensure_select_product_material(self, item_button, required_quantity, shop_check,
                                       item_name=None, tab_check=None, tab_button=None):
        """在岗位产品选择页读取当前材料数量，不足时进入对应商店补买。

        Args:
            item_button (Button): 商店中商品图标按钮。
            required_quantity (int): 所需材料数量。
            shop_check (Button): 商店界面判定按钮。
            item_name (str, optional): 商品名称。默认为 None。
            tab_check (Button, optional): 商店页签判定按钮。默认为 None。
            tab_button (Button, optional): 商店页签点击按钮。默认为 None。

        Returns:
            bool: True 表示发生过补货，调用方需要重新选择产品；False 表示库存已足够。
        """
        required_quantity = max(1, int(required_quantity))
        current_quantity, counter_text = self.ocr_select_product_material_detail(expected_quantity=required_quantity)
        display_name = item_name or getattr(item_button, 'name', '材料')
        logger.info(f"[岛屿] {self._item_cn(display_name)}页面材料: {counter_text}，当前库存: {current_quantity}，目标库存: {required_quantity}")

        if current_quantity >= required_quantity:
            return False

        buy_quantity = required_quantity - current_quantity
        logger.info(f"[岛屿] {self._item_cn(display_name)}数量不足，进入商店补买 {buy_quantity} 个")
        if not self.goto_shop_from_select_product(
            shop_check=shop_check,
            tab_check=tab_check,
            tab_button=tab_button,
        ):
            return True
        if not self.buy_shop_item(
            item_button=item_button,
            quantity=buy_quantity,
            shop_check=shop_check,
            item_name=display_name,
            tab_check=tab_check,
            tab_button=tab_button,
        ):
            return True
        self.back_to_select_product_after_shop()
        return True

    def goto_mill(self, max_attempts=3):
        """前往磨坊并打开磨坊界面。

        Args:
            max_attempts (int): 最大尝试次数。默认为 3。

        Returns:
            bool: 成功到达并打开磨坊界面返回 True，失败返回 False。
        """
        for attempt in range(max_attempts):
            logger.info(f"[岛屿] 尝试前往磨坊，第{attempt + 1}次尝试")
            if not self.island_map_goto('farm'):
                continue
            # 磨坊路线不在可配置的走位规则里：它和地图跳转强绑定，长度也短，
            # 保持写死更省事（顺序 U,L,D,L,D）。
            self.island_up(800)
            self.island_left(1300)
            self.island_down(1000)
            self.island_left(500)
            self.island_down(2500)
            for _ in self.loop(timeout=5, skip_first=False):
                if self.appear_then_click(ISLAND_MILL, interval=1):
                    continue
                if self.appear(ISLAND_MILL_CHECK):
                    logger.info("[岛屿] 成功到达磨坊")
                    return True
            logger.info("[岛屿] 超时，重新尝试")
        logger.info(f"[岛屿] 尝试{max_attempts}次后仍然失败")
        return False
