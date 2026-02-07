from module.logger import logger
from module.os.map import OSMap
from module.os.tasks.scheduling import CoinTaskMixin


class OpsiObscure(CoinTaskMixin, OSMap):
    
    def clear_obscure(self):
        """
        Raises:
            ActionPointLimit:
        """
        logger.hr('OS clear obscure', level=1)
        self.cl1_ap_preserve()
        if self.config.OpsiObscure_ForceRun:
            logger.info('OS obscure finish is under force run')

        result = self.storage_get_next_item('OBSCURE', use_logger=self.config.OpsiGeneral_UseLogger,
                                            skip_obscure_hazard_2=self.config.OpsiObscure_SkipHazard2Obscure)
        if not result:
            # No obscure coordinates - handle and try other tasks if needed
            if self._handle_no_content_and_try_other_tasks('隐秘海域', '隐秘海域没有可执行内容'):
                return

        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
        )
        self.zone_init()
        self.fleet_set(self.config.OpsiFleet_Fleet)
        with self.config.temporary(_disable_task_switch=True):
            self.os_order_execute(
                recon_scan=True,
                submarine_call=self.config.OpsiFleet_Submarine)
            self.run_auto_search(rescan='current')

            self.map_exit()
            self.handle_after_auto_search()

    def os_obscure(self):
        # ===== 任务开始前黄币检查 =====
        # 如果启用了CL1且黄币充足，直接返回CL1，不执行隐秘海域
        if self.is_cl1_enabled:
            return_threshold, cl1_preserve = self._get_operation_coins_return_threshold()
            if return_threshold is None:
                logger.info('OperationCoinsReturnThreshold 为 0，禁用黄币检查，仅使用行动力阈值控制')
            elif self._check_yellow_coins_and_return_to_cl1("任务开始前", "隐秘海域"):
                return
        
        while True:
            self.clear_obscure()
            # ===== 循环中黄币充足检查 =====
            # 在每次循环后检查黄币是否充足，如果充足则返回侵蚀1
            if self.is_cl1_enabled:
                if self._check_yellow_coins_and_return_to_cl1("循环中", "隐秘海域"):
                    return
            
            # 如果 ForceRun=False，根据是否启用智能调度选择关闭或推迟任务
            if not self.config.OpsiObscure_ForceRun:
                if self._finish_task_with_smart_scheduling('OpsiObscure', '隐秘海域', consider_reset_remain=True):
                    break
            
            self.config.check_task_switch()
            continue
