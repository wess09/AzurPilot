import re

import numpy as np

from module.base.button import ButtonGrid
from module.base.decorator import Config, cached_property
from module.base.filter import Filter
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_3, GET_SHIP
from module.logger import logger
from module.shop.assets import *
from module.shop.shop_select_globals import *
from module.statistics.item import Item, ItemGrid
from module.tactical.tactical_class import Book
from module.ui.ui import UI

FILTER_REGEX = re.compile(
    '^(array|book|box|bulin|cat'
    '|chip|coin|cube|drill|food'
    '|plate|retrofit|pr|dr|specializedcore'
    '|logger|tuning'
    '|hecombatplan|fragment|hiddenzonedatalogger'
    '|albacore|bataan|bearn|bluegill|carabiniere|casablanca|contedicavour|dukeofyork'
    '|echo|eldridge|gangut|glorious|grenville|hibiki|hunter|icarus'
    '|kawakaze|kinggeorgev|kinu|kuroshio|lagalissonniere|lemalinmuse|letemeraire|littorio'
    '|mikuma|minsk|newcastle|oyashio|quincy|ryuujou|sanjuan|sheffieldmuse'
    '|trento|u37|vincennes|z24|z26|z28|z36'
    ')'

    '(neptune|monarch|ibuki|izumo|roon|saintlouis'
    '|seattle|georgia|kitakaze|azuma|friedrich'
    '|gascogne|champagne|cheshire|drake|mainz|odin'
    '|anchorage|hakuryu|agir|august|marcopolo'
    '|plymouth|rupprecht|harbin|chkalov|brest'
    '|red|blue|yellow'
    '|general|gun|torpedo|antiair|plane|wild'
    '|dd|cl|bb|cv'
    '|iris|sardegna'
    '|abyssal|archive|obscure|unlock'
    '|combat|offense|survival)?'

    '(s[1-5]|t[1-6])?$',
    flags=re.IGNORECASE)
FILTER_ATTR = ('group', 'sub_genre', 'tier')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


class ShopItem_250814(Item):
    """
    未售出的 ship_T2 的计算结果为 0.36，因此取 0.3 作为阈值，
    已售出商品的结果 < 0.2。
    """

    def predict_valid(self):
        mean = np.mean(np.max(self.image, axis=2) > 139)
        return mean > 0.3


class ShopItemGrid(ItemGrid):
    def predict(self, image, name=True, amount=True, cost=False, price=False, tag=False):
        """
        预测商店物品并填充过滤所需的扩展属性。

        在基类预测结果之上，通过正则解析物品名称，为每个 Item
        追加 group、sub_genre、tier 三个属性，供 FILTER 进行
        匹配和排序。对于书籍类物品，会额外执行模板匹配以修正
        颜色和等级的误识别。

        Args:
            image: 商店截图。
            name: 是否识别物品名称。
            amount: 是否识别物品数量。
            cost: 是否识别物品消耗。
            price: 是否识别物品价格。
            tag: 是否识别物品标签。

        Returns:
            list[Item]: 带有扩展属性的物品列表。
        """
        super().predict(image, name, amount, cost, price, tag)
        for item in self.items:
            # 设置默认值
            item.group, item.sub_genre, item.tier = None, None, None

            # 使用正则表达式快速填充新属性
            name = item.name
            result = re.search(FILTER_REGEX, name)
            if result:
                item.group, item.sub_genre, item.tier = \
                [group.lower()
                 if group is not None else None
                 for group in result.groups()]
            else:
                continue

            # 书籍的颜色和/或等级有时会被误识别
            # 使用 Book 类进行第二次模板匹配
            if item.group == 'book':
                book = Book(image, item._button)
                if item.sub_genre is not None:
                    item.sub_genre = book.genre_str
                item.tier = book.tier_str.lower()
                item.name = ''.join(
                    [part.title()
                     if part is not None
                     else ''
                     for part in [item.group, item.sub_genre, item.tier]])

        return self.items


class ShopItemGrid_250814(ShopItemGrid):
    item_class = ShopItem_250814

    def get_soldout_count(self, image):
        """
        统计商店中已售罄的物品数量。

        遍历所有网格位置，通过 ShopItem_250814 的有效性判断
        区分已售罄和在售物品。已售罄物品的像素亮度较低，
        is_valid 返回 False。

        Args:
            image: 商店截图。

        Returns:
            int: 售罄物品数量。
        """
        count = 0
        for button in self.grids.buttons:
            item = self.item_class(image, button)
            if not item.is_valid:
                count += 1
        logger.attr('Item soldout', count)
        return count


