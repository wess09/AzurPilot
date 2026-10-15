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

import numpy as np

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import color_mask
from module.exception import GameStuckError
from module.logger import logger
from module.meowfficer.assets import *
from module.meowfficer.base import MeowfficerBase
from module.meowfficer.buy import MEOWFFICER_COINS
from module.ocr.ocr import Digit, DigitCounter
from module.ui.assets import MEOWFFICER_GOTO_DORMMENU
from module.ui.page import page_meowfficer
from module.ui.scroll import Scroll

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
MEOWFFICER_ENHANCE_CAPACITY = DigitCounter(OCR_MEOWFFICER_CAPACITY, letter=(131, 121, 123), threshold=64)
MEOWFFICER_CATTERY_SCROLL = Scroll(
    area=(1247, 139, 1256, 549), color=(255, 222, 99), name='MEOWFFICER_CATTERY_SCROLL')

# 选中虚线圈位于头像外缘；只检查其四侧，排除头像、等级与名字里的白色内容。
_ring_y, _ring_x = np.ogrid[-63:64, -63:64]
_ring_radius = _ring_x * _ring_x + _ring_y * _ring_y
_ring_mask = (_ring_radius >= 52 * 52) & (_ring_radius <= 61 * 61)
_ring_sides = tuple(_ring_mask & side for side in (
    _ring_x < -35, _ring_x > 35, _ring_y < -35, _ring_y > 35))


