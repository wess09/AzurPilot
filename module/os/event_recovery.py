"""侵蚀一随机事件的安全定位、有限恢复及重启续查。"""

from module.base.timer import Timer
from module.config.config import Function
from module.config.utils import get_os_next_reset
from module.exception import GameStuckError, MapDetectionError
from module.handler.assets import STORY_SKIP_3
from module.logger import logger
from module.map.map_base import location2node
from module.os.tasks.task_context import opsi_task_context
from module.os_handler.resource_state import reset_resource_caches
from module.statistics.opsi_runtime import record_cl1_akashi_encounter, record_siren_research_device


PENDING_EVENT_PATH = 'OpsiHazard1Leveling.OpsiHazard1Leveling.PendingEventRecovery'
MAP_EVENT_TYPES = (
    'is_exploration_container', 'is_exploration_reward', 'is_akashi',
    'is_scanning_device', 'is_logging_tower', 'is_question',
)


class MapEventRecovery:
    """由 OSMap 混入，统一保留事件身份、定位和恢复预算。"""

    def _event_recovery_enabled(self):
        return (self.config.task.command == 'OpsiHazard1Leveling'
                and self.zone.hazard_level == 1 and not self.zone.is_port
                and not self.is_in_special_zone())

    @staticmethod
    def _map_event_type(grid):
        return next((kind for kind in MAP_EVENT_TYPES if getattr(grid, kind, False)), 'is_question')

    def _event_global_location(self, grid):
        """将本帧的局部格子换算为全局格子，避免挪镜头后继续使用旧坐标。"""
        if not hasattr(grid, 'location'):
            return None
        return tuple(int(g + c - v) for g, c, v in
                     zip(grid.location, self.camera, self.view.center_loca))

    def _event_local_grid(self, target):
        """只换算当前视野，镜头移动由带次数限制的准备步骤负责。"""
        local = tuple(int(g - c + v) for g, c, v in
                      zip(target, self.camera, self.view.center_loca))
        return self.view[local] if local in self.view else None

    def _get_pending_event(self):
        """按服务器、重置周期和当前海域校验隐藏的续查记录。"""
        state = self.config.cross_get(PENDING_EVENT_PATH)
        if state is None:
            return None
        reason = None
        if not isinstance(state, dict):
            reason = '记录格式无效'
        elif state.get('server') != self.config.SERVER:
            reason = '服务器已变化'
        elif state.get('reset') != get_os_next_reset().isoformat():
            reason = '已跨大世界重置周期'
        elif (state.get('zone') != self.zone.zone_id or self.zone.hazard_level != 1
              or self.zone.is_port or self.is_in_special_zone()):
            reason = '当前海域与原侵蚀一海域不符'
        elif state.get('kind') not in MAP_EVENT_TYPES:
            reason = '事件类型无效'
        elif type(state.get('fleet')) is not int or state['fleet'] not in (1, 2, 3, 4):
            reason = '舰队编号无效'
        elif state.get('target') is not None and (
                not isinstance(state['target'], (list, tuple)) or len(state['target']) != 2
                or any(type(n) is not int for n in state['target'])):
            reason = '全局格子格式无效'
        elif state.get('phase', 'interact') not in ('interact', 'followup') or (
                state.get('phase') == 'followup' and (
                    state['kind'] != 'is_scanning_device'
                    or state.get('mode') not in ('enemy', 'resource', 'collected', 'unknown')
                    or type(state.get('remaining')) is not int
                    or not 0 <= state['remaining'] <= 3)):
            reason = '装置后续进度无效'
        if reason is not None:
            logger.warning(f'[大世界-事件] {reason}，作废旧续查记录')
            self.config.cross_set(PENDING_EVENT_PATH, None)
            return None
        state = dict(state)
        if 'recovery_attempted' in state:
            # 旧标记在恢复开始前写入，不能据此认定强制移动已经完整结束。
            state.pop('recovery_attempted')
            self.config.cross_set(PENDING_EVENT_PATH, state)
        return state

    def _event_matches_pending(self, kind, grid):
        """同类事件也按全局格子区分；问号允许在原格子上细化身份。"""
        state = self._get_pending_event()
        if state is None:
            return True
        if state['kind'] != 'is_question' and kind not in (state['kind'], 'is_question'):
            return False
        return state.get('target') is None or tuple(state['target']) == self._event_global_location(grid)

    def _remember_pending_event(self, kind, grid=None):
        """确认随机事件或雷达问号后、首次操作前立即保存；重扫不重置预算。"""
        if not self._event_recovery_enabled() or getattr(self, '_event_recovery_exhausted', False):
            return
        state = self._get_pending_event()
        if state is not None:
            if (grid is not None and hasattr(grid, 'location')
                    and not self._event_matches_pending(kind, grid)):
                return
            changed = False
            if state.get('target') is None and grid is not None:
                target = self._event_global_location(grid)
                if target is not None:
                    state['target'] = list(target)
                    changed = True
            if state['kind'] == 'is_question' and kind != 'is_question' and grid is not None:
                state['kind'] = kind
                changed = True
            if changed:
                self.config.cross_set(PENDING_EVENT_PATH, state)
            return
        target = self._event_global_location(grid)
        self.config.cross_set(PENDING_EVENT_PATH, dict(
            server=self.config.SERVER,
            reset=get_os_next_reset().isoformat(),
            zone=self.zone.zone_id,
            fleet=self.config.OpsiFleet_Fleet,
            target=list(target) if target is not None else None,
            kind=kind,
            phase='interact',
        ))
        logger.attr('待续查事件', f'{kind}, 全局格子={target}')

    def _finish_pending_event(self, kind):
        """调用方确认该事件的收尾流程结束且返回地图后，才允许清除记录。"""
        state = self._get_pending_event() if self.config.task.command == 'OpsiHazard1Leveling' else None
        if state is not None and state['kind'] == kind:
            self.config.cross_set(PENDING_EVENT_PATH, None)
            logger.info(f'[大世界-事件] {kind} 处理完成，清除续查记录')

    def _prepare_event_click(self, target, *, camera_budget=None):
        """刷新格子，必要时至多挪两次镜头，再生成避开固定 UI 的按钮。"""
        if camera_budget is None:
            camera_budget = [2]
        try:
            self.update()
            for attempt in range(3):
                if (self.appear(STORY_SKIP_3, offset=(20, 20)) or not self.is_in_map()
                        or self.fleet_selector.bar_opened()):
                    return None
                grid = self._event_local_grid(target)
                if grid is not None:
                    button = self._event_safe_click_button(grid)
                    if button is not None:
                        return button
                if attempt == 2 or camera_budget[0] <= 0:
                    break
                vector = tuple(max(-limit, min(limit, g - c))
                               for g, c, limit in zip(target, self.camera, (4, 3)))
                if vector == (0, 0):
                    break
                logger.info(f'[大世界-事件] 点击区域被按钮遮挡，调整镜头 {attempt + 1}/2')
                camera_budget[0] -= 1
                self.map_swipe(vector)
        except MapDetectionError:
            logger.warning('[大世界-事件] 无法确认当前地图格子，停止使用旧点击位置')
        return None

    def _try_akashi_grid(self, grid, drop=None):
        """尝试一次已确认明石的安全行军和购买，不在这里递归恢复。"""
        target = self._event_global_location(grid)
        self._remember_pending_event('is_akashi', grid)
        if self._event_recovery_enabled():
            # 相邻明石也可能需要走一格，统一用只发送一次移动指令的事件循环。
            with self.config.temporary(STORY_ALLOW_SKIP=False):
                result = self.wait_until_walk_stable(
                    confirm_timer=Timer(3, count=4), drop=drop, walk_out_of_step=False,
                    allow_event_finish=True, event_target=target,
                )
            return 'akashi' in result
        fleet = self.convert_radar_to_local((0, 0))
        if fleet.distance_to(grid) > 1:
            button = self._prepare_event_click(target)
            if button is None:
                return False
            grid = self._event_local_grid(target)
            fleet = self.convert_radar_to_local((0, 0))
            distance = grid.distance_to(fleet)
            self.device.click(button)
            with self.config.temporary(STORY_ALLOW_SKIP=False):
                result = self.wait_until_walk_stable(
                    confirm_timer=Timer(1.5 + 0.6 * distance, count=4),
                    drop=drop, walk_out_of_step=False, allow_event_finish=True,
                )
            if 'akashi' in result:
                return True
            self.update()
            grid = self._event_local_grid(target)
            if grid is None or self.convert_radar_to_local((0, 0)).distance_to(grid) > 1:
                return False
        return self.handle_akashi_supply_buy(grid)

    def _visit_akashi(self, grid, drop=None):
        """其他任务沿用明石恢复；侵蚀一统一交给地图事件恢复。"""
        if self._event_recovery_enabled():
            return self._visit_map_event('is_akashi', grid, drop=drop)
        node = location2node(self._event_global_location(grid))
        if self._try_akashi_grid(grid, drop=drop):
            self._solved_map_event.add('is_akashi')
            return True
        if (getattr(self, '_event_recovery_active', False)
                or getattr(self, '_in_event_recovery', False)):
            return False
        return self._recover_unreachable_akashi(drop, node)

    def _visit_map_event(self, kind, grid, drop=None):
        if getattr(self, '_event_recovery_exhausted', False):
            return False
        if not self._event_matches_pending(kind, grid):
            return False
        if kind == 'is_scanning_device' and not self._is_siren_research_enabled:
            if self._get_pending_event() is not None:
                self._remember_pending_event(kind, grid)
            record_siren_research_device(self)
            self._solved_map_event.add(kind)
            self._finish_pending_event(kind)
            logger.info('[大世界-事件] 按配置跳过塞壬装置，不触发交互恢复')
            return True
        self._remember_pending_event(kind, grid)
        if self._try_map_event_grid(kind, grid, drop=drop):
            return True
        if (getattr(self, '_event_recovery_active', False)
                or getattr(self, '_in_event_recovery', False)):
            return False
        return self._recover_pending_event(drop=drop)

    def _try_map_event_grid(self, kind, grid, drop=None):
        """只尝试当前事件，不递归恢复；剧情点击或普通弹窗本身不代表完成。"""
        target = self._event_global_location(grid)
        self._remember_pending_event(kind, grid)
        if kind == 'is_akashi':
            if not self._try_akashi_grid(grid, drop=drop):
                return False
            self._solved_map_event.add(kind)
            return True
        self.is_siren_device_confirmed = False
        self._walk_event_completed = False
        options = dict(STORY_ALLOW_SKIP=False, OS_SIREN_DEVICE_USAGE='use_until_destroyed')
        if kind == 'is_exploration_container':
            options['STORY_OPTION'] = 1
        with self.config.temporary(**options):
            result = self.wait_until_walk_stable(
                drop=drop, walk_out_of_step=False, confirm_timer=Timer(3, count=4),
                allow_event_finish=True, event_target=target,
            )
        if 'akashi' in result:
            self._solved_map_event.add('is_akashi')
            return self._get_pending_event() is None
        if kind in ('is_question', 'is_scanning_device') and getattr(self, 'is_siren_device_confirmed', False):
            state = self._get_pending_event()
            mode = getattr(self, 'siren_device_mode', None) or 'unknown'
            if mode not in ('enemy', 'resource', 'collected'):
                mode = 'unknown'
            state.update(kind='is_scanning_device', phase='followup', mode=mode,
                         remaining=3 if mode == 'enemy' else 0 if mode == 'collected' else 1)
            self.config.cross_set(PENDING_EVENT_PATH, state)
            record_siren_research_device(self)
            if not self._is_siren_research_enabled:
                self._solved_map_event.add('is_scanning_device')
                self._finish_pending_event('is_scanning_device')
                return True
            return self._complete_siren_event(state, drop=drop)
        completed = self._walk_event_completed
        if not completed and 'combat' in result and self.is_in_map():
            # 战斗内可能已经收走奖励；必须同时确认舰队到达原事件格，不能把途中战斗当完成。
            self.update()
            current = self._event_local_grid(target)
            completed = current is not None and getattr(current, 'is_current_fleet', False)
        if self.is_in_map() and completed:
            # 最终奖励、档案或原事件格上的战斗收尾；普通剧情和确认弹窗不能确认完成。
            self._solved_map_event.add(kind)
            self._finish_pending_event(kind)
            return True
        return False

    def _complete_siren_event(self, state, drop=None):
        """持久化装置后续自律次数；中断重启后先完成剩余步骤，再清除记录。"""
        current = self.fleet_selector.get()
        if current not in (1, 2, 3, 4):
            current = self.config.OpsiFleet_Fleet
        fleet = self.config.cross_get('OpsiHazard1Leveling.OpsiSirenBug.Siren_Fleet', default=0)
        try:
            if state['mode'] == 'enemy' and fleet > 0:
                self.fleet_set(fleet)
            while state['remaining']:
                self.os_auto_search_run(drop=drop, siren_resource=state['mode'] == 'resource')
                if not self.is_in_map():
                    raise GameStuckError('塞壬装置后续自律未返回地图，保留续查记录')
                state['remaining'] -= 1
                self.config.cross_set(PENDING_EVENT_PATH, dict(state))
            if not self.is_in_map():
                raise GameStuckError('塞壬装置交互未返回地图，保留续查记录')
            self._solved_map_event.add('is_scanning_device')
            self._finish_pending_event('is_scanning_device')
            return True
        finally:
            if state['mode'] == 'enemy' and fleet > 0 and self.is_in_map():
                self.fleet_set(current)

    def _goto_pending_event_with_other_fleets(self, drop=None):
        state = self._get_pending_event()
        current = self.fleet_selector.get()
        if current not in (1, 2, 3, 4):
            current = self.config.OpsiFleet_Fleet
        try:
            for fleet in (n for n in (1, 2, 3, 4) if n != current):
                self.fleet_set(fleet)
                self.device.screenshot()
                self.update()
                if state.get('target') is not None:
                    grid = self._event_local_grid(state['target'])
                    # 重启续查不允许按旧位置盲点；至少需要新图标或雷达问号。
                    if grid is None or not self._pending_event_visible(state, grid):
                        continue
                    kind = self._map_event_type(grid)
                    if kind == 'is_question':
                        kind = state['kind']
                else:
                    grids = self.view.select(**{state['kind']: True}) if state['kind'] != 'is_question' else []
                    grid = grids[0] if grids else self._radar_question_to_local()
                    if grid is None or not self._event_matches_pending(state['kind'], grid):
                        continue
                    kind = self._map_event_type(grid)
                if (self._event_matches_pending(kind, grid)
                        and self._try_map_event_grid(kind, grid, drop=drop)):
                    return True
            return False
        finally:
            if self.is_in_map():
                self.fleet_set(current)

    def _pending_event_visible(self, state, grid):
        if getattr(grid, state['kind'], False):
            return True
        radar_grid = self._radar_question_to_local()
        return radar_grid is not None and self._event_global_location(radar_grid) == self._event_global_location(grid)

    def _abandon_pending_event(self, reason):
        """耗尽本轮预算后结束续查，不把放弃的事件记为完成或触发重启。"""
        logger.warning(f'[大世界-事件] {reason}，结束本次续查，继续下一轮')
        self.config.cross_set(PENDING_EVENT_PATH, None)
        self._event_recovery_exhausted = True
        return False

    def _recover_pending_event(self, drop=None):
        """完整走完一遍仍未找到才结束；异常中断保留事件，重启后重新续查。"""
        if getattr(self, '_event_recovery_active', False):
            return False
        state = self._get_pending_event()
        if state is None:
            return False
        if not self.is_in_map():
            raise GameStuckError('事件交互未返回海域地图，保留续查记录，禁止在其他页面换队')
        if getattr(self, '_event_patrol_attempted', False):
            return self._abandon_pending_event('本次强制移动预算已经使用')
        self._event_recovery_active = True
        try:
            if self._goto_pending_event_with_other_fleets(drop=drop):
                return True
            logger.warning('[大世界-事件] 换队仍无法交互，临时执行本次强制移动')
            self._execute_fixed_patrol_scan(ExecuteFixedPatrolScan=True, event_recovery=True)
            if self._get_pending_event() is None:
                return True
            return self._abandon_pending_event('一遍强制移动后仍未找到原事件')
        finally:
            self._event_recovery_active = False

    def _resume_pending_event(self):
        """在任何新自律或换图前，以侵蚀一身份续查同一海域的未完成事件。"""
        state = self._get_pending_event()
        if state is None:
            return False
        logger.hr(f"[大世界-事件] 优先续查上次中断的 {state['kind']}")
        task = Function(self.config.data['OpsiHazard1Leveling'])
        with opsi_task_context(self.config, task, bind_task='OpsiHazard1Leveling', disable_task_switch=True):
            # 子任务上下文会恢复运行时覆盖，不把续查专用舰队和开关写入配置。
            self.config.override(OpsiFleet_Fleet=state['fleet'], OpsiGeneral_DoRandomMapEvent=True)
            self._solved_map_event = set()
            # 持久化记录存在说明上次尚未收尾；中途异常不等于完整走完一遍。
            self._event_patrol_attempted = False
            self._event_recovery_exhausted = False
            # 旧坐标只作诊断线索；新实例必须重新识别，不能按旧屏幕位置盲点。
            if state.get('phase') == 'followup':
                self._complete_siren_event(state)
            else:
                self.map_rescan(rescan_mode='full')
                if self._get_pending_event() is not None:
                    self._recover_pending_event()
            if 'is_akashi' in self._solved_map_event:
                record_cl1_akashi_encounter(self.config)
        reset_resource_caches(self)
        return True
