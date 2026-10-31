"""默认黄币调度中的三轮智能开荒与月度行动力购买。"""

from module.config.utils import get_os_next_reset
from module.exception import GameStuckError, RequestHumanTakeover
from module.logger import logger


SMART_EXPLORE_ROUTES = (
    (0, 44, 42, 22, 21, 23, 25, 83, 43, 81, 84, 91, 93, 131, 133, 135, 134,
     141, 143, 144, 122, 125, 114, 113, 65, 61, 52, 54, 64, 53),
    (155, 156, 2, 71, 73, 3, 121),
    (41, 105, 104, 103, 101, 102, 106, 24, 12, 11, 13, 14, 33, 31, 32, 34,
     51, 158, 159, 63, 66, 62, 111, 112, 132, 123, 142, 94, 95, 92, 82, 85,
     151, 153, 157, 152, 72, 124),
)
SMART_EXPLORE_ZONES = tuple(zone for route in SMART_EXPLORE_ROUTES for zone in route if zone >= 11)
SMART_EXPLORE_CONFIG = 'OpsiExplore.OpsiExplore.'
ACTION_POINT_PURCHASE_CONFIG = 'OpsiScheduling.OpsiScheduling.BuyActionPoint'


def monthly_explore_complete(config):
    """两种模式共用本月完成标记，兼容旧百分比，不依赖任务开关。"""
    month = config.cross_get('OpsiExplore.OpsiExplore.MeowfficerCleanupState')
    legacy_complete = config.cross_get(SMART_EXPLORE_CONFIG + 'Progress', default='') == '已完成百分之100.00'
    return (isinstance(month, dict) and (month.get('phase') == 'done' or legacy_complete)
            and month.get('reset') == get_os_next_reset().isoformat())


def smart_explore_enabled(config):
    """大世界开荒选择智能模式时，由默认黄币调度推进。"""
    return all(
        config.cross_get(key, default=False) is True for key in (
            'OpsiExplore.Scheduler.Enable',
            'OpsiScheduling.Scheduler.Enable',
            'OpsiScheduling.OpsiScheduling.UseSmartSchedulingOperationCoinsPreserve',
            SMART_EXPLORE_CONFIG + 'SmartEnable',
        ))


