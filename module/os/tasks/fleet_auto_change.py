"""大世界舰队自动更换模块。

在大世界战斗过程中自动更换旗舰满级的舰队，包括：
- 检测旗舰等级和经验值判断是否需要更换
- 舰队部署界面的进入、选择和确认操作
- 支持收藏夹筛选和多舰队槽位管理
- 舰队装备和编队的完整配置流程

通过舰船经验 OCR 检测旗舰升级状态，
当旗舰满级时自动切换到下一组备用舰队继续 farming。
"""

from datetime import timedelta

from module.base.timer import Timer
from module.config.time_source import now as current_time
from module.equipment.assets import EQUIPMENT_OPEN
from module.exception import ScriptError
from module.logger import logger
from module.os.assets import FLEET_FLAGSHIP
from module.os.dock_mixin import DockMixin
from module.os.map import OSMap
from module.os.ship_exp import ship_info_get_level_exp
from module.os.ship_exp_data import LIST_SHIP_EXP
from module.os.tasks.scheduling import CoinTaskMixin
from module.os_handler.assets import (
    AUTO_SEARCH_REWARD,
    DEPART_CONFIRM_BUTTON,
    DEPART_CONFIRM_TEMPLATE,
    DEPART_IMMEDIATELY_BUTTON,
    FAVORITE_BUTTON,
    FAVORITE_TEMPLATE,
    FLEET_DEPLOY_BUTTON,
    FLEET_DEPLOYMENT,
    FLEET_SLOT_1_BUTTON,
    FLEET_SLOT_1_TEMPLATE,
    FLEET_SLOT_2_BUTTON,
    FLEET_SLOT_2_TEMPLATE,
    FLEET_SLOT_3_BUTTON,
    FLEET_SLOT_3_TEMPLATE,
    FLEET_SLOT_4_BUTTON,
    FLEET_SLOT_4_TEMPLATE,
    FLEET_SLOT_5_BUTTON,
    FLEET_SLOT_5_TEMPLATE,
    FLEET_SLOT_6_BUTTON,
    FLEET_SLOT_6_TEMPLATE,
    FLEET_SLOT_CONFIRM_BUTTON,
    FLEET_SLOT_CONFIRM_TEMPLATE,
    OS_FLEET_SLOT_NAV_1_BUTTON,
    OS_FLEET_SLOT_NAV_2_BUTTON,
    OS_FLEET_SLOT_NAV_3_BUTTON,
    OS_FLEET_SLOT_NAV_4_BUTTON,
    OS_FLEET_SLOT_NAV_5_BUTTON,
    OS_FLEET_SLOT_NAV_6_BUTTON,
    PORT_GOTO_SUPPLY,
)
from module.retire.assets import DOCK_EMPTY
from module.ui.assets import BACK_ARROW


