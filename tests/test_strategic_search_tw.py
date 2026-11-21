"""台服计划作战面板选项定位的离线回归测试。

台服的「是/否」选项比国服靠上，若沿用国服坐标会漏检绿色勾选，
导致 ``strategic_search_set_option()`` 在等待「遭遇装置」时卡死。
"""

import unittest

import numpy as np
from PIL import Image

import module.config.server as server
from module.base.resource import Resource
from module.base.utils import crop, image_color_count
from module.os_handler.assets import STRATEGIC_SEARCH_DEVICE_CHECK, STRATEGIC_SEARCH_DEVICE_STOP
from module.os_handler.assets import STRATEGIC_SEARCH_DEVICE_CONTINUE

GREEN = (156, 255, 82)
TW_STOP_AREA = (443, 370, 463, 384)
TW_CONTINUE_AREA = (516, 370, 536, 384)
# 台服绿色勾选图标的实际像素形状，共 94 个像素。
CHECK_PATTERN = (
    '................###.',
    '...............#####',
    '..............######',
    '..............#####.',
    '............######..',
    '.##........######...',
    '####......######....',
    '#####....######.....',
    '.######.######......',
    '...#########........',
    '...#########........',
    '.....#####..........',
    '.....####...........',
    '.......#............',
)


class TestStrategicSearchTaiwanLayout(unittest.TestCase):
    def setUp(self):
        self._previous_server = server.server
        server.server = 'tw'
        self.release_assets()

    def tearDown(self):
        server.server = self._previous_server
        self.release_assets()

    @staticmethod
    def release_assets():
        for obj in Resource.instances.values():
            obj.resource_release()

    def build_panel(self, selected=True):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        template = np.array(Image.open(STRATEGIC_SEARCH_DEVICE_CHECK.file).convert('RGB'))
        x1, y1, x2, y2 = STRATEGIC_SEARCH_DEVICE_CHECK.area
        image[y1:y2, x1:x2] = template[y1:y2, x1:x2]
        if selected:
            self.draw_check(image, TW_STOP_AREA)
        return image

    @staticmethod
    def draw_check(image, area):
        x1, y1, x2, y2 = area
        mask = np.array([[char == '#' for char in row] for row in CHECK_PATTERN])
        image[y1:y2, x1:x2][mask] = GREEN

    def locate_options(self, image):
        self.assertTrue(STRATEGIC_SEARCH_DEVICE_CHECK.match(image, offset=(20, 200), similarity=0.7))
        STRATEGIC_SEARCH_DEVICE_STOP.load_offset(STRATEGIC_SEARCH_DEVICE_CHECK)
        STRATEGIC_SEARCH_DEVICE_CONTINUE.load_offset(STRATEGIC_SEARCH_DEVICE_CHECK)
        stop = image_color_count(crop(image, STRATEGIC_SEARCH_DEVICE_STOP.button), GREEN, 30, 30)
        cont = image_color_count(crop(image, STRATEGIC_SEARCH_DEVICE_CONTINUE.button), GREEN, 30, 30)
        return stop, cont

    def test_tw_detects_selected_stop(self):
        stop, cont = self.locate_options(self.build_panel(selected=True))
        self.assertTrue(stop)
        self.assertFalse(cont)

    def test_tw_detects_selected_continue(self):
        image = self.build_panel(selected=False)
        self.draw_check(image, TW_CONTINUE_AREA)
        stop, cont = self.locate_options(image)
        self.assertFalse(stop)
        self.assertTrue(cont)

    def test_tw_assets_differ_from_cn(self):
        self.assertEqual(STRATEGIC_SEARCH_DEVICE_STOP.raw_button['tw'][1], 370)
        self.assertEqual(STRATEGIC_SEARCH_DEVICE_CONTINUE.raw_button['tw'][1], 370)


if __name__ == '__main__':
    unittest.main()
