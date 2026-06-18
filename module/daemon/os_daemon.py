from module.combat.assets import EXP_INFO_C, EXP_INFO_D
from module.daemon.daemon_base import DaemonBase
from module.exception import CampaignEnd
from module.logger import logger
from module.os.config import OSConfig
from module.os.fleet import OSFleet
from module.os_combat.combat import ContinuousCombat
from module.os_handler.assets import AUTO_SEARCH_REWARD
from module.os_handler.port import PORT_ENTER, PortHandler


class AzurLaneDaemon(DaemonBase, OSFleet, PortHandler):
    def _os_combat_expected_end(self):
        """大世界战斗预期结束判断，优先处理搜索奖励弹窗。"""
        if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=2):
            return False

        return super()._os_combat_expected_end()

    def run(self):
        """大世界守护模式主循环。

        持续截图并按优先级处理：战斗状态 > 战斗准备 > 经验结算 > 地图事件 >
        港口维修 > 选择敌人。无终止条件，需手动停止。
        """
        self.config.merge(OSConfig())
        self.config.override(HOMO_EDGE_DETECT=False)
        while 1:
            self.device.screenshot()

            # 战斗执行中，不做额外操作
            if self.is_combat_executing():
                continue

            # 战斗处理
            if self.combat_appear():
                self.combat_preparation()
            try:
                if self.handle_battle_status():
                    self.combat_status(expected_end='no_searching')
                    continue
            except (CampaignEnd, ContinuousCombat):
                continue
            if self.appear_then_click(EXP_INFO_C, interval=2):
                continue
            if self.appear_then_click(EXP_INFO_D, interval=2):
                continue

            # 地图事件处理
            if self.handle_map_event():
                self._nearest_object_click_timer.clear()
                continue
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=2):
                continue

            # 港口维修
            if self.config.OpsiDaemon_RepairShip:
                if self.appear(PORT_ENTER, offset=(20, 20), interval=30):
                    self.port_enter()
                    self.port_dock_repair()
                    self.port_quit()
                    self.interval_reset(PORT_ENTER)
                    logger.info('Port repair finished, '
                                'please move your fleet out of the port in 30s to avoid repairing again')

            # 自动选择最近敌人
            if self.config.OpsiDaemon_SelectEnemy:
                if self.click_nearest_object():
                    continue

            # 无终止条件，需手动停止

        return True


if __name__ == '__main__':
    b = AzurLaneDaemon('alas', task='OpsiDaemon')
    b.run()
