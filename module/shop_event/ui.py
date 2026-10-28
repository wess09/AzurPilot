"""
活动商店界面导航与状态检测。

提供活动商店的页面检测、余额 OCR、滚动条控制和标签栏导航。
复用官源商店滚动条以识别活动商店滑块，
支持商店页面可用性检测（时间窗口校验）和货币余额读取。

Pages: in: EVENT_SHOP
"""

import re
from datetime import datetime, timedelta

import numpy as np

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, crop
from module.config.time_source import now as current_time
from module.config.utils import server_time_offset
from module.exception import GameStuckError
from module.logger import logger
from module.meowfficer.assets import MEOWFFICER_GET_CHECK, MEOWFFICER_TRAIN_CLICK_SAFE_AREA
from module.meowfficer.collect import SWITCH_LOCK
from module.ocr.ocr import Digit, Ocr
from module.shop.assets import SHOP_OCR_BALANCE, SHOP_OCR_OIL, SHOP_OCR_OIL_CHECK
from module.shop.shop_medal import ShopScroll
from module.shop_event.assets import *
from module.ui.navbar import Navbar
from module.ui.ui import UI

EVENT_SHOP_SCROLL = ShopScroll(
    EVENT_SHOP_SCROLL_AREA,
    color=(44, 48, 56),
    name="EVENT_SHOP_SCROLL"
)
EVENT_SHOP_SCROLL.drag_threshold = 0.08
EVENT_SHOP_SCROLL.edge_threshold = 0.1

if server.server == 'tw':
    EVENT_SHOP_DEADLINE_COLOR = (102, 204, 255)
else:
    EVENT_SHOP_DEADLINE_COLOR = (96, 162, 62)
OCR_EVENT_SHOP_DEADLINE = Ocr(SHOP_EVENT_DEADLINE, lang='cnocr', letter=EVENT_SHOP_DEADLINE_COLOR,
                              alphabet='0123456789.:~-', name="OCR_EVENT_SHOP_DEADLINE")

OCR_EVENT_SHOP_PT = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name='OCR_EVENT_SHOP_PT')
OCR_EVENT_SHOP_URPT = Digit(SHOP_OCR_BALANCE_SECOND, letter=(100, 100, 100), name='OCR_EVENT_SHOP_URPT')


