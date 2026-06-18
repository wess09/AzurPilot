from module.combat.assets import BATTLE_PREPARATION
from module.event_hospital.assets import *
from module.logger import logger
from module.minigame.assets import BACK
from module.raid.assets import RAID_FLEET_PREPARATION
from module.ui.page import page_hospital
from module.ui.ui import UI


class HospitalUI(UI):
    """医院活动 UI 处理器，处理线索界面的进入和退出。"""

    def is_in_clue(self, interval=0):
        """检测当前是否在线索界面。"""
        return self.appear(HOSIPITAL_CLUE_CHECK, offset=(20, 20), interval=interval)

    def handle_get_clue(self):
        """处理获取线索弹窗。

        检测到获取线索按钮时点击确认。

        Returns:
            bool: 是否点击了确认按钮。
        """
        if self.appear_then_click(GET_CLUE, offset=(20, 20), interval=1):
            return True
        if self.appear(GET_CLUE_TEXT, offset=(20, 20), interval=1):
            logger.info(f'{GET_CLUE_TEXT} -> {GET_CLUE}')
            self.device.click(GET_CLUE)
            return True
        return False

    def handle_clue_exit(self):
        """处理线索界面的退出逻辑。

        检测各种返回按钮并点击，包括战斗退出、
        医院主页跳转、战斗准备返回等。

        Returns:
            bool: 是否点击了返回按钮。
        """
        if self.appear_then_click(HOSPITAL_BATTLE_EXIT, offset=(20, 20), interval=2):
            return True
        if self.ui_page_appear(page_hospital, interval=2):
            logger.info(f'{page_hospital} -> {HOSIPITAL_GOTO_CLUE}')
            self.device.click(HOSIPITAL_GOTO_CLUE)
            return True
        if self.appear(BATTLE_PREPARATION, offset=(30, 20), interval=2):
            logger.info(f'{BATTLE_PREPARATION} -> {BACK}')
            self.device.click(BACK)
            return True
        if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=2):
            logger.info(f'{RAID_FLEET_PREPARATION} -> {BACK}')
            self.device.click(BACK)
            return True
        if self.handle_get_clue():
            return True
        return False
