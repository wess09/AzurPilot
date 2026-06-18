import numpy as np

from module.base.button import ButtonGrid
from module.base.decorator import Config
from module.base.timer import Timer
from module.handler.assets import *
from module.handler.enemy_searching import EnemySearchingHandler
from module.logger import logger
from module.map.assets import FLEET_PREPARATION_CHECK

AUTO_SEARCH_SETTINGS = [
    AUTO_SEARCH_SET_MOB,
    AUTO_SEARCH_SET_BOSS,
    AUTO_SEARCH_SET_ALL,
    AUTO_SEARCH_SET_STANDBY,
    AUTO_SEARCH_SET_SUB_AUTO,
    AUTO_SEARCH_SET_SUB_STANDBY
]
dic_setting_name_to_index = {
    'fleet1_mob_fleet2_boss': 0,
    'fleet1_boss_fleet2_mob': 1,
    'fleet1_all_fleet2_standby': 2,
    'fleet1_standby_fleet2_all': 3,
    'sub_auto_call': 4,
    'sub_standby': 5,
}
dic_setting_index_to_name = {v: k for k, v in dic_setting_name_to_index.items()}


class AutoSearchHandler(EnemySearchingHandler):
    @Config.when(SERVER='en')
    def _fleet_sidebar(self):
        if FLEET_PREPARATION_CHECK.match(self.device.image, offset=(20, 80)):
            offset = np.subtract(FLEET_PREPARATION_CHECK.button, FLEET_PREPARATION_CHECK._button)[1]
        else:
            offset = 0
        logger.attr('_fleet_sidebar_offset', offset)
        return ButtonGrid(
            origin=(1178, 171 + offset), delta=(0, 53),
            button_shape=(98, 42), grid_shape=(1, 3), name='FLEET_SIDEBAR')

    @Config.when(SERVER=None)
    def _fleet_sidebar(self):
        if FLEET_PREPARATION_CHECK.match(self.device.image, offset=(20, 80)):
            offset = np.subtract(FLEET_PREPARATION_CHECK.button, FLEET_PREPARATION_CHECK._button)[1]
        else:
            offset = 0
        logger.attr('_fleet_sidebar_offset', offset)
        return ButtonGrid(
            origin=(1185, 155 + offset), delta=(0, 111),
            button_shape=(53, 104), grid_shape=(1, 3), name='FLEET_SIDEBAR')

    def _fleet_preparation_get(self):
        """
        获取舰队准备界面当前选中的侧边栏索引。

        Returns:
            int:
                1 表示编队
                2 表示指挥喵
                3 表示自动搜索设置
        """
        current = 0
        total = 0
        sidebar = self._fleet_sidebar()

        for idx, button in enumerate(sidebar.buttons):
            if self.image_color_count(button, color=(99, 235, 255), threshold=221, count=50):
                current = idx + 1
                total = idx + 1
                continue
            if self.image_color_count(button, color=(255, 255, 255), threshold=221, count=100):
                total = idx + 1
            else:
                break

        if not current:
            logger.warning('No fleet sidebar active.')
        logger.attr('Fleet_sidebar', f'{current}/{total}')
        return current

    def fleet_preparation_sidebar_ensure(self, index):
        """
        确保舰队准备界面切换到指定的侧边栏标签。

        Args:
            index (int):
                1 表示编队
                2 表示指挥喵
                3 表示自动搜索设置

        Returns:
            bool: 是否成功切换到目标侧边栏，最多尝试 3 次，
                  超过则返回 False，成功则返回 True。
        """
        if index <= 0 or index > 5:
            logger.warning(f'Sidebar index cannot be ensured, {index}, limit 1 through 5 only')
            return False

        interval = Timer(1, count=2)
        sidebar = self._fleet_sidebar()
        for _ in self.loop(timeout=3):
            current = self._fleet_preparation_get()
            if current == index:
                return True
            if interval.reached():
                self.device.click(sidebar[0, index - 1])
                interval.reset()
                continue
        else:
            logger.warning('Sidebar could not be ensured')
            return False

    def _auto_search_set_click(self, setting):
        """
        点击自动搜索设置选项。

        Args:
            setting (str): 目标设置名称。

        Returns:
            bool: 是否已选中正确的选项。
        """
        active = []

        for index, button in enumerate(AUTO_SEARCH_SETTINGS):
            if self.image_color_count(button.button, color=(156, 255, 82), threshold=221, count=20):
                active.append(index)

        if not active:
            logger.warning('No active auto search setting found')
            return False

        logger.attr('Auto_Search_Setting', ', '.join([dic_setting_index_to_name[index] for index in active]))

        if setting not in dic_setting_name_to_index:
            logger.warning(f'Unknown auto search setting: {setting}')
        target_index = dic_setting_name_to_index[setting]

        if target_index in active:
            logger.info('Selected to the correct auto search setting')
            return True
        else:
            self.device.click(AUTO_SEARCH_SETTINGS[target_index])
            return False

    def auto_search_setting_ensure(self, setting, skip_first_screenshot=True):
        """
        确保自动搜索设置切换到指定选项。

        Args:
            setting (str):
                fleet1_mob_fleet2_boss, fleet1_boss_fleet2_mob, fleet1_all_fleet2_standby,
                fleet1_standby_fleet2_all, sub_auto_call, sub_standby
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否成功切换到目标设置，最多尝试 5 次，
                  超过则返回 False，成功则返回 True。
        """
        counter = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self._auto_search_set_click(setting):
                return True
            else:
                if counter >= 5:
                    logger.warning('Auto search setting could not be ensured')
                    return False
                counter += 1
                self.device.sleep((0.3, 0.5))
                continue

    _auto_search_offset = (5, 5)
    # 当 MULTIPLE_SORTIE 出现时向左偏移 213px
    _auto_search_menu_offset = (250, 30)

    def is_auto_search_running(self):
        """
        判断自动搜索是否正在运行。

        Returns:
            bool: 自动搜索是否已开启。
        """
        return self.appear(AUTO_SEARCH_MAP_OPTION_ON, offset=self._auto_search_offset) \
               and self.appear(AUTO_SEARCH_MAP_OPTION_ON)

    def handle_auto_search_map_option(self):
        """
        确保地图中的自动搜索选项已开启。

        Returns:
            bool: 是否进行了点击操作。
        """
        if self.appear(AUTO_SEARCH_MAP_OPTION_OFF, offset=self._auto_search_offset) \
                and self.appear_then_click(AUTO_SEARCH_MAP_OPTION_OFF, interval=2):
            return True

        return False

    def is_in_auto_search_menu(self):
        """
        判断是否处于自动搜索菜单界面。

        Returns:
            bool: 是否在自动搜索菜单中。
        """
        return AUTO_SEARCH_MENU_CONTINUE.match_luma(self.device.image, offset=self._auto_search_menu_offset)

    def handle_auto_search_continue(self):
        return self.appear_then_click(AUTO_SEARCH_MENU_CONTINUE, offset=self._auto_search_menu_offset, interval=2)

    def handle_auto_search_exit(self, drop=None):
        """
        处理自动搜索菜单的退出操作。

        Args:
            drop (DropImage): 掉落记录对象。

        Returns:
            bool: 是否执行了退出操作。
        """
        if self.appear(AUTO_SEARCH_MENU_EXIT, offset=self._auto_search_menu_offset, interval=2):
            # 此处实现较粗糙
            if drop:
                drop.handle_add(main=self, before=4)
            self.device.click(AUTO_SEARCH_MENU_EXIT)
            self.interval_reset(AUTO_SEARCH_MENU_EXIT)
            return True
        else:
            return False

    def ensure_auto_search_exit(self, skip_first_screenshot=True):
        """
        Pages:
            in: is_in_auto_search_menu
            out: page_campaign 或 page_event 或 page_sp
        """
        if not self.is_in_auto_search_menu():
            return False

        with self.stat.new(
                genre=self.config.campaign_name, method=self.config.DropRecord_CombatRecord
        ) as drop:
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                if self.handle_auto_search_exit(drop=drop):
                    continue

                # 结束条件
                if self.is_in_stage():
                    break

        return True