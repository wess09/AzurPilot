"""大世界地图事件的跨重启续查。

大世界海域里“已经看见事件、但还没处理完”时，如果点击后游戏卡死并被重启，
重启后整个任务会从“进入海域、找事件”重新开始，却没留下任何线索。本模块
把这类事件连同装置后续阶段一起存进隐藏配置项，重启后先续查，避免事件被
直接漏掉。

续查语义：
- 明石和未提交的装置先全图扫描。侵蚀一仍找不到时再尝试强制移动。
- 塞壬研究装置：装置已提交物品后按模式补自律寻敌（敌人模式 3 次：自律
  可能被游戏暂停，需要重新点击直到三次；资源模式 1 次，点自律收柱子；
  信息收集 0 次；未知模式 1 次），资源点完即被消耗，不要求对应事件再次
  完成；卡死重启后只补记录里剩下的次数。
- 短猫单海域续查扫不到事件就清掉记录并继续作战，不挪队重扫。

记录在事件真正处理完之前写入（明石开始点击购买前、装置提交物品后的自律
开始前），正常状态下事件处理完立即清除；只有处理中途抛出异常（卡死重启）
才会把记录留在配置里。

主要类:
    MapEventResumeMixin: 给 OSMap 提供续查记录的读写与恢复流程。
"""
from module.config.time_source import now as current_time
from module.config.utils import get_os_next_reset
from module.logger import logger
from module.map.map_base import location2node

# 续查记录存放的隐藏配置项（stored，界面不显示）。
PENDING_MAP_EVENT_KEY = "OpsiHazard1Leveling.OpsiHazard1Leveling.PendingMapEvent"

_PENDING_MAP_EVENT_VERSION = 1
_VALID_EVENT_TYPES = ("akashi", "scanning_device")
_VALID_SIREN_MODES = (None, "enemy", "resource", "collected")