class SmartExploreMixin:
    def _get_smart_explore_state(self):
        """以大世界重置周期隔离三轮断点，保留其他智能调度状态。"""
        state = self._get_smart_scheduling_state_value('SmartExplore')
        reset = get_os_next_reset().isoformat()
        if not isinstance(state, dict) or state.get('reset') != reset:
            state = dict(reset=reset, next=[0, 0, 0], second_started=False, second_decided=False,
                         phase='explore', attempts=0)
            self._save_smart_explore_state(state)
        return dict(state, next=list(state['next']))

    def _save_smart_explore_state(self, state):
        if state['reset'] != get_os_next_reset().isoformat():
            raise GameStuckError('智能开荒期间跨月，停止保存旧月份进度')
        self._set_smart_scheduling_state_value('SmartExplore', state)
        completed = sum(sum(zone >= 11 for zone in route[:index])
                        for route, index in zip(SMART_EXPLORE_ROUTES, state['next']))
        phase = {'explore': '开荒', 'cleanup': '开荒', 'done': '已完成'}[state['phase']]
        self.config.cross_set(SMART_EXPLORE_CONFIG + 'Progress',
                              f'已开荒 {completed}/{len(SMART_EXPLORE_ZONES)}，阶段：{phase}')

    def _smart_explore_first_round_complete(self):
        state = self._get_smart_scheduling_state_value('SmartExplore')
        return (isinstance(state, dict) and state.get('reset') == get_os_next_reset().isoformat()
                and state['next'][0] >= len(SMART_EXPLORE_ROUTES[0]))

    def _try_scheduling_action_point_purchase(self):
        """本月仅执行一轮港口行动力购买；流程正常返回即标记完成，中断后可续购。

        普通月度开荒 100% 或智能开荒第一轮完成后才允许购买。
        这里购买港口行动力箱，不调用耗油的每日行动力购买。
        """
        if self.is_running_prevent_action_point_overflow_task():
            return False
        if not self._config_enabled(ACTION_POINT_PURCHASE_CONFIG):
            return False
        if not (monthly_explore_complete(self.config) or self._smart_explore_first_round_complete()):
            return False
        reset = get_os_next_reset().isoformat()
        state = self._get_smart_scheduling_state_value('ActionPointPurchase')
        if isinstance(state, dict) and state.get('reset') == reset and state.get('phase') == 'done':
            return False
        # 旧版的全商店复扫误报会留下 attempts >= 3，不能继续用它阻止本月续购。
        # 实际导航或购买异常仍由上层统一恢复；只在正常退出港口后记为完成。
        state = dict(reset=reset, phase='buying')
        self._set_smart_scheduling_state_value('ActionPointPurchase', state)
        self._close_scheduling_action_point()
        logger.hr('智能调度：本月一次性购买港口全部行动力', level=1)
        self.handle_first_auto_search(run=False)
        self._run_with_opsi_task_context(
            'OpsiShop', self.perform_port_shop_purchase, action_point_only=True,
        )
        if reset != get_os_next_reset().isoformat():
            raise GameStuckError('购买行动力期间跨月，停止旧月份流程')
        self._set_smart_scheduling_state_value('ActionPointPurchase', dict(state, phase='done'))
        return True

    def _run_smart_explore_node(self, state, round_index):
        """每次清理一个普通海域或访问一个解锁港口，成功确认后保存断点。

        Pages:
            in: IN_MAP 或 IN_GLOBE
            out: IN_GLOBE
        """
        from module.os.globe_operation import OSExploreError
        from module.os_handler.action_point import ActionPointLimit

        route = SMART_EXPLORE_ROUTES[round_index]
        zone = route[state['next'][round_index]]
        if state['attempts'] >= 3:
            raise RequestHumanTakeover(f'智能开荒海域 {zone} 连续三次未完成，请检查解锁条件和事件')
        state = dict(state, attempts=state['attempts'] + 1)
        self._save_smart_explore_state(state)
        self._close_scheduling_action_point()
        self.handle_first_auto_search(run=False)
        try:
            with self.config.temporary(OS_ACTION_POINT_PRESERVE=0):
                if zone < 11:
                    self.globe_goto(zone)
                    self.port_enter()
                    self.port_quit()
                else:
                    # 强制确认全球地图类型，避免已在未清理目标海域时误当成完成。
                    entered = self.globe_goto(zone, stop_if_safe=True, force_enter=True)
                    if entered:
                        self._run_with_opsi_task_context('OpsiExplore', self._clear_smart_explore_zone)
                        self.os_map_goto_globe()
                        self.globe_update()
                        self.globe_focus_to(self.name_to_zone(zone))
                        if not self.zone_has_safe():
                            raise GameStuckError(f'智能开荒海域 {zone} 尚未解锁安全海域，保留当前断点')
                        self.ensure_no_zone_pinned()
        except OSExploreError as exc:
            raise GameStuckError(f'智能开荒海域 {zone} 未解锁，保留路线断点') from exc
        except ActionPointLimit:
            # 资源不足不是地图识别失败，不能耗尽三次恢复机会。
            self._save_smart_explore_state(dict(state, attempts=state['attempts'] - 1))
            raise
        state['next'][round_index] += 1
        self._save_smart_explore_state(dict(state, attempts=0))

    def _clear_smart_explore_zone(self):
        """复用月度开荒的样本、扫描、清敌、全图事件扫描及战后恢复。"""
        if not self.config.OpsiExplore_SpecialRadar:
            self.tuning_sample_use()
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=not self.config.OpsiExplore_SpecialRadar,
                              submarine_call=self.config.OpsiFleet_Submarine)
        # 两种开荒模式共用运行间隔开关。
        if not self.config.OpsiExplore_SpecialRadar and not self._config_enabled(SMART_EXPLORE_CONFIG + 'ForceRun'):
            self.config.task_delay(minute=27, task='OpsiScheduling')
        self.run_auto_search(question=False, rescan='full')
        self.handle_after_auto_search()

    def _run_smart_explore_once(self, yellow_coins, total_ap, current_ap):
        """仅默认黄币调度执行智能开荒；补币逐图达标即回侵蚀一。"""
        if not smart_explore_enabled(self.config) or self.is_running_prevent_action_point_overflow_task():
            return False
        previous = self._get_smart_scheduling_state_value('SmartExplore')
        current = isinstance(previous, dict) and previous.get('reset') == get_os_next_reset().isoformat()
        if current and previous.get('phase') == 'done':
            return False
        # 兼容旧版已完成路线、尚未结束的补扫阶段，直接完成收尾。
        pending_cleanup = current and previous.get('phase') == 'cleanup'
        if monthly_explore_complete(self.config) and not pending_cleanup:
            return False
        state = self._get_smart_explore_state()
        if state['phase'] == 'done':
            return False
        preserve = self._get_smart_scheduling_operation_coins_preserve()
        if state['next'][0] < len(SMART_EXPLORE_ROUTES[0]):
            self._run_smart_explore_node(state, 0)
            return True
        if state['next'][1] < len(SMART_EXPLORE_ROUTES[1]):
            if not state.get('second_decided', False):
                # 第一轮结束后的 1360 判定只做一次；不购买则第二轮保留给补黄币。
                buy_enabled = self._config_enabled(ACTION_POINT_PURCHASE_CONFIG)
                if total_ap <= 1360 and buy_enabled and self._try_scheduling_action_point_purchase():
                    total_ap, current_ap = self._get_scheduling_action_point()
                    yellow_coins = self.get_yellow_coins()
                state = dict(state, second_started=total_ap > 1360 or buy_enabled, second_decided=True)
                self._save_smart_explore_state(state)
            if state['second_started']:
                self._run_smart_explore_node(state, 1)
                return True
        if all(index >= len(route) for index, route in zip(state['next'], SMART_EXPLORE_ROUTES)):
            if state['phase'] != 'cleanup':
                state = dict(state, phase='cleanup')
                self._save_smart_explore_state(state)
            if not monthly_explore_complete(self.config):
                # 收尾中断后仍可补写本月完成标记，不把第一轮当作全图完成。
                with self.config.multi_set():
                    self.config.cross_set('OpsiExplore.OpsiExplore.MeowfficerCleanupState',
                                          dict(reset=state['reset'], phase='done'))
                    self.config.cross_set('OpsiExplore.OpsiExplore.LastZone', 0)
                    # 5000 油记录仪在下月失效，不能沿用本月的免扫描状态。
                    self.config.cross_set('OpsiExplore.OpsiExplore.SpecialRadar', False)
                    self.config.task_delay(target=get_os_next_reset(), task='OpsiExplore')
            self._save_smart_explore_state(dict(state, phase='done'))
            return True
        active = self._is_coin_replenish_active()
        if yellow_coins < preserve or active:
            target, _, _ = self._get_coin_replenish_target(yellow_coins, preserve)
            if yellow_coins < target:
                for round_index in (1, 2):
                    if state['next'][round_index] < len(SMART_EXPLORE_ROUTES[round_index]):
                        self._run_smart_explore_node(state, round_index)
                        return True
            self._clear_coin_replenish_target()
        if total_ap <= self._get_effective_cl1_ap_preserve():
            if self._try_scheduling_action_point_purchase():
                return True
            self._delay_smart_scheduling_for_ap_limit(total_ap, self._get_effective_cl1_ap_preserve())
            return True
        self._execute_hazard1_leveling(yellow_coins, total_ap, current_ap)
        return True
