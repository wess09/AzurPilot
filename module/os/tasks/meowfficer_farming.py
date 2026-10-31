"""大世界指挥喵 farming 模块。

在大世界中执行指挥喵（Meowfficer）资源 farming，包括：
- 支持指定目标海域的精确 farming
- 智能海域选择和路径规划
- 代币资源保护和行动力管理
- 失败重试和异常恢复机制
- 战后 debug 录像（可选，见 OpsiMeowfficerFarming.DebugClip）

继承自 CoinTaskMixin 和 OSMap，提供代币保护和地图导航能力，
通过指定海域列表实现高效的指挥喵资源收集。
"""

from module.config.config import TaskEnd
from module.config.utils import get_os_reset_remain
from module.exception import (
    GameStuckError,
    GameTooManyClickError,
    RequestHumanTakeover,
    ScriptError,
)
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import ALREADY_SOLVED_MAP_EVENTS, OSMap
from module.os_handler.action_point import ActionPointLimit
from module.os.tasks.scheduling import CoinTaskMixin


class MeowfficerTargetZoneMixin:
    def _meow_target_zone_tokens(self):
        """解析耄耋相接指定海域输入，保留原始顺序用于后续校验。

        智能调度月末清理代跑时经 ``_meow_target_zone_override`` 传入调度层
        已解析好的单个海域，直接覆盖用户配置的指定海域。

        Returns:
            list[str | int]: 分割后的海域标识字符串或整数列表。
        """
        override = getattr(self, '_meow_target_zone_override', None)
        if override is not None:
            return [override.zone_id]

        target_zone = self.config.OpsiMeowfficerFarming_TargetZone
        if target_zone is None:
            return []
        if isinstance(target_zone, int):
            return [] if target_zone == 0 else [target_zone]

        target_zone = str(target_zone).strip()
        if target_zone in ('', '0'):
            return []
        if ',' not in target_zone and '，' not in target_zone:
            return [target_zone]

        normalized = target_zone.replace('，', ',')
        return [token.strip() for token in normalized.split(',')]

    def _meow_target_zone_error(self, message):
        """记录目标海域配置错误并请求人工接管。

        Args:
            message (str): 错误日志消息。

        Raises:
            RequestHumanTakeover: 抛出人工接管异常以停止任务。
        """
        logger.error(message)
        raise RequestHumanTakeover('耄耋相接指定海域配置无效，任务已停止')

    def _meow_target_zones(self, *, require_target=False, allow_multiple=True):
        """
        获取耄耋相接指定海域列表。

        Args:
            require_target (bool): 未填写目标时是否停止任务。
            allow_multiple (bool): 是否允许逗号分隔的多海域列表。

        Returns:
            list[Zone]: 按用户输入顺序解析出的海域列表。
        """
        tokens = self._meow_target_zone_tokens()
        raw_value = self.config.OpsiMeowfficerFarming_TargetZone
        if not tokens:
            if require_target:
                message = '已启用 StayInZone 但未设置 TargetZone'
                logger.warning(f'[大世界-耄耋相接] {message}，跳过本次任务')
                if self.is_running_smart_scheduling_task():
                    self._handle_coin_task_no_content('耄耋相接', message)
                    return []
                self.delay_opsi_active_task(server_update=True)
                self.config.task_stop()
            return []

        if len(tokens) > 1 and not allow_multiple:
            self._meow_target_zone_error(
                f'耄耋相接指定海域填写了多海域列表 "{raw_value}"，需要开启“循环出击指定海域”后才能使用'
            )

        empty_tokens = [index + 1 for index, token in enumerate(tokens) if token == '']
        invalid_tokens = []
        port_zones = []
        duplicate_zones = []
        zones = []
        seen_zone_ids = set()
        for token in tokens:
            if token == '':
                continue
            if token == '0':
                invalid_tokens.append(token)
                continue
            try:
                zone = self.name_to_zone(token)
            except ScriptError:
                invalid_tokens.append(token)
                continue

            if zone.is_port:
                port_zones.append(zone)
            if zone.zone_id in seen_zone_ids:
                duplicate_zones.append(zone)
            else:
                seen_zone_ids.add(zone.zone_id)
                zones.append(zone)

        errors = []
        if empty_tokens:
            errors.append(f'第 {", ".join(map(str, empty_tokens))} 项为空')
        if invalid_tokens:
            errors.append(f'无法识别: {", ".join(map(str, invalid_tokens))}')
        if port_zones:
            errors.append(f'港口海域不可用于耄耋相接: {[zone.zone_id for zone in port_zones]}')
        if duplicate_zones:
            errors.append(f'重复海域: {[zone.zone_id for zone in duplicate_zones]}')
        if errors:
            self._meow_target_zone_error(f'耄耋相接指定海域输入错误 ({raw_value}): {"; ".join(errors)}')

        logger.attr('目标海域列表', [zone.zone_id for zone in zones])
        return zones

    def _meow_target_zone_at(self, zones, index):
        """按顺序循环获取本轮目标海域。

        Args:
            zones (list[Zone]): 目标海域列表。
            index (int): 当前轮次索引。

        Returns:
            tuple[Zone, int]: 本轮选中的海域实例及 1-based 序号。
        """
        zone_index = index % len(zones)
        zone = zones[zone_index]
        logger.attr('目标海域索引', f'{zone_index + 1}/{len(zones)}')
        return zone, zone_index + 1


