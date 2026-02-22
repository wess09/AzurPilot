from module.exception import RequestHumanTakeover
from module.logger import logger
from module.os.map import OSMap
from module.os.tasks.scheduling import CoinTaskMixin


class OpsiAbyssal(CoinTaskMixin, OSMap):
    
    def delay_abyssal(self, result=True):
        """
        Args:
            result(bool): If still have abyssal loggers.
        """
        # 无论是否有更多深渊记录器，都处理任务完成
        # 根据是否启用智能调度选择关闭或推迟任务
        self._finish_task_with_smart_scheduling('OpsiAbyssal', '深渊海域', consider_reset_remain=True)

    def clear_abyssal(self):
        """
        Get one abyssal logger in storage,
        attack abyssal boss,
        repair fleets in port.

        Raises:
            ActionPointLimit:
            TaskEnd: If no more abyssal loggers.
            RequestHumanTakeover: If unable to clear boss, fleets exhausted.
        """
        logger.hr('OS clear abyssal', level=1)
        self.cl1_ap_preserve()

        with self.config.temporary(STORY_ALLOW_SKIP=False):
            result = self.storage_get_next_item('ABYSSAL', use_logger=self.config.OpsiGeneral_UseLogger)
        if not result:
            # No abyssal loggers - handle and try other tasks if needed
            if self._handle_no_content_and_try_other_tasks('深渊海域', '深渊海域没有可执行内容'):
                return

        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0
        )
        self.zone_init()
        with self.config.temporary(_disable_task_switch=True):
            result = self.run_abyssal()
            if not result:
                raise RequestHumanTakeover

            self.handle_fleet_repair_by_config(revert=False)
            
            # 检查是否还有更多深渊记录器
            with self.config.temporary(STORY_ALLOW_SKIP=False):
                has_more = self.storage_get_next_item('ABYSSAL', use_logger=False) is not None
        self.delay_abyssal(result=has_more)

    def os_abyssal(self):
        # ===== 任务开始前黄币检查 =====
        # 如果启用了CL1且黄币充足，直接返回CL1，不执行深渊海域
        if self.is_cl1_enabled:
            return_threshold, cl1_preserve = self._get_operation_coins_return_threshold()
            if return_threshold is None:
                logger.info('OperationCoinsReturnThreshold 为 0，禁用黄币检查，仅使用行动力阈值控制')
            elif self._check_yellow_coins_and_return_to_cl1("任务开始前", "深渊海域"):
                return
        
        while True:
            self.clear_abyssal()
            # ===== 循环中黄币充足检查 =====
            # 在每次循环后检查黄币是否充足，如果充足则返回侵蚀1
            if self.is_cl1_enabled:
                if self._check_yellow_coins_and_return_to_cl1("循环中", "深渊海域"):
                    return
            self.config.check_task_switch()
