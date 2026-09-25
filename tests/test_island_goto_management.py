"""进入岛屿管理页入口按钮点击行为的离线回归测试。

`goto_management()` 在非岛屿页面时会先导航到岛屿页，再点击右上角“管理”入口
（ISLAND_GOTO_MANAGEMENT）。原实现只判断页面（ISLAND_CHECK）就点击，没有任何
间隔限制，云机场景转场慢时会在同一入口按钮上反复点击。现在两次点击间隔不得
小于 ISLAND_ENTRY_RETRY_WAIT，且一旦识别到管理页立即停止。
"""
import unittest
from types import SimpleNamespace

import numpy as np

import module.base.timer as timer_module
from module.base.timer import Timer
from module.base.utils import load_image
from module.exception import GameStuckError
from module.island.island import (
    ISLAND_CHECK,
    ISLAND_ENTRY_RETRY_WAIT,
    ISLAND_GOTO_MANAGEMENT,
    ISLAND_MANAGEMENT_CHECK,
    Island,
)


def build_frame(*assets):
    """叠加资源图，还原“页面上存在这些元素”的测试截图。"""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for asset in assets:
        frame = np.maximum(frame, load_image(asset.file))
    return frame


# 岛屿页面（右上角管理入口可见）
ISLAND_PAGE = build_frame(ISLAND_CHECK, ISLAND_GOTO_MANAGEMENT)
# 岗位管理页面（已到达目标）
POSTMANAGE_PAGE = build_frame(ISLAND_MANAGEMENT_CHECK)


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


class StubIsland:
    """绑定真实 goto_management 的测试替身。"""

    goto_management = Island.goto_management

    def __init__(self, device, current_page="page_main"):
        self.device = device
        self.interval_timer = {}
        self.current_page = current_page
        self.ui_goto_calls = []

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

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        if offset:
            return bool(button.match(self.device.image, offset=offset, similarity=similarity))
        return bool(button.appear_on(self.device.image, threshold=threshold))

    def ui_get_current_page(self, *args, **kwargs):
        return SimpleNamespace(name=self.current_page)

    def ui_goto(self, destination, get_ship=True, **kwargs):
        self.ui_goto_calls.append(str(destination))

    def ui_additional(self, get_ship=True):
        return False


class GotoManagementTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self._real_time = timer_module.time
        timer_module.time = lambda: self.clock.now

    def tearDown(self):
        timer_module.time = self._real_time

    def make_stub(self, timeline, current_page="page_main"):
        device = FakeDevice(self.clock, timeline)
        return StubIsland(device, current_page=current_page), device

    def test_entry_click_keeps_interval_until_page_switches(self):
        """岛屿场景转场期间不得反复点击入口按钮，转场完成后立即停止。"""
        stub, device = self.make_stub(lambda t: ISLAND_PAGE if t < 5.0 else POSTMANAGE_PAGE)

        stub.goto_management()

        names = [name for _, name in device.clicks]
        self.assertTrue(names, "应当点击过管理入口按钮")
        self.assertEqual(set(names), {"ISLAND_GOTO_MANAGEMENT"})
        timestamps = [stamp for stamp, _ in device.clicks]
        for previous, current in zip(timestamps, timestamps[1:]):
            self.assertGreaterEqual(current - previous, ISLAND_ENTRY_RETRY_WAIT)

    def test_entry_click_is_bounded_when_page_never_switches(self):
        """始终没进入管理页时按间隔补点，不会每轮都点，超时抛 GameStuckError。"""
        stub, device = self.make_stub(lambda t: ISLAND_PAGE)

        with self.assertRaises(GameStuckError):
            stub.goto_management()

        clicks = [stamp for stamp, _ in device.clicks]
        self.assertGreaterEqual(len(clicks), 2)
        self.assertLessEqual(len(clicks), 8)
        for previous, current in zip(clicks, clicks[1:]):
            self.assertGreaterEqual(current - previous, ISLAND_ENTRY_RETRY_WAIT)

    def test_skips_entry_click_when_already_in_island_page(self):
        """已在岛屿相关页面时直接走 ui_goto，不点击管理入口按钮。"""
        stub, device = self.make_stub(lambda t: ISLAND_PAGE, current_page="page_island")

        stub.goto_management()

        self.assertEqual(device.clicks, [])
        self.assertEqual(stub.ui_goto_calls, ["page_island_management"])


if __name__ == "__main__":
    unittest.main()
