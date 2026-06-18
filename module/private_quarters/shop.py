import re

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.filter import Filter
from module.logger import logger
from module.private_quarters.clerk import PQShopClerk
from module.private_quarters.status import PQStatus, OCR_SHOP_PRICE
from module.statistics.item import ItemGrid

FILTER_REGEX = re.compile(
    '^(gift|furn|misc'
    ')'

    '(sirius'
    '|cake|roses'
    ')'

    '([1-9]+)?$',
    flags=re.IGNORECASE)
FILTER_ATTR = ('group', 'sub_genre', 'tier')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


class PQShopItemGrid(ItemGrid):
    def predict(self, image, name=True, amount=True, cost=False, price=False, tag=False):
        """
        识别商品列表并为每个商品添加分组/子类/层级属性，用于过滤。

        通过正则表达式从商品名称中提取 group、sub_genre、tier 三个属性。

        Args:
            image: 截图图像
            name (bool): 是否识别名称
            amount (bool): 是否识别数量
            cost (bool): 是否识别消耗
            price (bool): 是否识别价格
            tag (bool): 是否识别标签

        Returns:
            list[Item]: 带有额外过滤属性的商品列表
        """
        super().predict(image, name, amount, cost, price, tag)

        for item in self.items:
            # 初始化默认值
            item.group, item.sub_genre, item.tier = None, None, None

            # 通过正则表达式快速填充过滤属性
            name = item.name
            result = re.search(FILTER_REGEX, name)
            if result:
                item.group, item.sub_genre, item.tier = \
                    [group.lower()
                     if group is not None else None
                     for group in result.groups()]
            else:
                continue

        return self.items


class PQShop(PQShopClerk, PQStatus):
    gems = 0
    shop_template_folder = './assets/shop/private_quarters'

    @cached_property
    def shop_filter(self):
        """
        根据配置生成商品过滤字符串。

        Returns:
            str: 过滤条件，如 'GiftRoses > GiftCake'
        """
        list_filter = []
        if self.config.PrivateQuarters_BuyRoses:
            list_filter.append('GiftRoses')
        if self.config.PrivateQuarters_BuyCake:
            list_filter.append('GiftCake')

        return ' > '.join(list_filter).strip()

    @cached_property
    def shop_grid(self):
        """
        商店商品网格布局（4 列 1 行）。

        Returns:
            ButtonGrid: 商品网格
        """
        shop_grid = ButtonGrid(
            origin=(290, 215), delta=(230, 0), button_shape=(96, 96), grid_shape=(4, 1),
            name='PRIVATE_QUARTERS_BUTTON_GRID_ITEM')
        return shop_grid

    @cached_property
    def shop_private_quarters_items(self):
        """
        私人宿舍商店商品网格，含模板匹配和 OCR 价格识别。

        Returns:
            PQShopItemGrid: 商品网格实例
        """
        shop_grid = self.shop_grid
        shop_private_quarters_items = PQShopItemGrid(shop_grid, templates={},
                                                     cost_area=(-52, 330, -26, 353), price_area=(-26, 331, 36, 357))
        shop_private_quarters_items.price_ocr = OCR_SHOP_PRICE
        shop_private_quarters_items.load_template_folder(self.shop_template_folder)
        shop_private_quarters_items.load_cost_template_folder('./assets/shop/private_quarters_cost')
        return shop_private_quarters_items

    def shop_items(self):
        """
        获取商店商品网格实例。

        若存在服务器语言差异，参考 shop_guild/medal 的 @Config 方式。

        Returns:
            PQShopItemGrid: 商品网格实例
        """
        return self.shop_private_quarters_items

    def shop_currency(self):
        """
        OCR 识别商店货币（金币和钻石）并更新内部状态。

        Pages:
            in: 私人宿舍商店页
        """
        self._currency = self.status_get_gold_coins()
        self.gems = self.status_get_gems()
        logger.info(f'Gold coins: {self._currency}, Gems: {self.gems}')

    def shop_check_item(self, item):
        """
        检查商品是否可购买（余额是否充足）。

        玫瑰需要 24000+ 金币，蛋糕需要 210+ 钻石。

        Args:
            item: 待检查的商品

        Returns:
            bool: 是否可购买
        """
        if self.config.PrivateQuarters_BuyRoses:
            if item.sub_genre == 'roses':
                if 24000 > self._currency:
                    return False
                return True

        if self.config.PrivateQuarters_BuyCake:
            if item.sub_genre == 'cake':
                if 210 > self.gems:
                    return False
                return True

        return False

    def shop_get_item_to_buy(self, items):
        """
        从商品列表中筛选出第一个可购买的商品。

        Args:
            items (list[Item]): 商品列表

        Returns:
            Item: 待购买的商品，无可买项时返回 None
        """
        # 加载过滤条件，应用过滤，返回第一个结果
        FILTER.load(self.shop_filter)
        filtered = FILTER.apply(items, self.shop_check_item)

        if not filtered:
            return None
        logger.attr('Item_sort', ' > '.join([str(item) for item in filtered]))

        return filtered[0]
