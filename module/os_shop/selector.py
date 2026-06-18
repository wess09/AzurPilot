"""大世界商店物品筛选与选择逻辑。

基于正则表达式解析商品类型，并根据用户配置的过滤器决定购买行为。
支持明石商店过滤和 OS 商店预设两种过滤模式。
"""
import re
from typing import List
from module.config.config_generated import GeneratedConfig
from module.os_shop.preset import *
from module.os_shop.item import OSShopItem as Item
from module.base.filter import Filter

# 物品名称正则匹配规则
FILTER_REGEX = re.compile(
    '^(actionpoint|crystallizedheatresistantsteel|developmentmaterial'
    '|energystoragedevice|geardesignplan|gearpart|logger|metaredbook'
    '|nanoceramicalloy|neuroplasticprostheticarm|ordnancetestingreport'
    '|platerandom|purplecoins|repairpack|supercavitationgenerator|tuningsample'
    '|tuning)'

    '(20|50|100|prototype|specialized|abyssal|obscure|full2|full|triple2|triple|2'
    '|combat|offence|survival)?'

    '(t[1-6])?$',
    flags=re.IGNORECASE)
FILTER_ATTR = ('group', 'sub_genre', 'tier')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


class Selector():
    """商店物品选择器基类。

    提供物品预处理、金币检查、物品计数验证和过滤功能。
    """

    def pretreatment(self, items) -> List[Item]:
        """预处理物品列表，解析物品名称中的类型信息。

        通过正则表达式提取物品的 group、sub_genre 和 tier 属性。

        Args:
            items: 待预处理的物品列表。

        Returns:
            list[Item]: 预处理后的物品列表，仅包含可解析的物品。
        """
        _items = []
        for item in items:
            item.group, item.sub_genre, item.tier = None, None, None
            result = re.search(FILTER_REGEX, item.name.lower())
            if result:
                item.group, item.sub_genre, item.tier = [group.lower()
                                                         if group is not None else None
                                                         for group in result.groups()]
                _items.append(item)

        return _items

    def enough_coins_in_akashi(self, item) -> bool:
        """检查明石商店是否有足够金币购买物品。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 金币足够返回 True，否则返回 False。
        """
        if item.cost == 'YellowCoins' and item.price <= self._shop_yellow_coins:
            return True
        if item.cost == 'PurpleCoins' and item.price <= self._shop_purple_coins:
            return True

        return False

    def check_cl1_purple_coins(self, item) -> bool:
        """检查 CL1 模式下是否允许购买紫币。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 允许购买返回 True，CL1 模式下购买紫币返回 False。
        """
        return not (self.is_cl1_enabled and item.name == 'PurpleCoins')

    def check_item_count(self, item) -> bool:
        """检查物品计数是否有效。

        Args:
            item: 待检查的物品。

        Returns:
            bool: 计数有效（当前数量 >= 1，总数量 >= 1，当前不超过总数）返回 True。
        """
        return item.count >= 1 and item.total_count >= 1 and item.count <= item.total_count

    def items_filter_in_akashi_shop(self, items) -> List[Item]:
        """过滤明石商店中可购买的物品。

        根据 CL1 模式或通用配置过滤物品，并检查金币是否充足。

        Args:
            items: 待过滤的物品列表。

        Returns:
            list[Item]: 可购买的物品列表。
        """
        items = self.pretreatment(items)
        if getattr(self, 'is_in_task_cl1_leveling', False) and getattr(self, 'is_cl1_enabled', False):
            parser = self.config.OpsiHazard1Leveling_Cl1Filter
            if not parser:
                parser = 'ActionPoint'
        else:
            parser = self.config.OpsiGeneral_AkashiShopFilter
            if not parser.strip():
                parser = GeneratedConfig.OpsiGeneral_AkashiShopFilter
        FILTER.load(parser)
        return FILTER.applys(items, funcs=[self.enough_coins_in_akashi])

    def items_filter_in_os_shop(self, items) -> List[Item]:
        """过滤 OS 商店中可购买的物品。

        根据预设或自定义过滤器筛选物品，并检查 CL1 紫币限制和物品计数。

        Args:
            items: 待过滤的物品列表。

        Returns:
            list[Item]: 可购买的物品列表。
        """
        items = self.pretreatment(items)
        preset = self.config.OpsiShop_PresetFilter
        parser = ''
        if preset == 'custom':
            parser = self.config.OpsiShop_CustomFilter
            if not parser.strip():
                parser = OS_SHOP[GeneratedConfig.OpsiShop_PresetFilter]
        else:
            parser = OS_SHOP[preset]
        FILTER.load(parser)
        return FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.check_item_count])
