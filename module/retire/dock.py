"""
船坞界面操作模块。

提供船坞页面的 UI 交互功能，包括卡片网格布局、排序切换、
收藏筛选、筛选器设置与确认、舰船选择、进入舰船详情等操作。
定义了卡片各属性区域 (稀有度、等级、情绪、情绪状态) 的
按钮网格和情绪颜色常量。
"""

import module.config.server as server

from module.base.button import ButtonGrid, get_color, color_similar
from module.base.decorator import Config, cached_property
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.equipment.equipment import Equipment
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.retire.assets import *
from module.ui.scroll import Scroll
from module.ui.setting import Setting
from module.ui.switch import Switch

DOCK_SORTING = Switch('Dork_sorting')
DOCK_SORTING.add_state('Ascending', check_button=SORT_ASC, click_button=SORTING_CLICK)
DOCK_SORTING.add_state('Descending', check_button=SORT_DESC, click_button=SORTING_CLICK)

DOCK_FAVOURITE = Switch('Favourite_filter')
DOCK_FAVOURITE.add_state('on', check_button=COMMON_SHIP_FILTER_ENABLE)
DOCK_FAVOURITE.add_state('off', check_button=COMMON_SHIP_FILTER_DISABLE)

CARD_GRIDS = ButtonGrid(
    origin=(93, 76), delta=(164 + 2 / 3, 227), button_shape=(138, 204), grid_shape=(7, 2), name='CARD')
CARD_RARITY_GRIDS = CARD_GRIDS.crop(area=(0, 0, 138, 5), name='RARITY')
if server.server != 'jp':
    CARD_LEVEL_GRIDS = CARD_GRIDS.crop(area=(77, 5, 138, 27), name='LEVEL')
    CARD_EMOTION_GRIDS = CARD_GRIDS.crop(area=(23, 29, 48, 52), name='EMOTION')
else:
    CARD_LEVEL_GRIDS = CARD_GRIDS.crop(area=(74, 5, 136, 27), name='LEVEL')
    CARD_EMOTION_GRIDS = CARD_GRIDS.crop(area=(21, 29, 71, 48), name='EMOTION')
CARD_EMOTION_STATUS_GRIDS = CARD_GRIDS.crop(area=(113, 57, 135, 77), name='EMOTION_STATUS')
EMOTION_RED = (255, 122, 109)
EMOTION_YELLOW = (255, 194, 115)
EMOTION_GREEN = (148, 232, 104)

DOCK_SCROLL = Scroll(DOCK_SCROLL, color=(247, 211, 66), name='DOCK_SCROLL')

OCR_DOCK_SELECTED = DigitCounter(DOCK_SELECTED, threshold=64, name='OCR_DOCK_SELECTED')


