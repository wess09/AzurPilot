"""指挥喵强化模块。

处理指挥喵强化（喂养）相关的所有操作，包括：
- 选择目标指挥喵进行强化
- 扫描可用的喂养材料（多余的指挥喵）
- 确认并执行强化操作
- 强化完成后自动提升索引至下一个指挥喵

强化机制说明：
- 消耗低等级指挥喵作为材料，为目标指挥喵提供经验值
- 每次强化最多可使用 10 个喂养材料
- 强化需要消耗金币（每次 1000）
- 目标指挥喵最高可升至 30 级
- 喂养材料的最大等级可通过 `MeowfficerTrain_MaxFeedLevel` 配置

配置项前缀：`MeowfficerTrain_*`
"""

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.logger import logger
from module.meowfficer.assets import *
from module.meowfficer.base import MeowfficerBase
from module.meowfficer.buy import MEOWFFICER_COINS
from module.ocr.ocr import Digit, DigitCounter
from module.ui.assets import MEOWFFICER_GOTO_DORMMENU
from module.ui.page import page_meowfficer

MEOWFFICER_SELECT_GRID = ButtonGrid(
    origin=(751, 237), delta=(130, 147), button_shape=(70, 20), grid_shape=(4, 3),
    name='MEOWFFICER_SELECT_GRID')
MEOWFFICER_FEED_GRID = ButtonGrid(
    origin=(783, 189), delta=(130, 148), button_shape=(46, 46), grid_shape=(4, 3),
    name='MEOWFFICER_FEED_GRID')
MEOWFICER_FEED_LEVEL_GRID = ButtonGrid(
    origin=(738, 211), delta=(130, 148), button_shape=(20, 22), grid_shape=(4, 3),
    name='MEOWFFICER_FEED_LEVEL_GRID')
MEOWFFICER_FEED = DigitCounter(OCR_MEOWFFICER_FEED, letter=(131, 121, 123), threshold=64)


class MeowfficerLevelOcr(Digit):
    """指挥喵等级 OCR 识别器。

    针对指挥喵等级显示的特殊 OCR 处理，移除等级标识字符（L、V）
    和小数点，以提高数字识别精度。
    """
    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789IDSLV',
                 name=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        result = result.replace('L', '').replace('V', '').replace('.', '')
        return super().after_process(result)


OCR_MEOWFFICER_ENHANCE_LEVEL = MeowfficerLevelOcr(OCR_MEOWFFICER_ENHANCE_LEVEL, name='OCR_MEOWFFICER_ENHANCE_LEVEL')


