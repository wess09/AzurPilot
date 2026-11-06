"""深渊海域的可选断点记录；实际寻路、战斗与脱离仍由 OSFleet 执行。"""

from module.config.utils import get_os_next_reset
from module.logger import logger
from module.os.assets import ABYSSAL_MAP_CHECK


ABYSSAL_RESUME_KEY = 'OpsiAbyssal.Storage.Storage.AbyssalResume'
ABYSSAL_CONTINUE_KEY = 'OpsiAbyssal.OpsiAbyssal.ContinueAfterRestart'


class AbyssalResumeMixin:
    """仅在深渊续接开关开启时保存进度，不改变其他海域的恢复方式。"""

    def abyssal_continue_enabled(self):
        """读取独立深渊任务的开关，兼容智能调度等代理入口。"""
        return self.config.cross_get(ABYSSAL_CONTINUE_KEY, default=False) is True

    def is_in_abyssal(self):
        """由退出入口和深渊任务目标共同确认当前海域，避免接管其他特殊海域。"""
        return self.is_in_special_zone() and self.appear(ABYSSAL_MAP_CHECK, offset=(20, 20))

    def _load_abyssal_resume(self):
        """旧断点只能用于相同服务器、重置周期和海域。"""
        state = self.config.cross_get(ABYSSAL_RESUME_KEY, default=None)
        if not isinstance(state, dict):
            return None
        if (state.get('server') == self.config.SERVER
                and state.get('reset') == get_os_next_reset().isoformat()
                and state.get('zone') == self.zone.zone_id
                and state.get('entry_fleet') in (0, 1, 2, 3, 4)
                and state.get('phase') in ('search', 'boss')
                and state.get('active') in (0, 1, 2, 3, 4)
                and isinstance(state.get('fighting'), bool)
                and isinstance(state.get('completed'), list)
                and all(fleet in (1, 2, 3, 4) for fleet in state['completed'])):
            return dict(state, completed=list(state['completed']))
        logger.info('[大世界-深渊续接] 断点已失效，按当前画面继续')
        self._clear_abyssal_resume()
        return None

    def _save_abyssal_resume(self, state):
        """在操作前落盘，避免进程重启后丢失探路舰队或出战位置。"""
        self.config.cross_set(ABYSSAL_RESUME_KEY, dict(state, completed=list(state['completed'])))

    def _clear_abyssal_resume(self):
        """确认离开深渊后清除断点，不带入下一张坐标。"""
        if self.config.cross_get(ABYSSAL_RESUME_KEY, default=None) is not None:
            self.config.cross_set(ABYSSAL_RESUME_KEY, None)

    def _new_abyssal_resume(self):
        """记住进入第一阶段时的实际舰队，而非 Boss 筛选器的第一项。"""
        state = {
            'server': self.config.SERVER,
            'reset': get_os_next_reset().isoformat(),
            'zone': self.zone.zone_id,
            'entry_fleet': self.fleet_selector.get(),
            'phase': 'search',
            'active': 0,
            'fighting': False,
            'completed': [],
        }
        self._save_abyssal_resume(state)
        return state

    def _record_abyssal_combat(self):
        """确认进入战斗时才标记已出战，单纯行军中重启不会跳过该舰队。"""
        state = getattr(self, '_abyssal_battle_progress', None)
        if state is not None and state['active'] and not state['fighting']:
            state['fighting'] = True
            self._save_abyssal_resume(state)

    def _resume_abyssal_fleet(self, state, fleets, has_fleet_step, drop):
        """先脱离中断的 Boss 战，再沿原筛选顺序继续后续舰队。

        Pages:
            in: 深渊地图，可能仍显示行动中和脱离按钮。
            out: 深渊地图，中断的舰队已脱离并回到原待命位置。
        """
        self.update_os()
        self.predict()
        caught = any(grid.predict_caught_by_siren() for grid in self.view)
        if not (state['fighting'] or caught):
            return
        current = state['active'] or self.fleet_selector.get()
        if current and self.fleet_selector.get() != current:
            self.fleet_set(current)
        state.update(phase='boss', active=current, fighting=True)
        # 没有旧记录时，当前行动中的舰队即本轮出战位置；之前的舰队也不重打。
        if any(fleet.fleet_index == current for fleet in fleets):
            for fleet in fleets:
                if fleet.fleet_index not in state['completed']:
                    state['completed'].append(fleet.fleet_index)
                if fleet.fleet_index == current:
                    break
        self._save_abyssal_resume(state)
        logger.info(f'[大世界-深渊续接] 舰队 {current} 的战斗中断，先脱离后继续下一队')
        self.boss_leave()
        for fleet in fleets:
            if fleet.fleet_index == current and fleet.standby_loca != (0, 0):
                self.boss_goto(location=fleet.standby_loca, has_fleet_step=has_fleet_step, drop=drop)
                break
        state.update(active=0, fighting=False)
        self._save_abyssal_resume(state)
