"""游戏原生连续作战的设置、结算与战役计数。"""

import cv2
import numpy as np

from module.base.timer import Timer
from module.exception import CampaignEnd, ScriptEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_ON, NEW_SHIP_SKIP
from module.logger import logger
from module.map.assets import (
    MULTIPLE_SORTIES_BOOK, MULTIPLE_SORTIES_BOOK_ON, MULTIPLE_SORTIES_CHECK, MULTIPLE_SORTIES_CLOSE,
    MULTIPLE_SORTIES_COUNT_MAX, MULTIPLE_SORTIES_COUNT_MINUS, MULTIPLE_SORTIES_COUNT_OCR,
    MULTIPLE_SORTIES_COUNT_PLUS, MULTIPLE_SORTIES_OIL_OCR,
    MULTIPLE_SORTIES_RESULT_CHECK, MULTIPLE_SORTIES_RESULT_EXIT, MULTIPLE_SORTIES_START,
)
from module.ocr.ocr import Digit


class MultipleSortiesOil(Digit):
    """按绿字字形宽度剔除「石油」，避免中文被数字模型识别成额外的 6。"""

    def pre_process(self, image):
        rgb = image.astype(np.int16)
        mask = ((rgb[:, :, 1] - rgb[:, :, 0] > 20)
                & (rgb[:, :, 1] - rgb[:, :, 2] > 25) & (rgb[:, :, 1] > 140)).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        units = [x for x, y, width, height, area in stats[1:] if width >= 18 and height >= 15]
        if not units:
            return np.full(image.shape[:2], 255, dtype=np.uint8)
        return (255 - mask[:, :min(units)] * 255).astype(np.uint8)


OCR_MULTIPLE_COUNT = Digit(MULTIPLE_SORTIES_COUNT_OCR, alphabet='0123456789')
OCR_MULTIPLE_OIL = MultipleSortiesOil(MULTIPLE_SORTIES_OIL_OCR, alphabet='0123456789')


def multiple_sorties_count(config, remaining=0, total_remaining=0, one_time=False):
    """将一次原生批次限制在当前任务剩余次数内；0 表示沿用普通作战。"""
    count = int(getattr(config, 'Campaign_MultipleSortiesCount', 0))
    if count <= 0:
        return 0
    if remaining > 0:
        count = min(count, remaining)
    if total_remaining > 0:
        count = min(count, total_remaining)
    if (one_time or config.StopCondition_MapAchievement != 'non_stop'
            or getattr(config, 'StopCondition_GetNewShip', False)
            or getattr(config, 'StopCondition_ReachLevel', 0)
            or getattr(config, 'FleetTraining_Enable', False)):
        count = min(count, 1)
    return count


