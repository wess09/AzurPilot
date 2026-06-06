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
from module.logger import logger

# 岗位产品选择滑动惯性消除安全区域
SELECT_PRODUCT_INERTIA_STOP = Button(
    area=(), color=(),
    button=(468, 400, 476, 500),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

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
    def warehouse_absolute_area(self, button, relative_area):
        """将相对坐标转换为绝对坐标"""
        x1 = button.area[0] + relative_area[0]
        y1 = button.area[1] + relative_area[1]
        x2 = button.area[0] + relative_area[2]
        y2 = button.area[1] + relative_area[3]
        return (x1, y1, x2, y2)

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
        # 等待并重置筛选器，直到两个全选按钮都被选中
        while 1:
            self.device.screenshot()
            # 检查all_kind全选按钮是否选中
            all_kind_button = self.warehouse_filter_kind[kind_map['all_kind']]
            warehouse_area = self.warehouse_absolute_area(all_kind_button, self.warehouse_area_relative)
            warehouse_color = get_color(self.device.image, warehouse_area)
            all_kind_selected = color_similar(warehouse_color, (60, 61, 63), 80)

            # 检查all_from全选按钮是否选中
            all_from_button = self.warehouse_filter_from[from_map['all_from']]
            warehouse_area = self.warehouse_absolute_area(all_from_button, self.warehouse_area_relative)
            warehouse_color = get_color(self.device.image, warehouse_area)
            all_from_selected = color_similar(warehouse_color, (60, 61, 63), 80)

            if all_kind_selected and all_from_selected:
                break
            else:
                self.appear_then_click(FILTER_RESET)
                self.device.sleep(0.3)

        # 处理第一个按钮
        # 确定按钮属于哪个网格并获取按钮对象
        if button1 in kind_map:
            button_obj = self.warehouse_filter_kind[kind_map[button1]]
        elif button1 in from_map:
            button_obj = self.warehouse_filter_from[from_map[button1]]
        else:
            raise ValueError(f"未知的按钮名称: {button1}")

        while 1:
            self.device.screenshot()

            # 检查按钮是否已选中
            warehouse_area = self.warehouse_absolute_area(button_obj, self.warehouse_area_relative)
            warehouse_color = get_color(self.device.image, warehouse_area)
            button_selected = color_similar(warehouse_color, (60, 61, 63), 80)

            if button_selected:
                break
            else:
                # 点击按钮
                self.device.click(button_obj)
                self.device.sleep(0.3)

        # 处理第二个按钮（如果有）
        if button2:
            # 确定按钮属于哪个网格并获取按钮对象
            if button2 in kind_map:
                button2_obj = self.warehouse_filter_kind[kind_map[button2]]
            elif button2 in from_map:
                button2_obj = self.warehouse_filter_from[from_map[button2]]
            else:
                raise ValueError(f"未知的按钮名称: {button2}")

            while 1:
                self.device.screenshot()

                # 检查按钮是否已选中
                warehouse_area = self.warehouse_absolute_area(button2_obj, self.warehouse_area_relative)
                warehouse_color = get_color(self.device.image, warehouse_area)
                button2_selected = color_similar(warehouse_color, (60, 61, 63), 80)

                if button2_selected:
                    break
                else:
                    # 点击按钮
                    self.device.click(button2_obj)
                    self.device.sleep(0.3)
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
            while True:
                self.device.screenshot()
                if self.appear(ISLAND_MANAGEMENT_CHECK, offset=1):
                    break
                if self.appear(ISLAND_CHECK, offset=1):
                    self.device.click(ISLAND_GOTO_MANAGEMENT)
                    continue
                if self.appear(ISLAND_SEASON_CHECK, offset=1):
                    self.device.click(ISLAND_SEASON_GOTO_ISLAND)
                    continue
                self.device.sleep(0.3)
            if self.appear(ISLAND_SEASON_CHECK, offset=1):
                self.ui_goto(page_island_management, get_ship=False)

    def goto_island_map(self):
        self.ui_goto(page_island,get_ship=False)
        while True:
            self.device.screenshot()
            if self.appear_then_click(ISLAND_GOTO_MAP):
                continue
            if self.appear(ISLAND_MAP_CHECK):
                break

    def island_map_goto(self,destination):
        button_map = {
            'mine_forest': {
                'click': ISLAND_MAP_MINE_FOREST,
                'check': ISLAND_MAP_MINE_FOREST_CHECK
            },
            'farm': {
                'click': ISLAND_MAP_FARM,
                'check': ISLAND_MAP_FARM_CHECK
            },
            'nursery': {
                'click': ISLAND_MAP_NURSERY,
                'check': ISLAND_MAP_NURSERY_CHECK
            }
        }
        destination_button = button_map.get(destination, {}).get('click')
        check_button = button_map.get(destination, {}).get('check')
        self.goto_island_map()
        while True:
            self.device.screenshot()
            if self.appear(check_button):
                self.device.click(ISLAND_MAP_CONFIRM)
                break
            if self.appear_then_click(destination_button, interval=1):
                pass
        self.goto_management()
        self.ui_goto(page_island)
    def post_manage_mode(self, post_manage_mode):
        post_manage_button = POST_MANAGE_BUSINESS if post_manage_mode == POST_MANAGE_PRODUCTION else POST_MANAGE_PRODUCTION
        while True:
            self.device.screenshot()
            if self.appear_then_click(post_manage_button):
                continue
            elif self.appear(post_manage_mode):
                break
            elif self.appear(ISLAND_GATHER_COLLECT_CHECK, offset=30):
                # 当前在采集页签，appear_then_click 无法匹配到生产和经营页签
                # 直接点击目标页签按钮（Button.button 返回点击坐标 tuple）
                self.device.click(post_manage_button)
                self.device.sleep(0.3)
                continue

    def post_manage_mode_collection(self):
        """
        切换到采集页签（管理页面左侧第三个页签）
        如果已经在采集页签则跳过，否则从当前页签切换过去
        """
        while True:
            self.device.screenshot()
            if self.appear(ISLAND_GATHER_COLLECT_CHECK):
                break
            if self.appear_then_click(ISLAND_GATHER_COLLECT):
                self.device.sleep(0.3)
                continue
            self.device.sleep(0.3)

    def select_product(self, product_selection, product_selection_check):
        max_attempts = 6  # 最大尝试次数
        attempt = 0

        while attempt < max_attempts:
            self.device.screenshot()

            # 使用形状+颜色双重验证来识别 product_selection_check
            if self.match_template_color(product_selection_check, offset=20, similarity=0.85, threshold=10):
                return True

            # 使用形状+颜色双重验证来识别 product_selection 并点击
            if self.match_template_color(product_selection, offset=300, similarity=0.85, threshold=10):
                self.device.click(product_selection)
                continue

            # 如果都不匹配，则滑动寻找
            self.device.swipe_vector(vector=(0, -200), box=(333, 142, 431, 602), name="SelectionUpSwipe")
            # 点击安全区域消除滑动惯性，防止截图时列表仍在滚动
            self.device.sleep(0.3)
            self.device.click(SELECT_PRODUCT_INERTIA_STOP)
            self.device.sleep(0.2)
            attempt += 1

        return False
    def post_close(self):
        while 1:
            self.device.screenshot()
            if self.ui_page_appear(page_island_postmanage) and not self.appear(ISLAND_POST_CHECK, offset=30) and not self.appear(ISLAND_POST_VACANT_CHECK, offset=30):
                break
            if self.appear(ISLAND_GET, offset=30):
                self.device.click(ISLAND_POST_SAFE_AREA)
                continue
            if self.appear(ISLAND_POST_CHECK, offset=30) or self.appear(ISLAND_POST_VACANT_CHECK, offset=30):
                self.device.click(POST_CLOSE)
                continue
    def post_get_and_close(self):
        while 1:
            self.device.screenshot()
            if self.ui_page_appear(page_island_postmanage) and not self.appear(ISLAND_POST_CHECK, offset=30) and not self.appear(ISLAND_POST_VACANT_CHECK, offset=30):
                break
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
            if (self.appear(ISLAND_POST_CHECK, offset=30) or self.appear(ISLAND_POST_VACANT_CHECK, offset=30)) and not self.appear(POST_GET, offset=(50, 0)):
                self.device.click(POST_CLOSE)
                continue
    def post_get_and_add(self,product_selection,product_selection_check):
        while 1:
            self.device.screenshot()
            if self.appear(ERROR1,offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                continue
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
                    self.device.sleep(0.5)
                    self.appear_then_click(SELECT_UI_CONFIRM)
                    self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK,offset=1):
                if self.select_product(product_selection,product_selection_check):
                    self.device.sleep(0.3)
                    self.device.click(POST_MAX)
                    self.device.sleep(0.3)
                    self.device.click(POST_ADD_ORDER)
                    self.device.sleep(0.5)
                continue
            if (
                    (self.appear(ISLAND_POST_CHECK, offset=30) or self.appear(ISLAND_POST_VACANT_CHECK, offset=30))
                    and not self.appear(POST_GET, offset=(50, 0))
                    and not self.appear(POST_ADD)
                    and not self.appear(ISLAND_POST_SELECT, offset=30)
            ):
                self.device.click(POST_CLOSE)
                break
            if (
                    self.ui_page_appear(page_island_postmanage)
                    and not self.appear(ISLAND_POST_CHECK, offset=30)
                    and not self.appear(ISLAND_POST_VACANT_CHECK, offset=30)
            ):
                break

    def post_open(self,post):
        template = TEMPLATE_POST_LOCK
        while True:
            image = self.device.screenshot()
            if self.appear(post,offset=300):
                cell_image = crop(image, post.button)
                if template.match(cell_image, similarity=0.85):
                    return False
            if self.appear(ISLAND_POST_CHECK) or self.appear(ISLAND_POST_VACANT_CHECK):
                return True
            if self.appear_then_click(post,offset=300):
                self.device.sleep(0.5)
                continue
            self.device.sleep(0.5)
    def post_manage_up_swipe(self,distance):
        self.device.swipe_vector(vector=(0, -distance), box=(688, 69, 725, 656), name="PostUpSwipe")
        self.device.click(POST_MANAGE_SWIPE_STOP)
    def post_manage_down_swipe(self,distance):
        self.device.swipe_vector(vector=(0, distance), box=(688, 69, 725, 656), name="PostDownSwipe")
        self.device.click(POST_MANAGE_SWIPE_STOP)
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
        while True:
            if add_ten_clicks == 0:
                break
            self.device.click(ADD_TEN_A)
            add_ten_clicks -= 1
            if add_ten_clicks == 0:
                break
            self.device.click(ADD_TEN_B)
            add_ten_clicks -= 1
            if add_ten_clicks == 0:
                break
            self.device.click(ADD_TEN_C)
            add_ten_clicks -= 1
        while True:
            if add_one_clicks == 0:
                break
            self.device.click(ADD_ONE_A)
            add_one_clicks -= 1
            if add_one_clicks == 0:
                break
            self.device.click(ADD_ONE_B)
            add_one_clicks -= 1
            if add_one_clicks == 0:
                break
            self.device.click(ADD_ONE_C)
            add_one_clicks -= 1

    def goto_mill(self, max_attempts=3):
        for attempt in range(max_attempts):
            logger.info(f"尝试前往磨坊，第{attempt + 1}次尝试")
            self.island_map_goto('farm')
            self.island_up(800)
            self.island_left(1300)
            self.island_down(1000)
            self.island_left(500)
            self.island_down(2500)
            start_time = time.time()
            while True:
                self.device.screenshot()
                if self.appear_then_click(ISLAND_MILL):
                    continue
                if self.appear(ISLAND_MILL_CHECK):
                    logger.info("成功到达磨坊")
                    return True
                if time.time() - start_time > 5:
                    logger.info("超时，重新尝试")
                    break
        logger.info(f"尝试{max_attempts}次后仍然失败")
        return False



