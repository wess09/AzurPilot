"""指挥喵强化的选中确认、滚动归位与重复执行回归测试。"""

import collections
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.base.timer import Timer
from module.device.device import Device
from module.exception import GameStuckError, GameTooManyClickError
from module.meowfficer.enhance import (
    MEOWFFICER_COINS,
    MEOWFFICER_ENHANCE_CAPACITY,
    MeowfficerEnhance,
)


FIXTURES = Path(__file__).parent / 'fixtures' / 'meowfficer_enhance'


def frame(ring='unselected', scroll='scroll_top'):
    """用匿名圆环与滚动条裁剪重建识别所需的两个区域。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[421:548, 983:1110] = np.array(Image.open(FIXTURES / f'{ring}.png'))
    if scroll:
        image[139:549, 1247:1256] = np.array(Image.open(FIXTURES / f'{scroll}.png'))
    return image


def runner(image=None, index=11):
    main = MeowfficerEnhance.__new__(MeowfficerEnhance)
    main.config = SimpleNamespace(MeowfficerTrain_EnhanceIndex=index, MeowfficerTrain_Enable=True)
    main.device = SimpleNamespace(image=frame() if image is None else image)
    return main


class SelectionImageTests(unittest.TestCase):
    def test_real_selected_ring_is_accepted(self):
        self.assertTrue(runner(frame('selected'))._meow_target_selected(2, 2))

    def test_unselected_cat_is_rejected(self):
        self.assertFalse(runner(frame('unselected'))._meow_target_selected(2, 2))

    def test_real_white_content_that_passed_old_check_is_rejected(self):
        self.assertFalse(runner(frame('false_white'))._meow_target_selected(2, 2))

    def test_white_ring_without_yellow_dashes_is_rejected(self):
        image = frame('selected')
        region = image[421:548, 983:1110]
        region[np.any(region, axis=2)] = 255
        self.assertFalse(runner(image)._meow_target_selected(2, 2))

    def test_incomplete_frame_is_rejected(self):
        self.assertFalse(runner(np.zeros((480, 800, 3), dtype=np.uint8))._meow_target_selected(2, 2))

    def test_real_scroll_position_must_be_at_top(self):
        self.assertTrue(runner(frame())._meow_cattery_at_top())
        self.assertFalse(runner(frame(scroll='scroll_middle'))._meow_cattery_at_top())

    def test_missing_scrollbar_requires_positive_small_cattery_capacity(self):
        main = runner(frame(scroll=None))
        with patch.object(MEOWFFICER_ENHANCE_CAPACITY, 'ocr') as read:
            for capacity, expected in [((12, 88, 100), True), ((1, 99, 100), True),
                                       ((68, 32, 100), False), ((0, 0, 0), False),
                                       ((0, 100, 100), False)]:
                with self.subTest(capacity=capacity):
                    read.return_value = capacity
                    self.assertEqual(main._meow_cattery_at_top(), expected)


class SelectionFlowTests(unittest.TestCase):
    def select(self, initial):
        main = runner(initial)
        clock = [100.0]
        screenshots, swipes, clicks = [], [], []
        next_image = [initial]
        pending_selection = [False]

        def screenshot():
            clock[0] += 0.35
            screenshots.append(clock[0])
            if len(screenshots) > 30:
                raise AssertionError('选猫没有在有限截图内完成')
            main.device.image = next_image[0]
            if pending_selection[0]:
                # 点击后的首帧仍是旧画面，下一帧才出现选中圈。
                next_image[0] = frame('selected')
                pending_selection[0] = False

        def swipe(start, end, **kwargs):
            # 猫窝内的向下手势才能恢复顶部；错误方向或区域不能伪造归位画面。
            self.assertTrue(720 <= start[0] <= 1200 and 720 <= end[0] <= 1200)
            self.assertTrue(139 <= start[1] < end[1] <= 549)
            self.assertEqual(start[0], end[0])
            swipes.append(len(screenshots))
            next_image[0] = frame()

        def click(button):
            clicks.append(len(screenshots))
            pending_selection[0] = True

        main.device.screenshot = screenshot
        main.device.swipe = swipe
        main.device.click = click
        main.meow_additional = lambda: False
        with patch('module.base.timer.time', side_effect=lambda: clock[0]):
            main._meow_select()
        self.assertTrue(main._meow_target_selected(2, 2))
        self.assertEqual(main.config.MeowfficerTrain_EnhanceIndex, 11)
        self.assertTrue(main.config.MeowfficerTrain_Enable)
        self.assertEqual(len(clicks), 1)
        self.assertGreater(len(screenshots), clicks[0] + 1)
        return swipes, clicks

    def test_scrolled_white_false_positive_is_reset_before_clicking(self):
        swipes, clicks = self.select(frame('false_white', 'scroll_middle'))
        self.assertEqual(len(swipes), 1)
        self.assertLess(swipes[0], clicks[0])

    def test_preexisting_ring_does_not_skip_click_and_fresh_confirmation(self):
        swipes, _ = self.select(frame('selected'))
        self.assertEqual(swipes, [])

    def test_unconfirmed_target_triggers_existing_click_recovery(self):
        main = runner(frame('false_white'))
        main.meow_additional = lambda: False
        device = Device.__new__(Device)
        device.image = main.device.image
        device.detect_record = set()
        device.click_record = collections.deque(maxlen=15)
        device._prev_fingerprint = None
        device.app_is_running = Mock(return_value=True)
        main.device = device
        clock = [100.0]
        screenshots, clicks = [], []

        def screenshot():
            clock[0] += 0.35
            screenshots.append(clock[0])
            if len(screenshots) > 150:
                raise AssertionError('未选中目标时没有触发已有恢复保护')
            # 画面始终未选中，复用实际设备的两种卡死检测，不直接注入异常。
            device.stuck_record_check()
            device._check_image_stuck()

        def click(button):
            clicks.append(button)
            # 仅隔离实际触屏；重复点击检测和卡死计时器重置使用真实实现。
            device.handle_control_check(button)

        device.screenshot = screenshot
        device.click = click
        with (
            patch('module.base.timer.time', side_effect=lambda: clock[0]),
            patch.object(main, '_meow_target_selected', wraps=main._meow_target_selected) as confirm,
        ):
            device.stuck_timer = Timer(60, count=60).start()
            device.stuck_timer_long = Timer(195, count=195).start()
            device._stuck_image_timer = Timer(30, count=0)
            # 每次点击会重置卡死计时器，实际先由第 12 次重复点击触发恢复。
            with self.assertRaisesRegex(GameTooManyClickError, '按钮点击次数过多'):
                main._meow_select()
            self.assertGreater(confirm.call_count, 1)
        self.assertEqual(len(clicks), 12)
        self.assertEqual(len({str(button) for button in clicks}), 1)
        self.assertGreater(len(screenshots), len(clicks))
        self.assertEqual(main.config.MeowfficerTrain_EnhanceIndex, 11)
        self.assertTrue(main.config.MeowfficerTrain_Enable)


class EnhanceLoopTests(unittest.TestCase):
    def test_non_max_result_ends_without_second_enhancement(self):
        for result in ('success', 'invalid', 'coin_limit', 'in_battle'):
            with self.subTest(result=result):
                main = runner()
                main._meow_enhance = Mock(side_effect=[result, 'leveled_max', 'success'])
                main.meow_enhance()
                main._meow_enhance.assert_called_once_with()
                self.assertEqual(main.config.MeowfficerTrain_EnhanceIndex, 11)
                self.assertTrue(main.config.MeowfficerTrain_Enable)

    def test_confirmed_max_level_advances_once(self):
        main = runner()
        indices = []
        def enhance():
            indices.append(main.config.MeowfficerTrain_EnhanceIndex)
            return 'leveled_max' if len(indices) == 1 else 'success'
        main._meow_enhance = enhance
        main.meow_enhance()
        self.assertEqual(indices, [11, 12])
        self.assertTrue(main.config.MeowfficerTrain_Enable)

    def test_confirmed_twelfth_max_level_disables_once(self):
        main = runner(index=12)
        main._meow_enhance = Mock(return_value='leveled_max')
        main.meow_enhance()
        main._meow_enhance.assert_called_once_with()
        self.assertFalse(main.config.MeowfficerTrain_Enable)

    def test_invalid_ocr_level_never_feeds_or_advances(self):
        for level in (0, 31, 99):
            with self.subTest(level=level):
                main = runner()
                main._meow_select = Mock()
                main._meow_get_level = Mock(return_value=level)
                main.meow_enhance_enter = Mock()
                with patch.object(MEOWFFICER_COINS, 'ocr', return_value=2000):
                    with self.assertRaises(GameStuckError):
                        main.meow_enhance()
                main.meow_enhance_enter.assert_not_called()
                self.assertEqual(main.config.MeowfficerTrain_EnhanceIndex, 11)
                self.assertTrue(main.config.MeowfficerTrain_Enable)


if __name__ == '__main__':
    unittest.main()
