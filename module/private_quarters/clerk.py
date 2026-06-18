from module.base.timer import Timer
from module.logger import logger
from module.private_quarters.assets import *
from module.private_quarters.ui import PQShopUI
from module.shop.clerk import ShopClerk


class PQShopClerk(ShopClerk, PQShopUI):
    def shop_interval_clear(self):
        """
        清除私人宿舍商店相关的按钮间隔计时器。

        子类可覆写此方法以清除特定资产的间隔。
        """
        self.interval_clear([
            PRIVATE_QUARTERS_SHOP_CHECK,
            PRIVATE_QUARTERS_SHOP_AMOUNT_MAX,
            PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT
        ])

    def shop_buy_execute(self, item, skip_first_screenshot=True):
        """
        执行单个商品的购买流程。

        点击商品 -> 最大数量 -> 确认购买 -> 等待购买完成。

        Args:
            item: 要购买的商品按钮
            skip_first_screenshot (bool): 是否跳过首次截图

        Pages:
            in: 私人宿舍商店
            out: 私人宿舍商店
        """

        # 辅助函数：检测购买确认前后的界面状态
        def after_confirm_state():
            return (self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20)) or
                    self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20)))

        def after_purchase_state():
            return (not self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20)) and
                    not self.appear(PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20)) and
                    self.appear(PRIVATE_QUARTERS_SHOP_CHECK))

        self.shop_interval_clear()
        PRIVATE_QUARTERS_SHOP_CHECK.clear_offset()

        for _ in self.loop():

            # 结束条件：购买确认状态
            if after_confirm_state():
                break

            if self.appear(PRIVATE_QUARTERS_SHOP_CHECK, interval=3):
                self.device.click(item)
                continue
            if self.appear_then_click(PRIVATE_QUARTERS_SHOP_AMOUNT_MAX, offset=(20, 20), interval=1):
                continue
            if self.appear_then_click(PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT, offset=(20, 20), interval=1):
                continue

        click_timer = Timer(3, count=6)
        for _ in self.loop():
            # 结束条件：购买完成状态
            if after_purchase_state():
                break

            if click_timer.reached() and after_confirm_state():
                self.device.click(PRIVATE_QUARTERS_SHOP_CHECK)
                click_timer.reset()
                continue

    def shop_buy(self):
        """
        循环扫描并购买商店中的可购物品。

        最多循环 12 次，每次扫描商品列表、检查余额、购买第一个匹配项。

        Returns:
            bool: 是否成功完成（True=全部买完或无可买项，False=余额不足）

        Pages:
            in: 私人宿舍商店
            out: 私人宿舍商店
        """
        for _ in range(12):
            logger.hr('Shop buy', level=2)
            # 先获取商品列表，再读取货币以获得更准确的 OCR 结果
            items = self.shop_get_items()
            self.shop_currency()
            if self._currency <= 0:
                logger.warning(f'Current funds: {self._currency}, stopped')
                return False

            item = self.shop_get_item_to_buy(items)
            if item is None:
                logger.info('Shop buy finished')
                return True
            else:
                self.shop_buy_execute(item)

                # 购买后导航栏会重置到默认位置，需要重新定位
                self.shop_left_navbar_ensure(2)
                self.shop_bottom_navbar_ensure(2)

                continue

        logger.warning('Too many items to buy, stopped')
        return True
