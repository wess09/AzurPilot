from datetime import datetime, timedelta

import numpy as np
from cached_property import cached_property

from module.base.button import ButtonGrid
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
from module.ui.page import page_island_phone
from module.ui_white.assets import POPUP_CANCEL_WHITE


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
        self.items = SelectedGrids([])
        self.parse_transport(main)
        if not self.valid:
            self.start = False
        self.create_time = datetime.now()

    def parse_transport(self, main):
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
            self.items = SelectedGrids([
                CargoPreparationTransportItem(self.image, button, self.blacklist)
                for button in grids.buttons
            ]).select(valid=True)
            self.start = self.items.select(load=True).count == self.items.count
            self.refresh = (
                main.appear(TRANSPORT_REFRESH, offset=self.offset)
                and bool(self.items.select(refresh=True).count)
            )

            if not main.match_template_color(TRANSPORT_START, offset=self.offset):
                self.start = False
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
        if self.valid:
            self.status = 'running'
            self.start = False
            self.refresh = False
            self.create_time = datetime.now()

    @property
    def finish_time(self):
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
        return ', '.join([f'{k}: {v}' for k, v in info.items()])


class CargoPreparationTransportItem:
    """货运委托中的单个货物格。"""

    def __init__(self, image, button, blacklist):
        self.image_raw = image
        self.button = button
        self.blacklist = blacklist
        self.image = crop(image, button.area)
        self.valid = self.predict_valid()
        self.refresh = False
        self.load = self.predict_load()

    def predict_valid(self):
        mean = np.mean(np.max(self.image, axis=2) > 234)
        blue_bar_check = image_color_count(
            self.image[:10, :, :],
            color=(90, 201, 255),
            threshold=221,
            count=500
        )
        return mean > 0.3 and not blue_bar_check

    def predict_load(self):
        if not self.valid:
            return False
        self.refresh = self.handle_blacklist_items()
        if self.refresh:
            return False
        return TEMPLATE_ITEM_SATISFIED.match(rgb2gray(self.image))

    def handle_blacklist_items(self):
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
        logger.hr('Island Cargo Preparation Run', level=1)

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

        logger.hr('Cargo preparation status', level=2)
        for comm in commissions:
            logger.attr('Cargo Preparation', comm)

        return commissions

    def transport_refresh(self, comm):
        """
        替换包含黑名单货物的货运委托。

        更换页面默认选中第一个可替换委托，因此只需要确认列表不为空，
        再点击确定按钮。
        """
        logger.info('Cargo preparation replace commission')
        self.interval_clear([TRANSPORT_REFRESH, CARGO_PREPARATION_REPLACE_CONFIRM])

        if not self._open_replace_page(comm):
            return False

        for _ in range(self.REPLACE_REFRESH_TRIALS):
            result = self._confirm_first_replacement()
            if result == 'success':
                return True
            if result == 'empty_refreshed':
                continue
            return False

        logger.warning('更换列表刷新后仍为空，返回货运界面')
        self._back_to_transport()
        return False

    def _needs_replacement(self, comm):
        """
        判断货运栏位是否需要进入更换页面。

        空白栏位需要直接确认默认选中的第一个委托；待装载栏位仅在命中黑名单时更换。
        """
        if comm.status == 'empty':
            return True
        return comm.status == 'pending' and comm.refresh

    def transport_slot_empty(self, index, offset):
        """检测白色空白货运栏位。"""
        return self.appear(CARGO_PREPARATION_EMPTY_REPLACE, offset=offset)

    def _transport_detect(self):
        """从当前截图中检测所有货运委托。"""
        logger.hr('Transport Commission detect')
        commissions = []
        for index in range(3):
            comm = CargoPreparationTransport(main=self, index=index, blacklist=self.blacklist)
            logger.attr('Transport Commission', comm)
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
                logger.warning('No commission detected, retry commission detect')
                continue
            if commissions.select(valid=False).count:
                logger.warning('Found 1 invalid commission at least, retry commission detect')
                continue
            return commissions.select(valid=True)

        logger.info('trials of transport commission detect exhausted, stop')
        return commissions.select(valid=True)

    def transport_receive(self):
        """领取运输页面上所有已完成的货运委托。"""
        logger.hr('Island Transport', level=2)
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
        logger.info('Transport commission start')
        self.interval_clear([GET_ITEMS_ISLAND, TRANSPORT_START, POPUP_CANCEL_WHITE])
        success = True
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
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

        logger.warning('进入更换委托页面超时')
        return False

    def _confirm_first_replacement(self):
        """
        确认更换页面默认选中的第一个委托。

        Returns:
            str: success / empty_refreshed / empty_unavailable / failed
        """
        for _ in self.loop(timeout=8):
            if not self.appear(REPLACE_PAGE_CHECK, offset=(20, 20)):
                continue

            if self.appear(EMPTY_LIST_CHECK, offset=(20, 20)):
                logger.info('更换委托列表为空')
                if self.appear_then_click(REFRESH_BUTTON_BLUE, offset=(20, 20), interval=2):
                    logger.info('刷新更换委托列表')
                    self._wait_replace_refresh()
                    return 'empty_refreshed'
                if self.appear(REFRESH_BUTTON_GREY, offset=(20, 20)):
                    logger.info('更换委托列表为空且刷新不可用')
                    self._back_to_transport()
                    return 'empty_unavailable'
                continue

            if self.appear_then_click(CARGO_PREPARATION_REPLACE_CONFIRM, offset=(20, 20), interval=2):
                logger.info('确认更换默认选中的货运委托')
                if self._wait_transport_after_replace():
                    return 'success'
                return 'failed'

        logger.warning('确认更换委托超时')
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
            if self.island_in_transport():
                if confirm_timer.reached():
                    return True
            else:
                confirm_timer.reset()

        logger.warning('更换委托后未回到货运界面')
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
            logger.info(f'所有货运栏位暂无可操作委托，下次检测: {target}')
            self.config.task_delay(target=target)
            return

        future_finish = sorted([
            finish for finish in commissions.get('finish_time')
            if finish is not None and finish > datetime.now()
        ])
        if future_finish:
            target = future_finish[0]
            logger.info(f'下次货物筹备检测: {target}')
            self.config.task_delay(target=target)
            return

        if commissions.count and commissions.select(status='locked').count == commissions.count:
            target = self._next_grey_retry_time()
            logger.info(f'所有货运栏位不可委托，下次检测: {target}')
            self.config.task_delay(target=target)
            return

        logger.info('暂无可确认完成时间，2 小时后重新检测货物筹备')
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
        now = datetime.now().replace(microsecond=0)
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
        logger.info('返回岛屿手机页面')
        for _ in self.loop():
            if self.ui_page_appear(page_island_phone):
                break
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self.ui_additional():
                continue
