"""EN Island Requests: the right panel's "Compiling Requests" state is recognised.

Fixtures are the right panel (840, 60, 1260, 710) of live EN 1280x720 screenshots, pasted back
onto a black frame at their original position:
- compiling.png: a declined request slot, "Compiling Requests / New Requests Ready in 00:09:10";
- request.png: a request with Decline / Accept buttons;
- map.png: the request map (0, 0, 850, 720) with three WAITING slots, a miner request near the right
  panel and Peary's seasonal (trophy) request.
"""
from unittest import mock
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


def map_frame():
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:, 0:850] = load_image(str(FIXTURES / 'map.png'))
    return image


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



class DailyOrderMarkerTest(unittest.TestCase):
    def test_markers_found_on_the_whole_map(self):
        o = order(map_frame())
        markers = o._find_markers()
        found = {label: [] for _, label in markers}
        for pos, label in markers:
            found[label].append(pos)

        def has(label, x, y):
            return any(abs(px - x) <= 5 and abs(py - y) <= 5 for px, py in found.get(label, []))

        # WAITING slots, including the one that scored under the old 0.85 similarity
        self.assertTrue(has('挑战', 278, 96))
        self.assertTrue(has('挑战', 396, 115))
        self.assertTrue(has('挑战', 668, 418))
        # miner request next to the right panel (badge scores ~0.76)
        self.assertTrue(has('挑战', 814, 360))
        self.assertTrue(has('季节', 558, 397))
        self.assertEqual(len(markers), 5)

    def test_markers_rescanned_after_every_tap(self):
        """A marker that moves after a tap is tapped at its new position, and the pass still ends."""
        o = order(None)
        scans = iter([
            [((100, 200), '挑战'), ((500, 300), '挑战')],
            [((100, 200), '挑战'), ((620, 420), '挑战')],  # second marker moved
            [((100, 200), '挑战'), ((620, 420), '挑战')],
        ])
        clicks = []
        o._seasonal_tried = False
        o._seasonal_selected = False
        o.device = SimpleNamespace(screenshot=lambda: None, sleep=lambda s: None)
        with mock.patch.object(IslandDailyOrder, '_find_markers', lambda self: next(scans)),                 mock.patch.object(IslandDailyOrder, '_click_position', lambda self, x, y: clicks.append((x, y))),                 mock.patch.object(IslandDailyOrder, '_is_preparing', lambda self: True):
            self.assertEqual(o._step_challenge_easy(), 'to_step4')
        dx, dy = IslandDailyOrder.MARKER_TAP_OFFSET
        self.assertEqual(clicks, [(100 + dx, 200 + dy), (620 + dx, 420 + dy)])

    def test_seasonal_tapped_once_and_not_declined(self):
        o = order(None)
        o._seasonal_tried = False
        o._seasonal_selected = False
        o.device = SimpleNamespace(screenshot=lambda: None, sleep=lambda s: None)
        with mock.patch.object(IslandDailyOrder, '_find_markers', lambda self: [((558, 397), '季节')]),                 mock.patch.object(IslandDailyOrder, '_click_position', lambda self, x, y: None),                 mock.patch.object(IslandDailyOrder, '_is_preparing', lambda self: False),                 mock.patch.object(IslandDailyOrder, '_has_reject_button', lambda self: True),                 mock.patch.object(IslandDailyOrder, 'appear_then_click', lambda self, *a, **k: False):
            self.assertEqual(o._step_challenge_easy(), 'to_step2')
            self.assertTrue(o._seasonal_selected)
            # already tried this run: not tapped again
            self.assertEqual(o._step_challenge_easy(), 'to_step4')

        # ② with not enough items: no Decline tap
        o._first_right_panel_check = False
        rejected = []
        with mock.patch.object(IslandDailyOrder, '_is_right_panel_empty', lambda self: False),                 mock.patch.object(IslandDailyOrder, '_has_reject_button', lambda self: True),                 mock.patch.object(IslandDailyOrder, '_check_items_for_reject', lambda self: False),                 mock.patch.object(IslandDailyOrder, '_submit_order', lambda self, b: False),                 mock.patch.object(IslandDailyOrder, 'appear_then_click', lambda self, *a, **k: rejected.append(a)):
            self.assertEqual(o._step_right_panel(), 'to_step3')
        self.assertEqual(rejected, [])


if __name__ == '__main__':
    unittest.main()
