"""每月开荒完成后的独立普通海域事件补扫任务。"""
from module.config.utils import get_os_next_reset
from module.exception import GameStuckError
from module.logger import logger
from module.os.map import OSMap


class OpsiExploreCleanup(OSMap):
    @staticmethod
    def reset_monthly_state(config):
        """月初先清除本任务的旧断点，即使开荒尚未完成也展示新月进度。"""
        state = config.OpsiExploreCleanup_State
        if isinstance(state, dict) and state.get('reset') != get_os_next_reset().isoformat():
            with config.multi_set():
                config.OpsiExploreCleanup_State = None
                config.OpsiExploreCleanup_Progress = ''
        elif isinstance(state, dict) and isinstance(state.get('order'), list) and not config.OpsiExploreCleanup_Progress:
            config.OpsiExploreCleanup_Progress = f'已补扫 {state.get("next", 0)}/{len(state["order"])}'

    @staticmethod
    def explore_complete(config):
        """读取开荒进度；已有月度标记时防止沿用上月的 100%。"""
        progress = config.cross_get('OpsiExplore.OpsiExplore.Progress', default='')
        month = config.cross_get('OpsiExplore.OpsiExplore.MeowfficerCleanupState')
        if isinstance(month, dict):
            return (month.get('reset') == get_os_next_reset().isoformat()
                    and (month.get('phase') == 'done' or progress == '已完成百分之100.00'))
        return progress == '已完成百分之100.00'

    def os_explore_cleanup(self):
        """使用本任务自己的断点执行补扫，开荒不完整时只提示并延期。"""
        self.reset_monthly_state(self.config)
        if not self.explore_complete(self.config):
            logger.warning('本月每月开荒进度未达到 100%，请重新运行一遍每月开荒后再进行事件补扫')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
            return
        reset = get_os_next_reset().isoformat()
        state = self.config.OpsiExploreCleanup_State
        if not isinstance(state, dict) or state.get('reset') != reset:
            order = [int(zone.strip()) for zone in self.config.OS_EXPLORE_FILTER.split('>')]
            state = dict(reset=reset, phase='cleanup', order=order, next=0, attempts=0)
            with self.config.multi_set():
                self.config.OpsiExploreCleanup_State = state
                self.config.OpsiExploreCleanup_Progress = f'已补扫 0/{len(order)}'
        if state.get('phase') != 'done':
            self._run_explore_cleanup()
        self.config.task_delay(target=get_os_next_reset())
        self.config.task_stop()

    def _run_explore_cleanup(self, max_zones=None):
        """只进入已开荒普通海域，复用全图事件扫描和短猫的逐队雷达补查。

        每张图退出成功后保存断点；失败保留当前图，由调度器统一处理重启和连续失败延期。

        Args:
            max_zones (int | None): 本轮最多补扫的海域数；智能调度每轮一张，独立任务默认全部。

        Pages:
            in: IN_MAP 或 IN_GLOBE
            out: IN_GLOBE
        """
        state = self.config.OpsiExploreCleanup_State
        reset = get_os_next_reset().isoformat()
        self._opsi_meowfficer_cleanup = True
        try:
            end = len(state['order']) if max_zones is None else min(state['next'] + max_zones, len(state['order']))
            for index in range(state['next'], end):
                if get_os_next_reset().isoformat() != reset:
                    raise GameStuckError('补扫期间跨月，停止旧月份补扫')
                # 旧尝试次数不能阻止重启后实际进图；连续失败由调度器统一限流。
                state = dict(state, attempts=state['attempts'] + 1)
                self.config.OpsiExploreCleanup_State = state
                zone = state['order'][index]
                logger.hr(f'每月开荒后事件补扫 {index + 1}/{len(state["order"])}: {zone}', level=1)
                # 只选择原始普通海域，避免默认类型顺序选中安全海域。
                self.globe_goto(zone, types='DANGEROUS', force_enter=True)
                if self.zone.zone_id != zone:
                    raise GameStuckError(f'补扫未进入目标海域 {zone}')
                self._solved_map_event = set()
                self._solved_fleet_mechanism = False
                self.fleet_set(self.config.OpsiFleet_Fleet)
                if self.fleet_selector.get() != self.config.OpsiFleet_Fleet:
                    raise GameStuckError('补扫主舰队切换失败')
                # 大世界重扫会遍历全部相机位置；普通战役 full_scan 依赖出生数据，不能用于此处。
                if not self.map_rescan(rescan_mode='full'):
                    raise GameStuckError(f'海域 {zone} 全图补扫未完成')
                self.clear_question_any_fleet()
                self.fleet_set(self.config.OpsiFleet_Fleet)
                self.os_map_goto_globe()
                if get_os_next_reset().isoformat() != reset:
                    raise GameStuckError('补扫期间跨月，停止保存旧月份进度')
                state = dict(state, next=index + 1, attempts=0)
                with self.config.multi_set():
                    self.config.OpsiExploreCleanup_State = state
                    self.config.OpsiExploreCleanup_Progress = f'已补扫 {index + 1}/{len(state["order"])}'
                self.config.check_task_switch()
            if state['next'] >= len(state['order']):
                self.config.OpsiExploreCleanup_State = dict(state, phase='done')
        finally:
            self._opsi_meowfficer_cleanup = False
