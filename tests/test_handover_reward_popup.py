"""作战委托：领奖路上弹出的结算 / 紧急委托 / 新船入手画面。

三个画面都会盖住关卡页，卡死检测只看画面有没有变化，认不出来就空转到
GameStuckError，所以它们必须在同一个入口里按固定优先级收掉。
"""

import unittest

import cv2
import numpy as np

from module.base.utils import get_bbox, get_color
from module.handler import assets as handler_assets
from module.handler.assets import NEW_SHIP_SKIP
from module.handover.handover import OperationHandover
from module.map.assets import HANDOVER_REWARD, HANDOVER_REWARD_CHECK


class FakeHandover:
    """只挂 handover_handle_popup 的桩，记录实际点到了哪个按钮。"""

    handover_handle_popup = OperationHandover.handover_handle_popup
    handle_handover_help = OperationHandover.handle_handover_help

    def __init__(self, reward=False, urgent=False, skip=False):
        self.reward = reward
        self.urgent = urgent
        self.skip = skip
        self.clicked = []

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        return self.reward and button is HANDOVER_REWARD_CHECK

    def appear_then_click(self, button, offset=0, interval=0, similarity=0.85, threshold=30):
        if button is HANDOVER_REWARD and self.reward:
            self.clicked.append('结算')
            return True
        if button is NEW_SHIP_SKIP and self.skip:
            self.clicked.append('新船')
            return True
        return False

    def handle_urgent_commission(self, drop=None):
        if self.urgent:
            self.clicked.append('紧急委托')
            return True
        return False


class TestHandoverRewardPopup(unittest.TestCase):
    def test_settlement_clicked(self):
        fake = FakeHandover(reward=True)
        self.assertTrue(fake.handover_handle_popup())
        self.assertEqual(fake.clicked, ['结算'])

    def test_urgent_commission_clicked(self):
        fake = FakeHandover(urgent=True)
        self.assertTrue(fake.handover_handle_popup())
        self.assertEqual(fake.clicked, ['紧急委托'])

    def test_new_ship_skip_clicked(self):
        fake = FakeHandover(skip=True)
        self.assertTrue(fake.handover_handle_popup())
        self.assertEqual(fake.clicked, ['新船'])

    def test_settlement_wins_over_new_ship(self):
        # 结算和紧急委托叠在一起时也要先把结算收掉，再来一轮才能看到新船
        fake = FakeHandover(reward=True, urgent=True, skip=True)
        fake.handover_handle_popup()
        self.assertEqual(fake.clicked, ['结算'])

    def test_nothing_to_do(self):
        fake = FakeHandover()
        self.assertFalse(fake.handover_handle_popup())
        self.assertEqual(fake.clicked, [])


class TestNewShipSkipAsset(unittest.TestCase):
    def test_definition_matches_png(self):
        """定义必须等于 button_extract 从 PNG 里算出来的 bbox 与均值色。

        用 cv2 读图而不是 load_image()：WebUI 的测试会给 sys.modules 塞一个假
        PIL，全量跑时会连真实 PIL 的解码器注册表一起搞坏（仓库已知问题）。
        """
        image = cv2.cvtColor(cv2.imread(handler_assets.NEW_SHIP_SKIP.file),
                             cv2.COLOR_BGR2RGB)
        bbox = get_bbox(image)
        color = tuple(int(x) for x in np.rint(get_color(image=image, area=bbox)))

        self.assertTrue(handler_assets.NEW_SHIP_SKIP.file.endswith('NEW_SHIP_SKIP.png'))
        self.assertEqual(handler_assets.NEW_SHIP_SKIP.area, bbox)
        self.assertEqual(handler_assets.NEW_SHIP_SKIP.color, color)
        self.assertEqual(handler_assets.NEW_SHIP_SKIP.button, bbox)


if __name__ == '__main__':
    unittest.main()
