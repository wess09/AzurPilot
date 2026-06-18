import module.config.server as server

from module.base.button import ButtonGrid, get_color, color_similar
from module.base.decorator import cached_property
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
        # confirm_timer 方法不可用，手动设置超时
        timeout = Timer(1.2, count=1).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                old_result = new_result
                self.device.screenshot()
                new_result = scanner.scan(self.device.image)
            # 船坞为空时快速退出
            if self.appear(DOCK_EMPTY):
                logger.info('Dock empty')
                break
            # 兜底超时 1.2s
            if timeout.reached():
                break
            # 画面已稳定，加载完成
            if old_result == new_result:
                break

    def dock_favourite_set(self, enable=False, wait_loading=True):
        """
        设置船坞收藏筛选。

        切换收藏夹筛选开关，开启后仅显示已收藏的舰船。

        Args:
            enable: True 仅筛选收藏舰船，False 显示全部。
            wait_loading: 是否等待卡片加载完成，连续操作时可设为 False。

        Pages:
            in: page_dock
        """
        if DOCK_FAVOURITE.set('on' if enable else 'off', main=self):
            if wait_loading:
                self.handle_dock_cards_loading()

    def _dock_quit_check_func(self):
        """检查是否已离开船坞页面（DOCK_CHECK 不再出现）。"""
        return not self.appear(DOCK_CHECK, offset=(20, 20))

    def dock_quit(self):
        """
        退出船坞页面。

        Pages:
            in: page_dock
            out: page_main
        """
        self.ui_back(check_button=self._dock_quit_check_func, skip_first_screenshot=True)

    def dock_sort_method_dsc_set(self, enable=True, wait_loading=True):
        """
        设置船坞排序方向。

        切换升序/降序排列，切换后等待卡片重新加载。

        Args:
            enable: True 设置为降序排列，False 设置为升序排列。
            wait_loading: 是否等待卡片加载完成，连续操作时可设为 False。

        Pages:
            in: page_dock
        """
        if DOCK_SORTING.set('Descending' if enable else 'Ascending', main=self):
            if wait_loading:
                self.handle_dock_cards_loading()

    def dock_filter_enter(self):
        """
        进入船坞筛选面板。

        点击筛选按钮并等待筛选面板出现。处理退役流程残留的弹窗（装备确认、获取物品）。

        Pages:
            in: page_dock (DOCK_CHECK)
            out: DOCK_FILTER_CONFIRM
        """
        logger.info('Dock filter enter')
        self.interval_clear(DOCK_CHECK)
        for _ in self.loop():
            if self.appear(DOCK_FILTER_CONFIRM, offset=(20, 20)):
                break
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=5):
                self.device.click(DOCK_FILTER)
                continue
            # 上次退役遗留的慢速弹窗：装备确认
            if self.appear_then_click(EQUIP_CONFIRM, offset=(30, 30), interval=2):
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(30, 30), interval=2):
                self.interval_clear(GET_ITEMS_1)
                continue
            # 上次退役遗留的慢速弹窗：获取物品
            if self.appear(GET_ITEMS_1, offset=(30, 30), interval=2):
                self.device.click(GET_ITEMS_1_RETIREMENT_SAVE)
                continue

    def dock_filter_confirm(self, wait_loading=True, skip_first_screenshot=True):
        """
        确认筛选面板并等待关闭。

        点击确认按钮关闭筛选面板。部分情况下筛选面板没有黑色模糊背景，
        DOCK_FILTER_CONFIRM 和 DOCK_CHECK 同时出现，此时需等待前者消失。

        Args:
            wait_loading: 是否等待卡片加载完成，连续操作时可设为 False。
            skip_first_screenshot: 是否跳过首次截图，复用上一状态循环的截图。

        Pages:
            in: DOCK_FILTER_CONFIRM
            out: page_dock (DOCK_CHECK)
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 筛选面板已关闭（确认按钮消失且船坞页面出现）
            if not self.appear(DOCK_FILTER_CONFIRM, offset=(20, 20)):
                if self.appear(DOCK_CHECK, offset=(20, 20)):
                    break
            if self.appear_then_click(DOCK_FILTER_CONFIRM, offset=(20, 20), interval=3):
                continue

        if wait_loading:
            self.handle_dock_cards_loading()

    @cached_property
    def dock_filter(self) -> Setting:
        delta = (147 + 1 / 3, 57)
        button_shape = (139, 42)
        setting = Setting(name='DOCK', main=self)
        setting.add_setting(
            setting='sort',
            option_buttons=ButtonGrid(
                origin=(218, 65), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_SORT'),
            # stat 选项有多余的网格，不值得处理
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
                origin=(218, 398), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name='FILTER_RARITY'),
            option_names=['all', 'common', 'rare', 'elite', 'super_rare', 'ultra', 'not_available'],
            option_default='all'
        )
        setting.add_setting(
            setting='extra',
            option_buttons=ButtonGrid(
                origin=(218, 471), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name='FILTER_EXTRA'),
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
            wait_loading=True
    ):
        """
        一步设置船坞筛选条件。

        进入筛选面板、设置所有筛选项、确认并等待加载。支持单个值或列表。

        Args:
            sort: 排序方式，可选值：rarity, level, total, join, intimacy, mood, stat。
            index: 舰种筛选，可选值：all, vanguard, main, dd, cl, ca, bb,
                cv, repair, ss, others, not_available。
            faction: 阵营筛选，可选值：all, eagle, royal, sakura, iron, dragon, sardegna,
                northern, iris, vichya, tulipa, meta, tempesta, other。
            rarity: 稀有度筛选，可选值：all, common, rare, elite, super_rare, ultra, not_available。
            extra: 额外筛选，可选值：no_limit, has_skin, can_retrofit, enhanceable,
                can_limit_break, not_level_max, can_awaken, can_awaken_plus,
                special, oath_skin, unique_augment_module, wear_skin, oathed, not_available。
            wait_loading: 是否等待卡片加载完成，连续操作时可设为 False。

        Pages:
            in: page_dock
        """
        self.dock_filter_enter()
        self.dock_filter.set(sort=sort, index=index, faction=faction, rarity=rarity, extra=extra)
        self.dock_filter_confirm(wait_loading=wait_loading)

    def dock_select_one(self, button, skip_first_screenshot=True):
        """
        在船坞中选择一艘舰船。

        点击指定舰船卡片并等待选择确认（选中计数变为 1/1）。
        处理可能出现的弹窗确认对话框。

        Args:
            button: 要选择的舰船卡片按钮。
            skip_first_screenshot: 是否跳过首次截图，复用上一状态循环的截图。

        Pages:
            in: page_dock (DOCK_CHECK)
        """
        self.interval_clear(DOCK_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.dock_selected():
                break

            if self.appear(DOCK_CHECK, offset=(20, 20), interval=5):
                self.device.click(button)
                continue
            if self.handle_popup_confirm('DOCK_SELECT'):
                continue

    def dock_selected(self, skip_first_screenshot=True):
        """
        检查船坞中是否已选中舰船。

        通过 OCR 读取选中计数（如 1/1），判断是否有舰船被选中。
        超时 1.5 秒后假设未选中。

        Args:
            skip_first_screenshot: 是否跳过首次截图，复用上一状态循环的截图。

        Returns:
            bool: True 表示已选中舰船（计数 >= 1/1），False 表示未选中（0/1）。
        """
        current = 0
        timeout = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Get dock_selected timeout, assume not selected')
                break

            current, _, total = OCR_DOCK_SELECTED.ocr(self.device.image)
            if total == 1:
                break

        return current > 0

    def dock_select_confirm(self, check_button, skip_first_screenshot=True):
        """
        确认舰船选择并等待跳转到目标页面。

        点击确认按钮，等待 check_button 指定的页面出现。
        处理可能出现的弹窗确认对话框。

        Args:
            check_button: 目标页面的检测按钮，可以是 Button 或 callable。
            skip_first_screenshot: 是否跳过首次截图，复用上一状态循环的截图。

        Pages:
            in: SHIP_CONFIRM
            out: check_button 对应的页面
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
        """
        进入船坞中第一艘舰船的详情页。

        点击第一艘舰船卡片进入详情。若 non_npc 为 True 且第一艘是 NPC，
        则自动选择第二艘。船坞为空时返回 False。

        Args:
            non_npc: True 时若第一艘是 NPC 则选择第二艘，False 时始终选择第一艘。
            skip_first_screenshot: 是否跳过首次截图，复用上一状态循环的截图。

        Returns:
            bool: True 成功进入舰船详情页，False 船坞为空或无可用舰船。

        Pages:
            in: page_dock (DOCK_CHECK)
            out: SHIP_DETAIL_CHECK
        """
        logger.info('Dock enter first')
        self.interval_clear(DOCK_CHECK, interval=3)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 退出条件：已进入详情页或船坞为空
            if self.appear(SHIP_DETAIL_CHECK, offset=(20, 20)):
                return True
            if self.appear(DOCK_EMPTY, offset=(20, 20)):
                logger.info('Dock empty')
                return False

            # 点击舰船卡片
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                if non_npc:
                    # 检测第一艘是否为 NPC
                    if DOCK_FIRST_NPC.match_luma(self.device.image, offset=(20, 20)):
                        logger.info('First ship is NPC, select second')
                        button = CARD_GRIDS[(1, 0)]
                        # 检测第二艘是否存在
                        color = get_color(self.device.image, button.area)
                        if color_similar(color, (34, 34, 42)):
                            logger.info('Second ship empty, dock empty')
                            return False
                    else:
                        button = CARD_GRIDS[(0, 0)]
                else:
                    button = CARD_GRIDS[(0, 0)]
                self.device.click(button)
                continue
            if self.handle_game_tips():
                continue
