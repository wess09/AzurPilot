"""装备管理系统。

管理舰船装备的查看、更换和装备码操作。

功能：
- 装备界面的导航和检测
- 舰船视图的左右滑动切换
- 装备编辑按钮的状态管理
- 装备过滤器（正在装备中）的切换
- 装备码（Equipment Code）的导入导出

装备类型：
- 主炮（Main Gun）
- 副炮（Secondary Gun）
- 鱼雷（Torpedo）
- 防空炮（Anti-Air Gun）
- 设备（Auxiliary Device）

继承自 EquipmentCodeHandler，提供装备码处理能力。
"""

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.equipment.assets import *
from module.equipment.equipment_code import EquipmentCodeHandler
from module.logger import logger
from module.retire.assets import DOCK_CHECK, EQUIP_CONFIRM as RETIRE_EQUIP_CONFIRM
from module.ui.assets import BACK_ARROW
from module.ui.navbar import Navbar
from module.ui.switch import Switch

# 滑动参数
SWIPE_DISTANCE = 250
SWIPE_RANDOM_RANGE = (-40, -20, 40, 20)
# 装备中过滤器开关
equipping_filter = Switch('Equiping_filter')
equipping_filter.add_state('on', check_button=EQUIPPING_ON)
equipping_filter.add_state('off', check_button=EQUIPPING_OFF)
# patch to handle both blue (folded) and orange (expanded) button
EQUIPMENT_OPEN.match = EQUIPMENT_OPEN.match_luma


