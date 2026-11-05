"""鱼肉加工：选鱼计划与 EN 服商店「鱼肉加工」页识别（截图只保留检测区域）。"""

import unittest
import unittest.mock
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



class FishMeatKeepTest(unittest.TestCase):
    def test_fishery_ids_are_exchangeable(self):
        from module.island.island_fishery import FISH_MEAT_FISH_IDS
        self.assertTrue(set(FISH_MEAT_FISH_IDS.values()) <= set(fm.FISH_MEAT_YIELD))

    def test_keep_threshold(self):
        # 鲤鱼 26 条、底线 20 时只能用 6 条（每条 3 鱼肉）
        self.assertEqual(fm.plan_fish_exchange({5003: 26}, 30, keep={5003: 20}), {5003: 6})


class GotoPageTest(unittest.TestCase):
    """兑换完淡水鱼肉后仍在鱼肉加工页，再进入海水鱼肉时不能先 ui_ensure（商店页是未知页面，会重启游戏）。"""

    def setUp(self):
        # 按钮在导入时按服务器选图，模块导入早于切换到 EN，这里重新加载 EN 图并替换
        import importlib
        import module.island.assets as island_assets
        import module.island_fish_meat.assets as fish_meat_assets
        import module.ui.assets as ui_assets
        reloaded = {}
        for assets in (island_assets, fish_meat_assets, ui_assets):
            reloaded.update(vars(importlib.reload(assets)))
        for name in ('ISLAND_BACK', 'ISLAND_CHECK', 'ISLAND_EXCHANGE_CONFIRM', 'ISLAND_GOTO_ISLAND_SHOP'):
            patcher = unittest.mock.patch.object(fm, name, reloaded[name])
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def exchanger(screen):
        from unittest.mock import Mock

        class Exchanger(fm.IslandFishMeatExchange):
            def appear(self, button, offset=0, **kwargs):
                return bool(button.match(self.device.image, offset=offset))

            def loop(self, timeout=None, skip_first=True):
                yield self.device.image

        exchanger = Exchanger()
        exchanger.device = Mock(image=screen)
        exchanger.ui_ensure = Mock()
        return exchanger

    def test_already_on_fish_meat_page_skips_ui_ensure(self):
        exchanger = self.exchanger(image('exchange_page'))
        self.assertTrue(exchanger._goto_fish_meat_page(fm.FRESHWATER_FISH_MEAT))
        exchanger.ui_ensure.assert_not_called()

    def test_other_page_goes_to_island_first(self):
        exchanger = self.exchanger(image('exchange_reward'))
        with unittest.mock.patch.object(fm, 'logger'):
            exchanger._goto_fish_meat_page(fm.SALTWATER_FISH_MEAT)
        exchanger.ui_ensure.assert_called_once_with(fm.page_island)


if __name__ == '__main__':
    unittest.main()
