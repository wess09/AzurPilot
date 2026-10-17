"""紧急委托 / 三油低耗的「每 N 小时最多 M 次」周期限制。

这个模块只维护周期状态，不直接操作游戏界面：
- 从首次启用开始记录周期起点和本周期剩余次数；
- 达到 N 小时或跨过 N 小时边界后，自动开启下一周期；
- 本周期次数用完后，调用方负责把任务延迟到周期结束；
- 已消耗次数、周期起点和生效配置写入隐藏配置项，进程重启后可继续。
"""

from datetime import datetime, timedelta

from module.config.time_source import now as current_time
from module.logger import logger


_DEFAULT_START = datetime(2020, 1, 1, 0, 0, 0)


class FarmCycleLimit:
    """维护紧急委托 / 三油低耗的周期次数限制。

    Args:
        config: 已绑定当前任务的配置对象。
        now_func: 测试用当前时间函数，默认使用项目时间源。
    """

    def __init__(self, config, now_func=None):
        self.config = config
        self._now = now_func or current_time
        self.enabled = False
        self.remaining = 0
        self.start = None
        self.hours = 0
        self.runs = 0

    @staticmethod
    def _to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_datetime(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @property
    def cycle_end(self):
        """当前周期结束时间；未启用时返回 None。"""
        if not self.enabled or self.start is None:
            return None
        return self.start + timedelta(hours=self.hours)

    @property
    def is_blocked(self):
        """本周期是否已经用完出击次数。"""
        return self.enabled and self.remaining <= 0

    def _invalidate(self):
        """关闭功能时清理运行状态，重新启用时从新周期开始。"""
        start = self._to_datetime(self.config.FarmCycle_CycleStart)
        remain = self._to_int(self.config.FarmCycle_CycleRemain)
        applied_hours = self._to_int(self.config.FarmCycle_CycleHoursApplied)
        applied_runs = self._to_int(self.config.FarmCycle_CycleRunsApplied)
        if start not in (None, _DEFAULT_START) or remain or applied_hours or applied_runs:
            with self.config.multi_set():
                self.config.FarmCycle_CycleStart = _DEFAULT_START
                self.config.FarmCycle_CycleRemain = 0
                self.config.FarmCycle_CycleHoursApplied = 0
                self.config.FarmCycle_CycleRunsApplied = 0

    def _start_cycle(self, now, hours, runs, reason):
        end = now + timedelta(hours=hours)
        logger.hr('周期出击限制', level=2)
        logger.info(
            f'[周期限制] {reason}，新周期 {now.strftime("%Y-%m-%d %H:%M:%S")}'
            f' 至 {end.strftime("%Y-%m-%d %H:%M:%S")}，最多出击 {runs} 次'
        )
        with self.config.multi_set():
            self.config.FarmCycle_CycleStart = now.replace(microsecond=0)
            self.config.FarmCycle_CycleRemain = runs
            self.config.FarmCycle_CycleHoursApplied = hours
            self.config.FarmCycle_CycleRunsApplied = runs

    def refresh(self):
        """读取配置并校正当前周期。

        Returns:
            bool: 周期限制是否启用。
        """
        hours = self._to_int(self.config.FarmCycle_CycleHours)
        runs = self._to_int(self.config.FarmCycle_CycleRuns)

        if hours <= 0 or runs <= 0:
            self.enabled = False
            self.remaining = 0
            self.start = None
            self.hours = 0
            self.runs = 0
            self._invalidate()
            return False

        now = self._now()
        start = self._to_datetime(self.config.FarmCycle_CycleStart)
        remain = self._to_int(self.config.FarmCycle_CycleRemain)
        applied_hours = self._to_int(self.config.FarmCycle_CycleHoursApplied)
        applied_runs = self._to_int(self.config.FarmCycle_CycleRunsApplied)

        reason = None
        initial = start in (None, _DEFAULT_START) and not applied_hours and not applied_runs
        if initial:
            reason = '初始化周期'
        elif start is None or start > now:
            reason = '周期起点无效'
        elif applied_hours != hours or applied_runs != runs:
            reason = '周期配置已变更'
        elif now >= start + timedelta(hours=hours):
            reason = '上一周期已结束'
        elif remain < 0 or remain > runs:
            reason = '周期剩余次数异常'

        if reason is not None:
            self._start_cycle(now, hours, runs, reason)
            self.start = now.replace(microsecond=0)
            self.remaining = runs
            self.hours = hours
            self.runs = runs
            self.enabled = True
            return True

        self.start = start
        self.remaining = remain
        self.hours = hours
        self.runs = runs
        self.enabled = True
        return True

    def consume(self):
        """一次战役流程正常返回后扣减本周期剩余次数。"""
        if not self.enabled or self.remaining <= 0:
            return

        remaining = max(self.remaining - 1, 0)
        with self.config.multi_set():
            self.config.FarmCycle_CycleRemain = remaining
        self.remaining = remaining

        if remaining:
            logger.info(f'[周期限制] 本周期剩余出击次数: {remaining} / {self.runs}')
        else:
            logger.hr('触发停止条件: 周期出击次数', level=1)
            logger.info(f'[周期限制] 本周期已出击 {self.runs} 次，等待周期结束')

    def defer(self):
        """把任务延迟到本周期结束，下一次运行自动开启新周期。"""
        end = self.cycle_end
        if not self.enabled or end is None:
            return
        logger.info(
            f'[周期限制] 本周期次数已用完，延迟任务到 {end.strftime("%Y-%m-%d %H:%M:%S")}'
        )
        self.config.task_delay(target=end)
