"""指挥喵猫窝处理器，执行猫窝中的日常互动获取经验值。
包括完成日常任务和收起已放置的指挥喵。
"""

from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.logger import logger
from module.meowfficer.assets import *
from module.meowfficer.base import MeowfficerBase


class MeowfficerFort(MeowfficerBase):
    """指挥喵猫窝处理器。

    执行猫窝中的日常互动任务以获取经验值和奖励。
    """

    def meow_chores(self, skip_first_screenshot=True):
        """循环执行猫窝日常打扫与互动以获取经验值。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: MEOWFFICER_FORT
            out: MEOWFFICER_FORT
        """
        self.interval_clear(GET_ITEMS_1)
        check_timer = Timer(1, count=2)
        confirm_timer = Timer(1.5, count=4).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 意外退出猫窝时重新进入
            if self.appear_then_click(MEOWFFICER_FORT_ENTER, offset=(20, 20), interval=3):
                check_timer.reset()
                confirm_timer.reset()
                continue

            if self.appear(MEOWFFICER_FORT_GET_XP_1) or \
                    self.appear(MEOWFFICER_FORT_GET_XP_2):
                check_timer.reset()
                confirm_timer.reset()
                continue

            if self.appear(GET_ITEMS_1, offset=5, interval=3):
                self.device.click(MEOWFFICER_FORT_CHECK)
                check_timer.reset()
                confirm_timer.reset()
                continue

            if check_timer.reached():
                is_chore = self.image_color_count(
                    MEOWFFICER_FORT_CHORE, color=(247, 186, 90),
                    threshold=20, count=50)
                check_timer.reset()
                if is_chore:
                    self.device.click(MEOWFFICER_FORT_CHORE)
                    confirm_timer.reset()
                    continue

            # 判定结束
            if self.appear(MEOWFFICER_FORT_CHECK, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def meow_fort(self):
        """检查并执行指挥喵猫窝日常打扫任务。

        检测猫窝红点，若有红点则进入猫窝执行日常打扫互动并返回。

        Returns:
            bool: 成功执行了打扫返回 True，无红点跳过返回 False。

        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        # 检查猫窝红点提示
        if not self.appear(MEOWFFICER_FORT_RED_DOT):
            return False
        logger.hr('指挥喵-猫窝', level=1)

        # 进入猫窝界面
        self.meow_enter(MEOWFFICER_FORT_ENTER, check_button=MEOWFFICER_FORT_CHECK)

        # 执行猫窝互动打扫
        self.meow_chores()

        # 关闭猫窝弹窗返回主界面
        self.meow_menu_close()

        return True