class OpsiMeowfficerFarming(MeowfficerTargetZoneMixin, CoinTaskMixin, OSMap):
    def _meow_ap_check(self, preserve, ap_checked):
        """
        行动力检查。

        Args:
            preserve (int): 行动力保留值。
            ap_checked (bool): 是否已完成行动力检查。

        Returns:
            bool: 如果已完成检查返回 True，否则返回 ap_checked 的值。
        """
        self.config.OS_ACTION_POINT_PRESERVE = preserve

        if self.config.is_task_enabled('OpsiAshBeacon') \
                and not self._ash_fully_collected \
                and self.config.cross_get("OpsiAshBeacon.OpsiAshBeacon.EnsureFullyCollected", True):
            logger.info('[大世界-耄耋相接] 余烬信标未收集满，暂时忽略行动力限制')
            self.config.OS_ACTION_POINT_PRESERVE = 0
        logger.attr('大世界行动力保留', self.config.OS_ACTION_POINT_PRESERVE)

        if not ap_checked:
            # 行动力前置检查，确保明日每日任务有足够行动力
            smart_scheduled = self.is_running_smart_scheduling_task()
            keep_current_ap = True
            check_rest_ap = True
            cl1_yellow_enough = False
            if self.is_cl1_mode_enabled and not smart_scheduled:
                cl1_yellow_enough = self.cl1_enough_yellow_coins
                if cl1_yellow_enough:
                    check_rest_ap = False

            if not smart_scheduled and self.is_cl1_mode_enabled and cl1_yellow_enough:
                try:
                    self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap,
                                          routine=True)
                except ActionPointLimit:
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
            else:
                self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap,
                                      routine=True)

            if not smart_scheduled:
                self.check_and_notify_action_point_threshold()
            return True
        return ap_checked

    def _meow_fixed_patrol_scan(self):
        """
        短猫相接的战后强制移动：短猫舰队没找到事件就换其他舰队扫雷达。

        这是短猫唯一的强制移动形式——等价于侵蚀一的 L0/L1（换队扫雷达清问号），
        **没有**侵蚀一的 L2。侵蚀一 L2 会把舰队逐个挪到固定的 C1/D1/E1/F1，
        那是照侵蚀一那张图定的，短猫跑的海域地图各不相同，挪了没意义、还可能
        把舰队挪到不该去的地方。共享的 _execute_fixed_patrol_scan 也会直接
        跳过短猫，短猫不走那条路。

        开启后遍历 1~4 号舰队的雷达清剩余问号：只切换舰队看雷达、
        不挪动舰队；已解决目标事件（明石/记录塔/信息探测装置）时跳过。
        结束后恢复短猫舰队（clear_question_any_fleet 不会恢复原舰队）。

        Pages:
            in: page_os
        """
        if not self.config.OpsiMeowfficerFarming_ExecuteFixedPatrolScan:
            return
        if self._solved_map_event & ALREADY_SOLVED_MAP_EVENTS:
            return
        logger.info('[大世界-耄耋相接] 触发效率模式强制移动')
        self.clear_question_any_fleet()
        self.fleet_set(self.config.OpsiFleet_Fleet)

    def _meow_debug_clip(self):
        """战后 debug 录像的上下文，开关为 OpsiMeowfficerFarming.DebugClip。

        录制「打完找事件 / 处理事件 / 强制移动」这一段的真实游戏画面，每一轮都保存，
        方便逐轮回看有没有漏掉问号或事件。保留天数统一在「大世界通用设置」里配置。

        Returns:
            contextlib.AbstractContextManager: with 块退出时自动保存录像。
        """
        from module.base.debug_clip import CLIP_PREFIX_MEOW, clip_recording

        return clip_recording(
            self.config,
            self.config.OpsiMeowfficerFarming_DebugClip,
            prefix=CLIP_PREFIX_MEOW,
        )

    def _meow_handle_traditional_zone(self, zone):
        """处理传统单一指定海域的耄耋相接搜索流程。

        Args:
            zone (Zone): 目标海域对象。
        """
        logger.hr(f'大世界-耄耋相接, zone_id={zone.zone_id}', level=1)
        self.globe_goto(zone, types='SAFE', refresh=True)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.meow_search_metrics_start()
        try:
            search_completed = self.run_strategic_search()
            with self._meow_debug_clip():
                if search_completed:
                    self._solved_map_event = set()
                    self._solved_fleet_mechanism = False
                    # 重扫地图找画面上可见的事件；逐队扫雷达清问号是强制移动的
                    # 事（_meow_fixed_patrol_scan）。分步检索链扫的是同一批雷达，
                    # 两边先后跑一遍就是同一轮白扫第二遍（舰队一步都没挪）。
                    self.map_rescan()
                    self._meow_fixed_patrol_scan()
                self.handle_after_auto_search()
        finally:
            self.meow_search_metrics_end()
        self._meow_record_akashi_if_solved()
        self.config.check_task_switch()

    def _meow_handle_stay_in_zone(self, zone, fresh_ap=None):
        """处理驻留指定海域的连续循环搜索流程。

        Args:
            zone (Zone): 目标海域对象。
            fresh_ap (tuple[int, int] | None): 调用方刚读到的
                (总行动力, 当前行动力)，开工检查足够时复用它跳过弹窗。
        """
        logger.hr(f'大世界-耄耋相接（指定海域循环）, zone_id={zone.zone_id}', level=1)
        self.get_current_zone()
        self.poll_background_resources(sample=True)
        if self.zone.zone_id != zone.zone_id or not self.is_zone_name_hidden:
            self.globe_goto(zone, types='SAFE', refresh=True)
            # 换海域会消耗行动力，开工检查必须重新读取。
            self.invalidate_action_point_cache()
            fresh_ap = None

        # 智能调度代跑时决策读刚读过行动力：达到开工线时弹窗只会
        # 读数再关掉，复用它跳过；不足 120 时仍需弹窗开箱/购买。
        if self.action_point_reusable(fresh_ap, cost=120):
            _fresh_total, _fresh_current = fresh_ap
            logger.info(
                f'[大世界-耄耋相接] 复用刚读到的行动力'
                f'(当前={_fresh_current}, 总={_fresh_total})，跳过行动点弹窗'
            )
        else:
            self.action_point_set(cost=120, keep_current_ap=True, check_rest_ap=True, routine=True)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)

        self.meow_search_metrics_start()
        search_completed = False
        try:
            try:
                search_completed = self.run_strategic_search()
            except (TaskEnd, GameStuckError, GameTooManyClickError, RequestHumanTakeover):
                raise
            except Exception as e:
                logger.warning(f'[大世界-耄耋相接] 战略搜索异常: {e}')

            with self._meow_debug_clip():
                if search_completed:
                    self._solved_map_event = set()
                    self._solved_fleet_mechanism = False
                    # 重扫地图找画面上可见的事件；逐队扫雷达清问号是强制移动的
                    # 事（_meow_fixed_patrol_scan），这里不要再自己扫一遍——
                    # 两边扫的是同一批雷达，中间没有舰队移动，第二遍纯属白扫。
                    self.map_rescan()
                    self._meow_fixed_patrol_scan()

                try:
                    self.handle_after_auto_search()
                except (TaskEnd, GameStuckError, GameTooManyClickError, RequestHumanTakeover):
                    raise
                except Exception:
                    logger.exception('[大世界-耄耋相接] handle_after_auto_search 发生异常')
        finally:
            self.meow_search_metrics_end()

        self._meow_record_akashi_if_solved()
        self.config.check_task_switch()

    def _meow_handle_target_zone_search(self, zone):
        """按普通耄耋相接流程清理指定海域。

        Args:
            zone (Zone): 目标海域对象。
        """
        logger.hr(f'大世界-耄耋相接, zone_id={zone.zone_id}', level=1)

        self.globe_goto(zone)

        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)

        self.meow_search_metrics_start()
        try:
            self.run_auto_search()
            with self._meow_debug_clip():
                self.handle_after_auto_search()
        finally:
            self.meow_search_metrics_end()

        self._meow_record_akashi_if_solved()
        self.config.check_task_switch()

    def _meow_record_akashi_if_solved(self):
        """本轮耄耋相接搜索结束后，记录明石事件（按侵蚀等级）。

        明石事件由共享的地图事件机制写入 _solved_map_event，
        这里消费掉该标记防止跨轮次重复计数。
        """
        solved_events = getattr(self, '_solved_map_event', set())
        if 'is_akashi' not in solved_events:
            return
        solved_events.discard('is_akashi')
        try:
            from module.statistics.opsi_runtime import record_meow_akashi_encounter

            record_meow_akashi_encounter(self)
        except Exception:
            logger.exception('[大世界-耄耋相接] 记录明石事件失败')

    def _meow_handle_normal_search(self):
        """执行普通耄耋相接的随机海域搜索流程。

        Returns:
            bool | None: 未找到符合条件海域时返回 False，正常完成返回 None。
        """
        hazard_level = self.config.OpsiMeowfficerFarming_HazardLevel
        zones = self.zone_select(hazard_level=hazard_level) \
            .delete(SelectedGrids([self.zone])) \
            .delete(SelectedGrids(self.zones.select(is_port=True))) \
            .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)

        if not zones:
            message = f'普通搜索模式未找到符合条件的海域 (侵蚀等级 {hazard_level})'
            logger.warning(f'[大世界-耄耋相接] {message}')
            self._handle_coin_task_no_content('耄耋相接', message)
            return False

        logger.hr(f'大世界-耄耋相接, zone_id={zones[0].zone_id}', level=1)

        self.globe_goto(zones[0])

        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)

        self.meow_search_metrics_start()
        try:
            self.run_auto_search()
            with self._meow_debug_clip():
                self._solved_map_event = set()
                self._solved_fleet_mechanism = False
                # 重扫地图找画面上可见的事件；逐队扫雷达清问号是强制移动的事
                # （_meow_fixed_patrol_scan，随机海域同样要跑）。这里原来只扫
                # 当前舰队的雷达，和强制移动的主队那一趟重叠，一并交给它。
                self.map_rescan()
                self._meow_fixed_patrol_scan()
                self.handle_after_auto_search()
        finally:
            self.meow_search_metrics_end()

        self._meow_record_akashi_if_solved()
        self.config.check_task_switch()

    def os_meowfficer_farming(self):
        """耄耋相接任务入口。"""
        self.run_meowfficer_farming()

    def _prepare_meowfficer_farming(self, ap_preserve=None):
        """准备耄耋相接的运行环境与配置参数。

        Args:
            ap_preserve (int | None): 行动力保留值，默认从配置读取。

        Returns:
            int | None: 解析出的行动力保留阈值，任务被推迟或中止时返回 None。
        """
        logger.hr(f'大世界-耄耋相接, hazard_level={self.config.OpsiMeowfficerFarming_HazardLevel}', level=1)

        if ap_preserve is None and self.is_cl1_mode_enabled and self.config.OpsiMeowfficerFarming_ActionPointPreserve < 500:
            logger.info('[大世界-耄耋相接] 启用侵蚀 1 练级时，最低行动力保留自动调整为 500')
            self.config.OpsiMeowfficerFarming_ActionPointPreserve = 500

        if ap_preserve is None:
            preserve = self.config.OpsiMeowfficerFarming_ActionPointPreserve
        else:
            preserve = int(ap_preserve)
        if preserve == 0:
            self.config.override(OpsiFleet_Submarine=False)

        if self.is_cl1_mode_enabled:
            # 侵蚀 1 练级模式下的必要覆盖项
            self.config.override(
                OpsiGeneral_DoRandomMapEvent=True,
                OpsiGeneral_AkashiShopFilter='ActionPoint',
                OpsiFleet_Submarine=False,
            )
            cd = self.nearest_task_cooling_down
            logger.attr('[大世界-耄耋相接] 最近冷却中的任务', cd)

            remain = get_os_reset_remain()
            if cd is not None and remain > 0:
                logger.info(f'[大世界-耄耋相接] 存在冷却中的任务，延迟耄耋相接任务至 {cd.next_run} 后执行')
                self.delay_opsi_active_task(target=cd.next_run)
                self.config.task_stop()

        if self.is_in_opsi_explore():
            logger.warning(f'[大世界-耄耋相接] 每月开荒正在运行，无法执行 {self.config.task.command}')
            self.delay_opsi_active_task(server_update=True)
            self.config.task_stop()

        if self.config.OpsiTarget_TargetFarming and not getattr(self, '_meow_target_checked', False):
            self._meow_target_checked = True
            if self.config.SERVER in ['cn', 'jp']:
                if hasattr(self, '_os_target'):
                    self._close_scheduling_action_point()
                    self._os_target()
            else:
                logger.info(f'服务器 {self.config.SERVER} 暂不支持海域成就，请联系开发者')

        target_zone_tokens = self._meow_target_zone_tokens()
        self._meow_target_zone_list = []
        self._meow_traditional_zone = None
        self._meow_target_zone_index = getattr(self, '_meow_target_zone_index', 0)
        if self.config.OpsiMeowfficerFarming_StayInZone:
            self._meow_target_zone_list = self._meow_target_zones(require_target=True, allow_multiple=True)
            if not self._meow_target_zone_list:
                return None
        elif target_zone_tokens:
            self._meow_traditional_zone = self._meow_target_zones(require_target=False, allow_multiple=False)[0]

        return preserve

    def run_meowfficer_farming(self):
        """执行大世界耄耋相接（指挥喵搜寻）持续循环主任务。"""
        preserve = None
        ap_checked = False
        preserve = self._prepare_meowfficer_farming()
        if preserve is None:
            return
        while True:
            ap_checked = self.run_meowfficer_farming_once(
                ap_preserve=preserve,
                ap_checked=ap_checked,
                prepared=True,
            )

    def run_meowfficer_farming_once(self, ap_preserve=None, ap_checked=False, prepared=False, fresh_ap=None):
        """执行单轮耄耋相接任务。

        Args:
            ap_preserve (int | None): 行动力保留值。
            ap_checked (bool): 是否已完成本轮前的行动力检查。
            prepared (bool): 是否已完成运行环境准备。
            fresh_ap (tuple[int, int] | None): 调用方刚读到的
                (总行动力, 当前行动力)；仅在读数与本次调用之间没有任何
                行动力消耗时传入（智能调度决策读），供开工检查复用。

        Returns:
            bool: 最新的行动力检查状态标志。
        """
        # 过期录像清理：与本次是否开启录制无关，避免关掉录制后旧录像一直堆着。
        # 内部有节流，不会每轮战斗都真的扫目录。保留天数见「大世界通用设置」。
        from module.base.debug_clip import cleanup_clips_if_due

        cleanup_clips_if_due(self.config)

        if prepared:
            preserve = int(ap_preserve or 0)
        else:
            preserve = self._prepare_meowfficer_farming(ap_preserve=ap_preserve)
            if preserve is None:
                return ap_checked

        if not ap_checked:
            self._close_scheduling_action_point()
        ap_checked = self._meow_ap_check(preserve, ap_checked)

        if getattr(self, '_scheduling_ap_panel_open', False):
            target_zones = getattr(self, '_meow_target_zone_list', [])
            if self.config.OpsiMeowfficerFarming_StayInZone and len(target_zones) == 1 \
                    and getattr(getattr(self, 'zone', None), 'zone_id', None) == target_zones[0].zone_id \
                    and self.is_zone_name_hidden:
                # 已在单个指定安全海域时，首读面板可直接完成本轮开工补充。
                fresh_ap = self._prepare_scheduling_action_point(fresh_ap, cost=120)
            else:
                # 换图、多海域或传统模式先关闭面板，沿各自的进入海域流程补充。
                self._close_scheduling_action_point()

        # ===== 传统目标海域模式 =====
        traditional_zone = getattr(self, '_meow_traditional_zone', None)
        if traditional_zone is not None:
            self._meow_handle_traditional_zone(traditional_zone)
            return ap_checked

        # ===== 指定海域计划作战 (StayInZone) =====
        if self.config.OpsiMeowfficerFarming_StayInZone:
            target_zones = getattr(self, '_meow_target_zone_list', [])
            zone, _ = self._meow_target_zone_at(target_zones, getattr(self, '_meow_target_zone_index', 0))
            self._meow_target_zone_index = getattr(self, '_meow_target_zone_index', 0) + 1
            if len(target_zones) == 1:
                self._meow_handle_stay_in_zone(zone, fresh_ap=fresh_ap)
            else:
                self._meow_handle_target_zone_search(zone)
            return ap_checked

        # ===== 普通耄耋相接搜索主逻辑 =====
        self._meow_handle_normal_search()
        return ap_checked
