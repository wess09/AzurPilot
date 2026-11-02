"""岛屿种子/鱼苗商店商品定位测试。

种子商店只列出已解锁的商品，格子顺序因账号和服务器而异。用国际服真实截图确认：
按图标整页搜索能找到每种种子的实际格子，且相似度阈值下不会误认成其他种子。
"""
import importlib
import os
import unittest

import numpy as np
from PIL import Image

import module.config.server as server
from module.island.island import ISLAND_SHOP_ITEM_SEARCH_OFFSET, ISLAND_SHOP_ITEM_SIMILARITY

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'island_seed_shop')

# 截图中每种种子所在格子的横向中心（国际服账号未解锁洋葱，苗圃格子整体前移一格）
EXPECTED_COLUMNS = {
    'en_nursery.png': {
        'CARROT': 299, 'FLAX': 461, 'STRAWBERRY': 624, 'COTTON': 788, 'TEA': 951, 'LAVENDER': 1114,
    },
    'en_faircrop.png': {
        'WHEAT': 298, 'CORN': 460, 'RICE': 624, 'CHINESE_CABBAGE': 788, 'POTATO': 951, 'SOYBEAN': 1114,
        'PASTURE': 299, 'COFFEE_BEAN': 460,
    },
    'en_orchard.png': {
        'APPLE': 297, 'CITRUS': 463, 'BANANA': 624, 'MANGO': 790, 'LEMON': 950, 'AVOCADO': 1112,
        'RUBBER': 296, 'PEAR': 461, 'PERSIMMON': 625,
    },
}

# 鱼苗商店同样只列出已解锁的鱼苗：该账号「其他」页签只有贝类和鱿鱼（国服鱿鱼在第 5 格），
# 「淡水鱼」页签只有鲤鱼苗，机器人会购买的鲈鱼苗未解锁、不应被找到
EXPECTED_FRY_COLUMNS = {
    'en_fry_other.png': {'SHELL': 299, 'SQUID': 463},
    'en_fry_freshwater.png': {},
}


class TestIslandSeedShopSearch(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'en'
        import module.island_farm.assets as farm_assets
        import module.island_fishery.assets as fishery_assets
        self.groups = [
            (importlib.reload(farm_assets), 'SHOP_SEED_', EXPECTED_COLUMNS),
            (importlib.reload(fishery_assets), 'SHOP_FRY_', EXPECTED_FRY_COLUMNS),
        ]

    def tearDown(self):
        server.server = self._server

    def _load(self, name):
        return np.array(Image.open(os.path.join(FIXTURE_DIR, name)).convert('RGB'))

    @staticmethod
    def _match(button, image):
        if not button.match(image, offset=ISLAND_SHOP_ITEM_SEARCH_OFFSET, similarity=ISLAND_SHOP_ITEM_SIMILARITY):
            return None
        return (button.button[0] + button.button[2]) // 2

    def test_each_listed_item_is_found_in_its_actual_slot(self):
        for assets, prefix, fixtures in self.groups:
            for fixture, expected in fixtures.items():
                image = self._load(fixture)
                for item, column in expected.items():
                    with self.subTest(fixture=fixture, item=item):
                        found = self._match(getattr(assets, prefix + item), image)
                        self.assertIsNotNone(found, f'{item} not found')
                        self.assertLess(abs(found - column), 20)

    def test_unlisted_items_are_not_matched(self):
        for assets, prefix, fixtures in self.groups:
            names = [name for name in dir(assets) if name.startswith(prefix)]
            for fixture, expected in fixtures.items():
                image = self._load(fixture)
                for name in names:
                    item = name[len(prefix):]
                    if item in expected:
                        continue
                    with self.subTest(fixture=fixture, item=item):
                        self.assertIsNone(self._match(getattr(assets, name), image))


if __name__ == '__main__':
    unittest.main()
