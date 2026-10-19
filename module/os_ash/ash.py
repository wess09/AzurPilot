"""大世界余烬信标模块。

提供碧蓝航线大世界（Operation Siren）中余烬（Ash/Ember）信标系统的自动化功能，包括：
- 信标数据收集进度的 OCR 读取与状态判断
- 每日信标收集上限的检测
- 信标战斗的特殊处理（战斗状态、战斗准备、经验信息跳过）
- 信标战斗完成的异常信号处理（AshBeaconFinished）
- 信标攻击任务的自动调度（收集进度 >= 100 时触发 OpsiAshBeacon 任务）

余烬信标系统允许玩家收集信标数据来挑战 META 级别的敌人，
战斗结束后可获得 META 角色碎片等奖励。
"""
import re
from datetime import timedelta

import cv2

from module.base.utils import image_left_strip
from module.combat.combat import BATTLE_PREPARATION, Combat
from module.config.time_source import now as current_time
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
        """对输入图像进行预处理，去除左侧干扰像素。

        Args:
            image (np.ndarray): 待处理的原始图像。

        Returns:
            np.ndarray: 裁剪预处理后的图像。
        """
        image = super().pre_process(image)
        image = image_left_strip(image, threshold=120, length=35)
        return image


class AshDigitCounter(DigitCounter):
    """核对原生信标字形数量，拒绝 OCR 凭空补出的百位数字。"""

    def pre_process(self, image):
        image = super().pre_process(image)
        # 地图上的数字与斜杠互不相连；短小的抗锯齿噪点不算完整字符。
        _, _, stats, _ = cv2.connectedComponentsWithStats((image < 120).astype('uint8'), connectivity=8)
        self._glyph_count = int((stats[1:, cv2.CC_STAT_HEIGHT] >= image.shape[0] / 2).sum())
        return image

    def after_process(self, result):
        result = super().after_process(result)
        match = re.fullmatch(r'(\d{1,3})/(100|200)', result)
        if match and int(match[1]) <= int(match[2]) and len(result) == self._glyph_count:
            return result

        # 不把多识别的一位剪掉或猜成其他读数，交给下次地图截图重读。
        logger.warning(f'[META作战] 信标读数与原生字形不符，忽略本次结果: {result!r}')
        return ''


class AshBeaconFinished(Exception):
    """信标战斗已完成的异常信号。"""
    pass


class AshCombat(Combat):
    """余烬信标战斗处理器。

    继承 Combat，覆盖部分战斗处理逻辑以适配 META 战斗的特殊行为：
    - 战斗状态页面的自定义点击处理（含掉落图像处理）
    - 经验信息的跳过（META 战斗不掉落经验）
    - 战斗准备页面的信标状态检测（完成 / 空信标 / 已在对决页面）
    - 战斗执行中捕获 AshBeaconFinished 异常以正常退出

    当信标已完成或为空时，抛出 AshBeaconFinished 异常通知上层停止战斗循环。
    """

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
        """处理经验信息界面。

        META 战斗不掉落经验，无需处理经验信息。
        BATTLE_STATUS 的随机背景可能误触发 EXP_INFO_B，直接忽略。

        Returns:
            bool: 始终返回 False。
        """
        return False

    def handle_battle_preparation(self):
        """处理战斗准备页面，点击开始战斗按钮。

        如果信标已完成或为空，则抛出 AshBeaconFinished。

        Returns:
            bool: 是否采取了行动。

        Raises:
            AshBeaconFinished: 当信标已完成、为空或已在 META 对决页面时抛出。
        """
        if super().handle_battle_preparation():
            return True

        if self.appear_then_click(ASH_START, offset=(30, 30), interval=2):
            return True
        if self.handle_get_items():
            return True
        if self.appear(BEACON_REWARD):
            logger.info("[META作战] 信标已完成")
            raise AshBeaconFinished
        if self.appear(BEACON_EMPTY, offset=(20, 20)):
            logger.info("[META作战] 信标为空")
            raise AshBeaconFinished
        if self.appear(ASH_SHOWDOWN, offset=(20, 20)):
            logger.info("[META作战] 已在 META 对决页面")
            raise AshBeaconFinished

        return False

    def combat(self, *args, expected_end=None, **kwargs):
        """执行战斗，捕获信标完成异常以正常退出。

        Args:
            *args: 传递给父类 combat 的位置参数。
            expected_end (callable, optional): 战斗结束判断函数。
            **kwargs: 传递给父类 combat 的关键字参数。
        """
        try:
            super().combat(*args, expected_end=expected_end, **kwargs)
        except AshBeaconFinished:
            pass


