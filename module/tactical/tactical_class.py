from datetime import datetime

import module.config.server as server
from module.base.button import Button, ButtonGrid
from module.base.filter import Filter
from module.base.timer import Timer
from module.base.utils import *
from module.combat.level import LevelOcr
from module.config.utils import get_server_next_update
from module.exception import ScriptError
from module.handler.assets import GET_MISSION, MISSION_POPUP_ACK, MISSION_POPUP_GO, POPUP_CANCEL, POPUP_CONFIRM
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.ocr.ocr import DigitCounter, Duration, Ocr
from module.retire.assets import DOCK_CHECK, DOCK_EMPTY, SHIP_CONFIRM
from module.retire.dock import CARD_GRIDS, CARD_LEVEL_GRIDS, Dock
from module.tactical.assets import *
from module.ui.assets import (BACK_ARROW, REWARD_CHECK, REWARD_GOTO_TACTICAL, TACTICAL_CHECK)
from module.ui.page import page_reward
from module.ui_white.assets import REWARD_2_WHITE, REWARD_GOTO_TACTICAL_WHITE

SKILL_GRIDS = ButtonGrid(origin=(315, 140), delta=(621, 132), button_shape=(621, 119), grid_shape=(1, 3), name='SKILL')
if server.server != 'jp':
    SKILL_LEVEL_GRIDS = SKILL_GRIDS.crop(area=(406, 98, 618, 116), name='EXP')
else:
    SKILL_LEVEL_GRIDS = SKILL_GRIDS.crop(area=(406, 98, 621, 118), name='EXP')


class ExpOnBookSelect(DigitCounter):
    def pre_process(self, image):
        # 图像格式类似 `NEXT:1900+500/5800`，其中 500 为绿色，其余为白色

        # 查找绿色字母
        hsv = rgb2hsv(image)
        h = (60, 180)
        s = (50, 100)
        v = (50, 100)
        lower = (h[0], s[0], v[0])
        upper = (h[1], s[1], v[1])
        green = np.mean(cv2.inRange(hsv, lower, upper), axis=0)
        # 转换为灰度图
        r, g, b = cv2.split(image)
        image = cv2.max(cv2.max(r, g), b)
        # 将 `+500` 部分涂黑
        matched = np.where(green > 0.5)[0]
        if len(matched):
            image[:, matched[0] - 8:matched[-1] + 2] = 0

        image = 255 - image

        # 去除左侧 `Next:` 文字
        if server.server == 'en':
            # EN 服加粗的 `Next:`
            return image_left_strip(image, threshold=105, length=46)
        if server.server == 'jp':
            # JP 服较宽的 `Next:`
            return image_left_strip(image, threshold=105, length=55)
        return image_left_strip(image, threshold=105, length=42)

    def after_process(self, result):
        result = super().after_process(result)

        if result.endswith("580"):
            new = f'{result[:-3]}5800'
            logger.info(f'ExpOnBookSelect result {result} is revised to {new}')
            result = new
        if '/' not in result:
            for exp in [5800, 4400, 3200, 2200, 1400, 800, 400, 200, 100]:
                if res := re.match(rf'^(\d+){exp}$', result):
                    # 10005800 -> 1000/5800
                    new = f'{res.group(1)}/{exp}'
                    logger.info(f'ExpOnBookSelect result {result} is revised to {new}')
                    result = new
                    break

        return result


class ExpOnSkillSelect(Ocr):
    def pre_process(self, image):
        # 转换为灰度图
        r, g, b = cv2.split(image)
        image = cv2.max(cv2.max(r, g), b)

        image = 255 - image

        # 去除左侧 `Next:` 文字
        if server.server == 'en':
            # EN 服加粗的 `Next:`
            return image_left_strip(image, threshold=105, length=46)
        if server.server == 'jp':
            # JP 服较宽的 `Next:`
            return image_left_strip(image, threshold=105, length=53)
        return image_left_strip(image, threshold=105, length=42)


