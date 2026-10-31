"""智能换船完成后，按实际舰队徽标将整队安排到指定后宅楼层。"""

import re

import cv2
import numpy as np

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import crop
from module.dorm.assets import (DORM_FLEET_CANCEL, DORM_FLEET_CHECK, DORM_FLEET_CONFIRM, DORM_FLEET_ENTER,
                               DORM_FLEET_FILTER_CANCEL, DORM_FLEET_REST, DORM_FLEET_TRAIN, OCR_DORM_FLEET_AMOUNT,
                               TEMPLATE_DORM_SELECTED)
from module.logger import logger
from module.ocr.ocr import Ocr
from module.retire.assets import DOCK_CHECK, DOCK_FILTER_CONFIRM, DOCK_SELECTED
from module.retire.dock import Dock
from module.runtime.fleet_formation import VisualDockScanner
from module.runtime.fleet_rotation import active_fleets
from module.runtime.fleet_training import ships
from module.ui.assets import DORM_CHECK, DORM_INFO
from module.ui.page import page_dorm, page_main
from module.ui.scroll import Scroll


DORM_PATH = 'FleetInfo.FleetDorm'
DORM_SLOTS = ButtonGrid(origin=(142, 205), delta=(170, 0), button_shape=(155, 440),
                        grid_shape=(6, 1), name='后宅舰船栏位')


class DormArrangeError(Exception):
    """本次后宅安排无法确认；取消未提交选择后交还原任务。"""


def rest_fleet(config, replaced):
    """只在已完成换船的出战队中，按全队出击、道中、Boss的优先级选择。"""
    if config.cross_get(DORM_PATH + '.Enabled', False) is not True:
        return None
    active = active_fleets(config)
    roles = (2, 1) if config.Fleet_FleetOrder == 'fleet1_boss_fleet2_mob' else (1, 2)
    return next((active[role] for role in roles if active.get(role) in replaced), None)


def rest_after_rotation(manager, replaced, *, committed=False):
    """换船与换装结束后才提交编队并安排后宅；关闭时不增加游戏操作。"""
    fleet = rest_fleet(manager.config, replaced)
    if fleet is None or manager.config.cross_get('FleetInfo.FleetTraining.State', {}).get('pending'):
        return
    if not committed:
        manager._commit_formation()
    FleetRotationDorm(config=manager.config, device=manager.device).run(fleet)


class DormCounter(Ocr):
    """拒绝未知、越界和残缺数量，不能把识别失败当作已清空。"""

    def __init__(self, button):
        super().__init__(button, threshold=128, alphabet='0123456789/')
        self.SHOW_LOG = False

    def after_process(self, result):
        match = re.fullmatch(r'([0-6])/([1-6])', result.strip())
        if match:
            current, total = map(int, match.groups())
            if current <= total:
                return current, total
        return None


class DormFleetScanner(VisualDockScanner):
    """复用动态卡位与编队徽标，只补充后宅的选中文字识别。"""

    @staticmethod
    def selected(image, card):
        # 只比对白色“已选中”字形，不把立绘颜色或训练中状态当作选中。
        region = crop(image, (card.x + 10, card.y + 75, card.x + 130, card.y + 124))
        binary = (region.min(axis=2) > 205).astype(np.uint8) * 255
        template = (TEMPLATE_DORM_SELECTED.image.min(axis=2) > 205).astype(np.uint8) * 255
        # 轻微平滑字形，容忍滚动后抗锯齿像素变化；不依赖整张立绘颜色。
        binary = cv2.GaussianBlur(binary, (3, 3), 0)
        template = cv2.GaussianBlur(template, (3, 3), 0)
        score = cv2.minMaxLoc(cv2.matchTemplate(binary, template, cv2.TM_CCOEFF_NORMED))[1]
        return score >= .7

    @staticmethod
    def fingerprint(image, card):
        """截取选中文字与舰队徽标上方的卡面，供同一轮跨滚动核对。"""
        portrait = crop(image, (card.x + 38, card.y + 30, card.x + 130, card.y + 70))
        return card.x, cv2.cvtColor(portrait, cv2.COLOR_RGB2GRAY)

    @staticmethod
    def same_ship(image, card, fingerprint):
        x, portrait = fingerprint
        if card.x != x or np.std(portrait) < 5:
            return False
        region = crop(image, (card.x + 30, card.y + 23, card.x + 138, card.y + 75))
        region = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        return cv2.minMaxLoc(cv2.matchTemplate(region, portrait, cv2.TM_CCOEFF_NORMED))[1] >= .9


