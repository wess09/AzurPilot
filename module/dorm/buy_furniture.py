"""
后宅家具购买模块。

自动检测并购买宿舍家具商店中的限时家具。功能包括：
- 进入宿舍家具商店并浏览家具详情
- 通过 OCR 识别家具代币余额和价格，判断是否足够购买
- 根据配置选择购买套装或全部购买
- 支持按固定间隔（默认 6 天）自动检查并购买
"""
from datetime import timedelta

from module.combat.assets import GET_SHIP
from module.config.time_source import now as current_time
from module.dorm.assets import *
from module.exercise.assets import EXERCISE_PREPARATION
from module.base.runtime_params import CHECK_INTERVAL
from module.config.utils import read_run_param
from module.logger import logger
from module.ocr.ocr import Digit
from module.ui.assets import DORM_CHECK
from module.ui.ui import UI

OCR_FURNITURE_COIN = Digit(OCR_DORM_FURNITURE_COIN, letter=(107, 89, 82), threshold=128, alphabet='0123456789', name='OCR_FURNITURE_COIN')
OCR_FURNITURE_PRICE = Digit(OCR_DORM_FURNITURE_PRICE, letter=(255, 247, 247), threshold=64, alphabet='0123456789', name='OCR_FURNITURE_PRICE')

# 检查间隔（天）走 WebUI「运行参数」页（RunParams.UiWait），
# 默认值集中在 module/base/runtime_params.py（界面等待域）。
# 购买按钮映射
FURNITURE_BUY_BUTTON = {
    "all": DORM_FURNITURE_BUY_ALL,
    "set": DORM_FURNITURE_BUY_SET
}


