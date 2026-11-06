"""大世界跨月重置模块。

处理大世界每月重置前后的过渡逻辑，包括：
- 重置时间检测和倒计时管理
- 重置前 10 分钟内的紧急操作
- 指定海域的快速清理
- 跨月期间其他任务的延迟协调

继承自 MeowfficerTargetZoneMixin 和 OSMap，
确保在月度重置前完成关键任务，避免资源损失。
"""

from datetime import timedelta

from module.config.time_source import now as current_time
from module.config.utils import get_os_next_reset
from module.exception import ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap
from module.os.tasks.meowfficer_farming import MeowfficerTargetZoneMixin


class OpsiCrossMonth(MeowfficerTargetZoneMixin, OSMap):
    def os_cross_month_end(self):
        """延迟跨月重置任务至下次重置前 10 分钟并停止任务。"""
        self.config.task_delay(target=get_os_next_reset() - timedelta(minutes=10))
        self.config.task_stop()

    def os_cross_month(self):
        """执行大世界跨月任务主流程。

        在月度重置前 10 分钟内等待重置，重置后依次清理每日任务、深渊坐标、
        隐秘海域和指挥喵海域。

        Raises:
            ScriptError: 下次重置时间早于当前时间时抛出。
        """
        next_reset = get_os_next_reset()
        now = current_time()
        logger.attr('大世界下次重置', next_reset)

        # 检查开始时间
        if next_reset < now:
            raise ScriptError(f'Invalid OpsiNextReset: {next_reset} < {now}')
        if next_reset - now > timedelta(days=3):
            logger.error('距离下次大世界重置超过 3 天，大世界可能已经重置，停止跨月每日')
            self.os_cross_month_end()
        if next_reset - now > timedelta(minutes=10):
            logger.error('距离下次大世界重置超过 10 分钟，距离跨月每日执行时间过早，停止任务')
            self.os_cross_month_end()

        # 距离大世界重置还有 10 分钟
        logger.hr('跨月每日等待大世界重置', level=1)
        logger.warning('AzurPilot 正在等待下次大世界重置，等待期间请不要操作游戏')
        while True:
            logger.info(f'等待到 {next_reset}')
            now = current_time()
            remain = (next_reset - now).total_seconds()
            if remain <= 0:
                break
            else:
                self.device.sleep(min(remain, 60))
                continue

        logger.hr('跨月每日处理大世界重置', level=3)

        def false_func(*args, **kwargs):
            return False

        self.is_in_opsi_explore = false_func
        self.config.override(_disable_task_switch=True)

        logger.hr('跨月每日清理大世界每日', level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiFleet_Fleet=self.config.cross_get('OpsiDaily.OpsiFleet.Fleet'),
            OpsiFleet_Submarine=False,
            # 每日任务
            OpsiDaily_SkipSirenResearchMission=False,
            OpsiDaily_KeepMissionZone=False,
        )
        count = 0
        empty_trial = 0
        while True:
            # 如果无法接收更多每日任务，先完成已有任务再重试
            success = self.os_mission_overview_accept()
            # 重新初始化区域名称
            # MISSION_ENTER 从右侧出现，需确认动画结束，否则会点击到 MAP_GOTO_GLOBE
            self.zone_init()
            if empty_trial >= 5:
                logger.warning('5 分钟内没有找到大世界每日，停止等待')
                break
            count += self.os_finish_daily_mission()
            if not count:
                logger.warning('未接取到大世界每日，可能游戏每日尚未刷新，等待 1 分钟')
                empty_trial += 1
                self.device.sleep(60)
                continue
            if success:
                break

        logger.hr('跨月每日清理深渊坐标', level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
            OpsiGeneral_UseLogger=True,
            # 隐秘海域
            OpsiObscure_SkipHazard2Obscure=self.config.cross_get('OpsiObscure.OpsiObscure.SkipHazard2Obscure'),
            OpsiObscure_ForceRun=True,
            OpsiFleet_Fleet=self.config.cross_get('OpsiObscure.OpsiFleet.Fleet'),
            OpsiFleet_Submarine=False,
            # 深渊坐标
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

        logger.hr('跨月每日清理隐秘海域', level=1)
        while True:
            if self.storage_get_next_item('OBSCURE', use_logger=True, 
                    skip_obscure_hazard_2=self.config.OpsiObscure_SkipHazard2Obscure):
                self.zone_init()
                self._save_obscure_resume()
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(
                    recon_scan=True,
                    submarine_call=False)
                self.run_auto_search(rescan='current', exit_map=True, on_map_scanned=self._obscure_after_scan)
                self.config.cross_set('OpsiObscure.OpsiObscure.ResumeState', None)
                self.handle_after_auto_search()
            else:
                break

        OpsiMeowfficerFarming_HazardLevel = self.config.cross_get('OpsiMeowfficerFarming'
                                                                  '.OpsiMeowfficerFarming'
                                                                  '.HazardLevel')
        logger.hr(f'跨月每日清理耄耋相接, hazard_level={OpsiMeowfficerFarming_HazardLevel}', level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_BuyActionPointLimit=0,
            HOMO_EDGE_DETECT=True,
            STORY_OPTION=-2,
            # 耄耋相接
            OpsiFleet_Fleet=self.config.cross_get('OpsiMeowfficerFarming.OpsiFleet.Fleet'),
            OpsiFleet_Submarine=False,
            OpsiMeowfficerFarming_ActionPointPreserve=0,
            OpsiMeowfficerFarming_HazardLevel=OpsiMeowfficerFarming_HazardLevel,
            OpsiMeowfficerFarming_TargetZone=self.config.cross_get('OpsiMeowfficerFarming.OpsiMeowfficerFarming.TargetZone'),
            OpsiMeowfficerFarming_StayInZone=self.config.cross_get('OpsiMeowfficerFarming.OpsiMeowfficerFarming.StayInZone'),
        )
        target_zone_tokens = self._meow_target_zone_tokens()
        target_zones = []
        traditional_zone = None
        target_zone_index = 0
        if self.config.OpsiMeowfficerFarming_StayInZone:
            target_zones = self._meow_target_zones(require_target=True, allow_multiple=True)
        elif target_zone_tokens:
            traditional_zone = self._meow_target_zones(require_target=False, allow_multiple=False)[0]

        while True:
            if target_zones or traditional_zone is not None:
                if target_zones:
                    zone, _ = self._meow_target_zone_at(target_zones, target_zone_index)
                    target_zone_index += 1
                else:
                    zone = traditional_zone
                    logger.hr(f'跨月每日清理耄耋相接, zone_id={zone.zone_id}', level=1)
                if len(target_zones) > 1:
                    self.globe_goto(zone)
                    self.fleet_set(self.config.OpsiFleet_Fleet)
                    self.os_order_execute(
                        recon_scan=False,
                        submarine_call=False)
                    self.run_auto_search()
                    self.handle_after_auto_search()
                else:
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
                logger.hr(f'跨月每日清理耄耋相接, zone_id={zones[0].zone_id}', level=1)
                self.globe_goto(zones[0])
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(
                    recon_scan=False,
                    submarine_call=False)
                self.run_auto_search()
                self.handle_after_auto_search()
