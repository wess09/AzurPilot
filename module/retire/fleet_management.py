"""按舰队和舰位交换卡面；姓名记录与卡面定位分开，心情读取供策略复核。"""

from copy import deepcopy

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.config.time_source import now as current_time
from module.equipment.assets import FLEET_DETAIL, FLEET_DETAIL_CHECK, FLEET_NEXT, FLEET_PREV
from module.exception import FleetManagementError, GameStuckError, GameTooManyClickError, MindCalculatorScanError
from module.logger import logger
from module.retire.assets import DOCK_CHECK, DOCK_EMPTY, DOCK_SEARCH_ACTIVE, DOCK_SEARCH_CLOSED
from module.retire.dock import Dock
from module.retire.fleet_emotion import learn_fleet_emotion, screenshot_window
from module.runtime.fleet_formation import (CATEGORY_SLOTS, SLOT_CENTERS, SUBMARINE_SLOT_CENTERS, TYPE_BUTTON_AREAS,
    FormationCardMerger, FormationDetailScanner, FormationDockScanner, PortraitMatcher, VisualDockScanner,
    choose_portrait, combine_references, detail_occupied, detail_portraits, menu_area, selected_count_changed,
    bottom_fleet_index, fleet_type_selected, selected_menu_fleet, selector_closed, slot_swap_plan, preserve_emotions,
    validate_position, validate_swap)
from module.ui.assets import BACK_ARROW, FLEET_CHECK
from module.ui.page import page_fleet
from module.ui.scroll import Scroll


PICKER_SCROLL = Scroll((1240, 70, 1247, 627), color=(247, 211, 66), name='编队选船滚动条')
PICKER_CONFIRM = Button((936, 641, 1109, 700), (80, 130, 190), (956, 651, 1090, 689), name='编队选船确定')


def position_button(area, name):
    return Button(area, (0, 0, 0), area, name=name)


def fleet_type_button(fleet_type):
    return position_button(TYPE_BUTTON_AREAS[fleet_type], f'{fleet_type}舰队类型')


def fleet_menu_button(fleet_type):
    area = (142, 650, 345, 702) if fleet_type == 'surface' else (500, 650, 710, 702)
    return position_button(area, f'{fleet_type}舰队选择')


