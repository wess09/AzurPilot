"""独立仓库统计任务：只浏览材料并在完整扫描后提交快照。"""

from datetime import datetime
import sqlite3
import numpy as np

import module.config.server as server
from module.base.timer import Timer
from module.exception import StorageStatisticsError
from module.logger import logger
from module.statistics.storage_snapshot import save_snapshot
from module.storage.assets import MATERIAL_STATISTICS_SCROLL
from module.storage.statistics_recognition import (StorageCatalog, StorageRecognitionError,
    StorageTraversal, calibrate_scroll, detect_rows, is_purple, recognize_rows, verify_targets)
from module.storage.ui import StorageUI
from module.ui.scroll import Scroll


class StorageStatistics(StorageUI):
    """材料仓库金/彩区域按三行扫描；跳过单格错误，无法继续浏览才保留旧快照。"""

    def _scroll_materials(self, start, end):
        """精确拖动列表；不支持拖拽的后端只滑动，避免设备层回退点击物品。"""
        if self.config.Emulator_ControlMethod in ('minitouch', 'MaaTouch', 'uiautomator2', 'scrcpy', 'nemu_ipc'):
            self.device.drag(start, end, point_random=(0, 0, 0, 0), shake=(0, 0),
                             shake_random=(0, 0, 0, 0), hold_duration=.3, name='StorageStatistics')
        else:
            self.device.swipe(start, end, duration=.3, name='StorageStatistics', distance_check=False)

    def _scan_pass(self, catalog):
        """标定滚动条后按三行定位；单格失败继续，页面或定位失效时退出。

        Pages:
            in: page_storage, material
            out: page_storage, material
        """
        scroll = Scroll(MATERIAL_STATISTICS_SCROLL, color=(247, 211, 66))
        traversal = StorageTraversal()
        phase = 'top'
        calibrated = False
        origin_rows = None
        origin_thumb = None
        origin_length = None
        origin_y = None
        pitch = scale = None
        goal_thumb = None
        goal_bottom = False
        attempts = 0
        layout = previous = None
        settle = Timer(1.5, count=2)
        stable = Timer(.8)
        action = Timer(2, count=2)
        timeout = Timer(30, count=2).start()
        last_error = '等待材料仓库稳定'
        regular_seen = False
        x = (scroll.area[0] + scroll.area[2]) // 2
        for image in self.loop(skip_first=False):
            action_ready = action.reached()
            if timeout.reached():
                raise StorageRecognitionError(last_error)
            if self.handle_info_bar() or not self._storage_in_material():
                if previous is not None:
                    raise StorageRecognitionError('同页核对期间材料页面变化')
                layout = previous = None
                continue
            mask = scroll.match_color(self)
            pixels = np.flatnonzero(mask)
            if not len(pixels):
                raise StorageRecognitionError('无法确认仓库滚动条位置')
            if pixels[-1] - pixels[0] + 1 != len(pixels):
                if previous is not None:
                    raise StorageRecognitionError('同页核对期间滚动条被遮挡')
                last_error = '仓库滚动条被光点或遮挡干扰'
                layout = previous = None
                continue
            thumb = scroll.area[1] + float(np.mean(pixels))
            at_top = pixels[0] <= 1
            at_bottom = pixels[-1] >= scroll.total - 2
            single_page = at_top and at_bottom
            if phase == 'top' and not at_top or phase == 'position' and not (
                    at_bottom if goal_bottom else abs(thumb - goal_thumb) <= 1.5):
                if previous is not None:
                    raise StorageRecognitionError('同页核对期间滚动条位置变化')
                if action_ready:
                    if attempts >= 3:
                        raise StorageRecognitionError('滚动条未到达指定三行位置')
                    destination = scroll.area[1] - 50 if phase == 'top' else goal_thumb
                    self._scroll_materials((x, round(thumb)), (x, round(destination)))
                    attempts += 1
                    action.reset()
                    timeout.reset()
                    layout = previous = None
                continue
            try:
                rows = detect_rows(image)
            except StorageRecognitionError as error:
                # 页面切换动画和点击反馈会短暂破坏方框轮廓；在统一超时内等待
                # 下一帧重新推导网格，不能把首帧未稳定的画面当成永久布局故障。
                last_error = str(error)
                layout = previous = None
                continue
            current_layout = (tuple(row[0].area[1] for row in rows), tuple(pixels))
            if current_layout != layout:
                if previous is not None:
                    raise StorageRecognitionError('同页核对期间材料位置变化')
                layout, previous = current_layout, None
                settle.reset()
                continue
            if not settle.reached():
                continue
            if phase == 'top' and not calibrated and not single_page:
                if len(rows) < 2:
                    raise StorageRecognitionError('滚动条标定需要至少两行完整材料')
                origin_rows, origin_thumb, origin_y = rows, thumb, rows[0][0].area[1]
                origin_length = scroll.length
                # 只在开扫时标定一次：用重叠行测实际响应，不用最小滑块长度推算内容。
                delta = max(12, round(scroll.length * .22))
                self._scroll_materials((x, round(thumb)), (x, round(thumb + delta)))
                phase = 'calibrate'
                layout = previous = None
                action.reset()
                timeout.reset()
                continue
            if phase == 'calibrate':
                if abs(scroll.length - origin_length) > 2:
                    raise StorageRecognitionError('标定期间滚动条长度变化，无法确认材料行距')
                pitch, scale = calibrate_scroll(origin_rows, rows, thumb - origin_thumb)
                logger.attr('仓库滚动标定', f'行距 {pitch:.0f}px，三行滑块距离 {3 * pitch / scale:.2f}px')
                calibrated = True
                phase = 'top'
                attempts = 0
                self._scroll_materials((x, round(thumb)), (x, scroll.area[1] - 50))
                layout = previous = None
                action.reset()
                timeout.reset()
                continue
            if len(rows) < 2 and not at_bottom:
                # 拖到列表内部时，下一行可能只露出一部分；两行完整材料已经
                # 足够按滚动距离确定行号，未完整露出的行留给下一次滚动读取。
                last_error = '材料页面未露出至少两行完整材料'
                layout = previous = None
                continue
            if single_page:
                row_start = 0
            else:
                if abs(scroll.length - origin_length) > 2:
                    raise StorageRecognitionError('滚动条长度变化，拒绝沿用旧标定距离')
                offset = (thumb - origin_thumb) * scale
                estimated = (offset + rows[0][0].area[1] - origin_y) / pitch
                row_start = int(round(estimated))
                # 游戏列表会按亚像素位置绘制，滑块中心和首行位置并非严格同步。
                # 相邻候选相差一整行，半行以内的误差仍能唯一确定行号。
                if abs(estimated - row_start) > .35:
                    raise StorageRecognitionError(
                        f'滚动距离与材料行位置不一致：估计第 {estimated:.3f} 行，'
                        f'最近完整行 {row_start}')
                if not at_bottom and row_start != len(traversal.rows):
                    raise StorageRecognitionError(
                        f'三行定位未到达下一组完整材料：定位第 {row_start} 行，'
                        f'已读 {len(traversal.rows)} 行')
            partial = [i for i, row in enumerate(rows) if any(not card.present for card in row)]
            if partial and (partial != [len(rows) - 1] or not at_bottom):
                raise StorageRecognitionError('只有确认到底后的末行才允许空格')
            # Lua 材料排序为 order 降序、rarity 降序、id 升序；目录目标均为 order=0。
            # 前面的活动紫色礼物不可作终点，已读普通目标后的整页紫色才确认金/彩区结束。
            if regular_seen and all(is_purple(card.image) for row in rows for card in row if card.present):
                logger.info('仓库金/彩材料区域已完整读取，整页紫色物品不再识别')
                return traversal
            if previous is None:
                stable.reset()
                previous = recognize_rows(image, catalog, rows=rows, target_only=True)
                continue
            if not stable.reached():
                continue
            rows = verify_targets(rows, previous, catalog)
            traversal.append(rows, at_bottom=at_bottom, row_start=row_start)
            if row_start > 0 and not at_bottom:
                # 滑块中心取整会影响短距离标定；用已确认的三行位移累计消除量化误差。
                scale = (row_start * pitch + origin_y - rows[0][0].area[1]) / (thumb - origin_thumb)
            self.device.click_record_clear()
            regular_seen = regular_seen or any(card.identifier for row in rows for card in row)
            logger.attr('仓库扫描', f'第 {traversal.pages} 页，累计 {len(traversal.rows)} 行，仅识别金/彩目标')
            if at_bottom:
                return traversal
            goal_thumb = origin_thumb + len(traversal.rows) * pitch / scale
            goal_bottom = goal_thumb >= scroll.area[3] - scroll.length / 2 - 1
            if goal_bottom:
                goal_thumb = scroll.area[3] + 50
            phase = 'position'
            attempts = 0
            layout = previous = None
            last_error = '等待下一组三行材料稳定'
            action.clear()
            timeout.reset()
        raise StorageRecognitionError('仓库扫描中断')

    def run(self):
        """单遍扫描完成后原子更新；单格错误存为未知，不中断其他物品。

        Pages:
            in: 任意可导航页面
            out: page_storage, material
        """
        logger.hr('仓库统计', level=1)
        started_at = datetime.now().isoformat(sep=' ', timespec='seconds')
        try:
            interval_days = self.config.StorageStatistics_RunIntervalDays
            if type(interval_days) is not int or not 1 <= interval_days <= 3650:
                raise StorageRecognitionError('仓库统计运行间隔必须为 1–3650 的整数天数')
            catalog = StorageCatalog()
            if server.server not in catalog.servers:
                raise StorageRecognitionError('当前仓库模板仅经国服截图验证，尚不支持此服务器')
            self.ui_goto_storage()
            # ui_goto_storage 的末帧只证明已到仓库页；这里重新截图再判断材料栏，
            # 避免默认停留在装备页或切换动画时把旧画面误判为材料页。
            self._storage_enter_material(skip_first_screenshot=False)
            scan = self._scan_pass(catalog)
            skipped = sum(card.error is not None for row in scan.rows for card in row)
            if skipped:
                logger.warning(f'仓库扫描完成，{skipped} 个物品格未能确认，相关数量保存为未知')
            items = catalog.snapshot_items(scan.rows)
            save_snapshot(self.config.config_name, server.server, items,
                          started_at=started_at, pages=scan.pages, catalog_version=catalog.version)
            from module.statistics.resource_flow import observe, session_for
            if session_for(self.config) is not None:
                for item in items:
                    if item['amount'] is not None:
                        observe(self.config, item['id'], item['amount'])
        except (ValueError, sqlite3.Error, OSError) as error:
            self.config.task_delay(success=False)
            raise StorageStatisticsError(f'仓库统计未更新，保留上次完整快照：{error}') from error
        logger.info('仓库统计单遍扫描并保存成功')
        self.config.task_delay(minute=interval_days * 1440)
