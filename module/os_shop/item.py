from typing import List
import module.config.server as server
from module.logger import logger
from module.ocr.ocr import DigitYuv, Ocr
from module.statistics.item import Item, ItemGrid


class PriceOcr(DigitYuv):
    """商店价格 OCR 识别器。

    修正常见 OCR 错误：I→1, D→0, S→5, B→8，
    处理前导零的情况。
    """

    def after_process(self, result):
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')

        prev = result
        if result.startswith('0'):
            result = '1' + result
            logger.warning(f'OS shop amount {prev} is revised to {result}')

        result = super().after_process(result)
        return result


class CounterOcr(Ocr):
    """商店计数器 OCR 识别器。

    识别形如 `14/15` 的计数器文本，返回当前值和总值。
    """

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789/IDSB',
                 name=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')
        return result

    def ocr(self, image, direct_ocr=False):
        """识别计数器文本，如 `14/15`，返回 [当前值, 总值]。

        Args:
            image: 待识别的图像。
            direct_ocr: 是否直接进行 OCR 识别。

        Returns:
            list[list[int]]: 识别结果列表，每个元素为 [当前值, 总值]。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if isinstance(result_list, list):
            parsed = []
            for i in result_list:
                if not i or '/' not in i:
                    logger.warning(f'Invalid OCR result format: {i}')
                    parsed.append([0, 0])
                    continue

                parts = i.split('/')
                if len(parts) != 2:
                    logger.warning(f'Invalid counter format: {i}')
                    parsed.append([0, 0])
                    continue
                parsed.append([int(j) for j in parts])

            return parsed
        else:
            if not result_list or '/' not in result_list:
                logger.warning(f'Invalid OCR result: {result_list}')
                return [0, 0]

            parts = result_list.split('/')
            if len(parts) != 2:
                logger.warning(f'Invalid counter format: {result_list}')
                return [0, 0]

            return [int(i) for i in parts]


# 根据服务器选择不同的价格 OCR 配置
COUNTER_OCR = CounterOcr([], threshold=96, name='Counter_ocr')
if server.server in ['jp']:
    PRICE_OCR = PriceOcr([], letter=(245, 214, 58), threshold=32, name='Price_ocr')
else:
    PRICE_OCR = PriceOcr([], letter=(255, 223, 57), threshold=32, name='Price_ocr')


class OSShopItem(Item):
    """大世界商店物品类。

    扩展基础物品类，增加商店索引、滚动位置、库存计数等属性。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shop_index = None
        self._scroll_pos = None
        self.total_count = -1
        self.count = -1

    @property
    def shop_index(self):
        """获取商店索引。"""
        return self._shop_index

    @shop_index.setter
    def shop_index(self, value):
        self._shop_index = value

    @property
    def scroll_pos(self):
        """获取滚动位置。"""
        return self._scroll_pos

    @scroll_pos.setter
    def scroll_pos(self, value):
        self._scroll_pos = value

    def is_known_item(self) -> bool:
        """判断是否为已知物品。

        排除默认物品、空物品和纯数字名称的物品。

        Returns:
            bool: 是已知物品返回 True，否则返回 False。
        """
        if self.name == 'DefaultItem':
            return False
        elif 'Empty' in self.name:
            return False
        elif self.name.isdigit():
            return False
        else:
            return True

    def __str__(self):
        if self.name != 'DefaultItem' and self.cost == 'DefaultCost':
            name = f'{self.name}_x{self.amount}'
        elif self.name == 'DefaultItem' and self.cost != 'DefaultCost':
            name = f'{self.cost}_x{self.price}'
        else:
            name = f'{self.name}_{self.amount}x{self.count}_{self.cost}_{self.price}'

        if self.tag is not None:
            name = f'{name}_{self.tag}'

        return name

    def __eq__(self, other):
        return id(self) == id(other)


class OSShopItemGrid(ItemGrid):
    """大世界商店物品网格类。

    支持物品识别、计数器 OCR、商店索引和滚动位置记录。
    """

    item_class = OSShopItem

    def __init__(self, grids, templates, template_area=(40, 21, 89, 70), amount_area=(60, 71, 91, 92),
                 cost_area=(6, 123, 84, 166), price_area=(52, 132, 132, 156), tag_area=(81, 4, 91, 8),
                 counter_area=(85, 170, 134, 186)):
        super().__init__(grids, templates, template_area, amount_area, cost_area, price_area, tag_area)
        self.counter_ocr = COUNTER_OCR
        self.price_ocr = PRICE_OCR
        self.counter_area = counter_area

    def predict(self, image, counter=False, shop_index=None, scroll_pos=None) -> List[OSShopItem]:
        """预测图像中的商店物品。

        识别物品的名称、数量、成本和价格，可选择性地识别计数器、
        商店索引和滚动位置。

        Args:
            image: 待识别的图像。
            counter: 是否识别物品计数器。
            shop_index: 商店索引，用于记录物品所在商店。
            scroll_pos: 滚动位置，用于记录物品在滚动条中的位置。

        Returns:
            list[OSShopItem]: 识别到的物品列表。
        """
        super().predict(image, name=True, amount=True, cost=True, price=True)
        if counter and len(self.items):
            counter_list = [item.crop(self.counter_area) for item in self.items]
            counter_list = self.counter_ocr.ocr(counter_list, direct_ocr=True)
            for i, t in zip(self.items, counter_list):
                i.count, i.total_count = t

        if isinstance(shop_index, int) and isinstance(scroll_pos, float) and len(self.items):
            for i in self.items:
                i.shop_index = shop_index
                i.scroll_pos = scroll_pos

        return self.items
