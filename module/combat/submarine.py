"""潜艇呼叫管理模块。

管理战斗中的潜艇呼叫操作。

潜艇呼叫模式：
- do_not_use: 不使用潜艇
- hunt_only: 仅狩猎模式（潜艇自动攻击范围内敌人）
- boss_only: 仅 Boss 战呼叫潜艇
- hunt_and_boss: 狩猎 + Boss 战都使用潜艇

潜艇呼叫需要消耗潜艇弹药，弹药耗尽后无法呼叫。
呼叫时机由自动搜索设置中的潜艇角色配置决定。

继承自 ModuleBase，被 Combat 组合使用。
"""

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.combat.assets import *
from module.logger import logger


class SubmarineCall(ModuleBase):
    """潜艇呼叫管理器。

    在战斗中控制潜艇的呼叫时机和状态。

    Attributes:
        submarine_call_flag (bool): 本次战斗是否已呼叫过潜艇。
        submarine_call_timer (Timer): 潜艇呼叫检测计时器。
        submarine_call_click_timer (Timer): 潜艇呼叫点击间隔计时器。
    """
    submarine_call_flag = False
    submarine_call_timer = Timer(5)
    submarine_call_click_timer = Timer(1)
    submarine_advanced = None

    def submarine_call_reset(self):
        """每次战斗执行前重置呼叫状态，避免不同实例共享计时器。"""
        self.submarine_call_timer = Timer(5).start()
        self.submarine_call_click_timer = Timer(2)
        self.submarine_call_flag = False

    def handle_submarine_call(self, submarine='do_not_use', call=False):
        """处理潜艇呼叫。

        Returns:
            bool: 是否执行了呼叫操作。
        """
        if self.submarine_call_flag:
            return False
        # 高级规则只接受地图已经规划好的召唤，缺少地图上下文时不出击。
        if submarine == 'advanced':
            self.submarine_call_flag = True
            return False
        if submarine == 'advanced_call':
            state = self.submarine_advanced
            if (state is None or state.plan is None or state.plan.mode != 'call'
                    or state.ammo <= 0 or state.consumed):
                self.submarine_call_flag = True
                return False
        if call and submarine == 'boss_only':
            pass
        else:
            if submarine in ['do_not_use', 'hunt_only', 'boss_only', 'hunt_and_boss']:
                self.submarine_call_flag = True
                return False
        # 先确认召唤结果，避免最后一次点击后计时到期而遗漏弹药扣减。
        available = self.appear(SUBMARINE_AVAILABLE_CHECK_1) and self.appear(SUBMARINE_AVAILABLE_CHECK_2)
        if available and self.appear(SUBMARINE_CALLED):
            logger.info('潜艇已呼叫')
            if submarine == 'advanced_call':
                self.submarine_advanced.consume('call')
            self.submarine_call_flag = True
            return False
        if self.submarine_call_timer.reached():
            logger.info('潜艇呼叫计时器到达')
            self.submarine_call_flag = True
            return False

        if not available:
            return False

        if self.submarine_call_click_timer.reached():
            # 高级模式依赖真实的可召唤图标，不能盲点耗尽或范围外的按钮。
            if submarine == 'advanced_call':
                if self.appear_then_click(SUBMARINE_READY, interval=2):
                    self.submarine_call_click_timer.reset()
                    self.submarine_call_timer.reset()
                    return True
                return False
            if not self.appear_then_click(SUBMARINE_READY):
                logger.info('错误的潜艇图标')
                self.device.click(SUBMARINE_READY)
            logger.info('呼叫潜艇')
            self.submarine_call_click_timer.reset()
            return True
        return False
