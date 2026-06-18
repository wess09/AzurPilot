from module.base.timer import Timer
from module.handler.assets import MAINTENANCE_ANNOUNCE, USE_DATA_KEY_NOTIFIED
from module.island.assets import *
from module.logger import logger
from module.ui.assets import SHOP_BACK_ARROW
from module.ui.page import page_island_phone
from module.ui.ui import UI


class IslandUI(UI):
    def ui_additional(self, get_ship=True):
        return super().ui_additional(get_ship=False)

    def island_in_management(self, interval=0):
        """
        检测是否在岛屿管理页面。

        Args:
            interval (int): 点击间隔

        Returns:
            bool: 是否在 ISLAND_MANAGEMENT_CHECK 页面
        """
        return self.appear(ISLAND_MANAGEMENT_CHECK, offset=(20, 20), interval=interval)

    #@cached_property
    def _island_season_bottom_navbar(self):
        """
        季节活动底部导航栏，包含 6 个选项：
        主页、PT奖励、赛季任务、赛季商店、赛季排名、赛季历史
        """
        island_season_bottom_navbar = ButtonGrid(
            origin=(14, 677), delta=(213, 0),
            button_shape=(186, 33), grid_shape=(6, 1),
            name='ISLAND_SEASON_BOTTOM_NAVBAR'
        )
        return Navbar(grids=island_season_bottom_navbar,
                      active_color=(237, 237, 237),
                      inactive_color=(65, 78, 96),
                      active_count=500,
                      inactive_count=500)

    def island_season_bottom_navbar_ensure(self, left=None, right=None):
        """
        确保切换到季节活动底部导航栏的指定标签页。

        Args:
            left (int): 从左数的标签页位置
                1=主页, 2=PT奖励, 3=赛季任务, 4=赛季商店, 5=赛季排名, 6=赛季历史
            right (int): 从右数的标签页位置
                1=赛季历史, 2=赛季排名, 3=赛季商店, 4=赛季任务, 5=PT奖励, 6=主页
        """
        return self.appear(ISLAND_MANAGEMENT_CHECK, offset=(20, 20), interval=interval)

    def island_in_transport(self, interval=0):
        """
        检测是否在岛屿运输页面。

        Args:
            interval (int): 点击间隔

        Returns:
            bool: 是否在 ISLAND_TRANSPORT_CHECK 页面
        """
        return self.match_template_color(ISLAND_TRANSPORT_CHECK, offset=(20, 20), interval=interval)

    def island_management_enter(self):
        """
        进入岛屿管理页面。

        Returns:
            bool: 是否成功进入

        Pages:
            in: page_island_phone
            out: ISLAND_MANAGEMENT_CHECK
        """
        logger.info('Island management enter')
        self.interval_clear(ISLAND_MANAGEMENT_CHECK)
        if self.appear(ISLAND_MANAGEMENT_LOCKED, offset=(20, 20)):
            return False
        self.ui_click(
            click_button=ISLAND_MANAGEMENT,
            check_button=self.island_in_management,
            offset=(20, 20),
            retry_wait=2,
            skip_first_screenshot=True
        )
        return True

    def island_transport_enter(self):
        """
        进入岛屿运输页面。

        Returns:
            bool: 是否成功进入

        Pages:
            in: page_island_phone
            out: ISLAND_TRANSPORT_CHECK
        """
        logger.info('Island transport enter')
        self.ui_click(
            click_button=ISLAND_TRANSPORT,
            check_button=self.island_in_transport,
            offset=(20, 20),
            retry_wait=2,
            skip_first_screenshot=True
        )
        return True

    def island_ui_back(self):
        """
        从岛屿子页面返回到岛屿手机页面。

        Pages:
            in: 任意带有 SHOP_BACK_ARROW 的页面
            out: page_island_phone
        """
        logger.info('Island UI back')
        self.ui_click(
            click_button=SHOP_BACK_ARROW,
            check_button=page_island_phone.check_button,
            offset=(20, 20),
            retry_wait=2,
            skip_first_screenshot=True
        )

    def ui_ensure_management_page(self):
        """
        确保当前在岛屿管理页面，如果不在则导航过去。

        Pages:
            in: page_island_phone 或产品页面
            out: ISLAND_MANAGEMENT_CHECK
        """
        logger.info('UI ensure management page')
        self.interval_clear(ISLAND_MANAGEMENT_CHECK)
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.island_in_management():
                if confirm_timer.reached():
                    break
                continue
            else:
                confirm_timer.reset()

            if self.appear_then_click(SHOP_BACK_ARROW, offset=(20, 20), interval=2):
                continue

            if self.appear_then_click(ISLAND_MANAGEMENT, offset=(20, 20), interval=2):
                continue

    def handle_get_items(self):
        if self.appear_then_click(GET_ITEMS_ISLAND, offset=(20, 20), interval=2):
            return True
        return False

    def ui_additional(self, get_ship=True):
        # 处理宿舍菜单页面的通知弹窗
        if self.appear(MAINTENANCE_ANNOUNCE, offset=(100, 50)):
            for _ in self.loop():
                enabled = self.image_color_count(
                    USE_DATA_KEY_NOTIFIED, color=(140, 207, 66), threshold=180, count=10)
                if enabled:
                    break

                if self.appear(MAINTENANCE_ANNOUNCE, offset=(100, 50), interval=5):
                    self.device.click(USE_DATA_KEY_NOTIFIED)
                    continue

            self.interval_clear(MAINTENANCE_ANNOUNCE)
            self.appear_then_click(MAINTENANCE_ANNOUNCE, offset=(100, 50), interval=2)
            return True
        
        # 处理岛屿页面的信息弹窗
        if self.appear_then_click(ISLAND_INFO_EXIT, offset=(30, 30), interval=3):
            return True

        return super().ui_additional(get_ship=False)
