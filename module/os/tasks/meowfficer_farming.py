"""大世界指挥喵 farming 模块。

在大世界中执行指挥喵（Meowfficer）资源 farming，包括：
- 支持指定目标海域的精确 farming
- 智能海域选择和路径规划
- 代币资源保护和行动力管理
- 失败重试和异常恢复机制

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
from module.os.map import OSMap
from module.os_handler.action_point import ActionPointLimit
from module.os.tasks.scheduling import CoinTaskMixin


class MeowfficerTargetZoneMixin:
    def _meow_target_zone_tokens(self):
        """解析耄耋相接指定海域输入，保留原始顺序用于后续校验。"""
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
        """按顺序循环获取本轮目标海域。"""
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
                and self.config.OpsiAshBeacon_EnsureFullyCollected:
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
                    self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap)
                except ActionPointLimit:
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
            else:
                self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap)

            if not smart_scheduled:
                self.check_and_notify_action_point_threshold()
            return True
        return ap_checked

    def _meow_handle_traditional_zone(self, zone):
        logger.hr(f'大世界-耄耋相接, zone_id={zone.zone_id}', level=1)
        self.globe_goto(zone, types='SAFE', refresh=True)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.meow_search_metrics_start()
        try:
            if self.run_strategic_search():
                self._solved_map_event = set()
                self._solved_fleet_mechanism = False
                self.clear_question()
                self.map_rescan()
            self.handle_after_auto_search()
        finally:
            self.meow_search_metrics_end()
        self.config.check_task_switch()

    def _meow_handle_stay_in_zone(self, zone):
        logger.hr(f'大世界-耄耋相接（指定海域循环）, zone_id={zone.zone_id}', level=1)
        self.get_current_zone()
        if self.zone.zone_id != zone.zone_id or not self.is_zone_name_hidden:
            self.globe_goto(zone, types='SAFE', refresh=True)

        # 智能调度+上下文外层已查询行动力，跳过冗余弹窗
        if not self.is_running_smart_scheduling_task():
            self.action_point_set(cost=120, keep_current_ap=True, check_rest_ap=True)
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

            if search_completed:
                self._solved_map_event = set()
                self._solved_fleet_mechanism = False
                self.clear_question()
                self.map_rescan()

            try:
                self.handle_after_auto_search()
            except (TaskEnd, GameStuckError, GameTooManyClickError, RequestHumanTakeover):
                raise
            except Exception:
                logger.exception('[大世界-耄耋相接] handle_after_auto_search 发生异常')
        finally:
            self.meow_search_metrics_end()

        self.config.check_task_switch()

    def _meow_handle_target_zone_search(self, zone):
        """按普通耄耋相接流程清理指定海域。"""
        logger.hr(f'大世界-耄耋相接, zone_id={zone.zone_id}', level=1)

        self.globe_goto(zone)

        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)

        self.meow_search_metrics_start()
        try:
            self.run_auto_search()
            self.handle_after_auto_search()
        finally:
            self.meow_search_metrics_end()

        self.config.check_task_switch()

    def _meow_handle_normal_search(self):
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
            self.handle_after_auto_search()
        finally:
            self.meow_search_metrics_end()

        self.config.check_task_switch()
        
    def os_meowfficer_farming(self):
        """耄耋相接任务入口。"""
        self.run_meowfficer_farming()

    def _prepare_meowfficer_farming(self, ap_preserve=None):
        """准备耄耋相接运行环境。"""
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
            logger.warning(f'[大世界-耄耋相接] 每月开荒+正在运行，无法执行 {self.config.task.command}')
            self.delay_opsi_active_task(server_update=True)
            self.config.task_stop()

        if self.config.OpsiTarget_TargetFarming and not getattr(self, '_meow_target_checked', False):
            self._meow_target_checked = True
            if self.config.SERVER in ['cn', 'jp']:
                if hasattr(self, '_os_target'):
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
        """执行大世界耄耋相接（猫箱搜寻）任务。"""
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

    def run_meowfficer_farming_once(self, ap_preserve=None, ap_checked=False, prepared=False):
        """执行一轮耄耋相接，由独立任务或 OpsiScheduling 调用。"""
        if prepared:
            preserve = int(ap_preserve or 0)
        else:
            preserve = self._prepare_meowfficer_farming(ap_preserve=ap_preserve)
            if preserve is None:
                return ap_checked

        ap_checked = self._meow_ap_check(preserve, ap_checked)

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
                self._meow_handle_stay_in_zone(zone)
            else:
                self._meow_handle_target_zone_search(zone)
            return ap_checked

        # ===== 普通耄耋相接搜索主逻辑 =====
        self._meow_handle_normal_search()
        return ap_checked