SKILL_EXP = ExpOnBookSelect(buttons=OCR_SKILL_EXP)
BOOKS_GRID = ButtonGrid(origin=(213, 292), delta=(147, 117), button_shape=(98, 98), grid_shape=(6, 2))
BOOK_FILTER = Filter(
    regex=re.compile(
        '(same)?'
        '(red|blue|yellow)?'
        '-?'
        '(t[1234])?'
    ),
    attr=('same_str', 'genre_str', 'tier_str'),
    preset=('first',)
)


class Book:
    color_genre = {
        1: (214, 69, 74),  # 攻击，红色
        2: (115, 178, 255),  # 防御，蓝色
        3: (247, 190, 99),  # 辅助，黄色
    }
    genre_name = {
        1: 'Red',  # 攻击，红色
        2: 'Blue',  # 防御，蓝色
        3: 'Yellow',  # 辅助，黄色
    }
    color_tier = {
        1: (104, 181, 238),  # T1，蓝色
        2: (151, 129, 203),  # T2，紫色
        3: (235, 208, 120),  # T3，金色
        4: (225, 181, 212),  # T4，彩虹
    }
    exp_tier = {
        0: 0,
        1: 100,
        2: 300,
        3: 800,
        4: 1500,
    }

    def __init__(self, image, button):
        """
        根据教材图像识别其类型、等级和经验加成。

        Args:
            image (np.ndarray): 完整截图
            button (Button): 教材对应的按钮区域
        """
        image = crop(image, button.area, copy=False)
        # 20250814 UI 更新后，输入物品图像大小为 (64, 64)，但默认
        # 输入为 (98, 98)，如果不放大图像，get_color 结果为 0，会输出 'BookUnknownTn'
        if image_size(image) < (98, 98):
            image = resize(image, (98, 98))
        self.button = button

        # 在 40 张随机截图的测试中，
        # 阈值范围 50-70 时全部通过，
        # 但不能超过 75，否则彩虹品质会被误识别为紫色
        self.genre = 0
        color = get_color(image, (65, 35, 72, 42))
        for key, value in self.color_genre.items():
            if color_similar(color1=color, color2=value, threshold=50):
                self.genre = key

        self.tier = 0
        color = get_color(image, (83, 61, 92, 70))
        for key, value in self.color_tier.items():
            if color_similar(color1=color, color2=value, threshold=50):
                self.tier = key

        color = color_similarity_2d(crop(image, (15, 0, 97, 13), copy=False), color=(148, 251, 99))
        self.exp = np.sum(color > 221) > 50

        self.valid = bool(self.genre and self.tier)
        self.genre_str = self.genre_name.get(self.genre, "unknown")
        self.tier_str = f'T{self.tier}' if self.tier else 'Tn'
        self.same_str = 'same' if self.exp else 'unknown'

        factor = 1 if not self.exp else 1.5 if self.tier < 4 else 2
        self.exp_value = self.exp_tier[self.tier] * factor

    def check_selected(self, image):
        """
        检查该教材是否已被选中。

        Args:
            image (np.ndarray): 截图
        """
        area = self.button.area
        check_area = (area[0], area[3] + 2, area[2], area[3] + 4)
        im = rgb2gray(crop(image, check_area, copy=False))
        return np.mean(im) > 127

    def __str__(self):
        # 示例：Red_T3_Exp
        text = f'{self.genre_str}_{self.tier_str}'
        if self.exp:
            text += '_Exp'
        return text


