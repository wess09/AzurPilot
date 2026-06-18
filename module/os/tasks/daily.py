import numpy as np

from module.config.config import TaskEnd
from module.config.utils import get_os_reset_remain
from module.exception import ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap
from module.os_handler.action_point import ActionPointLimit
from module.os_handler.assets import MISSION_COMPLETE_POPUP
from module.ui.assets import OS_CHECK
from module.ui.page import page_os


class OpsiDaily(OSMap):
    def os_port_mission(self):
        """
        遍历所有港口并执行每日任务。

        Pages:
            in: page_os, 大世界地图
            out: page_os, 大世界地图
        """
        logger.hr('OS port mission', level=1)
        ports = ['NY City', 'Dakar', 'Taranto', 'Gibraltar', 'Brest', 'Liverpool', 'Kiel', 'St. Petersburg']
        if np.random.uniform() > 0.5:
            ports.reverse()

        for port in ports:
            port = self.name_to_zone(port)
            logger.hr(f'OS port daily in {port}', level=2)
            self.globe_goto(port)

            self.run_auto_search()
            self.handle_after_auto_search()

    def _os_daily_mission_complete_check(self):
        return not self.appear(OS_CHECK, offset=(20, 20)) and \
            self.appear(MISSION_COMPLETE_POPUP, offset=(20, 20))

    def daily_interrupt_check(self):
        if not self.config.OS_MISSION_COMPLETE and self._os_daily_mission_complete_check():
            self.config.OS_MISSION_COMPLETE = True

        if self.config.OS_MISSION_COMPLETE and self.no_meowfficer_searching():
            return True
        return False

    def os_daily_set_keep_mission_zone(self):
        """
        将当前区域保存到 OpsiDaily_MissionZones 配置中。
        """
        zones = prev = self.config.OpsiDaily_MissionZones
        zones = [] if zones is None else str(zones).split()
        if str(self.zone.zone_id) not in zones:
            zones.append(str(self.zone.zone_id))
        new = ' '.join(zones)
        if prev != new:
            self.config.OpsiDaily_MissionZones = new

    def os_daily_clear_all_mission_zones(self):
        """
        清理 OpsiDaily_MissionZones 中记录的所有区域。

        仅在距大世界重置不足 1 天时执行，按顺时针顺序前往各区域清理。

        Raises:
            ActionPointLimit: 行动力不足时跳过当前区域。
        """
        if get_os_reset_remain() > 0:
            logger.info('More than 1 day to OpSi reset, skip OS clear mission zones')
            return

        def os_daily_check_zone(zone):
            return zone.hazard_level in [3, 4, 5, 6] and zone.region != 5 and not zone.is_port

        try:
            zones = self.config.cross_get('OpsiDaily.OpsiDaily.MissionZones')
            zones = [] if zones is None else str(zones).split()
            clear_zones = SelectedGrids([self.name_to_zone(zone) for zone in zones]) \
                .delete(SelectedGrids([self.zone])) \
                .filter(os_daily_check_zone) \
                .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)
        except ScriptError:
            logger.warning('Invalid zones setting, skip OS clear mission zones')
            zones = []

        for zone in clear_zones:
            logger.hr(f'OS clear mission zones, zone_id={zone.zone_id}', level=1)
            try:
                self.globe_goto(zone, types='SAFE', refresh=True)
            except ActionPointLimit:
                continue
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(recon_scan=False, submarine_call=False)
            self.run_auto_search()
            self.handle_after_auto_search()
            if str(zone.zone_id) in zones:
                zones.remove(str(zone.zone_id))
                self.config.cross_set('OpsiDaily.OpsiDaily.MissionZones', ' '.join(zones))

        if not len(zones):
            self.config.cross_set('OpsiDaily.OpsiDaily.MissionZones', None)

    def os_finish_daily_mission(self, skip_siren_mission=False, keep_mission_zone=False, question=True, rescan=None):
        """
        完成大世界中的所有每日任务。建议先运行 os_port_daily 接取任务。

        Args:
            skip_siren_mission (bool): 是否跳过塞壬研究任务。
            keep_mission_zone (bool): 是否保留任务区域不清理。
            question (bool): 传给 run_auto_search 的参数。
            rescan (None, bool): 传给 run_auto_search 的参数。

        Returns:
            int: 完成的任务数量。

        Pages:
            in: page_os, 大世界地图
            out: page_os, 大世界地图
        """
        logger.hr('OS finish daily mission', level=1)
        count = 0
        # 防止港口类型每日任务的无限刷新循环（如对话/拾取/商店交互等自动搜索无法完成的情况）
        stuck_port_zone_id = None
        stuck_port_retry = 0
        abort_due_to_stuck_port = False
        while True:
            result = self.os_get_next_mission(skip_siren_mission=skip_siren_mission)
            if not result:
                break

            if result != 'pinned_at_archive_zone':
                # 档案海域的名称是 "archive zone"，不是已存在的区域。
                # 完成档案海域后会自动返回之前的区域。
                self.zone_init()
            if result == 'already_at_mission_zone':
                self.globe_goto(self.zone, refresh=True)
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(
                recon_scan=False,
                submarine_call=self.config.OpsiFleet_Submarine and result != 'pinned_at_archive_zone')
            if keep_mission_zone and not self.zone.is_port:
                interrupt = [self.daily_interrupt_check, self.is_meowfficer_searching]
                self.config.OS_MISSION_COMPLETE = False
            else:
                interrupt = None
            try:
                finished_combat = self.run_auto_search(question, rescan, interrupt=interrupt)
                self.handle_after_auto_search()
            except TaskEnd:
                self.ui_ensure(page_os)
                if keep_mission_zone:
                    self.os_daily_set_keep_mission_zone()
                finished_combat = 0

            # 检测港口中的重复无进展循环，提前停止本轮运行。
            # 防止无尽的"刷新当前区域"来回切换。
            if self.zone.is_port and finished_combat == 0 and result in (
                    'already_at_mission_zone', 'pinned_at_mission_zone'):
                zone_id = self.zone.zone_id
                if stuck_port_zone_id == zone_id:
                    stuck_port_retry += 1
                else:
                    stuck_port_zone_id = zone_id
                    stuck_port_retry = 1

                if stuck_port_retry >= 3:
                    logger.warning(
                        f'Port mission appears stuck in zone {zone_id} '
                        f'({self.zone}). Auto-search made no progress after '
                        f'{stuck_port_retry} retries. Stop OpsiDaily to avoid '
                        f'infinite zone refresh loop.')
                    abort_due_to_stuck_port = True
                    break
            else:
                stuck_port_zone_id = None
                stuck_port_retry = 0
            count += 1
            if not keep_mission_zone:
                self.config.check_task_switch()

        if abort_due_to_stuck_port:
            # 返回 0 让外层 OpsiDaily 流程干净地退出本轮
            return 0

        return count

    def os_daily(self):
        # 清理调谐样本
        if self.config.OpsiDaily_UseTuningSample:
            self.tuning_sample_use(quit=not self.config.OpsiGeneral_UseLogger)
        if self.config.OpsiGeneral_UseLogger:
            self.logger_use()

        if self.config.OpsiDaily_SkipSirenResearchMission and self.config.SERVER not in ['cn']:
            logger.warning(f'OpsiDaily.SkipSirenResearchMission is not supported in {self.config.SERVER}')
            self.config.OpsiDaily_SkipSirenResearchMission = False
        if self.config.OpsiDaily_KeepMissionZone and self.config.SERVER not in ['cn']:
            logger.warning(f'OpsiDaily.KeepMissionZone is not supported in {self.config.SERVER}')
            self.config.OpsiDaily_KeepMissionZone = False

        skip_siren_mission = self.config.OpsiDaily_SkipSirenResearchMission
        while True:
            # 如果无法接收更多每日任务，先完成已有任务再重试
            success = self.os_mission_overview_accept(skip_siren_mission=skip_siren_mission)
            # 重新初始化区域名称
            # MISSION_ENTER 从右侧出现，需确认动画结束，否则会点击到 MAP_GOTO_GLOBE
            self.zone_init()
            if self.os_finish_daily_mission(
                    skip_siren_mission=skip_siren_mission,
                    keep_mission_zone=self.config.OpsiDaily_KeepMissionZone) and skip_siren_mission:
                continue
            if self.is_in_opsi_explore():
                self.os_port_mission()
                break
            if success:
                break

        if self.config.OpsiDaily_KeepMissionZone:
            if self.zone.is_azur_port:
                logger.info('Already in azur port')
            else:
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
            self.os_daily_clear_all_mission_zones()
        self.config.task_delay(server_update=True)