class MapEventResumeMixin:
    """记录并续查“已经看见、但没处理完”的大世界地图事件。"""

    def _pending_event_key(self):
        """获取续查记录在配置里的路径。

        Returns:
            str: 配置路径。
        """
        return PENDING_MAP_EVENT_KEY

    def _read_pending_map_event(self):
        """原样读取续查记录，不做有效性校验。

        Returns:
            dict | None: 记录字典；没有记录时返回 None。
        """
        state = self.config.cross_get(keys=self._pending_event_key(), default=None)
        return state if isinstance(state, dict) else None

    def _pending_event_valid(self, state):
        """校验记录是否属于当前服务器、当前重置周期和当前海域。

        服务器、重置周期或海域一变，旧记录指向的事件就再也找不到了，
        必须当作过期记录丢弃，而不是拿它去别的海域乱扫。

        Args:
            state (dict): 续查记录。

        Returns:
            bool: 记录仍然有效返回 True。
        """
        if state.get("version") != _PENDING_MAP_EVENT_VERSION:
            return False
        if state.get("reset") != get_os_next_reset().isoformat():
            return False
        if state.get("server") != self.config.SERVER:
            return False
        zone = getattr(self, "zone", None)
        if zone is None or state.get("zone") != zone.zone_id:
            return False
        if state.get("type") not in _VALID_EVENT_TYPES:
            return False
        if not state.get("node"):
            return False
        if state.get("mode") not in _VALID_SIREN_MODES:
            return False
        remaining = state.get("remaining", 0)
        if not isinstance(remaining, int) or remaining < 0:
            return False
        return True

    def _load_pending_map_event(self):
        """读取并校验续查记录。

        Returns:
            dict | None: 合法记录；没有记录或记录已过期时返回 None，
                过期记录会顺手清除。
        """
        state = self._read_pending_map_event()
        if state is None:
            return None
        if not self._pending_event_valid(state):
            logger.info(
                "[大世界-事件续查] 续查记录已失效（服务器/重置周期/海域不符），清除"
            )
            self._clear_pending_map_event()
            return None
        return state

    def _save_pending_map_event(self, event_type, grid):
        """写入续查记录（在事件处理完之前写入）。

        同一事件会在多个摄像机视野里被重复识别到，记录已经存在时不再重写，
        避免每次都写一遍配置。

        Args:
            event_type (str): 事件类型，akashi 或 scanning_device。
            grid (OSGrid): 事件所在格子。
        """
        node = location2node(grid.location)
        reset = get_os_next_reset().isoformat()
        existing = self._read_pending_map_event()
        if (
            existing is not None
            and existing.get("type") == event_type
            and existing.get("node") == node
            and existing.get("reset") == reset
        ):
            return
        state = {
            "version": _PENDING_MAP_EVENT_VERSION,
            "reset": reset,
            "server": self.config.SERVER,
            "zone": self.zone.zone_id,
            "type": event_type,
            "node": node,
            "grid": [int(x) for x in grid.location],
            "mode": None,
            "submitted": False,
            "remaining": 0,
            "fleet": self.fleet_selector.get(),
            "created": current_time().isoformat(timespec="seconds"),
        }
        self.config.cross_set(keys=self._pending_event_key(), value=state)
        logger.info(f"[大世界-事件续查] 记录待处理事件: {event_type} {node}")

    def _update_pending_map_event(self, **kwargs):
        """更新续查记录里的字段（如装置模式、是否已提交物品）。

        Args:
            **kwargs: 要覆盖的字段。
        """
        state = self._read_pending_map_event()
        if state is None:
            return
        state.update(kwargs)
        self.config.cross_set(keys=self._pending_event_key(), value=state)

    def _clear_pending_map_event(self):
        """清除续查记录。"""
        self.config.cross_set(keys=self._pending_event_key(), value=None)

    def _finish_pending_map_event(self, event_type, node=None):
        """事件已处理完（或已放弃）时清除续查记录。

        只有记录的事件类型（以及传入时的事件格子）对得上才清除，
        避免把另一只明石/装置的记录误删。

        Args:
            event_type (str): 事件类型。
            node (str, optional): 事件格子，如 'B7'。传入时要求一致。
        """
        state = self._read_pending_map_event()
        if state is not None:
            if state.get("type") != event_type:
                return
            if node is not None and state.get("node") != node:
                return
        self._clear_pending_map_event()

    def _siren_followup_run_count(self, mode):
        """按装置模式返回需要补跑的自律次数。

        敌人模式需要 3 次：游戏可能把自律暂停，必须逐次重新点击直到三次；
        资源模式点一次自律收柱子即可；信息收集装置/柱子已主动点击完成，
        不需要自律；未知模式按标准处理跑一次。

        Args:
            mode (str | None): 装置模式，enemy/resource/collected/None。

        Returns:
            int: 需要执行的自律次数。
        """
        if mode == "enemy":
            return 3
        if mode == "collected":
            return 0
        return 1

    def _record_siren_followup_progress(self):
        """每次自律完成后把剩余次数写回续查记录。

        敌人模式的自律可能中途卡死重启，续查只补没跑完的次数，不能从头再来。
        """
        state = self._read_pending_map_event()
        if state is None:
            return
        remaining = state.get("remaining")
        if isinstance(remaining, int) and remaining > 0:
            self._update_pending_map_event(remaining=remaining - 1)

    def _run_siren_followup_search(self, mode, drop=None, remaining=None):
        """装置提交物品后按模式补跑自律寻敌。

        敌人模式跑 3 次：游戏可能把自律暂停，需要重新点击直到三次；
        资源模式跑 1 次（点自律收柱子）；信息收集 0 次；未知模式 1 次。
        卡死重启后续查时传 remaining，只补记录里剩下的次数。

        Args:
            mode (str | None): 装置模式，enemy/resource/collected/None。
            drop: 掉落记录对象。
            remaining (int, optional): 剩余的自律次数；None 表示按模式跑满。
        """
        count = self._siren_followup_run_count(mode)
        if remaining is not None:
            count = min(count, max(int(remaining), 0))
        if count <= 0:
            if mode == "collected":
                logger.info("[大世界-事件] 信息收集装置/柱子已点击完成，无需自律")
            else:
                logger.info("[大世界-事件] 装置后续自律已无剩余次数，无需继续")
            return

        current_fleet = self.fleet_selector.get()
        siren_fleet = 0
        if mode == "enemy":
            task = self.config.task.command
            if task not in ("OpsiHazard1Leveling", "OpsiMeowfficerFarming"):
                task = "OpsiHazard1Leveling"
            siren_fleet = self.config.cross_get(
                keys=f"{task}.OpsiSirenBug.Siren_Fleet", default=0
            )
        try:
            if siren_fleet > 0:
                logger.info(f"[大世界-事件] 切换到塞壬装置自律舰队: {siren_fleet}")
                self.fleet_set(siren_fleet)
            else:
                logger.info(
                    f"[大世界-事件] 使用当前舰队执行自律寻敌（装置模式: {mode}）"
                )
            for i in range(count):
                logger.info(f"[大世界] [装置处理] 执行第 {i + 1}/{count} 次自律寻敌")
                self.os_auto_search_run(drop=drop)
                self._record_siren_followup_progress()
        finally:
            if siren_fleet > 0:
                logger.info(f"[大世界-事件] 切换回原舰队: {current_fleet}")
                self.fleet_set(current_fleet)

    def _resume_pending_map_event(self, drop=None, *, allow_forced_move=True):
        """重启后续查上次没处理完的地图事件。

        装置已提交物品：按记录里剩余次数补自律寻敌（敌人模式共 3 次，
        资源模式 1 次），补完清记录。
        其他情况先全图扫描。侵蚀一可以升级强制移动，短猫扫不到就继续本轮作战。

        Args:
            drop: 掉落记录对象。
            allow_forced_move (bool): 全图扫描后是否允许挪队重扫。
        """
        state = self._load_pending_map_event()
        if state is None:
            return

        event_type = state.get("type")
        node = state.get("node")
        mode = state.get("mode")
        logger.hr("[大世界-事件续查] 发现上次未处理完的事件，开始续查", level=1)
        logger.attr("续查事件", f"{event_type} {node}")
        logger.attr("塞壬装置模式", mode)

        if event_type == "scanning_device" and state.get("submitted"):
            remaining = state.get("remaining")
            if not isinstance(remaining, int):
                # 旧记录没有剩余次数：按模式补满（敌人 3 次、资源 1 次）
                remaining = self._siren_followup_run_count(mode)
            logger.info(
                f"[大世界-事件续查] 装置已提交物品，补跑剩余 {remaining} 次自律寻敌"
            )
            self._run_siren_followup_search(mode, drop=drop, remaining=remaining)
            self._finish_pending_map_event(event_type, node=node)
            return

        self._solved_map_event = set()
        self._solved_fleet_mechanism = False
        logger.info("[大世界-事件续查] 全图扫描重新查找事件")
        self.map_rescan(rescan_mode="full", drop=drop)
        if self._read_pending_map_event() is None:
            logger.info("[大世界-事件续查] 全图扫描已处理上次的事件")
            return

        if allow_forced_move:
            logger.info("[大世界-事件续查] 全图扫描仍未处理，升级强制移动")
            self._question_unreachable = True
            self._execute_fixed_patrol_scan(ExecuteFixedPatrolScan=True, recovery=True)
            if self._read_pending_map_event() is None:
                logger.info("[大世界-事件续查] 强制移动已处理上次的事件")
                return
            logger.warning(
                "[大世界-事件续查] 全图扫描与强制移动都没能看到事件，"
                "清除续查记录，继续下一轮"
            )
        else:
            logger.info("[大世界-事件续查] 全图扫描未完成待办事件，清除记录并继续作战")
        self._finish_pending_map_event(event_type, node=node)