class EventShopUI(UI):
    @cached_property
    def event_shop_tab_count_and_navbar(self):
        """动态计算活动商店标签数量并构建导航栏。

        Returns:
            tuple[int, Navbar]: (标签数量, 导航栏对象)。
        """
        gap_x = 33
        area = (206, 92, 1092, 134)
        image = crop(self.device.image, area)
        tab = color_similarity_2d(image, color=(232, 238, 240))
        index = np.where(np.average(tab > 221, axis=0) > 0.5)[0]
        count = (area[2] - area[0] + gap_x) // (len(index) + gap_x)
        logger.info(f"活动商店标签数: {count}")
        delta_x = (area[2] - area[0] + gap_x) // count - gap_x
        grid = ButtonGrid((206, 92), (delta_x + gap_x, 44),
                          (delta_x, 44), (count, 1),
                          "EVENT_SHOP_TAB_GRID")
        navbar = Navbar(grids=grid,
                        active_color=(232, 238, 240), inactive_color=(127, 141, 151),
                        active_count=delta_x * (area[3] - area[1]) // 2,
                        inactive_count=delta_x * (area[3] - area[1]) // 2)
        return count, navbar

    @cached_property
    def event_shop_has_urpt(self):
        """检测当前活动商店是否包含 UR 点数。

        Returns:
            bool: 包含 UR 点数返回 True，否则返回 False。
        """
        if self.image_color_count(SHOP_OCR_BALANCE_SECOND, OCR_EVENT_SHOP_URPT.letter, threshold=95, count=30):
            logger.info("[活动商店-UI] 活动商店包含UR点数")
            return True
        else:
            logger.info("[活动商店-UI] 活动商店无UR点数")
            return False

    def _get_event_deadline(self):
        """读取服务器时区中的活动商店截止时间。"""
        raw = OCR_EVENT_SHOP_DEADLINE.ocr(self.device.image)
        # 国际服可能不显示年份，且结束时间不一定是 23:59:59。
        hour, minute, second = 23, 59, 59
        period = raw
        match = re.search(r'(\d{2}):(\d{2}):(\d{2})\s*$', raw)
        if match:
            hour, minute, second = [int(x) for x in match.groups()]
            period = raw[:match.start()]
        else:
            logger.warning(f"[活动商店-UI] 截止时间未识别到时分秒，按 23:59:59 处理: {raw}")

        matches = re.findall(r'(?:(\d{4})\.)?(\d{1,2})\.(\d{1,2})', period)
        if len(matches) < 2:
            logger.warning(f"[活动商店-UI] 活动截止日期读取失败: {raw}")
            return None
        year, month, day = matches[-1]

        server_now = current_time() - server_time_offset()
        if year:
            years = [int(year)]
        else:
            years = [server_now.year - 1, server_now.year, server_now.year + 1]
            logger.warning(f"[活动商店-UI] 截止日期未显示年份，按 {server_now.year} 年附近推算: {raw}")

        candidates = []
        for y in years:
            try:
                candidates.append(datetime(y, int(month), int(day), hour, minute, second))
            except ValueError:
                pass
        if not candidates:
            logger.warning(f"[活动商店-UI] 活动截止日期无效: {raw}")
            return None

        deadline = min(candidates, key=lambda t: abs(t - server_now))
        if not year and abs(deadline - server_now) > timedelta(days=90):
            logger.warning(f"[活动商店-UI] 推算的截止日期 {deadline} 距今超过 90 天，"
                           f"改用当前年份 {server_now.year}")
            try:
                deadline = datetime(server_now.year, int(month), int(day), hour, minute, second)
            except ValueError:
                logger.warning(f"[活动商店-UI] 活动截止日期无效: {raw}")
                return None
        return deadline + timedelta(seconds=1)

    @cached_property
    def is_event_ended(self):
        """检查活动关卡是否已结束（距离商店兑换截止时间小于 7 天）。

        Returns:
            bool: 活动已结束返回 True，否则返回 False。
        """
        if self.config.EVENT_SHOP_IGNORE_DEADLINE:
            return True

        for _ in self.loop(timeout=2):
            deadline = self._get_event_deadline()
            if deadline is not None:
                break
        else:
            logger.error('[活动商店-UI] 多次尝试后仍无法读取活动截止日期')
            return False

        server_now = current_time() - server_time_offset()
        return (deadline - server_now).days < 7

    def event_shop_load_ensure(self):
        """等待活动商店页面及货币余额完全加载。

        Returns:
            bool: 加载成功返回 True。

        Raises:
            GameStuckError: 等待超时未检测到货币余额。
        """
        ensure_timeout = Timer(3, count=6).start()
        for _ in self.loop():
            if self.image_color_count(SHOP_OCR_BALANCE, OCR_EVENT_SHOP_PT.letter, threshold=95, count=30):
                logger.info("活动商店已加载。")
                break
            if ensure_timeout.reached():
                raise GameStuckError('Waiting too long for EventShop to appear.')
        return True

    @cached_property
    def is_pt_reversed(self):
        blacklist = [
            SHOP_EVENT_20240521
        ]
        return self.ui_process_check_button(check_button=blacklist)

    def event_shop_get_pt(self):
        """识别并获取当前活动 PT 点数余额。

        Returns:
            int: PT 点数数量。
        """
        ocr = OCR_EVENT_SHOP_URPT if self.is_pt_reversed else OCR_EVENT_SHOP_PT
        value = ocr.ocr(self.device.image)
        if getattr(ocr, 'last_valid', False):
            from module.log_res import LogRes
            LogRes(self.config).record('Pt', value, observed=True)
        return value

    def event_shop_get_urpt(self):
        """识别并获取当前活动 URpt 点数余额。

        Returns:
            int: URpt 点数数量。
        """
        ocr = OCR_EVENT_SHOP_PT if self.is_pt_reversed else OCR_EVENT_SHOP_URPT
        value = ocr.ocr(self.device.image)
        if getattr(ocr, 'last_valid', False):
            from module.statistics.resource_flow import observe
            observe(self.config, 'URPt', value)
        return value

    def get_oil(self, skip_first_screenshot=True):
        """获取当前石油余额。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Returns:
            int: 当前石油数量。
        """
        amount = 0
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('获取石油超时')
                break

            if not self.appear(SHOP_OCR_OIL_CHECK, offset=(10, 2)):
                logger.info('无石油图标')
                continue
            ocr = Digit(SHOP_OCR_OIL, name='OCR_OIL', letter=(247, 247, 247), threshold=128)
            amount = ocr.ocr(self.device.image)
            if amount >= 100:
                break

        return amount

    def handle_get_meowfficer(self):
        """处理购买商品后触发的指挥喵获得弹窗。

        Returns:
            bool: 是否检测并关闭了弹窗。
        """
        if self.appear(MEOWFFICER_GET_CHECK, offset=(40, 40), interval=3):
            logger.info(f'获取指挥喵奖励。')
            SWITCH_LOCK.set('lock', main=self)
            # 等待信息提示栏消失
            self.ensure_no_info_bar(timeout=1)
            self.device.click(MEOWFFICER_TRAIN_CLICK_SAFE_AREA)
            return True
        return False