class FleetRotationDorm(Dock):
    def _panel(self):
        return self.appear(DORM_FLEET_CHECK, offset=(3, 3))

    def _floor(self, floor):
        button = DORM_FLEET_TRAIN if floor == 'floor_1' else DORM_FLEET_REST
        return self.match_template_color(button, offset=(3, 3))

    def _enter_floor(self, floor):
        """打开训练入口，并正向确认用户指定的训练／休息页签。

        Pages:
            in: page_dorm
            out: 后宅舰船面板，指定楼层
        """
        tab = DORM_FLEET_TRAIN if floor == 'floor_1' else DORM_FLEET_REST
        click = Timer(3)
        confirmed = False
        for _ in self.loop(skip_first=False, timeout=30):
            if self.appear_then_click(DORM_INFO, offset=(30, 30), similarity=.75, interval=3):
                confirmed = False
                continue
            if self._panel():
                if self._floor(floor):
                    if confirmed:
                        return
                    confirmed = True
                    continue
                confirmed = False
                if click.reached():
                    self.device.click(tab)
                    click.reset()
                continue
            confirmed = False
            if self.appear(DORM_CHECK) and click.reached():
                self.device.click(DORM_FLEET_ENTER)
                click.reset()
        raise DormArrangeError('未确认指定楼层，请检查二楼是否已解锁')

    def _open_picker(self, floor):
        """从首个已解锁栏位进入选船页，不点击扩建栏位。

        Pages:
            in: 后宅舰船面板
            out: 后宅选船页
        """
        click, tab_click = Timer(3), Timer(3)
        tab = DORM_FLEET_TRAIN if floor == 'floor_1' else DORM_FLEET_REST
        for _ in self.loop(skip_first=False, timeout=20):
            if self.appear_then_click(DORM_INFO, offset=(30, 30), similarity=.75, interval=3):
                continue
            if self.appear(DOCK_CHECK) and self.appear(DORM_FLEET_CONFIRM, offset=(3, 3)):
                return
            if self._panel():
                # 页面交接后仍按新截图核对页签，不能在训练页只等休息页出现。
                if self._floor(floor):
                    if click.reached():
                        self.device.click(DORM_SLOTS.buttons[0])
                        click.reset()
                elif tab_click.reached():
                    self.device.click(tab)
                    tab_click.reset()
        raise DormArrangeError('未确认进入后宅选船页')

    def _top(self):
        """以滑块上沿确认顶部，避免小滑块的百分比误差漏掉前几行。"""
        scroll = Scroll((1240, 70, 1247, 627), color=(247, 211, 66), name='后宅选船滚动条')
        click = Timer(2)
        for _ in self.loop(skip_first=False, timeout=20):
            thumb = np.flatnonzero(scroll.match_color(self))
            if len(thumb) and thumb[0] <= 1:
                return
            if len(thumb) and click.reached():
                y = scroll.area[1] + int(np.median(thumb))
                self.device.swipe((1243, y), (1243, 1), name='后宅选船回到顶部')
                click.reset()
        raise DormArrangeError('未确认选船列表顶部，未执行点选')

    def _selection(self, fleet, target, capacity, *, clear=False):
        """逐次核对数量变化；翻页重叠的已选卡片不会再次点击。"""
        scanner, counter = DormFleetScanner(), DormCounter(DOCK_SELECTED)
        scroll = Scroll((1240, 70, 1247, 627), color=(247, 211, 66), name='后宅选船滚动条')
        previous, pending, last_count = None, None, None
        handled = []
        processed = []
        moved_from = None
        stable = Timer(.3, count=1).start()
        pages = 0
        change = Timer(10).start()
        for _ in self.loop(skip_first=False, timeout=45):
            if self.handle_popup_cancel('FLEET_DORM_SELECT'):
                raise DormArrangeError('目标舰船需要额外确认，已取消本次安排')
            if self.appear(DOCK_CHECK) and self.appear(DORM_FLEET_CONFIRM, offset=(3, 3)):
                count = counter.ocr(self.device.image)
                if count is None:
                    continue
                current, total = count
                if count != last_count:
                    logger.attr('后宅已选', f'{current}/{total}')
                    last_count = count
                if total != capacity:
                    raise DormArrangeError('后宅可选栏位数变化，未提交选择')
                if pending is not None:
                    expected, card, fingerprint = pending
                    if current == expected and scanner.selected(self.device.image, card) == (not clear):
                        processed.append(fingerprint)
                        pending, previous = None, None
                    else:
                        if change.reached():
                            raise DormArrangeError('点击后未确认已选数量变化或卡片选中状态，未重复点选')
                        continue
                if not clear and current > target:
                    raise DormArrangeError('已选数量超出当前舰队，未提交选择')
                if current == target:
                    if previous == ('done', count):
                        return
                    previous = ('done', count)
                    continue
                try:
                    cards = scanner.scan(self.device.image)
                except ValueError:
                    previous = None
                    continue
                selected = [scanner.selected(self.device.image, card) for card in cards]
                signature = tuple((card.x, card.y, card.fleet) for card in cards)
                if signature != previous:
                    previous = signature
                    stable.reset()
                if moved_from is not None:
                    pixels = self.device.image[65:627, 85:1225].astype(np.int16)
                    if np.mean(np.abs(pixels - moved_from)) <= 2:
                        if change.reached():
                            raise DormArrangeError('拖动后未确认列表移动，不再继续向下翻页')
                        continue
                    # 只等卡位停稳，不用会播放动画的整张立绘判定页面稳定。
                    if not stable.reached():
                        continue
                    moved_from = None
                candidates = [card for card, chosen in zip(cards, selected)
                              if chosen] if clear else [card for card, chosen in zip(cards, selected)
                                                        if card.fleet == fleet and not chosen]
                candidates = [card for card in candidates if not any(
                    card.x == done.x and abs(card.y - done.y) < 227 / 2 for done in handled)]
                candidates = [card for card in candidates if not any(
                    scanner.same_ship(self.device.image, card, fingerprint) for fingerprint in processed)]
                if candidates:
                    card = candidates[0]
                    fingerprint = scanner.fingerprint(self.device.image, card)
                    self.device.click(ButtonGrid(origin=(card.x + 25, card.y + 35), delta=(0, 0),
                        button_shape=(80, 135), grid_shape=(1, 1), name='后宅已选' if clear else '后宅编队').buttons[0])
                    pending = (current - 1 if clear else current + 1), card, fingerprint
                    handled.append(card)
                    change.reset()
                    previous = None
                    continue
                if not stable.reached():
                    continue
                # 只在确实需要翻页时读取滚动条，避免每帧输出重复位置日志。
                position = round(scroll.cal_position(self), 3)
                if scroll.length == 0 or position >= .995:
                    raise DormArrangeError(f'未能选齐第{fleet}舰队，或原有选中尚未清空，未提交选择')
                # 先锋与主力同时筛选，36艘编队船加12艘后宅置顶船和离队格，最多七排。
                if pages >= 5:
                    raise DormArrangeError(f'前七排未能选齐第{fleet}舰队，跳过本次后宅安排')
                pixels = self.device.image[65:627, 85:1225].astype(np.int16).copy()
                if self.config.Emulator_ControlMethod in ('minitouch', 'MaaTouch', 'uiautomator2', 'scrcpy', 'nemu_ipc'):
                    self.device.drag((1170, 470), (1170, 243), point_random=(0, 0, 0, 0),
                        shake=(0, 0), shake_random=(0, 0, 0, 0), hold_duration=.4, name='后宅选船逐排拖动')
                else:
                    # 不支持拖拽的后端使用慢滑，避免 Device.drag 的回退点击碰到舰船。
                    self.device.swipe((1170, 470), (1170, 243), duration=.6, name='后宅选船逐排滑动')
                pages += 1
                moved_from = pixels
                change.reset()
                previous = None
                handled.clear()
        raise DormArrangeError('选船状态未确认，未提交选择')

    def _confirm(self, floor, amount):
        """只在已选数量完整时提交，并确认后宅面板显示实际入驻数量。

        Pages:
            in: 后宅选船页
            out: 后宅舰船面板
        """
        counter = DormCounter(DOCK_SELECTED)
        panel_count = DormCounter(OCR_DORM_FLEET_AMOUNT)
        submitted = False
        for _ in self.loop(skip_first=False, timeout=30):
            if submitted and self._panel() and self._floor(floor):
                count = panel_count.ocr(self.device.image)
                if count is not None and count[0] == amount:
                    return
            if self.appear(DOCK_CHECK):
                count = counter.ocr(self.device.image)
                if count is None:
                    continue
                if count[0] != amount:
                    raise DormArrangeError('确认前已选数量不符，未提交选择')
                if self.appear_then_click(DORM_FLEET_CONFIRM, offset=(3, 3), interval=3):
                    submitted = True
                    continue
        raise DormArrangeError('未确认整队已安排到后宅')

    def _arrange(self, fleet):
        """全部换船和换装结束后调用，整队包括未更换的固定舰位。

        Pages:
            in: page_main，游戏编队已提交
            out: 指定楼层的后宅舰船面板
        """
        floor = self.config.cross_get(DORM_PATH + '.Floor', 'floor_1')
        if server.server != 'cn' or floor not in ('floor_1', 'floor_2'):
            raise DormArrangeError('当前仅支持国服一楼训练／二楼休息')
        formation = self.config.cross_get('FleetInfo.FleetInfo.Result', {})
        roster = ships(formation, fleet)
        amounts = {'vanguard': sum(slot in roster for slot in (4, 5, 6)),
                   'main': sum(slot in roster for slot in (1, 2, 3))}
        amount = sum(amounts.values())
        if not amounts['vanguard'] or not amounts['main']:
            raise DormArrangeError('当前舰队前后排快照不完整，不修改后宅')
        logger.hr(f'换船休息：第{fleet}舰队 → {"一楼训练" if floor == "floor_1" else "二楼休息"}', level=1)
        self.ui_ensure(page_dorm)
        self._enter_floor(floor)
        self._open_picker(floor)
        self.dock_favourite_set(False)
        self.dock_filter_set(index=['vanguard', 'main'], reset_index=True)
        self._top()
        counter, previous, count = DormCounter(DOCK_SELECTED), None, None
        for _ in self.loop(skip_first=False, timeout=15):
            count = counter.ocr(self.device.image)
            if count is not None and count == previous:
                break
            previous = count
        else:
            raise DormArrangeError('未确认后宅可选栏位，不取消原有选中')
        if count[1] < amount:
            raise DormArrangeError('未确认足够的后宅栏位，不取消原有选中')
        capacity = count[1]
        self._selection(fleet, 0, capacity, clear=True)
        # 清空时若发生过滚动，只恢复列表顶部；筛选始终沿用入口设置。
        self._top()
        self._selection(fleet, amount, capacity)
        self._confirm(floor, amount)

    def _leave(self):
        """取消未提交选择，关闭面板，再沿现有导航回母港。

        Pages:
            in: 后宅、后宅选船／筛选页或 page_main
            out: page_main
        """
        for _ in self.loop(skip_first=False, timeout=20):
            if self.is_in_main():
                return
            if self.handle_popup_cancel('FLEET_DORM_SKIP'):
                continue
            if self.appear(DORM_CHECK):
                break
            if self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60)):
                if self.appear_then_click(DORM_FLEET_FILTER_CANCEL, offset=(3, 3), interval=3):
                    continue
            if self.appear(DOCK_CHECK):
                if self.appear_then_click(DORM_FLEET_CANCEL, offset=(3, 3), interval=3):
                    continue
            if self.appear_then_click(DORM_FLEET_CHECK, offset=(3, 3), interval=3):
                continue
        self.ui_ensure(page_main)

    def run(self, fleet):
        """后宅安排不可用时跳过，保留已完成的换船和换装，继续原任务。

        Pages:
            in: page_main
            out: page_main
        """
        try:
            self._arrange(fleet)
        except DormArrangeError as exc:
            logger.warning(f'换船休息已跳过，继续原任务：{exc}')
            self._leave()
            return False
        self._leave()
        return True
