"""岛屿季节任务扫描：读取未完成任务，汇总成规划器的任务目标。

移植自 AzurLaneAutoScript（LmeSzinc/AzurLaneAutoScript，GPL-3.0）的
module/island/season_task.py。流程：进入季节页「任务」标签 → 一键领取已完成任务的奖励
（避免已完成任务被当成目标）→ 从上往下 OCR 任务名，按当前季节任务表用编辑距离纠正 →
遇到「已领取」标记或滑到底部为止。任务目标 `DIC_ISLAND_TASK[id]['target']` 为物品时计入。

AzurPilot 改动：作为规划器的一个步骤运行，不再单独调度；扫描结果写入规划器配置，
由规划器统一求解。
"""
from datetime import datetime, timezone

import cv2
from jellyfish import levenshtein_distance

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.decorator import cached_property, del_cached_property
from module.base.timer import Timer
from module.base.utils import rgb2luma
from module.combat.assets import GET_ITEMS_1
from module.config.utils import server_time_offset, server_timezone
from module.island.assets import (
    ISLAND_SEASON_TASK_RECEIVE_ALL,
    ISLAND_SEASON_TASK_SCROLL_AREA,
    TEMPLATE_ISLAND_SEASON_REWARD,
    TEMPLATE_ISLAND_SEASON_TASK_OBTAINED,
)
from module.island.ui import IslandUI
from module.island_planner.data import DIC_ISLAND_ITEM, DIC_ISLAND_SEASON, DIC_ISLAND_TASK
from module.logger import logger
from module.map_detection.utils import Points
from module.ocr.ocr import Ocr
from module.ui.navbar import Navbar
from module.ui.page import page_island_season
from module.ui.scroll import Scroll

DETECT_AREA = (42, 171, 1206, 604)
ICON_AREA = (21, 133, 225, 195)
TAB_DELTA = (395, 230)
TAB_SIZE = (376, 211)
NAME_AREA = (29, 18, 270, 48)
SEASON_TASK_TAB = 3
MAX_PAGES = 20
# OCR 丢空格、少几个字母时仍可纠正；超过 max(3, 任务名长度/2) 视为读错
MATCH_MIN_DISTANCE = 3
ISLAND_SEASON_TASK_SCROLL = Scroll(
    ISLAND_SEASON_TASK_SCROLL_AREA.button, color=(128, 128, 128), name='ISLAND_SEASON_TASK_SCROLL')


class SeasonTaskNameOcr(Ocr):
    def after_process(self, result):
        result = super().after_process(result)
        if server.server != 'en' or not result:
            return result
        # EN 服 OCR 常丢空格：去掉空格后与任务表恰好一条匹配时才还原
        compact = ''.join(result.split())
        matches = {
            task['name']['en'] for task in DIC_ISLAND_TASK.values()
            if ''.join(task['name']['en'].split()) == compact
        }
        return next(iter(matches)) if len(matches) == 1 else result


def current_season_task_ids(now=None):
    """当前季节的任务 ID（服务器时间）。"""
    if now is None:
        now = (datetime.now() - server_time_offset()).replace(tzinfo=timezone(server_timezone()))
    ids = set()
    for season in DIC_ISLAND_SEASON.values():
        start = season['start_time'].get(server.server) if season['start_time'] else None
        end = season['end_time'].get(server.server) if season['end_time'] else None
        if not start or not end:
            continue
        start = datetime.fromisoformat(start).replace(tzinfo=now.tzinfo)
        end = datetime.fromisoformat(end).replace(tzinfo=now.tzinfo)
        if start <= now <= end:
            ids.update(season['task_list'])
    return ids