class MultipleSorties:
    """混入地图操作；设置分支与 enter_map 共用同一个截图循环。"""

    def multiple_sorties_panel_appear(self):
        return self.appear(MULTIPLE_SORTIES_CHECK, offset=(20, 20))

    def multiple_sorties_result_appear(self):
        # 「合计获得奖励」也用于作战委托，必须匹配连续作战专属的正文。
        return self.appear(MULTIPLE_SORTIES_RESULT_CHECK, offset=(20, 20))

    def handle_multiple_sorties_stop(self):
        """在周回的地图移动阶段响应停止请求，关掉自律后由游戏结算当前批次。"""
        if not self.__dict__.get('_multiple_sorties_requested', 0):
            return False
        should_stop = self.__dict__.get('_multiple_sorties_should_stop')
        self._multiple_sorties_stop_requested |= (
            self.auto_search_oil_limit_triggered or self.auto_search_coin_limit_triggered
            or (callable(should_stop) and should_stop())
            or (self.config.StopCondition_GetNewShip and self.config.GET_SHIP_TRIGGERED)
        )
        if self._multiple_sorties_stop_requested:
            return self.appear_then_click(AUTO_SEARCH_MAP_OPTION_ON, offset=self._auto_search_offset, interval=3)
        return False

    def handle_multiple_sorties_preparation(self):
        """处理一帧连续作战设置；只有点击了界面才返回 True。

        Pages:
            in: 连续作战设置
            out: 连续作战设置 / 地图
        """
        if self._multiple_sorties_abort is not None:
            return self.appear_then_click(MULTIPLE_SORTIES_CLOSE, offset=(20, 20), interval=2)
        phase = self._multiple_sorties_phase
        if phase == 'max':
            if self.appear_then_click(MULTIPLE_SORTIES_COUNT_MAX, offset=(20, 20), interval=2):
                self._multiple_sorties_phase = 'limit'
                self._multiple_sorties_stable = Timer(0.6, count=2).start()
                self._multiple_sorties_last_count = None
                return True
            return False

        current = OCR_MULTIPLE_COUNT.ocr(self.device.image)
        if not OCR_MULTIPLE_COUNT.last_valid or current <= 0:
            self._multiple_sorties_stable.reset()
            return False
        if current != self._multiple_sorties_last_count:
            self._multiple_sorties_last_count = current
            self._multiple_sorties_stable.reset()
            return False
        if not self._multiple_sorties_stable.reached():
            return False
        if phase == 'limit':
            self._multiple_sorties_target = min(self._multiple_sorties_requested, current)
            self._multiple_sorties_phase = 'count'
            phase = 'count'
        target = self._multiple_sorties_target
        if current != target:
            button = MULTIPLE_SORTIES_COUNT_PLUS if current < target else MULTIPLE_SORTIES_COUNT_MINUS
            if self.appear_then_click(button, offset=(20, 20), interval=0.3):
                self._multiple_sorties_stable.reset()
                return True
            return False

        book_on = self.appear(MULTIPLE_SORTIES_BOOK_ON, offset=(3, 3))
        if book_on != self.config.Campaign_Use2xBook:
            button = MULTIPLE_SORTIES_BOOK_ON if book_on else MULTIPLE_SORTIES_BOOK
            if self.appear_then_click(button, offset=(3, 3), interval=2):
                self._multiple_sorties_stable.reset()
                return True
            return False
        cost = OCR_MULTIPLE_OIL.ocr(self.device.image)
        if not OCR_MULTIPLE_OIL.last_valid or cost <= 0:
            return False
        if self._multiple_sorties_oil - cost < self._multiple_sorties_oil_limit:
            self.config.task_delay(minute=60)
            self._multiple_sorties_abort = ScriptEnd('[连续作战] 预计油耗将超过石油停止下限')
            return self.appear_then_click(MULTIPLE_SORTIES_CLOSE, offset=(20, 20), interval=2)
        if phase != 'start':
            try:
                self.emotion.check_reduce(self._map_battle * target)
            except ScriptEnd as exc:
                self._multiple_sorties_abort = exc
                return self.appear_then_click(MULTIPLE_SORTIES_CLOSE, offset=(20, 20), interval=2)
        self._multiple_sorties_phase = 'start'
        if self.appear_then_click(MULTIPLE_SORTIES_START, offset=(20, 20), interval=3):
            logger.attr('连续作战次数', target)
            logger.attr('连续作战预计油耗', cost)
            return True
        return False

    def run_multiple_sorties(self, count=1, oil_limit=None):
        """复用舰队准备与逐场战斗处理，完成一批游戏原生连续作战。

        Args:
            count (int): 本批最多执行的关卡次数。
            oil_limit (int | None): 委托解锁使用自身油量下限，普通任务沿用停止条件。

        Returns:
            int: 正常批次按启动次数计入任务；已检测到中断时不计入整批。

        Pages:
            in: 章节选择页 / 关卡准备页
            out: 章节选择页
        """
        logger.hr('连续作战', level=2)
        self.map_get_info()
        rotation = self.__dict__.get('_fleet_rotation_preflight')
        if rotation is not None:
            rotation(self._map_battle)
        self._multiple_sorties_requested = count
        self._multiple_sorties_target = count
        self._multiple_sorties_phase = 'max'
        self._multiple_sorties_abort = None
        self._multiple_sorties_stop_requested = False
        self._multiple_sorties_dock_interrupted = False
        self._multiple_sorties_interrupted = False
        self.config.DOCK_FULL_TRIGGERED = False
        self._multiple_sorties_oil = self.get_oil()
        self._multiple_sorties_oil_limit = (max(
            self.config.StopCondition_OilLimit, self.config.StopCondition_OilLimitHardFloor)
            if oil_limit is None else max(0, oil_limit))
        self.map_is_auto_search = True
        self.map_is_2x_book = self.config.Campaign_Use2xBook
        self.map = self.MAP
        self.battle_count = 0
        self.lv_reset()
        result_seen = False
        try:
            self.ENTRANCE.area = self.ENTRANCE.button
            self.enter_map(self.ENTRANCE, mode=self.config.Campaign_Mode)
            self.map_is_auto_search = True
            while True:
                self.device.screenshot()
                if self.multiple_sorties_result_appear():
                    result_seen = True
                    if self.appear_then_click(MULTIPLE_SORTIES_RESULT_EXIT, offset=(20, 20), interval=2):
                        continue
                if result_seen and self.appear(self.ENTRANCE):
                    interrupted = (self._multiple_sorties_interrupted
                                   or self._multiple_sorties_stop_requested
                                   or self._multiple_sorties_dock_interrupted
                                   or self.config.DOCK_FULL_TRIGGERED)
                    return 0 if interrupted else self._multiple_sorties_target
                if self.handle_urgent_commission():
                    continue
                if self.appear_then_click(NEW_SHIP_SKIP, offset=(20, 20), interval=2, similarity=0.75):
                    continue
                if self.handle_story_skip():
                    continue
                if result_seen:
                    continue
                try:
                    # 周回已负责船坞满、强化/退役、低心情、战败及处理后的自律恢复。
                    self.auto_search_execute_a_battle()
                except CampaignEnd:
                    if getattr(getattr(self, 'combat_result', None), 'defeated', False):
                        self._multiple_sorties_interrupted = True
                    # 原生批次结算由外层关闭，不点击「再次前往」。
                    continue
                training = self.__dict__.get('_fleet_training_after_battle')
                if training is not None:
                    training()
        finally:
            self._multiple_sorties_dock_interrupted |= bool(self.config.DOCK_FULL_TRIGGERED)
            self._multiple_sorties_requested = 0
            self._multiple_sorties_stop_requested = False
            # 原生批次不能套用普通单图的续接计数，异常时交回原有重启流程。
            self._recovery_map_active = False
            self.device.screenshot_interval_set()
