"""回放自选轻量复刻截图，验证退出操作和登录后的主界面确认。"""

import unittest
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import module.config.server as server

# 在加载游戏资源前固定国服，避免测试环境加载其他服务器的模板。
server.server = 'cn'

from module.base.utils import load_image
from module.handler.assets import LOGIN_CHECK
from module.handler.login import LoginHandler
from module.ui.assets import CAPSULE_RERUN_CHECK
from module.ui.page import page_main, page_main_white
from module.ui.ui import UI
from module.ui_white.assets import BACK_ARROW_WHITE


FIXTURES = Path(__file__).parent / 'fixtures'


def make_ui(image=None, cls=UI):
    """只使用内存设备和最小配置，不初始化用户实例或连接模拟器。"""
    ui = object.__new__(cls)
    ui.config = SimpleNamespace(SERVER='cn', BUTTON_OFFSET=(30, 30), data={})
    ui.device = Mock(image=load_image(str(FIXTURES / 'capsule_rerun' / 'select.png'))
                     if image is None else image.copy())
    ui.interval_timer = {}
    return ui


class CapsuleRerunPopupTests(unittest.TestCase):
    def test_original_screenshot_recognizes_page_and_existing_arrow(self):
        ui = make_ui()
        self.assertTrue(ui.appear(CAPSULE_RERUN_CHECK, offset=(5, 5)))
        self.assertTrue(ui.appear(BACK_ARROW_WHITE, offset=(30, 30)))
        self.assertFalse(ui.is_in_main())

    def test_popup_clicks_only_existing_back_arrow(self):
        ui = make_ui()
        self.assertTrue(ui.ui_page_main_popups())
        ui.device.click.assert_called_once_with(BACK_ARROW_WHITE)
        left, top, right, bottom = BACK_ARROW_WHITE.button
        self.assertTrue(0 <= left < right <= 110)
        self.assertTrue(18 <= top < bottom <= 72)
        ui.device.screenshot.assert_not_called()

    def test_back_arrow_alone_does_not_dismiss_other_pages(self):
        ui = make_ui()
        ui.device.image[640:, 1040:] = 0
        self.assertTrue(ui.appear(BACK_ARROW_WHITE, offset=(30, 30)))
        self.assertFalse(ui.ui_page_main_popups())
        ui.device.click.assert_not_called()

    def test_page_marker_without_arrow_does_not_click(self):
        ui = make_ui()
        ui.device.image[:100, :115] = 0
        self.assertTrue(ui.appear(CAPSULE_RERUN_CHECK, offset=(5, 5)))
        self.assertFalse(ui.ui_page_main_popups())
        ui.device.click.assert_not_called()

    def test_return_arrow_cooldown_prevents_repeated_clicks(self):
        ui = make_ui()
        self.assertTrue(ui.ui_page_main_popups())
        self.assertFalse(ui.ui_page_main_popups())
        ui.device.click.assert_called_once_with(BACK_ARROW_WHITE)
        ui.interval_clear(BACK_ARROW_WHITE)
        self.assertTrue(ui.ui_page_main_popups())
        self.assertEqual(ui.device.click.call_count, 2)

    def test_detection_does_not_depend_on_event_cards_or_dates(self):
        ui = make_ui()
        ui.device.image[95:625] = 0
        ui.device.image[650:, :1000] = 0
        self.assertTrue(ui.ui_page_main_popups())
        ui.device.click.assert_called_once_with(BACK_ARROW_WHITE)

    def test_other_event_and_main_pages_are_not_dismissed(self):
        images = [FIXTURES / 'campaign_event_navigation' / name
                  for name in ('crimson.png', 'light.png')]
        images.extend(Path(page.check_button.file) for page in (page_main, page_main_white))
        for path in images:
            with self.subTest(image=path):
                ui = make_ui(load_image(str(path)))
                self.assertFalse(ui.ui_page_main_popups())
                ui.device.click.assert_not_called()

    def test_navigation_popup_chain_uses_same_dismissal(self):
        ui = make_ui()
        ui.ui_page_os_popups = Mock(return_value=False)
        ui.handle_popup_confirm = Mock(return_value=False)
        ui.handle_urgent_commission = Mock(return_value=False)
        self.assertTrue(ui.ui_additional())
        ui.device.click.assert_called_once_with(BACK_ARROW_WHITE)


class CapsuleRerunLoginTests(unittest.TestCase):
    def test_login_waits_for_stable_main_page_after_dismissal(self):
        for main_page, login_screen in product((page_main, page_main_white), (False, True)):
            with self.subTest(theme=main_page.name, login_screen=login_screen):
                login = make_ui(cls=LoginHandler)
                select_image = login.device.image.copy()
                login_image = load_image(LOGIN_CHECK.file)
                main_image = load_image(main_page.check_button.file)
                login.handle_cn_user_agreement = Mock(return_value=False)
                login.handle_popup_confirm = Mock(return_value=False)
                login.handle_urgent_commission = Mock(return_value=False)
                clock = [100.0]
                main_frames = []

                def screenshot():
                    if login.device.screenshot.call_count > 20:
                        self.fail('登录循环没有在主界面确认后退出')
                    clock[0] += 1
                    # 返回点击后仍保留一帧选择页，模拟界面切换延迟。
                    if login_screen and login.device.screenshot.call_count == 1:
                        login.device.image = login_image.copy()
                    elif login.device.screenshot.call_count <= 2 + int(login_screen):
                        login.device.image = select_image.copy()
                    else:
                        login.device.image = main_image.copy()
                        main_frames.append(login.device.screenshot.call_count)

                login.device.screenshot.side_effect = screenshot
                with patch('module.base.timer.time', side_effect=lambda: clock[0]):
                    self.assertTrue(login._handle_app_login())

                self.assertTrue(login.is_in_main())
                self.assertGreaterEqual(len(main_frames), 5)
                expected = [call(LOGIN_CHECK)] if login_screen else []
                self.assertEqual(login.device.click.call_args_list, expected + [call(BACK_ARROW_WHITE)])
                login.device.app_stop.assert_not_called()
                login.device.app_start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
