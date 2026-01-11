from datetime import datetime, timedelta

import numpy as np

from module.config.config import TaskEnd
from module.config.utils import (get_nearest_weekday_date,
                                 get_os_next_reset,
                                 get_os_reset_remain,
                                 get_server_next_update,
                                 DEFAULT_TIME)
# 此文件是大世界（Operation Siren）模式的具体任务执行类。
# 整合了从每日任务、商店购买到深渊清剿、全地图探索以及特定层级（如危险 1）挂机等各项大世界自动化攻略逻辑。
from module.exception import RequestHumanTakeover, GameStuckError, ScriptError
from module.equipment.assets import EQUIPMENT_OPEN
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.notify import handle_notify
from module.os.assets import FLEET_FLAGSHIP
from module.os.fleet import BossFleet
from module.os.globe_operation import OSExploreError
from module.os.map import OSMap
from module.os.ship_exp import ship_info_get_level_exp
from module.os.ship_exp_data import LIST_SHIP_EXP
from module.os_handler.action_point import OCR_OS_ADAPTABILITY, ActionPointLimit
from module.os_handler.assets import (OS_MONTHBOSS_NORMAL, OS_MONTHBOSS_HARD, OS_SUBMARINE_EMPTY,
                                      EXCHANGE_CHECK, EXCHANGE_ENTER, MISSION_COMPLETE_POPUP)
from module.os_shop.assets import OS_SHOP_CHECK
from module.shop.shop_voucher import VoucherShop
from module.ui.assets import OS_CHECK
from module.ui.page import page_os


