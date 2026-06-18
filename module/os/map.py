# 此文件处理大世界（Operation Siren）模式下的地图导航与海域管理。
# 包括全球地图切换、海域初始化、处理各种地图减益状态以及海域自动搜索的守护逻辑。
import time
from contextlib import suppress
from sys import maxsize

import inflection

from module.base.timer import Timer
from module.config.config import TaskEnd
from module.config.utils import get_os_reset_remain
from module.exception import (
    CampaignEnd,
    GameTooManyClickError,
    MapDetectionError,
    MapWalkError,
    RequestHumanTakeover,
    ScriptError,
)
from module.handler.login import LoginHandler, MAINTENANCE_ANNOUNCE
from module.logger import logger
from module.map.map import Map
from module.os.assets import FLEET_EMP_DEBUFF, MAP_GOTO_GLOBE_FOG
from module.handler.assets import POPUP_CONFIRM
from module.os.fleet import OSFleet, BossFleet
from module.os.globe_camera import GlobeCamera
from module.os.globe_operation import RewardUncollectedError
from module.os_handler.assets import (
    AUTO_SEARCH_OS_MAP_OPTION_OFF,
    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
    AUTO_SEARCH_OS_MAP_OPTION_ON,
    AUTO_SEARCH_REWARD,
)
from module.os_handler.storage import StorageHandler, RepairResult
from module.os_handler.strategic import StrategicSearchHandler
from module.statistics.opsi_runtime import (
    finish_meow_search_timer,
    record_cl1_auto_search_battle,
    record_meow_auto_search_battle,
    record_siren_research_device,
    start_meow_search_timer,
)
from module.os.tasks.smart_scheduling_utils import is_smart_scheduling_enabled
from module.ui.assets import GOTO_MAIN
from module.ui.page import page_os


