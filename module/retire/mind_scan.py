"""复用 AP 设备和船坞导航的心智单元扫描任务。"""
from datetime import datetime
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
from PIL import Image

import module.config.server as server
from module.base.timer import Timer
from module.base.utils import color_similarity_2d
from module.exception import (GamePageUnknownError, GameStuckError, GameTooManyClickError,
                              MindCalculatorScanError)
from module.logger import logger
from module.retire.assets import DOCK_EMPTY, DOCK_FILTER_CONFIRM, DOCK_SEARCH_ACTIVE, DOCK_SEARCH_CLOSED
from module.retire.dock import CARD_GRIDS, DOCK_SCROLL, Dock
from module.runtime.mind_calculator import (RESULT_PATH, calculate, editable_ship, find_ship,
                                          highest_ships, preserve_exclusions, revision)
from module.runtime.mind_recognition import Card, ScanMerger, ScanPolicy, ScrollMotion, grid_rows, recognize_cards
from module.runtime.scan_metrics import CachedOcr, ScanMetrics
from module.runtime.mind_identity import MindIdentity
from module.ui.page import page_dock, page_main


class MindCalculatorScan(Dock):
    evidence_folder = 'mind_scan'
    scan_label = '心智扫描'

    def _make_merger(self):
        return ScanMerger()

    def _read_cards(self, image, source, names, levels):
        return recognize_cards(image, source, name_ocr=names, level_ocr=levels,
                               identity=getattr(self, '_identity', None), metrics=getattr(self, '_metrics', None))

    def _check_scan_page(self, cards, at_bottom):
        """检查已加载行列；真实末页允许最后一排末尾不足七艘。"""
        rows = sorted({card.y for card in cards})
        columns = [{card.col for card in cards if card.y == y} for y in rows]
        if (not columns or any(cols != set(range(7)) for cols in columns[:-1])
                or columns[-1] != set(range(len(columns[-1])))
                or not at_bottom and (len(rows) != 3 or len(cards) != 21)):
            raise ValueError('扫描卡片未完整加载或存在缺格')

    @staticmethod
    def _has_partial_tail(cards):
        """三排中只有末排末尾缺格时，下一步必须保留整排重叠复核。"""
        rows = sorted({card.y for card in cards})
        columns = [{card.col for card in cards if card.y == y} for y in rows]
        return (len(rows) == 3 and all(cols == set(range(7)) for cols in columns[:2])
                and 0 < len(columns[-1]) < 7 and columns[-1] == set(range(len(columns[-1]))))

    def run(self):
        """按阵营扫描指定等级范围；局部失败保留结果并继续后续阵营。

        Pages:
            in: Any
            out: page_dock
        """
        if server.server != 'cn':
            raise MindCalculatorScanError('心智单元计算器当前内置国服舰船资料，请在国服实例使用自动扫描')
        from module.ocr.al_ocr import AlOcr
        from module.config.deep import deep_get, deep_set
        from module.config.transaction import config_transaction
        from module.config.utils import filepath_config
        logger.hr('心智单元船坞扫描', level=0)
        logger.attr('心智扫描源码', f'{Path(__file__).resolve()} SHA256 {sha256(Path(__file__).read_bytes()).hexdigest()}')
        self._scan_evidence_paths = set()
        self._metrics = ScanMetrics()
        self._scan_metadata = dict(reached_bottom=False, physical_count=0)
        try:
            self._identity = MindIdentity()
        except (MemoryError, ValueError, KeyError, OSError) as exc:
            raise MindCalculatorScanError(f'舰船目录初始化失败，保留旧清单：{type(exc).__name__}') from exc
        try:
            self._policy = ScanPolicy(self.config.MindCalculator_MinLevel, self.config.MindCalculator_MaxLevel,
                                      sorted_desc=True)
        except ValueError as exc:
            raise MindCalculatorScanError(str(exc)) from exc
        logger.attr('扫描等级范围', f'{self._policy.min_level}–{self._policy.max_level}（含边界）')
        previous_ships = deep_get(self.config.data, RESULT_PATH, {}).get('ships', [])
        previous_revision = revision(previous_ships)
        self._enter_scan_dock()
        self.dock_reset()
        # 通用 reset 服务于退役的升序流程；本任务需要明确切换为等级降序。
        self.dock_sort_method_dsc_set(True)
        full_range = (self._policy.min_level, self._policy.max_level) == (1, 125)
        expected_count = None
        if full_range:
            from module.runtime.scan_dock_amount import SCAN_DOCK_AMOUNT
            try:
                with self._metrics.measure('dock_count'):
                    count, remaining, capacity = SCAN_DOCK_AMOUNT.ocr(self.device.image)
                if capacity > 0 and 0 <= count <= capacity and count + remaining == capacity:
                    expected_count = count
            except (MemoryError, RuntimeError, ValueError) as exc:
                logger.warning(f'船坞数量读取失败，继续按阵营扫描：{exc}')
            if expected_count is None:
                logger.warning('船坞数量未确认，扫描完成后仅记录数量提示')
            logger.attr('完整扫描预期容量占用数量', expected_count)
        names = CachedOcr(AlOcr(config=self.config, name='ppocr_v6', save_debug_images=False), self._metrics, 'name_ocr')
        levels = CachedOcr(AlOcr(config=self.config, name='azur_lane', save_debug_images=False), self._metrics, 'level_ocr')
        ships = self._scan_factions(names, levels, previous_ships)
        if full_range:
            self._verify_full_count(expected_count)
        ships = [editable_ship(ship) for ship in preserve_exclusions(ships, previous_ships)]
        # 扫描期间用户可能修改数据；复读当前配置避免覆盖手工修正。
        with self._metrics.measure('save'), config_transaction(filepath_config(self.config.config_name)):
            latest = self.config.read_file(self.config.config_name)
            if revision(deep_get(latest, RESULT_PATH, {}).get('ships', [])) != previous_revision:
                raise MindCalculatorScanError('扫描期间舰船数据已修改，保留现有数据；请重新扫描')
            # 同一清单重复保存只会更新日期；通过版本检查后更新本字段基线，
            # 让通用配置保存继续保护其他字段，同时允许提交已完成的扫描。
            if hasattr(self.config, '_loaded_data'):
                import copy
                deep_set(self.config._loaded_data, RESULT_PATH, copy.deepcopy(deep_get(latest, RESULT_PATH, {})))
            self.config.modified[RESULT_PATH] = dict(ships=ships, updated_at=datetime.now().isoformat(timespec='seconds'))
            self.config.save()
        self._prune_scan_evidence()
        logger.attr('扫描阶段基准', json.dumps(self._metrics.snapshot(), ensure_ascii=False))
        result = calculate(ships)
        logger.info(f'[心智扫描] 已保存 {len(ships)} 艘，计入 {result["included"]} 艘，'
                    f'待核对 {result["review"]} 艘，心智单元Ⅰ {result["mind"]}，物资 {result["gold"]}')

    def _verify_full_count(self, expected):
        """数量仅作诊断，不因漏读或重叠计数丢弃整次结果；容量不含 META。"""
        raw = getattr(self, '_scan_raw_ships', [])
        meta = sum(bool((info := find_ship(row['name'], row.get('group_type')))
                        and info['nationality'] == 97) for row in raw)
        actual, occupied = len(raw), len(raw) - meta
        self._scan_metadata.update(physical_count=actual, occupied_count=occupied, meta_count=meta)
        confirmed = (expected is not None and self._scan_metadata.get('reached_bottom')
                     and self._scan_metadata.get('coverage_exact', True) and occupied == expected
                     and not any(row.get('candidates') for row in raw))
        message = f'占容量 {occupied}/{expected}，META {meta}，物理卡位 {actual}'
        if confirmed:
            logger.attr('完整扫描物理数量核验', message)
        else:
            logger.warning(f'完整扫描数量提示：{message}；保留已读结果，不中止保存')
        return confirmed

    def _scan_factions(self, names, levels, previous):
        """每个阵营只扫一次，目录限定在已核实按钮范围内。"""
        factions = ((1, 'eagle', '白鹰'), (2, 'royal', '皇家'), (3, 'sakura', '重樱'),
                    (4, 'iron', '铁血'), (5, 'dragon', '东煌'), (6, 'sardegna', '撒丁帝国'),
                    (7, 'northern', '北方联合'), (8, 'iris', '自由鸢尾'), (9, 'vichya', '维希教廷'),
                    (11, 'tulipa', '郁金王国'), (12, 'pedreria', '晶环联盟'),
                    (97, 'meta', 'META'), (96, 'tempesta', '飓风'), (None, 'other', '其他'))
        full_identity = self._identity
        known = {nation for nation, _, _ in factions if nation is not None}
        output, raw, completed = [], [], []
        exact, reached_bottom = True, True
        self._continuous_scan = True
        try:
            for nation, faction, label in factions:
                nationalities = {nation} if nation is not None else {
                    row['nationality'] for row in full_identity.ships.values() if row['nationality'] not in known}
                self._identity = MindIdentity(nationalities, continuous=True)
                if not self._identity.ships:
                    continue
                self._phase_ships = []
                self._scan_raw_ships = []
                self._scan_metadata = dict(reached_bottom=False, physical_count=0, coverage_exact=True, finished=False)
                logger.hr(f'心智扫描阵营：{label}', level=2)
                try:
                    self._set_identity_faction(faction, wait_loading=False)
                    self._scan_faction_pages(names, levels, label)
                except (MindCalculatorScanError, GameStuckError, GameTooManyClickError,
                        MemoryError, RuntimeError, ValueError) as exc:
                    logger.warning(f'[{label}] 局部扫描失败，保留已读结果并继续下一阵营：{exc}')
                    exact = False
                    if isinstance(exc, (GameStuckError, GameTooManyClickError)) and (
                            self.appear(page_dock.check_button) or self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60))):
                        # 已确认仍在扫描页面；开始下一阵营时清除上个局部循环的检测记录。
                        self.device.stuck_record_clear()
                        self.device.click_record_clear()
                found = list(self._phase_ships)
                if not self._scan_metadata.get('finished'):
                    # 未完成阵营保留其已有记录，不能因一页/一次模型故障清空整片阵营。
                    found += [dict(row) for row in previous
                              if (info := find_ship(row['name'], row.get('group_type')))
                              and info['nationality'] in nationalities
                              and (row.get('review') or self._policy.min_level <= row['level'] <= self._policy.max_level)]
                    exact = False
                else:
                    completed.append(label)
                output.extend(found)
                raw.extend(self._scan_raw_ships)
                reached_bottom = reached_bottom and self._scan_metadata.get('reached_bottom', False)
                exact = exact and self._scan_metadata.get('coverage_exact', True)
                logger.attr(f'{label}扫描结果', len(highest_ships(found)))
        finally:
            self._identity = full_identity
            self._continuous_scan = False
        self._scan_raw_ships = raw
        self._scan_metadata = dict(reached_bottom=reached_bottom, physical_count=len(raw), coverage_exact=exact)
        logger.attr('已完成扫描阵营', '、'.join(completed))
        if not output and not completed:
            raise MindCalculatorScanError('所有阵营均未能读取，保留旧清单')
        try:
            self._set_identity_faction('all', wait_loading=False)
        except (MindCalculatorScanError, GameStuckError, GameTooManyClickError) as exc:
            logger.warning(f'扫描结果已保留，恢复全阵营筛选失败：{exc}')
        return highest_ships(output)

    def _scan_faction_pages(self, names, levels, label):
        """重叠翻页，不强制三排精确停位；读图失败先重试，再前进继续。

        Pages:
            in: page_dock
            out: page_dock
        """
        merger, motion = self._make_merger(), ScrollMotion()
        stable, empty = Timer(.25, count=1).start(), Timer(1.2, count=3).start()
        waiting = Timer(12).start()
        previous = accepted = None
        accepted_thumb = None
        last_drag = None
        page = failures = unread_pages = stalled = top_attempts = 0
        positioning = True
        while page < 500:
            with self._metrics.measure('screenshot'):
                self.device.screenshot()
            if self.handle_popup_confirm():
                previous = None
                stable.reset()
                continue
            if waiting.reached():
                logger.warning(f'[{label}] 当前画面持续不可读，保留本阵营已读结果并继续下一阵营')
                break
            if not self.appear(page_dock.check_button):
                continue
            if self.appear(DOCK_EMPTY):
                # 切换筛选后会短暂显示空列表，必须在新截图上连续确认。
                if empty.reached():
                    self._scan_metadata.update(reached_bottom=True, finished=True)
                    break
                continue
            empty.reset()
            with self._metrics.measure('stability'):
                pixels = self._stable_pixels(self.device.image)
            if previous is None or previous.shape != pixels.shape or cv2.mean(cv2.absdiff(pixels, previous))[0] > 1:
                previous = pixels.copy()
                stable.reset()
                continue
            if not stable.reached():
                continue
            image = Image.fromarray(self.device.image)
            try:
                thumb = self._dock_scroll_thumb()
            except MindCalculatorScanError:
                thumb = None
            if positioning:
                if thumb is not None and thumb[0] > 2 and len(thumb) < DOCK_SCROLL.total - 2 and top_attempts < 2:
                    x = (DOCK_SCROLL.area[0] + DOCK_SCROLL.area[2]) // 2
                    self.device.swipe((x, DOCK_SCROLL.area[1] + int(np.median(thumb))),
                                      (x, DOCK_SCROLL.area[1] + 1), name='阵营扫描回顶')
                    top_attempts += 1
                    previous = None
                    stable.reset()
                    continue
                if thumb is not None and thumb[0] > 2 and len(thumb) < DOCK_SCROLL.total - 2:
                    self._scan_metadata['coverage_exact'] = False
                    logger.warning(f'[{label}] 回顶未完全确认，继续读取当前可见卡片')
                positioning = False
            same = accepted is not None and pixels.shape == accepted.shape and cv2.mean(cv2.absdiff(pixels, accepted))[0] <= 1
            thumb_moved = (thumb is not None and accepted_thumb is not None
                           and not np.array_equal(thumb, accepted_thumb))
            stalled = stalled + 1 if same and last_drag is not None and not thumb_moved else 0
            if stalled >= 2:
                bottom = self._dock_scroll_at_bottom(thumb)
                self._scan_metadata.update(finished=bottom, reached_bottom=bottom)
                if not self._scan_metadata['reached_bottom']:
                    self._scan_metadata['coverage_exact'] = False
                    logger.warning(f'[{label}] 连续翻页后画面不再变化，结束当前阵营并保留结果')
                break
            try:
                with self._metrics.measure('recognition'):
                    cards = self._read_cards(image, f'阵营扫描：{label} 第 {page + 1} 页', names, levels)
                if not cards:
                    raise ValueError('当前页没有完整可见卡片')
            except (MemoryError, RuntimeError, ValueError) as exc:
                failures += 1
                logger.warning(f'[{label}] 当前页读取失败（{failures}），继续扫描：{exc}')
                previous = None
                stable.reset()
                if failures >= 2:
                    self._scan_metadata['coverage_exact'] = False
                    unread_pages += 1
                    if unread_pages >= 3:
                        logger.warning(f'[{label}] 连续三页无法读取，保留记录并继续下一阵营')
                        break
                    with self._metrics.measure('drag'):
                        last_drag = self._drag_rows(190, hold_duration=.12)
                    page += 1
                    failures = 0
                    waiting.reset()
                continue
            failures = unread_pages = 0
            try:
                with self._metrics.measure('displacement'):
                    moved = merger.advance(image, bounds=motion.bounds(thumb, last_drag),
                                           after_drag=last_drag is not None, strict_bounds=motion.strict_bounds)
                motion.accept(thumb, moved, hinted=merger.motion_hint_used)
                with self._metrics.measure('merge'):
                    merger.add(image, cards)
            except ValueError as exc:
                # 位移失败只失去精确物理计数；最终仍按群组取最高，不丢弃当前舰船。
                logger.warning(f'[{label}] 位移未确认，按群组继续合并：{exc}')
                self._scan_metadata['coverage_exact'] = False
                merger.previous = None
                pitch = int(CARD_GRIDS.delta[1])
                merger.offset = max((y for _, y in merger.slots), default=-pitch) + pitch - min(card.y for card in cards)
                merger.add(image, cards)
                motion = ScrollMotion()
            # 跨屏冲突沿当前阵营目录回填；未知等级继续保留，不阻塞后面的页面。
            for card, _ in merger.slots:
                if card.ship.get('group_type') is None:
                    hull = card.ship.get('type')
                    info, note = self._identity.fallback(card.name_reads or [card.ship['name']], card.ship.get('rarity', ''),
                                                         aviation=hull in ('正航', '轻航', '航战', '潜母'),
                                                         surface=hull in ('战列', '战巡', '超巡', '重炮'))
                    if info:
                        card.ship.update(name=info['name'], rarity=info['rarity'], base_rarity=info['base_rarity'],
                                         group_type=info['group_type'], type=info['type'], candidates=[], review=not card.level_reliable,
                                         source=f'{note}；{card.ship["source"]}'[:200])
                elif card.level_reliable:
                    card.ship['review'] = False
            self._metrics.counts['cards'] += len(cards)
            self._phase_ships = merger.ships(self._policy.min_level, self._policy.max_level)
            self._scan_raw_ships = [dict(card.ship) for card, _ in merger.slots]
            self._scan_metadata['physical_count'] = len(merger.slots)
            page += 1
            logger.info(f'[{label}] 第 {page} 页，已读取 {len(merger.slots)} 格，范围内 {len(self._phase_ships)} 艘')
            at_bottom = self._dock_scroll_at_bottom(thumb)
            short_list = page == 1 and last_drag is None and thumb is None and len(grid_rows(self.device.image)) < 3
            if at_bottom or short_list or self._policy.can_stop(cards, merger.slots):
                self._scan_metadata.update(finished=True, reached_bottom=at_bottom or short_list)
                break
            accepted = pixels.copy()
            accepted_thumb = thumb.copy() if thumb is not None else None
            self.device.click_record_clear()
            with self._metrics.measure('drag'):
                last_drag = self._drag_rows(190, hold_duration=.12)
            previous = None
            stable.reset()
            waiting.reset()
        else:
            self._scan_metadata['coverage_exact'] = False
            logger.warning(f'[{label}] 已达单阵营页数上限，保留结果并继续下一阵营')

    @staticmethod
    def _stable_pixels(image):
        """比较等级、名字和滚动条，避免卡面动态闪光阻止稳定检测。"""
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        rows = grid_rows(image)
        if not rows:
            return gray[65:640, 80:1250]
        signature = np.zeros(gray.shape, dtype=np.uint8)
        for y in rows:
            signature[y:y + 32, 85:1225] = gray[y:y + 32, 85:1225]
            signature[y + 155:y + 185, 85:1225] = gray[y + 155:y + 185, 85:1225]
        signature[55:715, 1238:1250] = gray[55:715, 1238:1250]
        return signature

    def _restricted_identity(self, nationalities):
        return MindIdentity(nationalities)

    def _enter_scan_dock(self):
        """恢复可确认的筛选面板后重建船坞；未知页面不重启游戏。

        Pages:
            in: Any
            out: page_dock
        """
        self.device.screenshot()
        if self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60)):
            self.dock_filter_confirm()
        try:
            self.ui_ensure(page_main, recover_unknown=False)
            self.ui_ensure(page_dock, recover_unknown=False)
        except GamePageUnknownError as exc:
            raise MindCalculatorScanError('扫描前页面未确认，请恢复主界面后重试；保留旧清单') from exc
        self._close_search()

    def _close_search(self):
        """重新进入船坞后正向确认搜索关闭，不沿用隐藏关键词。"""
        timeout = Timer(20).start()
        while True:
            self.device.screenshot()
            if self.appear(DOCK_SEARCH_CLOSED):
                return
            if timeout.reached():
                raise MindCalculatorScanError('未能确认船坞搜索已关闭，保留旧清单')
            if self.appear_then_click(DOCK_SEARCH_ACTIVE, interval=2):
                continue
            if self.handle_popup_confirm():
                continue

    def _set_identity_faction(self, faction, *, wait_loading=True):
        """筛选后重新核实所有按钮状态，不能接受通用设置器的超时假定。

        Pages:
            in: page_dock
            out: page_dock
        """
        self.dock_filter_enter()
        self.dock_filter.set(faction='all', index='all', rarity='all', extra='no_limit', sort='level')
        self.dock_filter.set(faction=faction, index='all', rarity='all', extra='no_limit', sort='level')
        status = self.dock_filter._product_setting_status(faction=faction, index='all', rarity='all', extra='no_limit', sort='level')
        timeout = Timer(15).start()
        while True:
            self.device.screenshot()
            if (self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60))
                    and all(self.dock_filter.is_option_active(button) == active for button, active in status.items())):
                break
            if timeout.reached():
                raise MindCalculatorScanError('阵营筛选未能正向核实，保留旧清单')
        self.dock_filter_confirm(wait_loading=wait_loading)
        self.dock_sort_method_dsc_set(True)

    def _resolve_group_reviews(self, ships, names, levels):
        """舰船科技沿用严格身份复核；心智任务直接按阵营首扫，不调用此路径。"""
        components = []
        for ship in ships:
            ids = set(ship.get('candidates', [])) if ship.get('group_type') is None else set()
            if len(ids) < 2:
                continue
            overlap = [group for group in components if group & ids]
            for group in overlap:
                ids.update(group)
                components.remove(group)
            components.append(ids)
        if not components or not hasattr(self, '_scan_raw_ships'):
            return ships
        original = self._scan_raw_ships
        policy, metadata, identity = self._policy, self._scan_metadata, self._identity
        wanted = set().union(*components)

        def belongs(row, groups):
            return row.get('group_type') in groups or bool(set(row.get('candidates', [])) & groups)
        factions = {1: 'eagle', 2: 'royal', 3: 'sakura', 4: 'iron', 5: 'dragon', 6: 'sardegna',
                    7: 'northern', 8: 'iris', 9: 'vichya', 11: 'tulipa', 12: 'pedreria', 96: 'tempesta', 97: 'meta'}
        scopes = {}
        for gid in wanted:
            row = identity.ships.get(gid)
            if row:
                nation = row['nationality']
                faction = factions.get(nation, 'other' if nation >= 100 else None)
                if faction:
                    scopes.setdefault(faction, set()).add(nation)
        evidence = []
        if 'other' in scopes:
            # “其他”是复合筛选，不能把它当成单一联动阵营的证明。
            scopes['other'] = {row['nationality'] for row in identity.ships.values()
                               if row['nationality'] not in factions}
        try:
            for faction, nationalities in sorted(scopes.items()):
                logger.hr(f'重名身份阵营复核：{faction}', level=2)
                self._set_identity_faction(faction)
                self._identity = self._restricted_identity(nationalities)
                self._policy = ScanPolicy(1, 125, sorted_desc=True)
                if self.appear(DOCK_EMPTY):
                    continue
                DOCK_SCROLL.set_top(self)
                if not DOCK_SCROLL.appear(self) or not (DOCK_SCROLL.at_top(self) or DOCK_SCROLL.length == DOCK_SCROLL.total):
                    raise MindCalculatorScanError('阵营复核未能确认顶部，保留旧清单')
                self._scan_pages(names, levels)
                for row in self._scan_raw_ships:
                    if belongs(row, wanted) and policy.min_level <= row['level'] <= policy.max_level:
                        evidence.append(dict(row, source=f'阵营筛选已核实：{faction}；{row["source"]}'[:200]))
        finally:
            self._policy, self._scan_metadata, self._identity = policy, metadata, identity
            self._scan_raw_ships = original
        output = list(ships)
        resolved_raw = list(original)
        for groups in sorted(components, key=min):
            expected = [row for row in original if belongs(row, groups)
                        and policy.min_level <= row['level'] <= policy.max_level]
            found = [row for row in evidence if belongs(row, groups)]
            if (not expected or Counter(row['level'] for row in expected) != Counter(row['level'] for row in found)
                    or any(row['review'] or find_ship(row['name'], row.get('group_type')) is None for row in found)):
                logger.warning(f'重名复核数量、等级或身份不一致，保留独立核对：{sorted(groups)}')
                continue
            positions = [index for index, row in enumerate(output) if belongs(row, groups)
                         and policy.min_level <= row['level'] <= policy.max_level]
            first = min(positions)
            replaced = set(positions)
            output = [row for index, row in enumerate(output) if index not in replaced]
            output[first:first] = highest_ships(found)
            resolved_raw = [row for row in resolved_raw if not (belongs(row, groups)
                            and policy.min_level <= row['level'] <= policy.max_level)] + found
        self._scan_raw_ships = resolved_raw
        # 成功返回默认全船坞状态；取消或异常只执行上面的内存收尾，不继续后台输入。
        self._enter_scan_dock()
        self.dock_reset()
        self.dock_sort_method_dsc_set(True)
        return highest_ships(output)

    def _save_scan_evidence(self, image):
        """保存核对原帧；诊断写盘失败不影响扫描继续。"""
        from time import time_ns
        path = Path(logger.log_file or 'log/alas.txt').parent / self.evidence_folder / self.config.config_name / f'{time_ns()}.png'
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path)
            if not hasattr(self, '_scan_evidence_paths'):
                self._scan_evidence_paths = set()
            self._scan_evidence_paths.add(path.resolve())
            logger.attr('扫描核对原帧', str(path))
            return str(path)
        except OSError as exc:
            logger.warning(f'扫描核对原帧保存失败，继续新截图核对：{exc}')
            return ''

    def _save_motion_evidence(self, merger, image, motion, thumb, gesture, bounds):
        """诊断模式只在位移失败时保留真正的前后帧和标定，避免事后猜测。"""
        from time import time_ns
        root = Path(logger.log_file or 'log/alas.txt').parent / 'scan_motion_evidence' / self.config.config_name
        stamp = str(time_ns())
        try:
            root.mkdir(parents=True, exist_ok=True)
            Image.fromarray(merger.previous).save(root / f'{stamp}-before.png')
            image.save(root / f'{stamp}-after.png')
            data = dict(offset=merger.offset, gesture=gesture, bounds=bounds, strict=motion.strict_bounds,
                        before_thumb=motion.thumb.tolist() if motion.thumb is not None else None,
                        after_thumb=thumb[[0, -1]].tolist() if thumb is not None else None,
                        ratios=list(motion.ratios))
            (root / f'{stamp}.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            logger.attr('位移失败诊断', str(root / f'{stamp}.json'))
        except OSError as exc:
            logger.warning(f'位移诊断保存失败，保留原错误：{exc}')

    def _prune_scan_evidence(self):
        """成功提交后只保留本轮诊断；停止或冲突时不删除旧清单的原帧。"""
        if Path(f'cache/{self.evidence_folder.replace("_", "-")}-diagnostics').is_file():
            return
        log_root = Path(logger.log_file or 'log/alas.txt').parent.resolve()
        root = log_root / self.evidence_folder / self.config.config_name
        try:
            root = root.resolve()
            root.relative_to(log_root / self.evidence_folder)
            if not root.is_dir():
                return
            current = {path.stem for path in getattr(self, '_scan_evidence_paths', set())}
            for path in root.iterdir():
                # 只处理本工具的 time_ns 文件，不递归或清理普通日志、其他实例。
                if (path.suffix not in ('.png', '.json') or len(path.stem) != 19
                        or not path.stem.isdecimal() or path.stem in current or not path.is_file()):
                    continue
                path.resolve().relative_to(root)
                path.unlink()
        except (OSError, ValueError) as exc:
            logger.warning(f'旧扫描诊断清理失败，已保留扫描结果：{exc}')

    def _drag_rows(self, distance, *, hold_duration=.4):
        """一次最多拖一排行距，终点按住后释放，截图再确认实际位移。"""
        # 游戏开始滚动前会消耗一段触控距离；实机 13px 校正可能完全不动。
        # 小距离增加一次路径点的距离，是否到位仍由下一帧的卡片位置核实。
        supported = self.config.Emulator_ControlMethod in ('minitouch', 'MaaTouch', 'uiautomator2', 'scrcpy', 'nemu_ipc')
        if supported and 0 < abs(distance) < 64:
            distance += 20 if distance > 0 else -20
        start = (1170, 470) if distance > 0 else (1170, 243)
        end = (start[0], start[1] - distance)
        if supported:
            self.device.drag(start, end, point_random=(0, 0, 0, 0), shake=(0, 0),
                             shake_random=(0, 0, 0, 0), hold_duration=hold_duration, name='心智单元船坞三排定位')
        else:
            if abs(distance) < 10:
                raise MindCalculatorScanError('当前控制方式无法进行船坞小距离校正，请改用 MaaTouch 等支持拖拽的控制方式')
            # 不使用 Device.drag 的不支持分支，避免其松手后回退点击舰船。
            self.device.swipe(start, end, duration=.6, name='心智单元船坞三排定位')
        return distance, supported

    def _dock_scroll_thumb(self):
        """核实滑块连续性，仅容许一个颜色恰在阈值上的内部采样缺口。"""
        if not DOCK_SCROLL.appear(self):
            raise MindCalculatorScanError('无法识别船坞滚动条，保留旧扫描结果')
        mask = np.asarray(DOCK_SCROLL.match_color(self), dtype=bool)
        thumb = np.flatnonzero(mask)
        if len(thumb):
            gaps = np.flatnonzero(~mask[thumb[0]:thumb[-1] + 1]) + thumb[0]
            if not len(gaps):
                return thumb
            if len(gaps) == 1:
                # 只在一个阈值边界行内补抗锯齿像素，前后行仍用严格颜色。
                # 三行须八邻接连通，不用固定横向跨度猜圆角的采样相位。
                gap = gaps[0]
                pixels = self.image_crop(DOCK_SCROLL.area, copy=False)[gap - 1:gap + 2]
                scores = color_similarity_2d(pixels, color=DOCK_SCROLL.color)
                above = np.flatnonzero(scores[0] > DOCK_SCROLL.color_threshold)
                bridge = np.flatnonzero(scores[1] >= DOCK_SCROLL.color_threshold - 3)
                below = np.flatnonzero(scores[2] > DOCK_SCROLL.color_threshold)
                if (scores[1].max() == DOCK_SCROLL.color_threshold
                        and any(np.any(abs(above - col) <= 1) and np.any(abs(below - col) <= 1) for col in bridge)):
                    return np.arange(thumb[0], thumb[-1] + 1)
        raise MindCalculatorScanError('船坞滚动条被遮挡，无法确认底部，保留旧扫描结果')

    def _recover_page_cards(self, image, cards, at_bottom):
        """有可靠行位和同排实际卡片证据时，将局部缺格保留为未知卡位。"""
        rows = grid_rows(np.array(image))
        if not cards or not rows or not at_bottom and len(rows) != 3:
            return None
        if any(not any(card.y == y for card in cards) for y in rows):
            return None
        recovered = list(cards)
        for y in rows:
            present = {card.col for card in cards if card.y == y}
            end = max(present) + 1 if at_bottom and y == rows[-1] else 7
            for col in set(range(end)) - present:
                x = round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))
                recovered.append(Card(x, y, col, dict(
                    name=f'待核对舰船（{y}px 第 {col + 1} 列）', level=0, rarity='', base_rarity='',
                    excluded=False, review=True, group_type=None, type=None, candidates=[], identity_ambiguous=True,
                    source='当前卡位三帧仍未加载，保留位置待核对'), fleet=-1))
        return sorted(recovered, key=lambda card: (card.y, card.col))

    def _dock_scroll_at_bottom(self, thumb):
        """严格滑块或与其连通、收窄到轨道末端的圆角端帽证明到底。"""
        if thumb is None:
            return False
        if thumb[-1] >= DOCK_SCROLL.total - 2:
            return True
        if thumb[-1] != DOCK_SCROLL.total - 3:
            return False
        # 保留已验证的末端圆角修复；仅核对轨道最后两行，不扩大运动标定。
        pixels = self.image_crop(DOCK_SCROLL.area, copy=False)[-3:]
        scores = color_similarity_2d(pixels, color=DOCK_SCROLL.color)
        cap = scores >= DOCK_SCROLL.color_threshold - 18
        widths = cap.sum(axis=1)
        if not widths[0] > widths[1] > widths[2] >= 1:
            return False
        connected = np.flatnonzero(scores[0] > DOCK_SCROLL.color_threshold)
        for row in cap[1:]:
            connected = np.array([col for col in np.flatnonzero(row) if np.any(abs(connected - col) <= 1)])
        return bool(len(connected))

    def _scan_pages(self, names, levels):
        """分段核验三排位移，目标位置连续稳定后识别整页，末页确认到底。"""
        merger = self._make_merger()
        metrics = getattr(self, '_metrics', None) or ScanMetrics()
        self._metrics = metrics
        names = names if isinstance(names, CachedOcr) else CachedOcr(names, metrics, 'name_ocr')
        levels = levels if isinstance(levels, CachedOcr) else CachedOcr(levels, metrics, 'level_ocr')
        motion, last_drag = ScrollMotion(), None
        motion_retries = scroll_failures = 0
        diagnostic_pages = Path(f'cache/{self.evidence_folder.replace("_", "-")}-diagnostics').is_file()
        policy = getattr(self, '_policy', ScanPolicy(95, 125))
        previous = None
        stable = Timer(.6, count=3).start()
        drag = Timer(.8).start()
        target = pitch = origin_y = None
        attempts = 0
        read_attempts = 0
        evidence_path = ''
        evidence_frame = None
        last_page_image = None
        page = 0
        progress = Timer(20, count=10).start()
        waiting = Timer(30).start()
        while True:
            wait_started = perf_counter()
            with metrics.measure('screenshot'):
                self.device.screenshot()
            # 所有前置分支都经过期限检查，动画、页面丢失或反复弹窗不能无限续期。
            if waiting.reached():
                raise MindCalculatorScanError('船坞画面 30 秒内未能稳定或页面已丢失，保留旧扫描结果')
            if page and not read_attempts and progress.reached():
                raise MindCalculatorScanError('船坞扫描位移未能继续确认，保留旧清单；不重启游戏')
            if self.appear(page_dock.check_button):
                with metrics.measure('stability'):
                    pixels = self._stable_pixels(self.device.image)
                # 保留全像素平均差及原阈值，避免整帧浮点转换产生大块临时分配。
                if (previous is None or pixels.shape != previous.shape
                        or cv2.mean(cv2.absdiff(pixels, previous))[0] > 1):
                    previous = pixels.copy()
                    stable.reset()
                    metrics.seconds['stable_wait'] += perf_counter() - wait_started
                    continue
                if not stable.reached():
                    metrics.seconds['stable_wait'] += perf_counter() - wait_started
                    continue
                metrics.seconds['stable_wait'] += perf_counter() - wait_started
                waiting.reset()
                image = Image.fromarray(self.device.image)
                try:
                    thumb = self._dock_scroll_thumb()
                    scroll_failures = 0
                except MindCalculatorScanError:
                    thumb = None
                    scroll_failures += 1
                    if scroll_failures in (1, 3):
                        logger.warning('船坞滚动条暂未确认，继续核验卡片位移，本帧不据此判断到底')
                try:
                    with metrics.measure('displacement'):
                        bounds = motion.bounds(thumb, last_drag)
                        moved = merger.advance(image, bounds=bounds, after_drag=last_drag is not None,
                                               strict_bounds=motion.strict_bounds)
                except ValueError as exc:
                    if diagnostic_pages and not motion_retries and merger.previous is not None:
                        self._save_motion_evidence(merger, image, motion, thumb, last_drag, bounds)
                    motion_retries += 1
                    if motion_retries < 3:
                        logger.warning(f'当前滚动位移待确认，重新截图核对（{motion_retries}/3）')
                        previous = None
                        stable.reset()
                        waiting.reset()
                        continue
                    raise MindCalculatorScanError(str(exc)) from exc
                motion_retries = 0
                if merger.motion_hint_used:
                    logger.attr('重复卡片位移核验', f'{moved:+d}px，已结合独立滑块运动确认')
                motion.accept(thumb, moved, hinted=merger.motion_hint_used)
                last_drag = None
                if moved:
                    progress.reset()
                    # 只有已核实的位移才清除连击历史，停滞仍沿用设备检测和超时恢复。
                    self.device.click_record_clear()
                    logger.attr('船坞实际位移', f'{moved:+d}px，累计 {merger.offset}px')
                at_bottom = self._dock_scroll_at_bottom(thumb)
                visible_rows = grid_rows(self.device.image)
                aligned = (target is not None and len(visible_rows) == 3
                           and abs(visible_rows[0] + merger.offset - origin_y - target) <= 6)
                if target is None or aligned or abs(target - merger.offset) <= 3 or at_bottom:
                    try:
                        cards = []
                        partial_tail = False
                        try:
                            with metrics.measure('reread' if read_attempts else 'recognition'):
                                cards = self._read_cards(image, f'自动扫描第 {page + 1} 页', names, levels)
                            metrics.counts['cards'] += len(cards)
                            self._check_scan_page(cards, at_bottom)
                        except ValueError:
                            read_attempts += 1
                            if read_attempts < 3:
                                logger.warning(f'当前页卡片未完整加载，重新截图核对（{read_attempts}/3）')
                                previous = None
                                stable.reset()
                                waiting.reset()
                                continue
                            if not at_bottom and self._has_partial_tail(cards):
                                # 到底之前即可看到最后一排空位。只接纳实际读到的卡片，
                                # 前进一排使末排进入下一帧中排；不得虚构尾部未知卡位。
                                partial_tail = True
                                self._check_scan_page(cards, True)
                                logger.info('末排末尾尚待到底确认，保留两排重叠继续核验')
                            else:
                                cards = self._recover_page_cards(image, cards, at_bottom)
                                if cards is None:
                                    raise
                                self._check_scan_page(cards, at_bottom)
                            read_attempts = 2
                            if not partial_tail:
                                logger.warning('当前页局部缺格已保留为待核对卡位，继续处理其余舰船')
                        invalid = [card for card in cards if not card.level_reliable]
                        uncertain_names = [card for card in cards if card.ship['review'] and card.level_reliable
                                           and not (getattr(card, 'identity_ambiguous', False) or card.ship.get('identity_ambiguous'))]
                        uncertain_fleets = [card for card in cards if card.fleet < 0]
                        # 复核本页与前一船位的边界；历史疑点保留在原卡位，
                        # 不让单点读数问题持续污染后续完整页面的早停证据。
                        current_slots = [[card, card.y + merger.offset] for card in cards]
                        first = min((y, card.col) for card, y in current_slots)
                        preceding = [slot for slot in merger.slots if (slot[1], slot[0].col) < first]
                        boundary = max(preceding, key=lambda slot: (slot[1], slot[0].col)) if preceding else None
                        candidate_slots = current_slots
                        if boundary and boundary[0].level_reliable and boundary[0].fleet >= 0:
                            candidate_slots = [boundary, *current_slots]
                        order_issue = policy.sort_issue(candidate_slots)
                        if invalid or uncertain_names or uncertain_fleets or order_issue:
                            read_attempts += 1
                            locations = order_issue or '、'.join(f'{card.y}px 行第 {card.col + 1} 列'
                                                               for card in invalid or uncertain_names or uncertain_fleets)
                            reason = '等级' if invalid else '舰名/身份' if uncertain_names else '编队/排序'
                            if (uncertain_fleets or order_issue) and read_attempts == 1:
                                logger.attr('编队复核标记', ','.join(str(card.fleet) for card in cards))
                                evidence_path = self._save_scan_evidence(image)
                                evidence_frame = image
                            if read_attempts >= 3:
                                # 核对项对应最终接受的新帧；首次冲突原帧仍单独保留作诊断。
                                evidence_path = self._save_scan_evidence(image)
                                evidence_frame = image
                                affected = [(card, '等级未确认') for card in invalid]
                                affected += [(card, '舰名/身份未确认') for card in uncertain_names]
                                affected += [(card, '编队标记未确认') for card in uncertain_fleets]
                                if order_issue:
                                    affected += policy.sort_conflicts(candidate_slots)
                                positions = {id(card): y for card, y in merger.slots}
                                positions.update({id(card): card.y + merger.offset for card in cards})
                                current_ids = {id(card) for card in cards}
                                previous_evidence = self._save_scan_evidence(last_page_image) \
                                    if last_page_image is not None and any(id(card) not in current_ids for card, _ in affected) else ''
                                marked = set()
                                for card, note in affected:
                                    if id(card) in marked:
                                        continue
                                    marked.add(id(card))
                                    # 来源采用已核验网格行号，避免合法的像素停位偏移
                                    # 让同一物理卡位在重复扫描时出现不同的位置提示。
                                    origin = origin_y if origin_y is not None else min(item.y for item in cards)
                                    row = round((positions[id(card)] - origin) / (pitch or CARD_GRIDS.delta[1])) + 1
                                    location = f'第 {page + 1} 页发现，累计第 {row} 行第 {card.col + 1} 列'
                                    path = evidence_path if id(card) in current_ids else previous_evidence
                                    evidence = f'；原帧：{path}' if path else ''
                                    card.ship = dict(card.ship, review=True,
                                                     source=f'{location}；{note}，待人工核对{evidence}；{card.ship["source"]}'[:200])
                                    # 未确认名称保留实际 OCR 读数供人工定位；review
                                    # 标记仍使其独立保留，不能作为已确认身份合并或计费。
                                logger.warning(f'[{self.scan_label}] {reason}重读仍未确认：{locations}；已标记待核对，继续扫描')
                            else:
                                logger.warning(f'{reason}未确认，重新截图核对（{read_attempts}/3）：{locations}')
                                previous = None
                                stable.reset()
                                waiting.reset()
                                continue
                        previous_slots = len(merger.slots)
                        with metrics.measure('merge'):
                            merger.add(image, cards)
                        last_page_image = image
                        # 置顶编队读数影响当前边界，保留其原帧和最终卡位数据，
                        # 便于区分编号误读、透明背景与排序冲突；普通正常页不写图。
                        if (diagnostic_pages or any(card.fleet > 0 for card in cards) or evidence_path) and evidence_frame is not image:
                            evidence_path = self._save_scan_evidence(image)
                            evidence_frame = image
                        if evidence_path:
                            try:
                                Path(evidence_path).with_suffix('.json').write_text(json.dumps(
                                    [dict(x=card.x, y=card.y, col=card.col, ship=card.ship,
                                          fleet=card.fleet, level_reliable=card.level_reliable,
                                          name_reads=card.name_reads, name_ellipsis=card.name_ellipsis) for card in cards],
                                    ensure_ascii=False, indent=2), encoding='utf-8')
                            except OSError as exc:
                                logger.warning(f'扫描卡位诊断保存失败：{exc}')
                    except ValueError as exc:
                        raise MindCalculatorScanError(str(exc)) from exc
                    read_attempts = 0
                    evidence_path = ''
                    evidence_frame = None
                    page += 1
                    if len(merger.slots) > previous_slots:
                        # 新页经位移与网格核验后已完成读取；有界 OCR 复读的耗时
                        # 不应占用下一段滚动的期限，重复旧船位仍不能续期。
                        progress.reset()
                    if len(merger.slots) > 5000:
                        raise MindCalculatorScanError('识别卡片超过 5000，请核对船坞布局，保留旧扫描结果')
                    logger.attr('扫描页', page)
                    logger.attr('识别卡片', len(merger.slots))
                    identity_label = '按群组取最高'
                    page_ships = merger.ships(policy.min_level, policy.max_level)
                    logger.attr(f'范围内舰船（{identity_label}）', len(page_ships))
                    logger.attr('本页等级', ','.join(str(card.ship['level']) for card in cards))
                    logger.attr('本页编队', ','.join(str(card.fleet) for card in cards))
                    logger.attr('本页识别摘要', sha256(json.dumps(
                        [dict(ship=card.ship, fleet=card.fleet, level_reliable=card.level_reliable) for card in cards],
                        ensure_ascii=False, sort_keys=True).encode()).hexdigest())
                    logger.info(f'[{self.scan_label}] 第 {page} 页，已读取 {len(merger.slots)} 格，'
                                f'范围内 {len(page_ships)} 艘（{identity_label}）')
                    if policy.can_stop(cards, merger.slots):
                        self._scan_metadata = dict(reached_bottom=False, physical_count=len(merger.slots))
                        logger.info(f'[{self.scan_label}] 连续三排共 {len(cards)} 艘均低于 {policy.min_level} 级，已核实等级降序，扫描结束')
                        break
                    logger.attr('早停检查', policy.stop_reason(cards, merger.slots))
                    if at_bottom:
                        self._scan_metadata = dict(reached_bottom=True, physical_count=len(merger.slots))
                        cap_note = '，已核实连通圆角端帽' if thumb[-1] < DOCK_SCROLL.total - 2 else ''
                        logger.info(f'[{self.scan_label}] 已确认滚动条底部（严格颜色 {thumb[-1] + 1}/{DOCK_SCROLL.total}px'
                                    f'{cap_note}），扫描结束')
                        break
                    rows = sorted({card.y for card in cards})
                    if len(rows) != 3:
                        raise MindCalculatorScanError('船坞未显示三排完整船名，无法安全按三排推进')
                    if pitch is None:
                        distances = np.diff(rows)
                        pitch = int(round(float(np.median(distances))))
                        origin_y = rows[0]
                        if not 180 <= pitch <= 250 or max(abs(distances - pitch)) > 3:
                            raise MindCalculatorScanError('无法确认船坞实际行距，保留旧扫描结果')
                        motion.row_pitch = pitch
                        logger.attr('船坞行距', f'{pitch}px，三排 {3 * pitch}px')
                    expected_offset = target if target is not None else 0
                    if any(abs(y + merger.offset - origin_y - expected_offset - index * pitch) > 6
                           for index, y in enumerate(rows)):
                        raise MindCalculatorScanError('三排位移与卡片行位置不一致，保留旧扫描结果')
                    target = expected_offset + (pitch if partial_tail else 3 * pitch)
                    attempts = 0
                    logger.attr('船坞三排目标', f'{target}px')
                    if page >= 500:
                        raise MindCalculatorScanError('船坞扫描超过有限页数仍未确认底部，保留旧清单；不重启游戏')
                waiting.reset()
                if drag.reached():
                    if attempts >= 8:
                        raise MindCalculatorScanError('船坞三排定位未能停在目标位置，请检查控制方式')
                    remaining = target - merger.offset
                    with metrics.measure('drag'):
                        last_drag = self._drag_rows(int(np.clip(remaining, -pitch, pitch)))
                    attempts += 1
                    drag.reset()
                    stable.reset()
                    previous = None
                continue
            if self.handle_popup_confirm():
                previous = None
                stable.reset()
                continue
        self._scan_raw_ships = [dict(card.ship) for card, _ in sorted(merger.slots, key=lambda item: (item[1], item[0].col))]
        return merger.ships(policy.min_level, policy.max_level)
