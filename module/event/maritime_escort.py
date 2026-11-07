"""海上护卫活动执行模块。

实现海上护卫活动的自动化执行。进入关卡后立即撤退，
以较低消耗获取约 70% 的最大奖励。使用 OCR 识别剩余
挑战次数，每日自动执行直至次数耗尽。
"""

from module.campaign.campaign_event import CampaignEvent
from module.event.assets import *
from module.exception import CampaignEnd
from module.logger import logger
from module.map.map_operation import MapOperation
from module.ocr.ocr import DigitCounter

OCR_REMAIN = DigitCounter(ESCORT_REMAIN, letter=(148, 255, 99), threshold=64)


class MaritimeEscort(MapOperation, CampaignEvent):
    """海上护卫活动的执行器。

    通过进入地图后立即撤退的方式获取约 70% 的最大奖励。
    使用 OCR 识别剩余次数，每日自动执行。

    Pages:
        in: page_main
        out: page_main
    """

    def is_in_escort(self):
        """检测当前是否在海上护卫关卡画面中。"""
        return self.appear(ESCORT_CHECK, offset=(20, 20))

    def handle_in_stage(self):
        """处理关卡内状态，通过计时器避免重复检测。

        Returns:
            bool: 确认在关卡内且计时器已到返回 True，否则返回 False。
        """
        if self.is_in_escort():
            if self.in_stage_timer.reached():
                return True
            else:
                return False
        else:
            self.in_stage_timer.reset()
            return False

    def run_escort(self):
        """进入海上护卫关卡后立即撤退，获取约 70% 的最大奖励。

        Pages:
            in: ESCORT_CHECK
            out: ESCORT_CHECK
        """
        logger.hr('商路护航', level=1)
        try:
            self.enter_map(ESCORT_HARD_ENTRANCE, mode='escort')
            self.withdraw()
        except CampaignEnd:
            pass

        logger.info('[活动-护航] 商路护航完成')

    def run(self):
        """执行海上护卫主流程。

        流程：检查活动时间限制 → 导航到主页面 → 点击进入护卫界面 →
        OCR 识别剩余次数 → 有剩余则执行护卫 → 延迟到次日。
        """
        if self.event_time_limit_triggered():
            self.config.task_stop()

        # 从主页面导航到海上护卫界面
        self.ui_goto_main()
        self.ui_click(MAIN_GOTO_ESCORT, check_button=ESCORT_CHECK, offset=(20, 150), skip_first_screenshot=True)

        # OCR 识别剩余可执行次数
        current, _, _ = OCR_REMAIN.ocr(self.device.image)
        if current > 0:
            self.run_escort()
        else:
            logger.info('[活动-护航] 商路护航今日已完成')

        self.config.task_delay(server_update=True)
