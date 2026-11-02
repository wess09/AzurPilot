"""岛屿种子商店商品定位测试。

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
}


class TestIslandSeedShopSearch(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'en'
        import module.island_farm.assets as farm_assets
        self.assets = importlib.reload(farm_assets)
        self.seeds = [name for name in dir(self.assets) if name.startswith('SHOP_SEED_')]

    def tearDown(self):
        server.server = self._server

    def _load(self, name):
        return np.array(Image.open(os.path.join(FIXTURE_DIR, name)).convert('RGB'))

    def _match(self, seed, image):
        button = getattr(self.assets, f'SHOP_SEED_{seed}')
        if not button.match(image, offset=ISLAND_SHOP_ITEM_SEARCH_OFFSET, similarity=ISLAND_SHOP_ITEM_SIMILARITY):
            return None
        return (button.button[0] + button.button[2]) // 2

    def test_each_listed_seed_is_found_in_its_actual_slot(self):
        for fixture, expected in EXPECTED_COLUMNS.items():
            image = self._load(fixture)
            for seed, column in expected.items():
                with self.subTest(fixture=fixture, seed=seed):
                    found = self._match(seed, image)
                    self.assertIsNotNone(found, f'{seed} not found')
                    self.assertLess(abs(found - column), 20)

    def test_unlisted_seeds_are_not_matched(self):
        for fixture, expected in EXPECTED_COLUMNS.items():
            image = self._load(fixture)
            for name in self.seeds:
                seed = name[len('SHOP_SEED_'):]
                if seed in expected:
                    continue
                with self.subTest(fixture=fixture, seed=seed):
                    self.assertIsNone(self._match(seed, image))


if __name__ == '__main__':
    unittest.main()
