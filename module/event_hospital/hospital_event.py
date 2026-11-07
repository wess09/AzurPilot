"""医院活动事件主控模块。

医院活动的顶层任务处理器，管理活动入口导航、难度选择、
关卡进入和战斗编排。继承 Hospital 和 RaidRun，复用
突袭任务的运行框架来驱动医院活动的完整执行流程。
"""

from module.campaign.campaign_ui import ModeSwitch
from module.combat.assets import BATTLE_PREPARATION
from module.event_hospital.assets import *
from module.event_hospital.hospital import Hospital
from module.exception import OilExhausted, ScriptEnd, ScriptError
from module.logger import logger
from module.minigame.assets import BACK
from module.raid.assets import RAID_FLEET_PREPARATION
from module.raid.raid import raid_entrance
from module.raid.run import RaidRun
from module.ui.page import page_hospital

ASIDE_SWITCH_HOSPITAL = ModeSwitch('Aside_switch_hospital', is_selector=True)
ASIDE_SWITCH_HOSPITAL.add_state('easy', CHAPTER_HOSPITAL_EASY)
ASIDE_SWITCH_HOSPITAL.add_state('normal', CHAPTER_HOSPITAL_NORMAL)
ASIDE_SWITCH_HOSPITAL.add_state('hard', CHAPTER_HOSPITAL_HARD)


class HospitalEvent(Hospital, RaidRun):
    """医院活动突袭模式事件处理器。

    继承 Hospital 与 RaidRun，通过突袭模式机制驱动医院活动关卡的批量出击。

    Attributes:
        raid_name (str): 突袭活动标识名。
    """

    raid_name = 'raid_20250327'

    def campaign_ensure_aside_hospital(self, chapter):
        """确保医院活动难度标签正确设置。

        Args:
            chapter (str): 难度，'easy'、'normal' 或 'hard'。
        """
        if chapter in ['easy', 'normal', 'hard']:
            ASIDE_SWITCH_HOSPITAL.set(chapter, main=self)
        else:
            logger.warning(f'未知的医院活动难度: {chapter}')

    def hospital_expected_end(self):
        """判断医院活动战斗是否结束（突袭模式）。

        检测到医院主页时判定结束，处理各种返回按钮。

        Returns:
            bool: 战斗是否已结束。
        """
        if self.ui_page_appear(page_hospital, interval=2):
            return True
        if self.appear_then_click(HOSPITAL_BATTLE_EXIT, offset=(20, 20), interval=2):
            return False
        if self.appear(BATTLE_PREPARATION, offset=(30, 20), interval=2):
            logger.info(f'{BATTLE_PREPARATION} -> {BACK}')
            self.device.click(BACK)
            return False
        if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=2):
            logger.info(f'{RAID_FLEET_PREPARATION} -> {BACK}')
            self.device.click(BACK)
            return False
        if self.handle_get_clue():
            return False
        return False

    def raid_enter(self, stage, raid, skip_first_screenshot=True):
        """进入突袭关卡。

        点击入口进入舰队准备界面，同时检查 PT 限制。

        Args:
            stage (str): 关卡编号，如 'T1'、'T2'。
            raid (str): 突袭活动标识。
            skip_first_screenshot (bool): 是否跳过首次截图复用上一状态，默认 True。

        Pages:
            in: page_raid
            out: BATTLE_PREPARATION
        """
        entrance = raid_entrance(raid=raid, mode=stage)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 到达舰队准备界面
            if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30)):
                break

            if self.ui_page_appear(page_hospital):
                # 入口出现时检查 PT 限制
                if self.event_pt_limit_triggered():
                    self.config.task_stop()
                self.device.click(entrance)
                continue

            if self.appear_then_click(HOSPITAL_BATTLE_PREPARE, offset=(20, 20), interval=2):
                continue

            if self.handle_get_clue():
                continue

    def raid_execute_once(self, mode, raid, stage):
        """执行单次突袭战斗。

        Args:
            mode (str): 难度模式。
            raid (str): 突袭活动标识。
            stage (str): 关卡编号。

        Pages:
            in: page_raid
            out: page_raid
        """
        logger.hr('突袭执行')
        self.config.override(
            Campaign_Event=raid,
            Campaign_Name=f'{raid}_{mode}_{stage}',
            Campaign_UseAutoSearch=False,
            Fleet_FleetOrder='fleet1_all_fleet2_standby',
            Hospital_UseRecommendFleet=False,
        )

        self.emotion.check_reduce(1)

        self.raid_enter(stage=stage, raid=raid)
        self.hospital_combat()

        logger.hr('突袭结束')

    def run(self, name='', mode='', stage='', total=0):
        """医院活动突袭主运行入口。

        Args:
            name (str): 突袭名称，如 'raid_20250327'。
            mode (str): 难度模式，如 'hard'、'normal'、'easy'。
            stage (str): 关卡编号，如 'T1'、'T2'。
            total (int): 总运行次数限制，0 为不限。

        Raises:
            ScriptError: 参数未填全时抛出。
        """
        name = name if name else self.raid_name
        mode = mode if mode else self.config.HospitalEvent_Mode
        stage = stage if stage else self.config.HospitalEvent_Stage
        if not name or not mode or not stage:
            raise ScriptError(f'RaidRun arguments unfilled. name={name}, mode={mode}, stage={stage}')

        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount
        while 1:
            # 达到总次数限制
            if total and self.run_count == total:
                break
            if self.event_time_limit_triggered():
                self.config.task_stop()

            # 日志
            logger.hr(f'{name}_{mode}_{stage}', level=2)
            if self.config.StopCondition_RunCount > 0:
                logger.info(f'剩余次数: {self.config.StopCondition_RunCount}')
            else:
                logger.info(f'次数: {self.run_count}')

            # 停止条件检查
            if self.triggered_stop_condition():
                break

            # 确保 UI 状态
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            self.ui_ensure(page_hospital)

            # 执行突袭
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            try:
                self.campaign_ensure_aside_hospital(chapter=mode)
                self.raid_execute_once(mode=mode, raid=name, stage=stage)
            except OilExhausted:
                logger.hr('触发停止条件: 石油上限')
                self.config.task_delay(minute=(120, 240))
                break
            except ScriptEnd as e:
                logger.hr('脚本结束')
                logger.info(str(e))
                break

            # 运行后处理
            self.run_count += 1
            if self.config.StopCondition_RunCount:
                self.config.StopCondition_RunCount -= 1
            # 停止条件检查
            if self.triggered_stop_condition():
                break
            # 调度器检查
            if self.config.task_switched():
                self.config.task_stop()
