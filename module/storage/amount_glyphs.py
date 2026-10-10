"""仓库数量的原生灰度字形匹配，保留抗锯齿和固定字高。"""

from pathlib import Path

import cv2
import numpy as np

GLYPH_HEIGHT = 24
GLYPH_WIDTH = 20


def native_glyph(image, x, width, baseline):
    """以基线锚定原生画布，不随二值包围盒的 18/19px 跳变缩放数字。"""
    canvas = np.full((GLYPH_HEIGHT, GLYPH_WIDTH), 255, dtype=np.uint8)
    left = x + (width - GLYPH_WIDTH) // 2
    top = baseline - 22
    x0, x1 = max(0, x - 1, left), min(image.shape[1], x + width + 1, left + GLYPH_WIDTH)
    y0, y1 = max(0, top), min(image.shape[0], top + GLYPH_HEIGHT)
    canvas[y0 - top:y1 - top, x0 - left:x1 - left] = image[y0:y1, x0:x1]
    return canvas


class StorageAmountGlyphs:
    """灰度采样相位模板，仅作为完整单字形不确定时的严格补充。"""

    MAX_ERROR = .006
    MIN_MARGIN = .006

    def __init__(self, path):
        atlas = cv2.imread(str(Path(path)), cv2.IMREAD_GRAYSCALE)
        if atlas is None or atlas.shape[1] != 10 * GLYPH_WIDTH or atlas.shape[0] % GLYPH_HEIGHT:
            raise ValueError('仓库灰度数量模板缺失或尺寸无效')
        masks = []
        offsets = []
        for digit in range(10):
            offsets.append(len(masks))
            for y in range(0, atlas.shape[0], GLYPH_HEIGHT):
                glyph = atlas[y:y + GLYPH_HEIGHT, digit * GLYPH_WIDTH:(digit + 1) * GLYPH_WIDTH]
                if np.any(glyph < 250):
                    masks.append((255 - glyph.astype(np.float32)).ravel() / 255)
            if len(masks) == offsets[-1]:
                raise ValueError(f'仓库灰度数量模板缺少数字 {digit}')
        self.masks = np.stack(masks)
        self.offsets = np.array(offsets)
        self.norms = np.mean(self.masks * self.masks, axis=1)

    def _errors(self, glyph):
        """返回每种数字的最小模板误差，保留统一的候选比较范围。"""
        vector = (255 - glyph.astype(np.float32)).ravel() / 255
        # 小矩阵不调度多线程 BLAS，避免每个数字产生线程开销。
        errors = self.norms + np.mean(vector * vector) - 2 * np.einsum('ij,j->i', self.masks, vector) / vector.size
        return np.minimum.reduceat(np.maximum(errors, 0), self.offsets)

    def classify(self, glyph):
        """完整字形允许有界采样对齐，误差及次优数字差距门槛保持不变。"""
        errors = self._errors(glyph)
        first, second = np.argsort(errors)[:2]
        if errors[first] < self.MAX_ERROR and errors[second] - errors[first] > self.MIN_MARGIN:
            return int(first)
        # 不同设备的抗锯齿会让二值基线偏移一个像素；固定画布无需重新训练数字。
        # 只平移完整字形，不缩放或删除笔画；所有数字比较相同的有限采样相位。
        for dx in (-1., -.5, 0., .5, 1.):
            for dy in (-1., -.5, 0., .5, 1.):
                if dx == dy == 0:
                    continue
                shifted = cv2.warpAffine(glyph, np.array([[1, 0, dx], [0, 1, dy]], dtype=np.float32),
                                         (GLYPH_WIDTH, GLYPH_HEIGHT), flags=cv2.INTER_LINEAR, borderValue=255)
                errors = np.minimum(errors, self._errors(shifted))
        first, second = np.argsort(errors)[:2]
        if errors[first] < self.MAX_ERROR and errors[second] - errors[first] > self.MIN_MARGIN:
            return int(first)
        return None
