import re

import cv2
import numpy as np

import module.config.server as server

from module.base.utils import color_similarity_2d, color_similar, rgb2luma
from module.logger import logger
from module.ocr.ocr import Ocr, Digit
from module.shop_event.selector import FILTER_REGEX
from module.statistics.item import Item, ItemGrid

ITEM_SHAPE = (63, 63)
GRID_SHAPE = (152, 206)
DELTA_PRICE_BACKGROUND = (14, 164)
DELTA_ITEM = (45, 44, 45 + ITEM_SHAPE[0], 33 + ITEM_SHAPE[1])
DELTA_AMOUNT = (13, 144, 136, 160)
DELTA_PRICE = (28, 164, 128, 193)
DELTA_TAG = (108, 30, 155, 52)
COUNTER_COLOR = (106, 120, 131)
COUNTER_THRESHOLD = 150
COUNTER_TOTALS = (500, 350, 100, 50, 40, 30, 20, 15, 10, 5, 4, 2, 1)
PRICE_THRESHOLD = 230
PRICE_BACKGROUND_COLOR = (61, 78, 91)
UNOBTAINED_TAG_COLOR = (255, 72, 72)
# 角标区域中红底像素占比达到该值即视为“未获得”角标
UNOBTAINED_TAG_RED_RATIO = 0.4
if server.server == 'jp':
    COUNTER_LEFT_STRIP = 54
elif server.server == 'en':
    COUNTER_LEFT_STRIP = 42
else:
    COUNTER_LEFT_STRIP = 70


