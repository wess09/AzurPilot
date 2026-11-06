"""免费周礼包的首屏检查、滑动后重查与原有领取条件回归。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.exception import GameStuckError, GameTooManyClickError
from module.freebies.assets import FREE_SUPPLY_PACK
from module.freebies.supply_pack import SupplyPack
from module.ui.page import page_supply_pack


def frame(pack_offset=None, ready=True, shade=40):
    """用现有按钮模板重建匿名商店画面，价格栏颜色变化模拟加载和滑动。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[580:670, 200:950] = shade
    buttons = []
    if ready:
        buttons.append((page_supply_pack.check_button, 0))
    if pack_offset is not None:
        buttons.append((FREE_SUPPLY_PACK, pack_offset))
    for button, offset in buttons:
        button.ensure_template()
        x1, y1, x2, y2 = button.area
        image[y1:y2, x1 + offset:x2 + offset] = button.image
    return image


class ShopDevice:
    def __init__(self, pages):
        self.pages = pages
        self.page = 0
        self.index = 0
        self.image = pages[0][0]
        self.now = 100.0
        self.screenshots = 0
        self.swipes = []

    def screenshot(self):
        self.screenshots += 1
        if self.screenshots > 200:
            raise AssertionError('礼包检查没有在有限截图内完成')
        self.now += 0.3
        self.index = min(self.index + 1, len(self.pages[self.page]) - 1)
        self.image = self.pages[self.page][self.index]

    def swipe_vector(self, vector, box):
        self.swipes.append((self.now, self.screenshots, vector, box))
        self.page = min(self.page + 1, len(self.pages) - 1)
        self.index = -1

    def stuck_record_add(self, button):
        pass


def runner(pages):
    main = SupplyPack.__new__(SupplyPack)
    main.device = ShopDevice(pages)
    main.interval_timer = {}
    return main


class SupplyPackFindTests(unittest.TestCase):
    def find(self, pages, skip_first_screenshot=True):
        main = runner(pages)
        with patch('module.base.timer.time', side_effect=lambda: main.device.now):
            found = main.supply_pack_find(
                FREE_SUPPLY_PACK, skip_first_screenshot=skip_first_screenshot)
        return found, main.device

    def test_visible_first_pack_is_found_without_swiping(self):
        found, device = self.find([[frame(pack_offset=30)]])
        self.assertTrue(found)
        self.assertEqual(device.swipes, [])
        self.assertEqual(device.screenshots, 0)

    def test_first_pack_appearing_after_entry_frames_is_not_skipped(self):
        empty = frame()
        found, device = self.find([[empty, empty, empty, frame(pack_offset=30)]])
        self.assertTrue(found)
        self.assertEqual(device.swipes, [])
        self.assertEqual(device.screenshots, 3)

    def test_loading_animation_does_not_count_as_a_checked_page(self):
        frames = [frame(shade=shade) for shade in (20, 40, 60, 80, 100, 120)]
        frames.append(frame(pack_offset=30))
        found, device = self.find([frames])
        self.assertTrue(found)
        self.assertEqual(device.swipes, [])
        self.assertGreater(device.now - 100, 1)

    def test_page_must_be_confirmed_before_swiping(self):
        not_ready = frame(ready=False)
        found, device = self.find([[not_ready] * 8 + [frame(pack_offset=30)]])
        self.assertTrue(found)
        self.assertEqual(device.swipes, [])

    def test_later_pack_is_found_after_first_page_is_checked(self):
        empty = frame()
        found, device = self.find([[empty], [empty, empty, empty, frame(pack_offset=250)]])
        self.assertTrue(found)
        self.assertEqual(len(device.swipes), 1)
        self.assertGreater(device.swipes[0][0] - 100, 1)
        self.assertGreater(device.screenshots - device.swipes[0][1], 3)
        self.assertEqual(device.swipes[0][2:], ((-400, 0), (230, 200, 1060, 600)))

    def test_every_swipe_resets_the_page_observation(self):
        empty = frame()
        moving = [frame(shade=shade) for shade in (20, 60, 100, 140, 180)]
        found, device = self.find([[empty], moving, [frame(pack_offset=150)]])
        self.assertTrue(found)
        self.assertEqual(len(device.swipes), 2)
        self.assertGreater(device.swipes[1][0] - device.swipes[0][0], 2)

    def test_missing_pack_still_stops_after_eight_swipes_and_checks_last_page(self):
        found, device = self.find([[frame()]])
        self.assertFalse(found)
        self.assertEqual(len(device.swipes), 8)
        previous_time = 100
        for now, _, _, _ in device.swipes:
            self.assertGreater(now - previous_time, 1)
            previous_time = now
        self.assertGreater(device.now - previous_time, 1)
        self.assertGreater(device.screenshots - device.swipes[-1][1], 3)

    def test_pack_on_last_allowed_page_is_still_found(self):
        empty = frame()
        found, device = self.find([[empty]] * 8 + [[frame(pack_offset=300)]])
        self.assertTrue(found)
        self.assertEqual(len(device.swipes), 8)

    def test_requested_fresh_first_screenshot_is_honored(self):
        found, device = self.find([[frame(pack_offset=30)]], skip_first_screenshot=False)
        self.assertTrue(found)
        self.assertEqual(device.screenshots, 1)
        self.assertEqual(device.swipes, [])

    def test_device_recovery_exceptions_are_not_swallowed(self):
        for error in (GameStuckError, GameTooManyClickError):
            with self.subTest(error=error.__name__):
                main = runner([[frame(ready=False)]])
                main.device.screenshot = Mock(side_effect=error('设备恢复'))
                with self.assertRaises(error):
                    main.supply_pack_find(FREE_SUPPLY_PACK)
                self.assertEqual(main.device.swipes, [])


class SupplyPackRunTests(unittest.TestCase):
    def test_oil_limit_and_configured_weekday_are_preserved(self):
        for oil, today, target, should_buy in (
            (15797, 4, 4, True),
            (20999, 5, 4, True),
            (15797, 3, 4, False),
            (21000, 4, 4, False),
        ):
            with self.subTest(oil=oil, today=today, target=target):
                main = SupplyPack.__new__(SupplyPack)
                main.config = SimpleNamespace(SupplyPack_DayOfWeek=target)
                main.ui_ensure = Mock()
                main.goto_supply_pack = Mock()
                main.get_oil = Mock(return_value=oil)
                main.supply_pack_buy = Mock()
                with patch('module.freebies.supply_pack.get_server_weekday', return_value=today):
                    main.run()
                if should_buy:
                    main.supply_pack_buy.assert_called_once_with(FREE_SUPPLY_PACK)
                else:
                    main.supply_pack_buy.assert_not_called()
                main.goto_supply_pack.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
