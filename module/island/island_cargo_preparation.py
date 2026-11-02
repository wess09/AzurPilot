"""岛屿货物筹备与运输模块。

处理岛屿货物筹备界面的检测、刷新与运输启动流程。
包含运输状态识别（待处理/运行中）、运输时间 OCR、物品满意度模板匹配等核心功能。
"""
from datetime import timedelta

from module.config.time_source import now as current_time

import numpy as np
from cached_property import cached_property
from scipy import ndimage

from module.base.button import Button, ButtonGrid
from module.base.timer import Timer
from module.base.utils import area_offset, crop, image_color_count, rgb2gray
from module.island.assets import (
    GET_ITEMS_ISLAND,
    ISLAND_BACK,
    OCR_TRANSPORT_REFRESH,
    OCR_TRANSPORT_TIME,
    OCR_TRANSPORT_TIME_REMAIN,
    TEMPLATE_ITEM_SATISFIED,
    TRANSPORT_LOCKED,
    TRANSPORT_RECEIVE,
    TRANSPORT_REFRESH,
    TRANSPORT_REFRESH_CHECK,
    TRANSPORT_START,
    TRANSPORT_STATUS_PENDING,
    TRANSPORT_STATUS_RUNNING,
)
from module.island_cargo_preparation.assets import (
    CARGO_PREPARATION_EMPTY_REPLACE,
    CARGO_PREPARATION_REPLACE_CONFIRM,
    EMPTY_LIST_CHECK,
    REFRESH_BUTTON_BLUE,
    REFRESH_BUTTON_GREY,
    REPLACE_PAGE_CHECK,
    TEMPLATE_CARGO_MILK,
)
from module.island.ui import IslandUI
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.ocr.ocr import Duration
from module.ui.page import page_island, page_island_phone
from module.ui_white.assets import POPUP_CANCEL_WHITE


def cargo_can_start(available_item_count, action_button_active, refresh):
    """判断待处理货运委托是否可以点击装载/出发。

    一个委托可能只有 1～2 个实际货物格，后续格子为空时不会进入
    ``available_item_count``。装载状态不能作为启动前提：按钮本身会先补装
    缺失货物，再切换为出发；这里只要求至少有一个实际货物格、按钮可用，
    且没有命中黑名单。

    Args:
        available_item_count (int): 实际存在的有效货物格数量。
        action_button_active (bool): 右侧装载/出发按钮是否可用。
        refresh (bool): 是否因黑名单需要更换委托。

    Returns:
        bool: 是否允许当前流程点击该按钮。
    """
    return bool(available_item_count > 0 and action_button_active and not refresh)


def should_replace_unfillable(short, delivered, refresh):
    """判断无法凑齐货物的待装载委托是否应当更换。

    更换委托会扣除一次运输次数，且已提交的货物不退还。因此只更换尚未提交
    任何货物、且仍缺货的委托；已提交过部分货物的委托保留等待补齐。

    Args:
        short (bool): 是否存在库存不足的货物格。
        delivered (bool): 是否已有货物格提交完成。
        refresh (bool): 是否已因黑名单需要更换。

    Returns:
        bool: 是否需要因缺货而更换委托。
    """
    return bool(short and not delivered and not refresh)


# 更换委托列表中每行左侧的序号（01、02……）所在列，以及右侧货物数量所在横向范围
JOB_LIST_AREA = (405, 150, 900, 580)
JOB_LIST_NUMBER_COLUMN = (412, 450)
JOB_LIST_COUNT_COLUMN = (488, 900)
JOB_LIST_ROW_VISIBLE = (190, 540)


def _text_components(mask, min_width, min_height):
    """返回二值图中足够大的文字连通块数量。"""
    labels, _ = ndimage.label(ndimage.binary_dilation(mask, iterations=2))
    count = 0
    for region in ndimage.find_objects(labels):
        height = region[0].stop - region[0].start
        width = region[1].stop - region[1].start
        if width >= min_width and height >= min_height:
            count += 1
    return count


