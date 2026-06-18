from functools import reduce
from typing import List, Optional, Tuple

import cv2
import numpy as np

from module.base.utils import area_offset, color_similarity_2d, image_size, rgb2gray, xywh2xyxy
from module.event_hospital.assets import *
from module.event_hospital.ui import HospitalUI
from module.logger import logger
from module.raid.assets import RAID_FLEET_PREPARATION
from module.ui.page import page_hospital
from module.ui.scroll import Scroll


def merge_two_rects(
        r1: Tuple[int, int, int, int],
        r2: Tuple[int, int, int, int]
) -> Tuple[int, int, int, int]:
    """合并两个矩形区域，返回包含两者的最小矩形。"""
    return (
        min(r1[0], r2[0]),
        min(r1[1], r2[1]),
        max(r1[2], r2[2]),
        max(r1[3], r2[3])
    )


def merge_rows(list_word, merge):
    """将相近的文本行合并为同一行。"""
    # 按 y 坐标排序
    list_word = sorted(list_word, key=lambda x: x[1])

    # 合并相近的文本行
    list_row = []
    current_row = []
    current_center = None
    for rect, center_y in list_word:
        if not current_row:
            current_row.append(rect)
            current_center = center_y
        elif abs(center_y - current_center) <= merge:
            current_row.append(rect)
        else:
            list_row.append(reduce(merge_two_rects, current_row))
            current_row = [rect]
            current_center = center_y

    if current_row:
        list_row.append(reduce(merge_two_rects, current_row))

    return list_row


