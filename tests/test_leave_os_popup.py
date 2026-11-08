"""大世界「需要暂时离开大型作战么?」弹窗：识别、点 X 关闭、不误点确定。

在自动配队、退出港口时点击过快会点到海域地图外，游戏弹出离开大型作战的确认
框，它的确定按钮与出发确认等通用双按钮弹窗位置相同，按通用弹窗处理会被点成
确定、直接退出大型作战（2026-09-28 日志中随后卡死在弹窗上触发设备卡死）。
这里固定住三条行为：识别到「暂时离开」文字就点右上角 X；点击冷却期间仍返回
True，拦住后续通用确认；没有弹窗时不越权处理。另固定出发/回图流程中弹窗、
港口、出发确认的处理次序。
"""

import unittest
from types import SimpleNamespace

from module.os.tasks.fleet_auto_change import OpsiFleetAutoChange
from module.os_handler.assets import (AUTO_SEARCH_REWARD, DEPART_CONFIRM_BUTTON,
                                      DEPART_CONFIRM_TEMPLATE,
                                      DEPART_IMMEDIATELY_BUTTON,
                                      LEAVE_OS_POPUP_CHECK,
                                      LEAVE_OS_POPUP_CLOSE, PORT_GOTO_SUPPLY)
from module.os_handler.map_event import MapEventHandler


