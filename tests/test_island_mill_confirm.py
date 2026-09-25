"""磨坊加工确认补点行为的离线回归测试。

原实现是“检测到确认按钮 → sleep(0.5) → 不再检测直接再点一次”，
云手机转场较慢时第二次点击会落到已经切换过去的页面上。
现在改为：确认按钮只在检测到、且距上次点击 ≥2s 时补点，
点击后由下一轮重新截图复检。
"""
import unittest

import numpy as np

import module.base.timer as timer_module
from module.base.timer import Timer
from module.base.utils import load_image
from module.island.assets import ISLAND_SHOP_CONFIRM
from module.island.island_rancher import (
    ISLAND_MILL_CHECK,
    ISLAND_SHOPPING_CHECK,
    IslandRancher,
)
from module.island_rancher.assets import MILL_WHEAT_FLOUR


def build_frame(*assets):
    """叠加资源图，还原“页面上存在这些元素”的测试截图。"""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for asset in assets:
        frame = np.maximum(frame, load_image(asset.file))
    return frame


# 磨坊加工数量弹窗（含确认按钮）
BUY_POPUP_FRAME = build_frame(ISLAND_SHOPPING_CHECK, ISLAND_SHOP_CONFIRM)
# 已回到磨坊页面
MILL_FRAME = build_frame(ISLAND_MILL_CHECK)


class FakeClock:
    def __init__(self):
        # 起点取正值：Timer.start() 以 _start <= 0 判定“未启动”
        self.now = 1000.0

    def advance(self, seconds):
        self.now += seconds


class FakeDevice:
    """按时间线提供截图，截图与点击都推进虚拟时间。"""

    def __init__(self, clock, timeline, screenshot_cost=0.4, click_cost=0.2):
        self.clock = clock
        self.t0 = clock.now
        self.timeline = timeline
        self.screenshot_cost = screenshot_cost
        self.click_cost = click_cost
        self.image = timeline(0.0)
        self.clicks = []

    def screenshot(self):
        self.clock.advance(self.screenshot_cost)
        self.image = self.timeline(self.clock.now - self.t0)
        return self.image

    def click(self, button, control_check=True):
        self.clicks.append((round(self.clock.now - self.t0, 2), button.name))
        self.clock.advance(self.click_cost)

    def sleep(self, seconds):
        self.clock.advance(seconds)

    def stuck_record_add(self, button):
        return None


class StubRancher:
    """绑定真实 process_mill_item / appear / appear_then_click 的测试替身。"""

    appear = IslandRancher.appear
    appear_then_click = IslandRancher.appear_then_click
    process_mill_item = IslandRancher.process_mill_item

    def __init__(self, device):
        self.device = device
        self.interval_timer = {}
        self.config = type("Config", (), {"BUTTON_OFFSET": 30})()
        self.name_to_config = {"wheat_flour": {"mill": MILL_WHEAT_FLOUR, "number": 5}}
        self.buy_numbers = []

    def loop(self, skip_first=True, timeout=None):
        timeout = Timer.from_seconds(timeout).start() if timeout is not None else None
        while 1:
            if timeout is not None and timeout.reached():
                return
            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()
            yield self.device.image

    @staticmethod
    def ensure_button(button):
        return button

    def interval_clear(self, button):
        return None

    def set_buy_number(self, target):
        self.buy_numbers.append(target)

    @staticmethod
    def _item_cn(name):
        return name


class MillConfirmTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self._real_time = timer_module.time
        timer_module.time = lambda: self.clock.now

    def tearDown(self):
        timer_module.time = self._real_time

    def run_mill(self, timeline):
        device = FakeDevice(self.clock, timeline)
        stub = StubRancher(device)
        result = stub.process_mill_item("wheat_flour", quantity=5)
        return result, device, stub

    def test_confirm_clicks_once_without_blind_retry(self):
        """确认一次后回到磨坊页面：不得再盲点一次确认按钮。"""
        timeline = lambda t: BUY_POPUP_FRAME if t < 1.2 else MILL_FRAME

        result, device, stub = self.run_mill(timeline)

        self.assertTrue(result)
        self.assertEqual([name for _, name in device.clicks], ["ISLAND_SHOP_CONFIRM"])
        self.assertEqual(stub.buy_numbers, [5])

    def test_confirm_retry_keeps_interval(self):
        """确认未生效时按 ≥2s 间隔补点，不会在同一轮里连点两次。"""
        timeline = lambda t: BUY_POPUP_FRAME

        result, device, stub = self.run_mill(timeline)

        self.assertFalse(result)
        self.assertGreaterEqual(len(device.clicks), 3)
        timestamps = [stamp for stamp, _ in device.clicks]
        for previous, current in zip(timestamps, timestamps[1:]):
            self.assertGreaterEqual(current - previous, 2)


if __name__ == "__main__":
    unittest.main()
