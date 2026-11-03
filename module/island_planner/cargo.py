"""读取货运委托中「已部分提交」订单的缺口，作为规划器目标。

物品识别与「库存/需求」数字识别移植自 AzurLaneAutoScript（LmeSzinc/AzurLaneAutoScript，GPL-3.0）的
module/island/transport.py（TransportItemMatcher、primary_counter_area）与
module/island_handler/recipe.py（IslandReversedDigitCounter）。物品模板 assets/island/transport/ 也来自 ALAS，
是物品图标，与语言无关。

国际服逐件提交货物，已提交的格子显示蓝底「COMPLETED」印章。已提交过货物的委托更换后不退还货物，
只能补齐，因此其余格子的「需求 - 库存」作为生产目标；尚未提交任何货物的委托可以更换，不计入。
"""
import os
import re

import cv2
import numpy as np

import module.config.server as server
from module.base.button import Button, ButtonGrid
from module.base.decorator import cached_property
from module.base.utils import color_similarity_2d, crop, extract_letters, image_color_count, load_image, rgb2luma
from module.island_planner.data import DIC_ISLAND_ITEM
from module.logger import logger
from module.ocr.ocr import Ocr

SLOT_COUNT = 3
SLOT_DELTA = 175
TEXT_BLUE = (57, 190, 255)
TEXT_RED = (244, 124, 124)
COMPLETED_BLUE = (90, 201, 255)
# 主栏位每行 3 个货物格，只含图标部分
SUBMISSION_GRID = ButtonGrid(
    origin=(481, 174), delta=(104.5, SLOT_DELTA), button_shape=(86, 64), grid_shape=(3, SLOT_COUNT),
    name='CARGO_SUBMISSION')


def counter_area(card, slot):
    """货物格下方右对齐的「库存/需求」文字区域。库存位数多时向左溢出，从左侧空隙开始取。"""
    x = SUBMISSION_GRID[card, slot].area[0]
    left = SUBMISSION_GRID[card - 1, slot].area[0] + 85 if card else x - 20
    dy = 6 if server.server == 'en' else 0
    return left, 239 + dy + SLOT_DELTA * slot, x + 84, 255 + dy + SLOT_DELTA * slot


def card_completed(image, card, slot):
    """货物格顶部蓝条：国际服已逐件提交的格子。"""
    x1, y1 = SUBMISSION_GRID[card, slot].area[:2]
    return bool(image_color_count(crop(image, (x1, y1, x1 + 86, y1 + 10)), color=COMPLETED_BLUE,
                                  threshold=34, count=500))


