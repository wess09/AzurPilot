"""鱼肉加工：选鱼计划与 EN 服商店「鱼肉加工」页识别（截图只保留检测区域）。"""

import unittest
from pathlib import Path

import module.config.server as server

_previous_server = None


def setUpModule():
    # 截图来自 EN 服；只在本模块测试期间切换服务器，结束后恢复，避免影响其他测试
    global _previous_server
    _previous_server = server.server
    server.server = 'en'


def tearDownModule():
    server.server = _previous_server


from module.base.utils import load_image  # noqa: E402
from module.island import island_fish_meat as fm  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'island_fish_meat'


def image(name):
    return load_image(str(FIXTURES / f'{name}.png'))


class PlanTest(unittest.TestCase):
    def test_sources(self):
        # 鲤鱼（5003）每条 3 个淡水鱼肉，黄鳍金枪鱼（5107）每条 18 个海水鱼肉
        self.assertEqual(fm.FISH_MEAT_SOURCES[fm.FRESHWATER_FISH_MEAT][5003], 3)
        self.assertEqual(fm.FISH_MEAT_SOURCES[fm.SALTWATER_FISH_MEAT][5107], 18)

    def test_plan_covers_need_with_fewest_fish(self):
        # 鲶鱼（5002）每条 4 个优先；需要 10 → 3 条鲶鱼
        self.assertEqual(fm.plan_fish_exchange({5002: 5, 5003: 25}, 10), {5002: 3})
        # 鲶鱼不够时再用鲤鱼
        self.assertEqual(fm.plan_fish_exchange({5002: 1, 5003: 25}, 10), {5002: 1, 5003: 2})

    def test_plan_respects_keep_and_shortage(self):
        self.assertEqual(fm.plan_fish_exchange({5003: 25}, 100, keep={5003: 20}), {5003: 5})
        self.assertEqual(fm.plan_fish_exchange({5003: 0}, 10), {})
        self.assertEqual(fm.fish_meat_gain({5002: 1, 5003: 2}), 10)


class ScreenTest(unittest.TestCase):
    def test_exchange_page(self):
        page = image('exchange_page')
        self.assertTrue(fm.fish_meat_tab_active(page))
        self.assertEqual(fm.active_fish_meat(page), fm.FRESHWATER_FISH_MEAT)
        self.assertEqual(fm.read_fish_cards(page, fm.FRESHWATER_FISH_MEAT), [(0, 5003, 26)])
        self.assertEqual(fm.read_fish_meat(page), (6, 0))
        self.assertFalse(fm.exchange_popup_appear(page))
        self.assertFalse(fm.reward_popup_appear(page))

    def test_selected(self):
        self.assertEqual(fm.read_fish_meat(image('exchange_selected')), (6, 3))

    def test_popups(self):
        self.assertTrue(fm.exchange_popup_appear(image('exchange_popup')))
        self.assertFalse(fm.reward_popup_appear(image('exchange_popup')))
        self.assertTrue(fm.reward_popup_appear(image('exchange_reward')))
        self.assertFalse(fm.exchange_popup_appear(image('exchange_reward')))


if __name__ == '__main__':
    unittest.main()
