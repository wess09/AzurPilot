"""空投补给：只点每日补给/领取补给气泡，关闭奖励弹窗与分享邀请窗口，不再盲点到好友的邀请按钮。

截图来自 EN 服（1280×720），只保留检测用到的区域，其余涂黑（去掉岛屿名与好友名）。
"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import module.config.server as server

_previous_server = None


def _refresh_buttons():
    """按钮在创建时按当时的服务器缓存图片与区域，切换服务器后清掉缓存重新解析。"""
    from module.base.button import Button
    for button in (air_drop.ISLAND_AIR_DROP_A,):
        for name in Button.cached:
            button.__dict__.pop(name, None)
        button._match_init = False
        button.image = None


def setUpModule():
    # 截图来自 EN 服；只在本模块测试期间切换服务器，结束后恢复，避免影响其他测试
    global _previous_server
    _previous_server = server.server
    server.server = 'en'
    _refresh_buttons()


def tearDownModule():
    server.server = _previous_server
    _refresh_buttons()


from module.base.utils import load_image  # noqa: E402
from module.island import island_air_drop as air_drop  # noqa: E402
from module.island.island_air_drop import IslandAirDrop  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'island_air_drop'


def image(name):
    return load_image(str(FIXTURES / f'{name}.png'))


class ScreenCheckTest(unittest.TestCase):
    def test_bubble(self):
        for name in ('daily_supply_bubble', 'claim_bubble', 'share_bubble'):
            self.assertTrue(air_drop.air_drop_bubble_appear(image(name)), name)
        self.assertFalse(air_drop.air_drop_bubble_appear(image('cutscene')))
        self.assertFalse(air_drop.air_drop_bubble_appear(image('share_dialog')))

    def test_reward_popup(self):
        self.assertTrue(air_drop.air_drop_reward_popup_appear(image('reward_popup')))
        for name in ('claim_bubble', 'share_bubble', 'share_dialog', 'cutscene'):
            self.assertFalse(air_drop.air_drop_reward_popup_appear(image(name)), name)

    def test_share_dialog(self):
        self.assertTrue(air_drop.air_drop_share_dialog_appear(image('share_dialog')))
        for name in ('claim_bubble', 'share_bubble', 'reward_popup', 'cutscene'):
            self.assertFalse(air_drop.air_drop_share_dialog_appear(image(name)), name)


class ClaimFlowTest(unittest.TestCase):
    """模拟一轮领取：领取气泡 → 奖励弹窗 → 分享气泡，应只点一次气泡、关一次弹窗，不点分享。"""

    def run_flow(self, screens):
        with patch.object(IslandAirDrop, '__init__', lambda self: None):
            drop = IslandAirDrop()
        drop.device = Mock()
        drop.interval_clear = Mock()
        frames = [image(name) for name in screens]

        def loop(**kwargs):
            for frame in frames:
                drop.device.image = frame
                yield frame

        drop.loop = loop
        with patch.object(air_drop, 'Timer') as timer:
            timer.return_value.reached.return_value = True
            drop.island_air_drop()
        return [call.args[0] for call in drop.device.click.call_args_list]

    def test_claim_then_stop_at_share(self):
        clicks = self.run_flow(['claim_bubble', 'reward_popup', 'share_bubble', 'share_bubble'])
        self.assertEqual(clicks, [air_drop.ISLAND_AIR_DROP_A, air_drop.AIR_DROP_POPUP_CLOSE])

    def test_closes_share_dialog_without_inviting(self):
        clicks = self.run_flow(['share_dialog', 'share_bubble'])
        self.assertEqual(clicks, [air_drop.AIR_DROP_SHARE_DIALOG_CLOSE])

    def test_bubble_click_limit(self):
        clicks = self.run_flow(['daily_supply_bubble'] * 6 + ['cutscene'])
        self.assertEqual(clicks.count(air_drop.ISLAND_AIR_DROP_A), air_drop.AIR_DROP_BUBBLE_CLICK_LIMIT)


if __name__ == '__main__':
    unittest.main()
