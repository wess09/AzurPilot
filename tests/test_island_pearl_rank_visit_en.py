"""国际服珍珠交易「好友排名」拜访按钮识别的离线测试。

夹具是实机截图 (760, 200, 1200, 540) 的裁剪（只含价格与拜访按钮，不含好友名），
贴回 1280×720 黑底上的原位置。旧的 EN 模板与实际按钮字体/比例不一致，
相似度只有 0.675（阈值 0.85），每次都报「未识别到拜访按钮」。
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import module.config.server as server

server.server = 'en'

from module.base.utils import load_image
from module.island.island_pearl_sell import IslandPearlSell

FIXTURE = Path(__file__).parent / 'fixtures' / 'pearl_rank' / 'friend_rank_visit.png'


def screen():
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[200:540, 760:1200] = load_image(str(FIXTURE))
    return image


class PearlRankVisitEnTest(unittest.TestCase):
    def test_visit_buttons_and_prices_are_found(self):
        image = screen()
        pearl = object.__new__(IslandPearlSell)
        pearl.device = SimpleNamespace(image=image, screenshot=lambda: image)
        pearl.config = SimpleNamespace(SERVER='en')

        candidates = pearl.find_rank_visit_candidates()

        self.assertEqual([c['visit_button'].area[1] for c in candidates], [245, 364])
        self.assertEqual([c['price'] for c in candidates], [413, 884])


if __name__ == '__main__':
    unittest.main()
