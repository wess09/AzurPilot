
from datetime import datetime, timedelta

from module.equipment.assets import EQUIPMENT_OPEN
from module.exception import ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.notify import handle_notify as notify_handle_notify
from module.os.assets import FLEET_FLAGSHIP
from module.os.map import OSMap
from module.os.ship_exp import ship_info_get_level_exp
from module.os.ship_exp_data import LIST_SHIP_EXP
from module.os_handler.action_point import ActionPointLimit


class OpsiHazard1Leveling(OSMap):
    def notify_push(self, title, content):
        """
        发送推送通知（智能调度功能）
        
        Args:
            title (str): 通知标题（会自动添加实例名称前缀）
            content (str): 通知内容
            
        Notes:
            - 仅在启用智能调度时生效
            - 需要在配置中设置 Error_OnePushConfig 才能发送推送
            - 使用 onepush 库发送通知到配置的推送渠道
            - 标题会自动格式化为 "[Alas <实例名>] 原标题" 的形式
        """
        # 检查是否启用智能调度
        if not self.config.OpsiScheduling_EnableSmartScheduling:
            return
        # 检查是否启用推送大世界相关邮件
        if not self.config.OpsiGeneral_NotifyOpsiMail:
            return
            
        # 检查是否配置了推送
        # 默认值是 'provider: null'，需要检查 provider 是否有效
        push_config = self.config.Error_OnePushConfig
        if not push_config or 'provider: null' in push_config or 'provider:null' in push_config:
            logger.warning("推送配置未设置或 provider 为 null，跳过推送。请在 Alas 设置 -> 错误处理 -> OnePush 配置中设置有效的推送渠道。")
            return
        
        # 获取实例名称并格式化标题
        instance_name = getattr(self.config, 'config_name', 'Alas')
        # 如果标题已经包含 [Alas]，替换为带实例名的版本
        if title.startswith('[Alas]'):
            formatted_title = f"[Alas <{instance_name}>]{title[6:]}"
        else:
            formatted_title = f"[Alas <{instance_name}>] {title}"
            
        try:
            success = notify_handle_notify(
                self.config.Error_OnePushConfig,
                title=formatted_title,
                content=content
            )
            if success:
                logger.info(f"✓ 推送通知成功: {formatted_title}")
            else:
                logger.warning(f"✗ 推送通知失败: {formatted_title}")
        except Exception as e:
            logger.error(f"推送通知异常: {e}")

    def check_and_notify_action_point_threshold(self):
        """
        检查行动力是否跨越阈值并发送推送通知
        
        应在每次执行 action_point_set() 后调用此方法
        
        功能说明:
            1. 从配置中读取阈值列表（如 500, 1000, 2000, 3000）
            2. 判断当前行动力所在的阈值区间
            3. 如果跨越了新的阈值区间，发送推送通知
            4. 记录上次通知的阈值，避免重复推送
            
        示例:
            - 行动力从 400 升至 600，会推送"升至500+"
            - 行动力从 1200 降至 900，会推送"降至1000以下"
        """
        # 检查是否启用智能调度
        if not getattr(self.config, 'OpsiScheduling_EnableSmartScheduling', False):
            return
                    
        # 获取当前行动力总量
        current_ap = self._action_point_total
        
        # 解析配置的阈值列表
        try:
            levels_str = getattr(self.config, 'OpsiScheduling_ActionPointNotifyLevels', '500, 1000, 2000, 3000')
            thresholds = [int(x.strip()) for x in levels_str.split(',')]
        except Exception as e:
            logger.warning(f"解析行动力阈值配置失败: {e}")
            return
        
        # 确定当前所在的阈值区间
        # 从高到低遍历阈值，找到第一个小于等于当前行动力的阈值
        current_threshold = None
        for threshold in sorted(thresholds, reverse=True):
            if current_ap >= threshold:
                current_threshold = threshold
                break

        # 查询是否为首次调用
        if not hasattr(self, '_last_notified_ap_threshold'):
            # 更新上次通知的阈值记录
            self._last_notified_ap_threshold = current_threshold
            return
        
        # 如果跨越了阈值区间，发送推送通知
        if current_threshold != self._last_notified_ap_threshold:
            if current_threshold is not None:
                # 判断是升至还是降至该阈值
                if self._last_notified_ap_threshold is None:
                    direction = "升至"
                elif self._last_notified_ap_threshold < current_threshold:
                    # 行动力增加，升至更高阈值
                    direction = "升至"
                else:
                    # 行动力减少，降至较低阈值
                    direction = "降至"
                
                self.notify_push(
                    title="[Alas] 行动力阈值变化",
                    content=f"行动力{direction}{current_threshold}+ (当前: {current_ap})"
                )
            else:
                # 降到最低阈值以下
                lowest = min(thresholds)
                self.notify_push(
                    title="[Alas] 行动力阈值变化", 
                    content=f"行动力降至{lowest}以下 (当前: {current_ap})"
                )
            # 更新上次通知的阈值记录
            self._last_notified_ap_threshold = current_threshold

    def os_hazard1_leveling(self):
        logger.hr('OS hazard 1 leveling', level=1)
        # Without these enabled, CL1 gains 0 profits
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
        )
        #if not self.config.is_task_enabled('OpsiMeowfficerFarming'):
        #    self.config.cross_set(keys='OpsiMeowfficerFarming.Scheduler.Enable', value=True)
        while True:
            try:
                self.config.OS_ACTION_POINT_PRESERVE = int(self.config.cross_get(
                    keys='OpsiHazard1Leveling.OpsiHazard1Leveling.MinimumActionPointReserve',
                    default=200
                ))
            except Exception:
                self.config.OS_ACTION_POINT_PRESERVE = 200
            if self.config.is_task_enabled('OpsiAshBeacon') \
                    and not self._ash_fully_collected \
                    and self.config.OpsiAshBeacon_EnsureFullyCollected:
                logger.info('Ash beacon not fully collected, ignore action point limit temporarily')
                self.config.OS_ACTION_POINT_PRESERVE = 0
            logger.attr('OS_ACTION_POINT_PRESERVE', self.config.OS_ACTION_POINT_PRESERVE)


            # ===== 智能调度: 黄币检查与任务切换 =====
            # 检查黄币是否低于保留值
            yellow_coins = self.get_yellow_coins()
            if self.config.OpsiScheduling_EnableSmartScheduling:
                # 启用了智能调度
                if yellow_coins < self.config.OpsiHazard1Leveling_OperationCoinsPreserve:
                    logger.info(f'【智能调度】黄币不足 ({yellow_coins} < {self.config.OpsiHazard1Leveling_OperationCoinsPreserve}), 需要执行短猫相接')

                    # 先获取当前行动力数据（包含箱子里的行动力）
                    # 需要先进入行动力界面才能读取数据
                    self.action_point_enter()
                    self.action_point_safe_get()
                    self.action_point_quit()

                    # 使用 cross_get 读取短猫相接任务的行动力保留值（而非当前任务的配置）
                    meow_ap_preserve = int(self.config.cross_get(
                        keys='OpsiMeowfficerFarming.OpsiMeowfficerFarming.ActionPointPreserve',
                        default=1000
                    ))

                    # 检查行动力是否足够执行短猫相接
                    _previous_coins_ap_insufficient = getattr(self.config, 'OpsiHazard1_PreviousCoinsApInsufficient', False)
                    if self._action_point_total < meow_ap_preserve:
                        # 行动力也不足，推迟并推送通知
                        logger.warning(f'行动力不足以执行短猫 ({self._action_point_total} < {meow_ap_preserve})')

                        if _previous_coins_ap_insufficient == False:
                            _previous_coins_ap_insufficient = True
                            self.notify_push(
                                title="[Alas] 侵蚀1 - 黄币与行动力双重不足",
                                content=f"黄币 {yellow_coins} 低于保留值 {self.config.OpsiHazard1Leveling_OperationCoinsPreserve}\n行动力 {self._action_point_total} 不足 (需要 {meow_ap_preserve})\n推迟任务"
                            )
                        else:
                            logger.info('上次检查行动力不足，跳过推送邮件')

                        logger.info('推迟侵蚀1任务1小时')
                        self.config.task_delay(minute=60)
                        self.config.task_stop()
                    else:
                        # 行动力充足，切换到黄币补充任务获取黄币
                        logger.info(f'行动力充足 ({self._action_point_total}), 切换到黄币补充任务获取黄币')
                        _previous_coins_ap_insufficient = False
                        
                        # 检查黄币阈值适用范围配置
                        # 如果关闭，只启用短猫相接；如果开启，启用所有黄币补充任务
                        apply_to_all = self.config.cross_get(
                            keys='OpsiHazard1Leveling.OpsiScheduling.OperationCoinsReturnThresholdApplyToAllCoinTasks',
                            default=None
                        )
                        # 如果cross_get返回None，尝试直接属性访问
                        if apply_to_all is None:
                            if hasattr(self.config, 'OpsiScheduling_OperationCoinsReturnThresholdApplyToAllCoinTasks'):
                                apply_to_all = self.config.OpsiScheduling_OperationCoinsReturnThresholdApplyToAllCoinTasks
                            else:
                                # 如果属性也不存在，使用默认值True
                                apply_to_all = True
                        logger.info(f'【智能调度】黄币阈值适用范围配置读取: {apply_to_all}')
                        
                        task_names = {
                            'OpsiMeowfficerFarming': '短猫相接',
                            'OpsiObscure': '隐秘海域',
                            'OpsiAbyssal': '深渊海域',
                            'OpsiStronghold': '塞壬要塞'
                        }
                        
                        # 根据配置决定启用哪些任务
                        if apply_to_all:
                            # 开启：启用所有黄币补充任务（短猫、隐秘海域、深渊海域、塞壬要塞）
                            all_coin_tasks = ['OpsiMeowfficerFarming', 'OpsiObscure', 'OpsiAbyssal', 'OpsiStronghold']
                            logger.info('黄币阈值适用范围：四任务，将启用所有黄币补充任务')
                        else:
                            # 关闭：仅启用短猫相接
                            all_coin_tasks = ['OpsiMeowfficerFarming']
                            logger.info('黄币阈值适用范围：仅短猫，将只启用短猫相接任务')
                        
                        # 自动启用黄币补充任务的调度器
                        enabled_tasks = []
                        auto_enabled_tasks = []
                        with self.config.multi_set():
                            for task in all_coin_tasks:
                                if self.config.is_task_enabled(task):
                                    enabled_tasks.append(task)
                                    logger.info(f'黄币补充任务已启用: {task_names.get(task, task)}')
                                else:
                                    # 自动启用未启用的任务
                                    logger.info(f'自动启用黄币补充任务: {task_names.get(task, task)}')
                                    self.config.cross_set(keys=f'{task}.Scheduler.Enable', value=True)
                                    auto_enabled_tasks.append(task)
                        
                        # 合并所有任务（已启用 + 自动启用）
                        available_tasks = enabled_tasks + auto_enabled_tasks
                        
                        if auto_enabled_tasks:
                            auto_enabled_names = '、'.join([task_names.get(task, task) for task in auto_enabled_tasks])
                            logger.info(f'已自动启用以下黄币补充任务: {auto_enabled_names}')
                        
                        if not available_tasks:
                            # 理论上不应该到达这里，因为我们已经自动启用了所有任务
                            logger.error('无法启用任何黄币补充任务，这是一个错误状态')
                            self.config.task_delay(minute=60)
                            self.config.task_stop()
                            self.config.OpsiHazard1_PreviousCoinsApInsufficient = _previous_coins_ap_insufficient
                            return
                        
                        task_names_str = '、'.join([task_names.get(task, task) for task in available_tasks])
                        self.notify_push(
                            title="[Alas] 侵蚀1 - 切换至黄币补充任务",
                            content=f"黄币 {yellow_coins} 低于保留值 {self.config.OpsiHazard1Leveling_OperationCoinsPreserve}\n行动力: {self._action_point_total} (需要 {meow_ap_preserve})\n切换至{task_names_str}获取黄币"
                        )

                        with self.config.multi_set():
                            # 启用所有可用的黄币补充任务
                            for task in available_tasks:
                                self.config.task_call(task)
                            
                            cd = self.nearest_task_cooling_down
                            if cd is not None:
                                # 有冷却任务时，同时延迟侵蚀1任务到冷却任务之后
                                # 避免侵蚀1在黄币补充任务被延迟后立即再次运行导致无限循环
                                logger.info(f'有冷却任务 {cd.command}，延迟侵蚀1到 {cd.next_run}')
                                self.config.task_delay(target=cd.next_run)
                        self.config.task_stop()
                    self.config.OpsiHazard1_PreviousCoinsApInsufficient = _previous_coins_ap_insufficient
            else:
                # 未启用智能调度，保持原有逻辑
                if yellow_coins < self.config.OpsiHazard1Leveling_OperationCoinsPreserve:
                    logger.info(f'Reach the limit of yellow coins, preserve={self.config.OpsiHazard1Leveling_OperationCoinsPreserve}')
                    with self.config.multi_set():
                        self.config.task_delay(server_update=True)
                        if not self.is_in_opsi_explore():
                            cd = self.nearest_task_cooling_down
                            if cd is None:
                                for task in ['OpsiAbyssal', 'OpsiStronghold', 'OpsiObscure', 'OpsiMeowfficerFarming']:
                                    if self.config.is_task_enabled(task):
                                        self.config.task_call(task)
                    self.config.task_stop()

            # 获取当前区域
            self.get_current_zone()

            # Preset action point to 70
            # When running CL1 oil is for running CL1, not meowfficer farming
            keep_current_ap = True
            if self.config.OpsiGeneral_BuyActionPointLimit > 0:
                keep_current_ap = False
            self.action_point_set(cost=120, keep_current_ap=keep_current_ap, check_rest_ap=True)

            # ===== 智能调度: 行动力阈值推送检查 =====
            # 在设置行动力后检查是否跨越阈值并推送通知
            self.check_and_notify_action_point_threshold()

            # ===== 智能调度: 最低行动力保留检查 =====
            # 检查当前行动力是否低于最低保留值
            if getattr(self.config, 'OpsiScheduling_EnableSmartScheduling', False):
                min_reserve = self.config.OpsiHazard1Leveling_MinimumActionPointReserve
                if self._action_point_total < min_reserve:
                    logger.warning(f'【智能调度】行动力低于最低保留 ({self._action_point_total} < {min_reserve})')

                    _previous_ap_insufficient = getattr(self.config, 'OpsiHazard1_PreviousApInsufficient', False)
                    if _previous_ap_insufficient == False:
                        _previous_ap_insufficient = True
                        self.notify_push(
                            title="[Alas] 侵蚀1 - 行动力低于最低保留",
                            content=f"当前行动力 {self._action_point_total} 低于最低保留 {min_reserve}，推迟任务"
                        )
                    else:
                        logger.info('上次检查行动力低于最低保留，跳过推送邮件')

                    logger.info('推迟侵蚀1任务1小时')
                    self.config.task_delay(minute=60)
                    self.config.task_stop()
                else:
                    _previous_ap_insufficient = False
                self.config.OpsiHazard1_PreviousApInsufficient = _previous_ap_insufficient

            if self.config.OpsiHazard1Leveling_TargetZone != 0:
                zone = self.config.OpsiHazard1Leveling_TargetZone
            else:
                zone = 22
            logger.hr(f'OS hazard 1 leveling, zone_id={zone}', level=1)
            if self.zone.zone_id != zone or not self.is_zone_name_hidden:
                self.globe_goto(self.name_to_zone(zone), types='SAFE', refresh=True)
            self.fleet_set(self.config.OpsiFleet_Fleet)
            search_completed = self.run_strategic_search()

            # 只有战略搜索正常完成时才执行重扫（被中断时不执行）
            # [Antigravity Fix] 即使 search_completed 为 False ()，
            # 也尝试后续的重扫和定点巡逻，以确保任务不被跳过。
            if True: 
                if not search_completed and search_completed is not None:
                    # search_completed could be None if run_strategic_search returns nothing (though it returns bool)
                     logger.warning("Strategic search returned False, but proceeding with rescan/patrol anyway.")

                # ===== 第一次重扫：战略搜索后的完整镜头重扫 =====
                self._solved_map_event = set()
                self._solved_fleet_mechanism = False
                self.clear_question()
                self.map_rescan()

                # ===== 舰队移动搜索（如果启用且没有发现事件）=====
                if self.config.OpsiHazard1Leveling_ExecuteFixedPatrolScan:
                    exec_fixed = getattr(self.config, 'OpsiHazard1Leveling_ExecuteFixedPatrolScan', False)
                    # 只有在第一次重扫没有发现事件时才执行舰队移动
                    if exec_fixed and not self._solved_map_event:
                        self._execute_fixed_patrol_scan(ExecuteFixedPatrolScan=True)
                        # ===== 第二次重扫：舰队移动后再次重扫 =====
                        self._solved_map_event = set()
                        self.clear_question()
                        self.map_rescan()

            self.handle_after_auto_search()
            solved_events = getattr(self, '_solved_map_event', set())
            if 'is_akashi' in solved_events:
                try:
                    from datetime import datetime
                    key = f"{datetime.now():%Y-%m}-akashi"
                    data = self._load_cl1_monthly()
                    data[key] = int(data.get(key, 0)) + 1
                    self._save_cl1_monthly(data)
                    logger.attr('cl1_akashi_monthly', data[key])
                except Exception:
                    logger.exception('Failed to persist CL1 akashi monthly count')


            # 每次循环结束后提交CL1数据
            try:
                # 检查遥测上报开关
                if not getattr(self.config, 'DropRecord_TelemetryReport', True):
                    logger.info('Telemetry report disabled by config')
                else:
                    from module.statistics.cl1_data_submitter import get_cl1_submitter
                    # 获取当前实例名称，确保使用正确的数据文件路径
                    instance_name = self.config.config_name if hasattr(self.config, 'config_name') else None
                    submitter = get_cl1_submitter(instance_name=instance_name)
                    # 不检查时间间隔,每次循环都提交
                    raw_data = submitter.collect_data()
                    if raw_data.get('battle_count', 0) > 0:
                        metrics = submitter.calculate_metrics(raw_data)
                        submitter.submit_data(metrics)
                        logger.info(f'CL1 data submission queued for instance: {instance_name}')
            except Exception as e:
                logger.debug(f'CL1 data submission failed: {e}')

            self.config.check_task_switch()

    def os_check_leveling(self):
        logger.hr('OS check leveling', level=1)
        logger.attr('OpsiCheckLeveling_LastRun', self.config.OpsiCheckLeveling_LastRun)
        time_run = self.config.OpsiCheckLeveling_LastRun + timedelta(days=1)
        logger.info(f'Task OpsiCheckLeveling run time is {time_run}')
        if datetime.now().replace(microsecond=0) < time_run:
            logger.info('Not running time, skip')
            return
        target_level = self.config.OpsiCheckLeveling_TargetLevel
        if not isinstance(target_level, int) or target_level < 0 or target_level > 125:
            logger.error(f'Invalid target level: {target_level}, must be an integer between 0 and 125')
            raise ScriptError(f'Invalid opsi ship target level: {target_level}')
        if target_level == 0:
            logger.info('Target level is 0, skip')
            return

        logger.attr('Fleet to check', self.config.OpsiFleet_Fleet)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.equip_enter(FLEET_FLAGSHIP)
        all_full_exp = True
        
        # 收集所有舰船数据
        ship_data_list = []
        position = 1

        while 1:
            self.device.screenshot()
            level, exp = ship_info_get_level_exp(main=self)
            total_exp = LIST_SHIP_EXP[level - 1] + exp
            logger.info(f'Position: {position}, Level: {level}, Exp: {exp}, Total Exp: {total_exp}, Target Exp: {LIST_SHIP_EXP[target_level - 1]}')
            
            # 保存舰船数据
            ship_data_list.append({
                'position': position,
                'level': level,
                'current_exp': exp,
                'total_exp': total_exp
            })
            
            if total_exp < LIST_SHIP_EXP[target_level - 1]:
                all_full_exp = False
            
            if not self.equip_view_next():
                break
            position += 1

        # 保存所有舰船数据到JSON
        try:
            from module.statistics.ship_exp_stats import save_ship_exp_data
            from module.statistics.opsi_month import get_opsi_stats
            
            # 获取当前实例名称
            instance_name = self.config.config_name if hasattr(self.config, 'config_name') else None
            
            # 使用实例名获取战绩，确保战斗场次正确
            current_battles = get_opsi_stats(instance_name=instance_name).summary().get('total_battles', 0)
            
            save_ship_exp_data(
                ships=ship_data_list,
                target_level=target_level,
                fleet_index=self.config.OpsiFleet_Fleet,
                battle_count_at_check=current_battles,
                instance_name=instance_name  # 指定实例名称保存数据
            )
        except Exception as e:
            logger.warning(f'Failed to save ship exp data: {e}')

        if all_full_exp:
            logger.info(f'All ships in fleet {self.config.OpsiFleet_Fleet} are full exp, '
                        f'level {target_level} or above')
            self.notify_push(
                title=f"check leveling passed",
                content=f"<{self.config.config_name}> {self.config.task} reached level limit {target_level} or above."
            )
        self.ui_back(appear_button=EQUIPMENT_OPEN, check_button=self.is_in_map)
        self.config.OpsiCheckLeveling_LastRun = datetime.now().replace(microsecond=0)
        if all_full_exp and self.config.OpsiCheckLeveling_DelayAfterFull:
            logger.info('Delay task after all ships are full exp')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
