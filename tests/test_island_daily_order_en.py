"""EN Island Requests: the right panel's "Compiling Requests" state is recognised.

Fixtures are the right panel (840, 60, 1260, 710) of live EN 1280x720 screenshots, pasted back
onto a black frame at their original position:
- compiling.png: a declined request slot, "Compiling Requests / New Requests Ready in 00:09:10";
- request.png: a request with Decline / Accept buttons.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import module.config.server as server

server.server = 'en'

from module.base.button import Button
from module.base.utils import load_image
from module.island.island_daily_order import IslandDailyOrder
import module.island_daily_order.assets as order_assets

FIXTURES = Path(__file__).parent / 'fixtures' / 'island_daily_order_en'


def frame(name):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[60:710, 840:1260] = load_image(str(FIXTURES / name))
    return image


def fresh(button):
    """Rebuild a button for the current server in case another test loaded it as cn."""
    return Button(area=button.raw_area, color=button.raw_color, button=button.raw_button,
                  file=button.raw_file, name=button.raw_name)


def order(image):
    obj = object.__new__(IslandDailyOrder)
    obj.device = SimpleNamespace(image=image, stuck_record_add=lambda b: None)
    obj.interval_timer = {}
    obj.config = SimpleNamespace(SERVER='en', BUTTON_OFFSET=30)
    return obj


class DailyOrderEnTest(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self._server

    def test_compiling_panel_is_preparing(self):
        o = order(frame('compiling.png'))
        self.assertTrue(o.appear(fresh(order_assets.DAILY_ORDER_PREPARING)))
        self.assertFalse(o.appear(fresh(order_assets.DAILY_ORDER_REJECT)))
        self.assertEqual(o._ocr_cooldown_seconds(), 9 * 60 + 10)

    def test_request_panel_is_not_preparing(self):
        o = order(frame('request.png'))
        self.assertFalse(o.appear(fresh(order_assets.DAILY_ORDER_PREPARING)))
        self.assertTrue(o.appear(fresh(order_assets.DAILY_ORDER_REJECT)))


if __name__ == '__main__':
    unittest.main()
