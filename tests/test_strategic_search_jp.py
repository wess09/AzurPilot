"""日服计划作战换行布局修复的离线回归测试。"""

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
        handler = self.make_handler('cn')
        self.assertTrue(handler.strategic_search_set_option())
        self.assertEqual(scroll.set.call_count, 1)
        self.assertEqual(scroll.set.call_args_list[0].args, (0.5,))
        self.assertEqual(handler._strategy_search_scroll_appear.call_count, 2)
        for args in handler.appear.call_args_list:
            self.assertIsNot(args.args[0], merchant_check)


if __name__ == '__main__':
    unittest.main()
