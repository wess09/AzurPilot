import datetime
from module.config.utils import get_server_last_update
from module.exercise.assets import *
from module.exercise.combat import ExerciseCombat
from module.logger import logger
from module.ocr.ocr import Digit, Ocr, OcrYuv
from module.ui.page import page_exercise
from module.config.utils import get_server_next_update

class DatedDuration(Ocr):
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
            logger.warning(f'Invalid dated duration: {string}')
            return datetime.timedelta(days=0, hours=0, minutes=0, seconds=0)


class DatedDurationYuv(DatedDuration, OcrYuv):
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
    opponent_change_count = 0
    remain = 0
    preserve = 0

    def _new_opponent(self):
        logger.info('New opponent')
        self.appear_then_click(NEW_OPPONENT)
        self.opponent_change_count += 1

        logger.attr("Change_opponent_count", self.opponent_change_count)
        self.config.set_record(Exercise_OpponentRefreshValue=self.opponent_change_count)

        self.ensure_no_info_bar(timeout=3)

    def _opponent_fleet_check_all(self):
        if self.config.Exercise_OpponentChooseMode != 'leftmost':
            super()._opponent_fleet_check_all()

    def _opponent_sort(self, method=None):
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
                logger.hr(f'Opponent {opponent}', level=2)
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
            logger.hr(f'Opponent {opponents[0]}', level=2)
            self.config.override(Exercise_LowHpThreshold=threshold)
            success = self._combat(opponents[0])
            if success:
                self.config.override(Exercise_LowHpThreshold=restore)
                return success
            else:
                if self.opponent_change_count < 5:
                    logger.info("Cannot beat calculated easiest opponent, refresh")
                    self._new_opponent()
                    self._opponent_fleet_check_all()
                    continue
                else:
                    logger.info("Cannot beat calculated easiest opponent, MAX EXP then")
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
        获取演习策略。

        Returns:
            int: 保留次数，即剩余演习次数阈值。
            list, int: 将军试炼时间区间。
        """
        if self.config.Exercise_ExerciseStrategy == "aggressive":
            preserve = 0
            admiral_interval = None
        else:
            preserve = 5
            admiral_interval = ADMIRAL_TRIAL_HOUR_INTERVAL[self.config.Exercise_ExerciseStrategy]

        return preserve, admiral_interval

    def run(self):
        self.ui_ensure(page_exercise)
        server_update = self.config.Scheduler_ServerUpdate

        self.opponent_change_count = self._get_opponent_change_count()
        logger.attr("Change_opponent_count", self.opponent_change_count)
        logger.attr('Exercise_ExerciseStrategy', self.config.Exercise_ExerciseStrategy)
        self.preserve, admiral_interval = self._get_exercise_strategy()

        remain_time = OCR_PERIOD_REMAIN.ocr(self.device.image)
        logger.info(f'Exercise period remain: {remain_time}')

        if admiral_interval is not None and remain_time:
            admiral_start, admiral_end = admiral_interval

            if admiral_start > int(remain_time.total_seconds() // 3600) >= admiral_end:  # 达到将军试炼设定时间
                logger.info('Reach set time for admiral trial, using all attempts.')
                self.preserve = 0
                forced_run =True
            elif int(remain_time.total_seconds() // 3600) < 6:  # 未设置为 "sun18" 时，仍在周日 18 点前消耗
                logger.info('Exercise period remain less than 6 hours, using all attempts.')
                self.preserve = 0
                forced_run = True
            else:
                logger.info(f'Preserve {self.preserve} exercise')
                forced_run = False
        else:
            forced_run = False

        # 延迟到设定时间执行任务
        if ((get_server_next_update(server_update) - datetime.datetime.now()).seconds >
            3600 * self.config.Exercise_DelayUntilHoursBeforeNextUpdate)\
                and not forced_run:
            logger.warning(f'Exercise should run at {self.config.Exercise_DelayUntilHoursBeforeNextUpdate} '
                           f'hours before next update. Delay task to it.')
            run = False
        else:
            run = True

        while run:
            self.remain = OCR_EXERCISE_REMAIN.ocr(self.device.image)
            if self.remain <= self.preserve:
                break

            logger.hr(f'Exercise remain {self.remain}', level=1)
            if self.config.Exercise_OpponentChooseMode == "easiest_else_exp":
                success = self._exercise_easiest_else_exp()
            else:
                success = self._exercise_once()
            if not success:
                logger.info('New opponent exhausted')
                break

        # self.equipment_take_off_when_finished()

        # 调度器
        with self.config.multi_set():
            self.config.set_record(Exercise_OpponentRefreshValue=self.opponent_change_count)
            if self.remain <= self.preserve or self.opponent_change_count >= 5:
                next_run = get_server_next_update(server_update) \
                           - datetime.timedelta(hours=self.config.Exercise_DelayUntilHoursBeforeNextUpdate)
                now = datetime.datetime.now()
                if next_run < now or run:
                    self.config.task_delay(server_update=True)
                    return
                minutes_to_delay = int((next_run - now).total_seconds() / 60 + 1)
                self.config.task_delay(minute=minutes_to_delay)
            else:
                self.config.task_delay(success=False)
