"""联动活动战斗处理模块。

处理联动活动中的战斗流程，包括战斗重新进入、
战斗状态检测、战役结束判定等。继承 CoalitionUI 和
CampaignBase，组合 UI 导航与战役战斗能力。
"""

from module.base.timer import Timer
from module.campaign.campaign_base import CampaignBase
from module.coalition.assets import *
from module.coalition.ui import CoalitionUI
from module.exception import CampaignEnd
from module.logger import logger
from module.os_ash.assets import BATTLE_STATUS


class CoalitionCombat(CoalitionUI, CampaignBase):
    """联合出击战斗处理器。"""

    battle_status_click_interval = 2
    battle_result_retry_interval = battle_status_click_interval
    auto_search_defeat_recovery = False
    coalition_result_confirm_buttons = (COALITION_REWARD_CONFIRM,)

    def coalition_emotion_reduce(self):
        """多队整关扣一次基础心情，单队每次重新进入战斗都扣减。"""
        return self.battle_count == 0 or self.config.Coalition_Fleet == 'single'

    def coalition_combat_re_enter(self, skip_first_screenshot=True):
        """处理一轮战斗结束到下一轮战斗重新加载进入的过程。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: BATTLE_STATUS
            out: is_combat_executing

        Raises:
            CampaignEnd: 检测到回到联合出击主页面，本次战役全部战斗已结束。
        """
        logger.info('[联动-战斗] 联动战斗重新进入')
        self.device.screenshot_interval_set()
        status_clicked = False
        click_timer = Timer(0.3)
        click_last = Timer(1, count=3)
        veritas_ex = getattr(self.config, 'Campaign_Name', '') == 'coalition_20261124_ex'
        result_timer = Timer(2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 退出条件
            if self.is_combat_loading():
                break
            if self.is_combat_executing():
                break
            if self.in_coalition():
                raise CampaignEnd

            if self.handle_combat_defeat():
                continue
            # 执行阶段可能错过结果帧；在活动通用按钮推进前补充观察与记账。
            self.combat_result_observe()
            if self.appear_then_click(BATTLE_STATUS, offset=(80, 20), interval=2):
                # 偏移约 (+53, +3)
                continue
            if any(self.appear_then_click(button, offset=(20, 20), interval=2)
                   for button in self.coalition_result_confirm_buttons):
                # 战斗结束，停止点击战斗状态
                status_clicked = False
                continue
            # 联动活动可能有舰船掉落弹窗
            if self.handle_get_ship():
                continue
            if self.handle_battle_status():
                status_clicked = True
                click_last.reset()
                continue
            if self.handle_exp_info():
                continue
            if veritas_ex and result_timer.reached():
                result_timer.reset()
                if self.handle_veritas_ex_result():
                    status_clicked = False
                    continue
            # 持续点击 BATTLE_STATUS 以快速跳过结算动画
            if status_clicked:
                if click_timer.reached() and not click_last.reached():
                    self.device.click(BATTLE_STATUS)
                    click_timer.reset()

    def auto_search_combat_end(self):
        """检测自律战斗是否到达结算阶段。

        Returns:
            bool: 出现战斗状态结算界面时返回 True。
        """
        if self.handle_battle_status():
            return False
        if self.appear(BATTLE_STATUS, offset=(80, 20)):
            return True

    def coalition_combat(self):
        """执行联合出击的多轮自律战斗循环。

        Pages:
            in: is_coalition
            out: is_coalition
        """
        self.battle_count = 0
        self.combat_preparation(emotion_reduce=False)

        try:
            while 1:
                logger.hr(f'{self.FUNCTION_NAME_BASE}{self.battle_count}', level=2)
                self.auto_search_combat_execute(
                    emotion_reduce=self.coalition_emotion_reduce() and self.emotion.is_calculate,
                    shipwreck_reduce=self.emotion.is_calculate,
                    fleet_index=1,
                    expected_end=self.auto_search_combat_end
                )
                self.coalition_combat_re_enter()
                self.battle_count += 1
        except CampaignEnd:
            logger.info('[联动-战斗] 联动战斗结束')
