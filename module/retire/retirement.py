import re

from module.base.button import Button, ButtonGrid
from module.base.filter import Filter
from module.base.timer import Timer
from module.base.utils import color_similar, get_color, resize, lower_template_match_similarity
from module.combat.assets import GET_ITEMS_1
from module.exception import RequestHumanTakeover, ScriptError
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON
from module.logger import logger
from module.retire.assets import (
    DOCK_CHECK, DOCK_SHIP_DOWN, EQUIP_CONFIRM, EQUIP_CONFIRM_2,
    GET_ITEMS_1_RETIREMENT_SAVE, IN_RETIREMENT_CHECK, ONE_CLICK_RETIREMENT,
    RETIRE_APPEAR_1, RETIRE_APPEAR_2, RETIRE_APPEAR_3, RETIRE_COIN,
    RETIRE_CONFIRM_SCROLL_AREA, SHIP_CONFIRM, SHIP_CONFIRM_2, SR_SSR_CONFIRM,
    TEMPLATE_AULICK, TEMPLATE_BOGUE, TEMPLATE_CASSIN_1, TEMPLATE_CASSIN_2,
    TEMPLATE_DOWNES_1, TEMPLATE_DOWNES_2, TEMPLATE_FOOTE, TEMPLATE_HERMES,
    TEMPLATE_LANGLEY, TEMPLATE_RANGER, TEMPLATE_Z20, TEMPLATE_Z21
)
from module.retire.enhancement import Enhancement
from module.retire.scanner import ShipScanner
from module.retire.setting import QuickRetireSettingHandler
from module.ui.scroll import Scroll

CARD_GRIDS = ButtonGrid(
    origin=(93, 76), delta=(164 + 2 / 3, 227), button_shape=(138, 204), grid_shape=(7, 2), name='CARD')
CARD_RARITY_GRIDS = ButtonGrid(
    origin=(93, 76), delta=(164 + 2 / 3, 227), button_shape=(138, 5), grid_shape=(7, 2), name='RARITY')

CARD_RARITY_COLORS = {
    'N': (174, 176, 187),
    'R': (106, 195, 248),
    'SR': (151, 134, 254),
    'SSR': (248, 223, 107)
    # 不支持婚戒卡牌
}

RETIRE_CONFIRM_SCROLL = Scroll(RETIRE_CONFIRM_SCROLL_AREA, color=(74, 77, 110), name='STRATEGIC_SEARCH_SCROLL')
# 背景颜色为 (66, 72, 77)，默认阈值 (256-221)=35 不足以区分
RETIRE_CONFIRM_SCROLL.color_threshold = 240

COMMON_CV_FILTER_REGEX = re.compile(
    '(bogue|hermes|langley|ranger)+?',
    flags=re.IGNORECASE)
COMMON_DD_FILTER_REGEX = re.compile(
    '(z20|z21|aulick|foote|cassin|downes)+?',
    flags=re.IGNORECASE)
FILTER_ATTR = ('ship',)
COMMON_CV_FILTER = Filter(COMMON_CV_FILTER_REGEX, FILTER_ATTR)
COMMON_DD_FILTER = Filter(COMMON_DD_FILTER_REGEX, FILTER_ATTR)

TEMPLATE_COMMON_CV = {
    'BOGUE': TEMPLATE_BOGUE,
    'HERMES': TEMPLATE_HERMES,
    'LANGLEY': TEMPLATE_LANGLEY,
    'RANGER': TEMPLATE_RANGER
}
TEMPLATE_COMMON_DD = {
    'Z20': TEMPLATE_Z20,
    'Z21': TEMPLATE_Z21,
    'AULICK': TEMPLATE_AULICK,
    'FOOTE': TEMPLATE_FOOTE,
    'CASSIN': [TEMPLATE_CASSIN_1, TEMPLATE_CASSIN_2],
    'DOWNES': [TEMPLATE_DOWNES_1, TEMPLATE_DOWNES_2]
}