class RewardTacticalClass(Dock):
    books: SelectedGrids
    tactical_finish = []
    dock_select_index = 0

    def _tactical_books_get(self, skip_first_screenshot=True):
        """
        获取教材列表。处理加载状态，最多等待 15 次。
        当 TACTICAL_CLASS_START 出现时，游戏可能卡在加载中，等待并重试检测。
        如果持续加载则抛出 ScriptError。

        Returns:
            SelectedGrids: 可用教材列表，如果不在 TACTICAL_CLASS_START 则返回 False

        Pages:
            in: TACTICAL_CLASS_START
            out: TACTICAL_CLASS_START
        """
        prev = SelectedGrids([])
        for n in range(1, 16):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self.handle_info_bar()  # 在启航典礼委托中获得舰船时会出现 info_bar
            if not self.appear(TACTICAL_CLASS_START, offset=(30, 30)):
                logger.info('Not in TACTICAL_CLASS_START anymore, exit')
                return False

            books = SelectedGrids([Book(self.device.image, button) for button in BOOKS_GRID.buttons]).select(valid=True)
            self.books = books
            logger.attr('Book_count', books.count)
            logger.attr('Books', str(books))

            # End
            if books and books.count == prev.count:
                return books
            prev = books
            if n % 3 == 0:
                self.device.sleep(3)

        logger.warning('No book found.')
        raise ScriptError('No book found, after 15 attempts.')

    def _tactical_book_select(self, book, skip_first_screenshot=True):
        """
        选中屏幕上指定的教材。必要时更新当前截图。

        Args:
            book (Book): 目标教材对象
            skip_first_screenshot (bool): 是否跳过首次截图
        """
        logger.info(f'Book select {book}')
        interval = Timer(2, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            if book.check_selected(self.device.image):
                break

            if interval.reached():
                self.device.click(book.button)
                interval.reset()
                continue

    def _tactical_books_filter_exp(self):
        """
        根据当前战术技能的进度，从 self.books 中过滤掉会导致经验溢出的教材。
        """
        # 读取的 'current' 和 'remain' 不够精确
        # 因为第一本教材的经验值已计入其中
        current, remain, total = SKILL_EXP.ocr(self.device.image)

        # 即将达到10级满级，需要移除特定教材以防止经验浪费
        if total == 5800:
            logger.info('About to reach level 10; will remove '
                        'detected books based on actual '
                        f'progress: {current}/{total}; {remain}')

            def filter_exp_func(book):
                # 保留至少一本非 T1 的加成教材（如果别无选择）
                if book.exp_value == 100:
                    return True

                # 获取对应等级教材允许的经验溢出量（如果已启用）
                overflow = 0
                if self.config.ControlExpOverflow_Enable:
                    overflow = getattr(self.config, f'ControlExpOverflow_T{book.tier}Allow')

                # 如果当前经验加上教材经验超过总量（加溢出量），则移除该教材
                return (current + book.exp_value) <= (total + overflow)

            before = self.books.count
            self.books = SelectedGrids([book for book in self.books if filter_exp_func(book)])
            logger.attr('Filtered', before - self.books.count)
            logger.attr('Books', str(self.books))

    def _is_current_skill_max(self, skip_first_screenshot=True):
        """
        检测当前选中的技能是否已满级（基于教材选择界面的经验 OCR）。
        方法内部会自行截图，不依赖调用方是否已更新 self.device.image。

        Returns:
            bool: 如果当前技能已满级返回 True
        """
        if not skip_first_screenshot:
            self.device.screenshot()
        try:
            current, _, total = SKILL_EXP.ocr(self.device.image)
            if total > 0 and current >= total:
                logger.info(f'Current skill is max level: {current}/{total}')
                return True
        except Exception as e:
            logger.warning(f'Failed to check skill max level: {e}')
        return False

    def _wait_until_appear(self, button, offset, attempts=5):
        for _ in range(attempts):
            self.device.screenshot()
            if self.appear(button, offset=offset):
                return True
            self.device.sleep((0.3, 0.5))
        return False

    def _return_to_tactical_page(self):
        self.device.click(BACK_ARROW)
        self.device.sleep((0.3, 0.5))

    def _try_switch_to_next_skill(self):
        """
        当前技能已满级时，尝试切换到同舰娘的下一个非满级技能。

        进入时在 TACTICAL_CLASS_START，立即点击取消回到技能选择界面 (SKILL_CONFIRM)，
        查找下一个未满级技能并确认后返回教材选择界面 (TACTICAL_CLASS_START)。

        Returns:
            bool: 是否成功切换到下一个技能

        Pages:
            in: TACTICAL_CLASS_START (点击取消后进入 SKILL_CONFIRM)
            out: TACTICAL_CLASS_START (if success) or SKILL_CONFIRM (if no skill found)
        """
        logger.hr('Try switch to next skill', level=2)
        # 取消当前教材选择，回到技能选择界面
        self.device.click(TACTICAL_CLASS_CANCEL)
        self.device.sleep((0.5, 1.0))

        # 等待技能选择界面加载
        if not self._wait_until_appear(SKILL_CONFIRM, offset=(20, 20)):
            logger.warning('Failed to return to SKILL_CONFIRM after cancel')
            return False

        # 寻找下一个非满级技能
        selected_skill = self.find_not_full_level_skill(skip_first_screenshot=True)
        if selected_skill is None:
            logger.info('No other non-max skill available for this ship, return to tactical page')
            self._return_to_tactical_page()
            return False

        # 选中并确认新技能
        logger.info('Switching to next non-max skill')
        self._tactical_skill_select(selected_skill)
        self.device.click(SKILL_CONFIRM)

        # 等待教材选择界面加载
        if self._wait_until_appear(TACTICAL_CLASS_START, offset=(30, 30)):
            logger.info('Entered TACTICAL_CLASS_START after skill switch')
            return True
        logger.warning('Failed to enter TACTICAL_CLASS_START after skill switch')
        self._return_to_tactical_page()
        return False

    def _tactical_books_choose(self):
        """
        根据配置选择战术教材。

        Returns:
            int: 是否成功选择教材

        Pages:
            in: TACTICAL_CLASS_START
            out: Unknown, may TACTICAL_CLASS_START, page_tactical, or _tactical_animation_running
        """
        logger.hr('Tactical books choose', level=2)
        MAX_SWITCH_RETRIES = 3
        for retry in range(MAX_SWITCH_RETRIES + 1):
            if not self._tactical_books_get():
                return False

            self.device.click_record_clear()
            # 确保第一本教材被选中
            # 对于较慢的电脑，选中状态可能已改变
            first = self.books[0]
            self._tactical_book_select(first)

            # 应用经验溢出过滤，会修改 self.books
            self._tactical_books_filter_exp()

            # 应用配置过滤器，不修改 self.books
            BOOK_FILTER.load(self.config.Tactical_TacticalFilter)
            books = BOOK_FILTER.apply(self.books.grids)
            logger.attr('Book_sort', ' > '.join([str(book) for book in books]))

            # 如果有可用教材则选择，否则检测是否因为技能已满级
            if not books:
                # 无教材可选时，检测是否因为技能已满级（受 SkillAutoSwitch 配置控制）
                if not self.config.Tactical_SkillAutoSwitch:
                    break
                if retry >= MAX_SWITCH_RETRIES:
                    logger.warning('Max skill switch retries reached')
                    break
                if not self._is_current_skill_max(skip_first_screenshot=True):
                    break
                logger.info('No books because skill is max, try switch to next skill')
                if not self._try_switch_to_next_skill():
                    break
                logger.info('Switched to next skill, re-enter book choose')
                continue

            book = books[0]
            if str(book) != 'first':
                self._tactical_book_select(book)
            else:
                logger.info('Choose first book')
                self._tactical_book_select(first)
            logger.info(f'_tactical_books_choose -> {TACTICAL_CLASS_START}')
            self.device.click(TACTICAL_CLASS_START)
            return True

        logger.info('Cancel tactical')
        logger.info(f'_tactical_books_choose -> {TACTICAL_CLASS_CANCEL}')
        self.device.click(TACTICAL_CLASS_CANCEL)
        return True

    def handle_rapid_training(self):
        """
        处理急速训练按钮。

        Returns:
            bool: 是否处理了急速训练
        """
        slot = self.config.Tactical_RapidTrainingSlot
        if slot == 'slot_1':
            slot = 0
        elif slot == 'slot_2':
            slot = 1
        elif slot == 'slot_3':
            slot = 2
        elif slot == 'slot_4':
            slot = 3
        else:
            # do_not_use
            return False

        offset = (slot * 220 - 20, -20, slot * 220 + 20, 20)
        if self.appear(RAPID_TRAINING, offset=offset, interval=1):
            self.device.click(RAPID_TRAINING)
            # 清除间隔计时器以便快速进入教材选择
            self.interval_clear(TACTICAL_CLASS_START, interval=2)
            return True

        return False

    def _tactical_get_finish(self):
        """获取战术学院的完成时间。"""
        logger.hr('Tactical get finish')
        grids = ButtonGrid(
            origin=(421, 596), delta=(223, 0), button_shape=(139, 27), grid_shape=(4, 1), name='TACTICAL_REMAIN')

        is_running = [self.image_color_count(button, color=(148, 255, 99), count=50) for button in grids.buttons]
        logger.info(f'Tactical status: {["running" if s else "empty" for s in is_running]}')

        buttons = [b for b, s in zip(grids.buttons, is_running) if s]
        ocr = Duration(buttons, letter=(148, 255, 99), name='TACTICAL_REMAIN')
        remains = ocr.ocr(self.device.image)
        remains = remains if isinstance(remains, list) else [remains]

        now = datetime.now()
        self.tactical_finish = [(now + remain).replace(microsecond=0) for remain in remains if remain.total_seconds()]
        logger.info(f'Tactical finish: {[str(f) for f in self.tactical_finish]}')
        return self.tactical_finish

    def _handle_tactical_add_new_student(self, study_finished):
        if study_finished:
            return False
        if not self.appear(TACTICAL_CHECK, offset=(20, 20)):
            return False
        if not self.appear_then_click(ADD_NEW_STUDENT, offset=(800, 20), interval=1):
            return False

        self.interval_reset([TACTICAL_CHECK, RAPID_TRAINING])
        self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION, DOCK_CHECK, SKILL_CONFIRM])
        return True

    def _handle_tactical_finish(self, book_empty, empty_confirm):
        # sometimes you have TACTICAL_CHECK without black-blurred background
        # TACTICAL_CLASS_CANCEL and TACTICAL_CHECK appears
        if not self.appear(TACTICAL_CHECK, offset=(20, 20), interval=2) \
                or self.appear(TACTICAL_CLASS_START, offset=(20, 20)):
            empty_confirm.reset()
            return False, False

        self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION])
        if book_empty:
            self.device.click(BACK_ARROW)
            self.interval_reset(TACTICAL_CHECK)
            return True, False
        if self._tactical_get_finish():
            self.device.click(BACK_ARROW)
            self.interval_reset(TACTICAL_CHECK)
            empty_confirm.reset()
            return True, True

        self.interval_clear(TACTICAL_CHECK)
        if empty_confirm.reached():
            self.device.click(BACK_ARROW)
            empty_confirm.reset()
            return True, True
        return False, False

    def _handle_tactical_popups(self):
        if self.appear_then_click(REWARD_2, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_2_WHITE)
            return True, False
        if self.appear_then_click(REWARD_2_WHITE, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_2)
            return True, False
        if self.appear_then_click(REWARD_GOTO_TACTICAL, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_GOTO_TACTICAL_WHITE)
            return True, False
        if self.appear_then_click(REWARD_GOTO_TACTICAL_WHITE, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_GOTO_TACTICAL)
            return True, False
        if self.ui_main_appear_then_click(page_reward, interval=3):
            return True, False
        if self.handle_popup_confirm('TACTICAL'):
            self.interval_reset([BOOK_EMPTY_POPUP])
            return True, False
        if self.handle_urgent_commission():
            # Only one button in the middle, when skill reach max level.
            return True, self.config.Tactical_SkillAutoSwitch
        if self.ui_page_main_popups():
            self.interval_reset([BOOK_EMPTY_POPUP])
            return True, False
        # Similar to handle_mission_popup_ack, but battle pass item expire popup has a different ACK button
        if self.appear(MISSION_POPUP_GO, offset=self._popup_offset, interval=2):
            self.device.click(MISSION_POPUP_ACK)
            return True, False
        return False, False

    def _handle_tactical_books_start(self):
        if not self.appear(TACTICAL_CLASS_START, offset=(30, 30), interval=2):
            return False, False

        study_finished = False
        if self._tactical_books_choose():
            self.dock_select_index = 0
            self.interval_reset([TACTICAL_CLASS_START, BOOK_EMPTY_POPUP])
            self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION])
        else:
            study_finished = True
        return True, study_finished

    def _handle_tactical_dock(self):
        if not self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
            return False, False
        if self.dock_selected():
            # When you click a ship from page_main -> dock,
            # this ship will be selected default in tactical dock,
            # so we need click BACK_ARROW to clear selected state
            logger.info('Having pre-selected ship in dock, re-enter')
            self.device.click(BACK_ARROW)
            self.interval_reset([BOOK_EMPTY_POPUP, DOCK_CHECK], interval=3)
            return True, False

        study_finished = False
        # If not enable or can not fina a suitable ship
        if not self.config.AddNewStudent_Enable:
            logger.info('Not going to learn skill but in dock, close it')
            study_finished = True
            self.device.click(BACK_ARROW)
        elif not self.select_suitable_ship():
            study_finished = True
            self.device.click(BACK_ARROW)
        # reset DOCK_CHECK to Timer(3)
        self.interval_timer.pop(DOCK_CHECK.name, None)
        self.interval_reset([BOOK_EMPTY_POPUP, DOCK_CHECK], interval=3)
        return True, study_finished

    def _handle_tactical_skill_confirm(self, pending_skill_auto_switch):
        if not self.appear(SKILL_CONFIRM, offset=(20, 20), interval=3):
            return False, False, pending_skill_auto_switch

        study_finished = False
        if pending_skill_auto_switch or self.config.AddNewStudent_Enable:
            pending_skill_auto_switch = False
            if not self._tactical_skill_choose():
                study_finished = True
                self.device.click(BACK_ARROW)
        else:
            logger.info('Not going to learn skill but having SKILL_CONFIRM, close it')
            study_finished = True
            self.device.click(BACK_ARROW)
        self.interval_reset([BOOK_EMPTY_POPUP, SKILL_CONFIRM], interval=3)
        return True, study_finished, pending_skill_auto_switch

    def _handle_tactical_meta(self):
        if not self.appear(TACTICAL_META, offset=(200, 20), interval=3):
            return False

        logger.info('META skill found, exit')
        self.device.click(BACK_ARROW)
        # Select the next ship in `select_suitable_ship()`
        self.dock_select_index += 1
        # Avoid exit tactical between exiting meta skill to select new ship
        self.interval_reset([TACTICAL_CHECK, BOOK_EMPTY_POPUP])
        self.interval_clear(ADD_NEW_STUDENT)
        return True

    def _handle_tactical_book_empty(self):
        if not self.appear(BOOK_EMPTY_POPUP, offset=(20, 20), interval=3):
            return False

        self.device.click(BOOK_EMPTY_POPUP)
        return True

    def tactical_class_receive(self, skip_first_screenshot=True):
        """
        收取战术学院奖励并填充教材。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            bool: 是否已领取奖励

        Pages:
            in: page_reward, TACTICAL_CLASS_START
            out: page_reward
        """
        logger.hr('Tactical class receive', level=1)
        received = False
        study_finished = not self.config.AddNewStudent_Enable
        pending_skill_auto_switch = False
        book_empty = False
        # 战术卡片加载较慢，通过计时器确认是否真的为空
        empty_confirm = Timer(0.6, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if received and self.appear(REWARD_CHECK, offset=(20, 20)):
                break

            if self._handle_tactical_add_new_student(study_finished):
                continue
            if self.handle_rapid_training():
                self.interval_reset(TACTICAL_CHECK)
                self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION, DOCK_CHECK, SKILL_CONFIRM])
                continue

            # 获取完成时间
            # 有时 TACTICAL_CHECK 出现但没有黑色模糊背景
            # 此时 TACTICAL_CLASS_CANCEL 和 TACTICAL_CHECK 同时显示
            handled, finished = self._handle_tactical_finish(book_empty, empty_confirm)
            if handled:
                received = received or finished
                continue

            handled, auto_switch = self._handle_tactical_popups()
            if handled:
                pending_skill_auto_switch = pending_skill_auto_switch or auto_switch
                continue

            handled, finished = self._handle_tactical_books_start()
            if handled:
                study_finished = study_finished or finished
                continue

            # 2025.05.29 进入船坞时游戏弹出皮肤功能提示
            if self.handle_game_tips():
                return True

            handled, finished = self._handle_tactical_dock()
            if handled:
                study_finished = study_finished or finished
                continue

            handled, finished, pending_skill_auto_switch = self._handle_tactical_skill_confirm(pending_skill_auto_switch)
            if handled:
                study_finished = study_finished or finished
                continue
            if self._handle_tactical_meta():
                continue
            if self._handle_tactical_book_empty():
                study_finished = True
                received = True
                book_empty = True
                continue

        if book_empty:
            logger.warning('Tactical books empty, delay to tomorrow')
            self.tactical_finish = get_server_next_update(self.config.Scheduler_ServerUpdate)
            logger.info(f'Tactical finish: {self.tactical_finish}')
        return True

    def _tactical_skill_select(self, selected_skill, skip_first_screenshot=True):
        """
        选中屏幕上指定的技能。必要时更新当前截图。

        Args:
            selected_skill: 目标技能的 Button 对象
            skip_first_screenshot (bool): 是否跳过首次截图
        """
        logger.info('Tactical skill select')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.check_skill_selected(selected_skill, self.device.image):
                self.device.click(selected_skill)
                self.device.sleep((0.3, 0.5))
            else:
                break

    @staticmethod
    def check_skill_selected(button, image):
        area = button.area
        check_area = (area[0], area[3] + 2, area[2], area[3] + 4)
        im = rgb2gray(crop(image, check_area, copy=False))
        return np.mean(im) > 127

    def _tactical_skill_choose(self):
        """
        选择一个未满级的技能。

        Returns:
            bool: 是否找到可用技能

        Pages:
            in: SKILL_CONFIRM
            out: Unknown, may TACTICAL_CLASS_START, page_tactical
        """
        logger.hr('Tactical skill choose')
        selected_skill = self.find_not_full_level_skill()

        # 找不到可用技能，认为该舰船无需学习
        if selected_skill is None:
            logger.info('No available skill to learn')
            return False

        # 选中技能说明未满级，应开始或继续学习
        # 这里需要检查是否已选中
        self._tactical_skill_select(selected_skill)
        self.device.click(SKILL_CONFIRM)

        return True

    def select_suitable_ship(self):
        logger.hr('Select suitable ship')

        # 根据配置设置收藏筛选
        self.dock_favourite_set(enable=self.config.AddNewStudent_Favorite, wait_loading=False)

        # 重置筛选器；自然跳过 META 舰船
        self.dock_filter_set(
            faction=[v for k, v in self.dock_filter.settings if k == 'faction' and v not in ['all', 'meta']]
        )

        # 船坞中没有舰船
        if self.appear(DOCK_EMPTY, offset=(30, 30)):
            logger.info('Dock is empty or favorite ships is empty')
            return False

        # 舰船卡片加载可能较慢，例如：
        # [0, 0, 120, 120, 120, 120, 0, 0, 0, 0, 0, 0, 0, 0]
        # [12, 0, 0, 120, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        # 等待其变为
        # [120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120]
        level_ocr = LevelOcr(CARD_LEVEL_GRIDS.buttons, name='DOCK_LEVEL_OCR', threshold=64)
        list_level = []
        for _ in self.loop(timeout=1):
            list_level = level_ocr.ocr(self.device.image)
            first_ship = next((i for i, x in enumerate(list_level) if x > 0), len(list_level))
            first_empty = next((i for i, x in enumerate(list_level) if x == 0), len(list_level))
            if first_empty >= first_ship:
                break
        else:
            logger.warning('Wait ship cards timeout')

        try:
            min_level = int(self.config.AddNewStudent_MinLevel)
            if min_level < 1:
                min_level = 1
        except (ValueError, TypeError) as e:
            logger.warning(f'Invalid AddNewStudent_MinLevel: {self.config.AddNewStudent_MinLevel}, {e}')
            min_level = 1
        logger.attr('AddNewStudent_MinLevel', min_level)

        should_select_button = None
        for button, level in list(zip(CARD_GRIDS.buttons, list_level))[self.dock_select_index:]:
            # 仅选择等级 >= min_level 的舰船
            if level >= min_level:
                should_select_button = button
                break

        if should_select_button is None:
            logger.info(f'No ships with level >= {min_level} in dock')
            return False

        # 选择舰船
        self.dock_select_one(should_select_button, skip_first_screenshot=True)
        # 确认选中的舰船
        # 如果刚刚从 META 技能中退出，清除间隔计时器
        self.interval_clear(SHIP_CONFIRM)

        # 已移除 TACTICAL_SKILL_LIST 的使用，因为 EN 服普通技能列表用 "Select skills"
        # 而 META 技能列表用 "Choose skills"
        def check_button():
            if self.appear(SKILL_CONFIRM, offset=(30, 30)):
                return True
            if self.appear(TACTICAL_META, offset=(200, 30)):
                return True

        self.dock_select_confirm(check_button=check_button)

        return True

    def find_not_full_level_skill(self, skip_first_screenshot=True):
        """
        检查列表中最多三个技能，找到一个未满级的技能。

        Returns:
            选中技能的 Button 对象

        Pages:
            in: SKILL_CONFIRM
            out: SKILL_CONFIRM
        """

        if not skip_first_screenshot:
            self.device.screenshot()

        skill_level_ocr = ExpOnSkillSelect(buttons=SKILL_LEVEL_GRIDS.buttons, lang='cnocr', name='SKILL_LEVEL')
        skill_level_list = skill_level_ocr.ocr(self.device.image)
        for skill_button, skill_level in list(zip(SKILL_GRIDS.buttons, skill_level_list)):
            level = skill_level.upper().replace(' ', '')
            # 空技能槽位，可能是因为所有收藏舰娘的技能已满级
            # '———l', '—l'
            if not level:
                continue
            if re.search(r'[—\-一]{2,}', level):
                continue
            if re.search(r'[—一]+', level):
                continue
            # 使用 'MA' 作为 `MAX` 的一部分
            # SKILL_LEVEL_GRIDS 可能因未知原因向下偏移，OCR 结果示例：
            # ['NEXT:MA', 'NEXT:/1D]', 'NEXT:MA']（实际：`NEXT:MAX, NEXT:0/100, NEXT:MAX`）
            # ['NEXT:MA', 'NEX T:/ 14[]]', 'NEXT:MA']（实际：`NEXT:MAX, NEXT:150/1400, NEXT:MAX`）
            if 'MA' not in level:
                logger.attr('LEVEL', 'EMPTY' if len(level) == 0 else level)
                return skill_button

        return None

    def run(self):
        """
        运行战术学院任务。

        Pages:
            in: Any
            out: page_tactical
        """
        self.ui_ensure(page_reward)

        self.tactical_class_receive()

        if self.tactical_finish:
            self.config.task_delay(target=self.tactical_finish)
        else:
            logger.info('No tactical running')
            self.config.task_delay(success=False)