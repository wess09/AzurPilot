from datetime import datetime, timedelta

from module.config.utils import get_os_next_reset
from module.exception import ScriptError, RequestHumanTakeover
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap


class OpsiCrossMonth(OSMap):
    def os_cross_month_end(self):
        self.config.task_delay(target=get_os_next_reset() - timedelta(minutes=10))
        self.config.task_stop()

    def os_cross_month(self):
        next_reset = get_os_next_reset()
        now = datetime.now()
        logger.attr('OpsiNextReset', next_reset)

        # Check start time
        if next_reset < now:
            raise ScriptError(f'Invalid OpsiNextReset: {next_reset} < {now}')
        if next_reset - now > timedelta(days=3):
            logger.error('Too long to next reset, OpSi might reset already. '
                         'Running OpsiCrossMonth is meaningless, stopped.')
            self.os_cross_month_end()
        if next_reset - now > timedelta(minutes=10):
            logger.error('Too long to next reset, too far from OpSi reset. '
                         'Running OpsiCrossMonth is meaningless, stopped.')
            self.os_cross_month_end()

        # Now we are 10min before OpSi reset
        logger.hr('Wait until OpSi reset', level=1)
        logger.warning('ALAS is now waiting for next OpSi reset, please DO NOT touch the game during wait')
        while True:
            logger.info(f'Wait until {next_reset}')
            now = datetime.now()
            remain = (next_reset - now).total_seconds()
            if remain <= 0:
                break
            else:
                self.device.sleep(min(remain, 60))
                continue

        logger.hr('OpSi reset', level=3)

        def false_func(*args, **kwargs):
            return False

        self.is_in_opsi_explore = false_func
        # self.config.task_switched = false_func
        self.config.override(_disable_task_switch=True)

        logger.hr('OpSi clear daily', level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiFleet_Fleet=self.config.cross_get('OpsiDaily.OpsiFleet.Fleet'),
            OpsiFleet_Submarine=False,
            # Daily
            OpsiDaily_SkipSirenResearchMission=False,
            OpsiDaily_KeepMissionZone=False,
        )
        count = 0
        empty_trial = 0
        while True:
            # If unable to receive more dailies, finish them and try again.
            success = self.os_mission_overview_accept()
            # Re-init zone name
            # MISSION_ENTER appear from the right,
            # need to confirm that the animation has ended,
            # or it will click on MAP_GOTO_GLOBE
            self.zone_init()
            if empty_trial >= 5:
                logger.warning('No Opsi dailies found within 5 min, stop waiting')
                break
            count += self.os_finish_daily_mission()
            if not count:
                logger.warning('Did not receive any OpSi dailies, '
                               'probably game dailies are not refreshed, wait 1 minute')
                empty_trial += 1
                self.device.sleep(60)
                continue
            if success:
                break

        logger.hr('OS clear abyssal', level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
            OpsiGeneral_UseLogger=True,
            # Obscure
            OpsiObscure_SkipHazard2Obscure=self.config.cross_get('OpsiObscure.OpsiObscure.SkipHazard2Obscure'),
            OpsiObscure_ForceRun=True,
            OpsiFleet_Fleet=self.config.cross_get('OpsiObscure.OpsiFleet.Fleet'),
            OpsiFleet_Submarine=False,
            # Abyssal
            OpsiFleetFilter_Filter=self.config.cross_get('OpsiAbyssal.OpsiFleetFilter.Filter'),
            OpsiAbyssal_ForceRun=True,
        )
        while True:
            if self.storage_get_next_item('ABYSSAL', use_logger=True):
                self.zone_init()
                result = self.run_abyssal()
                if not result:
                    self.map_exit()
                self.handle_fleet_repair_by_config(revert=False)
            else:
                break

        logger.hr('OS clear obscure', level=1)
        while True:
            if self.storage_get_next_item('OBSCURE', use_logger=True, 
                    skip_obscure_hazard_2=self.config.OpsiObscure_SkipHazard2Obscure):
                self.zone_init()
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(
                    recon_scan=True,
                    submarine_call=False)
                self.run_auto_search(rescan='current')
                self.map_exit()
                self.handle_after_auto_search()
            else:
                break

        OpsiMeowfficerFarming_HazardLevel = self.config.cross_get('OpsiMeowfficerFarming'
                                                                  '.OpsiMeowfficerFarming'
                                                                  '.HazardLevel')
        logger.hr(f'OS meowfficer farming, hazard_level={OpsiMeowfficerFarming_HazardLevel}', level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_BuyActionPointLimit=0,
            HOMO_EDGE_DETECT=True,
            STORY_OPTION=-2,
            # Meowfficer farming
            OpsiFleet_Fleet=self.config.cross_get('OpsiMeowfficerFarming.OpsiFleet.Fleet'),
            OpsiFleet_Submarine=False,
            OpsiMeowfficerFarming_ActionPointPreserve=0,
            OpsiMeowfficerFarming_HazardLevel=OpsiMeowfficerFarming_HazardLevel,
            OpsiMeowfficerFarming_TargetZone=self.config.cross_get('OpsiMeowfficerFarming.OpsiMeowfficerFarming.TargetZone'),
            OpsiMeowfficerFarming_StayInZone=self.config.cross_get('OpsiMeowfficerFarming.OpsiMeowfficerFarming.StayInZone'),
            OpsiMeowfficerFarming_APPreserveUntilReset=False
        )
        while True:
            if self.config.OpsiMeowfficerFarming_TargetZone != 0:
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
            else:
                zones = self.zone_select(hazard_level=OpsiMeowfficerFarming_HazardLevel) \
                    .delete(SelectedGrids([self.zone])) \
                    .delete(SelectedGrids(self.zones.select(is_port=True))) \
                    .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)
                logger.hr(f'OS meowfficer farming, zone_id={zones[0].zone_id}', level=1)
                self.globe_goto(zones[0])
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(
                    recon_scan=False,
                    submarine_call=False)
                self.run_auto_search()
                self.handle_after_auto_search()