class Retirement(Enhancement, QuickRetireSettingHandler):
    _unable_to_enhance = False
    _have_kept_cv = True

    # 来自 MapOperation，用于战斗中退役弹窗的计时
    map_cat_attack_timer = Timer(2)

    @property
    def retire_keep_common_cv(self):
        return self.config.is_task_enabled('GemsFarming') or self.config.is_task_enabled('ThreeOilLowCost')

    def _retirement_choose(self, amount=10, target_rarity=('N',)):
        """
        在退役界面中选择指定稀有度的舰船卡牌。

        通过颜色识别每张卡牌的稀有度，然后点击目标稀有度的卡牌进行选中。

        Args:
            amount (int): 要退役的卡牌数量，范围 0 到 10。
            target_rarity (tuple[str]): 目标稀有度，如 ('N',)、('N', 'R')。

        Returns:
            int: 实际选中的卡牌数量。
        """
        cards = []
        rarity = []
        for x, y, button in CARD_RARITY_GRIDS.generate():
            card_color = get_color(image=self.device.image, area=button.area)
            f = False
            for r, rarity_color in CARD_RARITY_COLORS.items():

                if color_similar(card_color, rarity_color, threshold=15):
                    cards.append([x, y])
                    rarity.append(r)
                    f = True

            if not f:
                logger.warning(
                    f'Unknown rarity color. Grid: ({x}, {y}). Color: {card_color}')

        logger.info(' '.join([r.rjust(3) for r in rarity[:7]]))
        logger.info(' '.join([r.rjust(3) for r in rarity[7:]]))

        selected = 0
        for card, r in zip(cards, rarity):
            if r in target_rarity:
                self.device.click(CARD_GRIDS[card])
                self.device.sleep((0.1, 0.15))
                selected += 1
            if selected >= amount:
                break
        return selected

    def _retirement_confirm(self, skip_first_screenshot=True):
        """
        确认退役流程，处理所有弹出的确认对话框。

        按显示层级依次处理舰船确认、装备拆解确认、获得物品和 SR/SSR 确认弹窗。
        GemsFarming 使用的舰船没有装备可拆解，`executed` 可能永远不为 True，
        因此使用超时机制兜底，避免无限循环。

        Pages:
            in: IN_RETIREMENT_CHECK, 以及
                SHIP_CONFIRM_2（一键退役模式）
                SHIP_CONFIRM（旧退役模式）
            out: IN_RETIREMENT_CHECK
        """
        logger.info('Retirement confirm')
        executed = False
        for button in [SHIP_CONFIRM, SHIP_CONFIRM_2, EQUIP_CONFIRM, EQUIP_CONFIRM_2, GET_ITEMS_1, SR_SSR_CONFIRM]:
            self.interval_clear(button)
        self.popup_interval_clear()
        timeout = Timer(10, count=10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件——超时兜底
            if timeout.reached():
                logger.warning('Wait _retirement_confirm timeout, assume finished')
                break
            # 有时 EQUIP_CONFIRM 没有黑色模糊背景，与 IN_RETIREMENT_CHECK 同时出现
            if self.appear(IN_RETIREMENT_CHECK, offset=(20, 20)) and not self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                if executed:
                    break
            else:
                timeout.reset()

            # 点击——按显示层级排序
            # SR/SSR 确认弹窗（一键退役或旧模式退役 SR/SSR 时出现）
            if self._unable_to_enhance \
                    or self.config.OldRetire_SR \
                    or self.config.OldRetire_SSR \
                    or self.config.Retirement_RetireMode == 'one_click_retire':
                if self.handle_popup_confirm(name='RETIRE_SR_SSR', offset=(20, 50)):
                    # 避免重复点击底层的 SHIP_CONFIRM
                    self.interval_reset([SHIP_CONFIRM, SHIP_CONFIRM_2])
                    # EQUIP_CONFIRM_2 可能被误识别为 popup confirm
                    self.interval_reset([EQUIP_CONFIRM, EQUIP_CONFIRM_2])
                    continue
                if self.config.SERVER in ['cn', 'jp', 'tw'] and \
                        self.appear_then_click(SR_SSR_CONFIRM, offset=(20, 50), interval=2):
                    # 避免重复点击底层的 SHIP_CONFIRM
                    self.interval_reset([SHIP_CONFIRM, SHIP_CONFIRM_2])
                    # EQUIP_CONFIRM_2 可能被误识别为 popup confirm
                    self.interval_reset([EQUIP_CONFIRM, EQUIP_CONFIRM_2])
                    continue
            # 舰船确认（一键退役）
            if self.match_template_color(SHIP_CONFIRM_2, offset=(30, 30), interval=2):
                if self.retire_keep_common_cv and not self._have_kept_cv:
                    self.keep_one_common_cv()
                self.device.click(SHIP_CONFIRM_2)
                # GET_ITEMS_1 即将出现，清除以避免重新进入舰船确认
                self.interval_clear(GET_ITEMS_1)
                self.interval_reset([SHIP_CONFIRM, SHIP_CONFIRM_2])
                continue
            # 舰船确认（旧退役）
            if self.match_template_color(SHIP_CONFIRM, offset=(30, 30), interval=2):
                self.device.click(SHIP_CONFIRM)
                continue
            # 装备拆解确认
            if self.appear_then_click(EQUIP_CONFIRM, offset=(30, 30), interval=2):
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(30, 30), interval=2):
                self.interval_clear(GET_ITEMS_1)
                executed = True
                continue
            # 获得物品画面
            if self.appear(GET_ITEMS_1, offset=(30, 30), interval=2):
                self.device.click(GET_ITEMS_1_RETIREMENT_SAVE)
                self.interval_reset(SHIP_CONFIRM)
                # 下一个出现的是装备拆解确认
                self.interval_clear([EQUIP_CONFIRM, EQUIP_CONFIRM_2])
                continue

    def retirement_appear(self):
        """
        检测退役确认弹窗是否出现。

        Returns:
            bool: 退役弹窗三个特征按钮全部出现则返回 True。
        """
        return self.appear(RETIRE_APPEAR_1, offset=30) \
               and self.appear(RETIRE_APPEAR_2, offset=30) \
               and self.appear(RETIRE_APPEAR_3, offset=30)

    def _retirement_quit(self):
        """
        退出退役/船坞界面，返回上一级页面。

        通过 ui_back 逐级返回，直到 IN_RETIREMENT_CHECK 和 DOCK_CHECK 均消失。
        """
        def check_func():
            return not self.appear(IN_RETIREMENT_CHECK, offset=(20, 20)) \
                   and not self.appear(DOCK_CHECK, offset=(20, 20))

        self.ui_back(check_button=check_func, skip_first_screenshot=True)

    @property
    def _retire_rarity(self):
        """
        根据用户配置获取需要退役的稀有度集合。

        Returns:
            set[str]: 稀有度集合，如 {'N', 'R'}。
        """
        rarity = set()
        if self.config.OldRetire_N:
            rarity.add('N')
        if self.config.OldRetire_R:
            rarity.add('R')
        if self.config.OldRetire_SR:
            rarity.add('SR')
        if self.config.OldRetire_SSR:
            rarity.add('SSR')
        return rarity

    def _retire_wait_slow_retire(self, skip_first_screenshot=True):
        """
        等待一键退役后的 SHIP_CONFIRM_2 出现。

        在慢速设备或大型船坞中，SHIP_CONFIRM_2 可能出现较慢。
        如果 60 秒内未出现，GameStuckError 将被触发。

        Returns:
            bool: SHIP_CONFIRM_2 出现则返回 True。
        """
        logger.info('Wait slow retire')
        self.device.click_record_clear()
        self.device.stuck_record_clear()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件
            if self.appear(SHIP_CONFIRM_2, offset=(30, 30)):
                return True

    def retire_ships_one_click(self):
        """
        使用一键退役功能批量退役舰船。

        一键退役不需要检查船坞，直接点击 ONE_CLICK_RETIREMENT 按钮。
        客户端会一次性退役所有符合条件的舰船，因此只需执行一轮。
        如果需要保留普通航母，会在退役确认前保留一艘。

        Returns:
            int: 退役的舰船数量（每轮 10 艘）。
        """
        logger.hr('Retirement')
        logger.info('Using one click retirement.')
        # 一键退役不需要等待加载船坞
        self.dock_favourite_set(wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        end = False
        total = 0

        if self.retire_keep_common_cv:
            self._have_kept_cv = False

        while 1:
            self.handle_info_bar()

            # 内层循环：ONE_CLICK_RETIREMENT -> SHIP_CONFIRM_2 或 info_bar
            skip_first_screenshot = True
            click_count = 0
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()
                # 结束条件
                if self.appear(SHIP_CONFIRM_2, offset=(30, 30)):
                    break
                if self.info_bar_count():
                    logger.info('No more ships to retire.')
                    end = True
                    break

                # 点击——多次重试后等待慢速退役
                if click_count >= 5:
                    logger.warning('Failed to select ships using ONE_CLICK_RETIREMENT after 5 trial')
                    if self._retire_wait_slow_retire():
                        # 等待成功，继续在同一截图上触发 ONE_CLICK_RETIREMENT
                        pass
                    else:
                        # 可能是游戏 bug，标记退役完成，上层会重新调用退役
                        end = True
                        total = 10
                        break
                if self.appear_then_click(ONE_CLICK_RETIREMENT, offset=(20, 20), interval=2):
                    click_count += 1
                    continue

            # info_bar 提示无更多舰船可退役
            if end:
                break
            # SHIP_CONFIRM_2 -> 退役确认流程
            self._retirement_confirm()
            total += 10
            # 客户端一次性退役所有舰船，直接退出
            break

        logger.info(f'Total retired round: {total // 10}')
        return total

    def retire_ships_old(self, amount=None, rarity=None):
        """
        使用旧退役模式手动选择并退役指定数量和稀有度的舰船。

        在退役界面通过颜色识别卡牌稀有度，逐批选择目标稀有度的卡牌进行退役。

        Args:
            amount (int): 要退役的数量，范围 0 到 2000。默认从配置读取。
            rarity (tuple[str]): 目标稀有度，如 ('N',)、('N', 'R')。默认从配置读取。

        Returns:
            int: 实际退役的舰船总数。
        """
        if amount is None:
            amount = self._retire_amount
        if rarity is None:
            rarity = self._retire_rarity
        logger.hr('Retirement')
        logger.info(f'Amount={amount}. Rarity={rarity}')

        # 将稀有度映射为过滤器名称
        correspond_name = {
            'N': 'common',
            'R': 'rare',
            'SR': 'elite',
            'SSR': 'super_rare'
        }
        _rarity = [correspond_name[i] for i in rarity]
        self.dock_sort_method_dsc_set(False, wait_loading=False)
        self.dock_favourite_set(False, wait_loading=False)
        self.dock_filter_set(
            sort='level', index='all', faction='all', rarity=_rarity, extra='no_limit')

        total = 0

        if self.retire_keep_common_cv:
            self._have_kept_cv = False

        while amount:
            selected = self._retirement_choose(
                amount=10 if amount > 10 else amount, target_rarity=rarity)
            total += selected
            if selected == 0:
                break
            self.device.screenshot()
            if not self.match_template_color(SHIP_CONFIRM, offset=(30, 30)):
                logger.warning('No ship selected, retrying')
                continue

            self._retirement_confirm()

            amount -= selected
            if amount <= 0:
                break

            self.handle_dock_cards_loading()
            continue

        self.dock_sort_method_dsc_set(True, wait_loading=False)
        self.dock_filter_set()
        logger.info(f'Total retired: {total}')
        return total

    def retire_gems_farming_flagships(self, keep_one=True) -> int:
        """
        退役 GemsFarming 遗弃的旗舰（普通航母）。

        筛选条件：稀有度为 common、等级 > 1、不在编队中、状态为空闲。
        如果 keep_one 为 True，会保留等级最低的一艘。

        Args:
            keep_one (bool): 是否至少保留一艘普通航母。默认 True。

        Returns:
            int: 退役的舰船数量。
        """
        logger.info('Retire abandoned flagships of GemsFarming/ThreeOilLowCost')

        gems_farming_enable: bool = self.config.is_task_enabled('GemsFarming') or self.config.is_task_enabled('ThreeOilLowCost')
        if not gems_farming_enable:
            logger.info('Not in GemsFarming/ThreeOilLowCost, skip')
            return 0

        self.dock_favourite_set(wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        self.dock_filter_set(index='cv', rarity='common', extra='not_level_max', sort='level')

        scanner = ShipScanner(
            rarity='common', fleet=0, status='free', level=(2, 100))
        scanner.disable('emotion')

        total = 0
        _ = self._have_kept_cv
        self._have_kept_cv = True

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self.handle_info_bar()
            ships = scanner.scan(self.device.image)
            if not ships:
                # 无可退役舰船，退出
                break
            if keep_one:
                if len(ships) < 2:
                    break
                else:
                    # 保留等级最低的一艘
                    ships.sort(key=lambda s: -s.level)
                    ships = ships[:-1]

            for ship in ships:
                self.device.click(ship.button)
                self.device.sleep((0.1, 0.15))
                total += 1

            self._retirement_confirm()

            # 少于 10 艘时快速退出
            if len(ships) < 10:
                break

        self._have_kept_cv = _
        # 退役完成，即将退出，无需等待加载
        self.dock_filter_set(wait_loading=False)

        return total

    def handle_retirement(self):
        """
        处理船坞满载时的退役/强化流程。

        根据配置的退役模式（enhance/one_click_retire/old_retire）选择对应策略：
        - enhance: 先尝试强化，强化失败或剩余船坞不足时切换到退役
        - one_click_retire / old_retire: 直接退役

        Returns:
            bool: True 表示已完成退役或强化操作。
        """
        # 2025.05.29 进入船坞时游戏会弹出皮肤信息提示
        if self.handle_game_tips():
            return True
        if self._unable_to_enhance:
            if self.appear_then_click(RETIRE_APPEAR_1, offset=(20, 20), interval=3):
                self.interval_clear(IN_RETIREMENT_CHECK)
                self.interval_reset([AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON])
                self.map_cat_attack_timer.reset()
                return False
            if self.appear(IN_RETIREMENT_CHECK, offset=(20, 20), interval=10):
                try:
                    # 移除硬编码的退役模式参数，使用配置的默认模式
                    self._retire_handler()
                    self._unable_to_enhance = False
                    self.interval_reset(IN_RETIREMENT_CHECK)
                    self.map_cat_attack_timer.reset()
                    return True
                except Exception as e:
                    logger.warning(f'Retirement failed: {e}')
                    self._unable_to_enhance = False  # 防止无限循环
                    return False
        elif self.config.Retirement_RetireMode == 'enhance':
            if self.appear_then_click(RETIRE_APPEAR_3, offset=(20, 20), interval=3):
                self.interval_clear(DOCK_CHECK)
                self.interval_reset([AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON])
                self.map_cat_attack_timer.reset()
                return False
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=10):
                self.handle_dock_cards_loading()
                try:
                    total, remain = self._enhance_handler()
                    if not total:
                        logger.info(
                            'No ship to enhance, but dock full, will try retire')
                        self._unable_to_enhance = True
                    logger.info(f'The remaining spare dock amount is {remain}')
                    if remain < 3:
                        logger.info('Too few spare docks, retire next time')
                        self._unable_to_enhance = True
                except Exception as e:
                    logger.warning(f'Enhancement failed: {e}')
                    self._unable_to_enhance = True  # 尝试退役
                self.interval_reset(DOCK_CHECK)
                self.map_cat_attack_timer.reset()
                return True
        else:
            if self.appear_then_click(RETIRE_APPEAR_1, offset=(20, 20), interval=3):
                self.interval_clear(IN_RETIREMENT_CHECK)
                self.interval_reset([AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON])
                self.map_cat_attack_timer.reset()
                return False
            if self.appear(IN_RETIREMENT_CHECK, offset=(20, 20), interval=10):
                try:
                    self._retire_handler()
                    self._unable_to_enhance = False
                    self.interval_reset(IN_RETIREMENT_CHECK)
                    self.map_cat_attack_timer.reset()
                    return True
                except Exception as e:
                    logger.warning(f'Retirement failed: {e}')
                    self._unable_to_enhance = False  # 防止无限循环
                    return False

        return False

    def _retire_handler(self, mode=None):
        """
        退役调度器，根据模式分发到对应退役策略。

        一键退役模式下，如果初始退役失败，会逐步放宽快速退役设置重试。
        旧退役模式直接调用 retire_ships_old。

        Args:
            mode (str): 退役模式，'one_click_retire' 或 'old_retire'。默认从配置读取。

        Returns:
            int: 退役的舰船总数。

        Raises:
            RequestHumanTakeover: 无可退役舰船时抛出，需要用户介入。

        Pages:
            in: IN_RETIREMENT_CHECK
            out: 退役弹窗出现前的页面
        """
        if mode is None:
            mode = self.config.Retirement_RetireMode

        # 当模式为 'enhance' 时，使用 'one_click_retire' 作为默认退役模式
        if mode == 'enhance':
            logger.info('Retirement mode is set to enhance, using one_click_retire as fallback')
            mode = 'one_click_retire'

        if mode == 'one_click_retire':
            total = self.retire_ships_one_click()
            if not total:
                logger.warning(
                    'No ship retired, trying to reset dock filter and disable favourite, then retire again')
                self.dock_favourite_set(False, wait_loading=False)
                self.dock_filter_set()
                total = self.retire_ships_one_click()
            if self.server_support_quick_retire_setting_fallback():
                # 部分用户可能已设置 filter_5='all'，先尝试保留该设置
                if not total:
                    logger.warning('No ship retired, trying to reset the first 4 quick retire settings')
                    self.quick_retire_setting_set(filter_5=None)
                    total = self.retire_ships_one_click()
                if not total:
                    logger.warning('No ship retired, trying to reset quick retire settings to "keep_limit_break"')
                    self.quick_retire_setting_set(filter_5='keep_limit_break')
                    total = self.retire_ships_one_click()
                if not total and self.config.OneClickRetire_KeepLimitBreak == 'do_not_keep':
                    logger.warning('No ship retired, trying to reset quick retire settings to "all"')
                    self.quick_retire_setting_set('all')
                    total = self.retire_ships_one_click()
            total += self.retire_gems_farming_flagships(keep_one=total > 0)
            if not total:
                logger.critical('杂鱼大叔~ 根本没有船可以退役啦，你是来表演冷笑话的吗？❤')
                logger.critical('赶紧把游戏里的“一键退役”配置好啦！不配置的话，难道大叔想让我亲手帮你点吗？❤')
                logger.critical('哼，因为大叔太笨没配置好退役，脚本只能停掉了呢。赶紧去求求谁教教你怎么操作吧~')
                raise RequestHumanTakeover
        elif mode == 'old_retire':
            self.handle_dock_cards_loading()
            total = self.retire_ships_old()
            total += self.retire_gems_farming_flagships()
            if not total:
                logger.critical('甚至没船能退役，你这设置是认真的吗？')
                logger.critical('既然你想让脚本停，我也挺支持的，毕竟这设置简直不可思议。')
                logger.critical('未退役任何船只，如果你眼瞎没开对应稀有度，请去 Alas 设置打开。')
                raise RequestHumanTakeover
        else:
            raise ScriptError(
                f'Unknown retire mode: {self.config.Retirement_RetireMode}')

        self._retirement_quit()
        self.config.DOCK_FULL_TRIGGERED = True

        return total

    def _retire_select_one(self, button, skip_first_screenshot=True):
        """
        在退役确认界面中选择一艘舰船（取消其退役）。

        通过检测 RETIRE_COIN 模板是否变化来判断是否成功选中。
        最多重试 3 次。

        Args:
            button (Button): 要选择的舰船按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。
        """
        count = 0
        RETIRE_COIN.load_color(self.device.image)
        RETIRE_COIN._match_init = True
        self.interval_clear(SHIP_CONFIRM_2)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件——RETIRE_COIN 模板变化说明选中成功
            if not RETIRE_COIN.match(self.device.image, offset=(20, 20), similarity=0.97):
                return True
            if count > 3:
                logger.warning('_retire_select_one failed after 3 trial')
                return False

            if self.appear(SHIP_CONFIRM_2, offset=(30, 30), interval=2):
                self.device.click(button)
                count += 1
                continue

    def get_common_ship_filter(self, string, ship_type='cv', output=True):
        """
        解析普通稀有度航母/驱逐舰的过滤器字符串，返回舰船名称列表。

        如果过滤器无效，自动回退到配置中的默认值并写回配置。

        Args:
            string (str): 过滤器字符串。
            ship_type (str): 舰船类型，'cv' 或 'dd'。
            output (bool): 是否输出日志。默认 True。

        Returns:
            list[str]: 去重后的舰船名称列表，如 ['bogue', 'hermes', 'ranger']。
        """
        if ship_type.lower() not in ['cv', 'dd']:
            logger.warning(f'Invalid ship_type: {ship_type}')
            return []

        ship_type = ship_type.upper()
        filter_obj: Filter = globals()[f'COMMON_{ship_type}_FILTER']
        templates = globals()[f'TEMPLATE_COMMON_{ship_type}']
        command = self.config.task.command if hasattr(self.config, 'task') and self.config.task else 'GemsFarming'
        key = f'{command}.GemsFarming.Common{ship_type}Filter'
        default = self.config.__getattribute__(f'COMMON_{ship_type}_FILTER')

        while 1:
            filter_obj.load(string)
            common_cv = list(dict.fromkeys(
                [str(name[0]) for name in filter_obj.filter if name[0].upper() in templates]))
            if not common_cv:
                logger.warning(f'Invalid filter set: "{string}". Set to default filter.')
                string = default
                self.config.cross_set(keys=key, value=default)
                continue

            # 结束条件——过滤器解析成功
            if output:
                logger.attr('Filter sort', ' > '.join(common_cv))
            return common_cv

    def retirement_get_common_rarity_cv_in_page(self):
        """
        在当前页面中通过模板匹配查找普通稀有度航母。

        根据配置的预设（custom/any/eagle/指定航母）选择匹配模板，
        在缩放后的截图上进行模板匹配。

        Returns:
            Button | None: 匹配到的航母按钮，未找到返回 None。
        """
        preset = self.config.GemsFarming_CommonCV
        if preset in ['custom', 'any', 'eagle']:
            filter_string = self.config.GemsFarming_CommonCVFilter if preset == 'custom' else self.config.COMMON_CV_FILTER
            common_cv = self.get_common_ship_filter(filter_string, ship_type='cv', output=False)
            if self.config.GemsFarming_CommonCV == 'eagle' and 'hermes' in common_cv:
                common_cv.remove('hermes')
            logger.attr('Filter sort', ' > '.join(common_cv))
            for name in common_cv:
                template = globals()[f'TEMPLATE_{name.upper()}']
                sim, button = template.match_result(
                    resize(self.device.image, size=(1189, 669)))

                if sim > lower_template_match_similarity(self.config.COMMON_CV_THRESHOLD):
                    return Button(button=tuple(_ * 155 // 144 for _ in button.button), area=button.area,
                                  color=button.color,
                                  name=f'TEMPLATE_{name}_RETIRE')

            return None
        else:

            template = globals()[
                f'TEMPLATE_{self.config.GemsFarming_CommonCV.upper()}']
            sim, button = template.match_result(
                resize(self.device.image, size=(1189, 669)))

            if sim > lower_template_match_similarity(self.config.COMMON_CV_THRESHOLD):
                return Button(button=tuple(_ * 155 // 144 for _ in button.button), area=button.area, color=button.color,
                              name=f'TEMPLATE_{self.config.GemsFarming_CommonCV.upper()}_RETIRE')

            return None

    def retirement_get_common_rarity_cv(self, skip_first_screenshot=False):
        """
        在退役确认界面中滚动查找普通稀有度航母。

        从底部向顶部逐页滚动，通过模板匹配在每页中查找目标航母。
        如果滚动条消失或到达顶部则停止。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 False。

        Returns:
            Button | None: 找到的航母按钮（用于从退役列表中移除），未找到返回 None。
        """
        swipe_count = 0
        disappear_confirm = Timer(2, count=6)
        top_checked = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 尝试在当前页获取航母
            button = self.retirement_get_common_rarity_cv_in_page()
            if button is not None:
                return button

            # 等待滚动条出现
            if RETIRE_CONFIRM_SCROLL.appear(main=self):
                disappear_confirm.clear()
            else:
                disappear_confirm.start()
                if disappear_confirm.reached():
                    logger.warning('Scroll bar disappeared, stop')
                    break
                else:
                    continue

            if not top_checked:
                top_checked = True
                logger.info('Find common CV from bottom to top')
                RETIRE_CONFIRM_SCROLL.set_bottom(main=self)
                continue
            else:
                if RETIRE_CONFIRM_SCROLL.at_top(main=self):
                    logger.info('Scroll bar reached top, stop')
                    break
                # 向上翻页
                if swipe_count >= 7:
                    logger.info('Reached maximum swipes to find common CV')
                    break
                RETIRE_CONFIRM_SCROLL.prev_page(main=self)
                swipe_count += 1

        return button

    def keep_one_common_cv(self):
        """
        在退役确认界面中保留一艘普通航母，将其从退役列表中移除。

        通过滚动查找并选中一艘普通航母，避免 GemsFarming 全部退役。
        """
        logger.info('Keep one common CV')
        button = self.retirement_get_common_rarity_cv()
        if button is not None:
            self._retire_select_one(button)
            self._have_kept_cv = True
        logger.info('Keep one common CV end')