class BuyFurniture(UI):
    """家具购买处理器，负责自动检测和购买限时家具。

    继承自 UI，通过 OCR 识别家具代币余额和价格，
    在检测到限时家具时自动购买。支持套装购买和全部购买两种模式。

    Attributes:
        CHECK_INTERVAL (int): 检查间隔天数，默认 6 天。
        FURNITURE_BUY_BUTTON (dict): 购买按钮映射，包含 "all" 和 "set" 两种选项。
    """

    def enter_first_furniture_details_page(self, skip_first_screenshot=False):
        """从后宅进入商店并打开首个家具详情界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_dorm 或 DORM_FURNITURE_SHOP_ENTER（家具商店页面）
            out: DORM_FURNITURE_DETAILS_QUIT（家具详情页面）
        """
        self.interval_clear((DORM_CHECK, DORM_FURNITURE_DETAILS_ENTER,
                             DORM_FURNITURE_SHOP_FIRST,))
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 从后宅进入家具商店，只需进入一次
            if self.appear(DORM_CHECK, offset=(20, 20), interval=3):
                self.device.click(DORM_FURNITURE_SHOP_ENTER)
                self.interval_reset([GET_SHIP, EXERCISE_PREPARATION])
                continue

            if self.appear(DORM_FURNITURE_SHOP_FIRST_SELECTED, offset=(20, 20)):
                self.interval_reset([GET_SHIP, EXERCISE_PREPARATION])
                # 从家具商店进入家具详情页
                if self.appear(DORM_FURNITURE_DETAILS_ENTER, offset=(20, 20), interval=3):
                    self.device.click(DORM_FURNITURE_DETAILS_ENTER)
                    continue
            # 购买家具后当前选中的家具可能不再是列表首个，重新选中下方列表第一个家具
            elif self.appear(DORM_FURNITURE_SHOP_FIRST, offset=(20, 20), interval=3):
                self.device.click(DORM_FURNITURE_SHOP_FIRST)
                self.interval_reset([GET_SHIP, EXERCISE_PREPARATION])
                continue

            if self.appear(DORM_FURNITURE_DETAILS_QUIT, offset=(20, 20)):
                break

            if self.ui_additional(get_ship=False):
                self.interval_clear(DORM_CHECK)
                continue

    def furniture_shop_quit(self, skip_first_screenshot=False):
        """退出家具商店页面，返回后宅主界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: DORM_FURNITURE_DETAILS_ENTER（家具商店页面）
            out: page_dorm
        """
        self.interval_clear(DORM_FURNITURE_DETAILS_ENTER)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 退出条件
            if self.appear(DORM_CHECK, offset=(20, 20)):
                break

            if self.appear(DORM_FURNITURE_DETAILS_ENTER, offset=(20, 20), interval=3):
                self.device.click(DORM_FURNITURE_SHOP_QUIT)
                continue

    def furniture_details_page_quit(self, skip_first_screenshot=False):
        """退出家具详情界面，返回家具商店列表。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: DORM_FURNITURE_DETAILS_QUIT（家具详情界面）
            out: DORM_FURNITURE_DETAILS_ENTER（家具商店页面）
        """
        self.interval_clear(DORM_FURNITURE_DETAILS_QUIT)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 退出条件
            if self.appear(DORM_FURNITURE_DETAILS_ENTER, offset=(20, 20)):
                break

            if self.appear(DORM_FURNITURE_DETAILS_QUIT, offset=(20, 20), interval=3):
                self.device.click(DORM_FURNITURE_DETAILS_QUIT)
                continue

    def furniture_payment_enter(self, buy_button: Button, skip_first_screenshot=False):
        """在家具详情界面点击购买按钮，进入购买确认界面。

        Args:
            buy_button (Button): 购买按钮（DORM_FURNITURE_BUY_SET 或 DORM_FURNITURE_BUY_ALL）。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: DORM_FURNITURE_DETAILS_QUIT（家具详情界面）
            out: DORM_FURNITURE_BUY_CONFIRM（购买确认弹窗）
        """
        self.interval_clear(DORM_FURNITURE_DETAILS_QUIT)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DORM_FURNITURE_BUY_CONFIRM):
                break

            if self.appear(DORM_FURNITURE_DETAILS_QUIT, interval=3):
                self.device.click(buy_button)

    def buy_furniture_confirm(self, skip_first_screenshot=False):
        """点击确认购买按钮并返回家具详情界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: DORM_FURNITURE_BUY_CONFIRM（购买确认弹窗）
            out: DORM_FURNITURE_DETAILS_QUIT（家具详情界面）
        """
        self.interval_clear(DORM_FURNITURE_BUY_CONFIRM)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DORM_FURNITURE_DETAILS_QUIT):
                break

            if self.appear(DORM_FURNITURE_BUY_CONFIRM, offset=(20, 20), interval=3):
                self.device.click(DORM_FURNITURE_BUY_CONFIRM)

    def buy_furniture_once(self, buy_option: str):
        """执行单次家具购买检测与结算操作。

        Args:
            buy_option (str): 购买模式，'all'（全选）或 'set'（套装）。

        Returns:
            bool: 家具币充足并成功购买返回 True，否则返回 False。

        Pages:
            in: DORM_FURNITURE_DETAILS_QUIT（家具详情界面）
        """
        buy_button: Button = FURNITURE_BUY_BUTTON[buy_option]
        coin = OCR_FURNITURE_COIN.ocr(self.device.image)

        self.furniture_payment_enter(buy_button, skip_first_screenshot=True)
        price = OCR_FURNITURE_PRICE.ocr(self.device.image)

        # 无论购买成功与否都会有弹窗并返回详情页，通过家具币与价格比对得出结果
        if coin >= price > 0:
            logger.info(f"[宿舍-家具] 家具币充足，购买 {buy_option}")
            buy_successful = True
        else:
            logger.info(f"[宿舍-家具] 家具币不足，购买结束")
            buy_successful = False
        self.buy_furniture_confirm(skip_first_screenshot=True)
        self.furniture_details_page_quit(skip_first_screenshot=True)
        return buy_successful

    def _buy_furniture_run(self):
        """检测并尝试购买首个限时家具。

        Returns:
            bool: 成功购买且可继续寻找下一个返回 True，否则返回 False。
        """
        self.enter_first_furniture_details_page()
        if self.match_template_color(DORM_FURNITURE_COUNTDOWN, offset=(20, 20)):
            logger.info("[宿舍-家具] 发现限时家具可购买")

            if self.buy_furniture_once(self.config.BuyFurniture_BuyOption):
                logger.info("[宿舍-家具] 查找下一个限时家具")
                return True
            else:
                return False
        else:
            logger.info("[宿舍-家具] 未找到限时家具")
            return False

    def buy_furniture_run(self):
        """后宅家具购买主流程。

        循环检测并购买限时家具，完成后返回后宅页面并更新运行时间。

        Pages:
            in: DORM_FURNITURE_DETAILS_ENTER（家具商店页面）
            out: page_dorm
        """
        logger.info("[宿舍-家具] 开始购买家具")
        while 1:
            if self._buy_furniture_run():
                continue
            else:
                break
        # 退出回到 page_dorm
        logger.info("[宿舍-家具] 回退到后宅页面")
        self.furniture_details_page_quit(skip_first_screenshot=True)
        self.furniture_shop_quit(skip_first_screenshot=True)
        self.config.BuyFurniture_LastRun = current_time().replace(microsecond=0)

    def run(self):
        """执行后宅家具购买任务。

        根据配置的检查间隔判断是否到期，到期则进入商店购买限时家具。
        """
        check_days = int(read_run_param(
            self.config, 'UiWait_BuyFurnitureCheckIntervalDays', CHECK_INTERVAL, 1, 30))
        logger.attr("上次运行时间", self.config.BuyFurniture_LastRun)
        logger.attr("检查间隔", check_days)

        time_run = self.config.BuyFurniture_LastRun + timedelta(days=check_days)
        logger.info(f"[宿舍-家具] 任务运行时间: {time_run}")

        if current_time().replace(microsecond=0) < time_run:
            logger.info("[宿舍-家具] 未到运行时间，跳过")
            return

        self.buy_furniture_run()
