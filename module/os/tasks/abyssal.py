"""大世界深渊海域任务模块。

执行大世界深渊海域（Abyssal）的清理挑战，包括：
- 深渊坐标的获取和进入
- 潜艇配置检测和自动编队
- 多层深渊的逐层清理
- 行动力保护和代币资源管理

继承自 CoinTaskMixin 和 OSMap，提供代币保护和地图导航能力，
深渊海域是大世界中高难度的战斗内容，奖励丰厚。
"""

from datetime import timedelta

from module.exception import RequestHumanTakeover
from module.config.time_source import now as current_time
from module.logger import logger
from module.os.map import OSMap
from module.os.tasks.scheduling import CoinTaskMixin


class OpsiAbyssal(CoinTaskMixin, OSMap):
    @staticmethod
    def _has_call_submarine(task_name, config):
        filter_str = config.cross_get(
            f"{task_name}.OpsiFleetFilter.Filter", default=""
        )
        return "callsubmarine" in str(filter_str).lower()

    def _is_submarine_task(self, task_name):
        """
        检查指定任务是否使用潜艇。

        Args:
            task_name (str): 任务名称。

        Returns:
            bool: 如果任务使用潜艇则返回 True。
        """
        submarine_enabled = self.config.cross_get(
            f"{task_name}.OpsiFleet.Submarine", default=False
        )
        if submarine_enabled:
            return True

        filter_str = self.config.cross_get(
            f"{task_name}.OpsiFleetFilter.Filter", default=""
        )
        if filter_str and "submarine" in filter_str.lower():
            return True

        return False

    def _check_submarine_cooldown(self):
        """
        检查潜艇是否处于冷却状态。

        遍历所有已启用的潜艇相关任务，检查是否存在即将到期的冷却。

        Returns:
            tuple: (是否冷却中, 冷却结束时间)
        """
        now = current_time()
        submarine_tasks = [
            'OpsiExplore', 'OpsiDaily', 'OpsiObscure', 'OpsiAbyssal',
            'OpsiArchive', 'OpsiStronghold', 'OpsiMeowfficerFarming', 'OpsiMonthBoss'
        ]

        for task_name in submarine_tasks:
            enabled = self.config.cross_get(
                f"{task_name}.Scheduler.Enable", default=False
            )
            if not enabled:
                continue
            if not self._is_submarine_task(task_name):
                continue
            next_run = self.config.cross_get(
                f"{task_name}.Scheduler.NextRun", default=None
            )
            if next_run and next_run > now:
                time_diff = next_run - now
                if timedelta(0) < time_diff <= timedelta(minutes=60):
                    logger.info(f'[大世界-深渊坐标] 检测到潜艇冷却：任务 {task_name} 的下次运行时间为 {next_run}')
                    return True, next_run

        logger.info('[大世界-深渊坐标] 潜艇冷却检查通过，未检测到潜艇冷却')
        return False, None

    def _delay_until_submarine_cooldown_end(self, cooldown_end_time):
        """
        延迟深渊坐标任务直到潜艇冷却结束。

        Args:
            cooldown_end_time: 潜艇冷却结束的时间。
        """
        if self.is_running_smart_scheduling_task():
            logger.info(f'[大世界-深渊坐标] 智能调度+代理执行中，深渊坐标潜艇冷却至 {cooldown_end_time}，本轮跳过深渊')
            self._smart_scheduling_no_content_task = 'OpsiAbyssal'
            return

        logger.hr('检测到潜艇冷却', level=1)
        logger.info(f'[大世界-深渊坐标] 潜艇冷却结束时间：{cooldown_end_time}')
        logger.info('[大世界-深渊坐标] 延时深渊坐标任务到潜艇冷却结束')

        now = current_time()
        delay_seconds = int((cooldown_end_time - now).total_seconds())
        delay_minutes = delay_seconds // 60
        if delay_minutes <= 0:
            delay_minutes = 1

        logger.info(f'[大世界-深渊坐标] 延时 {delay_minutes} 分钟到潜艇冷却结束')
        self.config.task_delay(minute=delay_minutes)
        self.config.task_stop()

    def delay_abyssal(self, result=True, submarine_enabled=True):
        """
        延迟深渊坐标任务执行。

        Args:
            result (bool): 是否还有深渊日志仪。
            submarine_enabled (bool): 舰队过滤器是否包含呼叫潜艇。
        """
        if not submarine_enabled:
            logger.info('[大世界-深渊坐标] 本轮深渊过滤器不包含 CallSubmarine，不延迟')
            return

        if self.is_running_smart_scheduling_task():
            logger.info('[大世界-深渊坐标] 智能调度+代理执行中，跳过深渊坐标任务延迟')
            return

        logger.info('[大世界-深渊坐标] 本轮深渊过滤器包含 CallSubmarine，当前任务延迟 60 分钟后再运行')
        self.config.task_delay(minute=60)
        self.config.task_stop()

    def clear_abyssal(self):
        """
        清理一个深渊坐标。

        从仓库取出深渊日志仪，攻击深渊 Boss，完成后在港口修理舰队。
        如果检测到潜艇冷却，会延迟任务执行。

        Returns:
            bool: 舰队过滤器是否包含呼叫潜艇。

        Raises:
            ActionPointLimit: 行动力不足。
            TaskEnd: 没有更多深渊日志仪。
            RequestHumanTakeover: 无法击败 Boss，舰队耗尽。
        """
        logger.hr('大世界-深渊坐标', level=1)
        self.cl1_ap_preserve()

        submarine_enabled = self._has_call_submarine('OpsiAbyssal', self.config)
        if submarine_enabled:
            is_cooldown, cooldown_end_time = self._check_submarine_cooldown()
            if is_cooldown:
                self._delay_until_submarine_cooldown_end(cooldown_end_time)
                return False

        with self.config.temporary(STORY_ALLOW_SKIP=False):
            result = self.storage_get_next_item('ABYSSAL', use_logger=self.config.OpsiGeneral_UseLogger)
        if not result:
            if self._handle_coin_task_no_content('深渊坐标', '深渊坐标没有可执行内容'):
                return False

        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
        )
        self.zone_init()

        logger.info('[大世界-深渊坐标] 进入深渊坐标地图，禁止所有任务切换')
        with self.config.temporary(_disable_task_switch=True):
            result = self.run_abyssal()
            if not result:
                raise RequestHumanTakeover

            self.handle_fleet_repair_by_config(revert=False)

        return submarine_enabled

    def os_abyssal(self):
        while True:
            submarine_enabled = self.clear_abyssal()

            if not self.config.OpsiAbyssal_ForceRun and submarine_enabled:
                self.delay_abyssal(result=True, submarine_enabled=True)

            self.config.check_task_switch()
