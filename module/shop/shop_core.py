from module.base.decorator import cached_property
from module.logger import logger
from module.shop.assets import *
from module.shop.base import ShopItemGrid, ShopItemGrid_250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus


class CoreShop_250814(ShopClerk, ShopStatus):
    """核心商店处理器 (2025-08-14 新 UI)。

    Pages: in: page_shop (core shop tab)
    """

    shop_template_folder = './assets/shop/core'

    @cached_property
    def shop_filter(self):
        """获取核心商店过滤器。

        Returns:
            str: 过滤器字符串
        """
        return self.config.CoreShop_Filter.strip()

    # 2025-08-14 新 UI
    @cached_property
    def shop_core_items(self):
        """加载核心商店商品模板和配置。

        Returns:
            ShopItemGrid_250814: 商店商品网格对象
        """
        shop_grid = self.shop_grid
        shop_core_items = ShopItemGrid_250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(18, 121, 85, 150),
        )
        shop_core_items.load_template_folder(self.shop_template_folder)
        shop_core_items.load_cost_template_folder('./assets/shop/cost')
        return shop_core_items

    def shop_items(self):
        """获取商店商品网格的统一接口。

        所有商店共享相同的属性名。如存在服务器语言差异，
        参考 shop_guild/medal 的 @Config 用法。

        Returns:
            ShopItemGrid_250814: 商店商品网格
        """
        return self.shop_core_items

    def shop_currency(self):
        """OCR 识别核心商店货币数量。

        通过状态检测获取当前核心数据余额并记录日志。

        Returns:
            int: 核心数据数量
        """
        self._currency = self.status_get_core()
        logger.info(f'Core: {self._currency}')
        return self._currency

    def shop_interval_clear(self):
        """清除购买界面相关按钮的点击间隔。

        重置购买数量按钮的 interval 状态。
        """
        super().shop_interval_clear()
        self.interval_clear(SHOP_BUY_CONFIRM_AMOUNT)

    def shop_buy_handle(self, item):
        """处理核心商店购买界面。

        检测并处理购买数量输入界面。

        Args:
            item: 待购买的商品对象

        Returns:
            bool: 是否检测到购买界面并进行了处理
        """
        if self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
            self.shop_buy_amount_execute(item)
            self.interval_reset(SHOP_BUY_CONFIRM_AMOUNT)
            return True

        return False

    def run(self):
        """运行核心商店购买流程。

        Pages: in: page_shop (core shop tab)

        按照过滤器配置购买核心商店商品。
        """
        if not self.shop_filter:
            return

        logger.hr('Core Shop', level=1)

        # 执行购买操作
        self.shop_buy()