class ShopBase(UI):
    """
    商店系统基类。

    提供商店物品检测、过滤、购买决策的通用框架。
    子类重写 shop_items()、shop_filter、shop_currency() 等方法
    以适配不同商店的布局和货币类型。

    Pages: in: page_shop
    """
    _currency = 0
    shop_template_folder = ''

    @cached_property
    def shop_filter(self):
        """
        获取商店物品过滤器字符串。

        子类重写此属性以提供特定商店的过滤规则，
        格式由 FILTER_REGEX 定义，支持 group/sub_genre/tier 三级匹配。

        Returns:
            str: 商店过滤器字符串，空字符串表示不过滤。
        """
        return ''

    @cached_property
    @Config.when(SERVER=None)
    def shop_grid(self):
        """
        获取商店物品网格布局。

        2025-08-14 新版 UI 布局，5x2 网格排列。
        各服务器可重写此属性以适配不同布局。

        Returns:
            ButtonGrid: 商店物品网格，每个格子 64x64 像素。
        """
        shop_grid = ButtonGrid(
            origin=(265, 238), delta=(169, 223), button_shape=(64, 64), grid_shape=(5, 2), name='SHOP_GRID')
        return shop_grid

    def shop_items(self):
        """
        获取当前商店的物品网格对象。

        基类返回 None，子类必须重写以返回实际的 ShopItemGrid 实例。

        Returns:
            ShopItemGrid | None: 商店物品网格，基类默认返回 None。
        """
        return None

    def shop_currency(self):
        """
        获取当前持有的商店货币数量。

        子类可重写此方法以从 OCR 或其他途径读取实际货币值。

        Returns:
            int: 当前货币数量。
        """
        return self._currency

    def shop_has_loaded(self, items):
        """
        各子类商店的自定义加载完成检查步骤。

        例如 ShopMedal 初始会显示默认物品和默认价格，
        需要等待实际数据加载完毕。基类默认返回 True。

        Args:
            items: 当前已检测到的物品列表。

        Returns:
            bool: 商店是否已完全加载。
        """
        return True

    def shop_detect_items(self, image=None):
        """
        在图像上检测商店物品，用于测试目的。

        对指定截图执行物品预测，并将检测结果按行输出到日志。
        支持模板提取模式（SHOP_EXTRACT_TEMPLATE）。

        Args:
            image: 商店截图，为 None 时使用当前设备截图。

        Returns:
            list[Item]: 检测到的物品列表，未检测到时返回空列表。
        """
        if image is None:
            image = self.device.image

        # 获取 ShopItemGrid
        shop_items = self.shop_items()
        if shop_items is None:
            logger.warning('Expected type \'ShopItemGrid\' but was None')
            return []

        if self.config.SHOP_EXTRACT_TEMPLATE:
            if self.shop_template_folder:
                logger.info(f'Extract item templates to {self.shop_template_folder}')
                shop_items.extract_template(image, self.shop_template_folder)
            else:
                logger.warning('SHOP_EXTRACT_TEMPLATE enabled but shop_template_folder is not set, skip extracting')

        shop_items.predict(
            image,
            name=True,
            amount=False,
            cost=True,
            price=True,
            tag=False
        )

        # 记录预测物品的最终结果
        items = shop_items.items
        grids = shop_items.grids
        if len(items):
            min_row = grids[0, 0].area[1]
            row = [str(item) for item in items if item.button[1] == min_row]
            logger.info(f'Shop row 1: {row}')
            row = [str(item) for item in items if item.button[1] != min_row]
            logger.info(f'Shop row 2: {row}')
            return items
        else:
            logger.info('No shop items found')
            return []

    def shop_obstruct_handle(self):
        """
        移除商店视图中的遮挡物（如果存在）。

        处理获得舰船、获得物品、锁定确认等弹窗，
        点击安全区域关闭遮挡层。用于 shop_get_items 的截图循环中。

        Returns:
            bool: 是否存在并处理了遮挡物。
        """
        # 处理商店遮挡物
        if self.appear(GET_SHIP, interval=1):
            logger.info(f'Shop obstruct: {GET_SHIP} -> {SHOP_CLICK_SAFE_AREA}')
            self.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        # 锁定新获得的舰船
        if self.handle_popup_confirm('SHOP_OBSTRUCT'):
            return True
        if self.appear(GET_ITEMS_1, interval=1):
            logger.info(f'Shop obstruct: {GET_ITEMS_1} -> {SHOP_CLICK_SAFE_AREA}')
            self.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ITEMS_3, interval=1):
            logger.info(f'Shop obstruct: {GET_ITEMS_3} -> {SHOP_CLICK_SAFE_AREA}')
            self.device.click(SHOP_CLICK_SAFE_AREA)
            return True

        return False

    def shop_get_items(self, skip_first_screenshot=True):
        """
        获取当前商店页面中的所有物品。

        通过截图-检测循环等待物品加载完毕，同时处理遮挡弹窗。
        当已识别物品数量稳定且 shop_has_loaded 返回 True 时结束。

        Args:
            skip_first_screenshot: 是否跳过首次截图，复用上一状态循环的截图。

        Returns:
            list[Item]: 已加载的物品列表，无物品时返回空列表。
        """
        # 获取 ShopItemGrid
        shop_items = self.shop_items()
        if shop_items is None:
            logger.warning('Expected type \'ShopItemGrid\' but was None')
            return []

        # 循环预测以确保物品已加载且可被准确读取
        record = 0
        timeout = Timer(3, count=9).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.shop_obstruct_handle():
                timeout.reset()
                continue

            if self.config.SHOP_EXTRACT_TEMPLATE:
                if self.shop_template_folder:
                    logger.info(f'Extract item templates to {self.shop_template_folder}')
                    shop_items.extract_template(self.device.image, self.shop_template_folder)
                else:
                    logger.warning('SHOP_EXTRACT_TEMPLATE enabled but shop_template_folder is not set, skip extracting')

            shop_items.predict(
                self.device.image,
                name=True,
                amount=False,
                cost=True,
                price=True,
                tag=False
            )

            if timeout.reached():
                logger.warning('Items loading timeout; continue and assumed has loaded')
                break

            # 检查未加载的物品，因为游戏加载物品速度较慢
            items = shop_items.items
            known = len([item for item in items if item.is_known_item])
            logger.attr('Item detected', known)
            if known == 0 or known != record:
                record = known
                continue
            else:
                record = known

            # 结束条件
            if self.shop_has_loaded(items):
                break

        # 记录预测物品的最终结果
        items = shop_items.items
        grids = shop_items.grids
        if len(items):
            min_row = grids[0, 0].area[1]
            row = [str(item) for item in items if item.button[1] == min_row]
            logger.info(f'Shop row 1: {row}')
            row = [str(item) for item in items if item.button[1] != min_row]
            logger.info(f'Shop row 2: {row}')
            return items
        else:
            logger.info('No shop items found')
            return []

    def shop_check_item(self, item):
        """
        检查物品是否满足购买条件（货币足够）。

        子类中重写此方法以实现特定的物品检查逻辑，
        如额外的库存限制、优先级判断等。被过滤器 FILTER.apply 调用。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 物品是否可以购买。
        """
        if item.price > self._currency:
            return False
        return True

    def shop_check_custom_item(self, item):
        """
        子类中重写此方法以实现自定义物品检查逻辑，不受过滤器字符串限制。

        在 shop_get_item_to_buy 中优先于过滤器检查执行，
        适用于无法通过名称正则匹配的特殊物品。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 物品是否可以购买。
        """
        return False

    def shop_get_item_to_buy(self, items):
        """
        从物品列表中选出下一个待购买的物品。

        优先检查自定义物品（无模板/过滤器支持），
        然后应用过滤器字符串进行匹配和排序，返回优先级最高的物品。

        Args:
            items: 从 shop_get_items 获取的物品列表。

        Returns:
            Item: 待购买的物品，无可用物品时返回 None。
        """
        # 首先扫描自定义物品，因其没有模板或过滤器支持
        for item in items:
            if self.shop_check_custom_item(item):
                return item

        # 然后加载选择、应用过滤器，并返回结果中的第一个物品
        FILTER.load(self.shop_filter)
        filtered = FILTER.apply(items, self.shop_check_item)

        if not filtered:
            return None
        logger.attr('Item_sort', ' > '.join([str(item) for item in filtered]))

        return filtered[0]
