"""大世界主任务编排模块。

组合大世界的所有任务模块，提供统一的任务执行入口。
大世界（Operation Siren）是碧蓝航线的开放世界模式，
包含多种任务类型：

- 日常任务（OpsiDaily）：每日固定任务
- 商店（OpsiShop）：港口商店购买
- 代币兑换（OpsiVoucher）：代币商店
- 指挥喵 farming（OpsiMeowfficerFarming）
- 危险海域升级（OpsiHazard1Leveling）
- 舰队自动切换（OpsiFleetAutoChange）
- 行动力溢出保护（OpsiPreventActionPointOverflow）
- 模糊任务（OpsiObscure）
- 深渊任务（OpsiAbyssal）
- 档案任务（OpsiArchive）
- 要塞任务（OpsiStronghold）
- 月度 Boss（OpsiMonthBoss）
- 探索（OpsiExplore）
- 跨月重置（OpsiCrossMonth）

继承自所有任务模块，通过多重继承组合各任务的能力。
"""

from datetime import timedelta

from module.config.time_source import now as current_time
from module.config.utils import get_os_next_reset, get_server_last_update
from module.logger import logger
from module.os_handler.assets import TARGET_ENTER, TARGET_ALL_ON, TARGET_RED_DOT
from module.os_handler.target import OSTargetHandler
from module.os.tasks.daily import OpsiDaily
from module.os.tasks.shop import OpsiShop
from module.os.tasks.voucher import OpsiVoucher
from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os.tasks.fleet_auto_change import OpsiFleetAutoChange
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow
from module.os.tasks.obscure import OpsiObscure
from module.os.tasks.abyssal import OpsiAbyssal
from module.os.tasks.archive import OpsiArchive
from module.os.tasks.stronghold import OpsiStronghold
from module.os.tasks.month_boss import OpsiMonthBoss
from module.os.tasks.explore import OpsiExplore
from module.os.tasks.explore_cleanup import OpsiExploreCleanup
from module.os.tasks.cross_month import OpsiCrossMonth


class OperationSiren(
    OpsiDaily, OpsiShop, OpsiVoucher, OpsiMeowfficerFarming,
    OpsiHazard1Leveling, OpsiFleetAutoChange, OpsiPreventActionPointOverflow, OpsiObscure, OpsiAbyssal,
    OpsiArchive, OpsiStronghold, OpsiMonthBoss, OpsiExplore, OpsiExploreCleanup,
    OpsiCrossMonth,
):
    """大世界（Operation Siren）主类，组合所有任务模块。"""

    def _os_target_enter(self):
        """进入大世界海域目标与成就界面。"""
        self.os_map_goto_globe(unpin=False)
        self.ui_click(click_button=TARGET_ENTER, check_button=TARGET_ALL_ON,
                      offset=(200, 20), retry_wait=3, skip_first_screenshot=True)

    def _os_target_exit(self):
        """退出大世界海域目标界面并返回海域地图。"""
        self.ui_back(check_button=TARGET_ENTER, appear_button=TARGET_ALL_ON,
                     offset=(200, 20), retry_wait=3, skip_first_screenshot=True)
        self.os_globe_goto_map()

    def os_target_receive(self):
        """检查并领取海域目标成就奖励。"""
        next_reset = get_os_next_reset()
        now = current_time()
        logger.attr('大世界下次重置', next_reset)
        if next_reset - now < timedelta(days=1):
            logger.error('[大世界-目标] 距离下次重置仅剩一天，领取的目标奖励可能浪费。'
                         '运行目标奖励收集不太合适，延迟到下次重置。')
        else:
            self.os_map_goto_globe(unpin=False)
            if self.appear(TARGET_RED_DOT):
                self._os_target_enter()
                OSTargetHandler(self.config, self.device).receive_reward()
                self._os_target_exit()
            else:
                logger.info('[大世界-目标] 没有奖励可领取')
        self.config.OpsiTarget_LastRun = now.replace(microsecond=0)

    def _os_target(self):
        """执行大世界海域成就检查与任务流程。"""
        if self.config.OpsiTarget_LastRun > get_server_last_update('00:00'):
            logger.warning('海域目标今日已经运行过，停止任务')
        else:
            logger.hr('大世界-海域目标', level=1)
            self._os_target_enter()
            OSTargetHandler(self.config, self.device).run()
            self._os_target_exit()
            self.config.OpsiTarget_LastRun = current_time().replace(microsecond=0)

    def server_support_os_target(self):
        """检查当前服务器是否支持大世界海域成就功能。

        Returns:
            bool: 若支持海域成就返回 True，否则返回 False。
        """
        return self.config.SERVER in ['cn', 'jp']

    def os_daily(self):
        """执行大世界每日任务并根据配置收集成就奖励。"""
        super().os_daily()
        if self.config.OpsiDaily_CollectTargetReward:
            if self.server_support_os_target():
                self.os_target_receive()
            else:
                logger.info(f'服务器 {self.config.SERVER} 暂不支持海域目标，请联系开发者')


if __name__ == '__main__':
    self = OperationSiren('alas', task='OpsiMonthBoss')

    from module.os.config import OSConfig
    self.config = self.config.merge(OSConfig())

    self.device.screenshot()
    self.os_init()

    logger.hr("大世界-月度Boss", level=1)
    self.clear_month_boss()
