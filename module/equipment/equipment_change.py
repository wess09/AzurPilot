"""装备更换核心逻辑，处理舰船详细页面中的装备栏操作。
包括装备筛选、装备选择、滚动翻页、匹配确认等步骤，
继承 Equipment 基类提供完整的装备更换流程。"""

from module.base.button import ButtonGrid
from module.base.decorator import Config
from module.base.utils import *
from module.equipment.assets import *
from module.equipment.equipment import Equipment
from module.logger import logger
from module.ui.assets import BACK_ARROW
from module.ui.scroll import Scroll
from module.ui.switch import Switch

# 5 个装备槽位按钮网格
EQUIP_INFO_BAR = ButtonGrid(
    origin=(695, 127), delta=(86.25, 0), button_shape=(73, 73), grid_shape=(5, 1), name="EQUIP_INFO_BAR")
# 装备栏左下角区域，用于检测该网格是否存在装备
EQUIPMENT_GRID = ButtonGrid(
    origin=(696, 170), delta=(86.25, 0), button_shape=(32, 32), grid_shape=(5, 1), name='EQUIPMENT_GRID')
EQUIPMENT_SCROLL = Scroll(EQUIP_SCROLL, color=(247, 211, 66), name='EQUIP_SCROLL')
SIM_VALUE = 0.90

equipping_filter = Switch('Equipping_filter')
equipping_filter.add_state('on', check_button=EQUIPPING_ON)
equipping_filter.add_state('off', check_button=EQUIPPING_OFF)