class Dock(Equipment):
    """船坞界面操作处理器。

    提供船坞页面的通用操作：卡片加载等待、排序切换、收藏筛选、
    筛选器设置、舰船选择与确认、进入舰船详情等。
    继承 Equipment 以复用装备侧边导航栏操作。

    服务器差异：TW 服务器的筛选器按钮布局与其他服务器不同，
    通过 @Config.when 装饰器分发。
    """
    def handle_dock_cards_loading(self, skip_first_screenshot=True):
        """
        等待船坞卡片加载完成。

        通过哈希比对连续两帧截图判断画面是否稳定，若船坞为空则立即退出。
        使用 Timer(1.2s) 作为兜底超时，无法使用 confirm_timer 方法。

        Args:
            skip_first_screenshot: 是否跳过首次截图，复用上一状态循环的截图。
        """
        from module.retire.scanner import HashGenerator
        scanner = HashGenerator()
        old_result = None
        if not skip_first_screenshot:
            self.device.screenshot()
            skip_first_screenshot = True
        new_result = scanner.scan(self.device.image)
        timeout = Timer(1.2, count=1).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                old_result = new_result
                self.device.screenshot()
                new_result = scanner.scan(self.device.image)

            if self.appear(DOCK_EMPTY):
                logger.info('船坞为空')
                break
            if timeout.reached():
                break
            if old_result == new_result:
                break

    def dock_favourite_set(self, enable=False, wait_loading=True):
        """设置船坞是否仅筛选喜爱舰船。

        Args:
            enable (bool): True 表示仅显示喜爱舰船，False 表示显示全部。默认为 False。
            wait_loading (bool): 是否等待船坞卡片加载完成。连续设置时可设为 False。默认为 True。
        """
        if DOCK_FAVOURITE.set('on' if enable else 'off', main=self):
            if wait_loading:
                self.handle_dock_cards_loading()

    def _dock_quit_check_func(self):
        return not self.appear(DOCK_CHECK, offset=(20, 20))

    def dock_quit(self):
        self.ui_back(check_button=self._dock_quit_check_func, skip_first_screenshot=True)

    def dock_sort_method_dsc_set(self, enable=True, wait_loading=True):
        """设置船坞排序规则为降序或升序。

        Args:
            enable (bool): True 设置为降序，False 设置为升序。默认为 True。
            wait_loading (bool): 是否等待船坞卡片加载完成。默认为 True。
        """
        if DOCK_SORTING.set('Descending' if enable else 'Ascending', main=self):
            if wait_loading:
                self.handle_dock_cards_loading()

    def dock_filter_enter(self):
        logger.info('船坞筛选进入')
        self.interval_clear(DOCK_CHECK)
        for _ in self.loop():
            if self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60)):
                break
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=5):
                self.device.click(DOCK_FILTER)
                continue
            # 处理上次退役遗留的缓慢弹窗
            # 装备确认弹窗
            if self.appear_then_click(EQUIP_CONFIRM, offset=(30, 30), interval=2):
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(30, 30), interval=2):
                self.interval_clear(GET_ITEMS_1)
                continue
            # 获得物资弹窗
            if self.appear(GET_ITEMS_1, offset=(30, 30), interval=2):
                self.device.click(GET_ITEMS_1_RETIREMENT_SAVE)
                continue

    def dock_filter_confirm(self, wait_loading=True, skip_first_screenshot=True):
        """确认并保存船坞筛选设置，等待关闭筛选弹窗。

        Args:
            wait_loading (bool): 是否等待船坞卡片加载完成。默认为 True。
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 判定结束
            # 有时船坞筛选没有黑底模糊背景，DOCK_FILTER_CONFIRM 和 DOCK_CHECK 会同时出现
            if not self.appear(DOCK_FILTER_CONFIRM, offset=(20, 60)):
                if self.appear(DOCK_CHECK, offset=(20, 20)):
                    break
            if self.appear_then_click(DOCK_FILTER_CONFIRM, offset=(20, 60), interval=3):
                continue

        if wait_loading:
            self.handle_dock_cards_loading()

    @cached_property
    @Config.when(SERVER='tw')
    def dock_filter(self) -> Setting:
        delta = (147 + 1 / 3, 57)
        button_shape = (139, 42)
        setting = Setting(name='DOCK', main=self)
        setting.add_setting(
            setting='sort',
            option_buttons=ButtonGrid(
                origin=(218, 65), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_SORT'),
            # stat 包含额外网格，暂不单独处理
            option_names=['rarity', 'level', 'total', 'join', 'intimacy', 'mood', 'stat'],
            option_default='level'
        )
        setting.add_setting(
            setting='index',
            option_buttons=ButtonGrid(
                origin=(218, 138), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_INDEX'),
            option_names=['all', 'vanguard', 'main', 'dd', 'cl', 'ca', 'bb',
                          'cv', 'repair', 'ss', 'others', 'not_available', 'not_available', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='faction',
            option_buttons=ButtonGrid(
                origin=(218, 268), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_FACTION'),
            option_names=['all', 'eagle', 'royal', 'sakura', 'iron', 'dragon', 'sardegna',
                          'northern', 'iris', 'vichya', 'tulipa', 'meta', 'tempesta', 'other'],
            option_default='all'
        )
        setting.add_setting(
            setting='rarity',
            option_buttons=ButtonGrid(
                origin=(218, 427), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_RARITY'),
            option_names=['all', 'common', 'rare', 'elite', 'super_rare', 'ultra', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='extra',
            option_buttons=ButtonGrid(
                origin=(218, 499), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_EXTRA'),
            option_names=['no_limit', 'has_skin', 'can_retrofit', 'enhanceable', 'can_limit_break', 'not_level_max', 'can_awaken',
                          'can_awaken_plus', 'special', 'oath_skin', 'unique_augment_module', 'wear_skin', 'oathed', 'not_available'],
            option_default='no_limit'
        )
        return setting

    @cached_property
    @Config.when(SERVER=None)
    def dock_filter(self) -> Setting:
        delta = (147 + 1 / 3, 57)
        button_shape = (139, 42)
        setting = Setting(name='DOCK', main=self)
        setting.add_setting(
            setting='sort',
            option_buttons=ButtonGrid(
                origin=(218, 36), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_SORT'),
            # stat 包含额外网格，暂不单独处理
            option_names=['rarity', 'level', 'total', 'join', 'intimacy', 'mood', 'stat'],
            option_default='level'
        )
        setting.add_setting(
            setting='index',
            option_buttons=ButtonGrid(
                origin=(218, 109), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_INDEX'),
            option_names=['all', 'vanguard', 'main', 'dd', 'cl', 'ca', 'bb',
                          'cv', 'repair', 'ss', 'others', 'not_available', 'not_available', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='faction',
            option_buttons=ButtonGrid(
                origin=(218, 239), delta=delta, button_shape=button_shape, grid_shape=(7, 3), name='FILTER_FACTION'),
            option_names=['all', 'eagle', 'royal', 'sakura', 'iron', 'dragon', 'sardegna',
                          'northern', 'iris', 'vichya', 'tulipa', 'pedreria', 'meta', 'tempesta',
                          'other', 'not_available', 'not_available', 'not_available', 'not_available', 'not_available', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='rarity',
            option_buttons=ButtonGrid(
                origin=(218, 427), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_RARITY'),
            option_names=['all', 'common', 'rare', 'elite', 'super_rare', 'ultra', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='extra',
            option_buttons=ButtonGrid(
                origin=(218, 499), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_EXTRA'),
            option_names=['no_limit', 'has_skin', 'can_retrofit', 'enhanceable', 'can_limit_break', 'not_level_max', 'can_awaken',
                          'can_awaken_plus', 'special', 'oath_skin', 'unique_augment_module', 'wear_skin', 'oathed', 'not_available'],
            option_default='no_limit'
        )
        return setting

    def dock_filter_set(
            self,
            sort='level',
            index='all',
            faction='all',
            rarity='all',
            extra='no_limit',
            wait_loading=True,
            reset_index=False,
    ):
        """快速设置船坞的多维度筛选条件并确认。

        Args:
            sort (str | list): 排序依据（'rarity', 'level', 'total', 'join', 'intimacy', 'mood', 'stat'）。
            index (str | list): 舰种分类（'all', 'vanguard', 'main', 'dd', 'cl', 'ca', 'bb', 'cv', 'repair', 'ss', 'others'）。
            faction (str | list): 阵营筛选（'all', 'eagle', 'royal', 'sakura', 'iron', 'dragon', 'sardegna', 'northern', 'iris', 'vichya' 等）。
            rarity (str | list): 稀有度筛选（'all', 'common', 'rare', 'elite', 'super_rare', 'ultra'）。
            extra (str | list): 额外特性（'no_limit', 'has_skin', 'can_retrofit', 'enhanceable', 'can_limit_break', 'not_level_max', 'can_awaken' 等）。
            wait_loading (bool): 是否等待船坞卡片加载完成。默认为 True。
            reset_index (bool): 在同一面板先选“全部”清除旧舰种，再选择目标舰种；
                不重置排序及其他筛选。用于需要独立扫描各舰种的流程。

        Pages:
            in: page_dock
        """
        self.dock_filter_enter()
        if reset_index:
            self.dock_filter.set(sort=None, index='all', faction=None, rarity=None, extra=None)
        self.dock_filter.set(sort=sort, index=index, faction=faction, rarity=rarity, extra=extra)
        self.dock_filter_confirm(wait_loading=wait_loading)

    def dock_reset(self):
        """重置船坞所有筛选与排序条件为默认状态。"""
        self.dock_favourite_set(False, wait_loading=False)
        self.dock_sort_method_dsc_set(False, wait_loading=False)
        self.dock_filter_set()

    def dock_select_one(self, button):
        """在船坞中点击选中一艘舰船。

        Args:
            button (Button): 待选中的舰船卡片按钮。
        """
        self.interval_clear(DOCK_CHECK)
        click_interval = Timer(3, count=6)
        for _ in self.loop():
            if self.dock_selected():
                break

            # 使用 Timer 计次控制点击间隔
            if click_interval.reached():
                if self.appear(DOCK_CHECK, offset=(20, 20)):
                    self.device.click(button)
                    click_interval.reset()
                    continue
            if self.handle_popup_confirm('DOCK_SELECT'):
                continue

    def dock_selected(self):
        """检查船坞中是否已有选中的舰船。

        Returns:
            bool: 船坞计数显示 1/1 时返回 True，0/1 时返回 False。
        """
        current = 0
        timeout = Timer(1.5, count=3).start()
        for _ in self.loop():
            if timeout.reached():
                logger.warning('[退役-船坞] 获取已选数量超时，假设未选中')
                break

            current, _, total = OCR_DOCK_SELECTED.ocr(self.device.image)
            if total == 1:
                break

        return current > 0

    def dock_select_confirm(self, check_button, skip_first_screenshot=True):
        """点击确认选船按钮并等待目标界面出现。

        Args:
            check_button (callable | Button): 目标界面的确认按钮或判定函数。
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_process_check_button(check_button):
                break

            if self.appear_then_click(SHIP_CONFIRM, offset=(200, 50), interval=5):
                continue
            if self.handle_popup_confirm('DOCK_SELECT_CONFIRM'):
                continue

    def dock_enter_first(self, non_npc=True, skip_first_screenshot=True):
        """进入船坞中的第一艘舰船详情页。

        Args:
            non_npc (bool): 是否跳过 NPC 舰船（若第一艘是活动 NPC 则选择第二艘）。默认为 True。
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 成功进入舰船详情返回 True；船坞为空或仅有一艘 NPC 时返回 False。

        Pages:
            in: page_dock
            out: SHIP_DETAIL_CHECK
        """
        logger.info('进入船坞第一艘舰船')
        self.interval_clear(DOCK_CHECK, interval=3)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 判定结束
            if self.appear(SHIP_DETAIL_CHECK, offset=(20, 20)):
                return True
            if self.appear(DOCK_EMPTY, offset=(20, 20)):
                logger.info('船坞为空')
                return False

            # 点击进入详情
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                if non_npc:
                    # 检查是否为 NPC 舰船
                    if DOCK_FIRST_NPC.match_luma(self.device.image, offset=(20, 20)):
                        logger.info('第一艘是NPC舰船，选择第二艘')
                        button = CARD_GRIDS[(1, 0)]
                        # 检查是否存在第二艘舰船
                        color = get_color(self.device.image, button.area)
                        if color_similar(color, (34, 34, 42)):
                            logger.info('第二艘为空，船坞为空')
                            return False
                    else:
                        button = CARD_GRIDS[(0, 0)]
                else:
                    button = CARD_GRIDS[(0, 0)]
                self.device.click(button)
                continue
            if self.handle_game_tips():
                continue
