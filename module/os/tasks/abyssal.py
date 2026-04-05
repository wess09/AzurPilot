from datetime import datetime, timedelta

from module.exception import RequestHumanTakeover
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
        Check if a task uses submarine.

        Args:
            task_name (str): Task name to check.

        Returns:
            bool: True if task uses submarine.
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
        Check if submarine is on cooldown.

        Returns:
            tuple: (is_cooldown, cooldown_end_time)
        """
        now = datetime.now()
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
                    logger.info(f'检测到潜艇冷却：任务 {task_name} 的下次运行时间为 {next_run}')
                    return True, next_run

        logger.info('潜艇冷却检查通过，未检测到潜艇冷却')
        return False, None

    def _delay_until_submarine_cooldown_end(self, cooldown_end_time):
        """
        Delay abyssal task until submarine cooldown ends.

        Args:
            cooldown_end_time: datetime when submarine cooldown ends
        """
        logger.hr('Submarine cooldown detected', level=1)
        logger.info(f'潜艇冷却结束时间：{cooldown_end_time}')
        logger.info('延时深渊任务到潜艇冷却结束')

        now = datetime.now()
        delay_seconds = int((cooldown_end_time - now).total_seconds())
        delay_minutes = delay_seconds // 60
        if delay_minutes <= 0:
            delay_minutes = 1

        logger.info(f'延时 {delay_minutes} 分钟到潜艇冷却结束')
        self.config.task_delay(minute=delay_minutes)
        self.config.task_stop()

    def delay_abyssal(self, result=True, submarine_enabled=True):
        """
        Args:
            result(bool): If still have abyssal loggers.
            submarine_enabled(bool): If fleet filter contains CallSubmarine.
        """
        if not submarine_enabled:
            logger.info('本轮深渊过滤器不包含 CallSubmarine，不延迟')
            return

        logger.info('本轮深渊过滤器包含 CallSubmarine，当前任务延迟 60 分钟后再运行')
        self.config.task_delay(minute=60)
        self.config.task_stop()

    def clear_abyssal(self):
        """
        Get one abyssal logger in storage,
        attack abyssal boss,
        repair fleets in port.

        Returns:
            bool: If fleet filter contains CallSubmarine.

        Raises:
            ActionPointLimit:
            TaskEnd: If no more abyssal loggers.
            RequestHumanTakeover: If unable to clear boss, fleets exhausted.
        """
        logger.hr('OS clear abyssal', level=1)
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
            if self._handle_no_content_and_try_other_tasks('深渊海域', '深渊海域没有可执行内容'):
                return False

        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
        )
        self.zone_init()

        logger.info('进入深渊地图，禁止所有任务切换')
        with self.config.temporary(_disable_task_switch=True):
            result = self.run_abyssal()
            if not result:
                raise RequestHumanTakeover

            self.handle_fleet_repair_by_config(revert=False)

        return submarine_enabled

    def os_abyssal(self):
        if self.is_cl1_enabled:
            return_threshold, cl1_preserve = self._get_operation_coins_return_threshold()
            if return_threshold is None:
                logger.info('OperationCoinsReturnThreshold 为 0，禁用黄币检查，仅使用行动力阈值控制')
            elif self._check_yellow_coins_and_return_to_cl1('任务开始前', '深渊海域'):
                return

        while True:
            submarine_enabled = self.clear_abyssal()

            if self.is_cl1_enabled:
                if self._check_yellow_coins_and_return_to_cl1('循环中', '深渊海域'):
                    return

            if not self.config.OpsiAbyssal_ForceRun and submarine_enabled:
                self.delay_abyssal(result=True, submarine_enabled=True)

            self.config.check_task_switch()
