import datetime
import re

import cv2
import numpy as np

import module.config.server as server

from module.base.timer import Timer
from module.campaign.assets import OCR_EVENT_PT, OCR_COIN, OCR_OIL, OCR_COIN_LIMIT, OCR_OIL_LIMIT, OCR_OIL_CHECK
from module.base.utils import color_similar, get_color
from module.logger import logger
from module.ocr.ocr import Digit, Ocr
from module.ui.ui import UI
from module.log_res import LogRes

#if server.server != 'jp':
#    OCR_COIN = Digit(OCR_COIN, name='OCR_COIN', letter=(239, 239, 239), threshold=128)
#else:
#    OCR_COIN = Digit(OCR_COIN, name='OCR_COIN', letter=(201, 201, 201), threshold=128)

class PtOcr(Ocr):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, lang='azur_lane', alphabet='X0123456789', **kwargs)

    def pre_process(self, image):
        """
        对 PT 数字图像进行预处理。

        Args:
            image (np.ndarray): 形状为 (height, width, channel) 的图像。

        Returns:
            np.ndarray: 形状为 (width, height) 的灰度图像。
        """
        # 取 RGB 三通道的最大值
        r, g, b = cv2.split(cv2.subtract((255, 255, 255), image))
        image = cv2.min(cv2.min(r, g), b)
        # 去除背景，将 0-192 映射到 0-255
        image = cv2.multiply(image, 255 / 192)

        return image.astype(np.uint8)


OCR_PT = PtOcr(OCR_EVENT_PT)


class CampaignStatus(UI):
    def get_event_pt(self, update=False):
        """
        获取活动 PT 数量。

        Returns:
            int: PT 数量，解析失败返回 0。
        """
        pt = OCR_PT.ocr(self.device.image)

        # 首选匹配带前缀 X 的格式（历史上部分活动使用 ‘X1234’）
        res = re.search(r'X(\d+)', pt)
        if res:
            pt = int(res.group(1))
            logger.attr('Event_PT', pt)
            LogRes(self.config).Pt = pt
        else:
            # 回退：若 OCR 返回纯数字也接受（保留警告以便回溯）
            res2 = re.search(r'(\d+)', pt)
            if res2:
                num = int(res2.group(1))
                logger.warning(f"Invalid pt result format (missing 'X'): {pt}; fallback to digits: {num}")
                logger.attr('Event_PT_fallback', num)
                LogRes(self.config).Pt = num
                pt = num
            else:
                logger.warning(f'Invalid pt result: {pt}')
                pt = 0
        if update:
            self.config.update()
        return pt

    def get_coin(self, skip_first_screenshot=True, update=False):
        """
        获取金币数量。

        Returns:
            int: 金币数量。
        """
        _coin = {}
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Get coin timeout')
                break

            _coin = {
                'Value': self._get_num(OCR_COIN, 'OCR_COIN', (239, 239, 239)),
                'Limit': self._get_num(OCR_COIN_LIMIT, 'OCR_COIN_LIMIT', (239, 239, 239))
            }
            if _coin['Value'] >= 100:
                break
        LogRes(self.config).Coin = _coin
        if update:
            self.config.update()

        return _coin['Value']

    def _get_num(self, _button, name, letter=(247, 247, 247)):
        # 更新偏移量
        _ = self.appear(OCR_OIL_CHECK)

        color = get_color(self.device.image, OCR_OIL_CHECK.button)
        if color_similar(color, OCR_OIL_CHECK.color):
            # 原始颜色
            if isinstance(_button, Ocr):
                ocr = _button
            else:
                if server.server != 'jp':
                    ocr = Digit(_button, name=name, letter=letter, threshold=128)
                else:
                    ocr = Digit(_button, name=name, letter=(201, 201, 201), threshold=128)
        elif color_similar(color, (59, 59, 64)):
            # 带黑色遮罩
            ocr = Digit(_button, name=name, letter=(165, 165, 165), threshold=128)
        else:
            logger.warning(f'Unexpected OCR_OIL_CHECK color')
            ocr = Digit(_button, name=name, letter=(247, 247, 247), threshold=128)

        return ocr.ocr(self.device.image)

    def get_oil(self, skip_first_screenshot=True, update=False):
        """
        获取石油数量。

        Returns:
            int: 石油数量。
        """
        _oil = {}
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.appear(OCR_OIL_CHECK, offset=(10, 2)):
                logger.info('No oil icon')
                self.device.sleep(1)

            if timeout.reached():
                logger.warning('Get oil timeout')
                break

            _oil = {
                'Value': self._get_num(OCR_OIL, 'OCR_OIL', (247, 247, 247)),
                'Limit': self._get_num(OCR_OIL_LIMIT, 'OCR_OIL_LIMIT', (247, 247, 247))
            }
            if _oil['Value'] >= 100:
                break
        LogRes(self.config).Oil = _oil
        if update:
            self.config.update()

        return _oil['Value']

    def is_balancer_task(self):
        """
        判断当前任务是否为活动任务（排除每日活动任务）。

        Returns:
            bool: 是否为活动任务。
        """
        tasks = [
            'Event',
            'Event2',
            'Raid',
            'Coalition',
            'GemsFarming',
            'ThreeOilLowCost',
        ]
        command = self.config.Scheduler_Command
        if command in tasks:
            if self.config.Campaign_Event == 'campaign_main':
                return False
            else:
                return True
        else:
            return False
