"""复用 AP 设备和船坞导航的心智单元扫描任务。"""
from datetime import datetime

import cv2
import numpy as np
from PIL import Image

import module.config.server as server
from module.base.timer import Timer
from module.exception import GameStuckError, MindCalculatorScanError
from module.logger import logger
from module.retire.assets import DOCK_EMPTY
from module.retire.dock import DOCK_SCROLL, Dock
from module.runtime.mind_calculator import RESULT_PATH, calculate, revision
from module.runtime.mind_recognition import ScanMerger, ScanPolicy, grid_rows, recognize_cards
from module.ui.page import page_dock


class MindCalculatorScan(Dock):
    def run(self):
        """扫描指定等级范围；三排确认低于下限后结束，完成前保留旧结果。

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
        try:
            self._policy = ScanPolicy(self.config.MindCalculator_MinLevel, self.config.MindCalculator_MaxLevel,
                                      sorted_desc=True)
        except ValueError as exc:
            raise MindCalculatorScanError(str(exc)) from exc
        logger.attr('扫描等级范围', f'{self._policy.min_level}–{self._policy.max_level}（含边界）')
        previous_revision = revision(deep_get(self.config.data, RESULT_PATH, {}).get('ships', []))
        self.ui_ensure(page_dock)
        self.dock_reset()
        # 通用 reset 服务于退役的升序流程；本任务需要明确切换为等级降序。
        self.dock_sort_method_dsc_set(True)
        if self.appear(DOCK_EMPTY):
            ships = []
        else:
            DOCK_SCROLL.set_top(self)
            if DOCK_SCROLL.appear(self):
                if DOCK_SCROLL.at_top(self) or DOCK_SCROLL.length == DOCK_SCROLL.total:
                    logger.attr('船坞位置', '已确认顶部')
                else:
                    raise MindCalculatorScanError('船坞未能回到顶部，保留旧扫描结果')
            else:
                raise MindCalculatorScanError('无法识别船坞滚动条，保留旧扫描结果')
            names = AlOcr(config=self.config, name='ppocr_v6')
            levels = AlOcr(config=self.config, name='azur_lane')
            ships = self._scan_pages(names, levels)
        # 扫描期间用户可能修改数据；复读当前配置避免覆盖手工修正。
        with config_transaction(filepath_config(self.config.config_name)):
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
        result = calculate(ships)
        logger.info(f'[心智扫描] 已保存 {len(ships)} 艘，计入 {result["included"]} 艘，'
                    f'待核对 {result["review"]} 艘，心智单元Ⅰ {result["mind"]}，物资 {result["gold"]}')

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

    def _drag_rows(self, distance):
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
                             shake_random=(0, 0, 0, 0), hold_duration=.4, name='心智单元船坞三排定位')
        else:
            if abs(distance) < 10:
                raise MindCalculatorScanError('当前控制方式无法进行船坞小距离校正，请改用 MaaTouch 等支持拖拽的控制方式')
            # 不使用 Device.drag 的不支持分支，避免其松手后回退点击舰船。
            self.device.swipe(start, end, duration=.6, name='心智单元船坞三排定位')

    def _scan_pages(self, names, levels):
        """分段核验三排位移，目标位置连续稳定后识别整页，末页确认到底。"""
        merger = ScanMerger()
        policy = getattr(self, '_policy', ScanPolicy(95, 120))
        previous = None
        stable = Timer(.6, count=3).start()
        drag = Timer(.8).start()
        target = pitch = origin_y = None
        attempts = 0
        read_attempts = 0
        page = 0
        progress = Timer(20, count=10).start()
        while True:
            self.device.screenshot()
            if self.appear(page_dock.check_button):
                pixels = self._stable_pixels(self.device.image)
                if previous is None or pixels.shape != previous.shape or np.mean(np.abs(pixels.astype(float) - previous.astype(float))) > 1:
                    previous = pixels.copy()
                    stable.reset()
                    continue
                if not stable.reached():
                    continue
                image = Image.fromarray(self.device.image)
                try:
                    moved = merger.advance(image)
                except ValueError as exc:
                    raise MindCalculatorScanError(str(exc)) from exc
                if moved:
                    progress.reset()
                    # 只有已核实的位移才清除连击历史，停滞仍沿用设备检测和超时恢复。
                    self.device.click_record_clear()
                    logger.attr('船坞实际位移', f'{moved:+d}px，累计 {merger.offset}px')
                if not DOCK_SCROLL.appear(self):
                    raise MindCalculatorScanError('无法识别船坞滚动条，保留旧扫描结果')
                thumb = np.flatnonzero(DOCK_SCROLL.match_color(self))
                if len(thumb) and thumb[-1] - thumb[0] + 1 != len(thumb):
                    raise MindCalculatorScanError('船坞滚动条被遮挡，无法确认底部，保留旧扫描结果')
                at_bottom = len(thumb) and thumb[-1] >= DOCK_SCROLL.total - 2
                visible_rows = grid_rows(self.device.image)
                aligned = (target is not None and len(visible_rows) == 3
                           and abs(visible_rows[0] + merger.offset - origin_y - target) <= 6)
                if target is None or aligned or abs(target - merger.offset) <= 3 or at_bottom:
                    try:
                        cards = recognize_cards(image, f'自动扫描第 {page + 1} 页', name_ocr=names, level_ocr=levels)
                        invalid = [card for card in cards if not card.level_reliable]
                        if invalid:
                            read_attempts += 1
                            locations = '、'.join(f'{card.y}px 行第 {card.col + 1} 列' for card in invalid)
                            if read_attempts >= 3:
                                raise ValueError(f'等级重读仍未确认：{locations}；未导入零等级，保留旧扫描结果')
                            logger.warning(f'等级未确认，重新截图核对（{read_attempts}/3）：{locations}')
                            previous = None
                            stable.reset()
                            continue
                        merger.add(image, cards)
                    except ValueError as exc:
                        raise MindCalculatorScanError(str(exc)) from exc
                    read_attempts = 0
                    page += 1
                    if page == 1:
                        progress.reset()
                    if len(merger.slots) > 5000:
                        raise MindCalculatorScanError('识别卡片超过 5000，请核对船坞布局，保留旧扫描结果')
                    logger.attr('扫描页', page)
                    logger.attr('识别卡片', len(merger.slots))
                    logger.attr('范围内舰船（同名取最高）', len(merger.ships(policy.min_level, policy.max_level)))
                    logger.attr('本页等级', ','.join(str(card.ship['level']) for card in cards))
                    logger.info(f'[心智扫描] 第 {page} 页，已读取 {len(merger.slots)} 格，'
                                f'范围内 {len(merger.ships(policy.min_level, policy.max_level))} 艘（同名取最高）')
                    if policy.can_stop(cards, merger.slots):
                        logger.info(f'[心智扫描] 连续三排共 {len(cards)} 艘均低于 {policy.min_level} 级，已核实等级降序，扫描结束')
                        break
                    if at_bottom:
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
                        logger.attr('船坞行距', f'{pitch}px，三排 {3 * pitch}px')
                    expected_offset = (page - 1) * 3 * pitch
                    if any(abs(y + merger.offset - origin_y - expected_offset - index * pitch) > 6
                           for index, y in enumerate(rows)):
                        raise MindCalculatorScanError('三排位移与卡片行位置不一致，保留旧扫描结果')
                    target = page * 3 * pitch
                    attempts = 0
                    logger.attr('船坞三排目标', f'{target}px')
                    if page >= 500:
                        raise GameStuckError('船坞扫描未能到达底部')
                if progress.reached():
                    raise GameStuckError('船坞扫描画面没有继续滚动，尚未确认到底')
                if drag.reached():
                    if attempts >= 8:
                        raise MindCalculatorScanError('船坞三排定位未能停在目标位置，请检查控制方式')
                    remaining = target - merger.offset
                    self._drag_rows(int(np.clip(remaining, -pitch, pitch)))
                    attempts += 1
                    drag.reset()
                    stable.reset()
                    previous = None
                continue
            if self.handle_popup_confirm():
                previous = None
                stable.reset()
                continue
        return merger.ships(policy.min_level, policy.max_level)
