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
    
    def _should_skip_siren_research(self, grid):
        """
        重写父类方法，在塞壬探测装置搜索模式下跳过使用塞壬探测装置
        """
        # 如果开启了塞壬探测装置搜索模式，跳过使用塞壬探测装置
        if self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            if hasattr(grid, 'is_scanning_device') and grid.is_scanning_device:
                logger.info(f'[短猫任务] 在塞壬探测装置搜索模式下，跳过使用塞壬探测装置')
                return True
        
        # 调用父类方法
        return super()._should_skip_siren_research(grid)
    
    def map_rescan_current(self, drop=None):
        """
        重写父类方法，在塞壬探测装置搜索模式下跳过使用塞壬探测装置
        """
        # 如果开启了塞壬探测装置搜索模式，在检查塞壬探测装置时跳过处理
        if self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            # 确保视图已初始化
            if not hasattr(self, 'view') or self.view is None:
                self._view_init()
            try:
                self._update_view()
                # 需要调用 predict 才能正确检测塞壬探测装置
                self.view.predict()
            except Exception as e:
                logger.warning(f'[短猫任务] 更新视图失败: {e}')
            grids = self.view.select(is_scanning_device=True)
            logger.info(f'[短猫任务] map_rescan_current 检测到 {len(grids) if grids else 0} 个可疑格子')
            if grids and grids[0].is_scanning_device:
                # 标记为已处理，避免使用塞壬探测装置
                if not hasattr(self, '_solved_map_event'):
                    self._solved_map_event = set()
                if 'is_scanning_device' not in self._solved_map_event:
                    logger.info(f'[短猫任务] 在塞壬探测装置搜索模式下，发现塞壬探测装置 {grids[0]}，跳过使用')
                    self._solved_map_event.add('is_scanning_device')
        
        # 调用父类方法
        return super().map_rescan_current(drop=drop)
    
    def _handle_siren_detector_at_map(self, zone_id):
        """
        进入地图后检查是否有塞壬探测装置
        如果发现，记录该海域，并标记为已处理以避免自律时使用它
        只需要记录该海域，不需要特殊处理
        
        Args:
            zone_id: 当前海域ID
        
        Returns:
            bool: 如果发现塞壬探测装置，返回是否已达到指定数量（达到数量返回True，否则返回False）
                 如果没有发现，返回False
        """
        if not self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            return False
        
        # 更新地图视图
        self.update()
        self.view.predict()
        
        # 扫描整个地图寻找塞壬探测装置
        grids = self.view.select(is_scanning_device=True)
        logger.info(f'塞壬探测装置检查: 发现 {len(grids) if grids else 0} 个可疑格子')
        
        if grids and grids[0].is_scanning_device:
            logger.hr(f'在海域 {zone_id} 发现塞壬探测装置', level=2)
            
            # 记录到配置中
            zone_str = f'{zone_id}'
            current_str = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones
            found_count = 0
            if current_str is None:
                self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones = zone_str
                found_count = 1
            else:
                # 检查是否已经记录过该海域
                if zone_str not in str(current_str):
                    self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones = str(current_str) + ',' + zone_str
                    # 计算已找到的数量（逗号分隔的数量+1）
                    found_count = len(str(current_str).split(',')) + 1
                else:
                    # 已经记录过，计算当前数量
                    found_count = len(str(current_str).split(','))
            logger.info(f'已记录塞壬探测装置海域: {self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones}')
            logger.info(f'当前已找到塞壬探测装置数量: {found_count}')
            
            # 标记为已处理，避免自律时使用塞壬探测装置
            # 在短猫任务的塞壬探测装置搜索模式下，只记录海域，不使用装置
            if not hasattr(self, '_solved_map_event'):
                self._solved_map_event = set()
            self._solved_map_event.add('is_scanning_device')
            logger.info('已标记塞壬探测装置为已处理，自律时将跳过使用')
            
            # 检查是否达到指定数量
            stop_after_found = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_StopAfterFound
            if stop_after_found > 0 and found_count >= stop_after_found:
                logger.hr(f'已找到 {found_count} 个塞壬探测装置，达到设定数量 {stop_after_found}，停止搜索模式', level=1)
                return True
            
            return False
        
        return False
    
    def _handle_siren_detector_after_auto_search(self, zone_id):
        """
        自律结束后检查是否有塞壬探测装置
        如果发现，只记录该海域，标记为已处理，不触发自律
        
        Args:
            zone_id: 当前海域ID
        """
        if not self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            return
        
        # 检查 map 对象是否存在，如果不存在则先初始化地图数据
        if not hasattr(self, 'map') or not self.map.grids:
            logger.warning('自律后地图数据未加载，正在初始化...')
            self.map_data_init(map_=None)
            self.update()
            self.view.predict()
        
        # 扫描整个地图寻找塞壬探测装置
        grids = self.view.select(is_scanning_device=True)
        logger.info(f'自律后塞壬探测装置检查: 发现 {len(grids) if grids else 0} 个可疑格子')
        
        if grids and grids[0].is_scanning_device:
            logger.hr(f'在海域 {zone_id} 发现塞壬探测装置（自律后）', level=2)
            
            # 记录到配置中
            zone_str = f'{zone_id}'
            current_str = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones
            found_count = 0
            if current_str is None:
                self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones = zone_str
                found_count = 1
            else:
                # 检查是否已经记录过该海域
                if zone_str not in str(current_str):
                    self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones = str(current_str) + ',' + zone_str
                    found_count = len(str(current_str).split(',')) + 1
                else:
                    found_count = len(str(current_str).split(','))
            logger.info(f'已记录塞壬探测装置海域: {self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones}')
            logger.info(f'当前已找到塞壬探测装置数量: {found_count}')
            
            # 标记为已处理，避免再次触发自律
            if not hasattr(self, '_solved_map_event'):
                self._solved_map_event = set()
            self._solved_map_event.add('is_scanning_device')
            logger.info('已标记塞壬探测装置为已处理，自律时将跳过使用')
            
            # 检查是否达到指定数量
            stop_after_found = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_StopAfterFound
            if stop_after_found > 0 and found_count >= stop_after_found:
                logger.hr(f'已找到 {found_count} 个塞壬探测装置，达到设定数量 {stop_after_found}，停止搜索模式', level=1)
                self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable = False
    
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

            # ===== 塞壬探测装置搜索模式 =====
            # 优先检查塞壬探测装置搜索模式，即使设置了 TargetZone 也会先执行搜索
            siren_search_enabled = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable
            logger.info(f'塞壬探测装置搜索模式检查：SirenDetectorSearch_Enable={siren_search_enabled}')
            if siren_search_enabled:
                # 临时禁用指定海域计划作战（StayInZone），强制使用普通短猫模式
                self._original_stay_in_zone = self.config.OpsiMeowfficerFarming_StayInZone
                if self._original_stay_in_zone:
                    self.config.OpsiMeowfficerFarming_StayInZone = False
                    logger.info('塞壬探测装置搜索模式：临时禁用指定海域计划作战')

            # (1252, 1012) is the coordinate of zone 134 (the center zone) in os_globe_map.png
            # 只有在塞壬探测装置搜索模式未开启时才执行 TargetZone 分支
            if not siren_search_enabled and self.config.OpsiMeowfficerFarming_TargetZone != 0 and not self.config.OpsiMeowfficerFarming_StayInZone:
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

            # 如果开启了塞壬探测装置搜索模式，直接跳过 StayInZone 分支
            if self.config.OpsiMeowfficerFarming_StayInZone and not siren_search_enabled:
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

            # ===== 塞壬探测装置搜索 =====
            # 如果开启了自动寻找塞壬探测装置功能，使用配置的侵蚀等级来选择海域
            siren_search_enabled = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable
            if siren_search_enabled:
                # 使用塞壬探测装置搜索的侵蚀等级（只在中心海域中选择）
                hazard_level = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_HazardLevel
                logger.hr(f'塞壬探测装置搜索模式, hazard_level={hazard_level} (仅在中心海域)', level=1)
                
                # 获取已记录的海域列表（排除已发现塞壬探测装置的海域）
                found_zones_str = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones
                excluded_zones = []
                if found_zones_str:
                    for z in str(found_zones_str).split(','):
                        z = z.strip()
                        if not z:
                            continue
                        try:
                            zone_id = int(z)
                            selected = self.zones.select(zone_id=zone_id)
                            if selected:
                                excluded_zones.append(selected[0])
                            else:
                                logger.warning(f'无效的zone_id: {zone_id}, 在self.zones中未找到, 跳过')
                        except ValueError:
                            logger.warning(f'非法的zone_id格式: "{z}", 无法转换为整数, 跳过')
                    if excluded_zones:
                        logger.info(f'已记录的海域，将排除: {excluded_zones}')
                
                # 先选择中心海域（region 5），然后筛选指定侵蚀等级
                zones = self.zones.select(region=5, hazard_level=hazard_level) \
                    .delete(SelectedGrids([self.zone])) \
                    .delete(SelectedGrids(self.zones.select(is_port=True))) \
                    .delete(SelectedGrids(excluded_zones)) \
                    .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)
            else:
                hazard_level = self.config.OpsiMeowfficerFarming_HazardLevel
                zones = self.zone_select(hazard_level=hazard_level) \
                    .delete(SelectedGrids([self.zone])) \
                    .delete(SelectedGrids(self.zones.select(is_port=True))) \
                    .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)

            logger.hr(f'OS meowfficer farming, zone_id={zones[0].zone_id}', level=1)
            current_zone_id = zones[0].zone_id
            # 塞壬探测装置搜索模式只选择安全海域
            if siren_search_enabled:
                self.globe_goto(zones[0], types='SAFE')
            else:
                self.globe_goto(zones[0])
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(
                recon_scan=False,
                submarine_call=self.config.OpsiFleet_Submarine)
            
            # ===== 塞壬探测装置搜索模式核心逻辑 =====
            # 1. 先用二队卡住一个敌人（fleet_mechanism）
            # 2. 换回短猫指定的一队进行自律
            # 3. 自律结束后检查是否有塞壬探测装置
            # 4. 如果发现 - 记录海域，不处理卡住的敌人
            # 5. 如果没发现 - 处理卡住的敌人（fleet_mechanism）
            if siren_search_enabled:
                # 临时禁用塞壬研究功能，避免触发自律
                self._original_siren_research_enable = self.config.cross_get(
                    keys="OpsiHazard1Leveling.OpsiSirenBug.SirenResearch_Enable", default=False)
                self.config.cross_set(
                    keys="OpsiHazard1Leveling.OpsiSirenBug.SirenResearch_Enable", value=False)
                logger.info('塞壬探测装置搜索模式：临时禁用塞壬研究功能')
                # 设置标志位，让 story_skip 在整个搜索过程中遇到塞壬探测装置选项时点击第3个选项（离开）
                self.config._disable_siren_research = True
                logger.info('塞壬探测装置搜索模式：设置 _disable_siren_research 标志，整个搜索过程中遇到塞壬探测装置选项时将选择离开')
                
                # ===== 步骤1: 用卡位舰队卡住敌人 =====
                # 获取配置的卡位舰队编号
                block_fleet = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FleetForBlock
                logger.info(f'塞壬探测装置搜索模式：使用 {block_fleet} 队卡住敌人')
                # 切换到卡位舰队
                self.fleet_set(block_fleet)
                # 临时禁用塞壬研究功能，避免触发
                self.config.cross_set(
                    keys="OpsiHazard1Leveling.OpsiSirenBug.SirenResearch_Enable", value=False)
                
                # 使用 os_auto_search_daemon_until_combat 卡住敌人
                # 这个函数会一直搜索直到遇到敌人，然后自动进入战斗
                block_fleet = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FleetForBlock
                logger.info(f'塞壬探测装置搜索模式：{block_fleet}队开始寻敌直到遇到敌人')
                try:
                    self.os_auto_search_daemon_until_combat(drop=None)
                    logger.info(f'塞壬探测装置搜索模式：遇到敌舰，{block_fleet}队卡位完成')
                except Exception as e:
                    logger.info(f'塞壬探测装置搜索模式：{block_fleet}队寻敌异常={e}，可能没有敌人')
                
                # 切换回一队
                self.fleet_set(1)
                
                # ===== 步骤2: 换回一队进行自律 =====
                logger.info('塞壬探测装置搜索模式：换回一队进行自律')
                self.fleet_set(self.config.OpsiFleet_Fleet)
                # 恢复塞壬研究功能设置（供一队使用）
                if hasattr(self, '_original_siren_research_enable'):
                    self.config.cross_set(
                        keys="OpsiHazard1Leveling.OpsiSirenBug.SirenResearch_Enable",
                        value=self._original_siren_research_enable)
                # 执行一队自律（默认会进行地图扫描，处理随机事件）
                logger.info('塞壬探测装置搜索模式：一队执行自律，开始处理随机事件')
                self.run_auto_search()
                logger.info(f'塞壬探测装置搜索模式：一队自律结束，_solved_map_event={self._solved_map_event}')
                
                # ===== 步骤3: 自律结束后检查塞壬探测装置 =====
                # 由于塞壬探测装置在雷达上不以问号形式显示，需要显式使用地图扫描来检测
                siren_detector_found = False
                
                # 先检查 _solved_map_event 是否有记录
                if 'is_scanning_device' in self._solved_map_event:
                    logger.hr(f'在海域 {current_zone_id} 发现塞壬探测装置（自律过程中检测到）', level=2)
                    siren_detector_found = True
                else:
                    # _solved_map_event 中没有记录，需要使用地图全图扫描来检测塞壬探测装置
                    # 因为塞壬探测装置在雷达上不以问号形式显示，clear_question 不会处理它
                    # 使用 map_rescan() 进行全图扫描（和月度开荒相同的逻辑）
                    logger.info('塞壬探测装置搜索模式：使用全图扫描检测塞壬探测装置')
                    
                    # 调用 map_rescan 进行全图扫描
                    # 这会初始化地图数据并遍历所有摄像头位置
                    self.map_rescan(rescan_mode='full')
                    
                    # 检查是否检测到塞壬探测装置
                    if 'is_scanning_device' in self._solved_map_event:
                        logger.hr(f'在海域 {current_zone_id} 发现塞壬探测装置（全图扫描检测到）', level=2)
                        siren_detector_found = True
                    else:
                        logger.info('塞壬探测装置搜索模式：全图扫描未发现塞壬探测装置')
                        siren_detector_found = False
                
                # 如果发现塞壬探测装置，记录到配置中
                if siren_detector_found:
                    zone_str = f'{current_zone_id}'
                    current_str = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones
                    found_count = 0
                    if current_str is None:
                        self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones = zone_str
                        found_count = 1
                    else:
                        if zone_str not in str(current_str):
                            self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones = str(current_str) + ',' + zone_str
                            found_count = len(str(current_str).split(',')) + 1
                        else:
                            found_count = len(str(current_str).split(','))
                    logger.info(f'已记录塞壬探测装置海域: {self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones}')
                    logger.info(f'当前已找到塞壬探测装置数量: {found_count}')
                    
                    # 检查是否达到设定数量
                    stop_after_found = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_StopAfterFound
                    if stop_after_found > 0 and found_count >= stop_after_found:
                        logger.hr(f'已找到 {found_count} 个塞壬探测装置，达到设定数量 {stop_after_found}，停止搜索模式', level=1)
                        # 关闭塞壬探测装置搜索模式
                        self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable = False
                        # 恢复塞壬研究功能
                        if hasattr(self, '_original_siren_research_enable'):
                            self.config.cross_set(
                                keys="OpsiHazard1Leveling.OpsiSirenBug.SirenResearch_Enable",
                                value=self._original_siren_research_enable)
                        # 清除 _disable_siren_research 标志
                        if hasattr(self.config, '_disable_siren_research'):
                            delattr(self.config, '_disable_siren_research')
                            logger.info('塞壬探测装置搜索模式结束：清除 _disable_siren_research 标志')
                        # 恢复指定海域计划作战设置
                        if hasattr(self, '_original_stay_in_zone'):
                            self.config.OpsiMeowfficerFarming_StayInZone = self._original_stay_in_zone
                        # 不处理卡住的敌人，直接跳过本次出击
                        self.handle_after_auto_search()
                        self.config.check_task_switch()
                        continue
                
                # 如果没有发现塞壬探测装置，卡位舰队自律寻敌解决卡住的敌人
                if not siren_detector_found:
                    block_fleet = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FleetForBlock
                    logger.info(f'未发现塞壬探测装置，{block_fleet}队自律寻敌解决卡住的敌人')
                    # 切换到卡位舰队进行自律寻敌
                    self.fleet_set(block_fleet)
                    # 卡位舰队自律寻敌会自动解决卡住的敌人
                    self.os_auto_search_run(drop=None)
                    # 处理完后换回一队
                    self.fleet_set(self.config.OpsiFleet_Fleet)
                
                # 恢复塞壬研究功能设置
                if hasattr(self, '_original_siren_research_enable'):
                    self.config.cross_set(
                        keys="OpsiHazard1Leveling.OpsiSirenBug.SirenResearch_Enable",
                        value=self._original_siren_research_enable)
                    logger.info(f'塞壬探测装置搜索模式结束：恢复塞壬研究功能为 {self._original_siren_research_enable}')
                
                # 清除 _disable_siren_research 标志
                if hasattr(self.config, '_disable_siren_research'):
                    delattr(self.config, '_disable_siren_research')
                    logger.info('塞壬探测装置搜索模式结束：清除 _disable_siren_research 标志')
                
                # 恢复指定海域计划作战设置
                if hasattr(self, '_original_stay_in_zone'):
                    self.config.OpsiMeowfficerFarming_StayInZone = self._original_stay_in_zone
                    logger.info(f'塞壬探测装置搜索模式结束：恢复指定海域计划作战为 {self._original_stay_in_zone}')
            else:
                # 普通模式：直接执行自律搜索
                self.run_auto_search()
            
            self.handle_after_auto_search()
            self.config.check_task_switch()
            
            # ===== 循环中黄币充足检查 =====
            # 在每次循环后检查黄币是否充足，如果充足则返回侵蚀1
            if self._check_yellow_coins_and_return_to_cl1("循环中"):
                return
            
            continue
