"""岛屿鱼肉加工：在岛屿商店「鱼肉加工」页把鱼兑换成淡水/海水鱼肉。

移植自 AzurLaneAutoScript（LmeSzinc/AzurLaneAutoScript，GPL-3.0）的
module/island_handler/exchange.py：鱼卡网格、鱼名/库存/鱼肉数量识别与数量设置方式相同。
AzurPilot 改动：
- 只补到目标数量（`IslandFishery.MinFreshwaterFishMeat` / `MinSaltwaterFishMeat`），
  按每条鱼的鱼肉产量从高到低选鱼，不全部兑换；
- 商店侧栏、确认弹窗、获得物品弹窗按颜色识别（国际服通用弹窗资源不匹配），不新增截图；
- 由渔场任务在养殖完成后调用。

页面布局（1280×720）：岛屿主页右上「商店」→ 左侧栏第 7 项「鱼肉加工」，下方子页签「淡水」「海水」；
鱼卡每行 4 张，点卡片 +1，卡片右上「-」减 1；右下「加工」按钮，弹出「是否加工」确认。
"""
import cv2
import numpy as np
from jellyfish import levenshtein_distance

import module.config.server as server
from module.base.button import Button, ButtonGrid
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, crop, extract_letters
from module.exception import GameTooManyClickError
from module.island.assets import ISLAND_BACK
from module.ui.assets import ISLAND_CHECK
from module.island_fish_meat.assets import ISLAND_EXCHANGE_CONFIRM, ISLAND_GOTO_ISLAND_SHOP
from module.island_planner.data import DIC_ISLAND_EXCHANGE_RECIPE, DIC_ISLAND_ITEM
from module.logger import logger
from module.ocr.ocr import Digit, Ocr
from module.ui.page import page_island

FRESHWATER_FISH_MEAT = 2521
SALTWATER_FISH_MEAT = 2522
# {鱼肉ID: {鱼ID: 每条鱼产出鱼肉}}，每次兑换消耗一条鱼
FISH_MEAT_SOURCES = {
    meat_id: {
        fish_id: recipe['items'][meat_id]
        for recipe in DIC_ISLAND_EXCHANGE_RECIPE.values() if meat_id in recipe['items']
        for fish_id in recipe['resource_consume']
    }
    for meat_id in (FRESHWATER_FISH_MEAT, SALTWATER_FISH_MEAT)
}
FISH_MEAT_YIELD = {fish_id: amount for sources in FISH_MEAT_SOURCES.values() for fish_id, amount in sources.items()}

# 鱼卡（只显示有库存的鱼，按物品 ID 排序），每行 4 张
EXCHANGE_FISH_GRID = ButtonGrid(
    origin=(215, 111), delta=(131.33, 155), button_shape=(104, 108), grid_shape=(4, 2), name='EXCHANGE_FISH_GRID')
EXCHANGE_FISH_NAME_GRID = EXCHANGE_FISH_GRID.crop((-2, 111, 106, 138), name='EXCHANGE_FISH_NAME_GRID')
EXCHANGE_FISH_STOCK_GRID = EXCHANGE_FISH_GRID.crop((56, 86, 106, 110), name='EXCHANGE_FISH_STOCK_GRID')
# 已选数量显示在卡片左上方
EXCHANGE_FISH_COUNT_GRID = EXCHANGE_FISH_GRID.crop((34, -7, 81, 20), name='EXCHANGE_FISH_COUNT_GRID')
# 卡片右上的「-」，点在卡片外的部分（点卡片会再加一条）
EXCHANGE_FISH_MINUS_GRID = EXCHANGE_FISH_GRID.crop((105, -5, 116, 17), name='EXCHANGE_FISH_MINUS_GRID')
EXCHANGE_FISH_NAME_BACKGROUND = (112, 112, 115)
# 右侧「持有数量」：深色为已持有，蓝色为本次选中可获得
EXCHANGE_MEAT_AMOUNT = Button(area=(967, 530, 1171, 560), color=(), button=(967, 530, 1171, 560),
                              name='EXCHANGE_MEAT_AMOUNT')
ISLAND_EXCHANGE_CLEAR = Button(area=(375, 630, 423, 677), color=(), button=(375, 630, 423, 677),
                               name='ISLAND_EXCHANGE_CLEAR')

# 商店左侧栏：第 7 项「鱼肉加工」（选中为蓝色），其下两个子页签（选中为白色圆角条）
SHOP_FISH_MEAT_TAB = Button(area=(16, 510, 130, 572), color=(), button=(16, 510, 130, 572),
                            name='SHOP_FISH_MEAT_TAB')
