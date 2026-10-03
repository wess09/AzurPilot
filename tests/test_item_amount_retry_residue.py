"""数量 OCR 读数为 0 时「未裁剪重试」的残影规则。

真实截图实测（2026-10-04 大世界行动力弹窗，
`log/error/alas/1791060276929/2026-10-04_04-44-36-984706.png`）：

- 四个道具格的数量都压在格子右下角，数量框左侧还带着图标底衬的中灰残影；
- `crop_to_text` 按 `image < 120` 求外接框，会把浅于阈值的残影裁掉，
  所以裁剪版读数正常，问题出在读数为 0 时改用未裁剪图像兜底重试的那一步；
- 实测空白能源补给箱（大）的 `0` 被拼成 `70`：100 点的箱子被算成 7000 点，
  大世界总行动力从 25 变成 7025，任务随即卡在「道具不足」的「使用」按钮上，
  最终以 GameTooManyClickError 收场。

结论：重试仍要用未裁剪图像（保住被数量框右边界切掉的笔画），但送进模型前
必须先抹掉远离数字本体的残影；`erase_distant_residue` 只改像素、不改画布尺寸。
"""
import unittest

import numpy as np

from module.statistics.item import AmountOcr, erase_distant_residue

HEIGHT, WIDTH = 22, 36
INK = 0
RESIDUE = 160
BACKGROUND = 255


def blank():
    """构造与真实数量框等大的背景画布。"""
    return np.full((HEIGHT, WIDTH), BACKGROUND, dtype=np.uint8)


def draw(image, rows, cols, value):
    """在画布上画一个矩形色块。"""
    image[rows[0]:rows[1], cols[0]:cols[1]] = value
    return image


class StubCnocr:
    """按送入模型图像的宽度与残影带复现该数量框的真实读数。"""

    def __init__(self):
        self.calls = []

    def atomic_ocr_for_single_lines(self, images, alphabet):
        image = images[0]
        self.calls.append(image)
        if image.shape[1] < WIDTH:
            # 裁剪版：残影被 crop_to_text 削掉，但空白箱的 0 也丢笔画读成空
            return ['']
        # 未裁剪版：残影还在就会被拼成首位 7，抹掉后才读回 0
        return ['70' if (image[:, :15] < 200).any() else '0']


class TestEraseDistantResidue(unittest.TestCase):
    def test_erases_residue_far_from_digits_and_keeps_canvas(self):
        image = blank()
        draw(image, (6, 16), (24, 34), INK)       # 数字本体 0
        draw(image, (6, 16), (3, 15), RESIDUE)    # 距本体 9px 以上的图标残影

        result = erase_distant_residue(image, margin=4)

        self.assertEqual(result.shape, image.shape)
        self.assertEqual(result.dtype, image.dtype)
        self.assertEqual(int(result[:, :20].max()), BACKGROUND)      # 残影被抹掉
        self.assertTrue(np.array_equal(result[6:16, 24:34], image[6:16, 24:34]))
        self.assertTrue(np.array_equal(result[6:16, 20:24], image[6:16, 20:24]))

    def test_keeps_antialias_fringe_inside_margin(self):
        image = blank()
        draw(image, (6, 16), (10, 21), INK)  # 本体最右侧第 20 列
        image[6:16, 24] = RESIDUE            # 距本体 4px：margin 内，保留
        image[6:16, 25] = RESIDUE            # 距本体 5px：margin 外，抹掉

        result = erase_distant_residue(image, margin=4)

        self.assertEqual(int(result[10, 24]), RESIDUE)
        self.assertEqual(int(result[10, 25]), BACKGROUND)

    def test_returns_unchanged_without_ink(self):
        image = blank()
        draw(image, (0, HEIGHT), (0, WIDTH), 200)  # 全是浅于阈值的残影

        result = erase_distant_residue(image, margin=4)

        self.assertTrue(np.array_equal(result, image))

    def test_threshold_matches_crop_to_text(self):
        image = blank()
        draw(image, (6, 16), (24, 34), INK)
        draw(image, (6, 16), (3, 15), 119)  # 刚低于阈值，算本体

        result = erase_distant_residue(image, margin=4)

        self.assertEqual(int(result[10, 3]), 119)


class StubEmptyCnocr:
    def atomic_ocr_for_single_lines(self, images, alphabet):
        return ['']


class StubbedAmountOcr(AmountOcr):
    """把底层模型换成 StubCnocr 的 AmountOcr，避免测试依赖 OCR 服务。"""

    def __init__(self, stub):
        super().__init__([], threshold=96, name='test_amount_ocr')
        self._stub = stub

    @property
    def cnocr(self):
        return self._stub


class TestZeroReadRetry(unittest.TestCase):
    def setUp(self):
        self.stub = StubCnocr()
        self.ocr = StubbedAmountOcr(self.stub)
        self.pre = blank()
        draw(self.pre, (6, 16), (24, 34), INK)     # 空白补给箱的 0
        draw(self.pre, (6, 16), (3, 15), RESIDUE)  # 图标残影
        self.ocr.pre_process = lambda image: self.pre

    def test_retry_image_is_residue_erased(self):
        amount = self.ocr.ocr_with_validation(None, item_name='box', direct_ocr=True)

        self.assertEqual(len(self.stub.calls), 2)
        retry_image = self.stub.calls[1]
        self.assertEqual(retry_image.shape, (HEIGHT, WIDTH))
        self.assertEqual(int(retry_image[:, :20].max()), BACKGROUND)
        self.assertEqual(amount, 0)

    def test_retry_keeps_zero_when_model_reads_nothing(self):
        self.ocr._stub = StubEmptyCnocr()
        amount = self.ocr.ocr_with_validation(None, item_name='box', direct_ocr=True)

        self.assertEqual(amount, 0)

    def test_trim_disabled_skips_retry(self):
        self.ocr.ocr_with_validation(None, item_name='box', direct_ocr=True, trim=False)

        self.assertEqual(len(self.stub.calls), 1)


if __name__ == '__main__':
    unittest.main()
