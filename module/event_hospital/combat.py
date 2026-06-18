from module.base.decorator import run_once
from module.base.timer import Timer
from module.campaign.campaign_event import CampaignEvent
from module.combat.combat import BATTLE_PREPARATION, Combat
from module.event_hospital.assets import HOSPITAL_BATTLE_PREPARE
from module.event_hospital.ui import HospitalUI
from module.exception import OilExhausted, RequestHumanTakeover
from module.logger import logger
from module.map.assets import *
from module.map.map_fleet_preparation import FleetOperator
from module.raid.assets import RAID_FLEET_PREPARATION


class HospitalCombat(Combat, HospitalUI, CampaignEvent):
    """医院活动战斗处理器，组合战斗、UI 和活动逻辑。"""

    def handle_fleet_recommend(self, recommend=True):
        """处理舰队推荐。

        检查舰队是否已在使用中，若未使用则根据配置决定
        是否自动推荐舰队或要求手动编队。

        Args:
            recommend: 是否启用自动推荐舰队。

        Returns:
            bool: 是否点击了推荐按钮。

        Raises:
            RequestHumanTakeover: 舰队未准备且未启用推荐时抛出。
        """
        fleet_1 = FleetOperator(
            choose=FLEET_1_CHOOSE, advice=FLEET_1_ADVICE, bar=FLEET_1_BAR, clear=FLEET_1_CLEAR,
            in_use=FLEET_1_IN_USE, hard_satisfied=FLEET_1_HARD_SATIESFIED, main=self)
        if fleet_1.in_use():
            return False

        if recommend:
            logger.info('Recommend fleet')
            fleet_1.recommend()
            return True
        else:
            logger.error('Fleet not prepared and fleet recommend is not enabled, '
                         'please prepare fleets manually before running')
            raise RequestHumanTakeover

    def combat_preparation(self, balance_hp=False, emotion_reduce=False, auto='combat_auto', fleet_index=1):
        """战斗准备阶段，处理舰队编成和出击确认。

        Args:
            balance_hp: 是否平衡血量。
            emotion_reduce: 是否减少情绪值。
            auto: 自动战斗模式。
            fleet_index: 舰队索引。
        """
        logger.info('Combat preparation.')
        skip_first_screenshot = True

        @run_once
        def check_oil():
            if self.get_oil() < max(500, self.config.StopCondition_OilLimit):
                logger.hr('Triggered oil limit')
                raise OilExhausted

        @run_once
        def check_coin():
            if self.coin_limit_triggered():
                logger.hr('Triggered stop condition: Coin limit')
                self.config.task_stop()
                return True
            if self.config.TaskBalancer_Enable and self.triggered_task_balancer():
                logger.hr('Triggered stop condition: Coin limit')
                self.handle_task_balancer()
                return True

        for _ in self.loop():

            if self.appear(BATTLE_PREPARATION, offset=(30, 20)):
                if self.handle_combat_automation_set(auto=auto == 'combat_auto'):
                    continue
                check_oil()
                check_coin()
            if self.handle_retirement():
                continue
            if self.handle_combat_low_emotion():
                continue
            if self.appear_then_click(BATTLE_PREPARATION, offset=(30, 20), interval=2):
                continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue
            # 处理舰队编成
            if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=2):
                if self.handle_fleet_recommend(recommend=self.config.Hospital_UseRecommendFleet):
                    self.interval_clear(RAID_FLEET_PREPARATION)
                    continue
                self.device.click(RAID_FLEET_PREPARATION)
                continue
            if self.appear_then_click(HOSPITAL_BATTLE_PREPARE, offset=(20, 20), interval=2):
                continue

            # 战斗开始
            pause = self.is_combat_executing()
            if pause:
                logger.attr('BattleUI', pause)
                if emotion_reduce:
                    self.emotion.reduce(fleet_index)
                break

    in_clue_confirm = Timer(0.5, count=2)

    def hospital_expected_end(self):
        """判断医院战斗是否结束。

        连续两次检测到线索界面时判定战斗结束。

        Returns:
            bool: 战斗是否已结束。
        """
        if self.handle_clue_exit():
            return False
        if self.is_in_clue():
            self.in_clue_confirm.start()
            if self.in_clue_confirm.reached():
                return True
        else:
            self.in_clue_confirm.reset()
        return False

    def hospital_combat(self):
        """执行医院活动战斗流程。

        Pages:
            in: FLEET_PREPARATION
            out: is_in_clue
        """
        self.combat(balance_hp=False, expected_end=self.hospital_expected_end)
