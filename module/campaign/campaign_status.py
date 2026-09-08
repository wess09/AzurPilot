"""战役状态检测模块。

通过 OCR 读取战役页面上的数值信息，包括：
- 物资（金币）数量
- 石油数量
- 活动 PT（点数）
- 石油和物资限制检测

这些信息用于判断是否满足停止条件（如石油耗尽、物资溢出等）。

PtOcr 类专门处理活动 PT 数字的 OCR 识别，
需要特殊的图像预处理（反色、背景去除等）。

继承自 UI，利用页面导航能力。
"""

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
        # 取 RGB 三通道的最大值（等价于反色图取最小值后取反，避免分配中间数组）
        r, g, b = cv2.split(image)
        cv2.max(r, g, dst=r)
        cv2.max(r, b, dst=r)
        cv2.bitwise_not(r, dst=r)
        # 去除背景，将 0-192 映射到 0-255
        cv2.convertScaleAbs(r, alpha=255 / 192, dst=r)
        return r


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
            logger.attr('活动PT', pt)
            LogRes(self.config).Pt = pt
        else:
            # 回退：若 OCR 返回纯数字也接受（保留警告以便回溯）
            res2 = re.search(r'(\d+)', pt)
            if res2:
                num = int(res2.group(1))
                logger.warning(f"无效的PT结果格式 (missing 'X'): {pt}; fallback to digits: {num}")
                logger.attr('活动PT_回退', num)
                LogRes(self.config).Pt = num
                pt = num
            else:
                logger.warning(f'无效的PT结果: {pt}')
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
                logger.warning('获取物资超时')
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
            logger.warning('[战役-状态] 意外的OCR_OIL_CHECK颜色')
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
                logger.info('无石油图标')
                self.device.sleep(1)

            if timeout.reached():
                logger.warning('获取石油超时')
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