class CounterOcr(Ocr):
    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128,
                 alphabet='0123456789/IDSB', name=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def pre_process(self, image):
        mask = color_similarity_2d(image, (255, 255, 255))
        brightness = np.min(mask, axis=0)
        match = np.where(brightness < COUNTER_THRESHOLD)[0]
        if len(match):
            left = match[0] + COUNTER_LEFT_STRIP
            total = mask.shape[1]
            if left < total:
                image = image[:, left:]
        image = super().pre_process(image)
        return image

    def after_process(self, result):
        """后处理 OCR 文本，校正易混淆字符并修复缺失斜杠的计数。

        Args:
            result (str): 原始识别字符串。

        Returns:
            str: 校正后的计数文本。
        """
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')
        # 修复类似 "55" -> "5/5"、"2530" -> "25/30" 的无斜杠识别结果
        if result.isdigit() and result not in [str(total) for total in COUNTER_TOTALS]:
            candidates = []
            for total in COUNTER_TOTALS:
                total_str = str(total)
                current_str = result[:-len(total_str)]
                if result.endswith(total_str) and current_str and int(current_str) <= total:
                    candidates.append(f'{current_str}/{total_str}')
            # 例如 "1350" 既可能是 "13/50" 也可能是 "1/350"
            # 存在二义性时保持无效，以便商店扫描器重试
            if len(candidates) == 1:
                result = candidates[0]
        return result

    @staticmethod
    def parse_result(result):
        """解析斜杠分隔的计数字符串为整数对。

        Args:
            result (str):形如 '14/15' 的字符串。

        Returns:
            list[int]: [当前数量, 总数量]，解析失败返回 [0, 0]。
        """
        parts = result.split('/') if result else []
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            logger.warning(f'无效的计数格式: {result}')
            return [0, 0]

        current, total = [int(part) for part in parts]
        if total <= 0 or current > total:
            logger.warning(f'无效的计数值: {result}')
            return [0, 0]
        return [current, total]

    def ocr(self, image, direct_ocr=False):
        """对计数器进行 OCR 识别并解析出 [当前, 总量]。

        Args:
            image (np.ndarray | list[np.ndarray]): 输入图像或图像列表。
            direct_ocr (bool): 是否直接识别。默认为 False。

        Returns:
            list[int] | list[list[int]]: 单图返回 [当前, 总量]，多图返回列表。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if isinstance(result_list, list):
            return [self.parse_result(result) for result in result_list]
        return self.parse_result(result_list)


class PriceOcr(Digit):
    def pre_process(self, image):
        """预处理价格图像，裁切左侧空白。

        Args:
            image (np.ndarray): 原始输入图像。

        Returns:
            np.ndarray: 处理后的二值化图像。
        """
        mask = color_similarity_2d(image, PRICE_BACKGROUND_COLOR)
        brightness = np.min(mask, axis=0)
        match = np.where(brightness < PRICE_THRESHOLD)[0]
        if len(match):
            left = match[0] + 20
            total = mask.shape[1]
            if left < total:
                image = image[:, left:]
        image = super().pre_process(image)
        return image

PRICE_OCR = PriceOcr([], letter=(221, 221, 221), threshold=128, name='Price_ocr')


URPT_PRICE_IN_PT = 150  # 1 URpt costs 150 pt
COIN_PRICE_IN_URPT = 1  # 1 Coin costs 1 URpt
UR_SHIP_PRICES_IN_URPT = [200, 300]  # UR Ships cost 200 or 300 URpt


class EventShopItem(Item):
    IMAGE_SHAPE = ITEM_SHAPE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_ship = False
        self._scroll_pos = None
        self.total_count = -1
        self.count = 1

    def __str__(self):
        name = f'{self.name}_x{self.amount}_{self.count}/{self.total_count}_{self.cost}_x{self.price}'

        if self.tag is not None:
            name = f'{name}_{self.tag}'

        return name

    def predict_valid(self):
        luma = rgb2luma(self.image)
        return np.mean(luma > 127) >= 0.2

    @property
    def scroll_pos(self):
        return self._scroll_pos

    @scroll_pos.setter
    def scroll_pos(self, value):
        """设置商品所在的滚动条位置。

        Args:
            value (float | None): 滚动条相对位置值。
        """
        self._scroll_pos = value

    def __eq__(self, other):
        return id(self) == id(other)

    def correct_name_and_cost(self):
        """根据物品价格和总限购数量校正物品名称和货币消耗类型。"""
        if self.price in UR_SHIP_PRICES_IN_URPT and self.total_count == 1:
            self.name = 'ShipUR'
            self.cost = 'URpt'
            self.is_ship = True
        elif self.price == COIN_PRICE_IN_URPT and self.total_count == 350:
            # URpt 兑换金币
            self.name = 'Coin'
            self.cost = 'URpt'
        else:
            self.cost = 'pt'
            if self.price == 135 and self.total_count == 15:
                self.name = 'EquipSSR'
            elif self.price == 2000:
                if self.total_count == 10:
                    self.name = 'SkinBox'
                elif self.total_count == 4:
                    self.name = 'Meta'
                else:
                    self.name = 'EquipSSR'
            elif self.price == 8000:
                self.name = 'ShipSSR'
                self.is_ship = True
            elif self.price == 10000:
                self.name = 'EquipUR'
            elif self.price == URPT_PRICE_IN_PT and self.total_count == 500:
                self.name = 'URpt'
            elif self.name.isdigit():
                logger.warning(f'[活动商店-物品] 未识别的物品，价格 {self.price}，总数 {self.total_count}，'
                               f'保存图像以便分析。')
                import os
                from module.base.utils import save_image
                os.mkdir('assets/shop/event/new_templates/') if not os.path.exists('assets/shop/event/new_templates/') else None
                save_image(self.image, f'assets/shop/event/new_templates/{self.name}.png')
                # self.name = 'EquipSSR'

    def predict_genre(self):
        """使用正则表达式解析物品名称，填充 group、sub_genre 和 tier 属性。"""
        self.group, self.sub_genre, self.tier = None, None, None

        # 使用正则表达式快速填充新属性
        name = self.name.lower()
        result = re.search(FILTER_REGEX, name)
        if result:
            self.group, self.sub_genre, self.tier = \
            [group.lower()
             if group is not None else None
             for group in result.groups()]


class EventShopItemGrid(ItemGrid):
    item_class = EventShopItem

    def __init__(self,
                 grids,
                 templates,
                 template_area=(0, 0, ITEM_SHAPE[0], ITEM_SHAPE[1]),
                 amount_area=(31, 50, ITEM_SHAPE[0], ITEM_SHAPE[1]),
                 cost_area=(DELTA_PRICE[0] - DELTA_ITEM[0], DELTA_PRICE[1] - DELTA_ITEM[1],
                            DELTA_PRICE[2] - DELTA_ITEM[0], DELTA_PRICE[3] - DELTA_ITEM[1]),
                 price_area=(DELTA_PRICE[0] - DELTA_ITEM[0], DELTA_PRICE[1] - DELTA_ITEM[1],
                             DELTA_PRICE[2] - DELTA_ITEM[0], DELTA_PRICE[3] - DELTA_ITEM[1]),
                 tag_area=(DELTA_TAG[0] - DELTA_ITEM[0], DELTA_TAG[1] - DELTA_ITEM[1],
                           DELTA_TAG[2] - DELTA_ITEM[0], DELTA_TAG[3] - DELTA_ITEM[1]),
                 counter_area=(DELTA_AMOUNT[0] - DELTA_ITEM[0], DELTA_AMOUNT[1] - DELTA_ITEM[1],
                               DELTA_AMOUNT[2] - DELTA_ITEM[0], DELTA_AMOUNT[3] - DELTA_ITEM[1]),
                 ):
        super().__init__(grids, templates, template_area, amount_area, cost_area, price_area, tag_area)
        counter_lang = 'cnocr' if server.server == 'en' else 'azur_lane'
        self.counter_ocr = CounterOcr([], lang=counter_lang, letter=COUNTER_COLOR, name="CounterOcr")
        self.counter_area = counter_area
        self.price_ocr = PRICE_OCR

    def predict_tag(self, image):
        """识别商品角标（如未获得）。

        Args:
            image (np.ndarray): 角标区域图像。

        Returns:
            str | None: 'unobtained' 表示未获得，无对应角标返回 None。
        """
        image = np.array(image)
        color = cv2.mean(image)[:3]
        if color_similar(color1=color, color2=UNOBTAINED_TAG_COLOR, threshold=50):
            return 'unobtained'
        # 国际服角标文字“Unobtained”比“未获得”长，白字把平均色拉浅，
        # 改为统计接近角标红底的像素占比
        red = color_similarity_2d(image, UNOBTAINED_TAG_COLOR) >= 255 - 50
        if np.mean(red) >= UNOBTAINED_TAG_RED_RATIO:
            return 'unobtained'
        return None

    def predict(self, image, name=True, amount=True, cost=False, price=True, tag=True, counter=True, scroll_pos=None):
        """识别活动商店网格中的全部商品。

        Args:
            image (np.ndarray): 商店截图。
            name (bool): 是否识别物品名称。
            amount (bool): 是否识别单次获得数量。
            cost (bool): 是否识别货币类型。
            price (bool): 是否识别价格。
            tag (bool): 是否识别角标。
            counter (bool): 是否识别库存计数器（如 14/15）。默认为 True。
            scroll_pos (float, optional): 关联的滚动条纵向相对位置。默认为 None。

        Returns:
            list[EventShopItem]: 识别出的物品列表。
        """
        super().predict(image, name=name, amount=amount, cost=cost, price=price, tag=tag)
        if counter and len(self.items):
            counter_list = [item.crop(self.counter_area) for item in self.items]
            counter_list = self.counter_ocr.ocr(counter_list, direct_ocr=True)
            for i, t in zip(self.items, counter_list):
                i.count, i.total_count = t

        if isinstance(scroll_pos, float) and len(self.items):
            for i in self.items:
                i.scroll_pos = scroll_pos

        for i in self.items:
            if not (i.count == 0 and i.total_count == 0):
                i.correct_name_and_cost()
            i.predict_genre()

        return self.items
