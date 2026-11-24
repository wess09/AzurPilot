"""困难模式战役执行模块。

自动执行碧蓝航线的困难模式关卡。困难模式与普通模式共享同一张地图，
但使用独立的战役入口和额外的限制条件（如每日出击次数、舰队锁定等）。
通过 OCR 识别剩余出击次数，循环执行直到用尽。

配置路径: Hard.HardStage (关卡选择), Hard.HardFleet (舰队选择), Hard.RunAt18 (18点运行)
"""

import importlib

from campaign.campaign_hard.campaign_hard import Campaign
from module.campaign.run import CampaignRun
from module.config.time_source import now as current_time
from module.config.utils import server_time_offset
from module.handler.fast_forward import to_map_file_name
from module.hard.assets import *
from module.logger import logger
from module.ocr.ocr import Digit
from module.reward.reward import Reward

OCR_HARD_REMAIN = Digit(OCR_HARD_REMAIN, letter=(123, 227, 66), threshold=128, alphabet='0123')


class CampaignHard(CampaignRun):
    """困难模式战役执行器。

    继承自 CampaignRun，负责执行困难模式关卡。从普通模式战役加载地图数据，
    强制启用舰队锁定和自动搜索，通过 OCR 识别每日剩余出击次数并循环执行。

    Attributes:
        equipment_has_take_on: 装备是否已穿戴（当前未使用）。
        campaign: 战役执行实例，由 CampaignRun 提供。
    """

    equipment_has_take_on = False
    campaign: Campaign

    def run(self):
        """执行困难关卡出击主流程。

        流程包括：覆写困难模式配置、加载战役与地图模块、导航至困难关卡界面、
        OCR 识别剩余次数并循环出击，完成后退出自动搜索；18 点运行会先补领任务奖励，
        再按配置延迟到服务器零点或18点。

        Pages:
            in: 任意页面
            out: 延后时保留当前页面；18 点运行补领任务奖励后停在 page_mission；
                否则为 page_campaign 或关卡选择界面
        """
        logger.hr('困难战役', level=1)
        if self.config.Hard_RunAt18 and (current_time() - server_time_offset()).hour < 18:
            self.config.task_delay(server_update='18:00')
            self.config.task_stop()

        name = to_map_file_name(self.config.Hard_HardStage)
        # Hard.HardFleet 指定出击舰队，另一支在基地待命、不参与战斗。
        # Fleet_FleetOrder 与该选择一一对应，编队准备时会据此只校验出击舰队的困难限制
        # （见 module/map/map_fleet_preparation.py），不再强制要求两支舰队都满足困难限制。
        self.config.override(
            Campaign_Mode='hard',
            Campaign_UseFleetLock=True,
            Campaign_UseAutoSearch=True,
            Fleet_FleetOrder='fleet1_all_fleet2_standby' if self.config.Hard_HardFleet == 1 else 'fleet1_standby_fleet2_all',
            Emotion_Mode='nothing',  # 不计算也不忽略
        )
        # 装备穿戴
        # campaign/campaign_hard/campaign_hard.py Campaign.fleet_preparation()

        # 初始化
        self.load_campaign(name='campaign_hard', folder='campaign_hard')  # 加载战役文件
        module = importlib.import_module('.' + name, 'campaign.campaign_main')  # 从普通模式加载地图
        self.campaign.MAP = module.MAP

        # UI 确认
        self.device.screenshot()
        self.campaign.device.image = self.device.image
        self.campaign.ensure_campaign_ui(
            name=self.config.Hard_HardStage,
            mode='hard'
        )

        # 执行
        remain = OCR_HARD_REMAIN.ocr(self.device.image)
        logger.attr('剩余次数', remain)
        for n in range(remain):
            self.campaign.run()

        self.campaign.ensure_auto_search_exit()
        # self.campaign.equipment_take_off_when_finished()

        # 18 点运行时 Reward 任务当天零点已经执行过，困难图打完新增的任务奖励
        # 不会再有人领取，因此在关卡结束后原地补领一次。
        if self.config.Hard_RunAt18:
            self.claim_mission_reward()

        # 调度器
        self.config.task_delay(server_update='18:00' if self.config.Hard_RunAt18 else True)
        self.config.task_call('Reward', force_call=False)

    def claim_mission_reward(self):
        """补领困难图出击产生的任务奖励。

        18 点运行模式下 Reward 任务已在当天零点执行过，困难图打完新增的任务奖励
        不会再被领取，因此在关卡结束后补领一次；领取项跟随 Reward 任务的配置。

        Pages:
            in: 任意页面
            out: page_mission（没有可领取的任务奖励时保持原页面）
        """
        # 跨任务读取 Reward 任务配置，路径为 <Task>.<Group>.<Argument>。
        daily = self.config.cross_get(keys=['Reward', 'Reward', 'CollectMission'], default=True)
        weekly = self.config.cross_get(keys=['Reward', 'Reward', 'CollectWeeklyMission'], default=False)
        if not daily and not weekly:
            logger.info('[困难战役] Reward 任务未开启任务奖励领取，跳过补领')
            return

        logger.hr('任务奖励', level=1)
        self.ui_goto_main()
        Reward(self.config, self.device).reward_mission(daily=daily, weekly=weekly)