class MeowfficerEnhance(MeowfficerBase):
    """指挥喵强化处理器。

    负责指挥喵强化（喂养）的完整流程：
    选择目标指挥喵 -> 扫描可用材料 -> 选择材料 -> 确认强化 -> 循环直至资源耗尽。

    Attributes:
        config.MeowfficerTrain_EnhanceIndex (int): 目标指挥喵在网格中的位置索引（1~12）。
        config.MeowfficerTrain_MaxFeedLevel (int): 喂养材料的最大等级限制（1~30）。
    """
    def _meow_select(self, skip_first_screenshot=True):
        """
        Select the target meowfficer in the
        MEOWFFICER_SELECT_GRID (4x3)
        Ensure through dotted yellow/white
        circle appearance after click

        Args:
            skip_first_screenshot (bool):
        """
        # Calculate (x, y) coordinate within
        # MEOWFFICER_SELECT/FEED_GRID (4x3) for
        # enhance target
        index = self.config.MeowfficerTrain_EnhanceIndex - 1
        x = index if index < 4 else index % 4
        y = index // 4

        # Must confirm selected
        # Dotted yellow/white circle
        # around target meowfficer
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.meow_additional():
                click_timer.reset()
                continue

            if self.image_color_count(MEOWFFICER_SELECT_GRID[x, y], color=(255, 255, 255), threshold=246, count=100):
                break

            if click_timer.reached():
                self.device.click(MEOWFFICER_FEED_GRID[x, y])
                click_timer.reset()

    def meow_feed_scan(self):
        """
        Scan for meowfficers that can be fed
        according to the MEOWFFICER_FEED_GRID (4x3)
        into target meowfficer for enhancement
        Ensure through green check mark appearance
        after click

        Pages:
            in: MEOWFFICER_FEED
            out: MEOWFFICER_FEED

        Returns:
            list(Button)
        """
        clickable = []

        # Reset invalid value of MeowfficerTrain_MaxFeedLevel
        # it can work without this code, just for rigor
        reset_max_feed_level = -1
        if self.config.MeowfficerTrain_MaxFeedLevel < 1:
            reset_max_feed_level = 1
        elif self.config.MeowfficerTrain_MaxFeedLevel > 30:
            reset_max_feed_level = 30

        if -1 != reset_max_feed_level:
            logger.warning(f"[指挥喵-强化] 条件 '1 <= MeowfficerTrain_MaxFeedLevel <= 30' 需要满足, "
                           f'now MeowfficerTrain_MaxFeedLevel is {self.config.MeowfficerTrain_MaxFeedLevel}, '
                           f'reset to {reset_max_feed_level}')
            self.config.MeowfficerTrain_MaxFeedLevel = reset_max_feed_level

        # Get all the cat levels ready for enhance
        feed_level_list = Digit(MEOWFICER_FEED_LEVEL_GRID.buttons, letter=(49, 48, 49),
                                name='FEED_MEOWFFICER_LEVEL').ocr(self.device.image)

        for index, (button, level) in enumerate(zip(MEOWFFICER_FEED_GRID.buttons, feed_level_list)):
            # Exit if 11th button; no need to validate as not
            # possible to click beyond this point
            if index >= 10:
                break

            # Exit if button is empty slot
            if self.image_color_count(button, color=(231, 223, 221), threshold=235, count=450):
                break

            # Continue onto next if button
            # already selected (green check mark)
            if self.image_color_count(button, color=(95, 229, 108), threshold=221, count=150):
                continue

            # Continue onto next If the target Meowfficer's level
            # is greater than the maximum feed level set
            if level > self.config.MeowfficerTrain_MaxFeedLevel:
                continue

            # Neither base case, so presume
            # button is clickable
            clickable.append(button)

        logger.info(f'[指挥喵-强化] 找到强化材料总数: {len(clickable)}')
        return clickable

    def meow_feed_select(self):
        """
        Click and confirm the meowfficers that
        can be used as feed to enhance the target
        meowfficer

        Pages:
            in: MEOWFFICER_FEED
            out: MEOWFFICER_ENHANCE

        Returns:
            int: non-zero positive, some selected
                 zero, none selected
        """
        self.interval_clear([
            MEOWFFICER_FEED_CONFIRM,
            MEOWFFICER_FEED_CANCEL,
            MEOWFFICER_ENHANCE_CONFIRM
        ])
        current = 0
        retry = Timer(1, count=2)
        skip_first_screenshot = True

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Exit if maximum clicked
            current, remain, total = MEOWFFICER_FEED.ocr(self.device.image)
            if not remain:
                break

            # Scan for feed, exit if none
            buttons = self.meow_feed_scan()
            if not len(buttons):
                break

            # Else click each button to
            # apply green check mark
            # Sleep for stable image
            if retry.reached():
                for button in buttons:
                    self.device.click(button)
                retry.reset()

        # Use current to pass appropriate button for ui_click
        # route back to MEOWFFICER_ENHANCE
        if current:
            logger.info(f'[指挥喵-强化] 确认选择的强化材料, 总数: {current} / 10')
            self.ui_click(MEOWFFICER_FEED_CONFIRM, check_button=MEOWFFICER_ENHANCE_CONFIRM,
                          offset=(20, 20), skip_first_screenshot=True)
        else:
            logger.info('[指挥喵-强化] 强化材料不足，取消强化')
            self.ui_click(MEOWFFICER_FEED_CANCEL, check_button=MEOWFFICER_ENHANCE_CONFIRM,
                          offset=(10, 10), skip_first_screenshot=True)
        return current

    def meow_feed_enter(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Returns:
            bool: If success. False if failed,
                probably because the meowfficer
                to enhance has reached LV.30

        Pages:
            in: MEOWFFICER_FEED_ENTER
            out: MEOWFFICER_FEED_CONFIRM if success
                 MEOWFFICER_FEED_ENTER if failed
        """
        click_count = 0
        confirm_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(MEOWFFICER_FEED_ENTER, offset=(20, 20), interval=3):
                click_count += 1
                continue

            # End
            if self.appear(MEOWFFICER_FEED_CONFIRM, offset=(20, 20)):
                if confirm_timer.reached():
                    return True
            if click_count >= 3:
                logger.warning('[指挥喵-强化] 无法进入指挥喵喂养, '
                               'probably because the meowfficer to enhance has reached LV.30')
                return False

    def meow_enhance_confirm(self, skip_first_screenshot=True):
        """
        Finalize feed materials for enhancement
        of meowfficer

        Pages:
            in: MEOWFFICER_ENHANCE
            out: MEOWFFICER_ENHANCE
        """
        self.interval_clear([
            MEOWFFICER_FEED_ENTER,
            MEOWFFICER_ENHANCE_CONFIRM,
            MEOWFFICER_CONFIRM,
        ])
        confirm_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            if self.appear(MEOWFFICER_FEED_ENTER, offset=(20, 20)):
                if confirm_timer.reached():
                    break
                continue

            if self.handle_meow_popup_confirm():
                confirm_timer.reset()
                continue
            if self.appear_then_click(MEOWFFICER_ENHANCE_CONFIRM, offset=(20, 20), interval=3):
                confirm_timer.reset()
                continue

    def meow_enhance_enter(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Returns:
            bool: If success.

        Pages:
            in: MEOWFFICER_ENHANCE_ENTER
            out: MEOWFFICER_FEED_ENTER
        """
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            if self.appear(MEOWFFICER_FEED_ENTER, offset=(20, 20)):
                return True
            if count > 3:
                logger.warning('[指挥喵-强化] MEOWFFICER_ENHANCE_ENTER 点击次数过多，指挥喵可能在战斗中')
                return False

            if self.appear_then_click(MEOWFFICER_ENHANCE_ENTER, offset=(20, 20), interval=3):
                count += 1
                continue
            if self.meow_additional():
                continue
            # Meowfficer enhance tips
            if self.handle_game_tips():
                continue

    def _meow_get_level(self):
    """
    Returns:
        int: level from 1 to 30. Returns 0 if cannot detect

    Pages:
        in: MEOWFFICER_ENHANCE_ENTER
    """
    levels = []

    # Wait for the selected Meowfficer information to refresh.
    self.device.sleep(0.3)

    for attempt in range(3):
        # Use a fresh screenshot instead of the image captured while
        # selecting the Meowfficer.
        self.device.screenshot()

        level = OCR_MEOWFFICER_ENHANCE_LEVEL.ocr(self.device.image)

        if 1 <= level <= 30:
            levels.append(level)
        else:
            logger.warning(f'[指挥喵-强化] 无效的指挥喵等级: {level}')

        # Normal levels do not need additional confirmation.
        # LV.30 and invalid OCR results are confirmed with fresh frames.
        if attempt == 0 and 1 <= level < 30:
            return level

        if attempt < 2:
            self.device.sleep(0.2)

    # LV.30 may advance EnhanceIndex or disable MeowfficerTrain,
    # so require three consistent OCR results.
    if len(levels) == 3 and all(level == 30 for level in levels):
        return 30

    non_max_levels = [level for level in levels if level < 30]
    if non_max_levels:
        if 30 in levels:
            logger.warning(
                f'[指挥喵-强化] LV.30 OCR结果不一致: {levels}, '
                '忽略本次满级判断'
            )
        return max(set(non_max_levels), key=non_max_levels.count)

    logger.warning(
        f'[指挥喵-强化] 无法确认指挥喵等级: {levels}, '
        '本次不判定为满级'
    )
    return 0

    def _meow_enhance(self):
        """
        Perform meowfficer enhancement operations
        involving using extraneous meowfficers to
        donate XP into a meowfficer target

        Returns:
            str:

        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        logger.hr('指挥喵强化', level=1)
        logger.attr('强化索引', self.config.MeowfficerTrain_EnhanceIndex)

        # Base Cases
        # - Config at least > 0 but less than or equal to 12
        # - Coins at least > 1000
        if not (1 <= self.config.MeowfficerTrain_EnhanceIndex <= 12):
            logger.warning(f'[指挥喵-强化] 强化索引={self.config.MeowfficerTrain_EnhanceIndex} '
                           f'is out of bounds. Please limit to 1~12, skip')
            return 'invalid'

        coins = MEOWFFICER_COINS.ocr(self.device.image)
        if coins < 1000:
            logger.info(f'[指挥喵-强化] 物资 ({coins}) < 1000, 物资不足无法完成 '
                        f'enhancement, skip')
            return 'coin_limit'

        for _ in range(2):
            # Select target meowfficer
            # for enhancement
            self._meow_select()

            if self._meow_get_level() >= 30:
                logger.info('[指挥喵-强化] 当前指挥喵已满级')
                return 'leveled_max'

            # Transition to MEOWFFICER_FEED after
            # selection; broken up due to significant
            # delayed behavior of meow_additional
            if self.meow_enhance_enter():
                break
            else:
                # Retreat from an existing battle
                self.ui_goto_campaign()
                self.ui_goto(page_meowfficer)
                continue

        # Initiate feed sequence; loop until exhaust all
        # - Select Feed
        # - Confirm/Cancel Feed
        # - Confirm Enhancement
        # - Check remaining coins after enhancement
        while 1:
            logger.hr('强化一次', level=2)
            if not self.meow_feed_enter():
                # Exit back into page_meowfficer
                self.ui_click(MEOWFFICER_GOTO_DORMMENU, check_button=MEOWFFICER_ENHANCE_ENTER,
                              appear_button=MEOWFFICER_ENHANCE_CONFIRM, offset=None, skip_first_screenshot=True)
                # Re-enter page_meowfficer
                self.ui_goto_main()
                self.ui_goto(page_meowfficer)
                return 'in_battle'
            if not self.meow_feed_select():
                break
            self.meow_enhance_confirm()

            coins = MEOWFFICER_COINS.ocr(self.device.image)
            if coins < 1000:
                logger.info(f'[指挥喵-强化] 剩余物资 ({coins}) < 1000, 物资不足以进行下次 '
                            f'enhancement, skip')
                break

        # Exit back into page_meowfficer
        self.ui_click(MEOWFFICER_GOTO_DORMMENU, check_button=MEOWFFICER_ENHANCE_ENTER,
                      appear_button=MEOWFFICER_ENHANCE_CONFIRM, offset=None, skip_first_screenshot=True)
        return 'success'

    def meow_enhance(self):
        """
        A wrapper of _meow_enhance()
        MeowfficerTrain_EnhanceIndex will auto
        increase if it reached LV.30
        """
        while 1:
            result = self._meow_enhance()
            if result not in ['leveled_max']:
                break

            # Only for 'leveled_max'
            if self.config.MeowfficerTrain_EnhanceIndex < 12:
                self.config.MeowfficerTrain_EnhanceIndex += 1
                logger.info(f'[指挥喵-强化] 强化索引增加至 {self.config.MeowfficerTrain_EnhanceIndex}')
                continue
            else:
                logger.warning('[指挥喵-强化] 第12只指挥喵达到30级，禁用指挥喵训练')
                self.config.MeowfficerTrain_Enable = False
                break
