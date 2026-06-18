import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import area_offset, color_similarity_2d
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3
from module.guild.assets import *
from module.guild.base import GuildBase
from module.logger import logger
from module.map_detection.utils import Points
from module.ui.assets import GUILD_CHECK


class GuildLobby(GuildBase):
    def guild_lobby_get_report(self):
        """
        获取大舰队报告入口按钮。

        Returns:
            Button: 进入大舰队报告的按钮，如果不存在则返回 None。
        """
        # 在 GUILD_REPORT_AVAILABLE 区域内查找红色
        image = color_similarity_2d(self.image_crop(GUILD_REPORT_AVAILABLE, copy=False), color=(255, 8, 8))
        points = np.array(np.where(image > 221)).T[:, ::-1]
        if len(points):
            # 红点的中心位置
            points = Points(points).group(threshold=40) + GUILD_REPORT_AVAILABLE.area[:2]
            # 偏移到报告图标的中心
            area = area_offset((-51, -45, -13, 0), offset=points[0])
            return Button(area=area, color=(255, 255, 255), button=area, name='GUILD_REPORT')
        else:
            return None

    def _guild_lobby_collect(self, skip_first_screenshot=True):
        """
        收集大舰队大厅中的报告奖励。

        如果报告奖励存在则执行收取操作。如果已在 page_guild 但不在大厅界面，
        将超时并在下次运行时收取。这些奖励会排队等待，无需立即收取。

        Pages:
            in: 任意页面
            out: 任意页面
        """
        confirm_timer = Timer(1.5, count=3).start()
        click_timer = Timer(3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if click_timer.reached() and self.appear(GUILD_CHECK, offset=(20, 20)):
                button = self.guild_lobby_get_report()
                if button is not None:
                    self.device.click(button)
                    click_timer.reset()

            if self.appear_then_click(GUILD_REPORT_CLAIM, threshold=30, interval=3):
                confirm_timer.reset()
                continue

            if self.appear_then_click(GET_ITEMS_1, offset=(30, 30), interval=2):
                confirm_timer.reset()
                continue

            if self.appear_then_click(GET_ITEMS_2, offset=(30, 30), interval=2):
                confirm_timer.reset()
                continue

            if self.appear_then_click(GET_ITEMS_3, offset=(30, 30), interval=2):
                confirm_timer.reset()
                continue

            if self.appear(GUILD_REPORT_CLAIMED, threshold=30, interval=3):
                self.device.click(GUILD_REPORT_CLOSE)
                confirm_timer.reset()
                continue

            # 结束
            if self.appear(GUILD_CHECK, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def guild_lobby(self):
        """
        执行大舰队大厅中的所有操作。

        Pages:
            in: GUILD_LOBBY
            out: GUILD_LOBBY
        """
        logger.hr('Guild lobby', level=1)
        self._guild_lobby_collect()
        logger.info('Guild lobby collect finished')
