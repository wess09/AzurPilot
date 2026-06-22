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
from module.exception import GameStuckError
from module.logger import logger
import re

ISLAND_MAP_CONFIRM_WAIT = 3

# 岗位产品选择滑动惯性消除安全区域
SELECT_PRODUCT_INERTIA_STOP = Button(
    area=(), color=(),
    button=(468, 400, 476, 500),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
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
        self.post_open_retry_swipe_limit = 1
        self.post_open_full_retry_limit = 1

    def post_add_one(self, count, interval=0):
        """按 A/B/C 轮转点击生产数量 +1 按钮。"""
        buttons = (POST_ADD_ONE_A, POST_ADD_ONE_B, POST_ADD_ONE_C)
        for index in range(max(0, count)):
            self.device.click(buttons[index % len(buttons)])
            if interval:
                self.device.sleep(interval)

    def warehouse_absolute_area(self, button, relative_area):
        """将相对坐标转换为绝对坐标"""
        x1 = button.area[0] + relative_area[0]
        y1 = button.area[1] + relative_area[1]
        x2 = button.area[0] + relative_area[2]
        y2 = button.area[1] + relative_area[3]
        return (x1, y1, x2, y2)

    def warehouse_filter_button_selected(self, button):
        warehouse_area = self.warehouse_absolute_area(button, self.warehouse_area_relative)
        warehouse_color = get_color(self.device.image, warehouse_area)
        return color_similar(warehouse_color, (60, 61, 63), 80)

    def warehouse_filter(self, button1, button2=None):
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
        page = self.ui_get_current_page()
        valid_pages = ['page_island_management', 'page_island_postmanage', 'page_island', 'page_island_warehouse', 'page_island_visit', 'page_island_season']
        if page.name in valid_pages:
            self.ui_goto(page_island_postmanage,get_ship=False)
        else:
            self.goto_management()
            self.ui_goto(page_island_postmanage,get_ship=False)
    def goto_management(self):
        page = self.ui_get_current_page()
        valid_pages = ['page_island_management', 'page_island_postmanage', 'page_island', 'page_island_warehouse',
                       'page_island_visit', 'page_island_season']
        if page.name in valid_pages:
            self.ui_goto(page_island_management, get_ship=False)
        else:
            self.ui_goto(page_island,get_ship=False)
            for _ in self.loop(timeout=20, skip_first=False):
                if self.appear(ISLAND_MANAGEMENT_CHECK, offset=1):
                    break
                if self.appear(ISLAND_CHECK, offset=1):
                    self.device.click(ISLAND_GOTO_MANAGEMENT)
                    continue
                if self.appear(ISLAND_SEASON_CHECK, offset=1):
                    self.device.click(ISLAND_SEASON_GOTO_ISLAND)
                    continue
                if self.ui_additional(get_ship=False):
                    continue
            else:
                raise GameStuckError("进入岛屿管理页面超时")
            if self.appear(ISLAND_SEASON_CHECK, offset=1):
                self.ui_goto(page_island_management, get_ship=False)

    def is_in_friend_island(self):
        leave = self.appear(AIR_DROP_RUN_AWAY, offset=(20, 20))
        access_map = self.appear(ISLAND_ACCESS_MAP, offset=(20, 20))
        return leave and access_map

    def _wait_island_map_entry(self, timeout=3):
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
        logger.hr("Island goto map", level=2)
        expect_friend = bool(getattr(self, "_island_expect_friend", False))
        status = self._wait_island_map_entry(timeout=10 if expect_friend else 3)
        in_map = status["in_map"]
        in_friend = status["in_friend"]
        home_map = status["home_map"]
        access_map = status["access_map"]
        if not in_map and not in_friend and not home_map and not access_map:
            if expect_friend:
                logger.warning("预期已进入好友岛，但暂未识别到地图入口，继续等待好友岛入口")
            else:
                logger.info("当前不在岛屿地图或好友岛，先导航到本岛")
                self.ui_goto(page_island,get_ship=False)

        for _ in self.loop(timeout=30 if expect_friend else 20, skip_first=False):
            if self.appear(ISLAND_MAP_CHECK):
                logger.info("已进入岛屿地图")
                return True
            if self.appear_then_click(ISLAND_GOTO_MAP):
                logger.info("点击本岛地图入口")
                continue
            if self.appear_then_click(ISLAND_ACCESS_MAP, offset=(20, 20)):
                logger.info("点击好友岛右上角地图入口")
                continue
        else:
            logger.warning("进入岛屿地图超时")
            return False

    def island_map_goto(self,destination):
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
                    logger.info(f"点击岛屿地图目的地: {destination}")
                    destination_clicked = True
                continue

            if self.appear(check_button, offset=(20, 20)):
                logger.info(
                    f"岛屿地图目的地详情已识别: {destination} "
                    f"({check_button.name})"
                )
                self.device.click(ISLAND_MAP_CONFIRM)
                confirmed = True
                break
            if self.appear_then_click(destination_button, interval=1):
                continue

        if not confirmed:
            logger.warning(f"岛屿地图目的地选择超时: {destination}")
            return False

        confirm_wait = Timer(ISLAND_MAP_CONFIRM_WAIT).start()
        for _ in self.loop(timeout=20, skip_first=False):
            if self.ui_additional(get_ship=False):
                continue

            if self.appear_then_click(ISLAND_MAP_CONFIRM, interval=2):
                confirm_wait.reset()
                continue

            if self.ui_page_appear(page_island_map):
                continue

            if confirm_wait.reached() and (
                    self.appear(ISLAND_CHECK, offset=(20, 20))
                    or (in_friend and self.is_in_friend_island())
            ):
                return True

        logger.warning(f"岛屿地图进入目的地超时: {destination}")
        return False
    def post_manage_mode(self, post_manage_mode):
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
        """
        切换到采集页签（管理页面左侧第三个页签）
        如果已经在采集页签则跳过，否则从当前页签切换过去
        """
        for _ in self.loop(timeout=15, skip_first=False):
            if self.appear(ISLAND_GATHER_COLLECT_CHECK):
                return True
            if self.appear_then_click(ISLAND_GATHER_COLLECT, interval=1):
                continue
        raise GameStuckError("切换采集页签超时")

    def select_product(self, product_selection, product_selection_check):
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
        """select_product 失败时的统一处理：记录警告、关闭岗位面板、返回 False"""
        logger.warning(f"select_product 失败：未能找到产品 {product} 的选择项")
        self.device.click(POST_CLOSE)
        return False

    def post_close(self):
        for _ in self.loop(timeout=15, skip_first=False):
            if self.ui_page_appear(page_island_postmanage) and not self.appear(ISLAND_POST_CHECK) and not self.appear(ISLAND_POST_VACANT_CHECK):
                return True
            if self.appear(ISLAND_GET, offset=30):
                self.device.click(ISLAND_POST_SAFE_AREA)
                continue
            if self.appear(ISLAND_POST_CHECK) or self.appear(ISLAND_POST_VACANT_CHECK):
                self.device.click(POST_CLOSE)
                continue
        logger.warning("关闭岗位详情超时")
        return False
    def post_get_and_close(self):
        for _ in self.loop(timeout=20, skip_first=False):
            if self.ui_page_appear(page_island_postmanage) and not self.appear(ISLAND_POST_CHECK) and not self.appear(ISLAND_POST_VACANT_CHECK):
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
            if (self.appear(ISLAND_POST_CHECK) or self.appear(ISLAND_POST_VACANT_CHECK)) and not self.appear(POST_GET, offset=(50, 0)):
                self.device.click(POST_CLOSE)
                continue
        logger.warning("收取并关闭岗位详情超时")
        return False

    def post_get_stay(self):
        """收取当前岗位产物并停留在岗位详情界面，供后续直接复检状态。"""
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
            if (self.appear(ISLAND_POST_CHECK) or self.appear(ISLAND_POST_VACANT_CHECK) or self.ui_page_appear(page_island_postmanage)):
                return True
        logger.warning("收取当前岗位产物超时")
        return False

    def post_get_and_add(self,product_selection,product_selection_check):
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
                    logger.warning("岗位追加派遣无可用角色")
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
                    and not self.appear(ISLAND_POST_CHECK, offset=30)
                    and not self.appear(ISLAND_POST_VACANT_CHECK, offset=30)
            ):
                return True
        logger.warning("收取并追加岗位派遣超时")
        return False

    def back_to_postmanage_from_dispatch(self):
        """从角色选择或产品选择流程退回岗位管理页。"""
        self.interval_clear([SELECT_UI_BACK, POST_CLOSE])
        for _ in self.loop(timeout=15, skip_first=False):
            if (
                    self.ui_page_appear(page_island_postmanage)
                    and not self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1)
                    and not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1)
                    and not self.appear(ISLAND_POST_CHECK, offset=1)
                    and not self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
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
            if self.appear(ISLAND_POST_CHECK, offset=1) or self.appear(ISLAND_POST_VACANT_CHECK, offset=1):
                self.device.click(POST_CLOSE)
                continue

        logger.warning("从派遣流程返回岗位管理页超时")
        return False

    def confirm_post_add_order(self, context="岗位派遣"):
        """材料确认足够后，点击最大数量并确认派遣。"""
        if self.appear(POST_MAX):
            self.device.click(POST_MAX)
            self.device.sleep(0.3)
            self.device.screenshot()

        if self.appear(POST_ADD_ORDER):
            self.device.click(POST_ADD_ORDER)
            self.device.sleep(0.5)
            return True

        current, required = self.ocr_select_product_material_counter()
        if required and current < required:
            logger.warning(f"{context}材料不足，确认按钮不可用: {current}/{required}")
        else:
            logger.warning(f"{context}材料已确认足够，但确认按钮不可用，可能角色体力不足")
        return False

    def confirm_selected_character(self, context="岗位派遣"):
        """确认角色选择，并等待角色选择页切换到下一步。"""
        if not self.click_selected_character_confirm(context=context):
            return False

        for _ in self.loop(timeout=8, skip_first=False):
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                return True
            if (
                    (self.appear(ISLAND_POST_CHECK, offset=1) or self.appear(ISLAND_POST_VACANT_CHECK, offset=1))
                    and not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1)
            ):
                return True
            if (
                    self.ui_page_appear(page_island_postmanage)
                    and not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1)
            ):
                return True
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.appear_then_click(SELECT_UI_CONFIRM, interval=1):
                    continue

        logger.warning(f"{context}确认后未进入下一步")
        return False

    def confirm_selected_character_closed(self, context="角色选择", timeout=8):
        """确认角色选择，并等待角色选择页关闭。"""
        if not self.click_selected_character_confirm(context=context):
            return False

        for _ in self.loop(timeout=timeout, skip_first=False):
            if not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                return True
            if self.appear_then_click(SELECT_UI_CONFIRM, interval=1):
                continue

        logger.warning(f"{context}确认后仍停留在角色选择页")
        return False

    def click_selected_character_confirm(self, context="角色选择", timeout=5):
        """等待角色确认按钮出现并点击。"""
        self.interval_clear([SELECT_UI_CONFIRM])
        for _ in self.loop(timeout=timeout, skip_first=False):
            if not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                return True
            if self.appear_then_click(SELECT_UI_CONFIRM, interval=1):
                return True

        if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
            logger.warning(f"{context}确认按钮未出现")
            return False
        return True

    def post_open(self,post):
        template = TEMPLATE_POST_LOCK
        retry_swipe_timer = Timer(3, count=3).start()
        retry_swipe_used = 0
        full_retry_used = 0
        for image in self.loop(timeout=45, skip_first=False):
            post_appear = self.appear(post,offset=300)
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
                logger.info(f"未识别到岗位按钮 {post}，第{retry_swipe_used + 1}次滑动定位岗位列表")
                self.post_manage_swipe(getattr(self, 'post_manage_swipe_count', 1))
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
                        f"岗位按钮 {post} 连续{retry_swipe_used + 1}次滑动定位失败，重新进入岗位管理页重试"
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
    def post_manage_up_swipe(self,distance):
        self.device.swipe_vector(vector=(0, -distance), box=(688, 69, 725, 656), name="PostUpSwipe")
        self.device.click(POST_MANAGE_SWIPE_STOP, control_check=False)
    def post_manage_down_swipe(self,distance):
        self.device.swipe_vector(vector=(0, distance), box=(688, 69, 725, 656), name="PostDownSwipe")
        self.device.click(POST_MANAGE_SWIPE_STOP, control_check=False)
    def post_manage_swipe(self,count):
        if count >= 2:
            for _ in range(count):
                self.post_manage_up_swipe(450)
        elif count == 1:
            if self.appear(ISLAND_FARM_POST1, offset=100):
                for _ in range(count):
                    self.post_manage_up_swipe(450)
            else:
                self.post_manage_down_swipe(450)
                self.device.sleep(0.3)
                self.post_manage_down_swipe(450)
                self.device.sleep(0.3)
                for _ in range(count):
                    self.post_manage_up_swipe(450)
        elif count == 0:
            if not self.appear(ISLAND_FARM_POST1, offset=100):
                self.post_manage_down_swipe(450)
                self.device.sleep(0.3)
                self.post_manage_down_swipe(450)
                self.device.sleep(0.3)

    def island_up(self,hold_time):
        p1 = (218, 507)
        p2 = (218, 441)
        self.device.island_swipe_hold(p1, p2,hold_time)
    def island_down(self,hold_time):
        p1 = (218, 507)
        p2 = (218, 572)
        self.device.island_swipe_hold(p1, p2,hold_time)
    def island_right(self,hold_time):
        p1 = (218, 507)
        p2 = (282, 507)
        self.device.island_swipe_hold(p1, p2,hold_time)
    def island_left(self,hold_time):
        p1 = (218, 507)
        p2 = (152, 507)
        self.device.island_swipe_hold(p1, p2,hold_time)
    def set_buy_number(self, target):
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
        """切换岛屿商店内的页签。"""
        click_count = 0
        self.interval_clear([tab_button])
        for _ in self.loop(timeout=8, skip_first=False):
            if self.appear(tab_check, offset=1, threshold=30):
                if click_count:
                    logger.info(f"商店页签检测成功: {tab_check}，点击 {click_count} 次")
                return True
            if self.appear(tab_button, threshold=30):
                click_count += 1
                logger.info(f"商店页签检测失败，点击页签: {tab_button} -> {tab_check}，第 {click_count} 次")
                self.device.click(tab_button)
                self.device.sleep(1)
                continue

        logger.warning(f"切换商店页签超时: tab={tab_button}, check={tab_check}, clicked={click_count}")
        return False

    def buy_shop_item(self, item_button, quantity, shop_check, item_name=None,
                      tab_check=None, tab_button=None):
        """购买岛屿商店商品，适用于种子、鱼苗等同构购买弹窗。"""
        quantity = max(1, int(quantity))
        if tab_check is not None and tab_button is not None:
            if not self.switch_shop_tab(tab_check, tab_button):
                return False

        if item_name:
            logger.info(f"购买 {item_name} x{quantity}")

        for _ in self.loop(timeout=10, skip_first=False):
            if self.appear(ISLAND_SHOPPING_CHECK):
                break
            if self.appear_then_click(item_button, interval=1.2):
                continue
        else:
            logger.warning(f"打开购买弹窗超时: {item_name or item_button}")
            return False

        if self.appear(ISLAND_SHOPPING_CHECK):
            self.set_buy_number(quantity)

        for _ in self.loop(timeout=15, skip_first=False):
            shop_visible = self.appear(shop_check, offset=1)
            shopping_shown = self.appear(ISLAND_SHOPPING_CHECK)
            if shop_visible and not shopping_shown:
                break
            if self.appear_then_click(ISLAND_SHOP_CONFIRM):
                self.device.sleep(0.5)
                self.device.click(ISLAND_SHOP_CONFIRM)
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SHOP_GET):
                self.device.click(ISLAND_SHOP_CONFIRM)
                continue
        else:
            logger.warning(f"确认购买超时: {item_name or item_button}")
            return False

        if self.appear(ISLAND_SHOP_GET):
            self.device.click(ISLAND_SHOP_CONFIRM)
        return True

    def goto_shop_from_select_product(self, shop_check, tab_check=None, tab_button=None):
        """从岗位产品选择页跳转到补充材料的商店页签。"""
        self.interval_clear([ISLAND_SELECT_GOTO_BUY_SEED, ISLAND_SELECT_SEED])
        tab_click_count = 0
        for _ in self.loop(timeout=20, skip_first=False):
            in_select_product = self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1)
            in_shop = self.appear(shop_check)
            in_tab = tab_check is not None and self.appear(tab_check, threshold=30)
            goto_buy = self.appear(ISLAND_SELECT_GOTO_BUY_SEED)

            if not in_select_product and tab_check is not None and in_tab:
                if tab_click_count:
                    logger.info(f"补货商店页签检测成功: {tab_check}，点击 {tab_click_count} 次")
                return True
            if not in_select_product and tab_button is not None and in_shop:
                tab_click_count += 1
                logger.info(
                    f"补货商店页签检测失败，点击页签: {tab_button} -> {tab_check}，第 {tab_click_count} 次"
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

        logger.warning("从岗位产品选择页进入补货商店超时")
        return False

    @staticmethod
    def normalize_select_product_material_text(result):
        return str(result).replace('I', '1').replace('D', '0').replace('S', '5').replace('B', '8')

    @staticmethod
    def parse_select_product_material_current(result, require_separator=False):
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
        """读取岗位产品选择页底部材料数量文本。"""
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
        """读取岗位产品选择页材料数量，返回当前库存和页面材料文本。"""
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
            logger.warning(f"岗位派遣页材料数量未识别到分隔符，使用兜底结果: {result}")
            return current, str(current)

        logger.warning(f"岗位派遣页材料数量识别失败: {result}")
        return 0, '0'

    def ocr_select_product_material(self, expected_quantity=None):
        """读取岗位产品选择页中当前种子、鱼苗或饲料数量。"""
        current, _ = self.ocr_select_product_material_detail(expected_quantity=expected_quantity)
        return current

    def ocr_select_product_material_counter(self):
        """读取岗位产品选择页材料数量，返回当前库存和页面显示需求。"""
        current, result = self.ocr_select_product_material_detail()

        required = 0
        if '/' in result:
            required_text = result.split('/', 1)[1]
            required_numbers = [int(number) for number in re.findall(r'\d+', required_text)]
            required = sum(required_numbers)

        if current is None:
            logger.warning(f"岗位派遣页材料数量识别失败: {result}")
        return current, required

    def back_to_select_product_after_shop(self, back_button=ISLAND_BACK):
        """从补货商店返回岗位产品选择页。"""
        self.interval_clear([back_button])
        for _ in self.loop(timeout=15, skip_first=False):
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                return True
            if self.appear(ISLAND_POST_CHECK, offset=1) or self.appear(ISLAND_POST_VACANT_CHECK, offset=1):
                return True
            if self.appear(ISLAND_SHOP_GET):
                self.device.click(ISLAND_SHOP_CONFIRM)
                continue
            if self.appear_then_click(back_button, offset=(20, 20), interval=1):
                continue

        logger.warning("从补货商店返回岗位产品选择页超时")
        return False

    def ensure_select_product_material(self, item_button, required_quantity, shop_check,
                                       item_name=None, tab_check=None, tab_button=None):
        """
        在岗位产品选择页读取当前材料数量，不足时进入对应商店补买。

        Returns:
            bool: True 表示发生过补货，调用方需要重新选择产品；False 表示库存已足够。
        """
        required_quantity = max(1, int(required_quantity))
        current_quantity, counter_text = self.ocr_select_product_material_detail(expected_quantity=required_quantity)
        display_name = item_name or getattr(item_button, 'name', '材料')
        logger.info(f"{display_name}页面材料: {counter_text}，当前库存: {current_quantity}，目标库存: {required_quantity}")

        if current_quantity >= required_quantity:
            return False

        buy_quantity = required_quantity - current_quantity
        logger.info(f"{display_name}数量不足，进入商店补买 {buy_quantity} 个")
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
        for attempt in range(max_attempts):
            logger.info(f"尝试前往磨坊，第{attempt + 1}次尝试")
            if not self.island_map_goto('farm'):
                continue
            self.island_up(800)
            self.island_left(1300)
            self.island_down(1000)
            self.island_left(500)
            self.island_down(2500)
            for _ in self.loop(timeout=5, skip_first=False):
                if self.appear_then_click(ISLAND_MILL, interval=1):
                    continue
                if self.appear(ISLAND_MILL_CHECK):
                    logger.info("成功到达磨坊")
                    return True
            logger.info("超时，重新尝试")
        logger.info(f"尝试{max_attempts}次后仍然失败")
        return False
