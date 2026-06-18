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
        延迟深渊任务直到潜艇冷却结束。

        Args:
            cooldown_end_time: 潜艇冷却结束的时间。
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
        延迟深渊任务执行。

        Args:
            result (bool): 是否还有深渊日志仪。
            submarine_enabled (bool): 舰队过滤器是否包含呼叫潜艇。
        """
        if not submarine_enabled:
            logger.info('本轮深渊过滤器不包含 CallSubmarine，不延迟')
            return

        logger.info('本轮深渊过滤器包含 CallSubmarine，当前任务延迟 60 分钟后再运行')
        self.config.task_delay(minute=60)
        self.config.task_stop()

    def clear_abyssal(self):
        """
        清理一个深渊海域。

        从仓库取出深渊日志仪，攻击深渊 Boss，完成后在港口修理舰队。
        如果检测到潜艇冷却，会延迟任务执行。

        Returns:
            bool: 舰队过滤器是否包含呼叫潜艇。

        Raises:
            ActionPointLimit: 行动力不足。
            TaskEnd: 没有更多深渊日志仪。
            RequestHumanTakeover: 无法击败 Boss，舰队耗尽。
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
