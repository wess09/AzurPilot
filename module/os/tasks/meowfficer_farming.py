from module.config.config import TaskEnd
from module.config.utils import get_os_reset_remain
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap
from module.os_handler.action_point import ActionPointLimit
from module.os.tasks.scheduling import CoinTaskMixin
from module.os.tasks.smart_scheduling_utils import is_smart_scheduling_enabled


class OpsiMeowfficerFarming(CoinTaskMixin, OSMap):
    
    def os_meowfficer_farming(self):
        """
        Recommend 3 or 5 for higher meowfficer searching point per action points ratio.
        """
        logger.hr(f'OS meowfficer farming, hazard_level={self.config.OpsiMeowfficerFarming_HazardLevel}', level=1)
        
        # ===== 任务开始前黄币检查 =====
        # 如果启用了CL1且黄币充足，直接返回CL1，不执行短猫
        # 如果 OperationCoinsReturnThreshold 为 0，则禁用黄币检查，只使用行动力阈值控制
        if self.is_cl1_enabled:
            return_threshold, cl1_preserve = self._get_operation_coins_return_threshold()
            if return_threshold is None:
                logger.info('OperationCoinsReturnThreshold 为 0，禁用黄币检查，仅使用行动力阈值控制')
            elif self._check_yellow_coins_and_return_to_cl1("任务开始前", "短猫相接"):
                return
        
        if self.is_cl1_enabled and self.config.OpsiMeowfficerFarming_ActionPointPreserve < 500:
            logger.info('With CL1 leveling enabled, set action point preserve to 500')
            self.config.OpsiMeowfficerFarming_ActionPointPreserve = 500
        preserve = min(self.get_action_point_limit(self.config.OpsiMeowfficerFarming_APPreserveUntilReset),
                       self.config.OpsiMeowfficerFarming_ActionPointPreserve)
        if preserve == 0:
            self.config.override(OpsiFleet_Submarine=False)
        if self.is_cl1_enabled:
            # Without these enabled, CL1 gains 0 profits
            self.config.override(
                OpsiGeneral_DoRandomMapEvent=True,
                OpsiGeneral_AkashiShopFilter='ActionPoint',
                OpsiFleet_Submarine=False,
            )
            cd = self.nearest_task_cooling_down
            logger.attr('Task cooling down', cd)
            # At the last day of every month, OpsiObscure and OpsiAbyssal are scheduled frequently
            # Don't schedule after them
            remain = get_os_reset_remain()
            if cd is not None and remain > 0:
                logger.info(f'Having task cooling down, delay OpsiMeowfficerFarming after it')
                self.config.task_delay(target=cd.next_run)
                self.config.task_stop()
        if self.is_in_opsi_explore():
            logger.warning(f'OpsiExplore is still running, cannot do {self.config.task.command}')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        ap_checked = False
        while True:
            self.config.OS_ACTION_POINT_PRESERVE = preserve

            # ===== 智能调度: 行动力保留覆盖 =====
            # 如果启用了智能调度且设置了行动力保留值，优先使用智能调度的配置
            if is_smart_scheduling_enabled(self.config):
                if hasattr(self, '_get_smart_scheduling_action_point_preserve'):
                    smart_ap_preserve = self._get_smart_scheduling_action_point_preserve()
                    if smart_ap_preserve > 0:
                        logger.info(f'【智能调度】行动力保留使用智能调度配置: {smart_ap_preserve} (原配置: {self.config.OS_ACTION_POINT_PRESERVE})')
                        self.config.OS_ACTION_POINT_PRESERVE = smart_ap_preserve

            if self.config.is_task_enabled('OpsiAshBeacon') \
                    and not self._ash_fully_collected \
                    and self.config.OpsiAshBeacon_EnsureFullyCollected:
                logger.info('Ash beacon not fully collected, ignore action point limit temporarily')
                self.config.OS_ACTION_POINT_PRESERVE = 0
            logger.attr('OS_ACTION_POINT_PRESERVE', self.config.OS_ACTION_POINT_PRESERVE)
            if not ap_checked:
                # Check action points first to avoid using remaining AP when it not enough for tomorrow's daily
                # When not running CL1 and use oil
                keep_current_ap = True
                check_rest_ap = True
                if self.is_cl1_enabled:
                    return_threshold, _ = self._get_operation_coins_return_threshold()
                    # 如果值为 0，跳过黄币检查
                    if return_threshold is not None:
                        yellow_coins = self.get_yellow_coins()
                        if yellow_coins >= return_threshold:
                            check_rest_ap = False
                if not self.is_cl1_enabled and self.config.OpsiGeneral_BuyActionPointLimit > 0:
                    keep_current_ap = False
                if self.is_cl1_enabled and self.cl1_enough_yellow_coins:
                    check_rest_ap = False
                    try:
                        self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap)
                    except ActionPointLimit:
                        self.config.task_delay(server_update=True)
                        self.config.task_call('OpsiHazard1Leveling')
                        self.config.task_stop()
                else:
                    self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap)
                ap_checked = True
                
                # ===== 智能调度: 行动力阈值推送检查 =====
                # 在设置行动力后检查是否跨越阈值并推送通知
                self.check_and_notify_action_point_threshold()
                
                # ===== 智能调度: 短猫相接行动力不足检查 =====
                # 检查当前行动力是否低于配置的保留值
                if is_smart_scheduling_enabled(self.config):
                    # 获取行动力保留值（优先使用智能调度配置）
                    ap_preserve = self.config.OpsiMeowfficerFarming_ActionPointPreserve
                    if hasattr(self, '_get_smart_scheduling_action_point_preserve'):
                        smart_ap_preserve = self._get_smart_scheduling_action_point_preserve()
                        if smart_ap_preserve > 0:
                            ap_preserve = smart_ap_preserve

                    if self._action_point_total < ap_preserve:
                        logger.info(f'【智能调度】短猫相接行动力不足 ({self._action_point_total} < {ap_preserve})')
                        
                        # 获取当前黄币数量
                        yellow_coins = self.get_yellow_coins()
                        
                        # 推送通知
                        if self.is_cl1_enabled:
                            self.notify_push(
                                title="[Alas] 短猫相接 - 切换至侵蚀1",
                                content=f"行动力 {self._action_point_total} 不足 (需要 {ap_preserve})\n黄币: {yellow_coins}\n推迟短猫1小时，切换至侵蚀1继续执行"
                            )
                        else:
                            self.notify_push(
                                title="[Alas] 短猫相接 - 行动力不足",
                                content=f"行动力 {self._action_point_total} 不足 (需要 {ap_preserve})\n黄币: {yellow_coins}\n推迟1小时"
                            )
                        
                        # 推迟短猫1小时
                        logger.info('推迟短猫相接1小时')
                        self.config.task_delay(minute=60)
                        
                        # 如果启用了侵蚀1，立即切换回侵蚀1继续执行
                        if self.is_cl1_enabled:
                            logger.info('切换回侵蚀1继续执行')
                            with self.config.multi_set():
                                self.config.task_call('OpsiHazard1Leveling')
                        
                        # 停止当前短猫任务
                        self.config.task_stop()

            # (1252, 1012) is the coordinate of zone 134 (the center zone) in os_globe_map.png
            if self.config.OpsiMeowfficerFarming_TargetZone != 0 and not self.config.OpsiMeowfficerFarming_StayInZone:
                try:
                    zone = self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
                except ScriptError:
                    logger.warning(f'wrong zone_id input:{self.config.OpsiMeowfficerFarming_TargetZone}')
                    raise RequestHumanTakeover('wrong input, task stopped')
                else:
                    logger.hr(f'OS meowfficer farming, zone_id={zone.zone_id}', level=1)
                    self.globe_goto(zone, types='SAFE', refresh=True)
                    self.fleet_set(self.config.OpsiFleet_Fleet)
                    if self.run_strategic_search():
                        self._solved_map_event = set()
                        self._solved_fleet_mechanism = False
                        self.clear_question()
                        self.map_rescan()
                    self.handle_after_auto_search()
                    self.config.check_task_switch()
                continue

            if self.config.OpsiMeowfficerFarming_StayInZone:
                if self.config.OpsiMeowfficerFarming_TargetZone == 0:
                    logger.warning('StayInZone 已启用但未设置 TargetZone，跳过本次出击')
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
                try:
                    zone = self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
                except ScriptError:
                    logger.error('无法定位配置 of TargetZone, stop task')
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
                logger.hr(f'OS meowfficer farming (stay in zone), zone_id={zone.zone_id}', level=1)
                self.get_current_zone()
                if self.zone.zone_id != zone.zone_id or not self.is_zone_name_hidden:
                    self.globe_goto(zone, types='SAFE', refresh=True)

                #self.config.OS_ACTION_POINT_PRESERVE = 0
                keep_current_ap = True
                if self.config.OpsiGeneral_BuyActionPointLimit > 0:
                    keep_current_ap = False

                self.action_point_set(cost=120, keep_current_ap=keep_current_ap, check_rest_ap=True)
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)
                search_completed = False
                try:
                    search_completed = self.run_strategic_search()
                except TaskEnd:
                    raise
                except Exception as e:
                    logger.warning(f'Strategic search exception: {e}')

                if search_completed:
                    self._solved_map_event = set()
                    self._solved_fleet_mechanism = False
                    self.clear_question()
                    self.map_rescan()

                try:
                    self.handle_after_auto_search()
                except Exception:
                    logger.exception('Exception in handle_after_auto_search')

                #if not self.is_zone_name_hidden:
                #    try:
                #        self.globe_goto(zone, types='SAFE', refresh=True)
                #    except Exception as e2:
                #        logger.warning(f'重新进入目标海域失败: {e2}')

                self.config.check_task_switch()
                
                # ===== 循环中黄币充足检查 =====
                # 在每次循环后检查黄币是否充足，如果充足则返回侵蚀1
                if self._check_yellow_coins_and_return_to_cl1("循环中", "短猫相接"):
                    return
                
                continue

            zones = self.zone_select(hazard_level=self.config.OpsiMeowfficerFarming_HazardLevel) \
                .delete(SelectedGrids([self.zone])) \
                .delete(SelectedGrids(self.zones.select(is_port=True))) \
                .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)

            logger.hr(f'OS meowfficer farming, zone_id={zones[0].zone_id}', level=1)
            self.globe_goto(zones[0])
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(
                recon_scan=False,
                submarine_call=self.config.OpsiFleet_Submarine)
            self.run_auto_search()
            self.handle_after_auto_search()
            self.config.check_task_switch()
            
            # ===== 循环中黄币充足检查 =====
            # 在每次循环后检查黄币是否充足，如果充足则返回侵蚀1
            if self._check_yellow_coins_and_return_to_cl1("循环中"):
                return
            
            continue