class OperationSiren(OSMap):
    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except Exception as e:
            logger.exception("OperationSiren init failed")
            raise

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
                self.run_auto_search(question, rescan, interrupt=interrupt)
                self.handle_after_auto_search()
            except TaskEnd:
                self.ui_ensure(page_os)
                if keep_mission_zone:
                    self.os_daily_set_keep_mission_zone()
            count += 1
            if not keep_mission_zone:
                self.config.check_task_switch()

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
        self.config.task_switched = false_func

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

    def os_shop(self):
        """
        Buy all supplies in all ports.
        If not having enough yellow coins or purple coins, skip buying supplies in next port.
        """
        logger.hr('OS port daily', level=1)
        today = datetime.now().day
        limit = self.config.OpsiShop_DisableBeforeDate
        if today <= limit:
            logger.info(f'Delay Opsi shop, today\'s date {today} <= limit {limit}')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        if not self.zone.is_azur_port:
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

        self.port_enter()
        self.port_shop_enter()

        if self.appear(OS_SHOP_CHECK):
            not_empty = self.handle_port_supply_buy()
            next_reset = self._os_shop_delay(not_empty)
            logger.info('OS port daily finished, delay to next reset')
            logger.attr('OpsiShopNextReset', next_reset)
        else:
            next_reset = get_os_next_reset()
            logger.warning('There is no shop in the port, skip to the next month.')
            logger.attr('OpsiShopNextReset', next_reset)

        self.port_shop_quit()
        self.port_quit()

        self.config.task_delay(target=next_reset)
        self.config.task_stop()

    def _os_shop_delay(self, not_empty) -> datetime:
        """
        Calculate the delay of OpsiShop.

        Args:
            not_empty (bool): Indicates whether the shop is not empty.

        Returns:
            datetime: The time of the next shop reset.
        """
        next_reset = None

        if not_empty:
            next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
        else:
            remain = get_os_reset_remain()
            next_reset = get_os_next_reset()
            if remain == 0:
                next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
            elif remain < 7:
                next_reset = next_reset - timedelta(days=1)
            else:
                next_reset = (
                    get_server_next_update(self.config.Scheduler_ServerUpdate) +
                    timedelta(days=6)
                )
        return next_reset

    def _os_voucher_enter(self):
        self.os_map_goto_globe(unpin=False)
        self.ui_click(click_button=EXCHANGE_ENTER, check_button=EXCHANGE_CHECK,
                      offset=(200, 20), retry_wait=3, skip_first_screenshot=True)

    def _os_voucher_exit(self):
        self.ui_back(check_button=EXCHANGE_ENTER, appear_button=EXCHANGE_CHECK,
                     offset=(200, 20), retry_wait=3, skip_first_screenshot=True)
        self.os_globe_goto_map()

    def os_voucher(self):
        logger.hr('OS voucher', level=1)
        self._os_voucher_enter()
        VoucherShop(self.config, self.device).run()
        self._os_voucher_exit()

        next_reset = get_os_next_reset()
        logger.info('OS voucher finished, delay to next reset')
        logger.attr('OpsiNextReset', next_reset)
        self.config.task_delay(target=next_reset)

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
            
        # 导入并调用推送通知模块
        from module.notify.notify import handle_notify
        try:
            success = handle_notify(
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
            
        # 初始化上次通知的阈值记录（首次调用时为 None）
        if not hasattr(self, '_last_notified_ap_threshold'):
            self._last_notified_ap_threshold = None
        
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
        
        # 如果跨越了阈值区间，发送推送通知
        if current_threshold != self._last_notified_ap_threshold:
            if current_threshold is not None:
                # 判断是升至还是降至该阈值
                if self._last_notified_ap_threshold is None:
                    # 首次检测，直接通知当前所在区间
                    direction = "当前"
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
            elif self._last_notified_ap_threshold is not None:
                # 降到最低阈值以下
                lowest = min(thresholds)
                self.notify_push(
                    title="[Alas] 行动力阈值变化", 
                    content=f"行动力降至{lowest}以下 (当前: {current_ap})"
                )
            
            # 更新上次通知的阈值记录
            self._last_notified_ap_threshold = current_threshold

    def os_meowfficer_farming(self):
        """
        Recommend 3 or 5 for higher meowfficer searching point per action points ratio.
        """
        logger.hr(f'OS meowfficer farming, hazard_level={self.config.OpsiMeowfficerFarming_HazardLevel}', level=1)
        if self.is_cl1_enabled and self.config.OpsiMeowfficerFarming_ActionPointPreserve < 500:
            logger.info('With CL1 leveling enabled, set action point preserve to 500')
            self.config.OpsiMeowfficerFarming_ActionPointPreserve = 500
        preserve = min(self.get_action_point_limit(self.config.OpsiMeowfficerFarming_APPreserveUntilReset),
                       self.config.OpsiMeowfficerFarming_ActionPointPreserve)
        if preserve == 0:
            self.config.override(OpsiFleet_Submarine=False)
        if self.is_cl1_enabled:
            # Without these enabled, CL1 gains 0 profits
            self.config.override(
                OpsiGeneral_DoRandomMapEvent=True,
                OpsiGeneral_AkashiShopFilter='ActionPoint',
                OpsiFleet_Submarine=False,
            )
            cd = self.nearest_task_cooling_down
            logger.attr('Task cooling down', cd)
            # At the last day of every month, OpsiObscure and OpsiAbyssal are scheduled frequently
            # Don't schedule after them
            remain = get_os_reset_remain()
            if cd is not None and remain > 0:
                logger.info(f'Having task cooling down, delay OpsiMeowfficerFarming after it')
                self.config.task_delay(target=cd.next_run)
                self.config.task_stop()
        if self.is_in_opsi_explore():
            logger.warning(f'OpsiExplore is still running, cannot do {self.config.task.command}')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        ap_checked = False
        while True:
            self.config.OS_ACTION_POINT_PRESERVE = preserve
            if self.config.is_task_enabled('OpsiAshBeacon') \
                    and not self._ash_fully_collected \
                    and self.config.OpsiAshBeacon_EnsureFullyCollected:
                logger.info('Ash beacon not fully collected, ignore action point limit temporarily')
                self.config.OS_ACTION_POINT_PRESERVE = 0
            logger.attr('OS_ACTION_POINT_PRESERVE', self.config.OS_ACTION_POINT_PRESERVE)
            if not ap_checked:
                # Check action points first to avoid using remaining AP when it not enough for tomorrow's daily
                # When not running CL1 and use oil
                keep_current_ap = True
                check_rest_ap = True
                if self.is_cl1_enabled and self.get_yellow_coins() >= self.config.OpsiHazard1Leveling_OperationCoinsPreserve:
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
                ap_checked = True
                
                # ===== 智能调度: 行动力阈值推送检查 =====
                # 在设置行动力后检查是否跨越阈值并推送通知
                self.check_and_notify_action_point_threshold()
                
                # ===== 智能调度: 短猫相接行动力不足检查 =====
                # 检查当前行动力是否低于配置的保留值
                if getattr(self.config, 'OpsiScheduling_EnableSmartScheduling', False):

                    if self._action_point_total < self.config.OpsiMeowfficerFarming_ActionPointPreserve:
                        logger.info(f'【智能调度】短猫相接行动力不足 ({self._action_point_total} < {self.config.OpsiMeowfficerFarming_ActionPointPreserve})')
                        
                        # 获取当前黄币数量
                        yellow_coins = self.get_yellow_coins()
                        
                        # 推送通知
                        if self.is_cl1_enabled:
                            self.notify_push(
                                title="[Alas] 短猫相接 - 切换至侵蚀1",
                                content=f"行动力 {self._action_point_total} 不足 (需要 {self.config.OpsiMeowfficerFarming_ActionPointPreserve})\n黄币: {yellow_coins}\n推迟短猫1小时，切换至侵蚀1继续执行"
                            )
                        else:
                            self.notify_push(
                                title="[Alas] 短猫相接 - 行动力不足",
                                content=f"行动力 {self._action_point_total} 不足 (需要 {self.config.OpsiMeowfficerFarming_ActionPointPreserve})\n黄币: {yellow_coins}\n推迟1小时"
                            )
                        
                        # 推迟短猫1小时
                        logger.info('推迟短猫相接1小时')
                        self.config.task_delay(minute=60)
                        
                        # 如果启用了侵蚀1，立即切换回侵蚀1继续执行
                        if self.is_cl1_enabled:
                            logger.info('切换回侵蚀1继续执行')
                            with self.config.multi_set():
                                self.config.task_call('OpsiHazard1Leveling')
                        
                        # 停止当前短猫任务
                        self.config.task_stop()

            # (1252, 1012) is the coordinate of zone 134 (the center zone) in os_globe_map.png
            if self.config.OpsiMeowfficerFarming_TargetZone != 0 and not self.config.OpsiMeowfficerFarming_StayInZone:
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
                    self.config.check_task_switch()
                continue

            if self.config.OpsiMeowfficerFarming_StayInZone:
                if self.config.OpsiMeowfficerFarming_TargetZone == 0:
                    logger.warning('StayInZone 已启用但未设置 TargetZone，跳过本次出击')
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
                try:
                    zone = self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
                except ScriptError:
                    logger.error('无法定位配置的 TargetZone，停止任务')
                    self.config.task_delay(server_update=True)
                    self.config.task_stop()
                logger.hr(f'OS meowfficer farming (stay in zone), zone_id={zone.zone_id}', level=1)
                self.get_current_zone()
                if self.zone.zone_id != zone.zone_id or not self.is_zone_name_hidden:
                    self.globe_goto(zone, types='SAFE', refresh=True)

                #self.config.OS_ACTION_POINT_PRESERVE = 0
                keep_current_ap = True
                if self.config.OpsiGeneral_BuyActionPointLimit > 0:
                    keep_current_ap = False

                self.action_point_set(cost=120, keep_current_ap=keep_current_ap, check_rest_ap=True)
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)
                search_completed = False
                try:
                    search_completed = self.run_strategic_search()
                except TaskEnd:
                    raise
                except Exception as e:
                    logger.warning(f'Strategic search exception: {e}')

                if search_completed:
                    self._solved_map_event = set()
                    self._solved_fleet_mechanism = False
                    self.clear_question()
                    self.map_rescan()

                try:
                    self.handle_after_auto_search()
                except Exception:
                    logger.exception('Exception in handle_after_auto_search')

                #if not self.is_zone_name_hidden:
                #    try:
                #        self.globe_goto(zone, types='SAFE', refresh=True)
                #    except Exception as e2:
                #        logger.warning(f'重新进入目标海域失败: {e2}')

                self.config.check_task_switch()
                continue

            zones = self.zone_select(hazard_level=self.config.OpsiMeowfficerFarming_HazardLevel) \
                .delete(SelectedGrids([self.zone])) \
                .delete(SelectedGrids(self.zones.select(is_port=True))) \
                .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)

            logger.hr(f'OS meowfficer farming, zone_id={zones[0].zone_id}', level=1)
            self.globe_goto(zones[0])
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(
                recon_scan=False,
                submarine_call=self.config.OpsiFleet_Submarine)
            self.run_auto_search()
            self.handle_after_auto_search()
            self.config.check_task_switch()

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
                    if self._action_point_total < meow_ap_preserve:
                        # 行动力也不足，推迟并推送通知
                        logger.warning(f'行动力不足以执行短猫 ({self._action_point_total} < {meow_ap_preserve})')

                        self.notify_push(
                            title="[Alas] 侵蚀1 - 黄币与行动力双重不足",
                            content=f"黄币 {yellow_coins} 低于保留值 {self.config.OpsiHazard1Leveling_OperationCoinsPreserve}\n行动力 {self._action_point_total} 不足 (需要 {meow_ap_preserve})\n推迟1小时"
                        )

                        logger.info('推迟侵蚀1任务1小时')
                        self.config.task_delay(minute=60)
                        self.config.task_stop()
                    else:
                        # 行动力充足，切换到短猫相接获取黄币
                        logger.info(f'行动力充足 ({self._action_point_total}), 切换到短猫相接获取黄币')
                        self.notify_push(
                            title="[Alas] 侵蚀1 - 切换至短猫相接",
                            content=f"黄币 {yellow_coins} 低于保留值 {self.config.OpsiHazard1Leveling_OperationCoinsPreserve}\n行动力: {self._action_point_total} (需要 {meow_ap_preserve})\n切换至短猫相接获取黄币"
                        )

                        with self.config.multi_set():
                            self.config.task_call('OpsiMeowfficerFarming')
                        self.config.task_stop()
            else:
                # 未启用智能调度，保持原有逻辑
                if yellow_coins < self.config.OpsiHazard1Leveling_OperationCoinsPreserve:
                    logger.info(f'Reach the limit of yellow coins, preserve={self.config.OpsiHazard1Leveling_OperationCoinsPreserve}')
                    with self.config.multi_set():
                        self.config.task_delay(server_update=True)
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

                    self.notify_push(
                        title="[Alas] 侵蚀1 - 行动力低于最低保留",
                        content=f"当前行动力 {self._action_point_total} 低于最低保留 {min_reserve}，推迟1小时"
                    )

                    logger.info('推迟侵蚀1任务1小时')
                    self.config.task_delay(minute=60)
                    self.config.task_stop()

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
            if search_completed:
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
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"Alas <{self.config.config_name}> level check passed",
                content=f"<{self.config.config_name}> {self.config.task} reached level limit {target_level} or above."
            )
        self.ui_back(appear_button=EQUIPMENT_OPEN, check_button=self.is_in_map)
        self.config.OpsiCheckLeveling_LastRun = datetime.now().replace(microsecond=0)
        if all_full_exp and self.config.OpsiCheckLeveling_DelayAfterFull:
            logger.info('Delay task after all ships are full exp')
            self.config.task_delay(server_update=True)
            self.config.task_stop()


    def _os_explore_task_delay(self):
        """
        Delay other OpSi tasks during os_explore
        """
        logger.info('Delay other OpSi tasks during OpsiExplore')
        with self.config.multi_set():
            next_run = self.config.Scheduler_NextRun
            for task in ['OpsiObscure', 'OpsiAbyssal', 'OpsiArchive', 'OpsiStronghold', 'OpsiMeowfficerFarming',
                         'OpsiMonthBoss', 'OpsiShop']:
                keys = f'{task}.Scheduler.NextRun'
                current = self.config.cross_get(keys=keys, default=DEFAULT_TIME)
                if current < next_run:
                    logger.info(f'Delay task `{task}` to {next_run}')
                    self.config.cross_set(keys=keys, value=next_run)

    # List of failed zone id
    _os_explore_failed_zone = []

    def _os_explore(self):
        """
        Explore all dangerous zones at the beginning of month.
        Failed zone id will be set to _os_explore_failed_zone
        """

        def end():
            logger.info('OS explore finished, delay to next reset')
            next_reset = get_os_next_reset()
            logger.attr('OpsiNextReset', next_reset)
            logger.info('To run again, clear OpsiExplore.Scheduler.NextRun and set OpsiExplore.OpsiExplore.LastZone=0')
            with self.config.multi_set():
                self.config.OpsiExplore_LastZone = 0
                self.config.OpsiExplore_SpecialRadar = False
                self.config.task_delay(target=next_reset)
                self.config.task_call('OpsiDaily', force_call=False)
                self.config.task_call('OpsiShop', force_call=False)
                self.config.task_call('OpsiHazard1Leveling', force_call=False)
            self.config.task_stop()

        logger.hr('OS explore', level=1)
        order = [int(f.strip(' \t\r\n')) for f in self.config.OS_EXPLORE_FILTER.split('>')]
        # Convert user input
        try:
            last_zone = self.name_to_zone(self.config.OpsiExplore_LastZone).zone_id
        except ScriptError:
            logger.warning(f'Invalid OpsiExplore_LastZone={self.config.OpsiExplore_LastZone}, re-explore')
            last_zone = 0
        # Start from last zone
        if last_zone in order:
            order = order[order.index(last_zone) + 1:]
            logger.info(f'Last zone: {self.name_to_zone(last_zone)}, next zone: {order[:1]}')
        elif last_zone == 0:
            logger.info(f'First run, next zone: {order[:1]}')
        else:
            raise ScriptError(f'Invalid last_zone: {last_zone}')
        if not len(order):
            end()

        # Run
        self._os_explore_failed_zone = []
        for zone in order:
            # Check if zone already unlock safe zone
            if not self.globe_goto(zone, stop_if_safe=True):
                logger.info(f'Zone cleared: {self.name_to_zone(zone)}')
                self.config.OpsiExplore_LastZone = zone
                continue

            # Run zone
            logger.hr(f'OS explore {zone}', level=1)
            if not self.config.OpsiExplore_SpecialRadar:
                # Special radar gives 90 turning samples,
                # If no special radar, use the turning samples in storage to acquire stronger fleets.
                self.tuning_sample_use()
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(
                recon_scan=not self.config.OpsiExplore_SpecialRadar,
                submarine_call=self.config.OpsiFleet_Submarine)
            self._os_explore_task_delay()

            finished_combat = self.run_auto_search()
            self.config.OpsiExplore_LastZone = zone
            logger.info(f'Zone cleared: {self.name_to_zone(zone)}')
            if finished_combat == 0:
                logger.warning('Zone cleared but did not finish any combat')
                self._os_explore_failed_zone.append(zone)
            self.handle_after_auto_search()
            self.config.check_task_switch()

            # Reached end
            if zone == order[-1]:
                end()

    def os_explore(self):
        for _ in range(2):
            try:
                self._os_explore()
            except OSExploreError:
                logger.info('Go back to NY, explore again')
                self.config.OpsiExplore_LastZone = 0
                self.globe_goto(0)

        failed_zone = [self.name_to_zone(zone) for zone in self._os_explore_failed_zone]
        logger.error(f'OpsiExplore failed at these zones, please check you game settings '
                     f'and check if there is any unfinished event in them: {failed_zone}')
        logger.critical('Failed to solve the locked zone')
        raise GameStuckError

    def clear_obscure(self):
        """
        Raises:
            ActionPointLimit:
        """
        logger.hr('OS clear obscure', level=1)
        self.cl1_ap_preserve()
        if self.config.OpsiObscure_ForceRun:
            logger.info('OS obscure finish is under force run')

        result = self.storage_get_next_item('OBSCURE', use_logger=self.config.OpsiGeneral_UseLogger,
                                            skip_obscure_hazard_2=self.config.OpsiObscure_SkipHazard2Obscure)
        if not result:
            # No obscure coordinates, delay next run to tomorrow.
            if get_os_reset_remain() > 0:
                self.config.task_delay(server_update=True)
            else:
                logger.info('Just less than 1 day to OpSi reset, delay 2.5 hours')
                self.config.task_delay(minute=150, server_update=True)
            self.config.task_stop()

        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
        )
        self.zone_init()
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(
            recon_scan=True,
            submarine_call=self.config.OpsiFleet_Submarine)
        self.run_auto_search(rescan='current')

        self.map_exit()
        self.handle_after_auto_search()

    def os_obscure(self):
        while True:
            self.clear_obscure()
            if self.config.OpsiObscure_ForceRun:
                self.config.check_task_switch()
                continue
            else:
                break

    def delay_abyssal(self, result=True):
        """
        Args:
            result(bool): If still have obscure coordinates.
        """
        if get_os_reset_remain() == 0:
            logger.info('Just less than 1 day to OpSi reset, delay 2.5 hours')
            self.config.task_delay(minute=150, server_update=True)
            self.config.task_stop()
        elif not result:
            self.config.task_delay(server_update=True)
            self.config.task_stop()

    def clear_abyssal(self):
        """
        Get one abyssal logger in storage,
        attack abyssal boss,
        repair fleets in port.

        Raises:
            ActionPointLimit:
            TaskEnd: If no more abyssal loggers.
            RequestHumanTakeover: If unable to clear boss, fleets exhausted.
        """
        logger.hr('OS clear abyssal', level=1)
        self.cl1_ap_preserve()

        with self.config.temporary(STORY_ALLOW_SKIP=False):
            result = self.storage_get_next_item('ABYSSAL', use_logger=self.config.OpsiGeneral_UseLogger)
        if not result:
            self.delay_abyssal(result=False)

        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0
        )
        self.zone_init()
        result = self.run_abyssal()
        if not result:
            raise RequestHumanTakeover

        self.handle_fleet_repair_by_config(revert=False)
        self.delay_abyssal()

    def os_abyssal(self):
        while True:
            self.clear_abyssal()
            self.config.check_task_switch()

    def os_archive(self):
        """
        Complete active archive zone in daily mission
        Purchase next available logger archive then repeat
        until exhausted

        Run on weekly basis, AL devs seemingly add new logger
        archives after random scheduled maintenances
        """
        if self.is_in_opsi_explore():
            logger.info('OpsiExplore is under scheduling, stop OpsiArchive')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        shop = VoucherShop(self.config, self.device)
        while True:
            # In case logger bought manually,
            # finish pre-existing archive zone
            self.os_finish_daily_mission(
                skip_siren_mission=self.config.cross_get('OpsiDaily.OpsiDaily.SkipSirenResearchMission'),
                question=False, rescan=False)

            logger.hr('OS voucher', level=1)
            self._os_voucher_enter()
            bought = shop.run_once()
            self._os_voucher_exit()
            if not bought:
                break

        # Reset to nearest 'Wednesday' date
        next_reset = get_nearest_weekday_date(target=2)
        logger.info('All archive zones finished, delay to next reset')
        logger.attr('OpsiNextReset', next_reset)
        self.config.task_delay(target=next_reset)

    def clear_stronghold(self):
        """
        Find a siren stronghold on globe map,
        clear stronghold,
        repair fleets in port.

        Raises:
            ActionPointLimit:
            TaskEnd: If no more strongholds.
            RequestHumanTakeover: If unable to clear boss, fleets exhausted.
        """
        logger.hr('OS clear stronghold', level=1)
        with self.config.multi_set():
            self.config.OpsiStronghold_HasStronghold = True
            self.cl1_ap_preserve()

            self.os_map_goto_globe()
            self.globe_update()
            zone = self.find_siren_stronghold()
            if zone is None:
                # No siren stronghold, delay next run to tomorrow.
                self.config.OpsiStronghold_HasStronghold = False
                self.config.task_delay(server_update=True)
                self.config.task_stop()

        self.globe_enter(zone)
        self.zone_init()
        self.os_order_execute(recon_scan=True, submarine_call=False)
        self.run_stronghold(submarine=self.config.OpsiStronghold_SubmarineEveryCombat)

        if self.config.OpsiStronghold_SubmarineEveryCombat:
            if self.zone.is_azur_port:
                logger.info('Already in azur port')
            else:
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
        self.handle_fleet_repair_by_config(revert=False)
        self.handle_fleet_resolve(revert=False)

    def os_stronghold(self):
        while True:
            self.clear_stronghold()
            self.config.check_task_switch()

    def os_sumbarine_empty(self):
        return self.match_template_color(OS_SUBMARINE_EMPTY, offset=(20, 20))

    def stronghold_interrupt_check(self):
        return self.os_sumbarine_empty() and self.no_meowfficer_searching()

    def run_stronghold_one_fleet(self, fleet, submarine=False):
        """
        Args
            fleet (BossFleet):
            submarine (bool): If use submarine every combat

        Returns:
            bool: If all cleared.
        """
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0
        )
        interrupt = [self.stronghold_interrupt_check, self.is_meowfficer_searching] if submarine else None
        # Try 3 times, because fleet may stuck in fog.
        for _ in range(3):
            # Attack
            self.fleet_set(fleet.fleet_index)
            try:
                self.run_auto_search(question=False, rescan=False, interrupt=interrupt)
            except TaskEnd:
                self.ui_ensure(page_os)
            self.hp_reset()
            self.hp_get()

            # End
            if self.get_stronghold_percentage() == '0':
                logger.info('BOSS clear')
                return True
            elif any(self.need_repair):
                logger.info('Auto search stopped, because fleet died')
                # Re-enter to reset fleet position
                prev = self.zone
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
                self.handle_fog_block(repair=True)
                self.globe_goto(prev, types='STRONGHOLD')
                return False
            elif submarine and self.os_sumbarine_empty():
                logger.info('Submarine ammo exhausted, wait for the next clear')
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
                return True
            else:
                logger.info('Auto search stopped, because fleet stuck')
                # Re-enter to reset fleet position
                prev = self.zone
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
                self.handle_fog_block(repair=False)
                self.globe_goto(prev, types='STRONGHOLD')
                continue

    def run_stronghold(self, submarine=False):
        """
        All fleets take turns in attacking siren stronghold.
        Args:
            submarine (bool): If use submarine every combat

        Returns:
            bool: If success to clear.

        Pages:
            in: Siren logger (abyssal), boss appeared.
            out: If success, dangerous or safe zone.
                If failed, still in abyssal.
        """
        logger.hr(f'Stronghold clear', level=1)
        fleets = self.parse_fleet_filter()
        for fleet in fleets:
            logger.hr(f'Turn: {fleet}', level=2)
            if not isinstance(fleet, BossFleet):
                self.os_order_execute(recon_scan=False, submarine_call=True)
                continue

            result = self.run_stronghold_one_fleet(fleet, submarine=submarine)
            if result:
                return True
            else:
                continue

        logger.critical('Unable to clear boss, fleets exhausted')
        return False

    def get_adaptability(self):
        adaptability = OCR_OS_ADAPTABILITY.ocr(self.device.image)

        return adaptability

    def clear_month_boss(self):
        """
        check adaptability
        check current boss difficulty
        clear boss
        repair fleets in port

        Raises:
            ActionPointLimit
            TaskEnd: if no more month boss
        """
        if self.is_in_opsi_explore():
            logger.info('OpsiExplore is under scheduling, stop OpsiMonthBoss')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        logger.hr("OS clear Month Boss", level=1)
        logger.hr("Month Boss precheck", level=2)
        checkout_offset = self.os_mission_enter(
            skip_siren_mission=self.config.cross_get('OpsiDaily.OpsiDaily.SkipSirenResearchMission'))
        logger.attr('OpsiMonthBoss.Mode', self.config.OpsiMonthBoss_Mode)
        if self.appear(OS_MONTHBOSS_NORMAL, offset=checkout_offset):
            logger.attr('Month boss difficulty', 'normal')
            is_normal = True
        elif self.appear(OS_MONTHBOSS_HARD, offset=checkout_offset):
            logger.attr('Month boss difficulty', 'hard')
            is_normal = False
        else:
            logger.info("No Normal/Hard boss found, stop")
            self.os_mission_quit()
            self.month_boss_delay(is_normal=False, result=False)
            return True
        self.os_mission_quit()

        if not is_normal and self.config.OpsiMonthBoss_Mode == "normal":
            logger.info("Attack normal boss only but having hard boss, skip")
            self.month_boss_delay(is_normal=False, result=True)
            self.config.task_stop()
            return True

        if self.config.OpsiMonthBoss_CheckAdaptability:
            self.os_map_goto_globe(unpin=False)
            adaptability = self.get_adaptability()
            if (np.array(adaptability) < (203, 203, 156)).any():
                logger.info("Adaptability is lower than suppression level, get stronger and come back")
                self.config.task_delay(server_update=True)
                self.config.task_stop()
            # No need to exit, reuse
            # self.os_globe_goto_map()

        # combat
        logger.hr("Month Boss goto", level=2)
        self.globe_goto(154)
        self.go_month_boss_room(is_normal=is_normal)
        result = self.boss_clear(has_fleet_step=True, is_month=True)

        # end
        logger.hr("Month Boss repair", level=2)
        self.handle_fleet_repair_by_config(revert=False)
        self.handle_fleet_resolve(revert=False)
        self.month_boss_delay(is_normal=is_normal, result=result)

    def month_boss_delay(self, is_normal=True, result=True):
        """
        Args:
            is_normal: True for normal, False for hard
            result: If success to clear boss
        """
        if is_normal:
            if result:
                if self.config.OpsiMonthBoss_Mode == 'normal_hard':
                    logger.info('Monthly boss normal cleared, run hard boss then')
                    self.config.task_stop()
                else:
                    logger.info('Monthly boss normal cleared, task stop')
                    next_reset = get_os_next_reset()
                    self.config.task_delay(target=next_reset)
                    self.config.task_stop()
            else:
                logger.info("Unable to clear the normal monthly boss, will try later")
                self.config.opsi_task_delay(recon_scan=False, submarine_call=True, ap_limit=False)
                self.config.task_stop()
        else:
            if result:
                logger.info('Monthly boss hard cleared, task stop')
                next_reset = get_os_next_reset()
                self.config.task_delay(target=next_reset)
                self.config.task_stop()
            else:
                logger.info("Unable to clear the hard monthly boss, try again on tomorrow")
                self.config.task_delay(server_update=True)
                self.config.task_stop()


if __name__ == '__main__':
    self = OperationSiren('month_test', task='OpsiMonthBoss')
    from module.os.config import OSConfig

    self.config = self.config.merge(OSConfig())

    self.device.screenshot()
    self.os_init()

    logger.hr("OS clear Month Boss", level=1)
    self.clear_month_boss()