def classify_job_list_rows(image):
    """识别更换委托列表中当前可见的委托行，并判断每行货物是否都能凑齐。

    列表不默认选中任何委托，且保留上次的滚动位置，因此按每行左侧的序号定位行。
    每个货物格下方显示「库存/需求」：库存足够时为蓝色，不足时为红色（选中行
    会被高亮染成偏粉的红色）。一行内全部为蓝色才视为可完成。

    Args:
        image (np.ndarray): 截图。

    Returns:
        list[tuple[int, bool]]: 按从上到下排序的 (行中心 y, 是否可完成)。
    """
    img = image.astype(int)
    x1, y1, x2, y2 = JOB_LIST_AREA
    number_left, number_right = JOB_LIST_NUMBER_COLUMN
    dark = img[y1:y2, number_left:number_right].max(axis=2) < 110
    labels, _ = ndimage.label(ndimage.binary_dilation(dark, iterations=2))
    rows = []
    for region in ndimage.find_objects(labels):
        height = region[0].stop - region[0].start
        width = region[1].stop - region[1].start
        if width < 8 or height < 12:
            continue
        center_y = (region[0].start + region[0].stop) // 2 + y1
        if not JOB_LIST_ROW_VISIBLE[0] <= center_y <= JOB_LIST_ROW_VISIBLE[1]:
            continue
        count_left, count_right = JOB_LIST_COUNT_COLUMN
        strip = img[center_y + 12:center_y + 40, count_left:count_right]
        r, g, b = strip[..., 0], strip[..., 1], strip[..., 2]
        enough = _text_components((b > 200) & (r < 120) & (g > 140), 14, 10)
        short = _text_components((r - b > 25) & (r - g > 40) & (r > 150), 14, 10)
        rows.append((center_y, bool(enough and not short)))
    return sorted(rows)


class CargoPreparationTransport:
    """货物筹备中的单个货运栏位。"""

    def __init__(self, main, index, blacklist):
        self.index = index
        self.blacklist = blacklist
        self.image = main.device.image
        self.valid = True
        self.locked = False
        self.duration = None
        self.start = True
        self.refresh = False
        self.short = False
        self.delivered = False
        self.replace_unfillable = False
        self.items = SelectedGrids([])
        self.parse_transport(main)
        if not self.valid:
            self.start = False
        self.create_time = current_time()

    def parse_transport(self, main):
        """解析当前货运栏位的状态、倒计时和货物格子列表。

        Args:
            main (IslandCargoPreparation): 货物筹备任务实例。
        """
        offset = (-20, -20, 20, 20)
        delta = 176
        self.offset = area_offset(offset, (0, delta * self.index))

        lock_offset = area_offset(offset, (0, delta * (self.index - 1)))
        if self.index >= 1 and main.appear(TRANSPORT_LOCKED, lock_offset):
            self.locked = True
            self.status = 'locked'
            self.start = False
            self.refresh = False
            return

        self.status = self.get_transport_status(main)
        if self.status == 'unknown':
            self.valid = False
            return
        if self.status == 'pending':
            button = OCR_TRANSPORT_TIME.move((0, self.offset[1] + 20))
            ocr = Duration(button, lang='cnocr', letter=(207, 207, 207), name='OCR_TRANSPORT_TIME')
            self.duration = ocr.ocr(self.image)
            if not self.duration.total_seconds():
                self.valid = False
                return

            origin_y = 174 + delta * self.index
            grids = ButtonGrid(
                origin=(481, origin_y),
                delta=(105, 0),
                button_shape=(86, 86),
                grid_shape=(3, 1),
                name='ITEMS'
            )
            cells = SelectedGrids([
                CargoPreparationTransportItem(self.image, button, self.blacklist)
                for button in grids.buttons
            ])
            self.items = cells.select(valid=True)
            # 国际服逐件提交货物，已提交的格子显示蓝底「COMPLETED」印章，不再计入待装载货物
            self.delivered = bool(cells.select(completed=True).count)
            self.short = bool(self.items.filter(lambda item: not item.load and not item.refresh).count)
            self.refresh = (
                main.appear(TRANSPORT_REFRESH, offset=self.offset)
                and bool(self.items.select(refresh=True).count)
            )
            self.replace_unfillable = (
                main.appear(TRANSPORT_REFRESH, offset=self.offset)
                and should_replace_unfillable(self.short, self.delivered, self.refresh)
            )
            self.start = cargo_can_start(
                available_item_count=self.items.count,
                action_button_active=main.match_template_color(
                    TRANSPORT_START, offset=self.offset
                ),
                refresh=self.refresh,
            )
        elif self.status == 'running':
            self.start = False
            button = OCR_TRANSPORT_TIME_REMAIN.move((0, self.offset[1] + 20))
            ocr = Duration(button, name='OCR_TRANSPORT_TIME')
            self.duration = ocr.ocr(self.image)
            if not self.duration.total_seconds():
                self.valid = False
                return
        elif self.status == 'finished':
            self.start = False
        elif self.status == 'refreshing':
            self.start = False
            button = OCR_TRANSPORT_REFRESH.move((0, self.offset[1] + 20))
            ocr = Duration(button, letter=(63, 64, 66), name='OCR_TRANSPORT_REFRESH')
            self.duration = ocr.ocr(self.image)
            if not self.duration.total_seconds():
                self.valid = False
                return
        elif self.status == 'empty':
            self.start = False
            self.refresh = True

    def get_transport_status(self, main):
        """获取当前货运栏位的状态字符串。

        Args:
            main (IslandCargoPreparation): 货物筹备任务实例。

        Returns:
            str: 状态标识（'pending', 'running', 'finished', 'refreshing', 'empty', 'unknown'）。
        """
        if main.appear(TRANSPORT_STATUS_PENDING, offset=self.offset):
            return 'pending'
        if main.appear(TRANSPORT_STATUS_RUNNING, offset=self.offset):
            return 'running'
        if main.appear(TRANSPORT_RECEIVE, offset=self.offset):
            return 'finished'
        if main.appear(TRANSPORT_REFRESH_CHECK, offset=self.offset):
            return 'refreshing'
        if main.transport_slot_empty(index=self.index, offset=self.offset):
            return 'empty'
        return 'unknown'

    def convert_to_running(self):
        """将栏位状态本地转换为进行中，并记录创建时间。"""
        if self.valid:
            self.status = 'running'
            self.start = False
            self.refresh = False
            self.create_time = current_time()

    @property
    def finish_time(self):
        """获取货运委托预计完成时间。

        Returns:
            datetime.datetime | None: 预计完成时间点，无效时返回 None。
        """
        if self.valid and self.duration is not None:
            return (self.create_time + self.duration).replace(microsecond=0)
        return None

    def __str__(self):
        if not self.valid:
            return f'Index: {self.index} (Invalid)'
        if self.locked:
            return f'Index: {self.index} (Locked)'
        info = {'Index': self.index, 'Status': self.status}
        if self.duration:
            info['Duration'] = self.duration
        info['Start'] = self.start
        info['Refresh'] = self.refresh
        if self.status == 'pending':
            info['Short'] = self.short
            info['Delivered'] = self.delivered
            info['ReplaceUnfillable'] = self.replace_unfillable
        return ', '.join([f'{k}: {v}' for k, v in info.items()])