class FakePopupMain:
    """只挂弹窗处理方法的桩，模拟文字模板命中与 X 点击冷却。"""

    handle_leave_os_popup = MapEventHandler.handle_leave_os_popup

    def __init__(self, text_visible=True, click_ok=True):
        """
        Args:
            text_visible: 「暂时离开」文字模板是否命中。
            click_ok: X 按钮本次是否点成（False 模拟点击冷却或未渲染完）。
        """
        self.text_visible = text_visible
        self.click_ok = click_ok
        self.clicked = []

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        if button is LEAVE_OS_POPUP_CHECK:
            return self.text_visible
        raise AssertionError(f'未预期的按钮: {button}')

    def appear_then_click(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        if button is not LEAVE_OS_POPUP_CLOSE:
            raise AssertionError(f'未预期的按钮: {button}')
        if self.click_ok:
            self.clicked.append(button.name)
            self.text_visible = False
            return True
        return False


class TestLeaveOsPopup(unittest.TestCase):
    def test_clicks_close_button(self):
        """文字模板命中：点右上角 X 关闭弹窗。"""
        fake = FakePopupMain()

        self.assertTrue(fake.handle_leave_os_popup())

        self.assertEqual(fake.clicked, [LEAVE_OS_POPUP_CLOSE.name])

    def test_blocks_while_click_throttled(self):
        """点击冷却/未点成时仍返回 True，阻止通用处理器把弹窗点成确定。"""
        fake = FakePopupMain(click_ok=False)

        self.assertTrue(fake.handle_leave_os_popup())

        self.assertEqual(fake.clicked, [])

    def test_no_popup_no_click(self):
        """没有弹窗时不点击、不越权处理。"""
        fake = FakePopupMain(text_visible=False)

        self.assertFalse(fake.handle_leave_os_popup())

        self.assertEqual(fake.clicked, [])


class FakeAutoChangeMain:
    """只挂等待方法所需接口的桩，用脚本化状态模拟画面变化。"""

    _wait_until_back_in_os_map = OpsiFleetAutoChange._wait_until_back_in_os_map

    def __init__(self, popup_visible=False, port_visible=False):
        self.popup_visible = popup_visible
        self.port_visible = port_visible
        self.clicked = []

    def loop(self, skip_first=True, timeout=None):
        while True:
            yield None

    def handle_leave_os_popup(self):
        if self.popup_visible:
            self.popup_visible = False
            self.clicked.append(LEAVE_OS_POPUP_CLOSE.name)
            return True
        return False

    def is_combat_loading(self):
        return False

    def appear_then_click(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        if button is AUTO_SEARCH_REWARD:
            return False
        raise AssertionError(f'未预期的按钮: {button}')

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        if button is PORT_GOTO_SUPPLY:
            return self.port_visible
        raise AssertionError(f'未预期的按钮: {button}')

    def is_in_map(self):
        # 弹窗遮挡（变暗）或仍在港口时都识别不到海域地图
        return not self.popup_visible and not self.port_visible

    def port_quit(self, skip_first_screenshot=False):
        self.port_visible = False
        self.clicked.append('port_quit')

    def wait_os_map_buttons(self):
        pass


class TestWaitUntilBackInOsMap(unittest.TestCase):
    def test_returns_when_map_visible(self):
        fake = FakeAutoChangeMain()

        self.assertTrue(fake._wait_until_back_in_os_map(timeout=5))
        self.assertEqual(fake.clicked, [])

    def test_closes_popup_before_returning(self):
        """弹窗挡在画面上时先点 X 关闭，再确认回到海域地图。"""
        fake = FakeAutoChangeMain(popup_visible=True)

        self.assertTrue(fake._wait_until_back_in_os_map(timeout=5))

        self.assertEqual(fake.clicked, [LEAVE_OS_POPUP_CLOSE.name])

    def test_quits_port_before_returning(self):
        """误入港口时退出港口，再确认回到海域地图。"""
        fake = FakeAutoChangeMain(port_visible=True)

        self.assertTrue(fake._wait_until_back_in_os_map(timeout=5))

        self.assertEqual(fake.clicked, ['port_quit'])

    def test_popup_takes_priority_over_port(self):
        """弹窗与港口按钮同时在画面上时，先关弹窗再退港口，不误点。"""
        fake = FakeAutoChangeMain(popup_visible=True, port_visible=True)

        self.assertTrue(fake._wait_until_back_in_os_map(timeout=5))

        self.assertEqual(fake.clicked, [LEAVE_OS_POPUP_CLOSE.name, 'port_quit'])


class FakeFreshFrameMain(FakeAutoChangeMain):
    """复用真实截图循环，模拟缓存地图后才出现港口或过渡画面。"""

    loop = OpsiFleetAutoChange.loop
    _ensure_return_to_os_map = OpsiFleetAutoChange._ensure_return_to_os_map

    def __init__(self, frames):
        super().__init__()
        self.frames = iter(frames)
        self.screenshots = []
        self.device = SimpleNamespace(image='cached_map', screenshot=self._screenshot)

    def _screenshot(self):
        try:
            frame = next(self.frames)
        except StopIteration:
            raise AssertionError('已用完截图，流程仍未确认返回地图') from None
        self.device.image = frame
        self.screenshots.append(frame)
        self.popup_visible = frame == 'popup'
        self.port_visible = frame == 'port'

    def is_in_map(self):
        return self.device.image in ('cached_map', 'map')

    def is_combat_loading(self):
        return self.device.image == 'loading'

    def appear_then_click(self, button, **kwargs):
        if button is AUTO_SEARCH_REWARD and self.device.image == 'reward':
            self.clicked.append(AUTO_SEARCH_REWARD.name)
            return True
        return super().appear_then_click(button, **kwargs)


class TestReturnToOsMapFreshScreenshot(unittest.TestCase):
    def test_cached_map_does_not_skip_port_exit(self):
        fake = FakeFreshFrameMain(['port', 'map'])

        self.assertTrue(fake._wait_until_back_in_os_map(timeout=5))

        self.assertEqual(fake.clicked, ['port_quit'])
        self.assertEqual(fake.screenshots, ['port', 'map'])

    def test_ensure_map_refreshes_cache_before_exp_check(self):
        fake = FakeFreshFrameMain(['port', 'map'])

        self.assertTrue(fake._ensure_return_to_os_map())

        self.assertEqual(fake.clicked, ['port_quit'])
        self.assertEqual(fake.device.image, 'map')

    def test_transitions_are_handled_before_port_and_map(self):
        for frame, clicks in (
            ('loading', []),
            ('popup', [LEAVE_OS_POPUP_CLOSE.name]),
            ('reward', [AUTO_SEARCH_REWARD.name]),
            ('unknown', []),
        ):
            with self.subTest(frame=frame):
                fake = FakeFreshFrameMain([frame, 'port', 'map'])

                self.assertTrue(fake._wait_until_back_in_os_map(timeout=5))

                self.assertEqual(fake.clicked, clicks + ['port_quit'])
                self.assertEqual(fake.screenshots, [frame, 'port', 'map'])

    def test_fresh_map_returns_without_clicking(self):
        fake = FakeFreshFrameMain(['map'])

        self.assertTrue(fake._wait_until_back_in_os_map(timeout=5))

        self.assertEqual(fake.clicked, [])
        self.assertEqual(fake.screenshots, ['map'])


class FakeDepartureMain:
    """只挂出发确认所需接口的桩，模拟离开弹窗出现在出发确认之前。"""

    _confirm_departure = OpsiFleetAutoChange._confirm_departure

    def __init__(self, popup_calls=()):
        """
        Args:
            popup_calls: 第几次调用弹窗处理器时弹窗存在（1 为出发前的预检查）。
        """
        self.popup_calls = set(popup_calls)
        self.popup_call_count = 0
        self.popup_active = False
        self.clicked = []
        self.device = SimpleNamespace(click=self._click, screenshot=lambda: None)

    def _click(self, button):
        if self.popup_active and button in (DEPART_IMMEDIATELY_BUTTON, DEPART_CONFIRM_BUTTON):
            raise AssertionError('离开大型作战弹窗未关闭时不应点击出发按钮')
        self.clicked.append(button.name)

    def loop(self, skip_first=True, timeout=None):
        while True:
            yield None

    def handle_leave_os_popup(self):
        self.popup_call_count += 1
        self.popup_active = self.popup_call_count in self.popup_calls
        if self.popup_active:
            self.clicked.append(LEAVE_OS_POPUP_CLOSE.name)
        return self.popup_active

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        if button is DEPART_CONFIRM_TEMPLATE:
            if self.popup_active:
                raise AssertionError('离开大型作战弹窗未关闭时不应检查出发确认')
            return True
        raise AssertionError(f'未预期的按钮: {button}')

    def _wait_until_back_in_os_map(self, timeout=60):
        self.clicked.append('wait_map')
        return True


class TestConfirmDeparturePopupOrder(unittest.TestCase):
    def test_popup_closed_before_depart_click(self):
        """出发前画面上有离开弹窗：先关闭弹窗，再点立即前往。"""
        fake = FakeDepartureMain(popup_calls={1, 2})

        fake._confirm_departure()

        self.assertEqual(fake.clicked, [
            LEAVE_OS_POPUP_CLOSE.name,
            LEAVE_OS_POPUP_CLOSE.name,
            DEPART_IMMEDIATELY_BUTTON.name,
            DEPART_CONFIRM_BUTTON.name,
            'wait_map',
        ])

    def test_popup_during_confirm_wait_not_confirmed(self):
        """等待出发确认期间弹出离开弹窗：只关闭，不点成出发确认。"""
        fake = FakeDepartureMain(popup_calls={2, 3})

        fake._confirm_departure()

        self.assertEqual(fake.clicked, [
            DEPART_IMMEDIATELY_BUTTON.name,
            LEAVE_OS_POPUP_CLOSE.name,
            LEAVE_OS_POPUP_CLOSE.name,
            DEPART_CONFIRM_BUTTON.name,
            'wait_map',
        ])


if __name__ == '__main__':
    unittest.main()
