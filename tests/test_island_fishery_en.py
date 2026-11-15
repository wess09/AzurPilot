"""EN fishery: every fish (including Black Porgy) is found in the product list and its fry shop tab.

Fixtures are crops of live EN 1280x720 screenshots with every fish unlocked, pasted back onto a
black frame at their original position:
- list_*.png: the Select Product list (166, 68, 478, 652) at different scroll positions;
- selected_black_porgy.png: the right-hand panel (700, 200, 890, 360) with Black Porgy selected;
- fry_*.png: the fry shop cards (220, 175, 1195, 395) for each tab;
- warehouse_owned.png: warehouse cards (280, 140, 860, 300) showing Koi Carp, Shrimp, Crayfish and Tuna.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import module.config.server as server

server.server = 'en'

from module.base.button import Button
from module.base.template import Template
from module.base.utils import crop, load_image
from module.island.island import ISLAND_SHOP_ITEM_SEARCH_OFFSET, ISLAND_SHOP_ITEM_SIMILARITY, Island, shop_item_color_matches
from module.island.island_fishery import FISH_MEAT_FISH_IDS, IslandFishery
from module.island.warehouse import WarehouseOCR
import module.island_fishery.assets as fishery_assets
from module.island_planner import settings_map

FIXTURES = Path(__file__).parent / 'fixtures' / 'island_fishery_en'
FISH = ['SHELL', 'CATFISH', 'KOI_CARP', 'COMMON_CARP', 'SHRIMP', 'CRAYFISH', 'BASS', 'CRAB', 'SQUID', 'MACKEREL',
        'TUNA', 'SALMON', 'RED_SEA_BREAM', 'BLACK_PORGY', 'YELLOWFIN_TUNA', 'SEA_CUCUMBER']
# Which fry shop tab each fish is in on EN (from the live shop)
FRY_TAB = {
    'CATFISH': 'freshwater', 'KOI_CARP': 'freshwater', 'COMMON_CARP': 'freshwater', 'BASS': 'freshwater',
    'MACKEREL': 'seawater', 'TUNA': 'seawater', 'SALMON': 'seawater', 'YELLOWFIN_TUNA': 'seawater',
    'RED_SEA_BREAM': 'seawater', 'BLACK_PORGY': 'seawater',
    'SHELL': 'other', 'SHRIMP': 'other', 'CRAYFISH': 'other', 'CRAB': 'other', 'SQUID': 'other',
    'SEA_CUCUMBER': 'other',
}


def frame(name, box):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    x1, y1, x2, y2 = box
    image[y1:y2, x1:x2] = load_image(str(FIXTURES / name))
    return image


def fresh(button):
    """Rebuild a button for the current server in case another test loaded it as cn."""
    if isinstance(button, Template):
        return Template(file=button.raw_file)
    return Button(area=button.raw_area, color=button.raw_color, button=button.raw_button,
                  file=button.raw_file, name=button.raw_name)


def island(image):
    obj = object.__new__(Island)
    obj.device = SimpleNamespace(image=image, stuck_record_add=lambda b: None)
    obj.interval_timer = {}
    obj.config = SimpleNamespace(SERVER='en', BUTTON_OFFSET=30)
    return obj


class FisheryEnPicturesTest(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self._server

    def test_every_fish_is_found_in_the_product_list(self):
        lists = [frame(f'list_{i}.png', (166, 68, 478, 652)) for i in (0, 1, 2, 3, 4, 6)]
        for fish in FISH:
            with self.subTest(fish=fish):
                button = fresh(getattr(fishery_assets, f'SELECT_{fish}'))
                found = any(island(image).match_template_color(button, offset=300, similarity=0.85, threshold=10)
                            for image in lists)
                self.assertTrue(found)

    def test_every_fish_is_found_in_its_fry_shop_tab(self):
        tabs = {tab: frame(f'fry_{tab}.png', (220, 175, 1195, 395)) for tab in ('freshwater', 'seawater', 'other')}
        for fish, tab in FRY_TAB.items():
            with self.subTest(fish=fish):
                button = fresh(getattr(fishery_assets, f'SHOP_FRY_{fish}'))
                for name, image in tabs.items():
                    hit = island(image).appear(button, offset=ISLAND_SHOP_ITEM_SEARCH_OFFSET,
                                               similarity=ISLAND_SHOP_ITEM_SIMILARITY) \
                        and shop_item_color_matches(button, image)
                    self.assertEqual(bool(hit), name == tab, f'{fish} in {name} tab')

    def test_black_porgy_selected_panel(self):
        image = frame('selected_black_porgy.png', (700, 200, 890, 360))
        check = fresh(fishery_assets.SELECT_BLACK_PORGY_CHECK)
        self.assertTrue(island(image).match_template_color(check, offset=20, similarity=0.85, threshold=10))
        # Red Sea Bream has the same outline; its selected picture must not match the Black Porgy panel
        other = fresh(fishery_assets.SELECT_RED_SEA_BREAM_CHECK)
        self.assertFalse(island(image).match_template_color(other, offset=20, similarity=0.85, threshold=10))

    def test_black_porgy_warehouse_icon_does_not_match_other_fish(self):
        image = frame('warehouse_owned.png', (280, 140, 860, 300))
        ocr = object.__new__(WarehouseOCR)
        WarehouseOCR.__init__(ocr)
        template = fresh(fishery_assets.TEMPLATE_BLACK_PORGY)
        for _, _, button in ocr.warehouse_grid.generate():
            self.assertFalse(template.match(crop(image, button.area), similarity=0.85))
        # the same grid does find the fish that are really there
        koi = fresh(fishery_assets.TEMPLATE_KOI_CARP)
        self.assertTrue(any(koi.match(crop(image, button.area), similarity=0.85)
                            for _, _, button in ocr.warehouse_grid.generate()))


class FisheryListsAgreeTest(unittest.TestCase):
    def test_fish_lists_agree(self):
        fishery = object.__new__(IslandFishery)
        fishery.config = SimpleNamespace(**{name: 0 for name in dir(__import__(
            'module.config.config_generated', fromlist=['GeneratedConfig']).GeneratedConfig) if name.startswith('IslandFishery_')})
        fishery.config.IslandFishery_Positions = 2
        fishery.config.IslandFishery_DefaultFish = 'yellowfin_tuna'
        fishery.config.IslandFishery_RancherFilter = 'WorkerJuu'
        with unittest.mock.patch.object(Island, '__init__', lambda self, *a, **k: None):
            IslandFishery.__init__(fishery, None)
        items = [item['name'] for item in fishery.FISHERY_ITEMS]
        planner = list(settings_map.PRODUCT_ITEM_IDS['fishery'])
        self.assertEqual(items, planner)
        self.assertEqual(list(fishery.fishery_threshold), planner)
        thresholds = settings_map.THRESHOLD_GROUPS['fishery']
        self.assertEqual(sorted(thresholds), sorted(settings_map.PRODUCT_ITEM_IDS['fishery'].values()))
        self.assertIn('black_porgy', FISH_MEAT_FISH_IDS)

    def test_black_porgy_in_settings(self):
        import json
        args = json.loads((Path(__file__).parent.parent / 'module' / 'config' / 'argument' / 'args.json')
                          .read_text(encoding='utf-8'))
        self.assertIn('black_porgy', args['IslandRancher']['IslandFishery']['DefaultFish']['option'])
        self.assertIn('MinBlackPorgy', args['IslandRancher']['IslandFishery'])
        self.assertIn('black_porgy',
                      args['IslandProductionPlanner']['IslandProductionPlanner']['UnlockedFish']['option'])


import unittest.mock  # noqa: E402

if __name__ == '__main__':
    unittest.main()