class HospitalClue(HospitalUI):
    def get_clue_list(self) -> List[Button]:
        """获取线索列表中所有旁白按钮。

        通过颜色过滤和轮廓检测识别列表中的文本行，
        返回对应的 Button 对象列表。

        Returns:
            List[Button]: 旁白按钮列表。
        """
        area = CLUE_LIST.area
        image = self.image_crop(area, copy=False)

        # 灰色文字掩码
        gray = color_similarity_2d(image, color=(132, 134, 148))
        cv2.inRange(gray, 215, 255, dst=gray)
        # 白色文字掩码（已选中的旁白）
        white = color_similarity_2d(image, color=(255, 255, 255))
        cv2.inRange(white, 215, 255, dst=white)
        # 清除白色像素周围的灰色掩码
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (200, 20))
        white_expanded = cv2.dilate(white, kernel)
        cv2.subtract(gray, white_expanded, dst=gray)
        # 混合掩码
        cv2.bitwise_or(gray, white, dst=gray)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        cv2.dilate(gray, kernel, dst=gray)

        # 查找矩形轮廓
        list_word = []
        contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cont in contours:
            rect = cv2.boundingRect(cv2.convexHull(cont).astype(np.float32))
            # 按矩形高度过滤，通常为 16
            rect = xywh2xyxy(rect)
            # 过滤过矮的行
            if rect[3] - rect[1] < 12:
                continue
            center_y = (rect[1] + rect[3]) // 2
            list_word.append((rect, center_y))

        list_row = merge_rows(list_word, merge=5)
        list_row = [area_offset(r, offset=area[:2]) for r in list_row]
        list_button = [
            Button(area=rect, color=(), button=rect, name=f'CLUE_LIST_{i}')
            for i, rect in enumerate(list_row)
        ]
        return list_button

    def get_invest_button(self) -> Optional[Button]:
        """获取当前图像中未完成的调查按钮。

        通过模板匹配查找 INVEST 按钮，然后检查下方是否
        存在剩余次数标识来判断是否未完成。

        Returns:
            Optional[Button]: 未完成的调查按钮，全部完成则返回 None。
        """
        area = INVEST_SEARCH.area
        image = self.image_crop(area, copy=False)
        image = rgb2gray(image)

        # 搜索 INVEST 按钮
        buttons = TEMPLATE_INVEST.match_multi(image)
        buttons += TEMPLATE_INVEST2.match_multi(image)
        buttons = sorted(buttons, key=lambda b: b.area[1])
        count = len(buttons)
        if count == 0:
            return None
        buttons = [b.move(area[:2]) for b in buttons]
        if count == 1:
            # 只有 1 个 INVEST 按钮，在其下方搜索
            button = buttons[0]
            search = (area[0], button.button[3], area[2], area[3])
        else:
            # 多个 INVEST 按钮，在两者之间搜索
            button = buttons[0]
            second = buttons[1]
            search = (area[0], button.button[3], area[2], second.button[1])
        image = self.image_crop(search, copy=False)
        image = rgb2gray(image)

        # 检查图像尺寸
        x, y = image_size(image)
        if y < 50:
            return None

        # 检查 INVEST 下方是否有剩余次数标识
        if TEMPLATE_REMAIN_CURRENT.match(image):
            return button
        if TEMPLATE_REMAIN_TIMES.match(image):
            return button
        return None

    def clue_enter(self, skip_first_screenshot=True):
        """进入线索界面。

        Pages:
            in: 医院活动任意子页面
            out: is_in_clue
        """
        logger.info('Hospital clue enter')
        self.interval_clear(page_hospital.check_button)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.is_in_clue():
                break
            if self.handle_clue_exit():
                continue

    def clue_exit(self, skip_first_screenshot=True):
        """退出线索界面，返回医院主页。

        Pages:
            in: 医院活动任意子页面
            out: page_hospital
        """
        logger.info('Hospital clue exit')
        self.interval_clear(HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_page_appear(page_hospital):
                break
            if self.handle_clue_exit():
                continue
            if self.appear_then_click(HOSIPITAL_CLUE_CHECK, offset=(20, 20), interval=2):
                continue

    def invest_enter(self, skip_first_screenshot=True):
        """进入调查战斗准备界面。

        在线索界面中查找未完成的调查，点击进入舰队准备。

        Args:
            skip_first_screenshot: 是否跳过首次截图复用上一状态。

        Returns:
            bool: 是否成功进入调查。

        Pages:
            in: is_in_clue
            out: FLEET_PREPARATION
        """
        logger.info('Clue invest')
        self.interval_clear(HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30)):
                return True

            if self.is_in_clue(interval=2):
                invest = next(self.iter_invest(), None)
                if invest is None:
                    logger.info('No more invest')
                    return False
                logger.info(f'is_in_clue -> {invest}')
                self.device.click(invest)
                self.interval_reset(HOSIPITAL_CLUE_CHECK, interval=2)
                continue
            if self.appear_then_click(HOSPITAL_BATTLE_PREPARE, offset=(20, 20), interval=2):
                continue
            if self.handle_get_clue():
                continue

    def iter_invest(self):
        """遍历所有未完成的调查按钮。

        通过滚动列表逐页查找未完成的调查，依次 yield 返回。

        Yields:
            Button: 未完成的调查按钮。
        """
        logger.hr('Iter invest')
        scroll = Scroll(INVEST_SCROLL, color=(107, 97, 107), name='INVEST_SCROLL')
        # 无滚动条时只检查当前页
        if not scroll.appear(main=self):
            logger.info('No scroll')
            button = self.get_invest_button()
            if button:
                yield button
            return

        # 检查当前页
        button = self.get_invest_button()
        if button:
            yield button

        # 检查顶部
        if not scroll.at_top(main=self):
            scroll.set_top(main=self)
            button = self.get_invest_button()
            if button:
                yield button
        # 逐页遍历
        while 1:
            if scroll.at_bottom(main=self):
                logger.info(f'{scroll.name} reached end')
                return
            scroll.next_page(main=self, page=0.5)
            button = self.get_invest_button()
            if button:
                yield button

    def is_aside_selected(self, button: Button) -> bool:
        """检查旁白是否被选中（深色背景）。"""
        area = button.area
        search = CLUE_LIST.area
        # 检查周围是否有深色背景
        area = (search[0], area[1], search[2], area[3])
        return self.image_color_count(area, color=(82, 85, 107), threshold=221, count=500)

    def is_aside_checked(self, button: Button) -> bool:
        """检查旁白是否已完成（青色标记）。"""
        area = button.area
        search = CLUE_LIST.area
        # 检查是否有青色标记，JP 服文字溢出故右边界设为 308
        area = (search[0], area[1], 308, area[3])
        return self.image_color_count(area, color=(74, 130, 148), threshold=221, count=20)

    def iter_aside(self):
        """遍历所有未完成的旁白按钮。

        跳过已完成（有青色标记）的旁白，依次 yield 返回。

        Yields:
            Button: 未完成的旁白按钮。
        """
        list_button = self.get_clue_list()
        for button in list_button:
            if self.is_aside_checked(button):
                continue
            yield button

    def select_aside(self, skip_first_screenshot=True):
        """选择一个未完成的旁白。

        在线索界面中查找未完成的旁白并点击选中。

        Args:
            skip_first_screenshot: 是否跳过首次截图复用上一状态。

        Returns:
            bool: True 表示成功选中未完成旁白，False 表示全部已完成。

        Pages:
            in: is_in_clue
        """
        logger.info(f'Select aside')
        aside = None
        self.interval_clear(HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            # End
            if aside is not None and self.is_aside_selected(aside):
                return True
            if self.is_in_clue(interval=2):
                aside = next(self.iter_aside(), None)
                if aside is None:
                    logger.info('No more aside')
                    return False
                logger.info(f'is_in_clue -> {aside}')
                self.device.click(aside)
                self.interval_reset(HOSIPITAL_CLUE_CHECK, interval=2)
                continue
            if self.handle_clue_exit():
                continue
