from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import area_pad
import module.config.server as server
from module.campaign.assets import OCR_COIN as CAMPAIGN_OCR_COIN
from module.handler.assets import LOGIN_ANNOUNCE
from module.logger import logger
from module.ocr.ocr import Digit
from module.shipyard.ui_globals import *
from module.ui.assets import SHIPYARD_CHECK
from module.ui.navbar import Navbar
from module.ui.page import page_main_white
from module.ui.ui import UI

OCR_COIN = Digit(
    CAMPAIGN_OCR_COIN,
    name='OCR_COIN',
    letter=(201, 201, 201) if server.server == 'jp' else (239, 239, 239),
    threshold=128,
)


class ShipyardNavbar(Navbar):
    def is_button_active(self, button, main):
        if main.image_color_count(button, color=(33, 113, 222), threshold=221, count=400):
            return True
        # 奥丁肩部区域的颜色
        if main.image_color_count(button, color=(41, 85, 165), threshold=221, count=400):
            return True
        return False


class ShipyardUI(UI):
    def _shipyard_cannot_strengthen(self):
        """
        检测舰船是否无法继续强化。

        在 DEV 或 FATE 界面中，判断当前舰船是否已达
        到当前等级的最大强化程度，无法继续消耗蓝图。

        Returns:
            bool: 是否出现无法强化的提示
        """
        if self.appear(SHIPYARD_PROGRESS_DEV, offset=(20, 20)) \
                or self.appear(SHIPYARD_PROGRESS_FATE, offset=(20, 20)) \
                or self.appear(SHIPYARD_LEVEL_NOT_ENOUGH_FATE, offset=(20, 20)) \
                or self.appear(SHIPYARD_LEVEL_NOT_ENOUGH_DEV, offset=(20, 20)):
            logger.info('Ship at full strength for current level, '
                        'no more BPs can be consumed')
            return True
        return False

    def _shipyard_get_append(self):
        """
        获取当前所处的开发阶段后缀。

        Returns:
            str: 'FATE' 或 'DEV'
        """
        if self.appear(SHIPYARD_IN_FATE, offset=(20, 20)):
            return 'FATE'
        else:
            return 'DEV'

    def _shipyard_get_total(self):
        """
        获取当前界面中的蓝图总数读值。

        游戏 UI 在不同 PR 季节间有差异，且 DEV/FATE
        阶段的按钮布局不同，需要动态检测并生成 OCR 区域。

        Returns:
            tuple: (plus 按钮, minus 按钮, OCR 识别的数值)
        """
        # 游戏 UI 在此处较为复杂，DEV/FATE 与 MAX 按钮的有无会导致不同布局。
        # 有 MAX 按钮时: | - |   0   | + | | MAX |
        # 无 MAX 按钮时: | - |       0       | + |
        # 动态检测并生成新的 OCR 区域。
        append = self._shipyard_get_append()
        ocr = globals()[f'OCR_SHIPYARD_TOTAL_{append}']
        minus = globals()[f'SHIPYARD_MINUS_{append}']
        plus = globals()[f'SHIPYARD_PLUS_{append}']
        self.wait_until_appear(minus, offset=(20, 20), skip_first_screenshot=True)
        self.wait_until_appear(plus, offset=(150, 20), skip_first_screenshot=True)
        area = ocr.buttons[0]
        ocr.buttons = [(minus.button[2] + 3, area[1], plus.button[0] - 3, area[3])]

        return plus, minus, ocr.ocr(self.device.image)

    def _shipyard_ensure_index(self, count, skip_first_screenshot=True):
        """
        调整蓝图消耗数量到目标值。

        类似 ui_ensure_index 的实现，尝试将消耗数量调整到
        count。若界面不允许消耗全部数量，则保留允许的最大值。

        Args:
            count (int): 目标消耗数量
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            int: 无法消耗的剩余蓝图数量，None 表示异常
        """
        if count < 0:
            logger.warning('_shipyard_ensure_index --> Non-positive '
                           '\'count\' cannot continue')
            return None

        current = diff = 0
        for _ in range(3):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            plus, minus, current = self._shipyard_get_total()
            if current == count:
                logger.info(f'Capable of consuming all {count} BPs')
                return 0

            diff = count - current
            button = plus if diff > 0 else minus
            self.device.multi_click(button, n=diff, interval=(0.3, 0.5))
            self.device.sleep((0.3, 0.5))

        logger.info(f'Current interface does not allow consumption of {count} BPs\n')
        logger.info(f'Capable of consuming at most {current} of the {count} BPs')
        return diff

    def _shipyard_get_bp_count(self, index=0):
        """
        获取指定位置舰船的蓝图数量。

        Args:
            index (int): 目标舰船位置（从 1 开始）

        Returns:
            int: OCR 识别的蓝图数量
        """
        # index(config.SHIPYARD_INDEX) 从 1 开始
        if index <= 0 or index > len(SHIPYARD_BP_COUNT_GRID.buttons):
            logger.warning(f'Cannot parse for count from index {index}')
            return -1

        result = OCR_SHIPYARD_BP_COUNT_GRID.ocr(self.device.image)

        return result[index - 1]

    def _shipyard_in_ui(self):
        """
        检测当前是否在船坞界面内。

        Returns:
            bool: 是否处于船坞 UI 区域
        """
        if self.appear(SHIPYARD_CHECK, offset=(20, 20)):
            return True
        if self.appear(SHIPYARD_IN_DEV, offset=(20, 20)):
            return True
        if self.appear(SHIPYARD_IN_FATE, offset=(20, 20)):
            return True

        return False

    def _shipyard_set_series(self, series=1, skip_first_screenshot=True):
        """
        设置当前显示的科研系列。

        Args:
            series (int): 目标科研系列编号
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            bool: 是否设置成功
        """
        if series <= 0 or series > len(SHIPYARD_SERIES_GRID.buttons):
            logger.warning(f'Research Series {series} is not selectable')
            return False

        self.ui_click(SHIPYARD_SERIES_SELECT_ENTER, appear_button=self._shipyard_in_ui,
                      check_button=SHIPYARD_SERIES_SELECT_CHECK,
                      skip_first_screenshot=skip_first_screenshot)
        series_button = SHIPYARD_SERIES_GRID.buttons[series - 1]
        self.ui_click(series_button, appear_button=SHIPYARD_SERIES_SELECT_CHECK,
                      check_button=self._shipyard_in_ui,
                      skip_first_screenshot=skip_first_screenshot)

        return True

    @cached_property
    def _shipyard_bottom_navbar(self):
        """
        船坞底部导航栏，用于在选定系列内切换舰船。

        位置因用户的科研进度而异，用户需自行确认索引。
        """
        return ShipyardNavbar(
            grids=SHIPYARD_FACE_GRID,
            inactive_color=(49, 60, 82), inactive_threshold=221, inactive_count=50)

    def shipyard_bottom_navbar_ensure(self, left=None, right=None, skip_first_screenshot=True):
        """
        确保导航到指定索引的舰船页面。

        根据索引切换底部导航栏，等待界面完全过渡。

        Args:
            left (int): 目标舰船索引
            right (int): 目标舰船索引（右侧）
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            bool: 导航栏是否设置成功
        """
        if left is None and right is not None:
            left = right
            right = None
        if left is not None:
            if left <= 0 or left > len(SHIPYARD_FACE_GRID.buttons):
                logger.warning(f'Index for bottom Navbar {left} is not selectable')
                return False

        ensured = False
        if self._shipyard_bottom_navbar.set(self, left=left, right=right, skip_first_screenshot=skip_first_screenshot):
            ensured = True

        # 导航栏设置后，等待界面完全过渡
        confirm_timer = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束
            if self._shipyard_in_ui():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        return ensured

    def shipyard_set_focus(self, series=1, index=1, skip_first_screenshot=True):
        """
        设置船坞焦点到指定系列和舰船。

        Args:
            series (int): 目标科研系列编号
            index (int): 目标舰船索引
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            bool: 是否设置成功
        """
        if series > 2 and index > 5:
            logger.warning(f'Research Series {series} is limited to indexes 1-5, cannot set focus to index {index}')
            return False
        return self._shipyard_set_series(series, skip_first_screenshot) \
               and self.shipyard_bottom_navbar_ensure(left=index, skip_first_screenshot=skip_first_screenshot)

    def _shipyard_get_ship(self, skip_first_screenshot=True):
        """
        处理获取已完成研发的舰船的界面过渡。

        Pages: in: SHIPYARD_RESEARCH_COMPLETE, out: SHIPYARD_CONFIRM_DEV

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图
        """
        from module.combat.assets import GET_SHIP

        confirm_timer = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(SHIPYARD_RESEARCH_COMPLETE,
                                      interval=1, offset=(20, 20)):
                confirm_timer.reset()
                continue

            if self.story_skip():
                confirm_timer.reset()
                continue

            if self.appear_then_click(GET_SHIP, interval=1):
                confirm_timer.reset()
                continue

            if self.handle_popup_confirm('LOCK_SHIP'):
                confirm_timer.reset()
                continue

            if self.appear(SHIPYARD_CONFIRM_DEV, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _shipyard_buy_confirm(self, text, skip_first_screenshot=True):
        """
        处理使用/购买蓝图的界面过渡。

        Pages: in: SHIPYARD_CONFIRM_DEV/FATE, out: 船坞界面

        Args:
            text (str): 弹窗确认标识文本
            skip_first_screenshot (bool): 是否跳过首次截图
        """
        success = False
        append = self._shipyard_get_append()
        button = globals()[f'SHIPYARD_CONFIRM_{append}']
        ocr_timer = Timer(10, count=10).start()
        confirm_timer = Timer(1, count=2).start()
        self.interval_clear(button)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if ocr_timer.reached():
                # 未能检测到正常退出，回退到 OCR 检查
                logger.warning('Failed to detect for normal exit routine, resort to OCR check')
                _, _, current = self._shipyard_get_total()
                if not current:
                    logger.info('Confirm action has completed, setting flag for exit')
                    self.interval_reset(button)
                    success = True
                ocr_timer.reset()
                continue

            if self.appear_then_click(button, offset=(20, 20), interval=3):
                continue

            if self.handle_popup_confirm(text):
                self.interval_reset(button)
                ocr_timer.reset()
                confirm_timer.reset()
                continue

            if self.story_skip():
                self.interval_reset(button)
                success = True
                ocr_timer.reset()
                confirm_timer.reset()
                continue

            if self.handle_info_bar():
                self.interval_reset(button)
                success = True
                ocr_timer.reset()
                confirm_timer.reset()
                continue

            # DEV 完成进入 FATE 时会弹出 FATE 信息
            if self.appear_then_click(LOGIN_ANNOUNCE, offset=area_pad((-300, 127, -300, 127), pad=-50), interval=3):
                self.interval_reset(button)
                success = True
                ocr_timer.reset()
                confirm_timer.reset()
                continue

            # 结束
            if success and self._shipyard_in_ui():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _shipyard_buy_enter(self):
        """
        进入蓝图购买界面。

        检查当前舰船是否已完成研发，若研发完成则获取舰船，
        若有 FATE 阶段则进入 FATE 界面。

        Returns:
            bool: 是否成功进入购买界面
        """
        if self.appear(SHIPYARD_RESEARCH_INCOMPLETE, offset=(20, 20)) \
                or self.appear(SHIPYARD_RESEARCH_IN_PROGRESS, offset=(20, 20)):
            logger.warning('Cannot enter buy interface, focused '
                           'ship has not yet been fully researched')
            return False

        if self.appear(SHIPYARD_RESEARCH_COMPLETE, offset=(20, 20)):
            self._shipyard_get_ship()

        if self.appear(SHIPYARD_GO_FATE, offset=(20, 20)):
            self.device.click(SHIPYARD_GO_FATE)
            self.wait_until_appear(SHIPYARD_IN_FATE, offset=(20, 20))

        return True

    def _shipyard_get_coin(self):
        """
        获取当前金币数量。

        Returns:
            int: 金币数量
        """
        if self.ui_page_appear(page_main_white):
            return MAIN_OCR_COIN.ocr(self.device.image)
        else:
            return OCR_COIN.ocr(self.device.image)
