"""角色确认补点 helper 的离线回归测试（每日采集 / 经营走这条路径）。

`confirm_selected_character_closed()` 与 `click_selected_character_confirm()`
原实现是 `appear_then_click(SELECT_UI_CONFIRM, interval=1)`：间隔 1s 小于云手机
“选人页 → 下一页”的转场时间，而且点击前没有复核，容易把确认按钮点到已经切换
过去的页面上。现在与 `confirm_selected_character()` 对齐：

1. 只有本帧仍识别到角色页时才补点；
2. 点击前重新截取一帧复核；
3. 两次点击间隔不小于 ISLAND_CHARACTER_CONFIRM_RETRY_WAIT；
4. 只点击确认按钮右侧安全段（与选餐页确认按钮等其它页面按钮不重叠）。
"""
import unittest
from types import MethodType

import numpy as np

import module.base.timer as timer_module
from module.base.timer import Timer
from module.base.utils import load_image, random_rectangle_point
from module.island.assets import (
    ISLAND_SELECT_CHARACTER_CHECK,
    ISLAND_SELECT_PRODUCT_CHECK,
    POST_ADD_ORDER,
    SELECT_UI_CONFIRM,
)
from module.island.island import (
    ISLAND_CHARACTER_CONFIRM_RETRY_WAIT,
    SELECT_UI_CONFIRM_SAFE,
    Island,
)


def build_frame(*assets):
    """叠加资源图，还原“页面上存在这些元素”的测试截图。"""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for asset in assets:
        frame = np.maximum(frame, load_image(asset.file))
    return frame


CHARACTER_PAGE = build_frame(ISLAND_SELECT_CHARACTER_CHECK, SELECT_UI_CONFIRM)
PRODUCT_PAGE = build_frame(ISLAND_SELECT_PRODUCT_CHECK, POST_ADD_ORDER)


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
        point = random_rectangle_point(button.button)
        self.clicks.append((round(self.clock.now - self.t0, 2), button.name, point))
        self.clock.advance(self.click_cost)

    def sleep(self, seconds):
        self.clock.advance(seconds)

    def stuck_record_add(self, button):
        return None


class StubIsland:
    """绑定真实 helper 与真实识别逻辑的测试替身。"""

    is_character_page_visible = Island.is_character_page_visible
    confirm_selected_character_closed = Island.confirm_selected_character_closed
    click_selected_character_confirm = Island.click_selected_character_confirm

    def __init__(self, device):
        self.device = device
        self.interval_timer = {}

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

    def interval_clear(self, button, interval=3):
        return None


class CharacterConfirmHelperTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self._real_time = timer_module.time
        timer_module.time = lambda: self.clock.now

    def tearDown(self):
        timer_module.time = self._real_time

    def run_helper(self, timeline, method, **kwargs):
        device = FakeDevice(self.clock, timeline)
        stub = StubIsland(device)
        for name in ("is_character_page_visible", "confirm_selected_character_closed",
                     "click_selected_character_confirm"):
            setattr(stub, name, MethodType(getattr(Island, name), stub))
        result = getattr(stub, method)(**kwargs)
        return result, device

    def test_slow_transition_does_not_add_extra_click(self):
        """确认已生效但角色页约 2.4s 才关闭时，不得补点确认按钮。"""
        timeline = lambda t: CHARACTER_PAGE if t < 2.4 else PRODUCT_PAGE

        result, device = self.run_helper(
            timeline, "confirm_selected_character_closed", context="测试采集")

        self.assertTrue(result)
        self.assertEqual([name for _, name, _ in device.clicks], ["SELECT_UI_CONFIRM_SAFE"])

    def test_retry_keeps_interval_and_safe_area(self):
        """确认不生效时按不小于转场时间的间隔补点，超时返回 False。"""
        timeline = lambda t: CHARACTER_PAGE

        result, device = self.run_helper(
            timeline, "confirm_selected_character_closed", context="测试采集")

        self.assertFalse(result)
        self.assertGreaterEqual(len(device.clicks), 2)
        self.assertEqual({name for _, name, _ in device.clicks}, {"SELECT_UI_CONFIRM_SAFE"})
        timestamps = [stamp for stamp, _, _ in device.clicks]
        for previous, current in zip(timestamps, timestamps[1:]):
            self.assertGreaterEqual(current - previous, ISLAND_CHARACTER_CONFIRM_RETRY_WAIT)

    def test_returns_without_click_when_page_already_closed(self):
        """角色页已经关闭时直接返回成功，不产生点击。"""
        timeline = lambda t: PRODUCT_PAGE

        result, device = self.run_helper(
            timeline, "click_selected_character_confirm", context="测试采集")

        self.assertTrue(result)
        self.assertEqual(device.clicks, [])

    def test_safe_area_avoids_product_confirm_button(self):
        """补点落点必须避开选餐页确认按钮（否则会直接下单默认餐品）。"""
        safe = SELECT_UI_CONFIRM_SAFE.button
        confirm = SELECT_UI_CONFIRM.button
        product = POST_ADD_ORDER.button

        self.assertTrue(
            safe[0] >= confirm[0] and safe[1] >= confirm[1]
            and safe[2] <= confirm[2] and safe[3] <= confirm[3],
            f"补点区域 {safe} 必须仍在角色页确认按钮 {confirm} 内",
        )
        overlap = not (
            safe[2] <= product[0] or safe[0] >= product[2]
            or safe[3] <= product[1] or safe[1] >= product[3]
        )
        self.assertFalse(overlap, f"补点区域 {safe} 与选餐页确认按钮 {product} 重叠")


if __name__ == "__main__":
    unittest.main()
