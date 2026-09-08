"""
舰船强化系统。

提供船坞中舰船装备强化的完整流程，包括按舰船类型分类强化、
推荐材料选择、强化确认、失败重试等操作。通过 DFA（确定性有限自动机）
状态机模式驱动强化流程，自动处理战斗中、无材料等异常情况。

当退役模式为 enhance 时，优先执行强化；强化完成或失败后
可回退到退役流程。
"""

from random import choice

import cv2

import module.config.server as server
from module.base.timer import Timer
from module.base.utils import area_pad
from module.combat.assets import GET_ITEMS_1
from module.exception import GameStuckError, ScriptError
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.retire.assets import *
from module.retire.dock import Dock

VALID_SHIP_TYPES = ['dd', 'ss', 'cl', 'ca', 'bb', 'cv', 'repair', 'others']
if server.server != 'jp':
    OCR_DOCK_AMOUNT = DigitCounter(
        DOCK_AMOUNT, letter=(255, 255, 255), threshold=192)
else:
    OCR_DOCK_AMOUNT = DigitCounter(
        DOCK_AMOUNT, letter=(201, 201, 201), threshold=192)


class Enhancement(Dock):
    """舰船强化处理器。

    继承 Dock 类，在船坞页面中执行装备强化操作。
    使用 DFA 状态机模式管理强化流程，支持按舰船类型
    分类处理、推荐材料自动选择、强化失败后的自动翻页重试。

    Attributes:
        _retire_amount (property): 根据退役模式配置计算的退役数量上限。
    """
    @property
    def _retire_amount(self):
        if self.config.Retirement_RetireMode == 'one_click_retire':
            return 3000
        if self.config.Retirement_RetireMode == 'old_retire':
            if self.config.OldRetire_RetireAmount == 'retire_all':
                return 3000
            if self.config.OldRetire_RetireAmount == 'retire_10':
                return 10
        return 3000

    @property
    def _retire_keep_common_cv(self):
        """
        Returns:
            str: "any" or specific ship name, or empty string if GemsFarming is not enabled
        """
        if not self.config.is_task_enabled('GemsFarming'):
            return ''
        return self.config.cross_get('GemsFarming.GemsFarming.CommonCV', default='any')

    def _enhance_enter(self, favourite=False, ship_type=None):
        """
        Pages:
            in: page_dock
            out: page_ship_enhance

        Returns:
            bool: False with filter applied resulting
                  in empty dock.
                  Otherwise true with at least 1 card
                  available to be picked.
        """
        if favourite:
            self.dock_favourite_set(enable=True, wait_loading=False)

        if ship_type is not None:
            ship_type = str(ship_type)
            self.dock_filter_set(extra='enhanceable', index=ship_type)
        else:
            self.dock_filter_set(extra='enhanceable')

        if self.appear(DOCK_EMPTY, offset=(30, 30)):
            return False

        return self.dock_enter_first()

    def _enhance_quit(self):
        """
        Pages:
            in: page_ship_enhance
            out: page_dock
        """
        self.ui_back(DOCK_CHECK)
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_filter_set()

    def _enhance_confirm(self, skip_first_screenshot=True):
        """
        Pages:
            in: EQUIP_CONFIRM
            out: page_ship_enhance, without info_bar
        """

        confirm_timer = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(EQUIP_CONFIRM, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear(GET_ITEMS_1, interval=2):
                self.device.click(GET_ITEMS_1_RETIREMENT_SAVE)
                self.interval_reset(ENHANCE_CONFIRM)
                confirm_timer.reset()
                continue

            # End
            if self.appear(ENHANCE_CONFIRM, offset=(30, 30)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _enhance_get_deselect_cv(self, first_slot=False):
        """
        Args:
            first_slot: True to check in first slot only, False to check in all slots

        Returns:
            Button | None: Button of common rarity CV to de-select, or None if not found
        """
        cv = self._retire_keep_common_cv
        if not cv:
            return None
        dict_template = {
            'bogue': TEMPLATE_ENHANCE_BOGUE,
            'hermes': TEMPLATE_ENHANCE_HERMES,
            'langley': TEMPLATE_ENHANCE_LANGLEY,
            'ranger': TEMPLATE_ENHANCE_RANGER,
        }
        if cv != 'any':
            dict_template = {cv: dict_template[cv]}

        if first_slot:
            # outer pad 22 px reaches slot edge
            area = area_pad(EMPTY_ENHANCE_SLOT_PLUS.area, pad=-22)
        else:
            area = ENHANCE_AREA_FULL.area
        image = self.image_crop(area, copy=False)

        for cv, template in dict_template.items():
            sim, button = template.match_result(image)
            if sim > 0.85:
                button = button.move(area[:2])
                return Button(area=button.area, color=button.color, button=button.area,
                              name=f'TEMPLATE_ENHANCE_{cv.upper()}_RETIRE')

        return None

    def _enhance_deselect_cv(self):
        """
        De-select common rarity CV from enhance material slots
        """
        cv = self._enhance_get_deselect_cv()
        if cv is None:
            return

        logger.info(f'Enhance de-select common CV')
        # get cv slot, outer pad from matched center
        area = cv.area
        center = ((area[0] + area[2]) / 2, (area[1] + area[3]) / 2)
        radius = abs(EMPTY_ENHANCE_SLOT_PLUS.area[3] - EMPTY_ENHANCE_SLOT_PLUS.area[1]) / 2
        radius = radius + 22
        search = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)

        self.interval_clear(ENHANCE_RECOMMEND, interval=2)
        EMPTY_ENHANCE_SLOT_PLUS.ensure_template()
        for _ in self.loop():
            image = self.image_crop(search, copy=False)
            result = cv2.matchTemplate(EMPTY_ENHANCE_SLOT_PLUS.image, image, cv2.TM_CCOEFF_NORMED)
            _, similarity, _, _ = cv2.minMaxLoc(result)
            if similarity > 0.85:
                logger.info(f'Enhance de-select common CV done')
                break

            if self.appear(ENHANCE_RECOMMEND, offset=(5, 5), interval=2):
                self.device.click(cv)
                continue

    def _enhance_choose(self, ship_count, skip_first_screenshot=True):
        """
        Refactor the implementation.
        Divided the enhancement process into
        several state functions. Use a DFA method
        to call those functions according to
        current state. Each state corresponds to
        a function with the same name.

        Pages:
            in: page_ship_enhance
            out: page_ship_enhance

        Args:
            ship_count (int): ship_count, must be
            non-zero positive integer

        Returns:
            True if able to enhance otherwise False
            Always paired with current ship_count
        """
        need_to_skip: bool = False

        def state_enhance_check():
            # Check the base case, switch to ready if enhancement can continue
            nonlocal need_to_skip
            need_to_skip = False
            if ship_count <= 0:
                logger.info(
                    '[退役-强化] 已达到最大检查次数，退出当前分类')
                return "state_enhance_exit"
            if not self.equip_side_navbar_ensure(bottom=4):
                return "state_enhance_check"

            self.wait_until_appear(ENHANCE_RECOMMEND, offset=(
                5, 5), skip_first_screenshot=True)
            return "state_enhance_ready"

        def state_enhance_ready():
            # Wait until ENHANCE_RECOMMEND appears
            if self.appear_then_click(ENHANCE_RECOMMEND, offset=(5, 5), interval=0.3):
                logger.info('按推荐设置强化材料')
                return "state_enhance_recommend"

            return "state_enhance_ready"

        def state_enhance_recommend():
            # Judge if enhance material appeared
            if not EMPTY_ENHANCE_SLOT_PLUS.match(self.device.image, offset=(20, 20)):
                if self._retire_keep_common_cv:
                    # 若第一格为普通 CV 且第二格为空，视为无材料，
                    # 避免"推荐→反选"死循环；第二格在左侧 92px 处
                    if EMPTY_ENHANCE_SLOT_PLUS.match(self.device.image, offset=(72, -20, 112, 20)) \
                            and self._enhance_get_deselect_cv(first_slot=True):
                        logger.info('[退役-强化] 仅 1 个普通 CV 材料，视为无强化材料')
                        logger.info('[退役-强化] 强化失败，滑动到下一艘舰船（如可行）')
                        return "state_enhance_fail"
                    # 反选已填充的普通 CV
                    self._enhance_deselect_cv()

                logger.info('找到材料，尝试强化...')
                return "state_enhance_attempt"
            elif self.info_bar_count():
                logger.info('未找到强化材料')
                logger.info('[退役-强化] 强化失败，滑动到下一艘舰船（如可行）')
                return "state_enhance_fail"

            return "state_enhance_ready"

        def state_enhance_attempt():
            # Wait until ENHANCE_CONFIRM appears
            if (self.appear_then_click(ENHANCE_CONFIRM, offset=(5, 5), interval=0.3)
                    or self.appear(EQUIP_CONFIRM, offset=(30, 30))
                    or self.info_bar_count()
                    or self.handle_popup_confirm('ENHANCE')):
                return "state_enhance_confirm"

            return "state_enhance_attempt"

        def state_enhance_confirm():
            # Succeeded if EQUIP_CONFIRM appeared, otherwise failed
            if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                logger.info('强化成功')
                self._enhance_confirm()
                return "state_enhance_success"
            elif self.info_bar_count():
                logger.info(
                    '[退役-强化] 强化不可行，舰船当前在战斗中，滑动到下一艘舰船（如可行）')
                nonlocal need_to_skip
                need_to_skip = True
                return "state_enhance_fail"
            elif self.handle_popup_confirm('ENHANCE'):
                logger.info('尝试临时舰船')
                return "state_enhance_confirm"

            return "state_enhance_attempt"

        def state_enhance_fail():
            # Avoid a misjudgement caused by broken network
            if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                return "state_enhance_confirm"

            # Try to swipe to next
            if self.equip_view_next(check_button=ENHANCE_RECOMMEND):
                if not need_to_skip:
                    nonlocal ship_count
                    ship_count -= 1
                return "state_enhance_check"
            else:
                # Avoid a misjudgement caused by broken network
                if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                    return "state_enhance_confirm"
                else:
                    logger.info('滑动失败，退出当前分类')
                    return "state_enhance_exit"

        def state_enhance_success():
            return True

        def state_enhance_exit():
            return False

        state = "state_enhance_check"
        state_list = []
        while isinstance(state, str):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            logger.info(f'调用状态函数: {state}')

            if state == "state_enhance_check":
                # Avoid too_many_click exception caused by multiple tries without material
                if state_list[-2:] == ["state_enhance_recommend", "state_enhance_fail"]:
                    while self.device.click_record and (self.device.click_record[-1] in ['ENHANCE_RECOMMEND', 'EQUIP_SWIPE', 'SHIP_SWIPE']):
                        self.device.click_record.pop()
                # Avoid too_many_click exception caused by enhancement failure on in-battle ships
                elif state_list[-3:] == ["state_enhance_attempt", "state_enhance_confirm", "state_enhance_fail"]:
                    while self.device.click_record and (self.device.click_record[-1] in ['ENHANCE_RECOMMEND', 'EQUIP_SWIPE', 'SHIP_SWIPE', 'ENHANCE_CONFIRM']):
                        self.device.click_record.pop()
                state_list.clear()
            state_list.append(state)
            if len(state_list) > 30:
                logger.critical(f'[退役] 状态机循环次数过多: {state_list}')
                raise GameStuckError('状态机循环次数过多')

            try:
                state = locals()[state]()
            except KeyError as e:
                logger.warning(f'未知的状态函数: {state}')
                raise ScriptError(f'未知的状态函数: {state}')

        return state, ship_count

    def enhance_ships(self, favourite=None):
        """
        Enhance target ships by specified order
        of types listed in ENHANCE_ORDER_STRING

        Invalid types are treated as requesting
        from AzurPilot to choose a valid one at random

        Pages:
            in: page_dock
            out: page_dock

        Args:
            favourite (bool):

        Returns:
            int: total enhanced
        """
        if favourite is None:
            favourite = self.config.Enhance_ShipToEnhance == 'favourite'

        logger.hr('按类型强化')
        total = 0

        # Process ENHANCE_ORDER_STRING if any into ship_types
        if self.config.Enhance_Filter is not None:
            ship_types = [s.strip().lower()
                          for s in self.config.Enhance_Filter.split('>')]
            ship_types = list(filter(''.__ne__, ship_types))
            if len(ship_types) == 0:
                ship_types = [None]
        else:
            ship_types = [None]
        logger.attr('强化顺序', ship_types)

        # Process available ship types for choice randomization
        # Removing types that have already been specified by
        # ENHANCE_ORDER_STRING
        available_ship_types = VALID_SHIP_TYPES.copy()
        [available_ship_types.remove(s)
         for s in ship_types if s in available_ship_types]

        for ship_type in ship_types:
            # None check, do not execute if is None
            # Otherwise, select a type at random since
            # user has specified an unrecognized type
            if ship_type is not None and ship_type not in VALID_SHIP_TYPES:
                if len(available_ship_types) == 0:
                    logger.info(
                        '[退役-强化] 无可选舰船类型，跳过本次迭代')
                    continue
                ship_type = choice(available_ship_types)
                available_ship_types.remove(ship_type)

            logger.info(f'收藏={favourite}, 舰船类型={ship_type}')

            # Continue if at least 1 CARD_GRID is selectable
            # otherwise skip to next ship type
            if not self._enhance_enter(favourite=favourite, ship_type=ship_type):
                logger.hr(f'[退役-强化] 船坞为空，舰船类型: {ship_type}')
                continue

            current_count = self.config.Enhance_CheckPerCategory
            while 1:
                choose_result, current_count = self._enhance_choose(
                    ship_count=current_count)
                if not choose_result:
                    break
                total += 10
                if total >= self._retire_amount:
                    break
            self.ui_back(DOCK_CHECK)

        self._enhance_quit()
        return total

    def _enhance_handler(self):
        """
        Pages:
            in: RETIRE_APPEAR
            out:

        Returns:
            tuple(int, int): (enhance turn count, remaining dock amount)

        Pages:
            in: DOCK_CHECK
            out: the page before retirement popup
        """
        total = self.enhance_ships()
        _, remain, _ = OCR_DOCK_AMOUNT.ocr(self.device.image)

        self.dock_quit()
        self.config.DOCK_FULL_TRIGGERED = True

        return total, remain
