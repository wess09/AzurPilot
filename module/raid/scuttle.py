"""弃船突袭处理器，处理弃船突袭特有的战斗结算逻辑。

与联盟沉船（CoalitionScuttle）一致：仅扣除进图时的一次 2 点心情，
沉船（D 评价）不额外扣减心情。不再自动替换牺牲舰船，
战斗循环由 RunCount 等停止条件控制。
"""

from module.combat.assets import OPTS_INFO_D, BATTLE_STATUS_D, EXP_INFO_D
from module.logger import logger
from module.raid.combat import RaidCombat
from module.raid.run import RaidRun


class RaidScuttleCombat(RaidCombat):
    def handle_battle_status(self, drop=None):
        """
        处理弃船突袭的战斗结算画面，优先识别弃船专用结算按钮。

        Args:
            drop (DropImage): 掉落物图像处理器。

        Returns:
            bool: 是否成功识别并处理了战斗结算。
        """
        if self.is_combat_executing():
            return False
        if self.appear(BATTLE_STATUS_D, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_D)
            return True
        if self.appear(OPTS_INFO_D, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(OPTS_INFO_D)
            return True
        if super().handle_battle_status(drop=drop):
            logger.warning("触发正常结束")
            return True

        return False

    def handle_exp_info(self):
        """
        处理弃船突袭的经验结算画面。

        Returns:
            bool: 是否成功识别并处理了经验结算。
        """
        if self.is_combat_executing():
            return False
        if self.appear_then_click(EXP_INFO_D):
            self.device.sleep((0.25, 0.5))
            return True
        if super().handle_exp_info():
            return True

        return False


class RaidScuttleRun(RaidRun, RaidScuttleCombat):
    """弃船突袭主循环。

    与联盟沉船（CoalitionScuttle）一致：
    - 仅扣除进图时的一次 2 点心情，沉船（D 评价）不额外扣减 10 点心情
    - 不自动替换牺牲舰船，战斗循环由 RunCount 等停止条件控制
    """

    def handle_combat_low_emotion(self):
        """
        重写红脸出击警告弹窗处理。

        沉船任务中牺牲舰必然低心情，红脸弹窗出现时点击确认继续出击，
        不触发计算模式下的心情清零保底。
        """
        return self.handle_popup_confirm('IGNORE_LOW_EMOTION')