SHOP_FISH_MEAT_TAB_ACTIVE_AREA = (16, 560, 130, 572)
SHOP_SUB_TABS = {
    FRESHWATER_FISH_MEAT: Button(area=(40, 600, 135, 620), color=(), button=(40, 600, 135, 620),
                                 name='SHOP_FISH_MEAT_FRESHWATER'),
    SALTWATER_FISH_MEAT: Button(area=(40, 657, 135, 677), color=(), button=(40, 657, 135, 677),
                                name='SHOP_FISH_MEAT_SALTWATER'),
}
SHOP_SUB_TAB_PILL = {
    FRESHWATER_FISH_MEAT: (40, 602, 135, 618),
    SALTWATER_FISH_MEAT: (40, 659, 135, 675),
}
TEXT_BLUE = (57, 189, 255)
# 「是否加工」确认弹窗：深色标题栏 + 蓝色确认按钮
EXCHANGE_POPUP_CONFIRM = Button(area=(670, 490, 915, 528), color=(), button=(670, 490, 915, 528),
                                name='EXCHANGE_POPUP_CONFIRM')
# 获得物品弹窗：画面中部横跨全屏的白色横带，点下方「点击关闭」处关闭
EXCHANGE_REWARD_CLOSE = Button(area=(560, 588, 720, 612), color=(), button=(560, 588, 720, 612),
                               name='EXCHANGE_REWARD_CLOSE')


class FishStockDigit(Digit):
    """卡片右下深色徽标上的库存数字。"""

    def pre_process(self, image):
        # 只保留徽标，周围浅色卡面会被识别成数字
        ys, xs = np.where(image.max(axis=2) < 130)
        if len(xs):
            image = image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        image = extract_letters(image, letter=self.letter, threshold=self.threshold)
        return cv2.copyMakeBorder(image, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=255)


def _fraction(image, area, color, threshold=30):
    x1, y1, x2, y2 = area
    region = image[y1:y2, x1:x2].astype(int)
    return float((np.abs(region - np.array(color)).max(axis=2) < threshold).mean())


def fish_meat_tab_active(image):
    return _fraction(image, SHOP_FISH_MEAT_TAB_ACTIVE_AREA, TEXT_BLUE, threshold=40) > 0.5


def active_fish_meat(image):
    """当前子页签对应的鱼肉 ID，无法判断时为 None。"""
    pills = {meat_id: _fraction(image, area, (247, 247, 247), threshold=25)
             for meat_id, area in SHOP_SUB_TAB_PILL.items()}
    meat_id = max(pills, key=pills.get)
    return meat_id if pills[meat_id] > 0.2 else None


def exchange_popup_appear(image):
    return (_fraction(image, EXCHANGE_POPUP_CONFIRM.area, TEXT_BLUE) > 0.5
            and _fraction(image, (360, 150, 880, 195), (32, 32, 32), threshold=20) > 0.5)


def reward_popup_appear(image):
    return float((image[300:480, :, :].min(axis=2) > 225).mean()) > 0.9


def fish_name_to_id(name, meat_id):
    """鱼名 OCR 结果按编辑距离匹配到本页可兑换的鱼，空或不唯一时为 None。"""
    if not name:
        return None
    distances = sorted(
        (levenshtein_distance(name, DIC_ISLAND_ITEM[fish_id]['name'][server.server]), fish_id)
        for fish_id in FISH_MEAT_SOURCES[meat_id]
    )
    if len(distances) > 1 and distances[0][0] == distances[1][0]:
        return None
    return distances[0][1]


def read_fish_cards(image, meat_id):
    """
    Returns:
        list[tuple[int, int, int]]: (卡片序号, 鱼ID, 库存)，鱼名无法识别时鱼ID为 None。
    """
    indices = [
        index for index, button in enumerate(EXCHANGE_FISH_NAME_GRID.buttons)
        if np.mean(color_similarity_2d(crop(image, button.area), EXCHANGE_FISH_NAME_BACKGROUND) > 235) > 0.5
    ]
    if not indices:
        return []
    lang = server.server if server.server in ('jp', 'tw') else 'cnocr'
    name_ocr = Ocr([], lang=lang, letter=(255, 255, 255), threshold=128, name='EXCHANGE_FISH_NAME')
    names = name_ocr.ocr([crop(image, EXCHANGE_FISH_NAME_GRID.buttons[i].area) for i in indices], direct_ocr=True)
    stock_ocr = FishStockDigit([], lang='cnocr', letter=(255, 255, 255), threshold=128, name='EXCHANGE_FISH_STOCK')
    stocks = stock_ocr.ocr([crop(image, EXCHANGE_FISH_STOCK_GRID.buttons[i].area) for i in indices], direct_ocr=True)
    return [(index, fish_name_to_id(name, meat_id), stock) for index, name, stock in zip(indices, names, stocks)]