class OSAsh(UI, MapEventHandler):
    """大世界余烬信标模块。

    负责信标收集状态检测和信标攻击任务的自动调度。

    工作流程：
    1. 通过 OCR 读取信标收集进度，并核对原生字形数量（AshDigitCounter）
    2. 判断收集状态：可收集 / 未收集满 / 已达上限 / 被遮挡
    3. 当收集进度 >= 100 且信标任务可调度时，触发 OpsiAshBeacon 任务（只打档案时除外）
    4. 检查信标任务的下次执行时间，距今超过 30 分钟才允许调用

    Attributes:
        _ash_fully_collected (bool): 信标数据是否已收集满（达到每日上限或持有上限）。
    """
    _ash_fully_collected = False

    def ash_collect_status(self):
        """
        通过 OCR 读取余烬信标的收集进度。

        Returns:
            int: 信标记录仪当前点数；状态被遮挡或读数未通过字形校验时返回 0。
        """
        if self.image_color_count(ASH_COLLECT_STATUS, color=(235, 235, 235), threshold=30, count=20):
            logger.info('[META作战] 信标状态：可收集')
            ocr_collect = AshDigitCounter(
                ASH_COLLECT_STATUS, letter=(235, 235, 235), threshold=160, name='OCR_ASH_COLLECT_STATUS')
            ocr_daily = DailyDigitCounter(
                ASH_DAILY_STATUS, letter=(235, 235, 235), threshold=160, name='OCR_ASH_DAILY_STATUS')
        elif self.image_color_count(ASH_COLLECT_STATUS, color=(140, 142, 140), threshold=30, count=20):
            logger.info('[META作战] 信标状态：未收集满')
            ocr_collect = AshDigitCounter(
                ASH_COLLECT_STATUS, letter=(140, 142, 140), threshold=160, name='OCR_ASH_COLLECT_STATUS')
            ocr_daily = DailyDigitCounter(
                ASH_DAILY_STATUS, letter=(140, 142, 140), threshold=160, name='OCR_ASH_DAILY_STATUS')
        else:
            # 大世界每日任务领取或完成时，弹窗会遮挡信标状态
            logger.info('[META作战] 信标状态被遮挡，下次再检查')
            return 0

        status, _, _ = ocr_collect.ocr(self.device.image)
        daily, _, _ = ocr_daily.ocr(self.device.image)

        if daily >= 200:
            logger.info('[META作战] 今日信标数据已收集满')
            self._ash_fully_collected = True
        elif status >= 200:
            logger.info('[META作战] 信标数据达到持有上限')
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
        if next_run - current_time() > timedelta(minutes=30):
            return True
        return False

    def handle_ash_beacon_attack(self):
        """
        检查余烬信标收集状态，满足条件时调用信标攻击任务。

        当收集进度 >= 100 且信标任务可调度时，触发 OpsiAshBeacon 任务。

        Notes:
            AttackMode 为 `current_dossier_only`（只打档案）时不做触发。
            该模式下 `_begin_meta()` 会跳过当期信标入口，当期信标数据永远不会被消耗，
            以它为判断条件的触发一旦成立就永久成立，会每一轮都调用 OpsiAshBeacon，
            而该任务优先级高于 OpsiScheduling，会把正在进行的自动搜索反复打断。
            此时改由任务自身的调度运行（每次运行后延迟到服务器更新）。

        Returns:
            bool: 是否触发了信标攻击。

        Pages:
            in: is_in_map
            out: is_in_map
        """
        if not self.config.is_task_enabled('OpsiAshBeacon'):
            return False

        # 即使不触发也要读取一次，维持 _ash_fully_collected，
        # 侵蚀1练级要靠它决定是否忽略行动力保留
        collected = self.ash_collect_status()

        # 只打档案时不消耗当期信标数据，不能用它触发
        attack_mode = self.config.cross_get(
            keys="OpsiAshBeacon.OpsiAshBeacon.AttackMode", default='current')
        if attack_mode == 'current_dossier_only':
            return False

        if collected >= 100 and self._support_call_ash_beacon_task():
            self.config.task_call(task='OpsiAshBeacon')
            return True

        return False
