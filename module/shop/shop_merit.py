from module.base.decorator import cached_property
from module.logger import logger
from module.shop.base import ShopItemGrid, ShopItemGrid_250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus
from module.shop.ui import ShopUI


class MeritShop_250814(ShopClerk, ShopUI, ShopStatus):
    """功勋商店处理器 (2025-08-14 新 UI)。

    Pages: in: page_shop (merit shop tab)
    """

    shop_template_folder = './assets/shop/merit'

    @cached_property
    def shop_filter(self):
        """获取功勋商店过滤器。

        Returns:
            str: 过滤器字符串
        """
        return self.config.MeritShop_Filter.strip()

    # 2025-08-14 新 UI
    @cached_property
    def shop_merit_items(self):
        """加载功勋商店商品模板和配置。

        Returns:
            ShopItemGrid: 商店商品网格对象
        """
        shop_grid = self.shop_grid
        shop_merit_items = ShopItemGrid_250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(18, 121, 85, 150),
        )
        shop_merit_items.load_template_folder(self.shop_template_folder)
        shop_merit_items.load_cost_template_folder('./assets/shop/cost')
        return shop_merit_items

    def shop_items(self):
        """获取商店商品网格的统一接口。

        所有商店共享相同的属性名。如存在服务器语言差异，
        参考 shop_guild/medal 的 @Config 用法。

        Returns:
            ShopItemGrid: 商店商品网格
        """
        return self.shop_merit_items

    def shop_currency(self):
        """OCR 识别功勋商店货币数量。

        通过状态检测获取当前功勋余额并记录日志。

        Returns:
            int: 功勋数量
        """
        self._currency = self.status_get_merit()
        logger.info(f'Merit: {self._currency}')
        return self._currency

    def run(self):
        """运行功勋商店购买流程。

        Pages: in: page_shop (merit shop tab)

        按照过滤器配置购买功勋商店商品，支持刷新。
        """
        # 过滤器为空时直接退出
        if not self.shop_filter:
            return

        # 调用时应已在功勋商店界面
        logger.hr('Merit Shop', level=1)

        # 执行购买操作，启用刷新时最多尝试 2 次
        refresh = self.config.MeritShop_Refresh
        for _ in range(2):
            success = self.shop_buy()
            if not success:
                break
            if refresh and self.shop_refresh():
                continue
            break