def match_task_name(name, task_ids):
    """OCR 结果按编辑距离匹配到最接近的任务 ID。"""
    if not isinstance(name, str) or not name:
        return None
    best, code = None, None
    for task_id in task_ids:
        task = DIC_ISLAND_TASK.get(task_id)
        if not task:
            continue
        distance = levenshtein_distance(name, task['name'][server.server])
        if best is None or distance <= best:
            best, code = distance, task_id
    if code is None:
        return None
    target = DIC_ISLAND_TASK[code]['name'][server.server]
    # 编辑距离过大说明 OCR 读到的不是任务名（如只读到一个字母 F），不能硬配成最接近的任务
    if best > max(MATCH_MIN_DISTANCE, len(target) // 2):
        logger.warning(f'[岛屿-季节任务] 任务名「{name}」与任务表差距过大，不予识别')
        return None
    if target != name:
        logger.warning(f'[岛屿-季节任务] 任务名纠正: {name} -> {target}')
    return code


def task_item_targets(task_ids):
    """未完成任务中以物品为目标的部分，按物品汇总。

    Returns:
        dict[int, int]: {物品ID: 需要数量}。
    """
    targets = {}
    for task_id in task_ids:
        target = DIC_ISLAND_TASK.get(task_id, {}).get('target') or {}
        for item_id, count in target.items():
            if item_id in DIC_ISLAND_ITEM:
                targets[item_id] = targets.get(item_id, 0) + count
    return targets


class IslandSeasonTaskScanner(IslandUI):
    """
    Pages:
        in: 任意页面
        out: page_island_season（任务标签）
    """

    @cached_property
    def _season_bottom_navbar(self):
        """季节页底部 6 个标签：主页、PT 奖励、任务、商店、排名、历史。"""
        grids = ButtonGrid(origin=(14, 677), delta=(213, 0), button_shape=(186, 33), grid_shape=(6, 1),
                           name='ISLAND_SEASON_BOTTOM_NAVBAR')
        # 激活标签是整块浅色底（实测约 4900 像素）；EN 服较长的白色标签文字最多约 940 像素，
        # ALAS 的 500 会把未激活标签也判为激活，因此提高到 2500
        return Navbar(grids=grids, active_color=(237, 237, 237), inactive_color=(65, 78, 96),
                      active_count=2500, inactive_count=500)

    def has_white_band(self, threshold=1200):
        """领奖后的横幅弹窗：画面中部有一条足够高的白色横带。"""
        image = self.image_crop((0, 405, 1280, 560), copy=False)
        white_mask = cv2.inRange(rgb2luma(image), 200, 255)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 3))
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)
        count = 0
        for ok in (white_mask > 0).sum(axis=1) > threshold:
            count = count + 1 if ok else 0
            if count >= 50:
                return True
        return False

    def handle_season_get_items(self):
        """关闭领奖弹窗；点一键领取按钮所在位置即可关闭。"""
        if self.handle_get_items():
            return True
        if self.appear(GET_ITEMS_1, offset=(20, 100), interval=3):
            self.device.click(ISLAND_SEASON_TASK_RECEIVE_ALL)
            return True
        if self.has_white_band() and not self.appear(page_island_season.check_button):
            self.device.click(ISLAND_SEASON_TASK_RECEIVE_ALL)
            return True
        return False

    def receive_all_reward(self):
        """一键领取已完成任务的奖励，连续 3 秒无操作视为完成。"""
        clicked = False
        confirm_timer = Timer(3, count=6).start()
        for _ in self.loop(skip_first=False, timeout=60):
            if self.appear_then_click(ISLAND_SEASON_TASK_RECEIVE_ALL, offset=(20, 20), interval=2):
                clicked = True
                confirm_timer.reset()
                continue
            if self.handle_season_get_items():
                confirm_timer.reset()
                continue
            if confirm_timer.reached():
                break
        logger.info(f'[岛屿-季节任务] {"已领取任务奖励" if clicked else "没有可领取的任务奖励"}')

    def _task_rows(self):
        area = (DETECT_AREA[0] + ICON_AREA[0], DETECT_AREA[1] + ICON_AREA[1] - NAME_AREA[1],
                DETECT_AREA[2], DETECT_AREA[3])
        icons = TEMPLATE_ISLAND_SEASON_REWARD.match_multi(self.image_crop(area, copy=True), similarity=0.7,
                                                         threshold=5)
        return Points([(0., icon.area[1]) for icon in icons]).group(threshold=5)

    @cached_property
    def season_task_grid(self):
        grid = None
        self.season_task_rows_found = False
        for _ in self.loop(timeout=3):
            rows = self._task_rows()
            self.season_task_rows_found = len(rows) >= 1
            if len(rows) >= 1:
                origin_y = min(rows[:, 1]) + DETECT_AREA[1] - NAME_AREA[1]
            else:
                origin_y = DETECT_AREA[1] - NAME_AREA[1]
            grid = ButtonGrid(origin=(DETECT_AREA[0], origin_y), delta=TAB_DELTA, button_shape=TAB_SIZE,
                              grid_shape=(3, max(len(rows), 1)), name='SEASON_TASK_GRID')
            if len(rows) >= 1:
                break
        return grid

    @cached_property
    def task_ids_on_page(self):
        lang = server.server if server.server in ('jp', 'tw') else 'cnocr'
        ocr = SeasonTaskNameOcr([], lang=lang, letter=(57, 58, 60), name='SEASON_TASK_NAME_OCR')
        name_grid = self.season_task_grid.crop(NAME_AREA, name='SEASON_TASK_NAME_GRID')
        names = ocr.ocr([self.image_crop(button.area, copy=True) for button in name_grid.buttons], direct_ocr=True)
        season_ids = current_season_task_ids()
        if not season_ids:
            logger.warning(f'[岛屿-季节任务] {server.server} 服没有进行中的季节或缺少季节数据')
        ids = [match_task_name(name, season_ids) for name in names]
        logger.attr('SeasonTasks', ids)
        return ids

    def scan_unfinished(self):
        """从顶部扫到第一个「已领取」任务或底部，返回未完成任务 ID（已排序：可领取在前，已领取在后）。

        Returns:
            list[int] | None: 未完成任务 ID；第一页就识别不到任务卡片（页面未就绪或不在任务标签）时为 None，
                调用方应保留原有目标，避免写入错误目标。
        """
        ISLAND_SEASON_TASK_SCROLL.set_top(main=self, skip_first_screenshot=False)
        unfinished = []
        last_page = None
        for page in range(MAX_PAGES):
            del_cached_property(self, 'season_task_grid')
            del_cached_property(self, 'task_ids_on_page')
            grid = self.season_task_grid
            if not self.season_task_rows_found:
                if page == 0:
                    logger.warning('[岛屿-季节任务] 未识别到任务卡片，本次不更新季节任务目标')
                    return None
                return unfinished
            page_ids = self.task_ids_on_page
            # 翻页后内容不变（滚动未生效或已到底），不再重复读取
            if page_ids == last_page:
                return unfinished
            last_page = page_ids
            for task_id, button in zip(page_ids, grid.buttons):
                if TEMPLATE_ISLAND_SEASON_TASK_OBTAINED.match(self.image_crop(button.area, copy=True)):
                    logger.info('[岛屿-季节任务] 遇到已领取任务，停止扫描')
                    return unfinished
                if task_id is None:
                    logger.warning('[岛屿-季节任务] 无法识别任务名，跳过')
                elif task_id not in unfinished:
                    unfinished.append(task_id)
            if ISLAND_SEASON_TASK_SCROLL.at_bottom(main=self):
                return unfinished
            ISLAND_SEASON_TASK_SCROLL.next_page(main=self, skip_first_screenshot=False)
        logger.warning(f'[岛屿-季节任务] 翻页次数达到上限 {MAX_PAGES}')
        return unfinished

    def scan_season_task_targets(self):
        """
        Returns:
            dict[int, int] | None: 未完成季节任务需要的物品 {物品ID: 数量}；识别不到任务卡片时为 None。
        """
        logger.hr('Scan island season tasks', level=1)
        self.ui_ensure(page_island_season)
        self._season_bottom_navbar.set(self, left=SEASON_TASK_TAB)
        self.receive_all_reward()
        unfinished = self.scan_unfinished()
        if unfinished is None:
            return None
        logger.info(f'[岛屿-季节任务] 未完成任务 {len(unfinished)} 个: {unfinished}')
        return task_item_targets(unfinished)
