from module.base.decorator import cached_property
from module.logger import logger
from module.shop.assets import *
from module.shop.base import ShopItemGrid, ShopItemGrid_250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus
from module.shop.ui import ShopUI


class GuildShop_250814(ShopClerk, ShopUI, ShopStatus):
    """舰队商店处理器 (2025-08-14 新 UI)。

    Pages: in: page_shop (guild shop tab)
    """

    shop_template_folder = './assets/shop/guild'

    @cached_property
    def shop_filter(self):
        """获取舰队商店过滤器。

        Returns:
            str: 过滤器字符串
        """
        return self.config.GuildShop_Filter.strip()

    # 2025-08-14 新 UI
    @cached_property
    def shop_guild_items(self):
        """加载舰队商店商品模板和配置。

        Returns:
            ShopItemGrid_250814: 商店商品网格对象
        """
        shop_grid = self.shop_grid
        shop_guild_items = ShopItemGrid_250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(14, 121, 85, 150),
        )
        self.shop_template_folder = './assets/shop/guild'
        shop_guild_items.load_template_folder(self.shop_template_folder)
        shop_guild_items.load_cost_template_folder('./assets/shop/cost')
        return shop_guild_items

    def shop_items(self):
        """获取商店商品网格的统一接口。

        所有商店共享相同的属性名，使用 @Config 时需要
        定义唯一的别名作为覆盖。

        Returns:
            ShopItemGrid_250814: 商店商品网格
        """
        return self.shop_guild_items

    def shop_currency(self):
        """OCR 识别舰队商店货币数量。

        通过状态检测获取当前舰队币余额并记录日志。

        Returns:
            int: 舰队币数量
        """
        self._currency = self.status_get_guild_coins()
        logger.info(f'Guild coins: {self._currency}')
        return self._currency

    def shop_interval_clear(self):
        """清除购买界面相关按钮的点击间隔。

        重置购买确认选择按钮的 interval 状态。
        """
        super().shop_interval_clear()
        self.interval_clear(SHOP_BUY_CONFIRM_SELECT)

    def shop_buy_handle(self, item):
        """处理舰队商店购买界面。

        检测并处理购买确认选择界面。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否检测到购买界面并进行了处理
        """
        if self.appear(SHOP_BUY_CONFIRM_SELECT, offset=(20, 20), interval=3):
            self.shop_buy_select_execute(item)
            self.interval_reset(SHOP_BUY_CONFIRM_SELECT)
            return True

        return False

    def run(self):
        """运行舰队商店购买流程。

        Pages: in: page_shop (guild shop tab)

        按照过滤器配置购买舰队商店商品，支持刷新。
        刷新消耗 50 舰队币，T4 部件箱价格 60，余额不足 110 时跳过刷新。
        """
        if not self.shop_filter:
            return

        logger.hr('Guild Shop', level=1)

        # 执行购买操作，启用刷新时最多尝试 2 次
        refresh = self.config.GuildShop_Refresh
        for _ in range(2):
            success = self.shop_buy()
            if not success:
                break
            if refresh:
                # 刷新消耗 50，T4 部件箱价格 60
                if self._currency >= 110:
                    if self.shop_refresh():
                        continue
                else:
                    logger.info('Guild coins < 110, skip refreshing')
            break
