"""船坞原生等级字形：Lv 锚点确定数字位数，严格模板与 OCR 互补。"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from module.base.utils import extract_white_letters
from module.storage.amount_glyphs import GLYPH_HEIGHT, GLYPH_WIDTH, StorageAmountGlyphs


def prepare_level(raw, prefix, threshold=96):
    """在 720p 原生像素上定位 Lv，避免固定去前缀时截掉百位。"""
    gray = extract_white_letters(raw, threshold=threshold)
    # 灰度相关保留缩小截图的抗锯齿；二值阈值会丢失 Lv 的细笔画。
    mask = (255 - gray).astype(np.float32) / 255
    matches = cv2.matchTemplate(mask, prefix.astype(np.float32), cv2.TM_CCOEFF_NORMED)
    valid = np.full_like(matches, -1)
    valid[2:10, 4:31] = matches[2:10, 4:31]
    # 平坦背景的归一化相关无定义，OpenCV 浮点误差可能给全零块高分。
    # 先排除零方差窗口，再选择 Lv，不能让立绘空白冒充三位数锚点。
    sums, squares = cv2.integral2(mask)
    height, width = prefix.shape
    total = sums[height:, width:] - sums[:-height, width:] - sums[height:, :-width] + sums[:-height, :-width]
    energy = squares[height:, width:] - squares[:-height, width:] - squares[height:, :-width] + squares[:-height, :-width]
    valid[energy - total * total / (height * width) <= 1e-6] = -1
    _, score, _, (x, y) = cv2.minMaxLoc(valid)
    count = round((57 - x - 19) / 10.5)
    if score < .5 or not 1 <= count <= 3 or y + 19 > gray.shape[0]:
        return [], np.full((23, 42), 255, np.uint8), raw
    glyphs = []
    for index in range(count):
        left, right = x + 19 + round(index * 10.5), x + 19 + round((index + 1) * 10.5)
        cell = gray[y:y + 19, left:right]
        canvas = np.full((GLYPH_HEIGHT, GLYPH_WIDTH), 255, np.uint8)
        offset = (GLYPH_WIDTH - cell.shape[1]) // 2
        canvas[2:21, offset:offset + cell.shape[1]] = cell
        glyphs.append(canvas)
    clean = cv2.copyMakeBorder(gray[y:y + 19, x + 19:57], 2, 2, 2, 2,
                               cv2.BORDER_CONSTANT, value=255)
    return glyphs, clean, raw[y:y + 19, x + 19:57]


class DockLevelReader:
    """复用仓库数字的原生灰度匹配器，使用独立的实机船坞字体模板。"""
    def __init__(self):
        root = Path(__file__).parents[2] / 'assets/ship'
        self.prefix = np.array(Image.open(root / 'dock_level_prefix.png').convert('L')) < 120
        self.glyphs = StorageAmountGlyphs(root / 'dock_level_digits.png')

    def prepare(self, raw):
        return prepare_level(raw, self.prefix)

    def read(self, glyphs):
        digits = [self.glyphs.classify(glyph) for glyph in glyphs]
        if not digits or any(digit is None for digit in digits) or digits[0] == 0:
            return 0
        value = int(''.join(map(str, digits)))
        return value if 1 <= value <= 125 else 0

    def reread(self, raw, digit_count):
        """背景干扰时核实两种白字提取；模板误差及候选差距门槛不变。"""
        reads = []
        for threshold in (80, 88):
            glyphs, _, _ = prepare_level(raw, self.prefix, threshold=threshold)
            if len(glyphs) != digit_count:
                return 0
            reads.append(self.read(glyphs))
        return reads[0] if reads[0] and len(set(reads)) == 1 else 0


@lru_cache(maxsize=1)
def dock_level_reader():
    return DockLevelReader()
