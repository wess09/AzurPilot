"""海域里程 OCR 识别模块。

识别大世界中的海域里程（Sea Miles）数值。
海域里程是大世界的特殊货币，用于在港口商店购买物品。

继承自 Digit，复用数字 OCR 识别能力。
"""

from module.logger import logger
from module.ocr.ocr import Digit
from module.os_handler.assets import MARITIME_SCHEDULE


class SeaMilesOCR(Digit):
    """海域里程 OCR 识别器。

    识别范围 0-100000000，超出范围时返回 0。
    """
    def __init__(self):
        """初始化海域里程识别器。"""
        super().__init__(
            buttons=MARITIME_SCHEDULE,
            lang='azur_lane',
            letter=(255, 207, 66),
            threshold=128,
            alphabet='0123456789',
            name='SEA_MILES'
        )

    def after_process(self, result):
        """后处理校验里程数值范围。

        Args:
            result (str): 识别结果字符串。

        Returns:
            int: 校验后的里程数值，超出 0-100000000 时返回 0。
        """
        result = super().after_process(result)
        if not (0 <= result <= 100000000):
            logger.warning(f"[大世界-里程] 异常的出海里程: {result}")
            return 0
        return result


OCR_SEA_MILES_DIGIT = SeaMilesOCR()
