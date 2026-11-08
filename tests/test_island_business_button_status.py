"""经营列表按钮颜色分类的离线回归测试。

颜色取自国际服实机截图中按钮区域 (1020, y, 1154, y+27) 的平均色：
- 「开始经营 (1/1)」蓝色：(98, 202, 255)
- 「查看」深蓝（经营中，带倒计时）：(62, 69, 85)
- 「休息中 (0/1)」灰色（当日次数已用完，没有倒计时）：(133, 133, 131)

原阈值 80 会把灰色按钮判成深蓝，经营任务因此认为商店仍在经营，
去 OCR 不存在的倒计时并失败，只能按默认时间反复回来检查。
"""
import unittest
from types import SimpleNamespace

import numpy as np

from module.island.island_business import IslandBusiness

RECT = (1020, 356, 1154, 383)


def classify(color):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    x1, y1, x2, y2 = RECT
    image[y1:y2, x1:x2] = color
    business = object.__new__(IslandBusiness)
    business.device = SimpleNamespace(image=image)
    return business._detect_button_at(RECT)


class BusinessButtonStatusTest(unittest.TestCase):
    def test_on_break_button_is_gray(self):
        self.assertEqual(classify((133, 133, 131)), 'gray')

    def test_inspect_button_is_darkblue(self):
        self.assertEqual(classify((62, 69, 85)), 'darkblue')

    def test_start_button_is_blue(self):
        self.assertEqual(classify((98, 202, 255)), 'blue')

    def test_claim_button_is_yellow(self):
        self.assertEqual(classify((230, 192, 71)), 'yellow')


if __name__ == "__main__":
    unittest.main()