class FleetManagement(Dock):
    RESULT_PATH = 'FleetInfo.FleetInfo.Result'
    RECORD_PATH = 'FleetInfo.FleetInfo.Record'

    @staticmethod
    def _normalize_result(result):
        return {str(fleet): [dict(name=str(ship.get('name', '')), level=int(ship.get('level', 0)),
                                 emotion=ship.get('emotion'),
                                 **{key: ship[key] for key in ('review', 'raw_name') if key in ship},
                                 **({'slot': ship['slot']} if 'slot' in ship else {})) for ship in ships]
                for fleet, ships in result.items()}

    def _save_result(self, result):
        self._rotation_result = deepcopy(result)
        self.config.modified[self.RESULT_PATH] = result
        self.config.modified[self.RECORD_PATH] = current_time().replace(microsecond=0)
        self.config.save()

    @staticmethod
    def slot_button(slot, fleet_type='surface'):
        validate_position(1, slot, fleet_type)
        x, y = (SLOT_CENTERS if fleet_type == 'surface' else SUBMARINE_SLOT_CENTERS)[slot]
        return position_button((x - 9, y - 9, x + 9, y + 9), f'{fleet_type}舰位{slot}')

    def _formation_visible(self):
        return self.appear(FLEET_CHECK) and self.appear(FLEET_DETAIL)

    def fleet_enter(self, fleet, fleet_type='surface', method='menu'):
        """按类型和下拉列表高亮切队，支持左右箭头，不读取舰队编号OCR。

        Pages:
            in: Any
            out: page_fleet，指定类型和编号的舰队
        """
        validate_position(fleet, 1, fleet_type)
        if method not in ('menu', 'arrows'):
            raise ValueError('切队方式必须为 menu 或 arrows')
        # 工具任务的 Device 可能尚未截过图，不能先调用任何 appear()。
        if not self.device.has_cached_image:
            self.device.screenshot()
        if self.appear(FLEET_DETAIL_CHECK):
            self.ui_click(BACK_ARROW, appear_button=FLEET_DETAIL_CHECK,
                          check_button=self._formation_visible, retry_wait=2)
        self.ui_ensure(page_fleet)
        phase, current = 'kind', None
        click, settle = Timer(2), Timer(.5)
        opener = fleet_menu_button(fleet_type)
        for _ in self.loop(timeout=75):
            if phase == 'kind':
                if self._formation_visible() and fleet_type_selected(self.device.image, fleet_type):
                    phase = 'open'
                elif self._formation_visible() and click.reached():
                    self.device.click(fleet_type_button(fleet_type))
                    click.reset()
                continue
            if phase == 'open':
                current = selected_menu_fleet(self.device.image, fleet_type)
                if current is not None and click.reached():
                    if current == fleet:
                        self.device.click(opener)
                        phase = 'closed'
                    elif method == 'arrows':
                        self.device.click(opener)
                        phase = 'arrow'
                    else:
                        self.device.click(position_button(menu_area(fleet, fleet_type), f'第{fleet}舰队'))
                        phase = 'selected'
                        settle.reset()
                    click.reset()
                elif self._formation_visible() and selector_closed(self.device.image, fleet_type) and click.reached():
                    self.device.click(opener)
                    click.reset()
                continue
            if phase == 'selected':
                if (self._formation_visible() and fleet_type_selected(self.device.image, fleet_type)
                        and selector_closed(self.device.image, fleet_type)
                        and bottom_fleet_index(self.device.image, fleet_type) == fleet and settle.reached()):
                    return
                # 点选队号后菜单会自行关闭，只确认结果，不重新展开菜单。
                continue
            if phase == 'closed' and self._formation_visible() and selector_closed(self.device.image, fleet_type):
                return
            if phase == 'closed' and selected_menu_fleet(self.device.image, fleet_type) == fleet and click.reached():
                self.device.click(opener)
                click.reset()
                continue
            if phase == 'reopen' and selected_menu_fleet(self.device.image, fleet_type) is not None:
                phase = 'open'
                continue
            if (phase in ('reopen', 'arrow') and self._formation_visible()
                    and selector_closed(self.device.image, fleet_type) and click.reached()):
                if phase == 'arrow':
                    self.device.click(FLEET_NEXT if current < fleet else FLEET_PREV)
                    phase = 'reopen'
                else:
                    self.device.click(opener)
                    phase = 'open'
                click.reset()
        raise FleetManagementError(f'未能确认{fleet_type}第{fleet}舰队的切换结果')

    def _open_slot(self, slot, fleet_type='surface'):
        """点击固定舰位进入单选船坞；不判断舰名或已选数量OCR。

        Pages:
            in: page_fleet，调用方已选择目标舰队
            out: 编队选船页
        """
        click = Timer(2)
        for _ in self.loop(timeout=20):
            # “编队”和“船坞”标题的平均颜色接近，必须匹配字形确认已经进入选船页。
            if self.appear(DOCK_CHECK, offset=(20, 20)):
                return
            if self._formation_visible() and click.reached():
                self.device.click(self.slot_button(slot, fleet_type))
                click.reset()
        raise FleetManagementError('未能从指定舰位进入选船页')

    def _enter_scan_submarine(self):
        """从水面扫描切到默认第一潜艇舰队，只点击一次右侧舰队入口。

        Pages:
            in: page_fleet，第一水面舰队，选船页已关闭
            out: page_fleet，第一潜艇舰队
        """
        clicked = False
        for _ in self.loop(timeout=20):
            if self._formation_visible() and fleet_type_selected(self.device.image, 'submarine'):
                return
            if self._formation_visible() and not clicked:
                self.device.click(fleet_menu_button('submarine'))
                clicked = True
        raise FleetManagementError('未能从水面编队进入潜艇编队')

    def _close_picker(self):
        """取消选船并返回编队，不点击确定或离队。

        Pages:
            in: 编队选船页
            out: page_fleet
        """
        click = Timer(2)
        for _ in self.loop(timeout=20):
            if self._formation_visible():
                return
            if self.appear(DOCK_CHECK) and click.reached():
                self.device.click(BACK_ARROW)
                click.reset()
        raise FleetManagementError('未能从选船页返回编队')

    def _scan_fleet_enter(self, fleet, fleet_type='surface'):
        """详情扫描按箭头顺序切队，以底部编号确认，不展开舰队列表。

        Pages:
            in: page_fleet，编队视图
            out: page_fleet，指定类型和编号的舰队
        """
        validate_position(fleet, 1, fleet_type)
        type_requested = False
        click = Timer(2)
        settle = Timer(.5)
        for _ in self.loop(timeout=75):
            if self._formation_visible():
                if fleet_type_selected(self.device.image, fleet_type):
                    current = bottom_fleet_index(self.device.image, fleet_type)
                    if current == fleet:
                        if settle.reached():
                            logger.attr('详情采集舰队', f'{fleet_type}-{fleet}')
                            return
                        continue
                    if current is not None and click.reached():
                        self.device.click(FLEET_NEXT if current < fleet else FLEET_PREV)
                        click.reset()
                        # 队号可能先于动画更新，继续截图且至少等0.5秒再交给详情入口。
                        settle.reset()
                elif not type_requested:
                    self.device.click(fleet_menu_button(fleet_type))
                    type_requested = True
                    settle.reset()
        raise FleetManagementError(f'未能从底部编号确认{fleet_type}第{fleet}舰队')

    def _capture_formation(self, fleet, fleet_type='surface', *, navigate=True):
        """按固定列采集详情卡面，用于源舰位定位及交换后核对。

        Args:
            navigate (bool): 默认使用通用切队；顺序扫描已核对底部编号时传入False。

        Pages:
            in: Any
            out: page_fleet
        """
        if navigate:
            self.fleet_enter(fleet, fleet_type)
        self.ui_click(FLEET_DETAIL, appear_button=FLEET_DETAIL, check_button=FLEET_DETAIL_CHECK,
                      skip_first_screenshot=True, retry_wait=2)
        # 已确认详情页后获取当前帧，卡面提取与任何文字识别无关。
        self.device.screenshot()
        image = self.device.image.copy()
        portraits = detail_portraits(image, fleet_type)
        occupied = {slot: detail_occupied(image, slot) for slot in portraits}
        if fleet_type == 'surface':
            faces = self.__dict__.setdefault('_slot_portraits', {})
            for slot, portrait in portraits.items():
                if occupied[slot]:
                    faces[fleet, slot] = portrait
                else:
                    faces.pop((fleet, slot), None)
        # 左侧金色“详情界面”只是已选中的页签，点击左上返回关闭详情。
        self.ui_click(BACK_ARROW, appear_button=FLEET_DETAIL_CHECK,
                      check_button=self._formation_visible, retry_wait=2)
        return image, portraits, occupied

    def _prepare_dock(self, *, sort='level'):
        """清空搜索、收藏及多选舰种，保留编队入口本身限定的前后排。

        Pages:
            in: 编队选船页
            out: 编队选船页
        """
        for _ in self.loop(timeout=15):
            if self.appear(DOCK_SEARCH_CLOSED):
                break
            if self.appear_then_click(DOCK_SEARCH_ACTIVE, interval=2):
                continue
        else:
            raise FleetManagementError('未能确认船坞搜索已清空')
        self.dock_favourite_set(False, wait_loading=False)
        self.dock_sort_method_dsc_set(True, wait_loading=False)
        self.dock_filter_set(sort=sort, index='all', faction='all', rarity='all',
                             extra='no_limit', reset_index=True)

    def _prepare_level_dock(self):
        """同一轮扫描和换船只准备一次等级降序，离开选船页时不重置。"""
        if not self.__dict__.get('_level_prepared', False):
            self._prepare_dock()
            self._level_prepared = True

    def _dock_pages(self, scanner, *, max_rows=3, normal_dock=False):
        """滚动并核验物理位移，按已编队最大卡位数确定范围，不依赖OCR早停。

        Pages:
            in: 编队选船页
            out: 同一页面
        """
        from module.retire.dock_scan import DockScan
        self._scan_window = None
        if self.appear(DOCK_EMPTY, offset=(20, 20)):
            return
        from module.retire.dock import DOCK_SCROLL
        bar = DOCK_SCROLL if normal_dock else PICKER_SCROLL
        scroll = Scroll(bar.area, color=bar.color, name=bar.name)
        # 原生滑块顶端有圆角留白；先向轨道外拖动一次，再以顶部像素确认，
        # 不用宽松百分比把靠近顶部的几行当作第一行。
        requested_top = False
        top_retry = Timer(2)
        for _ in self.loop(skip_first=False, timeout=15):
            thumb = np.flatnonzero(scroll.match_color(self))
            if len(thumb) and thumb[0] <= 3 and requested_top:
                break
            if len(thumb) and top_retry.reached():
                x = (scroll.area[0] + scroll.area[2]) // 2
                y = scroll.area[1] + int(np.median(thumb))
                self.device.swipe((x, y), (x, 1), name='编队候选回到顶部')
                requested_top = True
                top_retry.reset()
        else:
            raise FleetManagementError('无法确认船坞顶部，未进行候选点击')
        merger = FormationCardMerger()
        stable, last_offset = None, None
        deadline = Timer(25).start()
        windows_valid, retries = True, 0
        for _ in self.loop(skip_first=False):
            if self.appear(DOCK_EMPTY, offset=(20, 20)):
                return
            if deadline.reached():
                raise FleetManagementError('卡片画面或滚动位移未就绪')
            if not self.appear(DOCK_CHECK):
                continue
            pixels = self.device.image
            signature = pixels[65:720 if normal_dock else 627, 85:1225].astype(np.int16)
            if stable is None or np.mean(np.abs(signature - stable)) > 2:
                stable = signature.copy()
                continue
            try:
                thumb = np.flatnonzero(scroll.match_color(self))
                if not len(thumb):
                    raise ValueError('船坞滚动条未加载')
                if normal_dock:
                    cards = scanner.scan(pixels, bottom=720, has_remove=False)
                else:
                    cards = scanner.scan(pixels, has_remove=thumb[0] <= 3)
                if not cards:
                    raise ValueError('未发现已加载的卡片行')
                merger.add(pixels, cards)
                if last_offset is not None and merger.offset <= last_offset:
                    raise ValueError('拖动后未确认向下滚动')
            except ValueError as exc:
                retries += 1
                if retries >= 3:
                    raise FleetManagementError(str(exc)) from exc
                stable = None
                continue
            self._dock_offset = merger.offset
            window = screenshot_window(self.device)
            if window is None:
                windows_valid = False
            elif windows_valid:
                self._scan_window = (self._scan_window[0] if self._scan_window else window[0], window[1])
            if not windows_valid:
                self._scan_window = None
            yield cards, merger.slots
            first_y = min(y for _, y in merger.slots)
            last_y = max(y for _, y in merger.slots)
            if round((last_y - first_y) / 227) + 1 >= max_rows or thumb[-1] >= scroll.total - 3:
                return
            last_offset = merger.offset
            try:
                DockScan._drag_rows(self, 227)
            except MindCalculatorScanError as exc:
                raise FleetManagementError(str(exc)) from exc
            stable, retries = None, 0
            deadline.reset()

    def _scan_category(self, scanner, max_rows=3):
        slots = []
        images = {}
        for cards, slots in self._dock_pages(scanner, max_rows=max_rows):
            for card in cards:
                images[id(card)] = VisualDockScanner.portrait(self.device.image, card).copy()
        result = {}
        self._reference_portraits = {}
        for card, _ in slots:
            if card.fleet > 0:
                result.setdefault(card.fleet, []).append(card.ship)
                self._reference_portraits.setdefault(str(card.fleet), []).append(images[id(card)])
        return self._normalize_result(result)

    def _retry_unknown_morale(self, scanner, result, dock, formations, portraits, images, windows=None):
        """未知心情所在排只补扫一遍；仍需卡面唯一对应，不覆盖已确认的读数。

        Pages:
            in: page_fleet，详情采集已完成
            out: page_fleet
        """
        pending = {category: next((int(fleet) for fleet, ships in teams.items()
                                  if any(ship.get('emotion') is None for ship in ships)), None)
                   for category, teams in result.items()}
        pending = {category: fleet for category, fleet in pending.items() if fleet is not None}
        if not pending:
            return
        for category, fleet in pending.items():
            logger.attr('补读未知心情', category)
            kind = 'submarine' if category == 'submarine' else 'surface'
            self.fleet_enter(fleet, kind)
            self._open_slot(4 if category == 'vanguard' else 1, kind)
            try:
                self._prepare_level_dock()
                dock[category] = self._scan_category(scanner, max_rows=2 if kind == 'submarine' else 3)
                portraits[category] = self._reference_portraits
                if windows is not None:
                    previous = windows.get(category)
                    windows[category] = (previous[0], self._scan_window[1]) if previous and self._scan_window else None
            finally:
                self._close_picker()
        reread = combine_references(dock, formations, portraits, images)
        for category in pending:
            for fleet, ships in result[category].items():
                values = {ship['slot']: ship.get('emotion') for ship in reread[category].get(fleet, [])}
                for ship in ships:
                    value = values.get(ship['slot'])
                    if ship.get('emotion') is None and type(value) is int and 0 <= value <= 150:
                        ship['emotion'] = value

    def run(self, update_emotion=None):
        """从第一舰队舰位4扫描，详情固定列记录舰位，文字只作参考。

        Pages:
            in: Any
            out: page_fleet
        """
        logger.hr('舰队编队参考扫描', level=0)
        self._level_prepared = False
        if update_emotion is None:
            update_emotion = self.config.cross_get('FleetInfo.FleetInfo.UpdateEmotion', True)
        scanner = FormationDockScanner(update_emotion=update_emotion)
        details = FormationDetailScanner()
        dock, windows, dock_portraits = {}, {}, {}
        if not self.device.has_cached_image:
            self.device.screenshot()
        self.ui_ensure(page_fleet)
        if self._formation_visible() and fleet_type_selected(self.device.image, 'submarine'):
            self._scan_fleet_enter(1, 'surface')
        reset_first = self.dock_filter.reset_first
        try:
            self.dock_filter.reset_first = False
            for category, fleet_type, slot in (('vanguard', 'surface', 4), ('main', 'surface', 1),
                                                ('submarine', 'submarine', 1)):
                # 新进入编队即为第一水面舰队；返回选船页也保留当前队伍，无需展开列表。
                if fleet_type == 'submarine':
                    self._enter_scan_submarine()
                self._open_slot(slot, fleet_type)
                try:
                    self._prepare_level_dock()
                    dock[category] = self._scan_category(scanner, max_rows=3 if fleet_type == 'surface' else 2)
                    windows[category] = self._scan_window
                    dock_portraits[category] = getattr(self, '_reference_portraits', {})
                finally:
                    self._close_picker()
            formations = {'surface': {}, 'submarine': {}}
            detail_images = {'surface': {}, 'submarine': {}}
            for fleet_type, count in (('surface', 6), ('submarine', 2)):
                for fleet in range(1, count + 1):
                    self._scan_fleet_enter(fleet, fleet_type)
                    image, _, _ = self._capture_formation(fleet, fleet_type, navigate=False)
                    formations[fleet_type][fleet] = details.scan(image, fleet_type)
                    detail_images[fleet_type][fleet] = image
            result = combine_references(dock, formations, dock_portraits, detail_images)
            if update_emotion:
                self._retry_unknown_morale(scanner, result, dock, formations, dock_portraits, detail_images, windows)
                learn_fleet_emotion(self.config, result, windows, set(scanner.matcher.names))
            else:
                preserve_emotions(result, self.config.cross_get(self.RESULT_PATH, {}))
            self._save_result(result)
            self._rotation_pool = {category: (dock[category], dock_portraits[category])
                                   for category in ('main', 'vanguard')}
        finally:
            self.dock_filter.reset_first = reset_first

        from module.runtime.fleet_training import mark_full_scan
        mark_full_scan(self.config)

    def _visual_candidates(self, scanner, matcher, max_rows):
        found = []
        for cards, _ in self._dock_pages(scanner, max_rows=max_rows):
            for card in cards:
                score = matcher.score(scanner.portrait(self.device.image, card))
                if score >= 12:
                    absolute_y = card.y + self._dock_offset
                    existing = next((index for index, item in enumerate(found)
                                     if item[0].col == card.col and abs(item[1] - absolute_y) <= 12), None)
                    if existing is None:
                        found.append((card, absolute_y, score))
                    elif score > found[existing][2]:
                        found[existing] = (card, absolute_y, score)
        return found

    def highest_morale_slot(self, source_fleet, fleet, slot):
        """从目标舰位的同排候选中，按游戏心情降序选指定来源队的第一张卡。

        Pages:
            in: Any
            out: page_fleet
        """
        validate_swap(source_fleet, slot, fleet, slot)
        self.fleet_enter(fleet)
        self._open_slot(slot)
        scanner = VisualDockScanner()
        selected = None
        try:
            self._prepare_dock(sort='mood')
            for cards, _ in self._dock_pages(scanner):
                candidates = [card for card in cards if card.fleet == source_fleet]
                if candidates:
                    card = min(candidates, key=lambda item: (item.y, item.col))
                    selected = scanner.portrait(self.device.image, card).copy()
                    break
        finally:
            self.dock_reset()
            self._close_picker()
        if selected is None:
            raise FleetManagementError(f'当前舰位候选中未找到第{source_fleet}舰队可交换舰船')
        _, portraits, occupied = self._capture_formation(source_fleet)
        matcher = PortraitMatcher(selected)
        scores = sorted(((matcher.score(portrait), position) for position, portrait in portraits.items()
                         if occupied[position] and (position <= 3) == (slot <= 3)), reverse=True)
        if not scores or scores[0][0] < 12 or (len(scores) > 1 and scores[1][0] >= scores[0][0] * .75):
            raise FleetManagementError('最高心情候选卡面未能对应唯一来源舰位，尚未执行互换')
        return scores[0][1]

    def read_fleet_morale(self, fleet, *, first_slot=4):
        """先扫描目标队前后排，再采集详情，将名称和实测心情写回固定舰位。

        Pages:
            in: Any
            out: page_fleet
        """
        if first_slot not in (1, 4):
            raise ValueError('心情刷新入口只能为舰位1或4')
        scanner = FormationDockScanner(update_emotion=True)
        dock, portraits = {}, {}
        entries = [('vanguard', 4), ('main', 1)]
        if first_slot == 1:
            entries.reverse()
        reset_first = self.dock_filter.reset_first
        try:
            self.dock_filter.reset_first = False
            self.fleet_enter(fleet)
            for category, slot in entries:
                self._open_slot(slot)
                try:
                    self._prepare_level_dock()
                    dock[category] = self._scan_category(scanner)
                    portraits[category] = self._reference_portraits
                finally:
                    self._close_picker()
            image, _, _ = self._capture_formation(fleet, navigate=False)
            positions = FormationDetailScanner().scan(image)
            refreshed = combine_references(dock, {'surface': {fleet: positions}}, portraits,
                                           {'surface': {fleet: image}})
            self._retry_unknown_morale(scanner, refreshed, dock, {'surface': {fleet: positions}}, portraits,
                                       {'surface': {fleet: image}})
        finally:
            self.dock_filter.reset_first = reset_first
        result = deepcopy(self.config.cross_get(self.RESULT_PATH, {}))
        if not isinstance(result, dict):
            result = {}
        for category in ('main', 'vanguard'):
            result.setdefault(category, {})[str(fleet)] = refreshed[category].get(str(fleet), [])
        self._save_result(result)
        return {ship['slot']: ship.get('emotion') for category in ('main', 'vanguard')
                for ship in result[category][str(fleet)]}

    def _verify_plan(self, captures, expected, original):
        for fleet, positions in expected.items():
            _, portraits, occupied = captures[fleet]
            for slot, token in positions.items():
                if token is None:
                    if occupied[slot]:
                        raise FleetManagementError(f'第{fleet}舰队舰位{slot}应为空，但画面仍有舰船')
                elif not occupied[slot] or PortraitMatcher(original[token]).score(portraits[slot]) < 12:
                    raise FleetManagementError(f'第{fleet}舰队舰位{slot}的卡面尚未与交换预期对应')

    def rotation_readings(self):
        """返回最近选船页快照中各实际舰队的固定舰位心情。"""
        result = self.__dict__.get('_rotation_result', self.config.cross_get(self.RESULT_PATH, {}))
        return {fleet: {ship['slot']: ship.get('emotion') for category in ('main', 'vanguard')
                        for ship in result.get(category, {}).get(str(fleet), [])}
                for fleet in range(1, 7)}

    @staticmethod
    def _rotation_reference_index(ship, pool, portraits, portrait=None, used=()):
        if portrait is not None:
            if len(portraits) != len(pool):
                return None
            matcher = PortraitMatcher(portrait)
            ranked = sorted(((matcher.score(face), index) for index, face in enumerate(portraits)
                             if index not in used), reverse=True)
            if ranked and ranked[0][0] >= 12 and (len(ranked) == 1 or ranked[1][0] < ranked[0][0] * .75):
                return ranked[0][1]
            return None
        matches = [index for index, item in enumerate(pool) if index not in used and ship.get('name')
                   and item.get('name') == ship['name'] and item.get('level') == ship.get('level')]
        return matches[0] if len(matches) == 1 else None

    def _scan_rotation_category(self, category, *, fleets=None):
        """更新当前排的参考；指定 fleets 时仅实读这些实际舰队，不退出或重设排序。"""
        result = deepcopy(self.__dict__.get('_rotation_result', self.config.cross_get(self.RESULT_PATH, {})))
        if fleets is not None:
            scanner = FormationDockScanner(update_emotion=True, fleets=fleets)
        else:
            scanner = self.__dict__.get('_rotation_scanner')
            if scanner is None:
                scanner = self._rotation_scanner = FormationDockScanner(update_emotion=True)
        faces = self.__dict__.setdefault('_slot_portraits', {})
        matched = set()
        for attempt in range(2):
            dock = self._scan_category(scanner)
            portraits = self._reference_portraits
            self.__dict__.setdefault('_rotation_pool', {})[category] = (dock, portraits)
            for fleet, ships in result.get(category, {}).items():
                if fleets is not None and int(fleet) not in fleets:
                    continue
                pool, pictures = dock.get(fleet, []), portraits.get(fleet, [])
                used = set()
                for ship in ships:
                    key = int(fleet), ship['slot']
                    index = self._rotation_reference_index(ship, pool, pictures, faces.get(key), used)
                    value = None
                    if index is not None:
                        used.add(index)
                        matched.add(key)
                        reference = pool[index]
                        value = reference.get('emotion')
                        if reference.get('name'):
                            ship.update(name=reference['name'], review=reference.get('review', False))
                        if reference.get('level'):
                            ship['level'] = reference['level']
                        if key not in faces and len(pictures) == len(pool):
                            faces[key] = pictures[index]
                    if not attempt or value is not None:
                        ship['emotion'] = value
            if all(ship.get('emotion') is not None for fleet, ships in result.get(category, {}).items()
                   if fleets is None or int(fleet) in fleets for ship in ships):
                break
        self._save_result(result)
        self._rotation_scanned_slot = self._rotation_picker
        return matched

    def prepare_rotation(self, fleet, *, slots=None, fleets=None, scan=True):
        """从目标舰位进入选船页，刷新参考或复用本轮已核实的卡面池。

        Args:
            slots: 优先进入的勾选舰位；默认从4位读前排，再从1位读后排。
            fleets: 限定实读的实际舰队；默认读取全部已编队舰船。
            scan: False 时复用本轮已有卡面池，直接打开第一个目标舰位。

        Pages:
            in: Any
            out: 目标舰队当前舰位的选船页
        """
        if not (self._formation_visible() and fleet_type_selected(self.device.image, 'surface')
                and bottom_fleet_index(self.device.image) == fleet and selector_closed(self.device.image)):
            self.fleet_enter(fleet)
        self._rotation_fleet = fleet
        if not scan:
            # 候补已在本轮扫描，打开实际换船舰位，沿用已核实的卡面池。
            slot = next(iter(slots or (1,)))
            self._open_slot(slot)
            self._rotation_picker = fleet, slot
            self._prepare_level_dock()
            return self.rotation_readings()
        entries = {}
        for slot in slots or ():
            entries.setdefault('main' if slot <= 3 else 'vanguard', slot)
        for category, slot in (('vanguard', 4), ('main', 1)):
            entries.setdefault(category, slot)
        for index, (category, slot) in enumerate(entries.items()):
            self._open_slot(slot)
            self._rotation_picker = fleet, slot
            self._prepare_level_dock()
            if fleets is None:
                self._scan_rotation_category(category)
            else:
                self._scan_rotation_category(category, fleets=fleets)
            if index < len(entries) - 1:
                self._close_picker()
                self._rotation_picker = None
        return self.rotation_readings()

    def _rotation_card(self, matcher, source):
        scanner = VisualDockScanner()

        def locate(cards):
            matches = [(card, card.y, matcher.score(scanner.portrait(self.device.image, card)))
                       for card in cards if card.fleet == source]
            if not matches or max(item[2] for item in matches) < 12:
                return None
            try:
                return choose_portrait(matches, source)[0]
            except ValueError as exc:
                raise FleetManagementError('来源队存在重复卡面，无法唯一确认当前舰位') from exc

        # 刚完成本舰位扫描时，先使用当前可见卡面；其他情况从新截图核验滚动。
        if self.__dict__.get('_rotation_scanned_slot') == self._rotation_picker:
            card = locate(scanner.scan(self.device.image))
            if card is not None:
                return card
        for cards, _ in self._dock_pages(scanner):
            card = locate(cards)
            if card is not None:
                return card
        raise FleetManagementError('当前选船页未能确认来源舰位卡面，下次自动重扫')

    def rotate_slot(self, source, slot, fleet):
        """从当前目标队选船页按同号舰位互换，换后仅刷新当前排。

        Pages:
            in: prepare_rotation确认的目标队选船页，或同队编队页
            out: 当前互换舰位的选船页，信息已刷新
        """
        validate_swap(source, slot, fleet, slot)
        if self.__dict__.get('_rotation_fleet') != fleet:
            raise FleetManagementError('当前选船页未确认目标舰队，下次自动重扫')
        category = 'main' if slot <= 3 else 'vanguard'
        result = deepcopy(self._rotation_result)
        ships = {number: next((ship for ship in result.get(category, {}).get(str(number), [])
                               if ship['slot'] == slot), None) for number in (source, fleet)}
        if ships[source] is None:
            raise FleetManagementError('同号来源舰位缺少最新信息，下次自动重扫')
        if ships[fleet] is None:
            # 空位添船可能压缩来源舰位，保留通用操作已有的空位及提交核验。
            self.finish_rotation()
            self.swap_slots(source, slot, fleet, slot)
            self._open_slot(slot)
            self._rotation_picker = fleet, slot
            self._scan_rotation_category(category, fleets={source, fleet})
            return self.rotation_readings()
        pool, portraits = self._rotation_pool[category]
        source_pool, source_faces = pool.get(str(source), []), portraits.get(str(source), [])
        faces = self.__dict__.setdefault('_slot_portraits', {})
        index = self._rotation_reference_index(ships[source], source_pool, source_faces, faces.get((source, slot)))
        if index is None or len(source_faces) != len(source_pool):
            raise FleetManagementError('来源舰位不能对应唯一候选，下次自动重扫')
        # 保留固定舰位卡面，避免船坞裁剪中的公共边框和同队徽标误匹配其他船。
        matcher = PortraitMatcher(faces.get((source, slot), source_faces[index]))
        if self._rotation_picker != (fleet, slot):
            if self._rotation_picker is not None:
                self._close_picker()
            self._open_slot(slot)
            self._rotation_picker = fleet, slot
        card = self._rotation_card(matcher, source)
        baseline = self.device.image.copy()
        self.device.click(position_button((card.x + 20, card.y + 40, card.x + 115, card.y + 145), '源舰位卡面'))
        self._confirm_replacement(baseline)
        self._rotation_picker = None
        for number, other in ((source, fleet), (fleet, source)):
            result[category][str(number)] = [dict(ships[other], slot=slot) if ship['slot'] == slot else ship
                                           for ship in result[category][str(number)]]
        source_face, target_face = faces.get((source, slot)), faces.get((fleet, slot))
        for number, face in ((source, target_face), (fleet, source_face)):
            if face is None:
                faces.pop((number, slot), None)
            else:
                faces[number, slot] = face
        self._rotation_result = result
        self._open_slot(slot)
        self._rotation_picker = fleet, slot
        matched = self._scan_rotation_category(category, fleets={source, fleet})
        if not {(source, slot), (fleet, slot)} <= matched:
            raise FleetManagementError('互换后双方卡面归属未读全，下次自动重扫实际编队')
        return self.rotation_readings()

    def finish_rotation(self):
        """退出最后一个选船页，保留当前队号和等级排序，交还正常选关导航。"""
        if self.__dict__.get('_rotation_picker') is not None:
            self._close_picker()
            self._rotation_picker = None

    def _save_swap_reference(self, expected, fleet_type):
        result = deepcopy(self.config.cross_get(self.RESULT_PATH, {}))
        if not isinstance(result, dict):
            result = {}
        categories = ('main', 'vanguard') if fleet_type == 'surface' else ('submarine',)
        originals = {}
        for category in categories:
            for fleet in expected:
                for ship in result.get(category, {}).get(str(fleet), []):
                    if isinstance(ship, dict) and type(ship.get('slot')) is int:
                        originals[f'{fleet}:{ship["slot"]}'] = ship
        for category in categories:
            result.setdefault(category, {})
            for fleet, positions in expected.items():
                ships = []
                for slot in CATEGORY_SLOTS[category]:
                    token = positions[slot]
                    if token is not None:
                        ship = deepcopy(originals.get(token, dict(name='', level=0, emotion=None, review=True)))
                        ship['slot'] = slot
                        ships.append(ship)
                result[category][str(fleet)] = ships
        self._save_result(result)

    def swap_slots(self, source_fleet, source_slot, fleet, slot, *, fleet_type='surface',
                   update_emotion=False):
        """按源舰队/舰位与目标舰队/舰位互换；操作与OCR完全分离。

        Args:
            source_fleet: 源水面舰队1–6或潜艇编队1–2。
            source_slot: 源水面舰位1–6或潜艇舰位1–3。
            fleet: 目标舰队号。
            slot: 目标舰位号。
            fleet_type: surface或submarine；水面前后排不可互换。
            update_emotion: 交换完成后是否重新扫描参考信息及心情。

        Returns:
            dict: 实际图像核验通过的舰位变更标记，以及参考信息刷新状态。

        Pages:
            in: Any
            out: page_fleet
        """
        validate_swap(source_fleet, source_slot, fleet, slot, fleet_type)
        if (source_fleet, source_slot) == (fleet, slot):
            return dict(changed=False, reference_updated=False)
        logger.hr(f'舰位互换 {source_fleet}-{source_slot} → {fleet}-{slot}', level=0)
        before = {number: self._capture_formation(number, fleet_type) for number in dict.fromkeys((source_fleet, fleet))}
        try:
            expected = slot_swap_plan({number: capture[2] for number, capture in before.items()},
                                      source_fleet, source_slot, fleet, slot, fleet_type)
        except ValueError as exc:
            raise FleetManagementError(str(exc)) from exc
        original = {f'{number}:{position}': image for number, capture in before.items()
                    for position, image in capture[1].items()}
        matcher = PortraitMatcher(before[source_fleet][1][source_slot])
        scanner = VisualDockScanner()
        max_rows = 3 if fleet_type == 'surface' else 2
        reset_first = self.dock_filter.reset_first
        clicked, verified = False, False
        try:
            self.dock_filter.reset_first = False
            self.fleet_enter(fleet, fleet_type)
            self._open_slot(slot, fleet_type)
            self._prepare_dock()
            try:
                choose_portrait(self._visual_candidates(scanner, matcher, max_rows), source_fleet)
            except ValueError as exc:
                raise FleetManagementError(str(exc)) from exc
            # 回到顶部后重新取得当前位置，不能使用上一轮滚动前的点击坐标。
            found = None
            for cards, _ in self._dock_pages(scanner, max_rows=max_rows):
                matches = [card for card in cards if card.fleet == source_fleet and
                           matcher.score(scanner.portrait(self.device.image, card)) >= 12]
                if len(matches) > 1:
                    raise FleetManagementError('来源队存在重复卡面，无法区分同名舰船，尚未点击')
                found = matches[0] if matches else None
                if found is not None:
                    break
            if found is None:
                raise FleetManagementError('未能重新确认来源队的唯一卡面，尚未点击')
            baseline = self.device.image.copy()
            area = (found.x + 20, found.y + 40, found.x + 115, found.y + 145)
            clicked = True
            self.device.click(position_button(area, '源舰位卡面'))
            self._confirm_replacement(baseline)
            after = {number: self._capture_formation(number, fleet_type) for number in expected}
            self._verify_plan(after, expected, original)
            self._commit_formation()
            after = {number: self._capture_formation(number, fleet_type) for number in expected}
            self._verify_plan(after, expected, original)
            self._save_swap_reference(expected, fleet_type)
            verified = True
        except (GameStuckError, GameTooManyClickError) as exc:
            # 交换可能已发生，不能让通用重启恢复重复执行一次互换。
            raise FleetManagementError(f'舰位互换画面未确认，需要检查当前编队：{exc}') from exc
        finally:
            self.dock_filter.reset_first = reset_first
            if clicked and not verified:
                # 只有实际操作后的画面核对失败才使受影响记录失效；OCR不会走到这里。
                result = deepcopy(self.config.cross_get(self.RESULT_PATH, {}))
                if isinstance(result, dict):
                    for category in (('main', 'vanguard') if fleet_type == 'surface' else ('submarine',)):
                        for number in expected:
                            result.get(category, {}).pop(str(number), None)
                    self._save_result(result)
            if self.appear(DOCK_CHECK, offset=(20, 20)):
                try:
                    self.dock_reset()
                    self._close_picker()
                except (GameStuckError, GameTooManyClickError) as exc:
                    raise FleetManagementError(f'选船页清理未完成，需要检查当前编队：{exc}') from exc
        reference_updated = False
        if update_emotion:
            try:
                self.run(update_emotion=True)
                reference_updated = True
            except (FleetManagementError, GameStuckError, GameTooManyClickError) as exc:
                logger.warning(f'舰位互换已完成，参考信息尚未刷新：{exc}')
        return dict(changed=True, positions=expected, reference_updated=reference_updated)

    def _confirm_replacement(self, baseline):
        """以单选计数图像的变化确认选中，再确认本次允许的交换。

        Pages:
            in: 刚点击候选卡片的选船页
            out: page_fleet
        """
        confirm = Timer(2)
        submitted = False
        for _ in self.loop(skip_first=False, timeout=25):
            if self._formation_visible():
                return
            if self.appear(DOCK_CHECK) and selected_count_changed(baseline, self.device.image) and confirm.reached():
                self.device.click(PICKER_CONFIRM)
                submitted = True
                confirm.reset()
                continue
            if submitted and self.handle_popup_confirm('FLEET_SLOT_EXCHANGE'):
                continue
        raise FleetManagementError('选船画面未确认完成本次交换；没有读取OCR或重复点选卡片')

    def _commit_formation(self):
        """返回主界面提交游戏编队，意外弹窗不自动确认。

        Pages:
            in: page_fleet
            out: page_main
        """
        click = Timer(2)
        for _ in self.loop(skip_first=False, timeout=25):
            if self.is_in_main():
                return
            if self._formation_visible() and click.reached():
                self.device.click(BACK_ARROW)
                click.reset()
        raise FleetManagementError('尚未确认游戏已提交编队；检查当前游戏提示后再操作')