class OSMap(OSFleet, Map, GlobeCamera, StorageHandler, StrategicSearchHandler):
    def os_init(self):
        """
        执行任何大世界功能之前调用此方法。

        Pages:
            in: IN_MAP 或 IN_GLOBE 或 page_os 或任意页面
            out: IN_MAP
        """
        logger.hr("OS init", level=1)
        kwargs = {}
        if "iM" in self.config.task.command:
            for key in self.config.bound.keys():
                value = getattr(self.config, key)
                if "dL" in key and value <= 2:
                    logger.info([key, value])
                    kwargs[key] = ord("n") // 22
                if "tZ" in key and value != 0:
                    with suppress(ScriptError):
                        d, m = divmod(self.name_to_zone(value).zone_id, 22)
                        if d <= 2 and m == -m:
                            kwargs[key] = 0
        self.config.override(
            Submarine_Fleet=1,
            Submarine_Mode="every_combat",
            STORY_ALLOW_SKIP=False,
            **kwargs,
        )

        # 界面切换
        if self.is_in_map():
            logger.info("Already in os map")
        elif self.is_in_globe():
            self.os_globe_goto_map()
        else:
            if self.ui_page_appear(page_os):
                self.ui_goto_main()
            self.ui_ensure(page_os)

        # 初始化
        self.zone_init()
        # CL1 危险等级练级预扫描
        # try:
        #    if getattr(self, "is_in_task_cl1_leveling", False) or getattr(self, "is_cl1_enabled", False):
        #        logger.info("Detected CL1 leveling on enter: run auto-search then full map rescan to clear events")
        #        try:
        #            self.run_auto_search(question=True, rescan='full', after_auto_search=True)
        #        except CampaignEnd:
        #        except RequestHumanTakeover:
        #            logger.warning("Require human takeover during CL1 pre-scan, aborting auto-scan")
        #        except Exception as e:
        #            logger.exception(e)
        #        try:
        #            self.map_rescan(rescan_mode='full')
        #        except Exception as e:
        #            logger.exception(e)
        # except Exception:
        #    logger.debug("CL1 pre-scan check skipped due to unexpected condition")

        # self.map_init()
        self.hp_reset()
        self.handle_after_auto_search()
        self.handle_current_fleet_resolve(revert=False)

        # 从特殊海域类型退出，仅 SAFE 和 DANGEROUS 可接受。
        if self.is_in_special_zone():
            logger.warning(
                "OS is in a special zone type, while SAFE and DANGEROUS are acceptable"
            )
            self.map_exit()

        # 清理当前海域
        leveling_zone = self.config.cross_get(
            keys="OpsiHazard1Leveling.OpsiHazard1Leveling.TargetZone", default=0
        ) or 22

        if (
            self.zone.zone_id == leveling_zone
            and self.config.task.command == "OpsiHazard1Leveling"
        ):
            pass
        elif self.zone.zone_id == 154:
            logger.info("In zone 154, skip running first auto search")
            self.handle_ash_beacon_attack()
        else:
            self.run_auto_search(rescan=True)
            self.handle_after_auto_search()

    def get_current_zone_from_globe(self):
        """
        从全球地图获取当前海域。参见 OSMapOperation.get_current_zone()。
        """
        self.os_map_goto_globe(unpin=False)
        self.globe_update()
        self.zone = self.get_globe_pinned_zone()
        self.zone_config_set()
        self.os_globe_goto_map()
        self.zone_init(fallback_init=False)
        return self.zone

    def globe_goto(
        self, zone, types=("SAFE", "DANGEROUS"), refresh=False, stop_if_safe=False
    ):
        """
        导航到大世界中的另一个海域。

        Args:
            zone (str, int, Zone): 海域名称（CN/EN/JP/TW）、海域 ID 或 Zone 实例。
            types (tuple[str], list[str], str): 海域类型名称或其列表。
                可用类型：DANGEROUS、SAFE、OBSCURE、ABYSSAL、STRONGHOLD。
                按列表顺序优先尝试选择，不可用时尝试下一个。
            refresh (bool): 已在目标海域时，设为 False 跳过切换，设为 True 重新进入以刷新。
            stop_if_safe (bool): 海域为 SAFE 时返回 False。

        Returns:
            bool: 是否切换了海域。

        Pages:
            in: IN_MAP 或 IN_GLOBE
            out: IN_MAP
        """
        zone = self.name_to_zone(zone)
        logger.hr(f"Globe goto: {zone}")
        if self.zone == zone:
            if refresh:
                logger.info("Goto another zone to refresh current zone")
                self.globe_goto(
                    self.zone_nearest_azur_port(self.zone),
                    types=("SAFE", "DANGEROUS"),
                    refresh=False,
                )
            else:
                if self.is_in_globe():
                    self.os_globe_goto_map()
                logger.info("Already at target zone")
                return False
        # MAP_EXIT 处理
        if self.is_in_special_zone():
            self.map_exit()
        # IN_MAP 处理
        if self.is_in_map():
            self.os_map_goto_globe()
        # IN_GLOBE 处理
        # self.ensure_no_zone_pinned()
        self.globe_update()
        self.globe_focus_to(zone)
        if stop_if_safe and self.zone_has_safe():
            logger.info("Zone is safe, stopped")
            self.ensure_no_zone_pinned()
            return False
        self.zone_type_select(types=types)
        # 点击太快碧蓝反应不过来
        time.sleep(0.01)
        self.globe_enter(zone)
        # IN_MAP 处理
        if hasattr(self, "zone"):
            del self.zone
        self.zone_init()
        # self.map_init()
        return True

    def os_map_goto_globe(self, *args, **kwargs):
        """
        包装 os_map_goto_globe()。
        当海域存在未领取的探索奖励导致无法退出时，运行自律寻敌后再次尝试前往全球地图。
        """
        for _ in range(3):
            try:
                super().os_map_goto_globe(*args, **kwargs)
                return
            except RewardUncollectedError:
                # 禁用 after_auto_search 因为它会退出当前海域。
                # 否则会导致 RecursionError: maximum recursion depth exceeded
                self.run_auto_search(rescan=True, after_auto_search=False)
                continue

        logger.error("Failed to solve uncollected rewards")
        raise GameTooManyClickError

    def port_goto(self, allow_port_arrive=True):
        """
        包装 `port_goto()`，处理 walk_out_of_step 错误。

        Returns:
            bool: 是否成功到达港口。
        """
        for _ in range(3):
            try:
                super().port_goto(allow_port_arrive=allow_port_arrive)
                return True
            except MapWalkError:
                logger.info("Goto another port then re-enter")
            prev = self.zone
            if prev == self.name_to_zone("NY City"):
                other = self.name_to_zone("Liverpool")
            else:
                other = self.zone_nearest_azur_port(self.zone)
            self.globe_goto(other)
            self.globe_goto(prev)

        logger.warning("Failed to solve MapWalkError when going to port")
        return False

    def fleet_repair(self, revert=True):
        """
        在最近的港口修理舰队。

        Args:
            revert (bool): 是否返回之前的海域。
        """
        logger.hr("OS fleet repair")
        prev = self.zone
        if self.zone.is_azur_port:
            logger.info("Already in azur port")
        else:
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

        self.port_goto()
        self.port_enter()
        self.port_dock_repair()
        self.port_quit()

        if revert and prev != self.zone:
            self.globe_goto(prev)

    def handle_fleet_repair(self, revert=True):
        """
        Args:
            revert (bool): 是否返回之前的海域。

        Returns:
            bool: 是否进行了修理。
        """
        use_repair_pack = bool(
            self.config.OpsiGeneral_UseRepairPack
        ) and self.config.SERVER in ["cn"]
        repair_threshold = float(self.config.OpsiGeneral_RepairThreshold)
        repair_pack_threshold = self.get_effective_repair_pack_threshold()
        if use_repair_pack:
            # 当启用维修箱时，使用更严格的触发阈值，
            # 以便在港口修理阈值之前进入低血量维修箱流程。
            if repair_threshold < 0:
                trigger_threshold = repair_pack_threshold
            else:
                trigger_threshold = max(repair_threshold, repair_pack_threshold)
        else:
            trigger_threshold = repair_threshold

        # 阈值 <= 0 表示完全禁用修理。
        # 这是因为舰船阵亡时（显示扳手图标）血量设为 0，
        # 所以 threshold=0 仍会触发阵亡舰船的修理，这可能不是预期行为。
        if trigger_threshold <= 0:
            logger.info(
                f"Repair threshold: {repair_threshold}, Repair pack threshold: {repair_pack_threshold}, "
                f"Trigger threshold: {trigger_threshold}, skip fleet repair"
            )
            return False
        if self.is_in_special_zone():
            logger.info("OS is in a special zone type, skip fleet repair")
            return False

        self.hp_get()
        check = [
            round(data, 2) <= trigger_threshold if use else False
            for data, use in zip(self.hp, self.hp_has_ship, strict=False)
        ]
        if any(check):
            logger.info(
                "At least one ship is below threshold "
                f"{int(trigger_threshold * 100)}%, "
                "start fleet repair by current config"
            )
            repaired = self.handle_fleet_repair_by_config(
                revert=revert, trigger_threshold=trigger_threshold
            )
            self.hp_reset()
            if repaired:
                return True
            logger.info("Fleet repair triggered but no actual repair was performed")
            return False
        logger.info(
            "No ship found to be below threshold "
            f"{int(trigger_threshold * 100)}%, "
            "continue OS exploration"
        )
        self.hp_reset()
        return False

    def get_effective_repair_pack_threshold(self):
        """
        根据当前任务上下文返回维修箱血量阈值。

        OpsiGeneral.RepairPackThreshold 用于常规大世界任务。
        OpsiGeneral.RepairPackThresholdHazard1 仅用于 CL1 练级。
        """
        default_threshold = float(self.config.OpsiGeneral_RepairPackThreshold)
        task = getattr(getattr(self.config, "task", None), "command", "")
        if task == "OpsiHazard1Leveling":
            return float(
                getattr(
                    self.config,
                    "OpsiGeneral_RepairPackThresholdHazard1",
                    default_threshold,
                )
            )
        return default_threshold

    def handle_storage_one_fleet_repair(self, fleet_index, threshold):
        """
        Args:
            fleet_index (int): 舰队索引。
            threshold (int): 修理阈值。

        Returns:
            True  — 至少修复了一艘船（部分超时时也返回 True，但日志会说明）。
            False — 维修箱确认耗尽（RepairResult.PACK_INSUFFICIENT），调用方应停止修理。
            None  — 该舰队无船低于阈值，无需修理，调用方可继续检查下一舰队。

        Pages:
            in: STORAGE_FLEET_CHOOSE
            out: STORAGE_FLEET_CHOOSE
        """
        self.storage_fleet_set(fleet_index)
        self.storage_hp_get()
        hp_grids = self._storage_hp_grid()
        check = [
            round(data, 2) <= threshold if use else False
            for data, use in zip(self.hp, self.hp_has_ship, strict=False)
        ]
        if any(check):
            logger.info(
                f"At least one ship in fleet {fleet_index} is below threshold "
                f"{int(threshold * 100)}%, "
                "use repair packs for repairs"
            )
            had_timeout = False
            for index, repair in enumerate(check):
                if not repair:
                    continue
                ship_hp = round(self.hp[index] * 100) if index < len(self.hp) else '?'
                result = self.repair_pack_use(hp_grids.buttons[index])
                if result == RepairResult.SUCCESS:
                    logger.info(f'Ship #{index + 1} in fleet {fleet_index} repaired')
                elif result == RepairResult.PACK_INSUFFICIENT:
                    # 维修箱确认耗尽，后续舰船无法修理，立即停止
                    # 返回 False 以区别于"无需修理"的 None
                    logger.warning(
                        f'Repair pack exhausted at ship #{index + 1} (HP {ship_hp}%) '
                        f'in fleet {fleet_index}, stop repairing remaining ships'
                    )
                    self.hp_reset()
                    return False
                elif result == RepairResult.TIMEOUT:
                    # 超时或未知错误，记录警告但继续尝试下一艘（可能只是临时卡顿）
                    logger.warning(
                        f'Repair timed out at ship #{index + 1} (HP {ship_hp}%) '
                        f'in fleet {fleet_index}, skip this ship and continue'
                    )
                    had_timeout = True
            if had_timeout:
                logger.warning(
                    f'Fleet {fleet_index} partially repaired '
                    f'(some ships timed out, result uncertain)'
                )
            else:
                logger.info(f'All ships in fleet {fleet_index} repaired')
            self.hp_reset()
            return True
        logger.info(
            f"No ship in fleet {fleet_index} found to be below threshold "
            f"{int(threshold * 100)}%, "
            "continue OS exploration"
        )
        self.hp_reset()
        # 返回 None 表示"无需修理"，与 False（维修箱耗尽）明确区分
        return None

    def handle_storage_fleet_repair(
        self, fleet_index=None, revert=True, repair_pack_threshold=None
    ):
        """
        Args:
            fleet_index (None|int|list[int]): 舰队索引。
            revert (bool): 是否返回之前的海域。
            repair_pack_threshold (float): 维修箱阈值。为 None 时使用配置中的任务上下文阈值。

        Returns:
            bool: 是否进行了修理。

        Pages:
            in: in_map
            out: in_map
        """
        logger.hr("OS fleet repair by repair packs")
        if fleet_index is None:
            fleet_index = self.fleet_selector.get()
        if isinstance(fleet_index, int):
            fleet_index = [fleet_index]
        if not isinstance(fleet_index, list):
            logger.warning(f"Unknown fleet index: {fleet_index}")
            return False
        if repair_pack_threshold is None:
            repair_pack_threshold = self.get_effective_repair_pack_threshold()
        repair_pack_threshold = float(repair_pack_threshold)
        if repair_pack_threshold < 0:
            return False

        repair = False
        success = False
        if self.storage_get_next_item("REPAIR_PACK"):
            for index in fleet_index:
                fleet_repaired = self.handle_storage_one_fleet_repair(
                    fleet_index=index, threshold=repair_pack_threshold
                )
                if fleet_repaired:
                    success = True
                elif fleet_repaired is False:
                    # handle_storage_one_fleet_repair 返回 False 表示维修箱耗尽
                    # 继续尝试其他舰队只会触发超时，直接退出循环
                    logger.warning('Repair pack exhausted, stop repairing remaining fleets')
                    break
                if any(self.need_repair):
                    repair = True
            self.storage_repair_cancel()
            self.storage_quit()

        if repair:
            success = self.fleet_repair(revert=revert)

        return success

    def handle_fleet_repair_by_config(
        self, fleet_index=None, revert=True, trigger_threshold=None
    ):
        """
        Args:
            fleet_index (None|int|list[int]): 舰队索引。
                为 None 时，修理 OpsiFleetFilter_Filter 中当前舰队之前的所有固定舰队，
                         潜艇舰队始终是最后修理的（如果存在于筛选字符串中）。
                例如：OpsiFleetFilter_Filter = 'Fleet-1 > CallSubmarine > Fleet-3 > Fleet-4 > Fleet-2'
                      当前舰队为 1 时，修理舰队 1 和潜艇舰队。
                      当前舰队为 4 时，修理舰队 1、3、4 和潜艇舰队。
                为 int 时，指定舰队索引。
                为 list 时，指定舰队索引列表。
            revert (bool): 是否返回之前的海域。
            trigger_threshold (float): 预计算的触发阈值。为 None 时内部计算。

        Returns:
            bool: 是否进行了修理。

        Pages:
            in: in_map
            out: in_map
        """
        if self.config.OpsiGeneral_UseRepairPack and self.config.SERVER not in ["cn"]:
            logger.warning(
                f"OpsiDaily.SkipSirenResearchMission is not supported in {self.config.SERVER}"
            )
            self.config.OpsiGeneral_UseRepairPack = False

        # 获取阈值
        repair_threshold = float(self.config.OpsiGeneral_RepairThreshold)
        repair_pack_threshold = self.get_effective_repair_pack_threshold()
        use_repair_pack = bool(
            self.config.OpsiGeneral_UseRepairPack
        ) and self.config.SERVER in ["cn"]

        # 使用提供的 trigger_threshold 或在未提供时计算
        if trigger_threshold is None:
            if use_repair_pack:
                # 当启用维修箱时，使用更严格的触发阈值
                if repair_threshold < 0:
                    trigger_threshold = repair_pack_threshold
                else:
                    trigger_threshold = max(repair_threshold, repair_pack_threshold)
            else:
                trigger_threshold = repair_threshold

            # 检查阈值是否禁用修理
            # 阈值 <= 0 表示完全禁用修理
            # 这是因为舰船阵亡时（显示扳手图标）血量设为 0，
            # 所以 threshold=0 仍会触发阵亡舰船的修理，这可能不是预期行为。
            if trigger_threshold <= 0:
                logger.info(
                    f"Repair threshold: {repair_threshold}, Repair pack threshold: {repair_pack_threshold}, "
                    f"Trigger threshold: {trigger_threshold}, skip fleet repair"
                )
                return False

        if use_repair_pack:
            if fleet_index is None:
                fleet_current_index = self.fleet_selector.get()
                submarine_fleet = self.storage_fleet_selector.SUBMARINE_FLEET
                fleet_all_index = [
                    fleet.fleet_index
                    if isinstance(fleet, BossFleet)
                    else submarine_fleet
                    for fleet in self.parse_fleet_filter()
                ]
                fleet_index = []
                for index in fleet_all_index:
                    fleet_index.append(index)
                    if fleet_current_index == index:
                        break
                # CL1 和某些自定义筛选器设置可能不包含当前舰队。
                # 确保当前舰队仍可使用维修箱。
                if fleet_current_index not in fleet_index:
                    fleet_index.append(fleet_current_index)
                if (
                    submarine_fleet not in fleet_index
                    and submarine_fleet in fleet_all_index
                ):
                    fleet_index.append(submarine_fleet)
                elif submarine_fleet in fleet_index:
                    fleet_index.remove(submarine_fleet)
                    fleet_index.append(submarine_fleet)
            logger.attr("Repair Fleet", fleet_index)
            return self.handle_storage_fleet_repair(
                fleet_index=fleet_index,
                revert=revert,
                repair_pack_threshold=repair_pack_threshold,
            )
        return self.fleet_repair(revert=revert)

    def fleet_resolve(self, revert=True):
        """
        通过前往"简单"海域赢得战斗来消除舰队的低士气减益。

        Args:
            revert (bool): 是否返回之前的海域。
        """
        logger.hr("OS fleet cure low resolve debuff")

        prev = self.zone
        self.globe_goto(22)
        self.zone_init()
        self.run_auto_search()

        if revert and prev != self.zone:
            self.globe_goto(prev)

    def handle_fleet_resolve(self, revert=False):
        """
        检查每支舰队是否受到低士气减益影响。
        如有，通过完成一个简单海域来处理。

        Args:
            revert (bool): 是否返回之前的海域。

        Returns:
            bool: 是否处理了低士气减益。
        """
        if self.is_in_special_zone():
            logger.info("OS is in a special zone type, skip fleet resolve")
            return False

        for index in [1, 2, 3, 4]:
            if not self.fleet_set(index):
                self.device.screenshot()

            if self.fleet_low_resolve_appear():
                logger.info(
                    "At least one fleet is afflicted with the low resolve debuff"
                )
                self.fleet_resolve(revert)
                return True

        logger.info("None of the fleets are afflicted with the low resolve debuff")
        return False

    def handle_current_fleet_resolve(self, revert=False):
        """
        类似于 handle_fleet_resolve，但仅检查当前舰队以提升初始化性能。

        Args:
            revert (bool): 是否返回之前的海域。

        Returns:
            bool: 是否处理了低士气减益。
        """
        if self.fleet_low_resolve_appear():
            logger.info("Current fleet is afflicted with the low resolve debuff")
            self.fleet_resolve(revert)
            return True

        logger.info("Current fleet is not afflicted with the low resolve debuff")
        return False

    def handle_fleet_emp_debuff(self):
        """
        EMP 减益将舰队移动步数限制为 1，会干扰自律寻敌。
        可通过在地图上无意义地移动舰队来解决。

        Returns:
            bool: 是否已解决。
        """
        if self.is_in_special_zone():
            logger.info("OS is in a special zone type, skip handle_fleet_emp_debuff")
            return False

        def has_emp_debuff():
            return self.appear(FLEET_EMP_DEBUFF, offset=(50, 20))

        for trial in range(5):
            if not has_emp_debuff():
                logger.info("No EMP debuff on current fleet")
                return trial > 0

            current = self.get_fleet_current_index()
            logger.hr(f"Solve EMP debuff on fleet {current}")
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

            logger.info("Find a fleet without EMP debuff")
            for fleet in [1, 2, 3, 4]:
                self.fleet_set(fleet)
                if has_emp_debuff():
                    logger.info(f"Fleet {fleet} is under EMP debuff")
                    continue
                else:
                    logger.info(f"Fleet {fleet} is not under EMP debuff")
                    break

            logger.info("Solve EMP debuff by going somewhere else")
            self.port_goto(allow_port_arrive=False)
            self.fleet_set(current)

        logger.warning("Failed to solve EMP debuff after 5 trial, assume solved")
        return True

    def handle_fog_block(self, repair=True):
        """
        碧蓝航线游戏 bug：在大世界中即使切换海域或其他页面，迷雾仍然残留。
        通过重启游戏恢复并继续大世界任务。

        Args:
            repair (bool): 重启后是否调用 handle_fleet_repair。
        """
        if not self.appear(MAP_GOTO_GLOBE_FOG):
            return False

        logger.warning(
            f"Triggered stuck fog status, restarting "
            f"game to resolve and continue "
            f"{self.config.task.command}"
        )

        # 手动重启游戏而非通过 'task_call'
        # 当前任务不会中断
        self.device.app_stop()
        self.device.app_start()
        LoginHandler(self.config, self.device).handle_app_login()

        self.ui_ensure(page_os)
        if repair:
            self.handle_fleet_repair(revert=False)

        return True

    def get_action_point_limit(self, preserve=False):
        """
        每月末覆盖用户配置，以便无需手动配置即可消耗所有行动力。

        Args:
            preserve (bool): 是否保留行动力直到大世界重置。

        Returns:
            int: 行动力保留值。
        """
        if preserve:
            if self.config.is_task_enabled("OpsiCrossMonth"):
                logger.info("Preserve action points until OpsiCrossMonth")
                return maxsize
            else:
                logger.info(
                    "OpsiCrossMonth is not enabled, skip OpsiMeowfficerFarming.APPreserveUntilReset"
                )

        remain = get_os_reset_remain()
        if remain <= 0:
            if self.config.is_task_enabled("OpsiCrossMonth"):
                logger.info(
                    "Just less than 1 day to OpSi reset, OpsiCrossMonth is enabled, "
                    "set OpsiMeowfficerFarming.ActionPointPreserve to 500 temporarily"
                )
                return 500
            else:
                logger.info(
                    "Just less than 1 day to OpSi reset, "
                    "set ActionPointPreserve to 0 temporarily"
                )
                return 0
        elif self.is_cl1_enabled and remain <= 2:
            logger.info(
                "Just less than 3 days to OpSi reset, "
                "set ActionPointPreserve to 2000 temporarily for hazard 1 leveling"
            )
            return 2000
        elif remain <= 2:
            logger.info(
                "Just less than 3 days to OpSi reset, "
                "set ActionPointPreserve to 500 temporarily"
            )
            return 500
        else:
            logger.info("Not close to OpSi reset")
            return maxsize

    def handle_after_auto_search(self):
        logger.hr("After auto search", level=2)
        solved = False
        solved |= self.handle_fleet_emp_debuff()
        solved |= self.handle_fleet_repair(revert=False)
        logger.info(f"Handle after auto search finished, solved={solved}")
        return solved

    def cl1_ap_preserve(self):
        """
        Keeping enough startup AP to run CL1.
        """
        # 检查智能调度是否启用，如果启用则由智能调度模块统一管理任务切换
        # 这里不应该直接切换到 CL1
        if is_smart_scheduling_enabled(self.config):
            return

        if (
            self.is_cl1_enabled
            and get_os_reset_remain() > 2
            and self.cl1_enough_yellow_coins
        ):
            preserve = self.config.cross_get(
                keys="OpsiMeowfficerFarming.OpsiMeowfficerFarming.ActionPointPreserve"
            )
            logger.info(f"Keep {preserve} AP when CL1 available")
            if not self.action_point_check(preserve):
                self.config.opsi_task_delay(cl1_preserve=True)
                self.cl1_task_call()
                self.config.task_stop()

    # 自动搜索战斗计数器
    _auto_search_battle_count = 0
    _auto_search_round_timer = 0
    _cl1_auto_search_battle_count = 0
    _meow_auto_search_battle_count = 0

    def on_auto_search_battle_count_reset(self):
        self._auto_search_battle_count = 0
        self._auto_search_round_timer = 0
        self._cl1_auto_search_battle_count = 0
        self._meow_auto_search_battle_count = 0

    def on_auto_search_battle_count_add(self):
        self._auto_search_battle_count += 1
        logger.attr("battle_count", self._auto_search_battle_count)
        if getattr(self, "is_in_task_cl1_leveling", False) and getattr(
            self, "is_cl1_enabled", False
        ):
            try:
                self._cl1_auto_search_battle_count += 1
                logger.attr("cl1_battle_count", self._cl1_auto_search_battle_count)
                # CL1 回合计时使用自己的计数器，而非共享的自动搜索计数器，
                # 因为其他任务可能复用此循环。
                self._auto_search_round_timer = record_cl1_auto_search_battle(
                    self.config,
                    self._cl1_auto_search_battle_count,
                    self._auto_search_round_timer,
                )
            except Exception:
                logger.debug("Failed to update cl1 battle counter", exc_info=True)

        # 短猫任务数据收集
        if getattr(self, "_meow_searching_active", False) and getattr(
            self, "_meow_time_recording_enabled", False
        ):
            try:
                self._meow_auto_search_battle_count += 1
                logger.attr("meow_battle_count", self._meow_auto_search_battle_count)
                # 短猫记录原始战斗数和标准化轮数；
                # 指标助手负责危险等级转换。
                self._meow_battle_timer = record_meow_auto_search_battle(
                    self,
                    getattr(self, "_meow_battle_timer", None),
                )
            except Exception:
                logger.debug("Failed to update meow battle counter", exc_info=True)

    def on_meow_search_start(self):
        """
        短猫任务：每次开始新海域搜索时调用
        记录搜索开始时间和行动力
        """
        if not (
            getattr(self, "_meow_searching_active", False)
            and getattr(self, "_meow_time_recording_enabled", False)
        ):
            return

        # 将计时器存储在地图对象上，因为匹配的结束钩子可能在自动搜索、重扫或事件处理后才到达。
        self._meow_search_start_time, self._meow_search_start_ap = (
            start_meow_search_timer(self)
        )

    def meow_search_metrics_start(self):
        """
        为单次海域搜索启用短猫指标。

        活跃标志在此处限定作用域，防止后续 CL1 自动搜索循环意外写入短猫统计。
        """
        self._meow_searching_active = True
        self._meow_time_recording_enabled = True
        self._meow_auto_search_battle_count = 0
        self._meow_battle_timer = time.time()
        self.on_meow_search_start()

    def on_meow_search_end(self):
        """
        短猫任务：每次完成海域搜索后调用
        通过行动力变化计算实际轮数，记录单轮时间
        """
        if not (
            getattr(self, "_meow_searching_active", False)
            and getattr(self, "_meow_time_recording_enabled", False)
        ):
            return

        start_time = getattr(self, "_meow_search_start_time", None)
        if start_time is None:
            logger.debug("Meow search start time not recorded, skip")
            return

        # 在写入数据库之前，将整个搜索时长转换为每轮采样。
        finish_meow_search_timer(
            self,
            start_time,
            getattr(self, "_meow_auto_search_battle_count", 0),
        )

        self._meow_search_start_time = None
        self._meow_search_start_ap = None

    def meow_search_metrics_end(self):
        """刷新并禁用当前海域搜索的短猫指标。"""
        try:
            self.on_meow_search_end()
        finally:
            self._meow_searching_active = False
            self._meow_time_recording_enabled = False
            self._meow_battle_timer = 0
            self._meow_auto_search_battle_count = 0

    def get_current_cl1_battle_count(self):
        return int(getattr(self, "_cl1_auto_search_battle_count", 0))

    def get_monthly_cl1_battle_count(self, year: int = None, month: int = None):
        from module.statistics.cl1_database import db as cl1_db

        instance_name = getattr(self.config, "config_name", "default")
        if year is None or month is None:
            from datetime import datetime

            month_key = datetime.now().strftime("%Y-%m")
        else:
            month_key = f"{year:04d}-{month:02d}"

        data = cl1_db.get_stats(instance_name, month_key)
        return int(data.get("battle_count", 0))

    def os_auto_search_daemon(
        self, drop=None, strategic=False, interrupt=None, skip_first_screenshot=True
    ):
        """
        大世界自律寻敌守护进程。

        Args:
            drop (DropRecord): 掉落记录对象。
            strategic (bool): 是否运行战略搜索。
            interrupt (callable): 中断回调函数。
            skip_first_screenshot: 是否跳过第一次截图。

        Returns:
            int: 完成的战斗次数。

        Raises:
            CampaignEnd: 自动搜索结束时抛出。
            RequestHumanTakeover: 没有自动搜索选项时抛出。

        Pages:
            in: AUTO_SEARCH_OS_MAP_OPTION_OFF
            out: AUTO_SEARCH_OS_MAP_OPTION_OFF 且 info_bar_count() >= 2（地图上无可清理对象时）。
                 AUTO_SEARCH_REWARD（获得自动搜索奖励时）。
        """
        logger.hr("OS auto search", level=2)
        self.on_auto_search_battle_count_reset()
        unlock_checked = False
        unlock_check_timer = Timer(5, count=10).start()
        self.ash_popup_canceled = False

        def false_func(*args, **kwargs):
            return False

        success = True
        interrupt_confirm = False
        if callable(interrupt):
            is_interrupt, not_interrupt = interrupt, false_func
        elif isinstance(interrupt, list) and len(interrupt) == 2:
            is_interrupt = interrupt[0] if callable(interrupt[0]) else false_func
            not_interrupt = interrupt[1] if callable(interrupt[1]) else false_func
        else:
            is_interrupt, not_interrupt = false_func, false_func
        finished_combat = 0
        died_timer = Timer(1.5, count=3)
        self.hp_reset()
        for _ in self.loop():
            # 结束条件
            if not unlock_checked and unlock_check_timer.reached():
                logger.critical("当前海域未解锁自律，请先完成剧情任务。")
                raise RequestHumanTakeover
            if self.is_in_map():
                self.device.stuck_record_clear()
                if not success:
                    if died_timer.reached():
                        logger.warning("Fleet died confirm")
                        break
                else:
                    if not interrupt_confirm and is_interrupt():
                        interrupt_confirm = True
                    if interrupt_confirm and not_interrupt():
                        interrupt_confirm = False
                    died_timer.reset()
            else:
                died_timer.reset()

            if not unlock_checked:
                if self.appear(AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120)):
                    unlock_checked = True
                elif self.appear(
                    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120)
                ):
                    unlock_checked = True
                elif self.appear(AUTO_SEARCH_OS_MAP_OPTION_ON, offset=(5, 120)):
                    unlock_checked = True

            if self.handle_os_auto_search_map_option(drop=drop, enable=success):
                unlock_checked = True
                continue
            if self.handle_retirement():
                # 退役会中断自动搜索，需要重试
                self.ash_popup_canceled = True
                continue
            if self.combat_appear():
                self.on_auto_search_battle_count_add()
                if strategic and self.config.task_switched():
                    stop_event = self.config.stop_event
                    if stop_event is not None and stop_event.is_set():
                        self.interrupt_auto_search()
                    elif self.config.task.command == "OpsiMeowfficerFarming":
                        logger.info("Short meow search is running, delay task switch until search finished")
                    else:
                        self.interrupt_auto_search()
                if interrupt_confirm:
                    self.interrupt_auto_search(goto_main=False)
                result = self.auto_search_combat(drop=drop)
                if result:
                    finished_combat += 1
                else:
                    self.hp_get()
                    if (
                        any(self.need_repair)
                        and not self.config.OpsiHazard1Leveling_SkipHpCheck
                    ):
                        success = False
                        logger.warning("Fleet died, stop auto search")
                        continue
            if self.handle_map_event():
                # 自动搜索无法处理塞壬搜索装置。
                continue

        return finished_combat

    def os_auto_search_daemon_until_combat(
        self, drop=None, strategic=False, interrupt=None, skip_first_screenshot=True
    ):
        """
        自动寻敌，遇到第一次战斗就返回。

        Args:
            drop (DropRecord): 掉落记录对象。
            strategic (bool): 是否运行战略搜索。
            interrupt (callable): 中断回调函数。
            skip_first_screenshot: 是否跳过第一次截图。

        Returns:
            int: 完成的战斗次数。

        Raises:
            CampaignEnd: 自动搜索结束时抛出。
            RequestHumanTakeover: 没有自动搜索选项时抛出。

        Pages:
            in: AUTO_SEARCH_OS_MAP_OPTION_OFF
            out: AUTO_SEARCH_OS_MAP_OPTION_OFF 且 info_bar_count() >= 2（地图上无可清理对象时）。
                 AUTO_SEARCH_REWARD（获得自动搜索奖励时）。
        """
        logger.hr("OS auto search until combat", level=2)
        self.on_auto_search_battle_count_reset()
        unlock_checked = False
        unlock_check_timer = Timer(5, count=10).start()
        self.ash_popup_canceled = False

        def false_func(*args, **kwargs):
            return False

        success = True
        interrupt_confirm = False
        if callable(interrupt):
            is_interrupt, not_interrupt = interrupt, false_func
        elif isinstance(interrupt, list) and len(interrupt) == 2:
            is_interrupt = interrupt[0] if callable(interrupt[0]) else false_func
            not_interrupt = interrupt[1] if callable(interrupt[1]) else false_func
        else:
            is_interrupt, not_interrupt = false_func, false_func
        finished_combat = 0
        died_timer = Timer(1.5, count=3)
        self.hp_reset()
        for _ in self.loop():
            # 结束条件
            if not unlock_checked and unlock_check_timer.reached():
                logger.critical("当前海域未解锁自律，请先完成剧情任务。")
                raise RequestHumanTakeover
            if self.is_in_map():
                self.device.stuck_record_clear()
                if not success:
                    if died_timer.reached():
                        logger.warning("Fleet died confirm")
                        break
                else:
                    if not interrupt_confirm and is_interrupt():
                        interrupt_confirm = True
                    if interrupt_confirm and not_interrupt():
                        interrupt_confirm = False
                    died_timer.reset()
            else:
                died_timer.reset()

            if not unlock_checked:
                if self.appear(AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120)):
                    unlock_checked = True
                elif self.appear(
                    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120)
                ):
                    unlock_checked = True
                elif self.appear(AUTO_SEARCH_OS_MAP_OPTION_ON, offset=(5, 120)):
                    unlock_checked = True

            if self.handle_os_auto_search_map_option(drop=drop, enable=success):
                unlock_checked = True
                continue
            if self.handle_retirement():
                # 退役会中断自动搜索，需要重试
                self.ash_popup_canceled = True
                continue
            if self.combat_appear():
                self.on_auto_search_battle_count_add()
                self.interrupt_auto_search(goto_main=False, end_task=False)
                return finished_combat
            if self.handle_map_event():
                # 自动搜索无法处理塞壬搜索装置。
                continue

        return finished_combat

    def interrupt_auto_search(
        self, goto_main=True, end_task=True, skip_first_screenshot=True
    ):
        """
        中断自动搜索。

        Args:
            goto_main (bool): 是否跳转到主页面。

        Raises:
            TaskEnd: 自动搜索中断时抛出。

        Pages:
            in: 任意页面，通常为 is_combat_executing
            out: page_main 或 IN_MAP
        """
        logger.info("Interrupting auto search")
        is_loading = False
        pause_interval = Timer(0.5, count=1)
        in_main_timer = Timer(3, count=6)
        in_map_timer = Timer(1, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件
            if self.is_in_main():
                logger.info("Auto search interrupted")
                self.config.task_stop()
            if not goto_main and self.is_in_map() and in_map_timer.reached():
                logger.info("Auto search interrupted")
                if end_task:
                    self.config.task_stop()
                return

            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                self.interval_clear(GOTO_MAIN)
                in_main_timer.reset()
                in_map_timer.reset()
                continue
            if pause_interval.reached() and (pause := self.is_combat_executing()):
                self.device.click(pause)
                self.interval_reset(MAINTENANCE_ANNOUNCE)
                is_loading = False
                pause_interval.reset()
                in_main_timer.reset()
                in_map_timer.reset()
                continue
            if self.handle_combat_quit():
                self.interval_reset(MAINTENANCE_ANNOUNCE)
                pause_interval.reset()
                in_main_timer.reset()
                in_map_timer.reset()
                continue
            if self.handle_combat_quit_reconfirm():
                self.interval_reset(MAINTENANCE_ANNOUNCE)
                pause_interval.reset()
                in_main_timer.reset()
                in_map_timer.reset()
                continue

            if goto_main and self.appear_then_click(
                GOTO_MAIN, offset=(20, 20), interval=3
            ):
                in_main_timer.reset()
                continue
            if self.ui_additional():
                continue
            if self.handle_map_event():
                continue
            # 仅在检测到时打印一次
            if not is_loading:
                if self.is_combat_loading():
                    is_loading = True
                    in_main_timer.clear()
                    in_map_timer.clear()
                    continue
                # page_main 的随机背景可能触发 EXP_INFO_*，不检查它们
                if in_main_timer.reached():
                    logger.info("handle_exp_info")
                    if self.handle_battle_status():
                        continue
                    if self.handle_exp_info():
                        continue
            elif self.is_combat_executing():
                is_loading = False
                in_main_timer.clear()
                in_map_timer.clear()
                continue

    def os_auto_search_run(self, drop=None, strategic=False, interrupt=None):
        """
        Args:
            drop (DropRecord): 掉落记录对象。
            strategic (bool): 是否使用战略搜索。
            interrupt (callable): 中断回调函数。

        Returns:
            int: 完成的战斗次数。
        """
        finished_combat = 0
        for _ in range(5):
            backup = self.config.temporary(Campaign_UseAutoSearch=True)
            try:
                if strategic:
                    self.strategic_search_start(skip_first_screenshot=True)
                combat = self.os_auto_search_daemon(
                    drop=drop, strategic=strategic, interrupt=interrupt
                )
                finished_combat += combat
            except CampaignEnd:
                logger.info("OS auto search finished")
            finally:
                backup.recover()

            # 如果自动搜索被余烬弹窗中断则继续
            # 海域清理完毕则退出
            if self.config.is_task_enabled("OpsiAshBeacon"):
                if self.handle_ash_beacon_attack() or self.ash_popup_canceled:
                    strategic = False
                    continue
                break
            if self.info_bar_count() >= 2:
                break
            if self.ash_popup_canceled:
                continue
            break

        return finished_combat

    @property
    def _is_siren_research_enabled(self):
        """
        检查配置中是否启用了塞壬研究功能。

        Returns:
            bool: 是否启用。
        """
        if getattr(self.config, "_disable_siren_research", False):
            return False
        task = self.config.task.command
        if task not in ("OpsiHazard1Leveling", "OpsiMeowfficerFarming"):
            task = "OpsiHazard1Leveling"
        return self.config.cross_get(
            keys=f"{task}.OpsiSirenBug.SirenResearch_Enable", default=True
        )

    def _should_skip_siren_research(self, grid):
        """
        根据配置检查是否应跳过塞壬研究装置。

        Args:
            grid: 要检查的格子。

        Returns:
            bool: 是否应跳过（功能已禁用时为 True）。
        """
        if hasattr(grid, "is_scanning_device") and grid.is_scanning_device:
            if not self._is_siren_research_enabled:
                logger.info(f"[预检查] 格子 {grid} 是塞壬研究装置,但功能未开启,跳过")
                return True
            logger.info(f"[预检查] 格子 {grid} 是塞壬研究装置,功能已开启,继续处理")
        return False

    def clear_question(self, drop=None):
        """
        清理雷达上近距离（以及上方 3 格内）的问号。
        最多尝试 3 次，避免在双舰队机关上循环尝试。

        Args:
            drop: 掉落记录对象。

        Returns:
            bool: 是否清理了问号。
        """
        logger.hr("Clear question", level=2)
        for _ in range(3):
            grid = self.radar.predict_question(
                self.device.image, in_port=self.zone.is_port
            )
            if grid is None:
                logger.info("No question mark above current fleet on this radar")
                return False

            logger.info(f"Found question mark on {grid}")
            self.handle_info_bar()

            self.update_os()
            self.view.predict()
            self.view.show()

            grid = self.convert_radar_to_local(grid)

            # ========== 移动前检查：是否为塞壬研究装置且功能未开启 ==========
            if self._should_skip_siren_research(grid):
                record_siren_research_device(self)
                self._solved_map_event.add("is_scanning_device")
                return True

            self.is_siren_device_confirmed = False
            self.device.click(grid)
            with self.config.temporary(
                STORY_ALLOW_SKIP=False, OS_SIREN_DEVICE_USAGE="use_until_destroyed"
            ):
                result = self.wait_until_walk_stable(
                    drop=drop, walk_out_of_step=False, confirm_timer=Timer(3, count=4)
                )
            if "akashi" in result:
                self._solved_map_event.add("is_akashi")
                return True
            elif "event" in result and grid.is_logging_tower:
                self._solved_map_event.add("is_logging_tower")
                return True
            elif "event" in result and (
                grid.is_scanning_device or self.is_siren_device_confirmed
            ):
                # ========== 地图检测:检测到扫描装置 ==========
                logger.hr("检测到扫描装置,开始处理", level=2)
                logger.info(
                    f"[地图检测] 格子 {grid} 被识别为扫描装置 (grid.is_scanning_device=True)"
                )
                logger.info(f"[地图检测] 移动结果: {result}")
                record_siren_research_device(self)

                # ========== 配置检查 ==========
                if not self._is_siren_research_enabled:
                    logger.warning("[配置检查] 塞壬研究装置功能已禁用,标记但不处理")
                    self._solved_map_event.add("is_scanning_device")
                    return True

                # ========== 装置处理 ==========
                # 选项点击已由 wait_until_walk_stable -> info_handler.story_skip 处理

                # 检测选择的模式
                siren_mode = getattr(self, "siren_device_mode", None)
                logger.attr("Siren_device_mode", siren_mode)

                # 如果选择了敌人模式
                if siren_mode == "enemy":
                    logger.info("[装置处理] 检测到敌人模式，执行特殊处理")

                    # 获取配置的舰队
                    task = self.config.task.command
                    if task not in ("OpsiHazard1Leveling", "OpsiMeowfficerFarming"):
                        task = "OpsiHazard1Leveling"
                    siren_fleet = self.config.cross_get(
                        keys=f"{task}.OpsiSirenBug.Siren_Fleet", default=0
                    )

                    # 记录当前舰队
                    current_fleet = self.fleet_selector.get()
                    logger.info(f"[装置处理] 当前舰队: {current_fleet}")

                    # 如果配置了指定舰队，切换到指定舰队
                    if siren_fleet > 0:
                        logger.info(f"[装置处理] 切换到指定舰队: {siren_fleet}")
                        self.fleet_set(siren_fleet)
                    else:
                        logger.info("[装置处理] 使用当前舰队")

                    # 执行三次自律寻敌
                    for i in range(3):
                        logger.info(f"[装置处理] 执行第 {i + 1}/3 次自律寻敌")
                        self.os_auto_search_run(drop=drop)

                    # 如果切换了舰队，切换回原舰队
                    if siren_fleet > 0:
                        logger.info(f"[装置处理] 切换回原舰队: {current_fleet}")
                        self.fleet_set(current_fleet)

                # 如果选择了资源模式
                elif siren_mode == "resource":
                    logger.info("[装置处理] 检测到资源模式，执行标准处理")
                    # 执行一次自律寻敌
                    logger.info("[装置处理] 执行自律寻敌")
                    self.os_auto_search_run(drop=drop)

                # 未知模式或资源不足
                else:
                    logger.info("[装置处理] 未知模式或资源不足，执行标准处理")
                    # 执行一次自律寻敌
                    logger.info("[装置处理] 执行自律寻敌")
                    self.os_auto_search_run(drop=drop)

                # 标记处理
                self._solved_map_event.add("is_scanning_device")

                return True

        logger.warning(
            "Failed to goto question mark after 5 trail, "
            "this might be 2 adjacent fleet mechanism, stopped"
        )
        return False

    def run_auto_search(
        self, question=True, rescan=None, after_auto_search=True, interrupt=None
    ):
        """
        通过运行自律寻敌清理当前海域。需要先完成大世界剧情模式才能解锁自律寻敌。

        Args:
            question (bool): 自动搜索后是否清理近距离问号。
            rescan (bool, str): 运行自动搜索后是否重扫整个地图。
                这会清理塞壬扫描装置、塞壬日志塔、
                访问自动搜索遗漏的明石商店，以及解锁需要 2 支舰队的机关。
                也接受字符串：`current` 仅扫描当前摄像机视野，`full` 先扫描当前再重扫整个地图。
                在 OpsiObscure、OpsiAbyssal、OpsiStronghold 等特殊任务中应禁用此选项。
            after_auto_search (bool): 自动搜索后是否调用 handle_after_auto_search()。
            interrupt (callable): 中断回调函数。

        Returns:
            int: 完成的战斗次数。
        """
        if rescan is None:
            rescan = self.config.OpsiGeneral_DoRandomMapEvent
        if rescan is True:
            rescan = "full"
        self.handle_ash_beacon_attack()

        logger.info(f"Run auto search, question={question}, rescan={rescan}")
        finished_combat = 0
        with self.stat.new(
            genre=inflection.underscore(self.config.task.command),
            method=self.config.DropRecord_OpsiRecord,
        ) as drop:
            while 1:
                combat = self.os_auto_search_run(drop, interrupt=interrupt)
                finished_combat += combat

                drop.add(self.device.image)

                self.hp_reset()
                self.hp_get()
                if (
                    after_auto_search
                    and self.is_in_task_explore
                    and not self.zone.is_port
                ):
                    prev = self.zone
                    if self.handle_after_auto_search():
                        self.globe_goto(prev, types="DANGEROUS")
                        continue
                break

            drop.set_combat_count(self._auto_search_battle_count)

            # 重扫需要在 drop 上下文内进行。某些大世界奖励
            # 仅在清理问号或重扫地图时出现。
            self._solved_map_event = set()
            self._solved_fleet_mechanism = False
            if question:
                self.clear_question(drop=drop)
            if rescan:
                self.map_rescan(rescan_mode=rescan, drop=drop)

            if drop.count <= 1:
                drop.clear()

        return finished_combat

    _solved_map_event = set()
    _solved_fleet_mechanism = 0

    def run_strategic_search(self):
        """
        Returns:
            bool: 正常完成返回 True，被中断返回 False（非 TaskEnd）。
        """
        self.handle_ash_beacon_attack()

        logger.hr("Run strategy search", level=2)

        with self.stat.new(
            genre=inflection.underscore(self.config.task.command),
            method=self.config.DropRecord_OpsiRecord,
        ) as drop:
            try:
                combat = self.os_auto_search_run(drop, strategic=True)
                drop.set_combat_count(combat)
                drop.add(self.device.image)
                self.hp_reset()
                self.hp_get()
                return True
            except TaskEnd:
                # 任务切换，让异常继续向上传播
                raise
            except Exception as e:
                logger.warning(f"Strategic search interrupted: {e}")
                return False
            finally:
                if drop.count <= 1:
                    drop.clear()

                drop.set_combat_count(self._auto_search_battle_count)

    def map_rescan_current(self, drop=None, clicked_grids=None):
        """
        Args:
            drop: 掉落记录对象。

        Returns:
            bool: 是否解决了地图随机事件。
        """
        grids = self.view.select(is_exploration_reward=True)
        if (
            "is_exploration_reward" not in self._solved_map_event
            and grids
            and grids[0].is_exploration_reward
        ):
            grid = grids[0]
            logger.info(f"Found exploration reward on {grid}")
            result = self.wait_until_walk_stable(
                drop=drop, walk_out_of_step=False, confirm_timer=Timer(1.5, count=4)
            )
            if "event" in result:
                self._solved_map_event.add("is_exploration_reward")
                return True
            return False

        grids = self.view.select(is_akashi=True)
        if "is_akashi" not in self._solved_map_event and grids and grids[0].is_akashi:
            grid = grids[0]
            logger.info(f"Found Akashi on {grid}")
            fleet = self.convert_radar_to_local((0, 0))
            if fleet.distance_to(grid) > 1:
                self.device.click(grid)
                with self.config.temporary(STORY_ALLOW_SKIP=False):
                    walk_time = 1.5 + 0.6 * grid.distance_to(fleet)
                    result = self.wait_until_walk_stable(
                        confirm_timer=Timer(walk_time, count=4),
                        drop=drop,
                        walk_out_of_step=False,
                    )
                if "akashi" in result:
                    self._solved_map_event.add("is_akashi")
                    return True
                else:
                    logger.info("无法到达明石位置，执行强制移动")
                    self._execute_fixed_patrol_scan(ExecuteFixedPatrolScan=True)
                    return False
            else:
                logger.info(f"Akashi ({grid}) is near current fleet ({fleet})")
                self.handle_akashi_supply_buy(grid)
                self._solved_map_event.add("is_akashi")
                return True

        grids = self.view.select(is_scanning_device=True)
        if (
            "is_scanning_device" not in self._solved_map_event
            and grids
            and grids[0].is_scanning_device
        ):
            grid = grids[0]

            # ========== 地图选择:发现研究装置 ==========
            logger.hr("发现研究装置,开始处理", level=2)
            logger.info(f"[地图选择] 在 {grid} 位置发现研究装置")
            record_siren_research_device(self)

            if not self._is_siren_research_enabled:
                logger.warning("[配置检查] 塞壬研究装置功能已禁用,跳过处理")
                self._solved_map_event.add("is_scanning_device")
                return True

            # ========== 移动并处理 ==========
            logger.info(f"[移动装置] 开始移动到装置位置: {grid}")
            self.device.click(grid)

            # 重置标志位
            self.is_siren_device_confirmed = False

            # wait_until_walk_stable 会调用 handle_story_skip 处理选项
            logger.info("[移动装置] 等待移动稳定...")
            with self.config.temporary(
                STORY_ALLOW_SKIP=False, OS_SIREN_DEVICE_USAGE="use_until_destroyed"
            ):
                result = self.wait_until_walk_stable(
                    drop=drop, walk_out_of_step=False, confirm_timer=Timer(3, count=4)
                )
            logger.info(f"[移动装置] 移动完成,结果: {result}")

            if getattr(self, "is_siren_device_confirmed", False):
                # 保存标志状态，因为二次重扫可能会重置它
                siren_confirmed = True

                # 检测选择的模式
                siren_mode = getattr(self, "siren_device_mode", None)
                logger.attr("Siren_device_mode", siren_mode)

                # 如果选择了敌人模式
                if siren_mode == "enemy":
                    logger.info("[装置处理] 敌人模式，执行特殊处理")

                    # 获取配置的舰队
                    task = self.config.task.command
                    if task not in ("OpsiHazard1Leveling", "OpsiMeowfficerFarming"):
                        task = "OpsiHazard1Leveling"
                    siren_fleet = self.config.cross_get(
                        keys=f"{task}.OpsiSirenBug.Siren_Fleet", default=0
                    )

                    # 记录当前舰队
                    current_fleet = self.fleet_selector.get()
                    logger.info(f"[装置处理] 当前舰队: {current_fleet}")

                    # 如果配置了指定舰队，切换到指定舰队
                    if siren_fleet > 0:
                        logger.info(f"[装置处理] 切换到指定舰队: {siren_fleet}")
                        self.fleet_set(siren_fleet)
                    else:
                        logger.info("[装置处理] 使用当前舰队")

                    # 执行三次自律寻敌
                    for i in range(3):
                        logger.info(f"[装置处理] 执行第 {i + 1}/3 次自律寻敌")
                        self.os_auto_search_run(drop=drop)

                    # 如果切换了舰队，切换回原舰队
                    if siren_fleet > 0:
                        logger.info(f"[装置处理] 切换回原舰队: {current_fleet}")
                        self.fleet_set(current_fleet)

                # 如果选择了资源模式
                elif siren_mode == "resource":
                    logger.info("[装置处理] 检测到资源模式，执行标准处理")
                    # 执行一次自律寻敌
                    logger.info("[装置处理] 执行自律寻敌")
                    self.os_auto_search_run(drop=drop)

                # 未知模式或资源不足
                else:
                    logger.info("[装置处理] 未知模式或资源不足，执行标准处理")
                    # 执行一次自律寻敌
                    logger.info("[装置处理] 执行自律寻敌")
                    self.os_auto_search_run(drop=drop)

                # 先标记为已处理，防止二次重扫时再次处理塞壬装置
                self._solved_map_event.add("is_scanning_device")

                # 二次重扫，防止出现意外情况导致装置处理失败
                logger.info("[装置处理] 执行二次重扫")
                self.map_rescan_current(drop=drop)

            return True

        grids = self.view.select(is_logging_tower=True)
        if (
            "is_logging_tower" not in self._solved_map_event
            and grids
            and grids[0].is_logging_tower
        ):
            grid = grids[0]
            logger.info(f"Found logging tower on {grid}")
            self.device.click(grid)
            with self.config.temporary(STORY_ALLOW_SKIP=False):
                result = self.wait_until_walk_stable(
                    drop=drop, walk_out_of_step=False, confirm_timer=Timer(3, count=4)
                )
            if "event" in result:
                self._solved_map_event.add("is_logging_tower")
                return True
            return False

        grids = self.view.select(is_fleet_mechanism=True)
        if (
            self.is_in_task_explore
            and "is_fleet_mechanism" not in self._solved_map_event
            and grids
            and grids[0].is_fleet_mechanism
        ):
            grid = grids[0]
            logger.info(f"Found fleet mechanism on {grid}")
            self.device.click(grid)
            self.wait_until_walk_stable(
                drop=drop, walk_out_of_step=False, confirm_timer=Timer(1.5, count=4)
            )

            if self._solved_fleet_mechanism:
                logger.info("All fleet mechanism are solved")
                self.os_auto_search_run(drop=drop)
                self._solved_map_event.add("is_fleet_mechanism")
                return True
            logger.info("One of the fleet mechanism is solved")
            self._solved_fleet_mechanism = True
            return True

        logger.info("No map event")
        return False

    def map_rescan_once(self, rescan_mode="full", drop=None):
        """
        Args:
            rescan_mode (str): `current` 仅扫描当前摄像机视野，`full` 先扫描当前再重扫整个地图。
            drop: 掉落记录对象。

        Returns:
            bool: 是否解决了地图随机事件。
        """
        result = False

        # 先尝试当前摄像机
        logger.hr("Map rescan current", level=2)
        self.map_data_init(map_=None)
        self.handle_info_bar()
        try:
            self.update()
        except MapDetectionError:
            # 地图可能已清理完毕，单应性变换无法检测到有效格子
            logger.warning(
                "MAP RESCAN CURRENT Homography failed (score below 0.8), "
                "map may be cleared or detection is unstable, unhandled events may be missed"
            )
            return False
        if self.map_rescan_current(drop=drop):
            logger.info("Map rescan once end, result=True")
            return True

        if rescan_mode == "full":
            logger.hr("Map rescan full", level=2)
            self.map_init(map_=None)
            queue = self.map.camera_data
            while len(queue) > 0:
                logger.hr(f"Map rescan {queue[0]}")
                queue = queue.sort_by_camera_distance(self.camera)
                self.focus_to(queue[0], swipe_limit=(6, 5))
                self.focus_to_grid_center(0.3)

                if self.map_rescan_current(drop=drop):
                    result = True
                    break
                queue = queue[1:]

        logger.info(f"Map rescan once end, result={result}")
        return result

    def map_rescan(self, rescan_mode="full", drop=None):
        if self.zone.is_port:
            logger.info("Current zone is a port, do not need rescan")
            return False

        for _ in range(5):
            if not self._solved_fleet_mechanism:
                self.fleet_set(self.config.OpsiFleet_Fleet)
            else:
                self.fleet_set(self.get_second_fleet())
            if not self.is_in_task_explore and len(self._solved_map_event):
                logger.info("Solved a map event and not in OpsiExplore, stop rescan")
                logger.attr("Solved_map_event", self._solved_map_event)
                self.fleet_set(self.config.OpsiFleet_Fleet)
                return False
            result = self.map_rescan_once(rescan_mode=rescan_mode, drop=drop)
            if not result:
                logger.attr("Solved_map_event", self._solved_map_event)
                self.fleet_set(self.config.OpsiFleet_Fleet)
                return True

        logger.attr("Solved_map_event", self._solved_map_event)
        logger.warning("Too many trial on map rescan, stop")
        self.fleet_set(self.config.OpsiFleet_Fleet)
        return False

    def safe_swipe(self, start, end, duration=0.5, retries=2):
        """执行带重试的安全滑动。

        在多次滑动场景中，先尝试清理设备卡住记录，再执行滑动，
        通过重试提升滑动成功率。

        Args:
            start (tuple[int, int]): 滑动起点坐标。
            end (tuple[int, int]): 滑动终点坐标。
            duration (float, optional): 单次滑动时长（秒）。默认值为 0.5。
            retries (int, optional): 最大重试次数。默认值为 2。

        Returns:
            bool: 任一重试成功返回 True；全部失败返回 False。
        """
        for attempt in range(1, retries + 1):
            try:
                with suppress(Exception):
                    self.device.stuck_record_clear()
                self.device.swipe(start, end, duration=duration)
                time.sleep(0.45)
                return True
            except Exception as e:
                logger.warning(f"安全滑动第 {attempt} 次尝试失败: {e}")
                time.sleep(0.4)
                continue
        return False

    def _get_fixed_patrol_candidate_grids(self, target_loc, occupied_locations=None):
        """为强制移动生成候选落点，主目标失败后尝试移动到附近空位。"""
        occupied = set(occupied_locations or [])
        offsets = [
            (0, 0),
            (0, 1),
            (0, 2),
            (-1, 1),
            (1, 1),
            (-1, 2),
            (1, 2),
            (-1, 0),
            (1, 0),
            (0, 3),
        ]
        absolute_fallback_rows = (11, 12)  # 对应地图显示中的第 12、13 行
        candidates = []
        seen = set()
        for dx, dy in offsets:
            loc = (target_loc[0] + dx, target_loc[1] + dy)
            if loc in seen or loc not in self.map or loc in occupied:
                continue
            seen.add(loc)
            grid = self.map[loc]
            if (
                grid.is_land
                or grid.is_enemy
                or grid.is_siren
                or grid.is_boss
                or grid.is_fortress
            ):
                continue
            if getattr(grid, "is_mechanism_block", False) or getattr(
                grid, "is_fleet", False
            ):
                continue
            candidates.append(grid)

        for row in absolute_fallback_rows:
            loc = (target_loc[0], row)
            if loc in seen or loc not in self.map or loc in occupied:
                continue
            seen.add(loc)
            grid = self.map[loc]
            if (
                grid.is_land
                or grid.is_enemy
                or grid.is_siren
                or grid.is_boss
                or grid.is_fortress
            ):
                continue
            if getattr(grid, "is_mechanism_block", False) or getattr(
                grid, "is_fleet", False
            ):
                continue
            candidates.append(grid)
        return candidates

    def _try_fixed_patrol_move(self, fleet_index, target_grid, primary_target):
        """尝试将指定舰队移动到候选落点。"""
        self.focus_to(target_grid.location)
        self.update()
        try:
            clickable_grid = self.convert_global_to_local(target_grid.location)
        except KeyError:
            logger.warning(
                f"已将视角移动到 {target_grid.location}，但在视野中找不到可点击的格子。"
            )
            return False

        for try_idx in range(2):
            try:
                with suppress(Exception):
                    self.device.stuck_record_clear()
                time.sleep(0.1)
                self.device.click(clickable_grid)
                self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4))
                if target_grid.location == primary_target:
                    logger.info(f"舰队 {fleet_index} 已到达 {target_grid}。")
                else:
                    logger.info(
                        f"舰队 {fleet_index} 主目标 {self.map[primary_target]} 失败，已改停靠至备用点 {target_grid}。"
                    )
                return True
            except (MapWalkError, GameTooManyClickError) as e:
                if isinstance(e, MapWalkError) and str(e) == "walk_out_of_step":
                    logger.warning(
                        f"舰队 {fleet_index} 前往 {target_grid} 超出移动范围，放弃当前候选点并尝试其他落点"
                    )
                    return False
                logger.warning(f"舰队移动异常: {e}，尝试强制恢复（{try_idx + 1}/2）")
                recovered = False
                try:
                    recovered = self._force_move_recover(
                        target_zone=self.zone or None
                    )
                except Exception:
                    recovered = False
                if recovered:
                    time.sleep(0.5)
                    self.focus_to(target_grid.location)
                    self.update()
                    try:
                        clickable_grid = self.convert_global_to_local(
                            target_grid.location
                        )
                    except KeyError:
                        clickable_grid = None
                    if clickable_grid:
                        continue
                logger.warning("尝试软恢复（back / screenshot / rebuild view）")
                try:
                    for _ in range(3):
                        with suppress(Exception):
                            self.device.back()
                    self.device.screenshot()
                    try:
                        self.ui_ensure(page_os)
                        self.map_init(map_=None)
                        self.update()
                    except Exception:
                        logger.debug("重建视图失败（soft recovery）", exc_info=True)
                    try:
                        clickable_grid = self.convert_global_to_local(
                            target_grid.location
                        )
                    except KeyError:
                        clickable_grid = None
                    if clickable_grid:
                        logger.info("软恢复后找到格子，重试点击")
                        try:
                            time.sleep(0.3)
                            self.device.click(clickable_grid)
                            self.wait_until_walk_stable(
                                confirm_timer=Timer(1.5, count=4)
                            )
                            logger.info("软恢复成功，舰队已到达")
                            return True
                        except Exception:
                            logger.debug("软恢复重试点击失败", exc_info=True)
                except Exception as rec_e:
                    logger.debug(f"软恢复过程出现异常: {rec_e}")
                if try_idx == 1:
                    logger.warning("软恢复失败，尝试重启应用以恢复状态")
                    try:
                        self.device.app_stop()
                        time.sleep(1.0)
                        self.device.app_start()
                        LoginHandler(self.config, self.device).handle_app_login()
                        self.ui_ensure(page_os)
                        time.sleep(0.8)
                        try:
                            self.map_init(map_=None)
                            self.update()
                        except Exception:
                            logger.debug(
                                "重建地图数据失败（app restart）", exc_info=True
                            )
                        try:
                            clickable_grid = self.convert_global_to_local(
                                target_grid.location
                            )
                        except KeyError:
                            clickable_grid = None
                        if clickable_grid:
                            time.sleep(0.3)
                            self.device.click(clickable_grid)
                            self.wait_until_walk_stable(
                                confirm_timer=Timer(1.5, count=4)
                            )
                            logger.info("重启应用后恢复成功，舰队已到达")
                            return True
                    except Exception:
                        logger.error(
                            "应用重启恢复失败，当前候选点移动失败", exc_info=True
                        )
                time.sleep(0.5)

        return False

    # 基于ShaddockNH3极致侵蚀一的个人修改
    def _execute_fixed_patrol_scan(
        self, ExecuteFixedPatrolScan: bool = False, **kwargs
    ):
        """执行强制移动并触发全图重扫。

        在每支舰队移动前执行视角复位，按预设坐标依次移动 1~4 号舰队，
        全部移动后执行全图重扫，并补一次自律寻敌以清理残留装置。

        Args:
            ExecuteFixedPatrolScan (bool, optional): 是否启用强制移动。
                为 False 时直接跳过。默认值为 False。
            **kwargs: 预留参数，当前未使用。

        Returns:
            None
        """
        logger.hr("执行强制移动")

        if not ExecuteFixedPatrolScan:
            logger.info("ExecuteFixedPatrolScan 未启用，跳过强制移动。")
            return
        logger.attr("ExecuteFixedPatrolScan", True)

        self.map_init(map_=None)
        if not hasattr(self, "map") or not self.map.grids:
            logger.warning("无法获取当前地图网格数据，已跳过强制移动。")
            return

        solved = getattr(self, "_solved_map_event", set())
        if any(
            k in solved for k in ("is_akashi", "is_scanning_device", "is_logging_tower")
        ):
            logger.info("彩蛋：雪风大人保佑你，本次舰队移动已跳过")
            return

        patrol_locations = [(2, 0), (3, 0), (4, 0), (5, 0)]  # 对应 C1, D1, E1, F1
        progress = {}

        for i, target_loc in enumerate(patrol_locations):
            fleet_index = i + 1
            if fleet_index in progress:
                logger.info(
                    f"舰队 {fleet_index} 已在本轮强制移动中完成停靠 ({self.map[progress[fleet_index]]})，跳过重复移动。"
                )
                continue

            target_grid_group = self.map.select(location=target_loc)
            if not target_grid_group:
                logger.warning(
                    f"在地图上找不到坐标为 {target_loc} 的格子，跳过舰队 {fleet_index} 的移动。"
                )
                continue
            target_grid = target_grid_group[0]
            occupied_locations = set(progress.values())
            candidate_grids = self._get_fixed_patrol_candidate_grids(
                target_loc, occupied_locations=occupied_locations
            )
            if not candidate_grids:
                logger.warning(
                    f"舰队 {fleet_index} 在 {target_grid} 附近找不到可用落点，跳过本次移动。"
                )
                continue

            logger.hr(f"强制移动: 指挥舰队 {fleet_index} 前往 {target_grid}", level=2)

            self.fleet_set(fleet_index)

            logger.info("视角复位...")

            top_point = (640, 150)
            bottom_point = (640, 600)
            quick_ok = True
            try:
                for _ in range(2):
                    self.device.swipe(top_point, bottom_point, duration=0.3)
                    time.sleep(0.18)
            except Exception:
                quick_ok = False
                logger.debug("快速滑动复位遇到异常，尝试安全滑动")

            if not quick_ok and not self.safe_swipe(
                top_point, bottom_point, duration=0.55, retries=2
            ):
                logger.warning("视角复位失败，继续尝试下一步")
            elif not quick_ok:
                logger.info("视角复位完成。")
            else:
                logger.info("快速滑动复位完成。")
            time.sleep(0.45)

            moved = False
            fallback_location = None
            for candidate_index, candidate_grid in enumerate(candidate_grids[:4]):
                if candidate_index > 0:
                    logger.info(
                        f"舰队 {fleet_index} 改用备用落点 {candidate_grid}（原目标 {target_grid}）"
                    )
                if self._try_fixed_patrol_move(fleet_index, candidate_grid, target_loc):
                    if candidate_grid.location == target_loc:
                        progress[fleet_index] = candidate_grid.location
                        moved = True
                        break

                    fallback_location = candidate_grid.location
                    logger.info(
                        f"舰队 {fleet_index} 已停靠备用点 {candidate_grid}，尝试返回真正目标 {target_grid}"
                    )
                    if self._try_fixed_patrol_move(
                        fleet_index, target_grid, target_loc
                    ):
                        progress[fleet_index] = target_loc
                        moved = True
                        logger.info(
                            f"舰队 {fleet_index} 已从备用点返回真正目标 {target_grid}"
                        )
                        break

                    logger.warning(
                        f"舰队 {fleet_index} 从备用点 {candidate_grid} 返回真正目标 {target_grid} 失败，继续尝试其他候选点"
                    )
            if not moved:
                if fallback_location is not None:
                    progress[fleet_index] = fallback_location
                    logger.warning(
                        f"舰队 {fleet_index} 无法回到真正目标 {target_grid}，暂时停靠在备用点 {self.map[fallback_location]}。"
                    )
                else:
                    logger.warning(
                        f"舰队 {fleet_index} 在 {target_grid} 及其备用落点均移动失败，继续后续流程。"
                    )

        backup = self.config.temporary(
            OpsiGeneral_RepairThreshold=-1, Campaign_UseAutoSearch=False
        )
        try:
            logger.info("所有舰队已定点，执行最终全图重扫（双遍检查）")
            self._solved_map_event = set()
            for _ in range(2):
                try:
                    self.map_rescan(rescan_mode="full")
                except Exception as e:
                    logger.debug(f"最终全图重扫出现异常，继续重试: {e}", exc_info=True)
                    time.sleep(0.6)
        finally:
            backup.recover()

        logger.info("执行一次自律寻敌以清理可能的装置")
        try:
            self.run_auto_search(question=True, rescan=None, after_auto_search=True)
        except Exception as e:
            logger.warning(f"自律寻敌过程出现异常: {e}")

    def _select_story_option_by_index(self, target_index, options_count=3):
        """按索引点击剧情选项按钮。

        在限定时间内识别剧情选项并尝试点击目标索引；当目标索引越界时，
        回退点击第一个选项。

        Args:
            target_index (int): 目标选项索引（从 0 开始）。
            options_count (int, optional): 期望识别到的选项数量。默认值为 3。

        Returns:
            bool: 点击目标索引成功返回 True；回退点击或超时返回 False。
        """
        option_confirm_timer = Timer(1.5, count=3).start()
        while option_confirm_timer.reached() is False:
            self.device.screenshot()
            # 识别所有选项
            options = self._story_option_buttons_2()
            if len(options) == options_count:
                try:
                    select = options[target_index]
                    self.device.click(select)
                    time.sleep(0.5)
                    return True
                except IndexError:
                    select = options[0]
                    self.device.click(select)
                    time.sleep(0.5)
                    return False
            time.sleep(0.3)
        return False

    def _click_story_confirm_button(self):
        """点击剧情确认按钮。

        在限定时间内轮询确认弹窗，出现后点击确认。

        Returns:
            bool: 成功点击确认返回 True；超时未出现返回 False。
        """
        confirm_timer = Timer(3, count=6).start()
        while confirm_timer.reached() is False:
            self.device.screenshot()
            if self.appear(POPUP_CONFIRM, offset=(20, 20), interval=0):
                self.device.click(POPUP_CONFIRM)
                time.sleep(0.5)
                return True
            time.sleep(0.3)
        return False
