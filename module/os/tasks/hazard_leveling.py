from datetime import datetime, timedelta
from calendar import monthrange

from module.base.timer import Timer
from module.equipment.assets import EQUIPMENT_OPEN
from module.exception import MapDetectionError, ScriptError
from module.logger import logger
from module.os.assets import FLEET_FLAGSHIP
from module.os.map import OSMap
from module.os.ship_exp import ship_info_get_level_exp
from module.os.ship_exp_data import LIST_SHIP_EXP
from module.os.tasks.smart_scheduling_utils import is_smart_scheduling_enabled
from module.os.tasks.scheduling import CoinTaskMixin
from module.statistics.opsi_runtime import record_cl1_akashi_encounter
from module.os.sea_miles_ocr import OCR_SEA_MILES_DIGIT
from module.os_handler.assets import MISSION_ENTER, MISSION_CHECK, MISSION_QUIT


class OpsiHazard1Leveling(CoinTaskMixin, OSMap):
    def _calculate_virtual_asset(self, action_points, yellow_coins):
        """
        计算虚拟资产值。
        
        虚拟资产 = 体力 × (1700/30) + 黄币 + (到月底时间/10分钟) × (1700/30)
        """
        cl5_efficiency = 1700.0 / 30.0
        
        # 获取当前时间
        now = datetime.now()
        
        # 计算该月底24时的时间戳
        year, month = now.year, now.month
        last_day = monthrange(year, month)[1]
        month_end = datetime(year, month, last_day, 23, 59, 59)
        
        # 计算到月底的剩余时间（秒）
        time_to_month_end_sec = (month_end - now).total_seconds()
        
        # 虚拟资产 = 体力 × CL5_efficiency + 黄币 + (到月底时间/10分钟) × CL5_efficiency
        # 其中 10分钟 = 600秒
        virtual_asset_from_time = (time_to_month_end_sec / 600.0) * cl5_efficiency
        virtual_asset = action_points * cl5_efficiency + yellow_coins + virtual_asset_from_time
        
        return virtual_asset

    def _cl1_smart_scheduling_check(self, yellow_coins):
        """处理智能调度中的黄币检查与任务切换"""
        # 获取虚拟资产保留值配置（与智能调度双向同步）
        virtual_asset_preserve = self._get_virtual_asset_preserve()
        
        if not is_smart_scheduling_enabled(self.config):
            # 未启用智能调度时，凭证不足则推迟任务
            cl1_preserve = self.config.OpsiHazard1Leveling_OperationCoinsPreserve
            if yellow_coins < cl1_preserve:
                logger.info(
                    f"[智能调度] 作战补给凭证不足 ({yellow_coins} < {cl1_preserve})，推迟侵蚀 1 任务至次日"
                )
                self.config.task_delay(server_update=True)
                self.config.task_stop()
            
            # 检查虚拟资产保留值（如果配置了）
            if virtual_asset_preserve > 0:
                self.action_point_enter()
                self.action_point_safe_get()
                self.action_point_quit()
                
                virtual_asset = self._calculate_virtual_asset(self._action_point_total, yellow_coins)
                if virtual_asset < virtual_asset_preserve:
                    logger.info(
                        f"[虚拟资产] 虚拟资产不足 ({virtual_asset:.0f} < {virtual_asset_preserve})，推迟侵蚀 1 任务至次日"
                    )
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
            return

        # 优先使用智能调度的黄币保留值
        if hasattr(self, "_get_smart_scheduling_operation_coins_preserve"):
            cl1_preserve = self._get_smart_scheduling_operation_coins_preserve()
        else:
            cl1_preserve = self.config.OpsiHazard1Leveling_OperationCoinsPreserve

        # 进入行动力界面读取当前行动力数据
        self.action_point_enter()
        self.action_point_safe_get()
        self.action_point_quit()
        
        # 计算虚拟资产
        virtual_asset = self._calculate_virtual_asset(self._action_point_total, yellow_coins) if virtual_asset_preserve > 0 else 0
        
        if virtual_asset_preserve > 0 and virtual_asset < virtual_asset_preserve:
            logger.info(
                f"[虚拟资产] 虚拟资产不足 ({virtual_asset:.0f} < {virtual_asset_preserve})，需要获取凭证"
            )
        elif yellow_coins < cl1_preserve:
            logger.info(
                f"[智能调度] 作战补给凭证不足 ({yellow_coins} < {cl1_preserve})，需要获取凭证"
            )
        else:
            return

        # 读取短猫相接任务的行动力保留值
        meow_ap_preserve = int(
            self.config.cross_get(
                keys="OpsiMeowfficerFarming.OpsiMeowfficerFarming.ActionPointPreserve",
                default=1000,
            )
        )

        # 覆盖为智能调度的行动力保留值
        if hasattr(self, "_get_smart_scheduling_action_point_preserve"):
            smart_ap_preserve = self._get_smart_scheduling_action_point_preserve()
            if smart_ap_preserve > 0:
                meow_ap_preserve = smart_ap_preserve

        # 检查行动力是否足以执行补充任务
        _previous_coins_ap_insufficient = getattr(
            self.config, "OpsiHazard1_PreviousCoinsApInsufficient", False
        )
        if self._action_point_total < meow_ap_preserve:
            logger.warning(
                f"行动力不足以执行短猫 ({self._action_point_total} < {meow_ap_preserve})"
            )

            if not _previous_coins_ap_insufficient:
                _previous_coins_ap_insufficient = True
                notify_content = f"作战补给凭证 {yellow_coins} 低于保留值 {cl1_preserve}\n行动力 {self._action_point_total} 不足 (需要 {meow_ap_preserve})\n任务已推迟"
                self.notify_push(
                    title="[Alas] 智能调度 - 警告",
                    content=notify_content,
                )
            else:
                logger.info("上次检查行动力不足，跳过推送通知")

            logger.info("推迟任务 50 分钟")
            self.config.task_delay(minute=50)
            self.config.OpsiHazard1_PreviousCoinsApInsufficient = (
                _previous_coins_ap_insufficient
            )
            self.config.task_stop()
        else:
            # 行动力充足，切换到预设计的补充任务
            logger.info(
                f"[智能调度] 行动力充足 ({self._action_point_total})，开始执行补充任务"
            )
            _previous_coins_ap_insufficient = False

            task_enable_config = {
                "OpsiMeowfficerFarming": self.config.cross_get(
                    keys="OpsiScheduling.OpsiScheduling.EnableMeowfficerFarming",
                    default=True,
                ),
                "OpsiObscure": self.config.cross_get(
                    keys="OpsiScheduling.OpsiScheduling.EnableObscure",
                    default=False,
                ),
                "OpsiAbyssal": self.config.cross_get(
                    keys="OpsiScheduling.OpsiScheduling.EnableAbyssal",
                    default=False,
                ),
                "OpsiStronghold": self.config.cross_get(
                    keys="OpsiScheduling.OpsiScheduling.EnableStronghold",
                    default=False,
                ),
            }

            task_names = {
                "OpsiMeowfficerFarming": "短猫相接",
                "OpsiObscure": "隐秘海域",
                "OpsiAbyssal": "深渊海域",
                "OpsiStronghold": "塞壬要塞",
            }

            all_coin_tasks = [
                task for task, enabled in task_enable_config.items() if enabled
            ]
            if not all_coin_tasks:
                logger.warning(
                    "[智能调度] 未启用任何作战补给凭证补充任务，将执行短猫相接"
                )
                all_coin_tasks = ["OpsiMeowfficerFarming"]

            enabled_names = "、".join(
                [task_names.get(task, task) for task in all_coin_tasks]
            )
            logger.info(f"[智能调度] 启用的补充任务: {enabled_names}")

            enabled_tasks = []
            auto_enabled_tasks = []
            with self.config.multi_set():
                for task in all_coin_tasks:
                    if self.config.is_task_enabled(task):
                        enabled_tasks.append(task)
                        logger.info(
                            f"[智能调度] 凭证补充已启用: {task_names.get(task, task)}"
                        )
                    else:
                        logger.info(
                            f"[智能调度] 自动启用补充任务: {task_names.get(task, task)}"
                        )
                        self.config.cross_set(
                            keys=f"{task}.Scheduler.Enable", value=True
                        )
                        auto_enabled_tasks.append(task)

            available_tasks = enabled_tasks + auto_enabled_tasks
            if auto_enabled_tasks:
                auto_enabled_names = "、".join(
                    [task_names.get(task, task) for task in auto_enabled_tasks]
                )
                logger.info(
                    f"[智能调度] 已自动启用以下补充任务: {auto_enabled_names}"
                )

            if not available_tasks:
                logger.error("[智能调度] 无法启用任何补充任务，处于异常状态")
                self.config.task_delay(minute=60)
                self.config.OpsiHazard1_PreviousCoinsApInsufficient = (
                    _previous_coins_ap_insufficient
                )
                self.config.task_stop()
                return

            task_names_str = "、".join(
                [task_names.get(task, task) for task in available_tasks]
            )
            notify_content = f"作战补给凭证 {yellow_coins} 低于保留值 {cl1_preserve}\n行动力: {self._action_point_total} (需要 {meow_ap_preserve})\n切换至 {task_names_str} 获取凭证"
            if virtual_asset_preserve > 0:
                notify_content += f"\n虚拟资产: {virtual_asset:.0f} (保留值 {virtual_asset_preserve})"
            self.notify_push(
                title="[Alas info] 智能调度 - 切换至凭证补充任务",
                content=notify_content,
            )

            with self.config.multi_set():
                for task in available_tasks:
                    self.config.task_call(task)

                cd = self.nearest_task_cooling_down
                if cd is not None:
                    logger.info(
                        f"[智能调度] 检测到冷却中的任务 {cd.command}，延迟侵蚀 1 任务至 {cd.next_run}"
                    )
                    self.config.task_delay(target=cd.next_run)
            self.config.task_stop()
        self.config.OpsiHazard1_PreviousCoinsApInsufficient = (
            _previous_coins_ap_insufficient
        )

    def _cl1_ap_check(self):
        """最低行动力保留检查"""
        self.action_point_enter()
        self.action_point_safe_get()
        self.action_point_quit()

        min_reserve = self.config.OS_ACTION_POINT_PRESERVE
        if self._action_point_total < min_reserve:
            logger.warning(
                f"[智能调度] 行动力低于最低保留 ({self._action_point_total} < {min_reserve})"
            )

            _previous_ap_insufficient = getattr(
                self.config, "OpsiHazard1_PreviousApInsufficient", False
            )
            if not _previous_ap_insufficient:
                _previous_ap_insufficient = True
                self.notify_push(
                    title="[Alas info] 智能调度 - 行动力低于最低保留",
                    content=f"当前行动力 {self._action_point_total} 低于最低保留 {min_reserve}，已推迟任务",
                )
            else:
                logger.info("上次检查行动力低于最低保留，跳过推送通知")

            logger.info("[智能调度] 推迟侵蚀 1 任务 50 分钟")
            self.config.task_delay(minute=50)
            self.config.OpsiHazard1_PreviousApInsufficient = _previous_ap_insufficient
            self.config.task_stop()
        else:
            _previous_ap_insufficient = False
        self.config.OpsiHazard1_PreviousApInsufficient = _previous_ap_insufficient

    def _cl1_run_battle(self):
        """执行侵蚀 1 实际战斗逻辑"""
        if self.config.OpsiHazard1Leveling_TargetZone != 0:
            zone = self.config.OpsiHazard1Leveling_TargetZone
        else:
            zone = 22
        logger.hr(f"OS hazard 1 leveling, zone_id={zone}", level=1)
        if self.zone.zone_id != zone or not self.is_zone_name_hidden:
            self.globe_goto(self.name_to_zone(zone), types="SAFE", refresh=True)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        search_completed = self.run_strategic_search()

        if not search_completed and search_completed is not None:
            logger.warning("战略搜索返回 False，可能已被提前中断")

        # 第一次重扫：检查是否还有事件
        self._solved_map_event = set()
        self._solved_fleet_mechanism = False
        self.map_rescan()

        # 强制移动逻辑
        if self.config.OpsiHazard1Leveling_ExecuteFixedPatrolScan:
            if not self._solved_map_event:
                self._execute_fixed_patrol_scan(ExecuteFixedPatrolScan=True)
                # 第二次重扫：舰队移动后再次重扫
                self._solved_map_event = set()
                self.map_rescan()

        self.handle_after_auto_search()

        # 明石遭遇记录
        solved_events = getattr(self, "_solved_map_event", set())
        if "is_akashi" in solved_events:
            # Akashi encounter counting belongs with the other runtime metrics;
            # the task only reports that an Akashi event was solved.
            record_cl1_akashi_encounter(self.config)

    def _cl1_handle_telemetry(self):
        """处理遥测数据提交"""
        try:
            if not getattr(self.config, "DropRecord_TelemetryReport", True):
                logger.info("[错误] 遥测上报已关闭")
            else:

                def run_telemetry():
                    try:
                        from module.statistics.cl1_data_submitter import (
                            get_cl1_submitter,
                        )

                        instance_name = getattr(self.config, "config_name", None)
                        submitter = get_cl1_submitter(instance_name=instance_name)
                        raw_data = submitter.collect_data()
                        if raw_data.get("battle_count", 0) > 0:
                            metrics = submitter.calculate_metrics(raw_data)
                            submitter.submit_data(metrics)
                            logger.info(
                                f"侵蚀 1 数据提交已排队，实例名称: {instance_name}"
                            )
                    except Exception as e:
                        logger.debug(f"侵蚀 1 数据提交后台执行失败: {e}")

                from module.base.async_executor import async_executor

                async_executor.submit(run_telemetry)
        except Exception as e:
            logger.debug(f"侵蚀 1 数据提交触发失败: {e}")

    def os_hazard1_leveling(self):
        """执行大世界侵蚀 1 练级任务。"""
        logger.hr("OS hazard 1 leveling", level=1)

        # 启用随机事件以获得收益
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
        )

        while True:
            # 读取行动力保留值
            self.config.OS_ACTION_POINT_PRESERVE = int(
                getattr(
                    self.config, "OpsiHazard1Leveling_MinimumActionPointReserve", 200
                )
            )

            if (
                self.config.is_task_enabled("OpsiAshBeacon")
                and not self._ash_fully_collected
                and self.config.OpsiAshBeacon_EnsureFullyCollected
            ):
                logger.info("余烬信标未收集满，暂时忽略行动力限制")
                self.config.OS_ACTION_POINT_PRESERVE = 0
            logger.attr(
                "OS_ACTION_POINT_PRESERVE", self.config.OS_ACTION_POINT_PRESERVE
            )

            # ===== 智能调度：黄币检查与任务切换 =====
            yellow_coins = self.get_yellow_coins()
            self._cl1_smart_scheduling_check(yellow_coins)

            # 获取当前区域
            try:
                self.get_current_zone()
            except MapDetectionError as e:
                logger.error("OS地图区域识别失败，请确保游戏已进入OS海域地图界面")
                logger.error(f"OCR识别错误: {e}")
                raise

            # 侵蚀 1 练级时，行动力优先用于此任务，而非短猫。
            keep_current_ap = True
            if self.config.OpsiGeneral_BuyActionPointLimit > 0:
                keep_current_ap = False
            self.action_point_set(
                cost=120, keep_current_ap=keep_current_ap, check_rest_ap=True
            )

            # ===== 智能调度：行动力阈值推送检查 =====
            self.check_and_notify_action_point_threshold()

            # ===== 最低行动力保留检查 =====
            self._cl1_ap_check()

            # ===== 执行侵蚀 1 实际战斗逻辑 =====
            self._cl1_run_battle()

            # ===== 处理遥测数据提交 =====
            self._cl1_handle_telemetry()

            self.config.check_task_switch()

    def os_check_leveling(self):
        """检查大世界阵容练级进度。"""
        logger.hr("OS check leveling", level=1)
        logger.attr("OpsiCheckLeveling_LastRun", self.config.OpsiCheckLeveling_LastRun)
        
        check_interval = self.config.OpsiCheckLeveling_CheckInterval
        if not isinstance(check_interval, int) or check_interval < 1:
            check_interval = 24
            logger.warning("检测间隔无效，使用默认值 24 小时")
        
        time_run = self.config.OpsiCheckLeveling_LastRun + timedelta(hours=check_interval)
        logger.info(f"练级检查下次运行时间: {time_run}")
        if datetime.now().replace(microsecond=0) < time_run:
            logger.info("未到运行时间，跳过")
            return
        target_level = self.config.OpsiCheckLeveling_TargetLevel
        if not isinstance(target_level, int) or target_level < 0 or target_level > 125:
            logger.error(f"目标等级无效: {target_level}，必须是 0 到 125 之间的整数")
            raise ScriptError(f"Invalid opsi ship target level: {target_level}")
        if target_level == 0:
            logger.info("目标等级为 0，跳过")
            return

        logger.attr("待检查舰队", self.config.OpsiFleet_Fleet)
        
        enable_custom_check = self.config.OpsiCheckLeveling_EnableCustomCheck
        custom_positions_value = self.config.OpsiCheckLeveling_CustomCheckPositions
        custom_positions_str = str(custom_positions_value) if custom_positions_value is not None else ''
        custom_positions = []
        if enable_custom_check and custom_positions_str.strip():
            try:
                custom_positions = [int(p.strip()) for p in custom_positions_str.split(',') if p.strip()]
                invalid_positions = [p for p in custom_positions if p < 1 or p > 6]
                if invalid_positions:
                    logger.warning(f"自定义舰位包含无效值: {invalid_positions}，有效范围为1-6，将检测所有舰船")
                    custom_positions = []
                else:
                    logger.info(f"自定义检测舰位: {custom_positions}")
            except (ValueError, AttributeError):
                logger.warning(f"自定义舰位格式错误: {custom_positions_str}，将检测所有舰船")
                custom_positions = []
        
        if not self._check_auto_change_prerequisite(enable_custom_check, custom_positions):
            logger.info("自动配队前置条件不满足，禁用自动配队")
            self.config.OpsiFleetAutoChange_Enable = False
        
        if enable_custom_check and custom_positions:
            ship_data_result = self._collect_custom_positions_data(target_level, custom_positions)
        else:
            ship_data_result = self._collect_ship_data_with_retry(target_level)
        
        if ship_data_result['ships'] is None:
            error_msg = ship_data_result['error'] or "未知错误"
            logger.error(f"舰船数据收集失败: {error_msg}")
            report = self._format_check_report(
                None, target_level, self.config.OpsiFleet_Fleet, error_msg=error_msg
            )
            self.notify_push(
                title="舰船经验检测失败",
                content=f"<{self.config.config_name}>\n\n{report}",
            )
            self.config.OpsiCheckLeveling_LastRun = datetime.now().replace(microsecond=0)
            logger.info("检测失败，下次检测时间设为24小时后")
            return
        
        ships = ship_data_result['ships']
        
        try:
            from module.statistics.ship_exp_stats import save_ship_exp_data
            from module.statistics.opsi_month import get_opsi_stats

            instance_name = (
                self.config.config_name if hasattr(self.config, "config_name") else None
            )

            current_battles = (
                get_opsi_stats(instance_name=instance_name)
                .summary()
                .get("total_battles", 0)
            )

            save_ship_exp_data(
                ships=ships,
                target_level=target_level,
                fleet_index=self.config.OpsiFleet_Fleet,
                battle_count_at_check=current_battles,
                instance_name=instance_name,
            )
        except Exception as e:
            logger.warning(f"保存舰船经验数据失败: {e}")

        report = self._format_check_report(
            ships, target_level, self.config.OpsiFleet_Fleet, custom_positions=custom_positions if enable_custom_check else None
        )
        self.notify_push(
            title="舰船经验检测报告",
            content=f"<{self.config.config_name}>\n\n{report}",
        )

        logger.info("开始海里数检测")
        try:
            sea_miles = self.detect_and_record_sea_miles()
            if sea_miles is not None:
                logger.info(f"海里数检测完成: {sea_miles}")
            else:
                logger.warning("海里数检测失败，但不影响后续流程")
        except Exception as e:
            logger.error(f"海里数检测异常: {e}，但不影响后续流程")

        if enable_custom_check and custom_positions:
            self._check_custom_positions_full_exp(
                ships, target_level, custom_positions
            )
        else:
            all_full_exp = all(
                ship['total_exp'] >= LIST_SHIP_EXP[target_level - 1]
                for ship in ships
            )
            if all_full_exp:
                logger.info(
                    f"舰队 {self.config.OpsiFleet_Fleet} 的所有舰船均已满经验（等级 {target_level} 或更高）"
                )
                self.notify_push(
                    title="练级检查通过",
                    content=f"<{self.config.config_name}> {self.config.task} 已达到等级限制 {target_level}。",
                )
                
                if self.config.OpsiFleetAutoChange_Enable:
                    logger.info("检测到自动配队已启用，开始执行自动配队")
                    try:
                        from module.os.tasks.fleet_auto_change import OpsiFleetAutoChange
                        auto_change = OpsiFleetAutoChange(config=self.config, device=self.device)
                        auto_change.run()
                        logger.info("自动配队执行完成")
                    except Exception as e:
                        logger.error(f"自动配队执行失败: {e}")
                
                if self.config.OpsiCheckLeveling_DelayAfterFull:
                    logger.info("所有舰船满经验后延迟任务")
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
        
        self.config.OpsiCheckLeveling_LastRun = datetime.now().replace(microsecond=0)

    def _check_auto_change_prerequisite(self, enable_custom_check, custom_positions):
        """
        检查自动配队前置条件
        
        Args:
            enable_custom_check: 是否启用自定义舰船检测
            custom_positions: 自定义舰位列表
            
        Returns:
            bool: 是否满足前置条件
        """
        if not self.config.OpsiFleetAutoChange_Enable:
            return True
        
        if not enable_custom_check:
            logger.warning("自动配队需要启用自定义舰船检测，将禁用自动配队")
            return False
        
        if not custom_positions:
            logger.warning("自动配队需要有效的自定义舰位配置，将禁用自动配队")
            return False
        
        logger.info(f"自动配队前置条件满足: 启用自定义检测，舰位 {custom_positions}")
        return True

    def _format_check_report(self, ship_data_list, target_level, fleet_index, error_msg=None, custom_positions=None):
        """
        格式化检测报告，用于推送通知
        
        Args:
            ship_data_list: 舰船数据列表，失败时为None
            target_level: 目标等级
            fleet_index: 舰队索引
            error_msg: 错误信息，成功时为None
            custom_positions: 自定义舰位列表，None时显示所有舰船
            
        Returns:
            str: 格式化的报告文本
        """
        lines = []
        lines.append("【舰船经验检测报告】")
        lines.append("")
        
        if error_msg:
            lines.append("检测状态: 失败")
            lines.append(f"错误信息: {error_msg}")
            return "\n".join(lines)
        
        lines.append("检测状态: 成功")
        lines.append(f"检测舰队: 第 {fleet_index} 舰队")
        lines.append(f"目标等级: Lv.{target_level}")
        if custom_positions:
            lines.append(f"检测舰位: {', '.join(map(str, custom_positions))}")
        lines.append("")
        
        target_exp = LIST_SHIP_EXP[target_level - 1] if 1 <= target_level <= 125 else 0
        
        try:
            from module.statistics.ship_exp_stats import get_ship_exp_stats
            stats = get_ship_exp_stats(
                instance_name=self.config.config_name if hasattr(self.config, 'config_name') else None
            )
            exp_per_hour = stats.get_exp_per_hour()
        except Exception:
            exp_per_hour = 22000.0
        
        ships_to_report = ship_data_list
        if custom_positions:
            ships_to_report = [s for s in ship_data_list if s.get('position') in custom_positions]
        
        for ship in ships_to_report:
            position = ship.get('position', 0)
            level = ship.get('level', 0)
            current_exp = ship.get('current_exp', 0)
            total_exp = ship.get('total_exp', 0)
            
            if target_exp > 0:
                progress = min(100, total_exp / target_exp * 100)
                progress_str = f"{progress:.1f}%"
            else:
                progress_str = "100%"
            
            if total_exp >= target_exp:
                status = "已满"
                time_str = "0分钟"
            else:
                status = progress_str
                exp_needed = target_exp - total_exp
                if exp_per_hour > 0:
                    hours_needed = exp_needed / exp_per_hour
                    time_seconds = hours_needed * 3600
                    hours = int(time_seconds // 3600)
                    minutes = int((time_seconds % 3600) // 60)
                    if hours > 0:
                        time_str = f"{hours}小时{minutes}分钟"
                    else:
                        time_str = f"{minutes}分钟"
                else:
                    time_str = "未知"
            
            lines.append(f"舰位{position}: Lv.{level} | 经验：{current_exp:,} | 进度：{status} │ 预计时间：{time_str}")
            lines.append("")
        
        all_full = all(ship.get('total_exp', 0) >= target_exp for ship in ships_to_report)
        if all_full:
            if custom_positions:
                lines.append(f"★ 指定舰位 {', '.join(map(str, custom_positions))} 已满经验！")
            else:
                lines.append("★ 所有舰船已满经验！")
        else:
            not_full = [s for s in ships_to_report if s.get('total_exp', 0) < target_exp]
            lines.append(f"未满经验舰位: {len(not_full)} 艘")
        
        lines.append(f"检测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)

    def _collect_custom_positions_data(self, target_level, custom_positions):
        """
        收集指定舰位的舰船数据
        
        Args:
            target_level: 目标等级
            custom_positions: 自定义舰位列表，如 [1, 3, 6]
            
        Returns:
            dict: {'ships': list, 'error': str} 
                  ships为舰船数据列表，失败时为None
                  error为错误信息，成功时为None
        """
        from module.os_handler.assets import (
            OS_FLEET_SLOT_NAV_1_BUTTON,
            OS_FLEET_SLOT_NAV_2_BUTTON,
            OS_FLEET_SLOT_NAV_3_BUTTON,
            OS_FLEET_SLOT_NAV_4_BUTTON,
            OS_FLEET_SLOT_NAV_5_BUTTON,
            OS_FLEET_SLOT_NAV_6_BUTTON,
        )
        
        logger.info(f"开始收集指定舰位数据: {custom_positions}")
        
        slot_buttons = {
            1: OS_FLEET_SLOT_NAV_1_BUTTON,
            2: OS_FLEET_SLOT_NAV_2_BUTTON,
            3: OS_FLEET_SLOT_NAV_3_BUTTON,
            4: OS_FLEET_SLOT_NAV_4_BUTTON,
            5: OS_FLEET_SLOT_NAV_5_BUTTON,
            6: OS_FLEET_SLOT_NAV_6_BUTTON,
        }
        
        ship_data_list = []
        
        self.fleet_set(self.config.OpsiFleet_Fleet)
        
        for position in sorted(custom_positions):
            button = slot_buttons.get(position)
            if not button:
                logger.warning(f"无效的舰位: {position}")
                continue
            
            logger.info(f"检测舰位 {position}")
            
            self.equip_enter(button, check_button=EQUIPMENT_OPEN, long_click=True)
            
            self.device.screenshot()
            level, exp = ship_info_get_level_exp(main=self)
            
            if level < 1 or level > len(LIST_SHIP_EXP):
                logger.warning(f"舰位 {position} 等级识别异常: {level}")
                ship_data_list.append({
                    "position": position,
                    "level": level,
                    "current_exp": exp,
                    "total_exp": 0,
                })
            else:
                total_exp = LIST_SHIP_EXP[level - 1] + exp
                logger.info(
                    f"舰位 {position}: 等级 {level}, 经验 {exp}, 总经验 {total_exp}"
                )
                ship_data_list.append({
                    "position": position,
                    "level": level,
                    "current_exp": exp,
                    "total_exp": total_exp,
                })
            
            self.ui_back(check_button=self.is_in_map)
            self.device.sleep(0.5)
        
        if not ship_data_list:
            return {'ships': None, 'error': '未收集到任何舰船数据'}
        
        logger.info(f"指定舰位数据收集完成，共 {len(ship_data_list)} 艘")
        return {'ships': ship_data_list, 'error': None}

    def _collect_ship_data_with_retry(self, target_level):
        """
        收集舰船数据，带重试机制
        
        Args:
            target_level: 目标等级
            
        Returns:
            dict: {'ships': list, 'error': str} 
                  ships为舰船数据列表，失败时为None
                  error为错误信息，成功时为None
        """
        max_retry = 3
        non_standard_retry_count = 0
        for attempt in range(max_retry):
            logger.info(f"开始收集舰船数据 (尝试 {attempt + 1}/{max_retry})")
            
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.equip_enter(FLEET_FLAGSHIP)
            
            ship_data_list = []
            position = 1
            
            while True:
                self.device.screenshot()
                level, exp = ship_info_get_level_exp(main=self)
                if level < 1 or level > len(LIST_SHIP_EXP):
                    logger.warning(f"舰船等级识别异常: {level}")
                    ship_data_list.append(
                        {
                            "position": position,
                            "level": level,
                            "current_exp": exp,
                            "total_exp": 0,
                        }
                    )
                    if not self.equip_view_next():
                        break
                    position += 1
                    continue
                total_exp = LIST_SHIP_EXP[level - 1] + exp
                logger.info(
                    f"位置: {position}, 等级: {level}, 经验: {exp}, 总经验: {total_exp}, 目标经验: {LIST_SHIP_EXP[target_level - 1]}"
                )

                ship_data_list.append(
                    {
                        "position": position,
                        "level": level,
                        "current_exp": exp,
                        "total_exp": total_exp,
                    }
                )

                if not self.equip_view_next():
                    break
                position += 1
            
            self.ui_back(appear_button=EQUIPMENT_OPEN, check_button=self.is_in_map)
            
            validation_result = self._validate_ship_data(ship_data_list)
            if validation_result['valid']:
                if validation_result.get('need_retry', False):
                    current_ship_count = len(ship_data_list)
                    non_standard_retry_count += 1
                    
                    if non_standard_retry_count >= 3:
                        logger.info(f"非标准舰船数量({current_ship_count}艘)已重试3次，使用当前检测结果")
                        return {'ships': ship_data_list, 'error': None}
                    
                    logger.warning(f"舰船数量非标准({current_ship_count}艘)，重试确认 ({non_standard_retry_count}/3)")
                    if attempt < max_retry - 1:
                        logger.info("等待1秒后重试...")
                        self.device.click_record_clear()
                        import time
                        time.sleep(1)
                    else:
                        logger.info(f"已达到最大重试次数，使用当前检测结果({current_ship_count}艘)")
                        return {'ships': ship_data_list, 'error': None}
                else:
                    logger.info("舰船数据验证通过")
                    return {'ships': ship_data_list, 'error': None}
            else:
                logger.warning(f"舰船数据验证失败: {validation_result['reason']}")
                last_error = validation_result['reason']
                if attempt < max_retry - 1:
                    logger.info("等待1秒后重试...")
                    self.device.click_record_clear()
                    import time
                    time.sleep(1)
                else:
                    logger.error("已达到最大重试次数，舰船数据收集失败")
                    return {'ships': None, 'error': f"验证失败: {last_error}"}
        
        return {'ships': None, 'error': "未知错误"}

    def _validate_ship_data(self, ship_data_list):
        """
        验证舰船数据有效性
        
        Args:
            ship_data_list: 舰船数据列表
            
        Returns:
            dict: {'valid': bool, 'reason': str}
        """
        if not ship_data_list:
            return {'valid': False, 'reason': '舰船数据为空'}
        
        ship_count = len(ship_data_list)
        if ship_count < 1 or ship_count > 6:
            return {
                'valid': False, 
                'reason': f'舰船数量异常: {ship_count}，应为1-6艘'
            }
        
        positions = [ship['position'] for ship in ship_data_list]
        if len(positions) != len(set(positions)):
            return {
                'valid': False, 
                'reason': f'存在重复的舰船位置: {positions}'
            }
        
        for ship in ship_data_list:
            if ship['level'] < 1 or ship['level'] > 125:
                return {
                    'valid': False, 
                    'reason': f"舰船等级异常: {ship['level']}"
                }
        
        if ship_count != 6:
            return {
                'valid': True, 
                'reason': f'舰船数量为{ship_count}，非标准6艘',
                'need_retry': True
            }
        
        return {'valid': True, 'reason': ''}

    def _check_custom_positions_full_exp(self, ship_data_list, target_level, custom_positions):
        """
        检查自定义舰位是否满经验
        
        Args:
            ship_data_list: 舰船数据列表
            target_level: 目标等级
            custom_positions: 自定义舰位列表，如 [4, 5]
        """
        target_exp = LIST_SHIP_EXP[target_level - 1]
        
        detected_positions = [ship['position'] for ship in ship_data_list]
        positions_full = []
        positions_not_full = []
        positions_not_exist = []
        
        for position in custom_positions:
            if position not in detected_positions:
                logger.warning(f"舰位 {position} 不存在于当前舰队中，已检测到的舰位: {detected_positions}")
                positions_not_exist.append(str(position))
                continue
            
            for ship in ship_data_list:
                if ship['position'] == position:
                    if ship['total_exp'] >= target_exp:
                        positions_full.append(str(position))
                        logger.info(f"舰位 {position} 已满经验")
                    else:
                        positions_not_full.append(str(position))
                        logger.info(f"舰位 {position} 未满经验")
                    break
        
        if positions_not_exist:
            logger.warning(f"以下舰位不存在: {', '.join(positions_not_exist)}")
        
        if positions_not_full:
            logger.info(
                f"自定义舰位未满经验: {', '.join(positions_not_full)}"
            )
        elif positions_not_exist:
            logger.warning("存在未检测到的自定义舰位，本次不判定为满经验")
        else:
            logger.info(
                f"所有自定义舰位均已满经验: {', '.join(positions_full)}"
            )
            self.notify_push(
                title="自定义舰位练级检查通过",
                content=f"<{self.config.config_name}> 自定义舰位 {', '.join(positions_full)} 已达到等级限制 {target_level}。",
            )
            
            if self.config.OpsiFleetAutoChange_Enable:
                logger.info("检测到自动配队已启用，开始执行自动配队")
                try:
                    from module.os.tasks.fleet_auto_change import OpsiFleetAutoChange
                    auto_change = OpsiFleetAutoChange(config=self.config, device=self.device)
                    auto_change.run()
                    logger.info("自动配队执行完成")
                except Exception as e:
                    logger.error(f"自动配队执行失败: {e}")
            
            if self.config.OpsiCheckLeveling_DelayAfterFull:
                logger.info("自定义舰位满经验后延迟任务")
                self.config.task_delay(server_update=True)
                self.config.task_stop()

    def detect_and_record_sea_miles(self):
        """
        检测并记录海里数
        
        Returns:
            int: 海里数，失败时返回None
        """
        logger.info("开始海里数检测")
        
        try:
            logger.info("确保在大世界地图上")
            if not self.is_in_map():
                logger.info("当前不在大世界地图，返回大世界地图")
                self.ui_back(check_button=self.is_in_map)
            
            logger.info("进入情报页面")
            skip_first_screenshot = True
            confirm_timer = Timer(3, count=6).start()
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()
                
                if self.appear(MISSION_CHECK, offset=(20, 20)):
                    break
                
                if confirm_timer.reached():
                    logger.warning("进入情报页面超时")
                    return None
                
                if self.appear_then_click(MISSION_ENTER, offset=(200, 5), interval=3):
                    continue
            
            logger.info("识别海里数")
            self.device.screenshot()
            sea_miles = OCR_SEA_MILES_DIGIT.ocr(self.device.image)
            
            if sea_miles <= 0:
                logger.warning(f"海里数识别异常: {sea_miles}")
                return None
            
            logger.info(f"海里数识别成功: {sea_miles}")
            
            from module.statistics.opsi_runtime import record_ap_snapshot
            record_ap_snapshot(
                config=self.config,
                ap_current=0,
                source='sea_miles',
                distance=sea_miles
            )
            
            logger.info("退出情报页面")
            self.ui_click(
                MISSION_QUIT, 
                check_button=self.is_in_map,
                offset=(20, 20),
                skip_first_screenshot=True
            )
            
            return sea_miles
            
        except Exception as e:
            logger.error(f"海里数检测失败: {e}")
            try:
                if self.appear(MISSION_CHECK, offset=(20, 20)):
                    self.ui_click(
                        MISSION_QUIT, 
                        check_button=self.is_in_map,
                        offset=(20, 20),
                        skip_first_screenshot=True
                    )
            except Exception:
                pass
            return None
