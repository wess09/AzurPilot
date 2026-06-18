from module.config.config import TaskEnd
from module.logger import logger
from module.os.fleet import BossFleet
from module.os.map import OSMap
from module.os_handler.assets import OS_SUBMARINE_EMPTY
from module.os.tasks.scheduling import CoinTaskMixin
from module.ui.page import page_os


class OpsiStronghold(CoinTaskMixin, OSMap):
    
    def clear_stronghold(self):
        """
        清理一个塞壬要塞。

        在地球仪地图上找到塞壬要塞，进入并清理，完成后在港口修理舰队。
        如果没有找到要塞，会尝试切换到其他黄币补充任务。

        Raises:
            ActionPointLimit: 行动力不足。
            TaskEnd: 没有更多要塞。
            RequestHumanTakeover: 无法击败 Boss，舰队耗尽。

        Pages:
            in: page_os, 大世界地球仪
            out: page_os, 大世界地图
        """
        logger.hr('OS clear stronghold', level=1)
        with self.config.multi_set():
            self.config.OpsiStronghold_HasStronghold = True
            self.cl1_ap_preserve()

            self.os_map_goto_globe()
            self.globe_update()
            zone = self.find_siren_stronghold()
            if zone is None:
                # 没有塞壬要塞，尝试切换到其他任务
                self.config.OpsiStronghold_HasStronghold = False
                if self._handle_no_content_and_try_other_tasks('塞壬要塞', '塞壬要塞没有可执行内容'):
                    return

        self.globe_enter(zone)
        self.zone_init()
        self.os_order_execute(recon_scan=True, submarine_call=False)
        self.run_stronghold(submarine=self.config.OpsiStronghold_SubmarineEveryCombat)

        if self.config.OpsiStronghold_SubmarineEveryCombat:
            if self.zone.is_azur_port:
                logger.info('Already in azur port')
            else:
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
        self.handle_fleet_repair_by_config(revert=False)
        self.handle_fleet_resolve(revert=False)

        # 检查是否还有更多要塞
        self.os_map_goto_globe()
        self.globe_update()
        next_zone = self.find_siren_stronghold()
        if next_zone is None:
            # 没有更多要塞，尝试切换到其他任务
            self.config.OpsiStronghold_HasStronghold = False
            if self._handle_no_content_and_try_other_tasks('塞壬要塞', '塞壬要塞没有更多可执行内容'):
                return

    def os_stronghold(self):
        # ===== 任务开始前黄币检查 =====
        # 如果启用了CL1且黄币充足，直接返回CL1，不执行塞壬要塞
        if self.is_cl1_enabled:
            return_threshold, cl1_preserve = self._get_operation_coins_return_threshold()
            if return_threshold is None:
                logger.info('OperationCoinsReturnThreshold 为 0，禁用黄币检查，仅使用行动力阈值控制')
            elif self._check_yellow_coins_and_return_to_cl1("任务开始前", "塞壬要塞"):
                return
        
        while True:
            self.clear_stronghold()
            # ===== 循环中黄币充足检查 =====
            # 在每次循环后检查黄币是否充足，如果充足则返回侵蚀1
            if self.is_cl1_enabled:
                if self._check_yellow_coins_and_return_to_cl1("循环中", "塞壬要塞"):
                    return
            self.config.check_task_switch()

    def os_sumbarine_empty(self):
        return self.match_template_color(OS_SUBMARINE_EMPTY, offset=(20, 20))

    def stronghold_interrupt_check(self):
        return self.os_sumbarine_empty() and self.no_meowfficer_searching()

    def run_stronghold_one_fleet(self, fleet, submarine=False):
        """
        使用单支舰队清理要塞。最多尝试 3 次（舰队可能卡在迷雾中）。

        Args:
            fleet (BossFleet): 舰队对象。
            submarine (bool): 是否每场战斗都呼叫潜艇。

        Returns:
            bool: 是否全部清理完毕。
        """
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0
        )
        interrupt = [self.stronghold_interrupt_check, self.is_meowfficer_searching] if submarine else None
        # 尝试 3 次，因为舰队可能卡在迷雾中
        for _ in range(3):
            # 攻击
            self.fleet_set(fleet.fleet_index)
            try:
                self.run_auto_search(question=False, rescan=False, interrupt=interrupt)
            except TaskEnd:
                self.ui_ensure(page_os)
            self.hp_reset()
            self.hp_get()

            # 判断结果
            if self.get_stronghold_percentage() == '0':
                logger.info('BOSS clear')
                return True
            elif any(self.need_repair):
                logger.info('Auto search stopped, because fleet died')
                # 重新进入以重置舰队位置
                prev = self.zone
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
                self.handle_fog_block(repair=True)
                self.globe_goto(prev, types='STRONGHOLD')
                return False
            elif submarine and self.os_sumbarine_empty():
                logger.info('Submarine ammo exhausted, wait for the next clear')
                # 潜艇弹药耗尽，等待下次清理
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
                return True
            else:
                logger.info('Auto search stopped, because fleet stuck')
                # 重新进入以重置舰队位置
                prev = self.zone
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
                self.handle_fog_block(repair=False)
                self.globe_goto(prev, types='STRONGHOLD')
                continue

    def run_stronghold(self, submarine=False):
        """
        所有舰队轮流攻击塞壬要塞。

        Args:
            submarine (bool): 是否每场战斗都呼叫潜艇。

        Returns:
            bool: 是否成功清理。

        Pages:
            in: 塞壬日志仪（深渊），Boss 已出现。
            out: 成功时为危险或安全海域，失败时仍在深渊中。
        """
        logger.hr(f'Stronghold clear', level=1)
        fleets = self.parse_fleet_filter()
        for fleet in fleets:
            logger.hr(f'Turn: {fleet}', level=2)
            if not isinstance(fleet, BossFleet):
                self.os_order_execute(recon_scan=False, submarine_call=True)
                continue

            result = self.run_stronghold_one_fleet(fleet, submarine=submarine)
            if result:
                return True
            else:
                continue

        logger.critical('无法击败boss，舰队已耗尽')
        return False
