"""
演习（PvP）任务模块。

自动执行演习系统的日常操作，包括：
- 通过 OCR 识别剩余演习次数和赛季重置倒计时
- 支持多种对手选择策略：按经验优先、按难度优先、最左优先等
- 支持将军试炼时间区间配置，在特定时段集中消耗次数
- 管理对手刷新次数，跨天自动重置
- 支持延迟执行，在赛季结束前指定时间开始消耗

对手选择策略：
- max_exp: 选择经验最高的对手
- easiest: 选择最容易击败的对手
- easiest_else_exp: 优先选最简单的，无法击败时切换到最大经验
- leftmost: 优先选择最左侧的对手
"""
import datetime
from module.config.time_source import now as current_time
from module.config.utils import get_server_last_update
from module.exercise.assets import *
from module.exercise.combat import ExerciseCombat
from module.logger import logger
from module.ocr.ocr import Digit, Ocr, OcrYuv
from module.ui.assets import EXERCISE_CHECK
from module.ui.page import page_exercise
from module.config.utils import get_server_next_update

class DatedDuration(Ocr):
    """
    带日期的时长 OCR 识别器。

    用于识别演习赛季剩余时间格式，如 `10d 01:30:30` 或 `7日01:30:30`。
    对 OCR 常见错误进行修正（I->1, D->0, S->5）。

    Attributes:
        buttons: OCR 识别区域。
        lang (str): OCR 语言，默认 'cnocr'。
        alphabet (str): 可识别字符集。
    """

    def __init__(self, buttons, lang='cnocr', letter=(255, 255, 255), threshold=128, alphabet='0123456789:IDS天日d',
                 name=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        return result

    def ocr(self, image, direct_ocr=False):
        """
        对带日期的时长进行 OCR 识别，如 `10d 01:30:30` 或 `7日01:30:30`。

        Args:
            image: 截图图像。
            direct_ocr: 是否直接进行 OCR。

        Returns:
            datetime.timedelta 或其列表：时间差对象。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if not isinstance(result_list, list):
            result_list = [result_list]
        result_list = [self.parse_time(result) for result in result_list]
        if len(self.buttons) == 1:
            result_list = result_list[0]
        return result_list

    @staticmethod
    def parse_time(string):
        """
        解析带日期的时长字符串。

        Args:
            string (str): 时长字符串，如 `10d 01:30:30` 或 `7日01:30:30`。

        Returns:
            datetime.timedelta: 解析后的时间差对象。
        """
        import re
        result = re.search(r'(\d{1,2})\D?(\d{1,2}):?(\d{2}):?(\d{2})', string)
        if result:
            result = [int(s) for s in result.groups()]
            return datetime.timedelta(days=result[0], hours=result[1], minutes=result[2], seconds=result[3])
        else:
            logger.warning(f'[演习-OCR] 无效的带日期时长: {string}')
            return datetime.timedelta(days=0, hours=0, minutes=0, seconds=0)


class DatedDurationYuv(DatedDuration, OcrYuv):
    """
    YUV 色彩空间的带日期时长 OCR 识别器。

    继承自 DatedDuration 和 OcrYuv，使用 YUV 色彩空间进行预处理。
    """
    pass


OCR_EXERCISE_REMAIN = Digit(OCR_EXERCISE_REMAIN, letter=(173, 247, 74), threshold=128)
OCR_PERIOD_REMAIN = DatedDuration(OCR_PERIOD_REMAIN, letter=(255, 255, 255), threshold=128)
ADMIRAL_TRIAL_HOUR_INTERVAL = {
    # "aggressive": [336, 0]  # 激进模式
    "sun18": [6, 0],
    "sun12": [12, 6],
    "sun0": [24, 12],
    "sat18": [30, 24],
    "sat12": [36, 30],
    "sat0": [48, 36],
    "fri18": [56, 48]
}


class Exercise(ExerciseCombat):
    """
    演习任务主处理器，负责演习的调度和执行。

    继承自 ExerciseCombat，整合了对手选择、战斗执行、次数管理等功能。
    根据配置的策略自动选择对手并执行战斗，支持多种消耗策略和延迟执行。

    Attributes:
        opponent_change_count (int): 当前对手刷新次数，每天最多刷新 5 次。
        remain (int): 剩余演习次数。
        preserve (int): 保留次数，剩余演习次数低于此值时停止。
    """

    opponent_change_count = 0
    remain = 0
    preserve = 0

    def _new_opponent(self):
        """
        刷新对手列表。

        点击刷新按钮获取新的对手，并记录当天的刷新次数。
        """
        logger.info('[演习-对手] 刷新对手')
        self.appear_then_click(NEW_OPPONENT)
        self.opponent_change_count += 1

        logger.attr('对手刷新次数', self.opponent_change_count)
        self.config.set_record(Exercise_OpponentRefreshValue=self.opponent_change_count)

        self.ensure_no_info_bar(timeout=3)

    def _opponent_fleet_check_all(self):
        """
        检查所有对手的舰队信息。

        当选择模式为 leftmost 时跳过检查，直接使用最左侧对手。
        """
        if self.config.Exercise_OpponentChooseMode != 'leftmost':
            super()._opponent_fleet_check_all()

    def _opponent_sort(self, method=None):
        """
        根据策略对对手进行排序。

        Args:
            method (str): 排序方法，默认使用配置中的 Exercise_OpponentChooseMode。
                leftmost 模式直接返回 [0, 1, 2, 3]。

        Returns:
            list[int]: 对手索引列表，按优先级排序。
        """
        if method is None:
            method = self.config.Exercise_OpponentChooseMode
        if method != 'leftmost':
            return super()._opponent_sort(method=method)
        else:
            return [0, 1, 2, 3]

    def _exercise_once(self):
        """
        执行一次演习。

        处理对手刷新和演习失败的情况。

        Returns:
            bool: 击败一个对手返回 True，所有对手均未击败且刷新次数耗尽返回 False。
        """
        self._opponent_fleet_check_all()
        while 1:
            for opponent in self._opponent_sort():
                logger.hr(f'对手 {opponent}', level=2)
                success = self._combat(opponent)
                if success:
                    return success

            if self.opponent_change_count >= 5:
                return False

            self._new_opponent()
            self._opponent_fleet_check_all()

    def _exercise_easiest_else_exp(self):
        """
        优先选择最简单的对手，若无法击败则切换到最大经验对手并接受失败。

        处理对手刷新和演习失败的情况。

        Returns:
            bool: 击败一个对手返回 True，所有对手均未击败且刷新次数耗尽返回 False。
        """
        method = "easiest_else_exp"
        restore = self.config.Exercise_LowHpThreshold
        threshold = self.config.Exercise_LowHpThreshold
        self._opponent_fleet_check_all()
        while 1:
            opponents = self._opponent_sort(method=method)
            logger.hr(f'对手 {opponents[0]}', level=2)
            self.config.override(Exercise_LowHpThreshold=threshold)
            success = self._combat(opponents[0])
            if success:
                self.config.override(Exercise_LowHpThreshold=restore)
                return success
            else:
                if self.opponent_change_count < 5:
                    logger.info("[演习-对手] 无法击败最简单对手，刷新")
                    self._new_opponent()
                    self._opponent_fleet_check_all()
                    continue
                else:
                    logger.info("[演习-对手] 无法击败最简单对手，切换最大经验")
                    method = "max_exp"
                    threshold = 0

    def _get_opponent_change_count(self):
        """
        获取对手刷新次数。

        同一天内，计数设为上次记录的刷新次数或 6（即不再刷新）。
        新的一天，计数重置为 0（即最多可刷新 5 次）。

        Returns:
            int: 当前对手刷新次数。
        """
        record = self.config.Exercise_OpponentRefreshRecord
        update = get_server_last_update('00:00')
        if record.date() == update.date():
            # 同一天
            return self.config.Exercise_OpponentRefreshValue
        else:
            # 新的一天
            self.config.set_record(Exercise_OpponentRefreshValue=0)
            return 0

    def _get_exercise_reset_remain(self):
        """
        获取演习重置剩余时间。

        Returns:
            datetime.timedelta: 重置剩余时间。
        """
        result = OCR_PERIOD_REMAIN.ocr(self.device.image)
        return result

    def _get_exercise_strategy(self):
        """
        获取演习消耗策略。

        根据配置的 Exercise_ExerciseStrategy 确定保留次数和将军试炼时间区间。

        Returns:
            tuple: (preserve, admiral_interval)
                - preserve (int): 保留次数，激进模式为 0，保守模式为 5。
                - admiral_interval (list 或 None): 将军试炼时间区间 [start, end]（小时），
                  激进模式为 None。
        """
        if self.config.Exercise_ExerciseStrategy == "aggressive":
            preserve = 0
            admiral_interval = None
        else:
            preserve = 5
            admiral_interval = ADMIRAL_TRIAL_HOUR_INTERVAL[self.config.Exercise_ExerciseStrategy]

        return preserve, admiral_interval

    def run(self):
        """
        演习任务主入口。

        流程：
        1. 导航到演习页面
        2. 获取对手刷新次数和消耗策略
        3. 检查是否达到将军试炼时间区间，决定是否强制消耗
        4. 检查是否需要延迟执行
        5. 循环执行演习直到次数用尽或达到保留阈值
        6. 设置下次任务调度时间

        Pages:
            in: 任意页面
            out: page_exercise
        """
        self.ui_ensure(page_exercise)
        server_update = self.config.Scheduler_ServerUpdate

        self.opponent_change_count = self._get_opponent_change_count()
        logger.attr('对手刷新次数', self.opponent_change_count)
        logger.attr('演习消耗策略', self.config.Exercise_ExerciseStrategy)
        self.preserve, admiral_interval = self._get_exercise_strategy()

        remain_time = OCR_PERIOD_REMAIN.ocr(self.device.image)
        logger.info(f'[演习-调度] 演习赛季剩余时间: {remain_time}')

        if admiral_interval is not None and remain_time:
            admiral_start, admiral_end = admiral_interval

            if admiral_start > int(remain_time.total_seconds() // 3600) >= admiral_end:  # 达到将军试炼设定时间
                logger.info('[演习-调度] 达到冲击元帅的设定时间，消耗所有次数')
                self.preserve = 0
                forced_run = True
            elif int(remain_time.total_seconds() // 3600) < 6:  # 未设置为 "sun18" 时，仍在周日 18 点前消耗
                logger.info('[演习-调度] 演习赛季剩余不足6小时，消耗所有次数')
                self.preserve = 0
                forced_run = True
            else:
                logger.info(f'[演习-调度] 保留 {self.preserve} 次演习')
                forced_run = False
        else:
            forced_run = False

        # 延迟到设定时间执行任务
        if ((get_server_next_update(server_update) - current_time()).seconds >
            3600 * self.config.Exercise_DelayUntilHoursBeforeNextUpdate)\
                and not forced_run:
            logger.warning(f'[演习-调度] 应在下次更新前 {self.config.Exercise_DelayUntilHoursBeforeNextUpdate} '
                           f'小时执行，延迟任务')
            run = False
        else:
            run = True

        while run:
            self.remain = OCR_EXERCISE_REMAIN.ocr(self.device.image)
            if self.remain <= self.preserve:
                break

            logger.hr(f'演习剩余 {self.remain}', level=1)
            if self.config.Exercise_OpponentChooseMode == "easiest_else_exp":
                success = self._exercise_easiest_else_exp()
            else:
                success = self._exercise_once()
            if not success:
                logger.info('[演习-对手] 对手刷新次数耗尽')
                break

        if self.equipment_config_enabled and self.equipment_handle_before_flag:
            self._choose_opponent(0)
            self.equipment_handle_after()
            self.ui_back(EXERCISE_CHECK)

        # 调度器
        with self.config.multi_set():
            self.config.set_record(Exercise_OpponentRefreshValue=self.opponent_change_count)
            if self.remain <= self.preserve or self.opponent_change_count >= 5:
                next_run = get_server_next_update(server_update) \
                           - datetime.timedelta(hours=self.config.Exercise_DelayUntilHoursBeforeNextUpdate)
                now = current_time()
                if next_run < now or run:
                    self.config.task_delay(server_update=True)
                    return
                minutes_to_delay = int((next_run - now).total_seconds() / 60 + 1)
                self.config.task_delay(minute=minutes_to_delay)
            else:
                self.config.task_delay(success=False)
