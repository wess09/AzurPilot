import numpy as np

import module.config.server as server
from module.base.utils import get_color
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.daily.assets import *
from module.daily.equipment import DailyEquipment
from module.logger import logger
from module.ocr.ocr import Digit
from module.ui.assets import BACK_ARROW, DAILY_CHECK
from module.ui.page import page_campaign_menu, page_daily

DAILY_MISSION_LIST = [DAILY_MISSION_1, DAILY_MISSION_2, DAILY_MISSION_3]
if server.server != 'jp':
    OCR_REMAIN = Digit(OCR_REMAIN, threshold=128, alphabet='01234')
else:
    OCR_REMAIN = Digit(OCR_REMAIN, letter=(222, 223, 222), threshold=128, alphabet='01234')
OCR_DAILY_FLEET_INDEX = Digit(OCR_DAILY_FLEET_INDEX, letter=(90, 154, 255), threshold=128, alphabet='123456')


class Daily(Combat, DailyEquipment):
    daily_current: int
    daily_checked: list
    emergency_module_development = False

    def is_active(self):
        color = get_color(image=self.device.image, area=DAILY_ACTIVE.area)
        color = np.array(color).astype(float)
        color = (np.max(color) + np.min(color)) / 2
        active = color > 30
        if active:
            logger.attr(f'Daily_{self.daily_current}', 'active')
        else:
            logger.attr(f'Daily_{self.daily_current}', 'inactive')
        return active

    def _wait_daily_switch(self):
        self.device.sleep((1, 1.2))

    def next(self):
        self.daily_current += 1
        logger.info('Switch to %s' % str(self.daily_current))
        self.device.click(DAILY_NEXT)
        self._wait_daily_switch()
        self.device.screenshot()

    def prev(self):
        self.daily_current -= 1
        logger.info('Switch to %s' % str(self.daily_current))
        self.device.click(DAILY_PREV)
        self._wait_daily_switch()
        self.device.screenshot()

    def handle_daily_additional(self):
        if self.handle_guild_popup_cancel():
            return True
        return False

    def get_daily_stage_and_fleet(self):
        """
        获取每日任务的关卡和舰队配置。

        Returns:
            int: 关卡索引，0 到 3。
            int: 舰队索引，1 到 6。
        """
        if self.emergency_module_development:
            # daily_current 含义
            # 1 限时兵装训练 Emergency Module Development
            # 2 商船护送 Escort Mission
            # 3 海域突进 Advance Mission
            # 4 斩首行动 Fierce Assault
            # 5 战术研修 Tactical Training
            # 6 破交作战 Supply Line Disruption
            # 7 兵装训练 Module Development
            fleets = [
                0,
                self.config.Daily_EmergencyModuleDevelopmentFleet,
                self.config.Daily_EscortMissionFleet,
                self.config.Daily_AdvanceMissionFleet,
                self.config.Daily_FierceAssaultFleet,
                self.config.Daily_TacticalTrainingFleet,
                0,  # 破交作战，需要手动完成或通过每日跳过
                self.config.Daily_ModuleDevelopmentFleet,
                0
            ]
            stages = [
                0,
                self.config.Daily_EmergencyModuleDevelopment,
                self.config.Daily_EscortMission,
                self.config.Daily_AdvanceMission,
                self.config.Daily_FierceAssault,
                self.config.Daily_TacticalTraining,
                self.config.Daily_SupplyLineDisruption,
                self.config.Daily_ModuleDevelopment,
                0
            ]
        else:
            # daily_current 含义
            # 1 战术研修 Tactical Training
            # 2 破交作战 Supply Line Disruption
            # 3 兵装训练 Module Development
            # 4 (未开放)
            # 5 商船护送 Escort Mission
            # 6 海域突进 Advance Mission
            # 7 斩首行动 Fierce Assault
            fleets = [
                0,
                self.config.Daily_TacticalTrainingFleet,
                0,  # 破交作战，需要手动完成或通过每日跳过
                self.config.Daily_ModuleDevelopmentFleet,
                0,  # 空
                self.config.Daily_EscortMissionFleet,
                self.config.Daily_AdvanceMissionFleet,
                self.config.Daily_FierceAssaultFleet,
                0
            ]
            stages = [
                0,
                self.config.Daily_TacticalTraining,
                self.config.Daily_SupplyLineDisruption,
                self.config.Daily_ModuleDevelopment,
                0,  # 空
                self.config.Daily_EscortMission,
                self.config.Daily_AdvanceMission,
                self.config.Daily_FierceAssault,
                0
            ]
        dic = {
            'skip': 0,
            'first': 1,
            'second': 2,
            'third': 3,
        }
        fleet = fleets[self.daily_current]
        stage = stages[self.daily_current]

        if stage not in dic:
            logger.warning(f'Unknown daily stage `{stage}` from daily_current={self.daily_current}')
        stage = dic.get(stage, 0)
        return int(stage), int(fleet)

    @property
    def supply_line_disruption_index(self):
        if self.emergency_module_development:
            return 2
        else:
            return 2

    @property
    def empty_index(self):
        if self.emergency_module_development:
            return 4
        else:
            return 4

    def daily_execute(self, remain=3, stage=1, fleet=1):
        """
        执行每日任务。

        Args:
            remain (int): 剩余每日挑战次数。
            stage (int): 从上到下的关卡索引，1 到 3。
            fleet (int): 使用的舰队索引。

        Returns:
            bool: 成功返回 True，每日任务锁定返回 False。

        Pages:
            in: page_daily
            out: page_daily
        """
        logger.hr(f'Daily {self.daily_current}', level=2)
        logger.info(f'remain={remain}, stage={stage}, fleet={fleet}')

        def daily_enter_check():
            return self.appear(DAILY_ENTER_CHECK, threshold=30)

        def daily_end():
            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                self.device.click(BACK_ARROW)
            return self.appear(DAILY_ENTER_CHECK, threshold=30) or self.appear(BACK_ARROW, offset=(30, 30))

        self.ui_click(click_button=DAILY_ENTER, check_button=daily_enter_check, appear_button=DAILY_CHECK,
                      skip_first_screenshot=True)
        if self.appear(DAILY_LOCKED):
            logger.info('Daily locked')
            self.ui_click(click_button=BACK_ARROW, check_button=DAILY_CHECK)
            self.device.sleep((1, 1.2))
            return False

        button = DAILY_MISSION_LIST[stage - 1]
        for n in range(remain):
            logger.hr(f'Count {n + 1}')
            result = self.daily_enter(button)
            if not result:
                break
            if self.daily_current == self.supply_line_disruption_index:
                logger.info('Submarine daily skip not unlocked, skip')
                self.ui_click(click_button=BACK_ARROW, check_button=daily_enter_check, skip_first_screenshot=True)
                break
            # 执行经典每日任务
            self.ui_ensure_index(fleet, letter=OCR_DAILY_FLEET_INDEX, prev_button=DAILY_FLEET_PREV,
                                 next_button=DAILY_FLEET_NEXT, fast=False, skip_first_screenshot=True)
            self.combat(emotion_reduce=False, save_get_items=False, expected_end=daily_end, balance_hp=False)

        self.ui_click(click_button=BACK_ARROW, check_button=DAILY_CHECK, additional=self.handle_daily_additional,
                      skip_first_screenshot=True)
        self.device.sleep((1, 1.2))
        return True

    def daily_enter(self, button, skip_first_screenshot=True):
        """
        进入每日任务。

        Args:
            button (Button): 每日任务入口按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 战斗画面出现返回 True，每日跳过已解锁/已跳过/已领取奖励返回 False。

        Pages:
            in: DAILY_ENTER_CHECK
            out: DAILY_ENTER_CHECK 或 combat_appear
        """
        reward_received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DAILY_ENTER_CHECK, threshold=30, interval=5):
                self.device.click(button)
                continue
            if self.handle_get_items():
                reward_received = True
                continue
            if self.config.Daily_UseDailySkip:
                if self.appear_then_click(DAILY_SKIP, offset=(20, 20), interval=5):
                    continue
            else:
                if self.appear_then_click(DAILY_NORMAL_RUN, offset=(20, 20), interval=5):
                    continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_daily_additional():
                continue
            if self.handle_popup_confirm('DAILY_SKIP'):
                continue

            # 结束
            if self.appear(DAILY_SKIP, offset=(20, 20)):
                if reward_received:
                    return False
                if self.info_bar_count():
                    return False
            if self.appear(DAILY_ENTER_CHECK, threshold=30):
                if self.info_bar_count():
                    return False
            if self.combat_appear():
                return True

    def daily_check(self, n=None):
        if not n:
            n = self.daily_current
        self.daily_checked.append(n)
        logger.info(f'Checked daily {n}')
        logger.info(f'Checked_list: {self.daily_checked}')

    def daily_run_one(self):
        logger.hr('Daily run one', level=1)
        self.ui_ensure(page_daily)
        self.device.sleep(0.2)
        self.device.screenshot()
        self.daily_current = 1
        self.emergency_module_development = self.appear(ENTRANCE_EMERGENCY_MODULE_DEVELOPMENT, offset=(25, 50))
        logger.attr('emergency_module_development', self.emergency_module_development)

        logger.info(f'Checked_list: {self.daily_checked}')
        for _ in range(max(self.daily_checked)):
            self.next()

        while 1:
            if self.daily_current > 7:
                break
            if self.daily_current == self.empty_index:
                logger.info('This daily is not open now')
                self.daily_check()
                self.next()
                continue
            stage, fleet = self.get_daily_stage_and_fleet()
            if self.daily_current == self.supply_line_disruption_index and not self.config.Daily_UseDailySkip:
                logger.info('Skip supply line disruption if UseDailySkip disabled')
                self.daily_check()
                self.next()
                continue
            if not stage:
                logger.info(f'No stage set on daily_current: {self.daily_current}, skip')
                self.daily_check()
                self.next()
                continue
            if self.daily_current != self.supply_line_disruption_index and not fleet:
                logger.info(f'No fleet set on daily_current: {self.daily_current}, skip')
                self.daily_check()
                self.next()
                continue
            if not self.is_active():
                self.daily_check()
                self.next()
                continue
            remain = OCR_REMAIN.ocr(self.device.image)
            if remain == 0:
                self.daily_check()
                self.next()
                continue
            else:
                self.daily_execute(remain=remain, stage=stage, fleet=fleet)
                self.daily_check()
                # 打完一次之后每日任务的顺序会乱掉, 退出再进入来重置顺序.
                self.ui_goto(page_campaign_menu)
                break

    def daily_run(self):
        self.daily_checked = [0]

        while 1:
            self.daily_run_one()

            if self.emergency_module_development and self.config.Daily_EmergencyModuleDevelopment != 'skip':
                self.daily_checked = [0]

            if max(self.daily_checked) >= 7:
                logger.info('Daily clear complete.')
                break

    def run(self):
        """
        运行每日任务。

        Pages:
            in: 任意页面
            out: page_daily
        """
        # self.equipment_take_on()
        self.daily_run()
        # self.equipment_take_off()

        # 不能停留在 page_daily，因为顺序会乱掉。
        self.config.task_delay(server_update=True)
