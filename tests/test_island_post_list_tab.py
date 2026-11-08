"""岗位列表回顶部前先切回生产页签的离线测试。

岗位管理页会停留在上次使用的页签。国际服 2026-11-08 的日志里，回顶部失败
（「岗位列表回顶部失败（已补滑 5 次）」）7 次全部发生在经营任务把页面留在
经营页签之后：经营页签的列表里没有农田行，补滑多少次都判断不到顶部，
08:27 农场任务因此找不到岗位卡死重启。

截图用资源图叠加还原（与 test_island_mill_confirm 相同的做法）。
"""
import unittest
from types import SimpleNamespace

import numpy as np

import module.config.server as server

server.server = 'en'

import module.base.timer as timer_module
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import load_image
from module.island import island as island_module
from module.island.island import Island


def fresh(button):
    """按当前服务器（en）重新创建按钮，避免被其他测试在 cn 下缓存。"""
    return Button(area=button.raw_area, color=button.raw_color, button=button.raw_button,
                  file=button.raw_file, name=button.raw_name)


class FakeDevice:
    def __init__(self, clock, frames):
        self.clock = clock
        self.frames = frames
        self.tab = 'business'
        self.clicks = []
        self.swipes = 0
        self.image = frames[self.tab]

    def screenshot(self):
        self.clock.now += 0.3
        self.image = self.frames[self.tab]
        return self.image

    def click(self, button, control_check=True):
        self.clicks.append(button.name)
        # 经营页签下 POST_MANAGE_BUSINESS 的点击区域是生产页签
        if button.name == 'POST_MANAGE_BUSINESS':
            self.tab = 'production'
        self.clock.now += 0.2

    def swipe_vector(self, *args, **kwargs):
        self.swipes += 1

    def sleep(self, seconds):
        self.clock.now += seconds

    def stuck_record_add(self, button):
        return None


class PostListTabTest(unittest.TestCase):
    def setUp(self):
        self._server = server.server
        server.server = 'en'
        self.now = SimpleNamespace(now=1000.0)
        self._time = timer_module.time
        timer_module.time = lambda: self.now.now
        self._saved = {}
        for name in ('POST_MANAGE_BUSINESS', 'POST_MANAGE_PRODUCTION', 'ISLAND_FARM_POST1',
                     'ISLAND_GATHER_COLLECT_CHECK', 'POST_MANAGE_SWIPE_STOP'):
            self._saved[name] = getattr(island_module, name)
            setattr(island_module, name, fresh(self._saved[name]))

    def tearDown(self):
        timer_module.time = self._time
        server.server = self._server
        for name, button in self._saved.items():
            setattr(island_module, name, button)

    def frame(self, *names):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        for name in names:
            image = np.maximum(image, load_image(getattr(island_module, name).file))
        return image

    def make(self, frames):
        device = FakeDevice(self.now, frames)
        island = object.__new__(Island)
        island.device = device
        island.interval_timer = {}
        island.config = SimpleNamespace(SERVER='en', BUTTON_OFFSET=30)

        def loop(skip_first=True, timeout=None):
            timer = Timer(timeout).start()
            while not timer.reached():
                if skip_first:
                    skip_first = False
                else:
                    device.screenshot()
                yield device.image

        island.loop = loop
        return island, device

    def test_switches_from_business_tab_before_swiping(self):
        island, device = self.make({
            'business': self.frame('POST_MANAGE_BUSINESS'),
            'production': self.frame('POST_MANAGE_PRODUCTION', 'ISLAND_FARM_POST1'),
        })

        self.assertTrue(island.post_manage_swipe_to_top())
        self.assertEqual(device.tab, 'production')
        self.assertIn('POST_MANAGE_BUSINESS', device.clicks)
        self.assertEqual(device.swipes, 0)

    def test_production_tab_not_at_top_still_swipes(self):
        island, device = self.make({
            'business': self.frame('POST_MANAGE_PRODUCTION'),   # 已在生产页签但不在顶部
            'production': self.frame('POST_MANAGE_PRODUCTION'),
        })

        self.assertFalse(island.post_manage_swipe_to_top(max_swipes=2))
        self.assertEqual(device.clicks.count('POST_MANAGE_BUSINESS'), 0)
        self.assertEqual(device.swipes, 2)


if __name__ == '__main__':
    unittest.main()
