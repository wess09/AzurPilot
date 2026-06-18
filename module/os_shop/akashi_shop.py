from typing import List
from module.base.button import Button, ButtonGrid
from module.base.decorator import Config, cached_property
from module.logger import logger
from module.os_handler.map_event import MapEventHandler
from module.os_handler.os_status import OSStatus
from module.os_shop.selector import Selector
from module.os_shop.ui import OSShopUI
from module.os_shop.item import OSShopItem as Item, OSShopItemGrid as ItemGrid


class AkashiShop(OSStatus, OSShopUI, Selector, MapEventHandler):
    @cached_property
    @Config.when(SERVER='tw')
    def os_akashi_shop_items(self) -> ItemGrid:
        """获取明石商店物品网格（台服）。

        Returns:
            ItemGrid: 台服明石商店的物品网格配置。
        """
        shop_grid = ButtonGrid(
            origin=(233, 224), delta=(193, 228), button_shape=(98, 98), grid_shape=(4, 2), name='SHOP_GRID')
        shop_items = ItemGrid(
            shop_grid, templates={}, amount_area=(60, 74, 96, 95),
            counter_area=(85, 170, 134, 186), price_area=(52, 132, 132, 165)
        )
        shop_items.load_template_folder('./assets/shop/os')
        shop_items.load_cost_template_folder('./assets/shop/os_cost')
        return shop_items

    @cached_property
    @Config.when(SERVER='en')
    def os_akashi_shop_items(self) -> ItemGrid:
        """获取明石商店物品网格（国际服）。

        Returns:
            ItemGrid: 国际服明石商店的物品网格配置。
        """
        shop_grid = ButtonGrid(
            origin=(231, 222), delta=(190, 224), button_shape=(98, 98), grid_shape=(4, 2), name='SHOP_GRID')
        shop_items = ItemGrid(
            shop_grid, templates={}, amount_area=(60, 74, 96, 95),
            counter_area=(85, 170, 134, 186), price_area=(52, 132, 132, 165)
        )
        shop_items.load_template_folder('./assets/shop/os')
        shop_items.load_cost_template_folder('./assets/shop/os_cost')
        return shop_items

    @cached_property
    @Config.when(SERVER=None)
    def os_akashi_shop_items(self) -> ItemGrid:
        """获取明石商店物品网格（默认/国服）。

        Returns:
            ItemGrid: 默认明石商店的物品网格配置。
        """
        shop_grid = ButtonGrid(
            origin=(233, 224), delta=(193.2, 228), button_shape=(98, 98), grid_shape=(4, 2), name='SHOP_GRID')
        shop_items = ItemGrid(
            shop_grid, templates={}, amount_area=(60, 74, 96, 95),
            counter_area=(85, 170, 134, 186), price_area=(52, 132, 132, 165)
        )
        shop_items.load_template_folder('./assets/shop/os')
        shop_items.load_cost_template_folder('./assets/shop/os_cost')
        return shop_items

    def os_shop_get_items_in_akashi(self) -> List[Item]:
        """识别明石商店中的所有物品。

        通过模板匹配识别当前屏幕上的商店物品，记录每行物品信息。

        Returns:
            list[Item]: 识别到的物品列表，无物品时返回空列表。
        """
        if self.config.SHOP_EXTRACT_TEMPLATE:
            self.os_akashi_shop_items.extract_template(self.device.image, './assets/shop/os')
        self.os_akashi_shop_items.predict(self.device.image)

        items = self.os_akashi_shop_items.items
        if len(items):
            min_row = self.os_akashi_shop_items.grids[0, 0].area[1]
            row = [str(item) for item in items if item.button[1] == min_row]
            logger.info(f'Shop row 1: {row}')
            row = [str(item) for item in items if item.button[1] != min_row]
            logger.info(f'Shop row 2: {row}')
            return items
        else:
            logger.info('No shop items found')
            return []

    def os_shop_get_item_to_buy_in_akashi(self) -> Item:
        """获取明石商店中待购买的物品。

        获取金币信息后识别商店物品，处理商店加载延迟的情况，
        应用过滤器筛选可购买物品。

        Returns:
            Item: 待购买的物品，无可购买物品时返回 None。
        """
        self.os_shop_get_coins()
        items = self.os_shop_get_items_in_akashi()
        # 商店物品不会立即出现，需要确认商店是否为空
        for _ in range(2):
            if not len(items) or any(not item.is_known_item() for item in items):
                logger.warning('Empty akashi shop or empty items, confirming')
                self.device.sleep((0.3, 0.5))
                self.device.screenshot()
                items = self.os_shop_get_items_in_akashi()
                continue
            else:
                items = self.items_filter_in_akashi_shop(items)
                if not len(items):
                    return None
                else:
                    return items.pop()

        return None
