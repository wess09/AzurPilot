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
        Visit all ports and do the daily mission in it.
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
        Set current zone into OpsiDaily_MissionZones
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
        Clear all zones in OpsiDaily_MissionZones
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
        Finish all daily mission in Operation Siren.
        Suggest to run os_port_daily to accept missions first.

        Args:
            skip_siren_mission (bool): if skip siren research missions
            keep_mission_zone(bool): if keep mission zone and do not clear it
            question (bool): refer to run_auto_search
            rescan (None, bool): refer to run_auto_search

        Returns:
            int: Number of missions finished
        """
        logger.hr('OS finish daily mission', level=1)
        count = 0
        # Guard against infinite refresh loops on port-type daily missions that
        # auto-search cannot finish (e.g. dialogue/pickup/shop interactions).
        stuck_port_zone_id = None
        stuck_port_retry = 0
        abort_due_to_stuck_port = False
        while True:
            result = self.os_get_next_mission(skip_siren_mission=skip_siren_mission)
            if not result:
                break

            if result != 'pinned_at_archive_zone':
                # The name of archive zone is "archive zone", which is not an existing zone.
                # After archive zone, it go back to previous zone automatically.
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

            # Detect repeated no-progress loops at ports and stop this run early.
            # This prevents endless "refresh current zone" ping-pong.
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
            # Return 0 to let outer OpsiDaily flow exit this round cleanly.
            return 0

        return count

    def os_daily(self):
        # Finish existing missions first
        # No need anymore, os_mission_overview_accept() is able to handle
        # self.os_finish_daily_mission()

        # Clear tuning samples daily
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
            # If unable to receive more dailies, finish them and try again.
            success = self.os_mission_overview_accept(skip_siren_mission=skip_siren_mission)
            # Re-init zone name
            # MISSION_ENTER appear from the right,
            # need to confirm that the animation has ended,
            # or it will click on MAP_GOTO_GLOBE
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
