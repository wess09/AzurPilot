import time
from datetime import timedelta
from typing import TYPE_CHECKING

import module.config.server as server
from module.base.button import Button
from module.base.decorator import cached_property
from module.base.utils import *
from module.logger import logger
from module.ocr.rpc import ModelProxyFactory
from module.webui.setting import State

if TYPE_CHECKING:
    from module.ocr.al_ocr import AlOcr

if not State.deploy_config.UseOcrServer:
    from module.ocr.models import OCR_MODEL
else:
    OCR_MODEL = ModelProxyFactory()


class Ocr:
    SHOW_LOG = True
    SHOW_REVISE_WARNING = False

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet=None, name=None):
        """初始化 OCR 识别器。

        Args:
            buttons: OCR 区域，支持 Button、坐标元组、Button 列表或坐标元组列表。
            lang: 语言模型，'azur_lane' 或 'cnocr'。
            letter: 字母 RGB 颜色值元组。
            threshold: 二值化阈值。
            alphabet: 字母白名单。
            name: 识别器名称。
        """
        self.name = str(buttons) if isinstance(buttons, Button) else name
        self._buttons = buttons
        self.letter = letter
        self.threshold = threshold
        self.alphabet = alphabet
        self.lang = lang
        if lang == 'azur_lane' and server.server in ['jp']:
            self.lang = 'azur_lane_' + server.server

    @property
    def cnocr(self) -> "AlOcr":
        return OCR_MODEL.__getattribute__(self.lang)

    @property
    def buttons(self):
        buttons = self._buttons
        buttons = buttons if isinstance(buttons, list) else [buttons]
        buttons = [button.area if isinstance(button, Button) else button for button in buttons]
        return buttons

    @buttons.setter
    def buttons(self, value):
        self._buttons = value

    def pre_process(self, image):
        """图像预处理，提取字母颜色通道。

        Args:
            image: 输入图像，形状为 (height, width, channel)。

        Returns:
            处理后的灰度图像，形状为 (width, height)。
        """
        image = extract_letters(image, letter=self.letter, threshold=self.threshold)

        return image.astype(np.uint8)

    def after_process(self, result):
        """OCR 结果后处理。

        Args:
            result: OCR 识别结果字符串。

        Returns:
            处理后的结果字符串。
        """
        return result

    def ocr(self, image, direct_ocr=False):
        """执行 OCR 识别。

        Args:
            image: 输入图像或图像列表。
            direct_ocr: 为 True 时跳过区域裁剪，直接对整图预处理。

        Returns:
            识别结果字符串或结果列表。
        """
        start_time = time.time()

        if direct_ocr:
            image_list = [self.pre_process(i) for i in image]
        else:
            image_list = [self.pre_process(crop(image, area)) for area in self.buttons]
        
        image_list = [crop_to_text(i) for i in image_list]

        # 调试用：显示送入 OCR 模型的图像
        # self.cnocr.debug(image_list)

        result_list = self.cnocr.atomic_ocr_for_single_lines(image_list, self.alphabet)
        result_list = [''.join(result) for result in result_list]
        result_list = [self.after_process(result) for result in result_list]

        if len(self.buttons) == 1:
            result_list = result_list[0]
        if self.SHOW_LOG:
            logger.attr(name='%s %ss' % (self.name, float2str(time.time() - start_time)),
                        text=str(result_list))

        return result_list


class OcrYuv(Ocr):
    """在 YUV 色彩空间的 Y 通道中执行 OCR 识别。"""

    @cached_property
    def letter_y(self):
        arr = np.array([[self.letter]], dtype=np.uint8)
        y = rgb2luma(arr)[0][0]
        return y

    def pre_process(self, image):
        """在 YUV 色彩空间中预处理图像，提取 Y 通道差异。

        Args:
            image: 输入图像，形状为 (height, width, channel)。

        Returns:
            Y 通道差异图像，形状为 (width, height)。
        """
        y = rgb2luma(image)
        letter_y = (np.ones(y.shape) * self.letter_y).astype(np.uint8)
        diff = cv2.absdiff(y, letter_y)
        diff = cv2.multiply(diff, 255.0 / self.threshold)
        return diff


class Digit(Ocr):
    """数字 OCR 识别器，识别如 `45` 这样的数字。

    ocr() 方法返回 int 或 int 列表。
    """

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789IDSB',
                 name=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')

        prev = result
        result = int(result) if result else 0
        if self.SHOW_REVISE_WARNING:
            if str(result) != prev:
                logger.warning(f'OCR {self.name}: Result "{prev}" is revised to "{result}"')

        return result


class DigitYuv(Digit, OcrYuv):
    pass


class DigitCounter(Ocr):
    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789/IDSB',
                 name=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')
        return result

    def ocr(self, image, direct_ocr=False):
        """识别计数器格式的数字，如 `14/15`，返回当前值、剩余值和总数。

        注意：DigitCounter 仅支持对单个按钮区域执行 OCR。

        Args:
            image: 输入图像。
            direct_ocr: 为 True 时跳过区域裁剪，直接对整图预处理。

        Returns:
            三元组 (current, remain, total)，分别为当前值、剩余值和总数。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        result = result_list[0] if isinstance(result_list, list) else result_list

        result = re.search(r'(\d+)/(\d+)', result)
        if result:
            result = [int(s) for s in result.groups()]
            current, total = int(result[0]), int(result[1])
            current = min(current, total)
            return current, total - current, total
        else:
            logger.warning(f'Unexpected ocr result: {result_list}')
            return 0, 0, 0


class DigitCounterYuv(DigitCounter, OcrYuv):
    pass


class Duration(Ocr):
    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='0123456789:IDSB',
                 name=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet, name=name)

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')
        return result

    def ocr(self, image, direct_ocr=False):
        """识别时长格式的文本，如 `01:30:00`。

        Args:
            image: 输入图像。
            direct_ocr: 为 True 时跳过区域裁剪，直接对整图预处理。

        Returns:
            timedelta 对象或 timedelta 列表。
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if not isinstance(result_list, list):
            result_list = [result_list]
        result_list = [self.parse_time(result) for result in result_list]
        if len(self.buttons) == 1:
            result_list = result_list[0]
        return result_list

    @staticmethod
    def parse_time(string):
        """解析时长字符串为 timedelta 对象。

        Args:
            string: 时长字符串，如 `01:30:00`。

        Returns:
            解析后的 timedelta 对象。
        """
        result = re.search(r'(\d{1,2}):?(\d{2}):?(\d{2})', string)
        if result:
            result = [int(s) for s in result.groups()]
            return timedelta(hours=result[0], minutes=result[1], seconds=result[2])
        else:
            logger.warning(f'Invalid duration: {string}')
            return timedelta(hours=0, minutes=0, seconds=0)


class DurationYuv(Duration, OcrYuv):
    pass
