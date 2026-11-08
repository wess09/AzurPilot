"""日服计划作战换行布局修复的离线回归测试。"""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from module.os_handler.strategic import StrategicSearchHandler


class TestStrategicSearchJapaneseLayout(unittest.TestCase):
    def make_handler(self, server):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.config = Mock(SERVER=server)
        handler.loop = Mock(side_effect=[iter([None]), iter([None]), iter([None])])
        handler._strategy_search_scroll_appear = Mock(return_value=True)
        handler._strategy_option_selected = Mock(return_value=True)
        handler.appear = Mock(return_value=True)
        handler.device = Mock()
        return handler

    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_SCROLL')
    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_MERCHANT_CHECK')
    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_ZONEMODE_REPEAT')
    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_ZONEMODE_RANDOM')
    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_MERCHANT_STOP')
    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_MERCHANT_CONTINUE')
    def test_jp_scrolls_to_wrapped_options_and_updates_button_offsets(
            self, merchant_continue, merchant_stop, zone_random, zone_repeat,
            merchant_check, scroll):
        handler = self.make_handler('jp')
        self.assertTrue(handler.strategic_search_set_option())
        self.assertEqual(scroll.set.call_count, 2)
        self.assertEqual(scroll.set.call_args_list[0].args, (0.17,))
        self.assertEqual(scroll.set.call_args_list[0].kwargs['random_range'], (-0.01, 0.01))
        self.assertIs(scroll.set.call_args_list[0].kwargs['distance_check'], False)
        merchant_check.load_offset.assert_not_called()
        handler.appear.assert_any_call(merchant_check, offset=(20, 100))
        for button in (zone_repeat, zone_random, merchant_stop, merchant_continue):
            button.load_offset.assert_called_once_with(merchant_check)
        self.assertEqual(handler._strategy_search_scroll_appear.call_count, 3)

    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_SCROLL')
    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_MERCHANT_CHECK')
    def test_other_servers_keep_existing_scroll_flow(self, merchant_check, scroll):
        for server in ('cn', 'en', 'tw'):
            with self.subTest(server=server):
                scroll.reset_mock()
                handler = self.make_handler(server)
                self.assertTrue(handler.strategic_search_set_option())
                self.assertEqual(scroll.set.call_count, 1)
                self.assertEqual(scroll.set.call_args_list[0].args, (0.5,))
                self.assertEqual(handler._strategy_search_scroll_appear.call_count, 2)
                for args in handler.appear.call_args_list:
                    self.assertIsNot(args.args[0], merchant_check)

    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_SCROLL')
    def test_jp_waits_for_merchant_anchor_before_reading_or_clicking_options(self, scroll):
        handler = self.make_handler('jp')
        handler.loop.side_effect = [iter([None, None]), iter([None]), iter([None])]
        handler.appear.side_effect = [False, True, True, True]

        def selected(button):
            # 第一帧未识别到标题时，不能沿用上一次滚动的选项坐标。
            self.assertGreaterEqual(handler.appear.call_count, 2)
            return True

        handler._strategy_option_selected.side_effect = selected
        self.assertTrue(handler.strategic_search_set_option())
        self.assertEqual(handler.appear.call_count, 4)
        self.assertEqual(handler._strategy_option_selected.call_count, 4)
        handler.device.click.assert_not_called()

    @patch('module.os_handler.strategic.STRATEGIC_SEARCH_SCROLL')
    def test_jp_disappeared_scroll_returns_to_existing_start_retry(self, scroll):
        handler = self.make_handler('jp')
        handler._strategy_search_scroll_appear.return_value = False
        self.assertFalse(handler.strategic_search_set_option())
        handler._strategy_option_selected.assert_not_called()
        handler.device.click.assert_not_called()
        scroll.set_bottom.assert_not_called()


class TestStrategicSearchJapaneseScreenshot(unittest.TestCase):
    def test_native_wrapped_panel_and_scroll_offsets(self):
        # Button 在导入时缓存服务器资源，日服实图识别需隔离于其他测试。
        code = r'''
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import module.config.server as server
server.server = 'jp'
from module.base.utils import load_image
from module.os_handler.assets import (
    STRATEGIC_SEARCH_MERCHANT_CHECK, STRATEGIC_SEARCH_MERCHANT_STOP,
    STRATEGIC_SEARCH_POPUP_CHECK, STRATEGIC_SEARCH_ZONEMODE_RANDOM,
    STRATEGIC_SEARCH_ZONEMODE_REPEAT,
)
from module.os_handler.strategic import StrategicSearchHandler, STRATEGIC_SEARCH_SCROLL

image = load_image('tests/fixtures/strategic_search_jp/wrapped_top.png')
assert image.shape == (720, 1280, 3)
handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
handler.config = SimpleNamespace(SERVER='jp', BUTTON_OFFSET=(30, 30))
handler.device = Mock(image=image)
assert handler.appear(STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20))
assert STRATEGIC_SEARCH_SCROLL.appear(handler)
assert STRATEGIC_SEARCH_SCROLL.at_top(handler)

for dy in (0, -58, -63, -68):
    # 只平移原图可见的内容，不补画商人选项；这些变体不是实机滚动截图。
    frame = image.copy()
    if dy:
        frame[277:470, 373:903] = 0
        frame[277:470 + dy, 373:903] = image[277 - dy:470, 373:903]
    handler.device.image = frame
    assert handler.appear(STRATEGIC_SEARCH_MERCHANT_CHECK, offset=(20, 100)), dy
    anchor = STRATEGIC_SEARCH_MERCHANT_CHECK
    assert tuple(np.subtract(anchor.button, anchor._button)) == (0, 63 + dy, 0, 63 + dy), dy
    for button in (STRATEGIC_SEARCH_ZONEMODE_REPEAT, STRATEGIC_SEARCH_ZONEMODE_RANDOM,
                   STRATEGIC_SEARCH_MERCHANT_STOP):
        button.load_offset(anchor)
    assert handler._strategy_option_selected(STRATEGIC_SEARCH_ZONEMODE_REPEAT), dy
    assert not handler._strategy_option_selected(STRATEGIC_SEARCH_ZONEMODE_RANDOM), dy
    # 原图中商人选项未完整露出，不能把标题或截断的文字当成已勾选。
    assert not handler._strategy_option_selected(STRATEGIC_SEARCH_MERCHANT_STOP), dy

blank = np.zeros_like(image)
handler.device.image = blank
assert not handler.appear(STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20))
assert not handler.appear(STRATEGIC_SEARCH_MERCHANT_CHECK, offset=(20, 100))
assert not handler._strategy_option_selected(STRATEGIC_SEARCH_ZONEMODE_REPEAT)
'''
        result = subprocess.run(
            [sys.executable, '-X', 'utf8', '-c', code],
            cwd=Path(__file__).resolve().parents[1],
            env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1'),
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
