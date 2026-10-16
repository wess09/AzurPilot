"""国服扫描的严格船坞数量，不把 OCR 越界读数裁成容量。"""
import re

from module.logger import logger
from module.ocr.ocr import DigitCounter, Ocr
from module.retire.assets import DOCK_AMOUNT


class ScanDockAmount(DigitCounter):
    def __init__(self):
        x1, y1, x2, y2 = DOCK_AMOUNT.area
        # 通用区域还含“量:”和刷新图标；扫描只读中间原生数字区。
        super().__init__((x1 + 20, y1, x2 - 32, y2), letter=(255, 255, 255),
                         threshold=192, name='SCAN_DOCK_AMOUNT')

    def ocr(self, image, direct_ocr=False):
        """仅完整且未超容量的计数器有效，失败返回未确认的全零三元组。"""
        raw = Ocr.ocr(self, image, direct_ocr=direct_ocr)
        raw = raw[0] if isinstance(raw, list) and len(raw) == 1 else raw
        match = re.fullmatch(r'(\d+)/(\d+)', str(raw).strip())
        if match:
            current, total = map(int, match.groups())
            if total > 0 and 0 <= current <= total:
                return current, total - current, total
        logger.warning(f'扫描船坞数量未严格确认，拒绝裁剪为容量：{raw}')
        return 0, 0, 0


SCAN_DOCK_AMOUNT = ScanDockAmount()