class MeowfficerLevelOcr(Digit):
    """指挥喵等级 OCR 识别器。

    针对指挥喵等级显示的特殊 OCR 处理，移除等级标识字符（L、V）
    和小数点，以提高数字识别精度。
    """
    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789IDSLV',
                 name=None):
        """初始化指挥喵等级 OCR 识别器。"""
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        """清洗 OCR 识别结果，移除等级前缀字符和小数点。

        Args:
            result (str): 识别出的原始字符串。

        Returns:
            str: 清洗后的纯数字字符串。
        """
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
    def _meow_cattery_at_top(self):
        """正向确认猫窝滚动条位于顶部；无滚动条时核对猫数量。"""
        thumb = np.flatnonzero(MEOWFFICER_CATTERY_SCROLL.match_color(self))
        if len(thumb):
            # 滑块圆角使首个匹配像素比轨道起点低 3 像素。
            return thumb[0] <= 4
        current, _, total = MEOWFFICER_ENHANCE_CAPACITY.ocr(self.device.image)
        return total > 0 and 0 < current <= 12

    def _meow_target_selected(self, x, y):
        """确认目标头像外缘四侧均有黄色虚线，并伴随白色选中圈。"""
        x1, y1, x2, _ = MEOWFFICER_SELECT_GRID[x, y].area
        cx, cy = int((x1 + x2) / 2), int(y1 - 47)
        ring = self.device.image[cy - 63:cy + 64, cx - 63:cx + 64]
        if ring.shape != (127, 127, 3):
            return False
        yellow = color_mask(ring, (255, 215, 90), threshold=45) > 0
        white = color_mask(ring, (255, 255, 255), threshold=15) > 0
        return (np.count_nonzero(white & _ring_mask) >= 200
                and all(np.count_nonzero(yellow & side) >= 10 for side in _ring_sides))

    def _meow_select(self, skip_first_screenshot=True):
        """在指挥喵选择网格（4x3）中选中目标指挥喵。

        先正向确认猫窝列表归位，再点击目标并等待外缘黄白虚线圈稳定。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。
        """
        # 计算目标指挥喵在 4x3 网格中的 (x, y) 坐标
        index = self.config.MeowfficerTrain_EnhanceIndex - 1
        x = index if index < 4 else index % 4
        y = index // 4

        click_timer = Timer(3, count=6)
        scroll_timer = Timer(1, count=2)
        top_timer = Timer(0.6, count=2).start()
        selected_timer = Timer(0.6, count=2).start()
        clicked = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.meow_additional():
                clicked = False
                click_timer.reset()
                top_timer.reset()
                selected_timer.reset()
                continue

            if not self._meow_cattery_at_top():
                clicked = False
                top_timer.reset()
                selected_timer.reset()
                if scroll_timer.reached():
                    logger.info('[指挥喵-强化] 猫窝列表未归位，滑回顶部')
                    self.device.swipe((1100, 180), (1100, 500), duration=(0.6, 0.6),
                                      name='MEOWFFICER_RESET_LIST')
                    scroll_timer.reset()
                continue
            if not top_timer.reached():
                continue

            # 即使旧截图看似已有选中圈，也先点击一次，再使用新截图确认。
            if clicked and self._meow_target_selected(x, y):
                if selected_timer.reached():
                    logger.attr('强化目标已选中', index + 1)
                    break
                continue
            selected_timer.reset()

            if click_timer.reached():
                self.device.click(MEOWFFICER_FEED_GRID[x, y])
                clicked = True
                click_timer.reset()

    def meow_feed_scan(self):
        """扫描可作为材料喂养给目标指挥喵的候选指挥喵列表。

        检查 4x3 材料网格中的槽位，过滤已选中、空槽位以及等级超过上限的指挥喵。

        Returns:
            list[Button]: 可作为强化材料的指挥喵按钮列表。

        Pages:
            in: MEOWFFICER_FEED
            out: MEOWFFICER_FEED
        """
        clickable = []

        # 修正非法的最大喂养等级配置
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

        # OCR 识别候选材料的指挥喵等级
        feed_level_list = Digit(MEOWFICER_FEED_LEVEL_GRID.buttons, letter=(49, 48, 49),
                                name='FEED_MEOWFFICER_LEVEL').ocr(self.device.image)

        for index, (button, level) in enumerate(zip(MEOWFFICER_FEED_GRID.buttons, feed_level_list)):
            # 超过 10 只后退出，无需继续判断
            if index >= 10:
                break

            # 遇到空槽位退出
            if self.image_color_count(button, color=(231, 223, 221), threshold=20, count=450):
                break

            # 若已选中（绿色对勾），跳过
            if self.image_color_count(button, color=(95, 229, 108), threshold=30, count=150):
                continue

            # 若材料等级超过设定的最大喂养等级，跳过
            if level > self.config.MeowfficerTrain_MaxFeedLevel:
                continue

            # 满足条件，加入可选材料列表
            clickable.append(button)

        logger.info(f'[指挥喵-强化] 找到强化材料总数: {len(clickable)}')
        return clickable

    def meow_feed_select(self):
        """点击并确认用作强化材料的指挥喵。

        Returns:
            int: 选中的材料数量（大于 0 表示有材料被选中并确认，0 表示无可用材料并取消）。

        Pages:
            in: MEOWFFICER_FEED
            out: MEOWFFICER_ENHANCE
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

            # 已达上限则退出
            current, remain, total = MEOWFFICER_FEED.ocr(self.device.image)
            if not remain:
                break

            # 扫描可用材料，无材料则退出
            buttons = self.meow_feed_scan()
            if not len(buttons):
                break

            # 依次点击材料按钮以选中
            if retry.reached():
                for button in buttons:
                    self.device.click(button)
                retry.reset()

        # 根据是否选中材料点击确认或取消
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
        """进入材料选择（喂养）界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 成功进入材料选择界面返回 True；失败（可能因为目标指挥喵已达到满级 30 级）返回 False。

        Pages:
            in: MEOWFFICER_FEED_ENTER
            out: MEOWFFICER_FEED_CONFIRM（成功）或 MEOWFFICER_FEED_ENTER（失败）
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

            # 判定结束
            if self.appear(MEOWFFICER_FEED_CONFIRM, offset=(20, 20)):
                if confirm_timer.reached():
                    return True
            if click_count >= 3:
                logger.warning('[指挥喵-强化] 无法进入指挥喵喂养, '
                               'probably because the meowfficer to enhance has reached LV.30')
                return False

    def meow_enhance_confirm(self, skip_first_screenshot=True):
        """确认强化操作并等待消耗材料完成。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

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

            # 判定结束
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
        """进入指挥喵强化详情界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 成功进入返回 True，失败（如指挥喵在战斗中）返回 False。

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

            # 判定结束
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
            # 处理强化提示弹窗
            if self.handle_game_tips():
                continue

    def _meow_get_level(self):
        """识别当前选中指挥喵的等级。

        Returns:
            int: 指挥喵等级（1 到 30）；识别失败返回 0。

        Pages:
            in: MEOWFFICER_ENHANCE_ENTER
        """
        level = OCR_MEOWFFICER_ENHANCE_LEVEL.ocr(self.device.image)
        if level > 30:
            logger.warning(f'[指挥喵-强化] 无效的指挥喵等级: {level}')
        return level

    def _meow_enhance(self):
        """执行单次指挥喵强化流程。

        选择目标指挥喵并循环喂养材料，直至材料耗尽、金币不足或达到满级。

        Returns:
            str: 强化结果状态码（'invalid', 'coin_limit', 'leveled_max', 'in_battle', 'success'）。

        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        logger.hr('指挥喵强化', level=1)
        logger.attr('强化索引', self.config.MeowfficerTrain_EnhanceIndex)

        # 基础条件检查：索引 1~12，金币 >= 1000
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
            # 选中目标指挥喵
            self._meow_select()

            level = self._meow_get_level()
            if not 1 <= level <= 30:
                raise GameStuckError(f'[指挥喵-强化] 目标等级识别无效: {level}')
            if level == 30:
                logger.info('[指挥喵-强化] 当前指挥喵已满级')
                return 'leveled_max'

            # 进入材料界面，若失败则撤退并重进
            if self.meow_enhance_enter():
                break
            else:
                # 处理可能存在的战役未结束状态
                self.ui_goto_campaign()
                self.ui_goto(page_meowfficer)
                continue

        # 循环执行喂养流程：选材料 -> 确认/取消 -> 确认强化 -> 检查金币
        while 1:
            logger.hr('强化一次', level=2)
            if not self.meow_feed_enter():
                # 返回指挥喵主界面
                self.ui_click(MEOWFFICER_GOTO_DORMMENU, check_button=MEOWFFICER_ENHANCE_ENTER,
                              appear_button=MEOWFFICER_ENHANCE_CONFIRM, offset=None, skip_first_screenshot=True)
                # 重新进入指挥喵主界面
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

        # 返回指挥喵主界面
        self.ui_click(MEOWFFICER_GOTO_DORMMENU, check_button=MEOWFFICER_ENHANCE_ENTER,
                      appear_button=MEOWFFICER_ENHANCE_CONFIRM, offset=None, skip_first_screenshot=True)
        return 'success'

    def meow_enhance(self):
        """执行指挥喵强化任务。

        封装 `_meow_enhance()`；若当前目标指挥喵达到满级（30级），会自动递增索引强化下一只，直至第 12 只满级后禁用。
        """
        while 1:
            result = self._meow_enhance()
            if result not in ['leveled_max']:
                break

            # 仅针对满级情况递增索引
            if self.config.MeowfficerTrain_EnhanceIndex < 12:
                self.config.MeowfficerTrain_EnhanceIndex += 1
                logger.info(f'[指挥喵-强化] 强化索引增加至 {self.config.MeowfficerTrain_EnhanceIndex}')
                continue
            else:
                logger.warning('[指挥喵-强化] 第12只指挥喵达到30级，禁用指挥喵训练')
                self.config.MeowfficerTrain_Enable = False
                break
