"""EN nursery seed shop: every seed, including Lavender in the second row, is found by icon search.

The fixture is a crop (220, 175, 1195, 615) of a live EN screenshot (seed cards only),
pasted back onto a black 1280x720 frame. The old EN Lavender picture was recorded at the
top-right slot, so the search never reached the real slot at the start of row 2 and every
purchase timed out with "item not found".
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import module.config.server as server

server.server = 'en'

from module.base.button import Button
from module.base.utils import load_image
from module.island.island import ISLAND_SHOP_ITEM_SEARCH_OFFSET, ISLAND_SHOP_ITEM_SIMILARITY, Island, shop_item_color_matches
import module.island_farm.assets as farm_assets

FIXTURE = Path(__file__).parent / 'fixtures' / 'island_seed_shop' / 'en_nursery_seeds.png'
# Card centres in the live screenshot: row 1 left to right, then Lavender alone in row 2.
EXPECTED = {
    'CARROT': (299, 265), 'ONION': (460, 265), 'FLAX': (623, 265), 'STRAWBERRY': (789, 265),
    'COTTON': (951, 265), 'TEA': (1115, 265), 'LAVENDER': (297, 492),
}


def fresh(button):
    """Rebuild the button for the current server in case another test loaded it as cn."""
    return Button(area=button.raw_area, color=button.raw_color, button=button.raw_button,
                  file=button.raw_file, name=button.raw_name)


class EnNurserySeedShopTest(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'en'
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[175:615, 220:1195] = load_image(str(FIXTURE))
        self.image = image
        island = object.__new__(Island)
        island.device = SimpleNamespace(image=image, stuck_record_add=lambda b: None)
        island.interval_timer = {}
        island.config = SimpleNamespace(SERVER='en', BUTTON_OFFSET=30)
        self.island = island

    def tearDown(self):
        server.server = self._server

    def test_every_seed_is_found_at_its_card(self):
        for name, (cx, cy) in EXPECTED.items():
            with self.subTest(seed=name):
                button = fresh(getattr(farm_assets, f'SHOP_SEED_{name}'))
                self.assertTrue(self.island.appear(button, offset=ISLAND_SHOP_ITEM_SEARCH_OFFSET,
                                                   similarity=ISLAND_SHOP_ITEM_SIMILARITY))
                self.assertTrue(shop_item_color_matches(button, self.image))
                x1, y1, x2, y2 = button.button
                self.assertLess(abs((x1 + x2) / 2 - cx), 30)
                self.assertLess(abs((y1 + y2) / 2 - cy), 30)


if __name__ == '__main__':
    unittest.main()
