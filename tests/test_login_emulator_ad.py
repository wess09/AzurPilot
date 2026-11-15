"""离线验证 MuMu 模拟器全屏广告的识别与关闭。

夹具是实机截图右上角 (880, 30, 1280, 180) 的裁剪，贴回 1280×720 黑底上：
两种不同广告（2026-11-07、2026-11-03）和一张没有广告的游戏画面。
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import module.config.server as server

server.server = 'en'

from module.base.utils import load_image
from module.handler.login import LoginHandler

FIXTURES = Path(__file__).parent / 'fixtures' / 'emulator_ad'


def screen(name):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    if name:
        image[30:180, 880:1280] = load_image(str(FIXTURES / name))
    return image


def make_handler(image):
    handler = object.__new__(LoginHandler)
    handler.config = SimpleNamespace(SERVER='en', BUTTON_OFFSET=(30, 30))
    handler.device = Mock(image=image)
    handler.interval_timer = {}
    return handler


class EmulatorAdTests(unittest.TestCase):
    def test_ads_are_closed_at_the_x(self):
        for name in ('ad_goddess.png', 'ad_pirates.png'):
            with self.subTest(name=name):
                handler = make_handler(screen(name))
                self.assertTrue(handler.handle_emulator_ad())
                button = handler.device.click.call_args[0][0]
                self.assertEqual(button.area, (1092, 81, 1116, 105))

    def test_no_ad_no_click(self):
        for name in ('no_ad.png', None):
            with self.subTest(name=name):
                handler = make_handler(screen(name))
                self.assertFalse(handler.handle_emulator_ad())
                handler.device.click.assert_not_called()

    def test_interval_prevents_repeat_clicks(self):
        handler = make_handler(screen('ad_goddess.png'))
        self.assertTrue(handler.handle_emulator_ad())
        self.assertFalse(handler.handle_emulator_ad())
        self.assertEqual(handler.device.click.call_count, 1)


if __name__ == '__main__':
    unittest.main()
