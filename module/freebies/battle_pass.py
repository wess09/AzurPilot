from module.base.timer import Timer
from module.base.utils import get_color
from module.combat.combat import Combat
from module.freebies.assets import *
from module.logger import logger
from module.ui.assets import BATTLE_PASS_CHECK, REWARD_GOTO_BATTLE_PASS
from module.ui.page import page_reward
from module.ui.ui import UI
from module.ui_white.assets import POPUP_CONFIRM_WHITE_BATTLEPASS


class BattlePass(Combat, UI):
    def battle_pass_red_dot_appear(self):
        """
        检测战斗通行证红点是否出现。

        Returns:
            bool: 红点是否出现。

        Pages:
            in: page_reward
        """
        if self.appear(REWARD_GOTO_BATTLE_PASS, offset=(50, 150)):
            # 从 REWARD_GOTO_BATTLE_PASS 加载按钮偏移，因为入口可能不在最上方。
            BATTLE_PASS_RED_DOT.load_offset(REWARD_GOTO_BATTLE_PASS)
            # 此处不使用 self.appear()，因为红点是透明的，颜色会随背景变化。
            r, _, _ = get_color(self.device.image, BATTLE_PASS_RED_DOT.button)
            if r > BATTLE_PASS_RED_DOT.color[0] - 40:
                logger.info('Found battle pass red dot')
                return True
            else:
                logger.info('No battle pass red dot')
                return False
        else:
            logger.warning('No battle pass entrance')
            return False

    def handle_battle_pass_popup(self):
        return self.appear_then_click(PURCHASE_POPUP, offset=(20, 20), interval=2)

    def battle_pass_enter(self):
        """
        进入战斗通行证页面。

        Pages:
            in: page_reward
            out: page_battle_pass
        """

        def appear_button():
            return self.appear(REWARD_GOTO_BATTLE_PASS, offset=(50, 150))

        self.ui_click(REWARD_GOTO_BATTLE_PASS, appear_button=appear_button, check_button=BATTLE_PASS_CHECK,
                      additional=self.handle_battle_pass_popup, skip_first_screenshot=True)

    def battle_pass_receive(self, skip_first_screenshot=True):
        """
        领取战斗通行证奖励。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否领取了奖励。

        Pages:
            in: page_battle_pass
            out: page_battle_pass
        """
        logger.hr('Battle pass receive', level=1)
        self.battle_status_click_interval = 2
        confirm_timer = Timer(1, count=3).start()
        received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(REWARD_RECEIVE, offset=(20, 20), interval=3):
                confirm_timer.reset()
                continue
            if self.match_template_color(REWARD_RECEIVE_SP, offset=(20, 20), interval=3, threshold=15):
                self.device.click(REWARD_RECEIVE_SP)
                confirm_timer.reset()
                continue
            if self.appear_then_click(REWARD_RECEIVE_WHITE, offset=(20, 20), interval=3):
                confirm_timer.reset()
                continue
            if self.handle_battle_pass_popup():
                confirm_timer.reset()
                continue
            if self.config.SERVER in ['cn', 'jp', 'en']:
                if self.appear_then_click(POPUP_CONFIRM_WHITE_BATTLEPASS, offset=(20, 20), interval=3):
                    confirm_timer.reset()
                    continue
            if self.handle_popup_confirm('BATTLE_PASS'):
                # 锁定新 META 舰船
                confirm_timer.reset()
                continue
            if self.handle_get_items():
                received = True
                confirm_timer.reset()
                continue
            if self.handle_get_ship():
                received = True
                confirm_timer.reset()
                continue
            if self.handle_get_skin():
                received = True
                confirm_timer.reset()
                continue

            # 结束
            if self.appear(BATTLE_PASS_CHECK, offset=(20, 20)) \
                    and not self.appear(REWARD_RECEIVE, offset=(20, 20)) \
                    and not self.appear(REWARD_RECEIVE_WHITE, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        logger.info(f'Battle pass receive finished, received={received}')
        return received

    def run(self):
        self.ui_ensure(page_reward)

        if self.battle_pass_red_dot_appear():
            self.battle_pass_enter()
            self.battle_pass_receive()