class CargoPreparationTransportItem:
    """货运委托中的单个货物格。"""

    def __init__(self, image, button, blacklist):
        self.image_raw = image
        self.button = button
        self.blacklist = blacklist
        self.image = crop(image, button.area)
        self.completed = self.predict_completed()
        self.valid = self.predict_valid()
        self.refresh = False
        self.load = self.predict_load()

    def predict_completed(self):
        """检测货物格子是否已提交完成（顶部蓝条、蓝底「COMPLETED」印章）。

        Returns:
            bool: 已提交返回 True，否则返回 False。
        """
        return bool(image_color_count(
            self.image[:10, :, :],
            color=(90, 201, 255),
            threshold=34,
            count=500
        ))

    def predict_valid(self):
        """检测当前货物格子是否为有效格子。

        Returns:
            bool: 有效返回 True，否则返回 False。
        """
        mean = np.mean(np.max(self.image, axis=2) > 234)
        return mean > 0.3 and not self.completed

    def predict_load(self):
        """预测货物格子是否满足装载条件或命中黑名单。

        Returns:
            bool: 满足装载且未命中黑名单返回 True，否则返回 False。
        """
        if not self.valid:
            return False
        self.refresh = self.handle_blacklist_items()
        if self.refresh:
            return False
        return TEMPLATE_ITEM_SATISFIED.match(rgb2gray(self.image))

    def handle_blacklist_items(self):
        """匹配当前货物格子是否命中黑名单物品模板。

        Returns:
            bool: 命中黑名单返回 True，否则返回 False。
        """
        for template in self.blacklist:
            if template.match(self.image, similarity=0.80):
                return True
        return False

    def __str__(self):
        if not self.valid:
            return '(Invalid)'
        info = {'Load': self.load, 'Refresh': self.refresh}
        return ', '.join([f'{k}: {v}' for k, v in info.items()])