class CargoCounterOcr(Ocr):
    """「库存/需求」，库存足够为蓝色、不足为红色。"""

    def __init__(self):
        if server.server == 'en':
            threshold, sub_threshold = 125, 110
        else:
            threshold, sub_threshold = 170, 110
        lang = 'azur_lane' if server.server == 'jp' else 'cnocr'
        super().__init__([], lang=lang, letter=TEXT_BLUE, threshold=threshold, alphabet='0123456789/IDSB',
                         name='CARGO_COUNTER_OCR')
        self.sub_threshold = sub_threshold

    def pre_process(self, image):
        main = extract_letters(image, letter=TEXT_BLUE, threshold=self.threshold)
        mask = color_similarity_2d(image, TEXT_RED)
        mask[mask < self.sub_threshold] = 0
        if cv2.countNonZero(mask) > 30:
            sub = extract_letters(image, letter=TEXT_RED, threshold=self.sub_threshold)
            cv2.bitwise_and(main, sub, dst=main)
        return cv2.copyMakeBorder(main, 2, 4, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5').replace('B', '8')
        match = re.fullmatch(r'([0-9]+)/([0-9]+)', result)
        if not match:
            logger.warning(f'[岛屿-货运] 无法识别数量: {result}')
            return 0, 0
        return int(match.group(1)), int(match.group(2))


class CargoItemMatcher:
    """按 assets/island/transport 的物品模板识别货物格。

    *_2.png 为 46x46 配方图标，无编号文件为主栏位货物格裁剪（没有配方图标的物品，如铜矿、鱼肉、禽肉）。
    缩放比例为 ALAS 在截图上实测的主栏位比例。
    """
    FOLDER = './assets/island/transport'
    ICON_SCALE = 1.045
    CARD_WHITE = (237, 237, 235)
    SIMILARITY = 0.70
    COLOR_THRESHOLD = 20

    @cached_property
    def templates(self):
        icons, cards = {}, {}
        for file in sorted(os.listdir(self.FOLDER)):
            name, ext = os.path.splitext(file)
            if ext != '.png':
                continue
            image = load_image(os.path.join(self.FOLDER, file))
            if name.endswith('_2'):
                icons[name[:-2]] = cv2.resize(image, None, fx=self.ICON_SCALE, fy=self.ICON_SCALE,
                                              interpolation=cv2.INTER_AREA)
            else:
                cards[name] = image
        for name, image in cards.items():
            if name not in icons:
                # 去掉货物格的白色底，只留图标
                diff = np.abs(image.astype(int) - np.array(self.CARD_WHITE)).max(axis=2) > 25
                ys, xs = np.where(diff)
                icons[name] = image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        return {name: (image, rgb2luma(image), tuple(cv2.mean(image)[:3])) for name, image in icons.items()}

    @cached_property
    def item_ids(self):
        return {data['name']['en'].replace(' ', '_'): item_id for item_id, data in DIC_ISLAND_ITEM.items()}

    def match(self, image, area):
        """
        Returns:
            int: 物品 ID，无法识别时为 None。
        """
        x1, y1, x2, y2 = area
        passed = []
        for name, (template, luma, color) in self.templates.items():
            th, tw = template.shape[:2]
            if tw > x2 - x1 or th > y2 - y1:
                continue
            button = Button(area=(x1, y1, x1 + tw, y1 + th), color=color, button=(x1, y1, x1 + tw, y1 + th),
                            name=f'CARGO_ITEM_{name}')
            button.image, button.image_luma = template, luma
            button._match_init = button._match_luma_init = True
            if button.match_template_color(image, offset=(0, 0, x2 - x1 - tw, y2 - y1 - th),
                                           similarity=self.SIMILARITY, threshold=self.COLOR_THRESHOLD):
                passed.append(name)
        if not passed:
            return None
        if len(passed) > 1:
            card = rgb2luma(crop(image, area))
            scores = {name: cv2.minMaxLoc(cv2.matchTemplate(card, self.templates[name][1], cv2.TM_CCOEFF_NORMED))[1]
                      for name in passed}
            passed.sort(key=lambda name: -scores[name])
        return self.item_ids.get(passed[0])


def read_cargo_slots(image, matcher=None, ocr=None):
    """读取三个主栏位的货物格。

    Returns:
        list[dict]: 每个栏位 {'completed': 已提交格数, 'items': [(物品ID, 库存, 需求)],
            'unreadable': 无法识别的格数}，
            运行中或空栏位没有数字，items 为空。无法识别的格子记录警告后跳过并计数；
            已部分提交的委托中有图标但还没显示数字的格子也计为无法识别。
    """
    matcher = matcher or CargoItemMatcher()
    ocr = ocr or CargoCounterOcr()
    slots = []
    for slot in range(SLOT_COUNT):
        completed = 0
        cards = []
        blank = []
        for card in range(3):
            if card_completed(image, card, slot):
                completed += 1
                continue
            area = counter_area(card, slot)
            counter = crop(image, area)
            if not (image_color_count(counter, color=TEXT_RED, threshold=60, count=20)
                    or image_color_count(counter, color=TEXT_BLUE, threshold=60, count=20)):
                blank.append(SUBMISSION_GRID[card, slot].area)
                continue
            cards.append((SUBMISSION_GRID[card, slot].area, counter))
        items = []
        unreadable = 0
        if cards:
            counters = ocr.ocr([counter for _, counter in cards], direct_ocr=True)
            for (area, _), (stock, need) in zip(cards, counters):
                item_id = matcher.match(image, area)
                if item_id is None or need <= 0:
                    logger.warning(f'[岛屿-货运] 栏位 {slot + 1} 有无法识别的货物格')
                    unreadable += 1
                    continue
                items.append((item_id, stock, need))
        if completed:
            # 已部分提交的委托里有货物图标却没有数字，多半是页面还没渲染完，计为未识别
            for area in blank:
                if matcher.match(image, area) is not None:
                    logger.warning(f'[岛屿-货运] 栏位 {slot + 1} 有货物格尚未显示数字')
                    unreadable += 1
        slots.append({'completed': completed, 'items': items, 'unreadable': unreadable})
    return slots


def partial_order_targets(slots):
    """已部分提交的委托还缺的货物。

    同一物品出现在多个委托中时需求相加，库存只算一次（各格显示的是同一份库存）。

    Returns:
        dict[int, int]: {物品ID: 还需生产的数量}。
    """
    need, stock = {}, {}
    for slot in slots:
        if not slot['completed']:
            continue
        for item_id, current, required in slot['items']:
            need[item_id] = need.get(item_id, 0) + required
            stock[item_id] = max(stock.get(item_id, 0), current)
    return {item_id: total - stock[item_id] for item_id, total in sorted(need.items()) if total > stock[item_id]}


def partial_orders_fully_read(slots):
    """已部分提交的委托是否每个未完成格都识别成功。

    有格子没识别出来时缺口不完整，不能据此覆盖已保存的货运目标。
    """
    return not any(slot['completed'] and slot.get('unreadable', 0) for slot in slots)
