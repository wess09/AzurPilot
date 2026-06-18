from module.combat.assets import EXP_INFO_C, EXP_INFO_D
from module.combat.combat import Combat
from module.guild.assets import BATTLE_STATUS_CF, EXP_INFO_CF


class RaidCombat(Combat):
    def handle_battle_status(self, drop=None):
        """
        处理突袭战斗的状态结算画面，识别大世界风格的战斗结算按钮。

        Args:
            drop (DropImage): 掉落物图像处理器。

        Returns:
            bool: 是否成功识别并处理了战斗结算。
        """
        if self.is_combat_executing():
            return False
        if super().handle_battle_status(drop=drop):
            return True
        if self.appear(BATTLE_STATUS_CF, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_CF)
            return True

        return False

    def handle_get_items(self, drop=None):
        """
        处理突袭战斗中的获取物品画面。

        Args:
            drop (DropImage): 掉落物图像处理器。

        Returns:
            bool: 是否成功处理了物品获取。
        """
        if super().handle_get_items(drop=drop):
            self.interval_reset(BATTLE_STATUS_CF)
            return True
        else:
            return False

    def handle_exp_info(self):
        """
        处理突袭战斗中的经验值结算画面。

        Returns:
            bool: 是否成功识别并处理了经验结算。
        """
        if self.is_combat_executing():
            return False
        if super().handle_exp_info():
            return True
        if self.appear_then_click(EXP_INFO_C):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(EXP_INFO_D):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(EXP_INFO_CF):
            self.device.sleep((0.25, 0.5))
            return True

        return False
