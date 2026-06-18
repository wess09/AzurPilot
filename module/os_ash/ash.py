from datetime import datetime, timedelta

from module.base.utils import image_left_strip
from module.combat.combat import BATTLE_PREPARATION, Combat
from module.config.utils import DEFAULT_TIME
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.os_ash.assets import *
from module.os_handler.map_event import MapEventHandler
from module.ui.assets import BACK_ARROW
from module.ui.ui import UI


class DailyDigitCounter(DigitCounter):
    """每日计数器，对图像左侧进行裁剪以去除干扰区域。"""

    def pre_process(self, image):
        image = super().pre_process(image)
        image = image_left_strip(image, threshold=120, length=35)
        return image


class AshBeaconFinished(Exception):
    """信标战斗已完成的异常信号。"""
    pass


class AshCombat(Combat):
    """余烬信标战斗处理器，处理战斗状态和战斗准备。"""

    def handle_battle_status(self, drop=None):
        """
        处理战斗结束状态，点击结算画面。

        Args:
            drop (DropImage): 掉落图像处理器。

        Returns:
            bool: 是否采取了行动。
        """
        if self.is_combat_executing():
            return False
        if self.appear(BATTLE_STATUS, offset=(120, 20), interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS)
            return True
        if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
            self.device.click(BACK_ARROW)
            return True
        if super().handle_battle_status(drop=drop):
            return True

        return False

    def handle_exp_info(self):
        """
        META 战斗不掉落经验，无需处理经验信息。

        BATTLE_STATUS 的随机背景可能误触发 EXP_INFO_B，直接忽略。
        """
        return False

    def handle_battle_preparation(self):
        """
        处理战斗准备页面，点击开始战斗按钮。

        如果信标已完成或为空，则抛出 AshBeaconFinished。

        Returns:
            bool: 是否采取了行动。
        """
        if super().handle_battle_preparation():
            return True

        if self.appear_then_click(ASH_START, offset=(30, 30), interval=2):
            return True
        if self.handle_get_items():
            return True
        if self.appear(BEACON_REWARD):
            logger.info("Ash beacon already finished.")
            raise AshBeaconFinished
        if self.appear(BEACON_EMPTY, offset=(20, 20)):
            logger.info("Ash beacon already empty.")
            raise AshBeaconFinished
        if self.appear(ASH_SHOWDOWN, offset=(20, 20)):
            logger.info("Ash beacon already at ASH_SHOWDOWN.")
            raise AshBeaconFinished

        return False

    def combat(self, *args, expected_end=None, **kwargs):
        """
        执行战斗，捕获信标完成异常以正常退出。

        Args:
            expected_end: 战斗结束判断函数。
        """
        try:
            super().combat(*args, expected_end=expected_end, **kwargs)
        except AshBeaconFinished:
            pass


class OSAsh(UI, MapEventHandler):
    """大世界余烬信标模块，负责信标收集状态检测和任务调度。"""
    _ash_fully_collected = False

    def ash_collect_status(self):
        """
        通过 OCR 读取余烬信标的收集进度。

        Returns:
            int: 收集进度值，0 到 100。
        """
        if self._ash_fully_collected:
            return 0
        if self.image_color_count(ASH_COLLECT_STATUS, color=(235, 235, 235), threshold=221, count=20):
            logger.info('Ash beacon status: light')
            ocr_collect = DigitCounter(
                ASH_COLLECT_STATUS, letter=(235, 235, 235), threshold=160, name='OCR_ASH_COLLECT_STATUS')
            ocr_daily = DailyDigitCounter(
                ASH_DAILY_STATUS, letter=(235, 235, 235), threshold=160, name='OCR_ASH_DAILY_STATUS')
        elif self.image_color_count(ASH_COLLECT_STATUS, color=(140, 142, 140), threshold=221, count=20):
            logger.info('Ash beacon status: gray')
            ocr_collect = DigitCounter(
                ASH_COLLECT_STATUS, letter=(140, 142, 140), threshold=160, name='OCR_ASH_COLLECT_STATUS')
            ocr_daily = DailyDigitCounter(
                ASH_DAILY_STATUS, letter=(140, 142, 140), threshold=160, name='OCR_ASH_DAILY_STATUS')
        else:
            # 大世界每日任务领取或完成时，弹窗会遮挡信标状态
            logger.info('Ash beacon status is covered, will check next time')
            return 0

        status, _, _ = ocr_collect.ocr(self.device.image)
        daily, _, _ = ocr_daily.ocr(self.device.image)

        if daily >= 200:
            logger.info('Ash beacon fully collected today')
            self._ash_fully_collected = True
        elif status >= 200:
            logger.info('Ash beacon data reached the holding limit')
            self._ash_fully_collected = True

        if status < 0:
            status = 0
        return status

    def _support_call_ash_beacon_task(self):
        """
        检查是否可以调用信标任务。

        当信标任务的下次执行时间距今超过 30 分钟时，允许调用。

        Returns:
            bool: 是否支持调用信标任务。
        """
        # 信标任务的下次运行时间
        next_run = self.config.cross_get(keys="OpsiAshBeacon.Scheduler.NextRun", default=DEFAULT_TIME)
        # 距下次执行时间超过 30 分钟
        if next_run - datetime.now() > timedelta(minutes=30):
            return True
        return False

    def handle_ash_beacon_attack(self):
        """
        检查余烬信标收集状态，满足条件时调用信标攻击任务。

        当收集进度 >= 100 且信标任务可调度时，触发 OpsiAshBeacon 任务。

        Returns:
            bool: 是否触发了信标攻击。

        Pages:
            in: is_in_map
            out: is_in_map
        """
        if self.config.is_task_enabled('OpsiAshBeacon') \
                and self.ash_collect_status() >= 100 \
                and self._support_call_ash_beacon_task():
            self.config.task_call(task='OpsiAshBeacon')
            return True

        return False
