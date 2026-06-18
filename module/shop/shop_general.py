from module.base.decorator import cached_property
from module.logger import logger
from module.shop.base import ShopItemGrid, ShopItemGrid_250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus
from module.shop.ui import ShopUI
from module.ui.page import page_meowfficer


class GeneralShop_250814(ShopClerk, ShopUI, ShopStatus):
    """通用商店处理器 (2025-08-14 新 UI)。

    Pages: in: page_shop (general shop tab)

    支持金币和钻石两种货币购买，可配置是否允许使用钻石。
    """

    gems = 0
    shop_template_folder = './assets/shop/general'

    @cached_property
    def shop_filter(self):
        """获取通用商店过滤器。

        Returns:
            str: 过滤器字符串
        """
        return self.config.GeneralShop_Filter.strip()

    # 2025-08-14 新 UI
    @cached_property
    def shop_general_items(self):
        """加载通用商店商品模板和配置。

        Returns:
            ShopItemGrid_250814: 商店商品网格对象
        """
        shop_grid = self.shop_grid

        shop_general_items = ShopItemGrid_250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(14, 121, 85, 150),
        )
        shop_general_items.load_template_folder(self.shop_template_folder)
        shop_general_items.load_cost_template_folder('./assets/shop/cost')
        return shop_general_items

    def shop_items(self):
        """获取商店商品网格的统一接口。

        所有商店共享相同的属性名。如存在服务器语言差异，
        参考 shop_guild/medal 的 @Config 用法。

        Returns:
            ShopItemGrid_250814: 商店商品网格
        """
        return self.shop_general_items

    currency_rechecked = 0

    def shop_currency(self):
        """OCR 识别通用商店货币数量（金币和钻石）。

        通过状态检测获取当前金币和钻石余额并记录日志。

        Returns:
            int: 金币数量
        """
        while 1:
            self._currency = self.status_get_gold_coins()
            self.gems = self.status_get_gems()
            logger.info(f'Gold coins: {self._currency}, Gems: {self.gems}')

            if self.currency_rechecked >= 3:
                logger.warning('Failed to handle fix currency bug in general shop, skip')
                break

            break

        return self._currency

    def shop_check_item(self, item):
        """检查商品是否可购买（基于货币余额）。

        Args:
            item: 待检查的商品对象

        Returns:
            bool: 是否可购买
        """
        if item.cost == 'Coins':
            if item.price > self._currency:
                return False
            return True

        if self.config.GeneralShop_UseGems:
            if item.cost == 'Gems':
                if item.price > self.gems:
                    return False
                return True

        return False

    def shop_check_custom_item(self, item):
        """检查自定义商品是否满足特定购买条件。

        处理需要特殊判断的商品，如物资超过 ConsumeCoins 阈值时
        自动购买消耗物资的商品，或购买装备外观箱。

        Args:
            item: 待检查的商品对象

        Returns:
            bool: 是否为满足条件的自定义商品
        """
        consume_coins = self.config.GeneralShop_ConsumeCoins
        # 阈值验证：必须 > 0 且 <= 600000
        # 类型安全由 run() → _validate_config_values() 中的规范化保证
        if consume_coins > 0 and consume_coins <= 600000:
            if self._currency >= consume_coins:
                if item.cost == 'Coins':
                    return True

        if self.config.GeneralShop_BuySkinBox:
            if (not item.is_known_item()) and item.amount == 1 and item.cost == 'Coins' and item.price == 7000:
                # 装备外观箱无法通过模板匹配识别（颜色和外观持续变化）
                logger.info(f'Item {item} is considered to be an equip skin box')
                if self._currency >= item.price:
                    return True

        return False

    @staticmethod
    def _normalize_threshold(value, name):
        """验证并修正阈值配置值。

        检测值是否为有效的 int 类型（排除 bool）且在 0-600000 范围内，
        无效则返回 0 并记录警告。有效范围：0 表示关闭功能，1-600000 表示启用。

        Args:
            value: 待验证的阈值。
            name: 配置项名称（用于日志）。

        Returns:
            int: 规范化后的阈值（0 或有效范围内的 int）。
        """
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 600000:
            return value
        logger.warning(f'{name}={value}, invalid value (expected int in 0-600000), '
                       f'set to 0 to disable feature')
        return 0

    def _meowfficer_overflow_buy(self):
        """金币溢出时自动购买猫箱。

        当金币超过 OverflowCoins 阈值时，导航到指挥喵界面购买猫箱，
        直到金币降至阈值以下或达到每日15个购买限制。
        阈值范围 1-600000，超出范围视为无效并跳过功能。

        Pages: in: page_shop, out: page_main
        """
        overflow_coins = self.config.GeneralShop_OverflowCoins

        # 阈值检查：<= 0 表示功能关闭
        # 类型安全由 run() → _validate_config_values() 中的规范化保证
        if overflow_coins <= 0:
            return

        # 重新OCR识别金币（购买消耗物资后金币可能已变化）
        self.shop_currency()
        if self._currency <= overflow_coins:
            logger.info(f'Gold coins {self._currency} <= OverflowCoins {overflow_coins}, skip meowfficer overflow buy')
            return

        logger.hr('Meowfficer overflow buy', level=1)
        logger.info(f'Gold coins {self._currency} > OverflowCoins {overflow_coins}, trigger meowfficer overflow buy')

        # 导航到指挥喵界面
        self.ui_goto(page_meowfficer)

        # 等待界面加载完成
        from module.meowfficer.buy import MeowfficerBuy
        meow = MeowfficerBuy(config=self.config, device=self.device)
        meow.wait_meowfficer_buttons()

        # 执行猫箱溢出购买
        meow.meow_overflow_buy(overflow_coins=overflow_coins)

        # 返回主界面
        self.ui_goto_main()

    def _validate_config_values(self):
        """验证并修正配置值。

        检测 ConsumeCoins 和 OverflowCoins 的异常值（不在 0-600000 范围内，
        或类型非 int（如旧数据中的 bool）），并将异常值强制设置为零。

        有效范围：0 表示关闭功能，1-600000 表示启用功能并设置阈值。
        必须为 int 类型：Python 中 bool 是 int 的子类，True > 0 恒为 True，
        旧数据中的布尔值会导致消费溢出逻辑永远触发。
        """
        self.config.GeneralShop_ConsumeCoins = self._normalize_threshold(
            self.config.GeneralShop_ConsumeCoins, 'ConsumeCoins')
        self.config.GeneralShop_OverflowCoins = self._normalize_threshold(
            self.config.GeneralShop_OverflowCoins, 'OverflowCoins')

    def run(self):
        """运行通用商店购买流程。

        Pages: in: page_shop (general shop tab)

        按照过滤器配置购买通用商店商品，支持刷新。
        购买完成后，若金币超过溢出阈值则自动购买猫箱。
        """
        # 配置值验证：检测并修正异常值
        self._validate_config_values()

        if not self.shop_filter:
            return

        logger.hr('General Shop', level=1)

        # 执行购买操作，启用刷新时最多尝试 2 次
        refresh = self.config.GeneralShop_Refresh
        for _ in range(2):
            success = self.shop_buy()
            if not success:
                break
            if refresh and self.shop_refresh():
                continue
            break

        # 金币溢出购买猫箱
        self._meowfficer_overflow_buy()
