"""
守护模式（Daemon Mode）模块。

后台监控自动化模块，在玩家手动操作时提供辅助支持。
守护模式持续截图并检测游戏状态，自动处理战斗、地图事件、
退役、紧急委托等场景，让玩家的战斗体验更加流畅。

主要功能：
    - 战斗准备和状态处理：自动检测战斗界面并处理战斗结算
    - 地图事件处理：伏击规避、神秘格子处理
    - 地图准备（可选）：自动点击地图准备和舰队准备按钮
    - 退役处理：满仓时自动退役多余舰船
    - 紧急委托：检测并处理紧急委托弹窗
    - 弹窗处理：大舰队弹窗、投票弹窗等
    - 剧情跳过：自动跳过剧情对话

设计特点：
    - 禁用死循环检测（通过 DaemonBase.disable_stuck_detection），
      因为守护模式需要长时间无操作运行
    - 无自动结束条件，需手动停止任务
    - 不主动执行游戏任务，仅辅助处理弹出事件

继承关系：
    - DaemonBase: 禁用死循环检测的基础类，继承自 ModuleBase
    - CampaignBase: 提供战斗、地图、退役等操作能力

Pages:
    无固定页面，在当前游戏页面持续运行
"""

from module.campaign.campaign_base import CampaignBase
from module.daemon.daemon_base import DaemonBase
from module.exception import CampaignEnd
from module.handler.ambush import MAP_AMBUSH_EVADE
from module.map.map_operation import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_HARD


class AzurLaneDaemon(DaemonBase, CampaignBase):
    """
    守护模式主任务类。

    在后台持续监控游戏画面，自动处理各类突发事件。
    主循环以固定间隔截图，依次检查并处理以下场景：

    处理优先级：
        1. 跳过正在执行的战斗
        2. 战斗准备和战斗结算
        3. 伏击规避和神秘格子
        4. 地图准备和舰队准备（需开启 Daemon_EnterMap）
        5. 退役处理（船坞满仓时）
        6. 紧急委托
        7. 大舰队/投票弹窗
        8. 剧情跳过

    属性:
        无额外实例属性

    配置项:
        Daemon_EnterMap: 是否自动进入地图准备

    注意:
        该模式无自动结束条件，运行后需手动停止。
        由于禁用了死循环检测，长时间无截图变化不会触发异常。
    """
    battle_result_retry_interval = 2

    def run(self):
        """执行常规出击守护主循环，持续响应战斗、地图、弹窗等交互。"""
        while 1:
            self.device.screenshot()

            # 如果正在执行战斗，跳过
            if self.is_combat_executing():
                continue

            # 战斗相关
            if self.combat_appear():
                self.combat_preparation()
            try:
                if self.handle_battle_status():
                    self.combat_status(expected_end='no_searching')
                    continue
            except CampaignEnd:
                continue

            # 地图操作
            if self.appear_then_click(MAP_AMBUSH_EVADE, offset=(20, 20)):
                self.device.sleep(1)
                continue
            if self.handle_mystery_items():
                continue

            # 地图准备
            if self.config.Daemon_EnterMap:
                if self.appear_then_click(MAP_PREPARATION, offset=(20, 20), interval=2):
                    continue
                if self.appear_then_click(MAP_PREPARATION_HARD, offset=(20, 20), interval=2):
                    continue
                if self.appear_then_click(FLEET_PREPARATION, offset=(20, 50), interval=2):
                    continue

            # 退役处理
            if self.handle_retirement():
                continue

            # 情绪管理
            pass

            # 紧急委托
            if self.handle_urgent_commission():
                continue

            # 弹窗处理
            if self.handle_guild_popup_cancel():
                return True
            if self.handle_vote_popup():
                continue

            # 剧情跳过
            if self.story_skip():
                continue

            # 结束条件：无自动结束条件，需手动停止

        return True


if __name__ == '__main__':
    b = AzurLaneDaemon('alas', task='Daemon')
    b.run()