def read_fish_meat(image):
    """
    Returns:
        tuple[int, int]: (已持有鱼肉, 当前选中可获得的鱼肉)。
    """
    owned = Digit(EXCHANGE_MEAT_AMOUNT, lang='cnocr', letter=(60, 60, 60), threshold=160,
                  name='EXCHANGE_MEAT_OWNED').ocr(image)
    gain = Digit(EXCHANGE_MEAT_AMOUNT, lang='cnocr', letter=TEXT_BLUE, threshold=128,
                 name='EXCHANGE_MEAT_GAIN').ocr(image)
    return owned, gain


def plan_fish_exchange(stock, need, keep=None):
    """选择要兑换的鱼，使获得的鱼肉不少于 need。

    按每条鱼的鱼肉产量从高到低选（用的鱼最少），每种鱼最多用到「库存 - keep」。

    Args:
        stock (dict): {鱼ID: 库存}。
        need (int): 还需要的鱼肉数量。
        keep (dict): {鱼ID: 保留数量}。

    Returns:
        dict: {鱼ID: 兑换数量}，鱼不够时尽量多换。
    """
    keep = keep or {}
    amounts = {}
    remaining = need
    for fish_id in sorted(stock, key=lambda i: (-FISH_MEAT_YIELD.get(i, 0), i)):
        if remaining <= 0:
            break
        per_fish = FISH_MEAT_YIELD.get(fish_id, 0)
        available = max(stock[fish_id] - max(keep.get(fish_id, 0), 0), 0)
        if per_fish <= 0 or available <= 0:
            continue
        count = min(available, -(-remaining // per_fish))
        amounts[fish_id] = count
        remaining -= count * per_fish
    return amounts


def fish_meat_gain(amounts):
    return sum(FISH_MEAT_YIELD[fish_id] * amount for fish_id, amount in amounts.items())


class IslandFishMeatExchange:
    """鱼肉加工，混入 Island 子类使用（需要 UI 导航与截图方法）。"""

    def _goto_fish_meat_page(self, meat_id):
        """
        Pages:
            in: 任意页面
            out: 商店「鱼肉加工」页，meat_id 对应的子页签
        """
        self.ui_ensure(page_island)
        click_timer = Timer(2)
        # 只在点过「商店」之后才点侧栏：岗位管理等页面也有深色侧栏与返回按钮，同一位置是别的按钮
        shop_clicked = self.appear(ISLAND_EXCHANGE_CONFIRM, offset=(20, 20))
        for image in self.loop(timeout=30):
            if self.appear(ISLAND_EXCHANGE_CONFIRM, offset=(20, 20)) and fish_meat_tab_active(image):
                if active_fish_meat(image) == meat_id:
                    return True
                if click_timer.reached():
                    self.device.click(SHOP_SUB_TABS[meat_id])
                    click_timer.reset()
                continue
            if reward_popup_appear(image):
                self.device.click(EXCHANGE_REWARD_CLOSE)
                continue
            if self.appear(ISLAND_CHECK, offset=(5, 5)):
                if self.appear_then_click(ISLAND_GOTO_ISLAND_SHOP, offset=(20, 20), interval=2):
                    shop_clicked = True
                    continue
            # 商店页（左侧栏）但不在鱼肉加工页
            elif shop_clicked and click_timer.reached() and self.appear(ISLAND_BACK, offset=(20, 20)):
                self.device.click(SHOP_FISH_MEAT_TAB)
                click_timer.reset()
                continue
        logger.warning('[岛屿-鱼肉加工] 进入鱼肉加工页超时')
        return False

    def _leave_fish_meat_page(self):
        """
        Pages:
            in: 商店「鱼肉加工」页
            out: page_island
        """
        for image in self.loop(timeout=30):
            if self.appear(ISLAND_CHECK, offset=(5, 5)):
                return True
            if reward_popup_appear(image):
                self.device.click(EXCHANGE_REWARD_CLOSE)
                continue
            if self.appear_then_click(ISLAND_BACK, offset=(20, 20), interval=2):
                continue
        logger.warning('[岛屿-鱼肉加工] 返回岛屿主页超时')
        return False

    def _clear_fish_selection(self):
        """清空选择，返回已持有鱼肉；未能清空时为 None。"""
        click_timer = Timer(1, count=2)
        for image in self.loop(timeout=5):
            owned, gain = read_fish_meat(image)
            if gain == 0:
                return owned
            if click_timer.reached_and_reset():
                self.device.click(ISLAND_EXCHANGE_CLEAR)
        logger.warning('[岛屿-鱼肉加工] 无法清空已选的鱼')
        return None

    def _read_fish_cards_stable(self, meat_id):
        """连续两张截图识别结果一致才采用。"""
        last = None
        for image in self.loop(timeout=5):
            cards = read_fish_cards(image, meat_id)
            if any(fish_id is None or stock <= 0 for _, fish_id, stock in cards):
                logger.info(f'[岛屿-鱼肉加工] 鱼卡识别不完整: {cards}')
                last = None
                continue
            if cards == last:
                return cards
            last = cards
        logger.warning('[岛屿-鱼肉加工] 无法识别鱼卡')
        return None

    def _set_fish_count(self, index, amount):
        ocr = Digit([EXCHANGE_FISH_COUNT_GRID.buttons[index]], lang='cnocr', letter=(255, 235, 85), threshold=128,
                    name='EXCHANGE_FISH_COUNT')
        try:
            self.ui_ensure_index(amount, letter=ocr, next_button=EXCHANGE_FISH_GRID.buttons[index],
                                 prev_button=EXCHANGE_FISH_MINUS_GRID.buttons[index], skip_first_screenshot=True)
            return True
        except GameTooManyClickError:
            logger.warning(f'[岛屿-鱼肉加工] 设置鱼卡 {index} 数量 {amount} 时点击过多')
            return False

    def _confirm_exchange(self, before, expected):
        """点击加工并确认弹窗，等待鱼肉数量增加。返回加工后持有数量（未确认到增加时为 before）。"""
        popup_confirmed = False
        owned = before
        for image in self.loop(timeout=15):
            if exchange_popup_appear(image):
                self.device.click(EXCHANGE_POPUP_CONFIRM)
                popup_confirmed = True
                continue
            if reward_popup_appear(image):
                self.device.click(EXCHANGE_REWARD_CLOSE)
                continue
            owned, gain = read_fish_meat(image)
            # 只认精确值：弹窗淡出时暗色的获得数字可能被读成持有数字的一部分
            if gain == 0 and owned == before + expected:
                return owned
            if not popup_confirmed and self.appear_then_click(ISLAND_EXCHANGE_CONFIRM, offset=(20, 20), interval=2):
                continue
        logger.warning(f'[岛屿-鱼肉加工] 预期获得 {expected}，实际持有 {owned}（加工前 {before}）')
        return before

    def exchange_fish_meat(self, meat_id, target, keep=None):
        """把鱼兑换成鱼肉，直到持有数量不少于 target。

        Args:
            meat_id (int): 2521 淡水鱼肉 / 2522 海水鱼肉。
            target (int): 目标持有数量。
            keep (dict): {鱼ID: 保留数量}。

        Returns:
            int: 加工后持有数量，无法完成时为 None。
        """
        name = DIC_ISLAND_ITEM[meat_id]['name']['cn']
        logger.hr(f'Island fish meat exchange {meat_id}', level=2)
        if not self._goto_fish_meat_page(meat_id):
            return None
        before = self._clear_fish_selection()
        if before is None:
            return None
        logger.attr('FishMeatOwned', f'{name} {before}/{target}')
        if before >= target:
            return before
        cards = self._read_fish_cards_stable(meat_id)
        if cards is None:
            return None
        stock = {fish_id: amount for _, fish_id, amount in cards}
        amounts = plan_fish_exchange(stock, target - before, keep)
        expected = fish_meat_gain(amounts)
        logger.info(f'[岛屿-鱼肉加工] {name} 持有 {before}，目标 {target}；鱼库存 {stock}，兑换 {amounts}，'
                    f'预期获得 {expected}')
        if expected <= 0:
            logger.info(f'[岛屿-鱼肉加工] 没有可兑换{name}的鱼')
            return before
        for index, fish_id, _ in cards:
            if not self._set_fish_count(index, amounts.get(fish_id, 0)):
                self._clear_fish_selection()
                return None
        for image in self.loop(timeout=3):
            _, gain = read_fish_meat(image)
            if gain == expected:
                break
        else:
            logger.warning(f'[岛屿-鱼肉加工] 已选可获得 {gain} 与计划 {expected} 不符，取消')
            self._clear_fish_selection()
            return None
        return self._confirm_exchange(before, expected)

    def run_fish_meat_exchange(self, targets, keep=None):
        """按目标补鱼肉，完成后回到岛屿主页。

        Args:
            targets (dict): {鱼肉ID: 目标持有数量}，0 或负数跳过。

        Pages:
            in: 任意页面
            out: page_island
        """
        targets = {meat_id: int(target or 0) for meat_id, target in targets.items() if int(target or 0) > 0}
        if not targets:
            return
        logger.hr('Island fish meat exchange', level=1)
        for meat_id, target in targets.items():
            self.exchange_fish_meat(meat_id, target, keep)
        self._leave_fish_meat_page()
