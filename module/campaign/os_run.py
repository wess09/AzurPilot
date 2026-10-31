"""大世界战役运行模块。

管理大世界（Operation Siren）任务的执行流程。

大世界是一个独立于主线战役的开放世界系统，有自己的：
- 行动力（Action Point）机制
- 适应性（Adaptability）系统
- 净化装置（Purification Device）
- 港口商店和任务系统

此模块负责：
- 加载大世界配置和地图操作实例
- 处理行动力溢出保护
- 大世界任务的延迟和调度
- 行动力不足时的任务延迟

继承自 OSMapOperation，提供大世界地图操作能力。
"""

from module.config.utils import get_os_reset_remain
from module.logger import logger
from module.os.config import OSConfig
from module.os.map_operation import OSMapOperation
from module.os.operation_siren import OperationSiren
from module.os_handler.action_point import ActionPointLimit


class OSCampaignRun(OSMapOperation):
    """大世界战役运行器。

    管理大世界任务的执行，包括行动力保护和任务调度。

    Attributes:
        PREVENT_AP_OVERFLOW_TASK (str): 防止行动力溢出的任务名称。
    """
    PREVENT_AP_OVERFLOW_TASK = 'OpsiPreventActionPointOverflow'

    def load_campaign(self, cls=OperationSiren):
        """加载并初始化大世界战役实例。

        Args:
            cls (type): 大世界战役类。默认 OperationSiren。

        Returns:
            OperationSiren: 初始化后的大世界战役实例。
        """
        config = self.config.merge(OSConfig())
        campaign = cls(config=config, device=self.device)
        campaign.os_init()
        return campaign

    def delay_opsi_tasks_after_ap_limit(self, error):
        """因行动力限制触发后延迟大世界任务。

        Args:
            error (ActionPointLimit): 行动力限制异常对象。
        """
        delay_minutes = getattr(error, 'delay_minutes', None)
        if delay_minutes is not None:
            logger.info(f'[大世界-运行] 延迟大世界行动力任务 {delay_minutes} 分钟直到行动力恢复')
        self.config.opsi_task_delay(ap_limit=True, ap_limit_minutes=delay_minutes)

    def _run_opsi_task_with_ap_overflow_guard(self, runner):
        """运行普通大世界任务时临时暂停派发防溢出任务，并在结束时恢复调度。

        暂停只作用于本进程的调度队列，不改写用户的
        `OpsiPreventActionPointOverflow.Scheduler.Enable`。因此运行期间用户
        保存的开关不会被收尾流程覆盖，进程被强制终止也不会遗留临时状态。

        Args:
            runner (callable): 接收 campaign 实例的执行函数。

        Returns:
            Any: runner 函数的执行结果。
        """
        campaign = None
        prevent_enabled = self.config.is_task_enabled(self.PREVENT_AP_OVERFLOW_TASK)
        if prevent_enabled:
            logger.info('[战役] 本次运行暂停派发防止行动力溢出任务')
            self.config.exclude_task_runtime(self.PREVENT_AP_OVERFLOW_TASK)

        try:
            campaign = self.load_campaign()
            return runner(campaign)
        finally:
            if prevent_enabled:
                self.config.resume_task_runtime(self.PREVENT_AP_OVERFLOW_TASK)
                # 用户可能在运行期间关闭了防溢出任务，收尾时以磁盘上的最新设置判断。
                if campaign is not None:
                    try:
                        self.config.load()
                    except Exception:
                        logger.debug('重新加载配置失败，改用内存中的开关判断', exc_info=True)
                    if self.config.is_task_enabled(self.PREVENT_AP_OVERFLOW_TASK):
                        try:
                            campaign.update_prevent_action_point_overflow_schedule(enable=None)
                        except Exception:
                            logger.debug('更新防止行动力溢出任务排期失败，保留用户当前设置', exc_info=True)

    def opsi_explore(self):
        """执行大世界海域开荒探索任务。"""
        from module.os.tasks.smart_explore import smart_explore_enabled

        if smart_explore_enabled(self.config):
            logger.info('智能开荒已接管普通海域，唤起智能调度')
            self.config.task_call('OpsiScheduling', force_call=False)
            self.config.task_delay(server_update=True)
            self.config.task_stop()
            return
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_explore())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_explore_cleanup(self):
        """先检查每月开荒进度，满足条件后才初始化设备与独立补扫任务。"""
        from module.os.tasks.explore_cleanup import OpsiExploreCleanup
        OpsiExploreCleanup.reset_monthly_state(self.config)
        if not OpsiExploreCleanup.explore_complete(self.config):
            logger.warning('本月每月开荒进度未达到 100%，请重新运行一遍每月开荒')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
            return
        state = self.config.OpsiExploreCleanup_State
        if isinstance(state, dict) and state.get('phase') == 'done':
            from module.config.utils import get_os_next_reset
            self.config.task_delay(target=get_os_next_reset())
            self.config.task_stop()
            return
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_explore_cleanup())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_shop(self):
        """执行大世界港口商店购买任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_shop())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_voucher(self):
        """执行大世界特别兑换凭证购买任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_voucher())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_daily(self):
        """执行大世界每日任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_daily())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_meowfficer_farming(self):
        """执行大世界指挥喵打捞刷取任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_meowfficer_farming())
        except ActionPointLimit:
            if get_os_reset_remain() > 0:
                self.config.task_delay(server_update=True)
                self.config.task_call('Reward', force_call=False)
            else:
                logger.info('[大世界-运行] 距离大世界重置不足1天，延迟2.5小时')
                self.config.task_delay(minute=150, server_update=True)

    def opsi_hazard1_leveling(self):
        """执行大世界侵蚀1练级任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(
                lambda campaign: (campaign.os_check_leveling(), campaign.os_hazard1_leveling())
            )
        except ActionPointLimit:
            self.config.task_delay(server_update=True)

    def opsi_obscure(self):
        """执行大世界隐秘海域任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_obscure())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_month_boss(self):
        """执行大世界月度 Boss 挑战任务。"""
        if self.config.SERVER in ['tw']:
            logger.info(f'[大世界-运行] OpsiMonthBoss不支持服务器 {self.config.SERVER}，请联系服务器维护者')
            self.config.task_delay(server_update=True)
            self.config.task_stop()
            return
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.clear_month_boss())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_abyssal(self):
        """执行大世界深渊海域任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_abyssal())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_archive(self):
        """执行大世界档案海域任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_archive())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_stronghold(self):
        """执行大世界要塞海域任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_stronghold())
        except ActionPointLimit as e:
            self.delay_opsi_tasks_after_ap_limit(e)

    def opsi_scheduling(self):
        """执行大世界智能调度任务。"""
        # 必须在 load_campaign() 前拦截，否则 os_init() 会执行首次自律寻敌。
        if self.is_in_opsi_explore():
            logger.info('[大世界-智能调度] 每月开荒正在运行，初始化前延期智能调度')
            self.config.task_delay(
                server_update=self.config.cross_get(
                    keys='OpsiScheduling.Scheduler.ServerUpdate',
                    default='00:00',
                ),
                task='OpsiScheduling',
            )
            self.config.task_stop()
            return

        self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.run_smart_scheduling())

    def opsi_prevent_action_point_overflow(self):
        """执行大世界防止行动力溢出任务。"""
        campaign = self.load_campaign()
        campaign.os_prevent_action_point_overflow()

    def opsi_cross_month(self):
        """执行大世界跨月重置前置与收尾任务。"""
        try:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_cross_month())
        except ActionPointLimit:
            self._run_opsi_task_with_ap_overflow_guard(lambda campaign: campaign.os_cross_month_end())