class OpsiFleetAutoChange(CoinTaskMixin, DockMixin, OSMap):
    """侵蚀一舰队自动配队处理器。

    当经验检测发现指定舰位已满经验时，自动进入船坞选择替换舰船。
    """

    def run(self):
        """执行自动配队主流程。

        流程包括：检查冷却时间、返回碧蓝港口、解析自定义舰位配置、
        执行自动配队、更新冷却时间、重新运行经验检测并推送通知。
        """
        if not self._check_cooldown():
            logger.info("[大世界-自动配队] 自动配队冷却中，跳过")
            return

        try:
            self._goto_azur_port()

            custom_positions = self._parse_custom_positions()

            logger.info(f"[大世界-自动配队] 开始执行自动配队，舰位: {custom_positions}")
            self._execute_fleet_auto_change(custom_positions)

            self._set_cooldown()
            logger.info("[大世界-自动配队] 自动配队完成")

            self._run_exp_check_after_auto_change(custom_positions)

            self._notify_auto_change_complete(custom_positions)

        except Exception as e:
            logger.error(f"[大世界-自动配队] 自动配队执行失败: {e}")
            self._handle_auto_change_error(str(e))
            raise

    def _run_exp_check_after_auto_change(self, custom_positions):
        """自动配队后运行经验检测。

        Args:
            custom_positions (list[int]): 自定义舰位列表。
        """
        logger.info("[大世界-自动配队] 自动配队后运行经验检测")

        if not self._ensure_return_to_os_map():
            logger.warning("[大世界-自动配队] 无法返回大世界地图，尝试回到主界面")
            self._return_to_main_page()

        try:
            from module.os.tasks.hazard_leveling import OpsiHazard1Leveling

            leveling = OpsiHazard1Leveling(config=self.config, device=self.device)
            leveling.os_check_leveling()
            logger.info("[大世界-自动配队] 经验检测完成")
        except Exception as e:
            logger.warning(f"[大世界-自动配队] 经验检测失败: {e}")

    def _wait_until_back_in_os_map(self, timeout=60):
        """等待离开港口并回到大世界海域地图。

        途中处理加载界面、延迟弹出的通关奖励，以及点击过快、点到海域地图外
        出现的「需要暂时离开大型作战么?」弹窗（点击 X 取消，避免退出大型作战）。

        Args:
            timeout (int): 超时秒数，识别到加载界面时重新计时。

        Returns:
            bool: 成功回到大世界海域地图返回 True。

        Pages:
            in: 舰队部署界面出发后、港口界面或加载界面
            out: is_in_map
        """
        timer = Timer(timeout).start()
        for _ in self.loop():
            if timer.reached():
                break
            # 误触地图外出现的「需要暂时离开大型作战么?」弹窗，点击 X 留在大型作战
            if self.handle_leave_os_popup():
                continue
            # 出发后经过加载界面，等待加载完成后再识别
            if self.is_combat_loading():
                timer.reset()
                continue
            # 游戏偶尔出现上一次通关弹窗 AUTO_SEARCH_REWARD 延迟弹出的 Bug
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
            # 仍在港口界面，退出港口
            if self.appear(PORT_GOTO_SUPPLY, offset=(20, 20)):
                logger.info("[大世界-自动配队] 检测到港口界面，退出港口")
                self.port_quit(skip_first_screenshot=True)
                self.wait_os_map_buttons()
                continue
            # 已回到大世界海域地图
            if self.is_in_map():
                logger.info("[大世界-自动配队] 已返回大世界地图")
                return True

        return False

    def _ensure_return_to_os_map(self):
        """确保当前界面已返回大世界地图。

        Returns:
            bool: 是否成功返回大世界地图。
        """
        if self._wait_until_back_in_os_map(timeout=30):
            return True
        logger.warning("[大世界-自动配队] 超时未能返回大世界地图")
        return False
    
    def _return_to_main_page(self):
        """返回游戏主界面。"""
        from module.ui.page import page_main
        logger.info("[大世界-自动配队] 尝试回到主界面")

        try:
            self.ui_goto(page_main)
            logger.info("[大世界-自动配队] 已回到主界面")
        except Exception as e:
            logger.warning(f"[大世界-自动配队] 回到主界面失败: {e}")

    def _notify_auto_change_complete(self, custom_positions):
        """推送自动配队完成通知。

        Args:
            custom_positions (list[int]): 自定义舰位列表。
        """
        try:
            positions_str = ', '.join(map(str, custom_positions))
            self.notify_push(
                title="大世界自动配队完成",
                content=f"<{self.config.config_name}>\n\n已更换舰位: {positions_str}\n\n自动配队冷却时间: {self.config.OpsiFleetAutoChange_CooldownHours} 小时"
            )
        except Exception as e:
            logger.warning(f"[大世界-自动配队] 推送通知失败: {e}")

    def _goto_azur_port(self):
        """前往最近的碧蓝港口。"""
        logger.info("[大世界-自动配队] 前往碧蓝航线港口")

        if not hasattr(self, 'zone') or self.zone is None:
            logger.info("[大世界-自动配队] 初始化当前区域信息")
            self.zone_init()

        if not self.zone.is_azur_port:
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

        logger.info(f"[大世界-自动配队] 已到达港口: {self.zone}")

    def _handle_auto_change_error(self, error_msg):
        """处理自动配队失败的异常，禁用功能并发送通知。

        Args:
            error_msg (str): 错误信息。
        """
        from module.config.recovery import check_error_recovery
        check_error_recovery(self.config, RuntimeError(error_msg))
        logger.error(f"[大世界-自动配队] 自动配队发生错误: {error_msg}")

        self.config.OpsiFleetAutoChange_Enable = False
        logger.info("[大世界-自动配队] 已禁用大世界自动配队功能")

        try:
            self.notify_push(
                title="大世界自动配队错误",
                content=f"<{self.config.config_name}>\n\n自动配队执行失败: {error_msg}\n\n已禁用自动配队功能，请检查后手动启用。"
            )
        except Exception as e:
            logger.warning(f"[大世界-自动配队] 推送通知失败: {e}")

        logger.info("[大世界-自动配队] 尝试重启游戏以恢复状态")
        self.config.task_call('Restart')

    def _check_cooldown(self):
        """检查自动配队冷却时间是否已到期。

        Returns:
            bool: 若冷却已结束或从未运行过返回 True，否则返回 False。
        """
        last_run = self.config.OpsiFleetAutoChange_LastRun
        if last_run is None:
            return True

        cooldown_hours = self.config.OpsiFleetAutoChange_CooldownHours
        next_run_time = last_run + timedelta(hours=cooldown_hours)

        return current_time() >= next_run_time

    def _parse_custom_positions(self):
        """解析自定义舰位配置。

        Returns:
            list[int]: 需检查和更换的舰位列表，如 [1, 2, 3, 4, 5, 6]。
        """
        enable_custom_check = self.config.OpsiCheckLeveling_EnableCustomCheck
        if not enable_custom_check:
            return [1, 2, 3, 4, 5, 6]
        
        custom_str = self.config.OpsiCheckLeveling_CustomCheckPositions
        if not custom_str:
            return [1, 2, 3, 4, 5, 6]
        
        try:
            positions = [int(p.strip()) for p in str(custom_str).split(',')]
            return [p for p in positions if 1 <= p <= 6]
        except:
            logger.warning(f"[大世界-自动配队] 自定义舰位配置格式错误: {custom_str}")
            return [1, 2, 3, 4, 5, 6]
    
    def _check_trigger_condition(self, ship_data_list, target_level, custom_positions):
        """检查是否满足触发自动配队的条件。

        Args:
            ship_data_list (list[dict]): 舰船数据列表，包含各舰位的位置与经验。
            target_level (int): 目标等级。
            custom_positions (list[int]): 自定义检查的舰位列表。

        Returns:
            bool: 所有指定舰位均已满经验时返回 True，否则返回 False。
        """
        target_exp = LIST_SHIP_EXP[target_level - 1]

        for ship in ship_data_list:
            position = ship['position']

            if position not in custom_positions:
                continue

            if ship['total_exp'] < target_exp:
                logger.info(f"[大世界-自动配队] 舰位 {position} 未满经验，不触发自动配队")
                return False

        logger.info(f"[大世界-自动配队] 所有指定舰位 {custom_positions} 已满经验，触发自动配队")
        return True

    def _execute_fleet_auto_change(self, positions):
        """执行自动更换舰队流程。

        Args:
            positions (list[int]): 需要更换的舰位列表。
        """
        self._cancel_favorite_for_positions(positions)
        self._enter_fleet_deploy()
        self._select_ships_at_positions(positions)
        self._confirm_departure()

    def _cancel_favorite_for_positions(self, positions):
        """取消指定舰位舰船的常用标记。

        Args:
            positions (list[int]): 舰位列表，如 [1, 3, 5]。
        """
        logger.info(f"[大世界-自动配队] 取消舰位 {positions} 的常用标记")
        
        slot_buttons = {
            1: OS_FLEET_SLOT_NAV_1_BUTTON,
            2: OS_FLEET_SLOT_NAV_2_BUTTON,
            3: OS_FLEET_SLOT_NAV_3_BUTTON,
            4: OS_FLEET_SLOT_NAV_4_BUTTON,
            5: OS_FLEET_SLOT_NAV_5_BUTTON,
            6: OS_FLEET_SLOT_NAV_6_BUTTON,
        }
        
        for position in positions:
            button = slot_buttons.get(position)
            if not button:
                logger.warning(f"[大世界-自动配队] 无效的舰位: {position}")
                continue
            
            logger.info(f"[大世界-自动配队] 长按舰位 {position} 进入详情界面")
            
            self.equip_enter(button, check_button=EQUIPMENT_OPEN, long_click=True)
            
            if self.appear(FAVORITE_TEMPLATE, offset=(20, 20)):
                self.device.click(FAVORITE_BUTTON)
                logger.info(f"[大世界-自动配队] 已取消舰位 {position} 的常用标记")
                self.device.sleep(0.5)
            else:
                logger.info(f"[大世界-自动配队] 舰位 {position} 未设置常用标记")
            
            self.ui_back(check_button=self.is_in_map, additional=self.handle_leave_os_popup)
            self.device.sleep(0.5)
    
    def _enter_fleet_deploy(self):
        """进入舰队部署界面。

        Raises:
            ScriptError: 无法进入舰队部署界面时抛出。
        """
        logger.info("[大世界-自动配队] 进入舰队部署界面")

        self.order_enter()

        self.device.click(FLEET_DEPLOY_BUTTON)
        self.device.screenshot()

        timeout = 10
        enter_timeout = 0
        while not self.appear(FLEET_DEPLOYMENT, offset=(20, 20)):
            self.device.screenshot()
            enter_timeout += 1
            if enter_timeout > timeout * 2:
                logger.error("[大世界-自动配队] 无法进入舰队部署界面")
                raise ScriptError("无法进入舰队部署界面")

    def _select_ships_at_positions(self, positions):
        """在指定舰位选择舰船。

        选择逻辑：
        1. 将舰位列表升序排序。
        2. 第 N 个要更换的舰位（从 0 开始）对应船坞第一排第 (N+1) 个位置。

        Args:
            positions (list[int]): 舰位列表，如 [1, 4, 5, 6]。

        Raises:
            ScriptError: 船坞中没有可用常用舰船时抛出。
        """
        sorted_positions = sorted(positions)
        logger.info(f"[大世界-自动配队] 在舰位 {sorted_positions} 选择舰船")

        slot_buttons = {
            1: FLEET_SLOT_1_BUTTON,
            2: FLEET_SLOT_2_BUTTON,
            3: FLEET_SLOT_3_BUTTON,
            4: FLEET_SLOT_4_BUTTON,
            5: FLEET_SLOT_5_BUTTON,
            6: FLEET_SLOT_6_BUTTON,
        }

        for index, position in enumerate(sorted_positions):
            button = slot_buttons.get(position)
            if button:
                logger.info(f"[大世界-自动配队] 点击舰位 {position}")
                self.device.click(button)
                self.device.screenshot()

                if self.appear(DOCK_EMPTY, offset=(20, 20)):
                    logger.error("[大世界-自动配队] 船坞中没有可用的常用舰船")
                    raise ScriptError("船坞中没有可用的常用舰船，无法完成自动配队")

                self.dock_favourite_set(enable=True, wait_loading=False)

                self.device.screenshot()
                if self.appear(DOCK_EMPTY, offset=(20, 20)):
                    logger.error("[大世界-自动配队] 船坞中没有可用的常用舰船")
                    raise ScriptError("船坞中没有可用的常用舰船，无法完成自动配队")

                grid_index = index + 1
                self.dock_select_ship_at_grid(grid_index)

                self._confirm_ship_selection()

    def _confirm_ship_selection(self):
        """确认舰船选择。

        Raises:
            ScriptError: 无法找到确认按钮或确认后未返回部署界面时抛出。
        """
        logger.info("[大世界-自动配队] 确认舰船选择")

        timeout = 10
        confirm_timeout = 0
        while not self.appear(FLEET_SLOT_CONFIRM_TEMPLATE, offset=(20, 20)):
            self.device.screenshot()
            confirm_timeout += 1
            if confirm_timeout > timeout * 2:
                logger.error("[大世界-自动配队] 无法找到确认按钮")
                raise ScriptError("无法找到确认按钮，舰船选择失败")

        self.device.click(FLEET_SLOT_CONFIRM_BUTTON)
        self.device.screenshot()

        return_timeout = 0
        while not self.appear(FLEET_DEPLOYMENT, offset=(20, 20)):
            self.device.screenshot()
            return_timeout += 1
            if return_timeout > timeout * 2:
                logger.error("[大世界-自动配队] 确认舰船选择后未返回舰队部署界面")
                raise ScriptError("确认舰船选择后未返回舰队部署界面")

    def _confirm_departure(self):
        """确认舰队出击。

        Raises:
            ScriptError: 出发确认超时且无法返回大世界地图时抛出。
        """
        logger.info("[大世界-自动配队] 确认出发")

        # 配队过程中点击过快可能点到海域地图外，弹出「需要暂时离开大型作战么?」，
        # 先关闭弹窗，否则「立即前往」会点空
        for _ in self.loop(timeout=3):
            if self.handle_leave_os_popup():
                continue
            break

        self.device.click(DEPART_IMMEDIATELY_BUTTON)

        confirm_timeout = 0
        confirm_max_timeout = 10
        while confirm_timeout < confirm_max_timeout * 2:
            self.device.screenshot()

            # 出发确认弹窗与离开大型作战弹窗的确定按钮位置相同，
            # 必须先关闭离开弹窗，否则会把它当成出发确认点成确定，直接退出大型作战
            if self.handle_leave_os_popup():
                confirm_timeout += 1
                continue

            if self.appear(DEPART_CONFIRM_TEMPLATE, offset=(20, 20)):
                logger.info("[大世界-自动配队] 检测到出发确认弹窗，点击确认")
                self.device.click(DEPART_CONFIRM_BUTTON)
                break

            confirm_timeout += 1
        else:
            logger.info("[大世界-自动配队] 未检测到出发确认弹窗，继续执行")

        if not self._wait_until_back_in_os_map(timeout=60):
            logger.error("[大世界-自动配队] 出发确认超时")
            raise ScriptError("出发确认超时，无法返回大世界地图")

    def _set_cooldown(self):
        """设置自动配队冷却时间。"""
        self.config.OpsiFleetAutoChange_LastRun = current_time().replace(microsecond=0)
        logger.info(f"[大世界-自动配队] 已设置冷却时间，下次可运行时间: {self.config.OpsiFleetAutoChange_LastRun}")
    
    def _collect_ship_data_with_retry(self, target_level):
        """收集当前舰队舰船的等级与经验数据，支持重试。

        Args:
            target_level (int): 目标等级。

        Returns:
            dict: 包含收集结果的字典：
                - 'ships' (list[dict] | None): 舰船数据列表，失败时为 None。
                - 'error' (str | None): 错误描述信息，成功时为 None。
        """
        max_retry = 3
        non_standard_retry_count = 0
        last_error = None

        for attempt in range(max_retry):
            logger.info(f"[大世界-自动配队] 开始收集舰船数据 (尝试 {attempt + 1}/{max_retry})")

            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.equip_enter(FLEET_FLAGSHIP)

            ship_data_list = []
            position = 1

            while True:
                self.device.screenshot()
                level, exp = ship_info_get_level_exp(main=self)

                if level < 1 or level > len(LIST_SHIP_EXP):
                    logger.warning(f"[大世界-自动配队] 舰船等级识别异常: {level}")
                    ship_data_list.append({
                        "position": position,
                        "level": level,
                        "current_exp": exp,
                        "total_exp": 0,
                    })
                    if not self.equip_view_next():
                        break
                    position += 1
                    continue

                total_exp = LIST_SHIP_EXP[level - 1] + exp
                logger.info(
                    f"位置: {position}, 等级: {level}, 经验: {exp}, 总经验: {total_exp}, 目标经验: {LIST_SHIP_EXP[target_level - 1]}"
                )

                ship_data_list.append({
                    "position": position,
                    "level": level,
                    "current_exp": exp,
                    "total_exp": total_exp,
                })

                if not self.equip_view_next():
                    break
                position += 1

            self.ui_back(appear_button=EQUIPMENT_OPEN, check_button=self.is_in_map,
                         additional=self.handle_leave_os_popup)

            validation_result = self._validate_ship_data(ship_data_list)
            if validation_result['valid']:
                if validation_result.get('need_retry', False):
                    current_ship_count = len(ship_data_list)
                    non_standard_retry_count += 1

                    if non_standard_retry_count >= 3:
                        logger.info(f"[大世界-自动配队] 非标准舰船数量({current_ship_count}艘)已重试3次，使用当前检测结果")
                        return {'ships': ship_data_list, 'error': None}

                    logger.warning(f"[大世界-自动配队] 舰船数量非标准({current_ship_count}艘)，重试确认 ({non_standard_retry_count}/3)")
                    if attempt < max_retry - 1:
                        logger.info("[大世界-自动配队] 等待后重试...")
                        self.device.click_record_clear()
                        self.interval_reset()
                    else:
                        logger.info(f"[大世界-自动配队] 已达到最大重试次数，使用当前检测结果({current_ship_count}艘)")
                        return {'ships': ship_data_list, 'error': None}
                else:
                    logger.info("[大世界-自动配队] 舰船数据验证通过")
                    return {'ships': ship_data_list, 'error': None}
            else:
                logger.warning(f"[大世界-自动配队] 舰船数据验证失败: {validation_result['reason']}")
                last_error = validation_result['reason']
                if attempt < max_retry - 1:
                    logger.info("[大世界-自动配队] 等待后重试...")
                    self.device.click_record_clear()
                    self.interval_reset()
                else:
                    logger.error("[大世界-自动配队] 已达到最大重试次数，舰船数据收集失败")
                    return {'ships': None, 'error': f"验证失败: {last_error}"}

        return {'ships': None, 'error': f"未知错误: {last_error}"}

    def _validate_ship_data(self, ship_data_list):
        """验证收集到的舰船数据有效性。

        Args:
            ship_data_list (list[dict]): 待校验的舰船数据列表。

        Returns:
            dict: 校验结果字典：
                - 'valid' (bool): 数据是否有效。
                - 'reason' (str): 验证失败或重试的原因说明。
                - 'need_retry' (bool, optional): 是否建议重试确认。
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