class EquipmentChange(Equipment):
    """装备更换处理器。

    负责记录舰船当前所穿装备模板，以及在装备仓库中搜索匹配并穿戴装备。

    Attributes:
        equip_list (dict): 记录的装备槽位与对应装备图像模板映射。
    """
    equip_list = {}

    def equipping_set(self, enable=False):
        """设置“正在装备中”过滤开关状态。

        Args:
            enable (bool): 是否开启正在装备中过滤，默认 False。
        """
        if equipping_filter.set('on' if enable else 'off', main=self):
            self.wait_until_stable(SWIPE_AREA)

    def ship_equipment_record_image(self, index_list=range(0, 5)):
        """通过装备强化详情界面截取并记录舰船的装备图像模板。

        注意：装备强化界面中的装备图标大小与装备状态界面图标大小完全一致。

        Args:
            index_list (Iterable[int]): 需要记录的装备槽位索引列表（0 到 4）。
        """
        logger.info('[装备-更换] 记录装备')
        self.equip_side_navbar_ensure(bottom=1)

        # 确保 EQUIPMENT_GRID 处于正确位置
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(EQUIPMENT_OPEN, offset=(5, 5)):
                break

        self.equip_list = {}
        info_bar_disappeared = False
        for index, button in enumerate(EQUIPMENT_GRID.buttons):
            if index not in index_list:
                continue
            crop_image = self.image_crop(button, copy=False)
            edge_value = np.mean(np.abs(cv2.Sobel(crop_image, 3, 1, 1)))
            # 空槽位边缘响应约为 0.15~1，+1 强化约为 40，+10 约为 46
            if edge_value > 10:
                # 进入装备详情
                self.ui_click(appear_button=EQUIPMENT_OPEN,
                              click_button=EQUIP_INFO_BAR[(index, 0)],
                              check_button=UPGRADE_ENTER)
                # 进入强化详情
                self.ui_click(click_button=UPGRADE_ENTER,
                              check_button=UPGRADE_ENTER_CHECK, skip_first_screenshot=True)
                # 保存装备模板图像
                if not info_bar_disappeared:
                    self.handle_info_bar()
                    info_bar_disappeared = True
                self.equip_list[index] = self.image_crop(EQUIP_SAVE)
                # 退出强化详情
                self.ui_click(
                    click_button=UPGRADE_QUIT, check_button=EQUIPMENT_OPEN, appear_button=UPGRADE_ENTER_CHECK,
                    skip_first_screenshot=True)
            else:
                logger.info(f"[装备-更换] 装备栏 {index} 为空")

        logger.info(f"[装备-更换] 装备列表: {list(self.equip_list.keys())}")

    def equipment_take_on(self, index_list=range(0, 5), skip_first_screenshot=True):
        """为舰船穿上此前记录保存的装备。

        Args:
            index_list (Iterable[int]): 需要穿戴的装备槽位索引列表（0 到 4）。
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。
        """
        logger.info('[装备-更换] 装上装备')
        self.equip_side_navbar_ensure(bottom=2)

        for index in index_list:
            if index in self.equip_list:
                logger.info(f'[装备-更换] 装上装备 {index}')
                enter_button = globals()[
                    'EQUIP_TAKE_ON_{index}'.format(index=index)]

                self.ui_click(enter_button, check_button=EQUIPPING_ON,
                              skip_first_screenshot=skip_first_screenshot, offset=(5, 5))
                self.handle_info_bar()
                self._find_equip(index)

    @Config.when(DEVICE_CONTROL_METHOD='minitouch')
    def _equipment_swipe(self, distance=190):
        """通过 minitouch 向上滑动装备列表以浏览更多装备。

        Args:
            distance (int): 滑动距离，默认 190。
        """
        # 两行装备间的垂直距离约为 146px
        p1, p2 = random_rectangle_vector(
            (0, -distance), box=(620, 67, 1154, 692), random_range=(-20, -5, 20, 5))
        self.device.drag(p1, p2, segments=2, shake=(25, 0),
                         point_random=(0, 0, 0, 0), shake_random=(-5, 0, 5, 0))
        self.device.sleep(0.3)
        self.device.screenshot()

    @Config.when(DEVICE_CONTROL_METHOD=None)
    def _equipment_swipe(self, distance=300):
        """向上滑动装备列表以浏览更多装备。

        Args:
            distance (int): 滑动距离，默认 300。
        """
        # 两行装备间的垂直距离约为 146px
        p1, p2 = random_rectangle_vector(
            (0, -distance), box=(620, 67, 1154, 692), random_range=(-20, -5, 20, 5))
        self.device.drag(p1, p2, segments=2, shake=(25, 0),
                         point_random=(0, 0, 0, 0), shake_random=(-5, 0, 5, 0))
        self.device.sleep(0.3)
        self.device.screenshot()

    def _equip_equipment(self, point, offset=(100, 100)):
        """在装备选择列表中点击指定坐标的装备并完成确认穿戴。

        Args:
            point (tuple[int, int]): 匹配到的装备左上角坐标。
            offset (tuple[int, int]): 装备按钮的宽高偏移，默认 (100, 100)。

        Pages:
            in: 装备选择列表（EQUIPMENT STATUS）
            out: 舰船装备栏（SHIP_INFO_EQUIPMENT_CHECK）
        """
        logger.info('[装备-更换] 装上装备')
        button = Button(area=(), color=(), button=(point[0], point[1], point[0] + offset[0], point[1] + offset[1]),
                        name='EQUIPMENT')
        self.ui_click(appear_button=EQUIPPING_OFF, click_button=button, check_button=EQUIP_CONFIRM)
        logger.info('[装备-更换] 装备确认')
        self.ui_click(click_button=EQUIP_CONFIRM, check_button=SHIP_INFO_EQUIPMENT_CHECK)

    def _find_equip(self, index):
        """在装备列表中滑动寻找与记录模板匹配的装备并穿戴。

        Args:
            index (int): 装备槽位索引（0 到 4）。

        Pages:
            in: 装备选择列表（EQUIPMENT STATUS）
        """
        self.equipping_set(False)

        res = cv2.matchTemplate(self.device.screenshot(), np.array(
            self.equip_list[index]), cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)

        if sim > lower_template_match_similarity(SIM_VALUE):
            self._equip_equipment(point)
            return

        if not EQUIPMENT_SCROLL.appear(main=self):
            logger.warning('[装备-更换] 未找到记录的装备')
            self.ui_back(check_button=globals()[f'EQUIP_TAKE_ON_{index}'], appear_button=EQUIPPING_OFF)
            return

        for _ in range(0, 15):
            self._equipment_swipe()

            if self.appear(EQUIP_CONFIRM, offset=(20, 20), interval=2):
                self.device.click(BACK_ARROW)
                continue
            res = cv2.matchTemplate(self.device.screenshot(), np.array(
                self.equip_list[index]), cv2.TM_CCOEFF_NORMED)
            _, sim, _, point = cv2.minMaxLoc(res)

            if sim > lower_template_match_similarity(SIM_VALUE):
                self._equip_equipment(point)
                break
            if self.appear(EQUIPMENT_SCROLL_BOTTOM):
                logger.warning('[装备-更换] 未找到记录的装备')
                self.ui_back(check_button=globals()[f'EQUIP_TAKE_ON_{index}'], appear_button=EQUIPPING_OFF)
                break

        return
