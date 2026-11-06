"""补给包处理器，自动购买每周和每日补给包。
根据星期和服务器时间判断可购买的补给包类型。
"""

from calendar import day_name

import cv2

from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.config.utils import get_server_weekday
from module.freebies.assets import *
from module.logger import logger
from module.ocr.ocr import Digit
from module.shop.assets import SHOP_OCR_OIL, SHOP_OCR_OIL_CHECK
from module.ui.page import page_shop, page_supply_pack


class SupplyPack(CampaignStatus):
    """商店免费补给包购买处理器。

    检测并自动购买商店中的免费补给礼包（如每周免费石油补给包）。
    """

    def supply_pack_find(self, supply_pack, skip_first_screenshot=True):
        """稳定检查当前屏后再向左查找补给包，最多滑动 8 次。

        Returns:
            bool: 是否找到补给包。

        Pages:
            in: page_supply_pack
            out: page_supply_pack
        """
        confirm_timer = Timer(1, count=3).start()
        previous = None
        attempt = 0
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(supply_pack, offset=(0, -20, 400, 20)):
                return True

            if self.appear(page_supply_pack.check_button, offset=(20, 20)):
                # 只观察识别范围内的价格栏，避开商品立绘动画；过渡帧不能算作检查完成。
                x1, y1, x2, y2 = supply_pack.area
                current = self.image_crop((x1, y1 - 20, x2 + 400, y2 + 20))
                if previous is None or cv2.norm(current, previous, cv2.NORM_L1) > current.size:
                    previous = current
                    confirm_timer.reset()
                    continue

                if confirm_timer.reached():
                    if attempt >= 8:
                        break
                    logger.info('[免费福利-补给] 当前屏稳定检查未找到补给包，向左查找')
                    self.device.swipe_vector((-400, 0), box=(230, 200, 1060, 600))
                    attempt += 1
                    previous = None
                    confirm_timer.reset()
            else:
                previous = None
                confirm_timer.reset()

        logger.warning(f'[免费福利-补给] 左滑 8 次后仍未找到 {supply_pack}')
        return False

    def supply_pack_buy(self, supply_pack, skip_first_screenshot=True):
        """购买指定的补给包。

        Args:
            supply_pack (Button): 补给包按钮。
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。

        Returns:
            bool: 成功购买返回 True，否则返回 False。

        Pages:
            in: page_supply_pack
            out: page_supply_pack
        """
        logger.hr('购买补给包')
        if not self.supply_pack_find(supply_pack, skip_first_screenshot=skip_first_screenshot):
            return False
        [self.interval_clear(asset) for asset in [GET_ITEMS_1, GET_ITEMS_2, supply_pack, BUY_CONFIRM]]

        logger.info(f'[免费福利-补给] 购买 {supply_pack}')
        executed = False
        click_count = 0
        confirm_timer = Timer(1, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(supply_pack, offset=(200, 20), interval=3):
                if click_count >= 3:
                    logger.warning(f'[免费福利-补给] 购买 {supply_pack} 尝试3次后失败，可能达到资源限制，跳过')
                    break
                self.device.click(supply_pack)
                click_count += 1
                confirm_timer.reset()
                continue
            if self.appear_then_click(BUY_CONFIRM, offset=(20, 20), interval=3):
                confirm_timer.reset()
                continue
            if self.handle_popup_confirm('BUY_SUPPLY_PACK'):
                self.interval_reset(supply_pack)
                self.interval_reset(BUY_CONFIRM)
                executed = True
                continue
            for button in [GET_ITEMS_1, GET_ITEMS_2]:
                if self.appear_then_click(button, offset=(30, 30), interval=3):
                    confirm_timer.reset()
                    continue

            # 结束条件
            if self.appear(page_supply_pack.check_button, offset=(20, 20)) \
                    and not self.appear(supply_pack, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        logger.info(f'购买补给包 finished, executed={executed}')
        return executed

    def goto_supply_pack(self, skip_first_screenshot=True):
        """导航前往补给包标签页。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。

        Pages:
            in: page_shop
            out: page_supply_pack
        """
        self.ui_goto(page_supply_pack, skip_first_screenshot=skip_first_screenshot)

    def run(self):
        """执行免费补给包检查与购买流程。

        Pages:
            in: 任意页面
            out: page_supply_pack
        """
        self.ui_ensure(page_shop)
        self.goto_supply_pack()
        if self.get_oil() < 21000:
            server_today = get_server_weekday()
            target = self.config.SupplyPack_DayOfWeek
            target_name = day_name[target]
            if server_today >= target:
                self.supply_pack_buy(FREE_SUPPLY_PACK)
            else:
                logger.info(f'[免费福利-补给] 将免费周补给包延迟到 {target_name}')
        else:
            logger.info('石油超限，无法购买免费周补给包')


class SupplyPack_250814(SupplyPack):
    """2025年8月改版后的商店补给包处理器。

    适配新版商店 UI 下的石油数值识别与补给包页面导航。
    """

    def get_oil(self, skip_first_screenshot=True):
        """通过 OCR 识别商店页面顶部的石油存量。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。

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

    def goto_supply_pack(self, skip_first_screenshot=True):
        """进入新版商店补给包标签页。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图，默认 True。

        Pages:
            in: page_shop
            out: page_supply_pack
        """
        logger.info('前往补给包')
        for _ in self.loop():

            if self.match_template_color(page_supply_pack.check_button, offset=(20, 20)):
                logger.info('在补给包')
                break

            elif self.appear_then_click(page_supply_pack.check_button, offset=(20, 20), interval=3):
                continue