class Equipment(EquipmentCodeHandler):
    """装备管理器。

    管理舰船装备的查看和更换操作。

    Attributes:
        equipment_has_take_on (bool): 是否已执行装备更换操作。
    """
    equipment_has_take_on = False

    def equipping_set(self, enable=False):
        """设置“正在装备中”过滤开关状态。

        Args:
            enable (bool): 是否开启正在装备中过滤，默认 False。
        """
        if equipping_filter.set('on' if enable else 'off', main=self):
            self.wait_until_stable(SWIPE_AREA)

    def _ship_view_swipe(self, distance, check_button=EQUIPMENT_OPEN):
        """在舰船详情界面左右滑动切换舰船。

        Args:
            distance (int): 滑动水平位移（负数向左滑切换下一艘，正数向右滑切换上一艘）。
            check_button (Button): 滑动完成后用于确认界面的按钮，默认 EQUIPMENT_OPEN。

        Returns:
            bool: 成功切换到新舰船返回 True，到达末尾或遇到确认弹窗返回 False。
        """
        swipe_count = 0
        swipe_timer = Timer(5, count=10)
        self.handle_info_bar()
        SWIPE_CHECK.load_color(self.device.image)
        SWIPE_CHECK._match_init = True  # 匹配时禁用 ensure_template()，以便准确判断舰船是否发生切换
        while 1:
            if not swipe_timer.started() or swipe_timer.reached():
                swipe_timer.reset()
                self.device.swipe_vector(vector=(distance, 0), box=SWIPE_AREA.area, random_range=SWIPE_RANDOM_RANGE,
                                         padding=0, duration=(0.1, 0.12), name='SHIP_SWIPE')
                skip_first_screenshot = True
                while 1:
                    if skip_first_screenshot:
                        skip_first_screenshot = False
                    else:
                        self.device.screenshot()
                    if self.appear(check_button, offset=(30, 30)):
                        break
                    if self.appear(RETIRE_EQUIP_CONFIRM, offset=(30, 30)):
                        logger.info('[装备-穿戴] 退役装备确认弹窗')
                        return False
                    # 强化 NPC 舰船时的弹窗
                    if self.handle_popup_confirm('SHIP_VIEW_SWIPE'):
                        continue
                swipe_count += 1

            self.device.screenshot()

            if self.appear(RETIRE_EQUIP_CONFIRM, offset=(30, 30)):
                logger.info('[装备-穿戴] 退役装备确认弹窗')
                return False
            if SWIPE_CHECK.match(self.device.image):
                if swipe_count > 1:
                    logger.info('[装备-穿戴] 多次滑动同一舰船')
                    return False
                continue

            if self.appear(check_button, offset=(30, 30)) and not SWIPE_CHECK.match(self.device.image):
                logger.info('[装备-穿戴] 滑动检测到新舰船')
                return True

    def ship_view_next(self, check_button=EQUIPMENT_OPEN):
        """在舰船详情界面滑动切换到下一艘舰船。

        Args:
            check_button (Button): 页面确认按钮，默认 EQUIPMENT_OPEN。

        Returns:
            bool: 成功切换返回 True，否则返回 False。
        """
        return self._ship_view_swipe(distance=-SWIPE_DISTANCE, check_button=check_button)

    def ship_view_prev(self, check_button=EQUIPMENT_OPEN):
        """在舰船详情界面滑动切换到上一艘舰船。

        Args:
            check_button (Button): 页面确认按钮，默认 EQUIPMENT_OPEN。

        Returns:
            bool: 成功切换返回 True，否则返回 False。
        """
        return self._ship_view_swipe(distance=SWIPE_DISTANCE, check_button=check_button)

    def ship_info_enter(self, click_button, check_button=EQUIPMENT_OPEN, long_click=True, skip_first_screenshot=True,
                        *, additional=None, can_click=None):
        """从编队或船坞等界面点击或长按舰船图标进入舰船详情页面。

        Args:
            click_button (Button): 需要点击/长按的目标舰船按钮。
            check_button (Button): 目标页面确认按钮，默认 EQUIPMENT_OPEN。
            long_click (bool): 是否使用长按进入，默认 True。
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。
            additional (callable | None): 处理额外界面，返回 True 时重新截图。
            can_click (callable | None): 在点击前确认当前画面上的舰位可用。

        Pages:
            in: 包含 click_button 的编队或船坞界面
            out: check_button 对应界面
        """
        enter_timer = Timer(10)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束
            if self.appear(check_button, offset=(5, 5)):
                break

            if additional is not None and additional():
                continue

            # 长按偶发识别为普通点击时误入船坞，从船坞返回
            if long_click:
                if self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                    logger.info(f'[装备-穿戴] 舰船信息进入 {DOCK_CHECK} -> {BACK_ARROW}')
                    self.device.click(BACK_ARROW)
                    continue
            if enter_timer.reached() and (can_click is None or can_click()):
                if long_click:
                    self.device.long_click(click_button, duration=(1.5, 1.7))
                else:
                    self.device.click(click_button)
                enter_timer.reset()
            if self.handle_game_tips():
                continue

    @cached_property
    def _ship_side_navbar(self):
        """获取舰船详情界面左侧导航栏网格。

        根据方案舰、普通舰船、改造舰船的不同具有 3 至 5 个选项。
        """
        ship_side_navbar = ButtonGrid(
            origin=(21, 118), delta=(0, 94.5), button_shape=(60, 75), grid_shape=(1, 5), name='SHIP_SIDE_NAVBAR')

        return Navbar(grids=ship_side_navbar,
                      active_color=(247, 255, 173), active_threshold=30,
                      inactive_color=(140, 162, 181), inactive_threshold=30)

    def ship_side_navbar_ensure(self, upper=None, bottom=None):
        """确保舰船详情侧边栏切换至指定页面。

        Args:
            upper (int, optional): 从顶部开始计数的索引（1-5）：
                方案舰：1 为研发（不支持跳转），2 为装备，3 为详情。
                普通舰：1 为强化，2 为突破，3 为装备，4 为详情。
                改造舰：1 为改造，2 为强化，3 为突破，4 为装备，5 为详情。
            bottom (int, optional): 从底部开始反向计数的索引：
                2 为装备，1 为详情。

        Returns:
            bool: 侧边栏成功设置并切换返回 True，不支持或失败返回 False。
        """
        if self._ship_side_navbar.get_total(main=self) == 3:
            if upper == 1 or bottom == 3:
                logger.warning('[装备-穿戴] 不支持跳转到 "research"')
                return False

        if self._ship_side_navbar.set(self, upper=upper, bottom=bottom):
            return True
        return False

    def equip_view_next(self, check_button=EQUIPMENT_OPEN):
        """在装备界面切换到下一艘舰船。

        Args:
            check_button (Button): 界面确认按钮，默认 EQUIPMENT_OPEN。

        Returns:
            bool: 成功切换返回 True，否则返回 False。
        """
        return self.ship_view_next(check_button=check_button)

    def equip_view_prev(self, check_button=EQUIPMENT_OPEN):
        """在装备界面切换到上一艘舰船。

        Args:
            check_button (Button): 界面确认按钮，默认 EQUIPMENT_OPEN。

        Returns:
            bool: 成功切换返回 True，否则返回 False。
        """
        return self.ship_view_prev(check_button=check_button)

    def equip_enter(self, click_button, check_button=EQUIPMENT_OPEN, long_click=True, skil_first_screenshot=True):
        """进入舰船装备界面。

        Args:
            click_button (Button): 点击的目标按钮。
            check_button (Button): 目标页面确认按钮，默认 EQUIPMENT_OPEN。
            long_click (bool): 是否使用长按进入，默认 True。
            skil_first_screenshot (bool): 是否跳过首次截图，默认 True。
        """
        return self.ship_info_enter(
            click_button=click_button,
            check_button=check_button,
            long_click=long_click,
            skip_first_screenshot=skil_first_screenshot
        )

    def equip_side_navbar_ensure(self, upper=None, bottom=None):
        """确保在侧边栏中切换到装备子界面。

        Args:
            upper (int, optional): 从顶部开始计数的索引。
            bottom (int, optional): 从底部开始反向计数的索引。

        Returns:
            bool: 成功切换返回 True。
        """
        return self.ship_side_navbar_ensure(upper=upper, bottom=bottom)

    def ship_equipment_take_off(self, name=None):
        """清除舰船装备（一键卸装）。

        Args:
            name (str, optional): 舰船标识名称。
        """
        self.code_clear(name=name)

    def ship_equipment_take_on(self, name=None):
        """为舰船穿戴装备码方案。

        Args:
            name (str, optional): 舰船标识名称。
        """
        self.code_apply(name=name)

    def _equip_take_off_one(self, skip_first_screenshot=True):
        """卸下当前舰船的全部装备。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。
        """
        logger.info('[装备-穿戴] 装备卸下')
        bar_timer = Timer(5)
        off_timer = Timer(5)
        confirm_timer = Timer(5)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if off_timer.started() and self.info_bar_count():
                break

            if self.handle_storage_full():
                continue

            if confirm_timer.reached() and self.handle_popup_confirm('EQUIPMENT_TAKE_OFF'):
                confirm_timer.reset()
                off_timer.reset()
                bar_timer.reset()
                continue

            if off_timer.reached():
                if not self.info_bar_count() and self.appear_then_click(EQUIP_OFF, offset=(20, 20)):
                    off_timer.reset()
                    bar_timer.reset()
                    continue

            if bar_timer.reached():
                if self.appear(EQUIPMENT_OPEN, offset=(20, 20)) and not self.appear(EQUIP_OFF, offset=(20, 20)):
                    self.device.click(EQUIPMENT_OPEN)
                    bar_timer.reset()
                    continue

        logger.info('[装备-穿戴] 装备卸下完成')

    def equipment_take_off(self, enter, out, fleet):
        """批量卸下指定编队舰船的装备。

        Args:
            enter (Button): 长按进入装备编辑界面的按钮。
            out (Button): 退出装备界面时需要确认的按钮。
            fleet (list[int]): 编队装备记录列表，例如 [3, 1, 1, 1, 1, 1]。
        """
        logger.hr('[装备-穿戴] 装备卸下')
        self.equip_enter(enter)

        for index in '9'.join([str(x) for x in fleet if x > 0]):
            index = int(index)
            if index == 9:
                self.equip_view_next()
            else:
                self._equip_take_off_one()
                self.ui_click(click_button=EQUIPMENT_CLOSE, check_button=EQUIPMENT_OPEN, offset=None)

        self.ui_back(out)
        self.equipment_has_take_on = False

    def _equip_take_on_one(self, index, skip_first_screenshot=True):
        """为当前舰船穿戴指定编号的装备预设方案。

        Args:
            index (int): 装备预设方案序号（1-3）。
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。
        """
        logger.info('[装备-穿戴] 装备预设装上')
        bar_timer = Timer(5)
        on_timer = Timer(5)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if on_timer.started() and self.info_bar_count():
                break

            if bar_timer.reached() and not self.appear(EQUIP_1, offset=10):
                self.device.click(EQUIPMENT_OPEN)
                bar_timer.reset()
                continue

            if on_timer.reached() and self.appear(EQUIP_1, offset=10) and not self.info_bar_count():
                if index == 1:
                    self.device.click(EQUIP_1)
                elif index == 2:
                    self.device.click(EQUIP_2)
                elif index == 3:
                    self.device.click(EQUIP_3)

                on_timer.reset()
                bar_timer.reset()
                continue

        logger.info('[装备-穿戴] 装备装上完成')

    def equipment_take_on(self, enter, out, fleet):
        """批量为指定编队舰船穿戴装备预设方案。

        Args:
            enter (Button): 长按进入装备编辑界面的按钮。
            out (Button): 退出装备界面时需要确认的按钮。
            fleet (list[int]): 编队装备预设方案列表，例如 [3, 1, 1, 1, 1, 1]。
        """
        logger.hr('[装备-穿戴] 装备装上')
        self.equip_enter(enter)

        for index in '9'.join([str(x) for x in fleet if x > 0]):
            index = int(index)
            if index == 9:
                self.equip_view_next()
            else:
                self._equip_take_on_one(index=index)
                self.ui_click(click_button=EQUIPMENT_CLOSE, check_button=EQUIPMENT_OPEN, offset=None)

        self.ui_back(out)
        self.equipment_has_take_on = True
