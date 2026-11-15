"""货物筹备刷新更换委托列表时的确认弹窗离线测试。

夹具是国际服实机截图 (640, 470, 880, 650) 的裁剪：
- refresh_popup.png：点击刷新后弹出「Do you want to refresh all displayed jobs?」，
  弹窗的 Confirm 按钮与下方列表自身（变暗）的 Confirm 都在画面里；
- job_list.png：没有弹窗的更换委托列表。

原实现点击刷新后只等待 5 秒、不处理弹窗，列表从未真正刷新，
弹窗文字还被识别成一行委托。
"""
import unittest
from pathlib import Path

import numpy as np

import module.config.server as server

server.server = 'en'

import module.base.timer as timer_module
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import load_image
from module.island import island_cargo_preparation as cargo_module
from module.island.island_cargo_preparation import IslandCargoPreparation

FIXTURES = Path(__file__).parent / 'fixtures' / 'cargo_refresh'


def frame(name):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[470:650, 640:880] = load_image(str(FIXTURES / name))
    return image


POPUP = frame('refresh_popup.png')
LIST = frame('job_list.png')


class FakeClock:
    def __init__(self):
        self.now = 1000.0


class FakeDevice:
    def __init__(self, clock, timeline):
        self.clock = clock
        self.timeline = timeline
        self.clicks = []
        self.image = timeline(self)

    def screenshot(self):
        self.clock.now += 0.3
        self.image = self.timeline(self)
        return self.image

    def click(self, button, control_check=True):
        x1, y1, x2, y2 = button.button
        self.clicks.append(((x1 + x2) // 2, (y1 + y2) // 2))
        self.clock.now += 0.2

    def sleep(self, seconds):
        self.clock.now += seconds

    def stuck_record_add(self, button):
        return None

    def click_record_clear(self):
        return None


class Stub:
    _wait_replace_refresh = IslandCargoPreparation._wait_replace_refresh
    REFRESH_POPUP_CONFIRM_OFFSET = IslandCargoPreparation.REFRESH_POPUP_CONFIRM_OFFSET
    appear = IslandCargoPreparation.appear
    appear_then_click = IslandCargoPreparation.appear_then_click
    interval_clear = IslandCargoPreparation.interval_clear
    get_interval_timer = IslandCargoPreparation.get_interval_timer
    ensure_button = IslandCargoPreparation.ensure_button

    def __init__(self, device):
        self.device = device
        self.interval_timer = {}
        self.config = type('Config', (), {'SERVER': 'en', 'BUTTON_OFFSET': 30})()

    def handle_popup_confirm(self, name='', offset=None, interval=2):
        return False

    def loop(self, skip_first=True, timeout=None):
        timeout = Timer(timeout).start()
        while not timeout.reached():
            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()
            yield self.device.image


class CargoRefreshPopupTest(unittest.TestCase):
    def setUp(self):
        # 其他测试可能把全局服务器改回 cn，资源按服务器取区域，这里每次设回 en
        self._server = server.server
        server.server = 'en'
        # Button 在首次访问时按当时的服务器缓存区域与模板；若本模块先被其他测试在 cn 下
        # 导入，这里换成按 en 新建的同名按钮，测试结束后还原
        original = cargo_module.CARGO_PREPARATION_REPLACE_CONFIRM
        self._original_confirm = original
        cargo_module.CARGO_PREPARATION_REPLACE_CONFIRM = Button(
            area=original.raw_area, color=original.raw_color, button=original.raw_button,
            file=original.raw_file, name=original.raw_name)
        self.clock = FakeClock()
        self._time = timer_module.time
        timer_module.time = lambda: self.clock.now

    def tearDown(self):
        timer_module.time = self._time
        server.server = self._server
        cargo_module.CARGO_PREPARATION_REPLACE_CONFIRM = self._original_confirm

    def test_refresh_popup_is_confirmed(self):
        device = FakeDevice(self.clock, lambda d: LIST if d.clicks else POPUP)
        Stub(device)._wait_replace_refresh()

        self.assertEqual(len(device.clicks), 1)
        x, y = device.clicks[0]
        # 弹窗 Confirm 位于 (741, 495, 847, 523)，不是列表底部的 Confirm（约 y=614）
        self.assertTrue(741 <= x <= 847 and 490 <= y <= 530, device.clicks)

    def test_no_popup_no_click(self):
        device = FakeDevice(self.clock, lambda d: LIST)
        Stub(device)._wait_replace_refresh()
        self.assertEqual(device.clicks, [])


if __name__ == '__main__':
    unittest.main()
