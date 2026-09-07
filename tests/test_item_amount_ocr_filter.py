"""remove_small_fragments 单元测试。

覆盖：图标碎块过滤、数字笔画保留、空白图像、全碎块图像等场景。
"""
import unittest

import numpy as np

from module.statistics.item import remove_small_fragments


class TestRemoveSmallFragments(unittest.TestCase):
    def _make_image(self, height=21, width=41):
        return np.full((height, width), 255, dtype=np.uint8)

    def test_digit_strokes_are_kept(self):
        """高数字笔画（h>=6）应保留。"""
        image = self._make_image()
        # 两个竖笔画，高 14，模拟 "11"
        image[4:18, 25:28] = 0
        image[4:18, 33:36] = 0
        result = remove_small_fragments(image)
        self.assertEqual((result[4:18, 25:28] == 0).all(), True)
        self.assertEqual((result[4:18, 33:36] == 0).all(), True)

    def test_small_fragments_are_removed(self):
        """低碎块（h<6）应被置为背景。"""
        image = self._make_image()
        image[2:4, 3:8] = 0  # h=2 的碎块
        image[0:3, 13:17] = 0  # h=3 的碎块
        result = remove_small_fragments(image)
        self.assertEqual((result == 255).all(), True)

    def test_mixed_fragments_and_digits(self):
        """混合场景：碎块剔除、数字保留，其余为背景。"""
        image = self._make_image()
        image[2:5, 4:9] = 0  # 碎块
        image[4:18, 20:26] = 0  # 数字笔画
        result = remove_small_fragments(image)
        self.assertEqual((result[2:5, 4:9] == 255).all(), True)
        self.assertEqual((result[4:18, 20:26] == 0).all(), True)

    def test_empty_image(self):
        """空白图像不崩溃，返回全背景。"""
        image = self._make_image()
        result = remove_small_fragments(image)
        self.assertEqual((result == 255).all(), True)

    def test_all_fragments_image_becomes_blank(self):
        """全部组件都是碎块时，输出为全背景。"""
        image = self._make_image()
        image[0:2, 0:2] = 0
        image[5:7, 10:13] = 0
        result = remove_small_fragments(image)
        self.assertEqual((result == 255).all(), True)

    def test_small_pieces_near_digit_are_kept(self):
        """靠近大组件的小组件视为字形部件保留（如 7 的顶横）。"""
        image = self._make_image()
        image[4:18, 25:38] = 0  # 数字主体
        image[0:3, 33:39] = 0  # 顶部小横（距主体 1px）
        image[11:19, 38:41] = 0  # 右侧小竖（紧贴主体）
        result = remove_small_fragments(image)
        self.assertEqual((result[0:3, 33:39] == 0).all(), True)
        self.assertEqual((result[11:19, 38:41] == 0).all(), True)

    def test_far_fragments_still_removed_even_near_digit(self):
        """远离主体的碎片仍被删除，靠近主体的保留，两者互不干扰。"""
        image = self._make_image()
        image[4:18, 25:38] = 0  # 数字主体
        image[2:5, 4:9] = 0  # 远处碎片（x 距离 > keep_margin）
        image[0:3, 33:39] = 0  # 近处部件
        result = remove_small_fragments(image)
        self.assertEqual((result[2:5, 4:9] == 255).all(), True)
        self.assertEqual((result[0:3, 33:39] == 0).all(), True)

    def test_gray_pixels_preserved_by_default(self):
        """默认只删除碎片像素，中灰像素（字形抗锯齿边缘）保留。"""
        image = self._make_image()
        image[4:18, 25:38] = 0  # 数字主体
        image[10:15, 4:9] = 180  # 中灰像素，不属于任何组件
        result = remove_small_fragments(image)
        self.assertEqual(result[10:15, 4:9].tolist(), image[10:15, 4:9].tolist())

    def test_fill_background_erases_gray(self):
        """fill_background=True 时非保留像素全部置为背景。"""
        image = self._make_image()
        image[4:18, 25:38] = 0
        image[10:15, 4:9] = 180
        result = remove_small_fragments(image, fill_background=True)
        self.assertEqual((result[10:15, 4:9] == 255).all(), True)
        self.assertEqual((result[4:18, 25:38] == 0).all(), True)

    def test_flat_bar_left_of_digit_removed(self):
        """悬在数字左侧、无水平重叠的扁平横条（面积大）按图标残影删除。

        复现：数字 1 左侧的图标横条使 1 被 OCR 拼读成 7。
        """
        image = self._make_image()
        image[3:19, 25:28] = 0  # 数字 1 的竖笔画（h=16 大组件）
        image[0:6, 6:23] = 0  # 左侧扁平横条（h=6 面积大，距数字 2px）
        result = remove_small_fragments(image, min_height=15, min_area=30,
                                        max_digit_gap=10)
        self.assertEqual((result[0:6, 6:23] == 255).all(), True)
        self.assertEqual((result[3:19, 25:28] == 0).all(), True)

    def test_tiny_speck_touching_digit_kept(self):
        """紧贴数字的小像素斑点（衬线等抗锯齿部件）必须保留。"""
        image = self._make_image()
        image[3:19, 25:28] = 0  # 数字 1 的竖笔画（h=16 大组件）
        image[10:12, 23:25] = 0  # 紧贴数字左侧的 2x2 斑点
        result = remove_small_fragments(image, min_height=15, min_area=30,
                                        max_digit_gap=10)
        self.assertEqual((result[10:12, 23:25] == 0).all(), True)
        self.assertEqual((result[3:19, 25:28] == 0).all(), True)

    def test_input_is_not_mutated(self):
        """不应修改输入图像。"""
        image = self._make_image()
        image[2:5, 4:9] = 0
        snapshot = image.copy()
        remove_small_fragments(image)
        self.assertEqual((image == snapshot).all(), True)


if __name__ == "__main__":
    unittest.main()