class IslandCargoPreparation(IslandUI):
    """
    岛屿货物筹备。

    负责进入货运委托界面，领取已完成委托，并按货物黑名单刷新或装载可提交委托。

    Pages:
        in: page_island_phone
        out: page_island_phone
    """

    DEFAULT_DELAY = timedelta(hours=2)
    EVENING_DELAY_HOUR = 18
    EARLY_MORNING_DELAY_HOUR = 3
    REPLACE_REFRESH_TRIALS = 2
    REPLACE_ROUNDS = 3

    @cached_property
    def blacklist(self):
        """
        货物黑名单。

        当前仅支持 Milk，且使用 TEMPLATE_CARGO_MILK 资源直接识别货物格子。
        """
        names = str(self.config.IslandCargoPreparation_Blacklist or '')
        blacklist = []
        if 'milk' in names.lower():
            blacklist.append(TEMPLATE_CARGO_MILK)
        return blacklist

    def run(self):
        logger.hr('岛屿货物准备运行', level=1)

        self.ui_ensure(page_island)
        self.ui_goto(page_island_phone, get_ship=False)
        self.island_transport_enter()

        commissions = self._run_cargo_preparation()
        self._schedule_next_run(commissions)
        self._back_to_island_phone()

    def _run_cargo_preparation(self):
        """
        执行一次货物筹备流程。

        先领取已完成委托，再替换命中黑名单或空白的委托，最后装载所有可提交委托。
        """
        self.transport_receive()
        commissions = self.transport_detect(trial=5)

        blocked_replacements = set()
        for _ in range(self.REPLACE_ROUNDS):
            targets = commissions.filter(
                lambda comm: self._needs_replacement(comm) and comm.index not in blocked_replacements
            )
            if not targets.count:
                break

            replaced = False
            for comm in targets:
                if self.transport_refresh(comm):
                    replaced = True
                else:
                    blocked_replacements.add(comm.index)

            if not replaced:
                break
            commissions = self.transport_detect(trial=5, skip_first_screenshot=False)

        for comm in commissions.select(status='pending', start=True):
            if self.transport_start(comm):
                comm.convert_to_running()

        logger.hr('货物准备状态', level=2)
        for comm in commissions:
            logger.attr('货运委托', comm)

        return commissions

    def transport_refresh(self, comm):
        """
        为空白栏位选择委托，或更换命中黑名单/无法凑齐货物的委托。

        更换列表不保证默认选中可完成的委托，因此只选择货物全部足够的委托；
        列表中没有可完成的委托时刷新一次，仍没有就保留原委托，避免为换成
        另一个同样无法完成的委托而白白扣除运输次数。
        """
        logger.info('货物准备替换委托')
        self.interval_clear([TRANSPORT_REFRESH, CARGO_PREPARATION_REPLACE_CONFIRM])

        if not self._open_replace_page(comm):
            return False

        for _ in range(self.REPLACE_REFRESH_TRIALS):
            result = self._confirm_fillable_replacement()
            if result == 'success':
                return True
            if result == 'refreshed':
                continue
            return False

        logger.warning('[岛屿-货物筹备] 刷新后仍没有可完成的委托，保留原委托并返回货运界面')
        self._back_to_transport()
        return False

    def _needs_replacement(self, comm):
        """
        判断货运栏位是否需要进入更换页面。

        空白栏位需要选择委托；待装载栏位在命中黑名单，或尚未提交任何货物且
        存在库存不足的货物时更换。已提交过货物的委托更换后不退还，保留等待补齐。
        """
        if comm.status == 'empty':
            return True
        return comm.status == 'pending' and (comm.refresh or comm.replace_unfillable)

    def transport_slot_empty(self, index, offset):
        """检测白色空白货运栏位。"""
        return self.appear(CARGO_PREPARATION_EMPTY_REPLACE, offset=offset)

    def _transport_detect(self):
        """从当前截图中检测所有货运委托。"""
        logger.hr('运输委托检测')
        commissions = []
        for index in range(3):
            comm = CargoPreparationTransport(main=self, index=index, blacklist=self.blacklist)
            logger.attr('运输委托', comm)
            for item in comm.items:
                logger.attr(item.button, item)
            commissions.append(comm)
        return SelectedGrids(commissions)

    def transport_detect(self, trial=1, skip_first_screenshot=True):
        """检测所有货运委托，支持重试。"""
        commissions = SelectedGrids([])
        for _ in range(trial):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            commissions = self._transport_detect()
            if not commissions.count:
                logger.warning('[岛屿-货运] 未检测到委托，重试检测')
                continue
            if commissions.select(valid=False).count:
                logger.warning('[岛屿-货运] 检测到无效委托，重试检测')
                continue
            return commissions.select(valid=True)

        logger.info('[岛屿-货运] 委托检测重试耗尽，停止')
        return commissions.select(valid=True)

    def transport_receive(self):
        """领取运输页面上所有已完成的货运委托。"""
        logger.hr('岛屿运输', level=2)
        self.device.click_record_clear()
        self.interval_clear([GET_ITEMS_ISLAND, TRANSPORT_RECEIVE, POPUP_CANCEL_WHITE])
        success = True
        click_timer = Timer(5, count=10).start()
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.handle_info_bar():
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.appear_then_click(TRANSPORT_RECEIVE, offset=(-20, -20, 20, 400), interval=2):
                success = False
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.handle_get_items():
                success = True
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.handle_popup_cancel('REFRESH_CANCEL', offset=(30, 30)):
                click_timer.reset()
                confirm_timer.reset()
                continue

            if click_timer.reached():
                success = True
                self.device.click(GET_ITEMS_ISLAND)
                self.device.sleep(0.3)
                click_timer.reset()
                confirm_timer.reset()
                continue

            if self.island_in_transport():
                if success and confirm_timer.reached():
                    break
                click_timer.reset()
            else:
                confirm_timer.reset()

        return success

    def transport_start(self, comm):
        """启动指定的货运委托。"""
        logger.info('[岛屿-货运] 运输委托开始')
        self.interval_clear([GET_ITEMS_ISLAND, TRANSPORT_START, POPUP_CANCEL_WHITE])
        success = True
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop(timeout=30):
            if self.appear_then_click(TRANSPORT_START, offset=comm.offset, interval=2):
                success = False
                confirm_timer.reset()
                continue

            if self.handle_get_items():
                success = True
                confirm_timer.reset()
                continue

            if self.handle_popup_cancel('REFRESH_CANCEL', offset=(30, 30)):
                confirm_timer.reset()
                continue

            if self.island_in_transport():
                if success and confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
        else:
            logger.warning('[岛屿-货运] 启动或装载货运委托超时')
            return False
        return success

    def _open_replace_page(self, comm):
        """从货运栏位打开更换委托页面。"""
        replace_button = TRANSPORT_REFRESH
        if comm.status == 'empty':
            replace_button = CARGO_PREPARATION_EMPTY_REPLACE

        for _ in self.loop(timeout=8):
            if self.appear(REPLACE_PAGE_CHECK, offset=(20, 20)):
                return True
            if comm.status == 'empty':
                if self.appear_then_click(replace_button, offset=comm.offset, interval=2):
                    continue
            if self.appear_then_click(TRANSPORT_REFRESH, offset=comm.offset, interval=2):
                continue
            if self.ui_additional():
                continue

        logger.warning('[岛屿-货物筹备] 进入更换委托页面超时')
        return False

    def _refresh_replace_list(self, reason):
        """刷新更换委托列表；刷新不可用时返回货运界面。

        Returns:
            str: refreshed / no_fillable
        """
        if self.appear_then_click(REFRESH_BUTTON_BLUE, offset=(20, 20), interval=2):
            logger.info(f'[岛屿-货物筹备] {reason}，刷新更换委托列表')
            self._wait_replace_refresh()
            return 'refreshed'
        logger.info(f'[岛屿-货物筹备] {reason}且刷新不可用，保留原委托')
        self._back_to_transport()
        return 'no_fillable'

    def _confirm_fillable_replacement(self):
        """
        在更换页面选中第一个货物全部足够的委托并确认。

        Returns:
            str: success / refreshed / no_fillable / failed
        """
        selected = False
        for _ in self.loop(timeout=8):
            if not self.appear(REPLACE_PAGE_CHECK, offset=(20, 20)):
                continue

            if self.appear(EMPTY_LIST_CHECK, offset=(20, 20)):
                if self.appear(REFRESH_BUTTON_GREY, offset=(20, 20)):
                    logger.info('[岛屿-货物筹备] 更换委托列表为空且刷新不可用')
                    self._back_to_transport()
                    return 'no_fillable'
                return self._refresh_replace_list('更换委托列表为空')

            if not selected:
                rows = classify_job_list_rows(self.device.image)
                logger.attr('更换委托行（y, 可完成）', rows)
                target = next((center_y for center_y, fillable in rows if fillable), None)
                if target is None:
                    if not rows:
                        continue
                    return self._refresh_replace_list('更换列表中没有货物全部足够的委托')
                row = Button(
                    area=(470, target - 35, 890, target + 35), color=(),
                    button=(560, target - 30, 880, target + 30), name='CARGO_PREPARATION_JOB_ROW',
                )
                self.device.click(row)
                selected = True
                continue

            if self.appear_then_click(CARGO_PREPARATION_REPLACE_CONFIRM, offset=(20, 20), interval=2):
                logger.info('[岛屿-货物筹备] 确认更换为货物全部足够的委托')
                if self._wait_transport_after_replace():
                    return 'success'
                return 'failed'

        logger.warning('[岛屿-货物筹备] 确认更换委托超时')
        self._back_to_transport()
        return 'failed'

    def _wait_replace_refresh(self):
        """等待更换列表刷新完成。"""
        wait_timer = Timer(5, count=10).start()
        for _ in self.loop(timeout=6, skip_first=False):
            if wait_timer.reached():
                break

    def _wait_transport_after_replace(self):
        """等待更换确认后回到货运委托页面。"""
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop(timeout=12):
            if self.handle_popup_confirm('CARGO_PREPARATION_REPLACE', offset=(30, 30)):
                confirm_timer.reset()
                continue
            # 更换已有委托时弹出「已提交的货物不退还、扣除运输次数」确认框；国际服的白色确认框
            # 不匹配通用弹窗资源，但确认按钮文字与更换列表的确认按钮相同，列表关闭后在弹窗位置搜索
            if not self.appear(REPLACE_PAGE_CHECK, offset=(20, 20)) and self.appear_then_click(
                    CARGO_PREPARATION_REPLACE_CONFIRM, offset=(120, 130), interval=2):
                confirm_timer.reset()
                continue
            if self.island_in_transport():
                if confirm_timer.reached():
                    return True
            else:
                confirm_timer.reset()

        logger.warning('[岛屿-货物筹备] 更换委托后未回到货运界面')
        self._back_to_transport()
        return False

    def _back_to_transport(self):
        """从更换页面返回货运委托页面。"""
        for _ in self.loop(timeout=8):
            if self.island_in_transport():
                return True
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self.ui_additional():
                continue
        return False

    def _schedule_next_run(self, commissions):
        """根据委托状态设置下次运行时间。"""
        if self._all_slots_inactive(commissions):
            target = self._next_grey_retry_time()
            logger.info(f'[岛屿-货物筹备] 所有货运栏位暂无可操作委托，下次检测: {target}')
            self.config.task_delay(target=target)
            return

        future_finish = [
            finish for finish in commissions.get('finish_time') or []
            if finish is not None and finish > current_time()
        ]
        if future_finish:
            target = max(future_finish)
            logger.info(f'[岛屿-货物筹备] 下次货物筹备检测（最晚完成）: {target}')
            self.config.task_delay(target=target)
            return

        if commissions.count and commissions.select(status='locked').count == commissions.count:
            target = self._next_grey_retry_time()
            logger.info(f'[岛屿-货物筹备] 所有货运栏位不可委托，下次检测: {target}')
            self.config.task_delay(target=target)
            return

        logger.info('[岛屿-货物筹备] 暂无可确认完成时间，2 小时后重新检测货物筹备')
        self.config.task_delay(minute=self.DEFAULT_DELAY.total_seconds() / 60)

    def _all_slots_inactive(self, commissions):
        """判断是否所有栏位都没有可启动或可替换动作。"""
        if not commissions.count:
            return False
        return all(
            comm.status in {'locked', 'pending'} and not comm.start and not comm.refresh
            for comm in commissions
        )

    def _next_grey_retry_time(self):
        now = current_time().replace(microsecond=0)
        today_morning = now.replace(hour=self.EARLY_MORNING_DELAY_HOUR, minute=0, second=0)
        today_evening = now.replace(hour=self.EVENING_DELAY_HOUR, minute=0, second=0)
        tomorrow_morning = (now + timedelta(days=1)).replace(
            hour=self.EARLY_MORNING_DELAY_HOUR, minute=0, second=0
        )
        if now < today_morning:
            return today_morning
        if now < today_evening:
            return today_evening
        return tomorrow_morning

    def _back_to_island_phone(self):
        logger.info('[岛屿-货物筹备] 返回岛屿手机页面')
        for _ in self.loop():
            if self.ui_page_appear(page_island_phone):
                break
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self.ui_additional():
                continue
