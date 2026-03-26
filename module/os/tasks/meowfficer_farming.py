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
    SIREN_DETECTOR_HAZARD_LEVELS = (5, 6)

    def _clone_siren_found(self, found):
        return {level: set(found.get(level, set())) for level in self.SIREN_DETECTOR_HAZARD_LEVELS}

    def _get_zone_hazard_level(self, zone_id):
        selected = self.zones.select(zone_id=int(zone_id))
        if not selected:
            return None
        return selected[0].hazard_level

    def _parse_siren_found_zones(self):
        """
        Parse found zones as level-aware records.

        Supported formats in config:
        - New format: "5:151,6:153"
        - Legacy format: "151,153" (will be mapped by real zone hazard level)
        """
        raw = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones
        raw_text = str(raw) if raw else ''

        if getattr(self, '_siren_found_cache_raw', None) == raw_text and hasattr(self, '_siren_found_cache_parsed'):
            return self._clone_siren_found(self._siren_found_cache_parsed)

        found = {level: set() for level in self.SIREN_DETECTOR_HAZARD_LEVELS}
        if not raw_text:
            self._siren_found_cache_raw = raw_text
            self._siren_found_cache_parsed = self._clone_siren_found(found)
            return found

        for token in raw_text.split(','):
            token = token.strip()
            if not token:
                continue

            if ':' in token:
                level_text, zone_text = token.split(':', 1)
                try:
                    level = int(level_text.strip())
                    zone_id = int(zone_text.strip())
                except ValueError:
                    logger.warning(f'忽略非法分级海域记录: "{token}"')
                    continue

                real_level = self._get_zone_hazard_level(zone_id)
                if real_level in self.SIREN_DETECTOR_HAZARD_LEVELS:
                    found[real_level].add(zone_id)
                else:
                    logger.warning(f'忽略无效海域ID: {zone_id} (不在中心海域5/6级)')
                continue

            try:
                zone_id = int(token)
            except ValueError:
                logger.warning(f'忽略非法海域 ID 格式: "{token}"')
                continue

            real_level = self._get_zone_hazard_level(zone_id)
            if real_level in self.SIREN_DETECTOR_HAZARD_LEVELS:
                found[real_level].add(zone_id)
            else:
                logger.warning(f'忽略无效海域ID: {zone_id} (不在中心海域5/6级)')

        self._siren_found_cache_raw = raw_text
        self._siren_found_cache_parsed = self._clone_siren_found(found)
        return found

    def _dump_siren_found_zones(self, found):
        tokens = []
        for level in self.SIREN_DETECTOR_HAZARD_LEVELS:
            for zone_id in sorted(found.get(level, set())):
                tokens.append(f'{level}:{zone_id}')
        return ','.join(tokens) if tokens else None

    def _record_siren_found_zone(self, zone_id):
        """
        Record one zone in level-aware format.

        Returns:
            tuple[int, int, bool]: (zone_hazard_level, count_in_that_level, added)
        """
        level = self._get_zone_hazard_level(zone_id)
        if level not in self.SIREN_DETECTOR_HAZARD_LEVELS:
            logger.warning(f'海域 {zone_id} 不属于中心海域5/6级，跳过记录')
            return None, 0, False

        found = self._parse_siren_found_zones()
        before = len(found[level])
        found[level].add(int(zone_id))
        added = len(found[level]) > before

        dumped = self._dump_siren_found_zones(found)
        self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones = dumped
        self._siren_found_cache_raw = str(dumped) if dumped else ''
        self._siren_found_cache_parsed = self._clone_siren_found(found)
        return level, len(found[level]), added
    
    def _should_skip_siren_research(self, grid):
        """判断是否应跳过塞壬研究（在搜索模式下）。

        Args:
            grid: 地图格子对象。

        Returns:
            bool: 如果应跳过则返回 True，否则返回 False。
        """
        if self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            if hasattr(grid, 'is_scanning_device') and grid.is_scanning_device:
                logger.info('[短猫任务] 塞壬探测装置搜索模式下，跳过使用塞壬探测装置')
                return True
        
        return super()._should_skip_siren_research(grid)
    
    def map_rescan_current(self, drop=None):
        """在当前位置重新扫描（处理搜索模式逻辑）。

        Args:
            drop: 掉落处理对象。
        """
        if self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            if not hasattr(self, 'view') or self.view is None:
                self._view_init()
            try:
                self._update_view()
                self.view.predict()
            except Exception as e:
                logger.warning(f'[短猫任务] 更新视图失败: {e}')
            
            grids = self.view.select(is_scanning_device=True)
            logger.info(f'[短猫任务] 当前扫描检测到 {len(grids) if grids else 0} 个可疑格子')
            if grids and grids[0].is_scanning_device:
                if not hasattr(self, '_solved_map_event'):
                    self._solved_map_event = set()
                if 'is_scanning_device' not in self._solved_map_event:
                    logger.info(f'[短猫任务] 搜索模式发现塞壬探测装置 {grids[0]}，跳过使用')
                    self._solved_map_event.add('is_scanning_device')
        
        return super().map_rescan_current(drop=drop)
    
    def _handle_siren_detector_at_map(self, zone_id):
        """进入地图后检查是否有塞壬探测装置。

        Args:
            zone_id: 当前海域 ID。

        Returns:
            bool: 如果发现且达到指定数量返回 True，否则返回 False。
        """
        if not self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            return False
        
        self.update()
        self.view.predict()
        
        grids = self.view.select(is_scanning_device=True)
        logger.info(f'塞壬探测装置检查: 发现 {len(grids) if grids else 0} 个可疑格子')
        
        if grids and grids[0].is_scanning_device:
            logger.hr(f'在海域 {zone_id} 发现塞壬探测装置', level=2)
            level, found_count, added = self._record_siren_found_zone(zone_id)
            if not level:
                return False

            logger.info(f'已记录海域: {self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones}')
            if added:
                logger.info(f'已找到数量(侵蚀{level}): {found_count}')
            else:
                logger.info(f'侵蚀{level}海域 {zone_id} 已存在记录，当前数量: {found_count}')
            
            if not hasattr(self, '_solved_map_event'):
                self._solved_map_event = set()
            self._solved_map_event.add('is_scanning_device')
            logger.info('已将探测装置标记为已处理，自律中将跳过')
            
            stop_after_found = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_StopAfterFound
            if stop_after_found > 0 and found_count >= stop_after_found:
                logger.hr(f'侵蚀{level}已找到 {found_count} 个探测装置，达到设定目标 {stop_after_found}，停止搜索模式', level=1)
                return True
            
            return False
        
        return False
    
    def _handle_siren_detector_after_auto_search(self, zone_id):
        """自律结束后检查是否有塞壬探测装置。

        Args:
            zone_id: 当前海域 ID。
        """
        if not self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable:
            return
        
        if not hasattr(self, 'map') or not self.map.grids:
            logger.warning('自律后地图数据未加载，正在初始化...')
            self.map_data_init(map_=None)
            self.update()
            self.view.predict()
        
        grids = self.view.select(is_scanning_device=True)
        logger.info(f'自律后检测发现 {len(grids) if grids else 0} 个可疑格子')
        
        if grids and grids[0].is_scanning_device:
            logger.hr(f'在海域 {zone_id} 发现塞壬探测装置（自律后）', level=2)
            level, found_count, added = self._record_siren_found_zone(zone_id)
            if not level:
                return

            logger.info(f'已记录海域: {self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones}')
            if added:
                logger.info(f'已找到数量(侵蚀{level}): {found_count}')
            else:
                logger.info(f'侵蚀{level}海域 {zone_id} 已存在记录，当前数量: {found_count}')
            
            if not hasattr(self, '_solved_map_event'):
                self._solved_map_event = set()
            self._solved_map_event.add('is_scanning_device')
            logger.info('已将探测装置标记为已处理，防止自律重复触发')
            
            stop_after_found = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_StopAfterFound
            if stop_after_found > 0 and found_count >= stop_after_found:
                logger.hr(f'侵蚀{level}已找到 {found_count} 个探测装置，达到设定目标 {stop_after_found}，停止搜索模式', level=1)
                self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable = False
    
    def _meow_ap_and_scheduling_check(self, preserve, ap_checked):
        """Action point check and scheduling check"""
        self.config.OS_ACTION_POINT_PRESERVE = preserve

        # ===== 智能调度：行动力保留覆盖 =====
        if is_smart_scheduling_enabled(self.config):
            if hasattr(self, '_get_smart_scheduling_action_point_preserve'):
                smart_ap_preserve = self._get_smart_scheduling_action_point_preserve()
                if smart_ap_preserve > 0:
                    logger.info(f'[智能调度] 行动力保留使用智能调度配置: {smart_ap_preserve} (原配置: {self.config.OS_ACTION_POINT_PRESERVE})')
                    self.config.OS_ACTION_POINT_PRESERVE = smart_ap_preserve

        if self.config.is_task_enabled('OpsiAshBeacon') \
                and not self._ash_fully_collected \
                and self.config.OpsiAshBeacon_EnsureFullyCollected:
            logger.info('余烬信标未收集满，暂时忽略行动力限制')
            self.config.OS_ACTION_POINT_PRESERVE = 0
        logger.attr('OS_ACTION_POINT_PRESERVE', self.config.OS_ACTION_POINT_PRESERVE)

        if not ap_checked:
            # 行动力前置检查，确保明日每日任务有足够行动力
            keep_current_ap = True
            check_rest_ap = True
            if self.is_cl1_enabled:
                return_threshold, _ = self._get_operation_coins_return_threshold()
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

            self.check_and_notify_action_point_threshold()

            # ===== 智能调度：行动力不足检查 =====
            if is_smart_scheduling_enabled(self.config):
                ap_preserve = self.config.OpsiMeowfficerFarming_ActionPointPreserve
                if hasattr(self, '_get_smart_scheduling_action_point_preserve'):
                    smart_ap_preserve = self._get_smart_scheduling_action_point_preserve()
                    if smart_ap_preserve > 0:
                        ap_preserve = smart_ap_preserve

                if self._action_point_total < ap_preserve:
                    logger.info(f'[智能调度] 短猫相接行动力不足 ({self._action_point_total} < {ap_preserve})')
                    yellow_coins = self.get_yellow_coins()

                    if self.is_cl1_enabled:
                        self.notify_push(
                            title="[Alas] 短猫相接 - 切换至侵蚀 1",
                            content=f"行动力 {self._action_point_total} 不足 (需要 {ap_preserve})\n补充凭证: {yellow_coins}\n推迟短猫 1 小时，切换至侵蚀 1"
                        )
                    else:
                        self.notify_push(
                            title="[Alas] 短猫相接 - 行动力不足",
                            content=f"行动力 {self._action_point_total} 不足 (需要 {ap_preserve})\n凭证: {yellow_coins}\n任务推迟 1 小时"
                        )

                    logger.info('已推迟短猫相接 1 小时')
                    self.config.task_delay(minute=60)

                    if self.is_cl1_enabled:
                        logger.info('主动切换回侵蚀 1 任务')
                        with self.config.multi_set():
                            self.config.task_call('OpsiHazard1Leveling')

                    self.config.task_stop()
            return True
        return ap_checked

    def _meow_handle_traditional_zone(self):
        try:
            zone = self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
        except ScriptError:
            logger.warning(f'目标海域输入错误: {self.config.OpsiMeowfficerFarming_TargetZone}')
            raise RequestHumanTakeover('输入海域无效，任务已停止')
        else:
            logger.hr(f'OS meowfficer farming, zone_id={zone.zone_id}', level=1)
            self.globe_goto(zone, types='SAFE', refresh=True)
            self.fleet_set(self.config.OpsiFleet_Fleet)
            # 开始短猫搜索计时
            self._meow_searching_active = True
            self._meow_time_recording_enabled = True
            import time as time_module
            self._meow_battle_timer = time_module.time()
            self.on_meow_search_start()
            if self.run_strategic_search():
                self._solved_map_event = set()
                self._solved_fleet_mechanism = False
                self.clear_question()
                self.map_rescan()
            self.handle_after_auto_search()
            # 结束短猫搜索计时
            self.on_meow_search_end()
            self.config.check_task_switch()

    def _meow_handle_stay_in_zone(self):
        if self.config.OpsiMeowfficerFarming_TargetZone == 0:
            logger.warning('已启用 StayInZone 但未设置 TargetZone，跳过本次任务')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
        try:
            zone = self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
        except ScriptError:
            logger.error('无法定位配置的目标海域，停止任务')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
        
        logger.hr(f'OS meowfficer farming (stay in zone), zone_id={zone.zone_id}', level=1)
        self.get_current_zone()
        if self.zone.zone_id != zone.zone_id or not self.is_zone_name_hidden:
            self.globe_goto(zone, types='SAFE', refresh=True)

        keep_current_ap = True
        if self.config.OpsiGeneral_BuyActionPointLimit > 0:
            keep_current_ap = False

        self.action_point_set(cost=120, keep_current_ap=keep_current_ap, check_rest_ap=True)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)

        # 开始短猫搜索计时
        self._meow_searching_active = True
        self._meow_time_recording_enabled = True
        import time as time_module
        self._meow_battle_timer = time_module.time()
        self.on_meow_search_start()

        search_completed = False
        try:
            search_completed = self.run_strategic_search()
        except TaskEnd:
            raise
        except Exception as e:
            logger.warning(f'战略搜索异常: {e}')

        if search_completed:
            self._solved_map_event = set()
            self._solved_fleet_mechanism = False
            self.clear_question()
            self.map_rescan()

        try:
            self.handle_after_auto_search()
        except Exception:
            logger.exception('handle_after_auto_search 发生异常')

        # 结束短猫搜索计时
        self.on_meow_search_end()

        self.config.check_task_switch()
        
        if self._check_yellow_coins_and_return_to_cl1("循环中", "短猫相接"):
            return True
        return False

    def _meow_handle_siren_detector_search(self):
        hazard_level = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_HazardLevel
        logger.hr(f'探测装置搜索模式，当前侵蚀等级: {hazard_level} (仅中心海域)', level=1)

        # 步骤 0. 临时配置：禁用塞壬研究（做一次即可，后续会显式恢复原值）
        # 设计说明：这里按"覆盖式临时状态"处理，后续会显式恢复原值。
        self._original_siren_research_enable = self.config.OpsiSirenBug_SirenResearch_Enable
        self.config.OpsiSirenBug_SirenResearch_Enable = False
        logger.info('探测装置搜索：临时禁用塞壬研究')
        
        self.config._disable_siren_research = True
        logger.info('探测装置搜索：已设置离开标志，遇到装置选项时将选择离开')

        def _restore_siren_search_state():
            if hasattr(self, '_original_siren_research_enable'):
                self.config.OpsiSirenBug_SirenResearch_Enable = self._original_siren_research_enable
            if hasattr(self.config, '_disable_siren_research'):
                delattr(self.config, '_disable_siren_research')
            # 清理忽略标记（不修改配置本身）
            if hasattr(self, '_siren_search_ignore_stay_in_zone'):
                try:
                    delattr(self, '_siren_search_ignore_stay_in_zone')
                except Exception:
                    pass
            if hasattr(self, '_original_siren_research_enable'):
                try:
                    delattr(self, '_original_siren_research_enable')
                except Exception:
                    pass

        # 获取目标数量
        stop_after_found = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_StopAfterFound
        
        # 持续循环：不断搜索zones直到达成目标或无可搜zones
        while True:
            # 重新解析已找到的zone，用于排除
            excluded_zones = []
            found = self._parse_siren_found_zones()
            level_zone_ids = sorted(found.get(hazard_level, set()))
            for zone_id in level_zone_ids:
                selected = self.zones.select(zone_id=zone_id)
                if selected:
                    excluded_zones.append(selected[0])

            if excluded_zones:
                logger.info(f'侵蚀{hazard_level}已找到海域，将排除: {excluded_zones}')
            
            # 在中心海域 (region 5) 中筛选未搜索的zones
            zones = self.zones.select(region=5, hazard_level=hazard_level) \
                .delete(SelectedGrids([self.zone])) \
                .delete(SelectedGrids(self.zones.select(is_port=True))) \
                .delete(SelectedGrids(excluded_zones)) \
                .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)
            
            if not zones:
                logger.warning(f'探测装置搜索模式：无更多符合条件的海域 (侵蚀等级 {hazard_level})')
                _restore_siren_search_state()
                break  # 无可搜zones，退出外层while循环
            
            # 内层循环：逐个搜索该轮的zones
            for zone_obj in zones:
                current_zone_id = zone_obj.zone_id
                logger.hr(f'OS meowfficer farming, zone_id={current_zone_id}', level=1)
                
                self.globe_goto(zone_obj, types='SAFE')
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)
                
                # 步骤 2. 舰队卡位：切换到指定舰队卡住敌人
                block_fleet = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FleetForBlock
                logger.info(f'探测装置搜索：使用舰队 {block_fleet} 进行卡位')
                self.fleet_set(block_fleet)
                
                try:
                    self.os_auto_search_daemon_until_combat(drop=None)
                    logger.info(f'探测装置搜索：已通过团队 {block_fleet} 完成卡位')
                except Exception as e:
                    logger.info(f'探测装置搜索：舰队 {block_fleet} 寻敌异常或未发现敌人: {e}')
                
                # 步骤 3. 主队自律：换回主队执行短猫逻辑
                self.fleet_set(self.config.OpsiFleet_Fleet)
                if hasattr(self, '_original_siren_research_enable'):
                    self.config.OpsiSirenBug_SirenResearch_Enable = self._original_siren_research_enable
                
                logger.info('探测装置搜索：换回主队执行自律')
                # 开始短猫搜索计时
                self._meow_searching_active = True
                self._meow_time_recording_enabled = True
                import time as time_module
                self._meow_battle_timer = time_module.time()
                self.on_meow_search_start()
                self.run_auto_search()
                logger.info(f'探测装置搜索：自律完成，标记事件: {self._solved_map_event}')
                
                # 步骤 4. 结果检测：检查是否有塞壬探测装置
                siren_detector_found = False
                if 'is_scanning_device' in self._solved_map_event:
                    logger.hr(f'在海域 {current_zone_id} 发现塞壬探测装置 (自律检测)', level=2)
                    siren_detector_found = True
                else:
                    logger.info('探测装置搜索：正通过全图扫描进行最后确认')
                    self.map_rescan(rescan_mode='full')
                    if 'is_scanning_device' in self._solved_map_event:
                        logger.hr(f'在海域 {current_zone_id} 发现塞壬探测装置 (全图扫描)', level=2)
                        siren_detector_found = True
                    else:
                        logger.info('探测装置搜索：全图扫描未发现装置')

                # 步骤 5. 记录与收尾
                if not siren_detector_found:
                    # 未发现时的后续处理：由卡位舰队清理残局
                    block_fleet = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FleetForBlock
                    logger.info(f'未发现装置，由舰队 {block_fleet} 执行清理，继续搜索下一个海域')
                    self.fleet_set(block_fleet)
                    self.os_auto_search_run(drop=None)
                    self.fleet_set(self.config.OpsiFleet_Fleet)
                    # 此处不恢复状态，继续while循环搜索下一个zone
                    continue

                level, found_count, added = self._record_siren_found_zone(current_zone_id)
                if not level:
                    _restore_siren_search_state()
                    return False

                logger.info(f'已记录海域: {self.config.OpsiMeowfficerFarming_SirenDetectorSearch_FoundZones}')
                if added:
                    logger.info(f'累计发现数量(侵蚀{level}): {found_count}')
                else:
                    logger.info(f'侵蚀{level}海域 {current_zone_id} 已存在记录，当前数量: {found_count}')

                if stop_after_found > 0 and found_count >= stop_after_found:
                    logger.hr(f'侵蚀{level}达成目标数量 {stop_after_found}，关闭搜索模式', level=1)
                    self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable = False
                    _restore_siren_search_state()
                    self.handle_after_auto_search()

                # 仅在找到探测装置后结束本轮并返回
                self.on_meow_search_end()
                self.config.check_task_switch()
                return True

        _restore_siren_search_state()

        # 结束短猫搜索计时
        self.on_meow_search_end()

        return False
        
    def _meow_handle_normal_search(self):
        hazard_level = self.config.OpsiMeowfficerFarming_HazardLevel
        zones = self.zone_select(hazard_level=hazard_level) \
            .delete(SelectedGrids([self.zone])) \
            .delete(SelectedGrids(self.zones.select(is_port=True))) \
            .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)

        if not zones:
            logger.warning(f'普通搜索模式：未找到符合条件的海域 (侵蚀等级 {hazard_level})')
            return

        logger.hr(f'OS meowfficer farming, zone_id={zones[0].zone_id}', level=1)

        self.globe_goto(zones[0])

        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)

        # 开始短猫搜索计时
        self._meow_searching_active = True
        self._meow_time_recording_enabled = True
        import time as time_module
        self._meow_battle_timer = time_module.time()
        self.on_meow_search_start()

        self.run_auto_search()

        self.handle_after_auto_search()

        # 结束短猫搜索计时
        self.on_meow_search_end()

        self.config.check_task_switch()
        
    def os_meowfficer_farming(self):
        """执行大世界短猫相接（猫箱搜寻）任务。"""
        logger.hr(f'OS meowfficer farming, hazard_level={self.config.OpsiMeowfficerFarming_HazardLevel}', level=1)
        
        # ===== 前置检查：黄币状态 =====
        if self.is_cl1_enabled:
            return_threshold, _ = self._get_operation_coins_return_threshold()
            if return_threshold is None:
                logger.info('凭证返回阈值为 0，禁用黄币检查')
            elif self._check_yellow_coins_and_return_to_cl1("任务开始前", "短猫相接"):
                return
        
        # ===== 行动力保留配置 =====
        if self.is_cl1_enabled and self.config.OpsiMeowfficerFarming_ActionPointPreserve < 500:
            logger.info('启用侵蚀 1 练级时，最低行动力保留自动调整为 500')
            self.config.OpsiMeowfficerFarming_ActionPointPreserve = 500
        
        preserve = min(self.get_action_point_limit(self.config.OpsiMeowfficerFarming_APPreserveUntilReset),
                       self.config.OpsiMeowfficerFarming_ActionPointPreserve)
        if preserve == 0:
            self.config.override(OpsiFleet_Submarine=False)
            
        if self.is_cl1_enabled:
            # 侵蚀 1 练级模式下的必要覆盖项
            self.config.override(
                OpsiGeneral_DoRandomMapEvent=True,
                OpsiGeneral_AkashiShopFilter='ActionPoint',
                OpsiFleet_Submarine=False,
            )
            cd = self.nearest_task_cooling_down
            logger.attr('最近冷却中的任务', cd)
            
            remain = get_os_reset_remain()
            if cd is not None and remain > 0:
                logger.info(f'存在冷却中的任务，延迟短猫任务至 {cd.next_run} 后执行')
                self.config.task_delay(target=cd.next_run)
                self.config.task_stop()
                
        if self.is_in_opsi_explore():
            logger.warning(f'大世界探索正在运行，无法执行 {self.config.task.command}')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        ap_checked = False
        while True:
            ap_checked = self._meow_ap_and_scheduling_check(preserve, ap_checked)

            # ===== 塞壬探测装置搜索准备 =====
            siren_search_enabled = self.config.OpsiMeowfficerFarming_SirenDetectorSearch_Enable
            logger.info(f'探测装置搜索模式状态: {siren_search_enabled}')
            if siren_search_enabled:
                # 强制在搜索期间忽略已开启的指定海域计划作战，但不修改实际配置
                if not getattr(self, '_siren_search_ignore_stay_in_zone', False):
                    self._siren_search_ignore_stay_in_zone = True
                    if self.config.OpsiMeowfficerFarming_StayInZone:
                        logger.info('探测装置搜索模式：临时忽略指定海域计划作战（不修改配置）')

            # ===== 传统目标海域模式 =====
            if not siren_search_enabled and self.config.OpsiMeowfficerFarming_TargetZone != 0 and not self.config.OpsiMeowfficerFarming_StayInZone:
                self._meow_handle_traditional_zone()
                continue

            # ===== 指定海域计划作战 (StayInZone) =====
            if self.config.OpsiMeowfficerFarming_StayInZone and not siren_search_enabled:
                if self._meow_handle_stay_in_zone():
                    return
                continue

            # ===== 塞壬探测装置搜索 / 普通短猫搜索主逻辑 =====
            if siren_search_enabled:
                if not self._meow_handle_siren_detector_search():
                    # 未找到符合条件的海域，执行普通短猫搜索
                    logger.info('探测装置搜索未找到目标海域，切换到普通短猫搜索')
                    self._meow_handle_normal_search()
                else:
                    # 找到装置，移除忽略标记并保持配置不变
                    if getattr(self, '_siren_search_ignore_stay_in_zone', False):
                        try:
                            delattr(self, '_siren_search_ignore_stay_in_zone')
                        except Exception:
                            pass
                        logger.info('探测装置搜索完成：恢复指定海域计划作战（配置未被关闭）')
            else:
                self._meow_handle_normal_search()
            
            # ===== 循环中黄币充足检查 =====
            if self._check_yellow_coins_and_return_to_cl1("循环中"):
                return
            continue
