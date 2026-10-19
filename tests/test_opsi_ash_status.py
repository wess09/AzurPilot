"""信标原生字图校验及错误读数反复抢占大世界任务的离线回归。"""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import numpy as np

from module.base.utils import load_image
from module.ocr.ocr import DigitCounter, Ocr
from module.os_ash.ash import AshDigitCounter, OSAsh
from module.os_ash.assets import ASH_COLLECT_STATUS, ASH_DAILY_STATUS


FIXTURES = Path(__file__).parent / 'fixtures' / 'opsi_beacon'
GRAY = (140, 142, 140)
WHITE = (235, 235, 235)


def map_image():
    """仅还原两个原生计数区域，不包含账号或其他游戏画面。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    for button, name in (
        (ASH_COLLECT_STATUS, 'map_70_200_gray.png'),
        (ASH_DAILY_STATUS, 'daily_200_gray.png'),
    ):
        x1, y1, x2, y2 = button.area
        image[y1:y2, x1:x2] = load_image(str(FIXTURES / name))
    return image


def model_output(text):
    return [list(text)]


class AshDigitCounterTests(unittest.TestCase):
    def setUp(self):
        self.image = map_image()
        self.model = SimpleNamespace(atomic_ocr_for_single_lines=Mock())
        self.enterContext(patch.object(Ocr, 'cnocr', PropertyMock(return_value=self.model)))

    def read(self, text, image=None, letter=GRAY, counter_type=AshDigitCounter):
        self.model.atomic_ocr_for_single_lines.return_value = model_output(text)
        counter = counter_type(ASH_COLLECT_STATUS, letter=letter, threshold=160)
        return counter.ocr(self.image if image is None else image)

    def test_native_70_is_accepted(self):
        self.assertEqual(self.read('70/200'), (70, 130, 200))

    def test_phantom_hundreds_digit_is_rejected_before_task_dispatch(self):
        # 复现日志里的模型输出：普通计数器会直接接受 170，原图实际只有两位。
        self.assertEqual(self.read('170/200', counter_type=DigitCounter), (170, 30, 200))
        self.assertEqual(self.read('170/200'), (0, 0, 0))
        self.assertEqual(self.read('I70/200'), (0, 0, 0))

    def test_invalid_counter_is_not_clamped_into_full_data(self):
        for text in ('270/200', '700/200', '70/20', '70/2000', '70/300', '70200', '070/200'):
            with self.subTest(text=text):
                self.assertEqual(self.read(text), (0, 0, 0))

    def test_white_hundred_from_existing_resource_is_accepted(self):
        image = load_image('assets/cn/os_ash/ASH_COLLECT_STATUS.png')
        self.assertEqual(self.read('100/100', image=image, letter=WHITE), (100, 0, 100))

    def test_real_hundreds_glyph_is_not_removed(self):
        # 合成反例：在原生 70 字图前放入资源中的完整 1，不能一律删除百位。
        image = self.image.copy()
        source = load_image('assets/cn/os_ash/ASH_COLLECT_STATUS.png')
        x1, y1, x2, y2 = ASH_COLLECT_STATUS.area
        native = source[y1:y2, x1:x2]
        one = DigitCounter(ASH_COLLECT_STATUS, letter=WHITE, threshold=160).pre_process(native)[:, 13:19]
        region = image[y1:y2, x1 + 13:x1 + 19]
        region[one < 120] = GRAY
        self.assertEqual(self.read('170/200', image=image), (170, 30, 200))


class AshTaskDispatchTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 21, 41)
        self.next_run = datetime(2026, 10, 19)
        self.task_call = Mock()
        self.model = SimpleNamespace(atomic_ocr_for_single_lines=Mock())
        self.enterContext(patch.object(Ocr, 'cnocr', PropertyMock(return_value=self.model)))
        self.enterContext(patch('module.os_ash.ash.current_time', side_effect=lambda: self.now))

    def runner(self, mode='current', enabled=True, white=False):
        values = {
            'OpsiAshBeacon.Scheduler.NextRun': self.next_run,
            'OpsiAshBeacon.OpsiAshBeacon.AttackMode': mode,
        }
        runner = OSAsh.__new__(OSAsh)
        runner.config = SimpleNamespace(
            is_task_enabled=Mock(return_value=enabled),
            cross_get=lambda keys, default=None: values.get(keys, default),
            task_call=self.task_call,
        )
        image = map_image()
        if white:
            source = load_image('assets/cn/os_ash/ASH_COLLECT_STATUS.png')
            x1, y1, x2, y2 = ASH_COLLECT_STATUS.area
            image[y1:y2, x1:x2] = source[y1:y2, x1:x2]
        runner.device = SimpleNamespace(image=image)
        return runner

    def test_recreated_world_tasks_do_not_repeat_false_meta_dispatch(self):
        self.model.atomic_ocr_for_single_lines.side_effect = [
            model_output(text) for _ in range(12) for text in ('170/200', '200/200')
        ]
        for _ in range(12):
            # 模拟委托、META 与智能调度切换后重新创建大世界对象。
            runner = self.runner()
            self.assertFalse(runner.handle_ash_beacon_attack())
            self.assertTrue(runner._ash_fully_collected)
            self.now += timedelta(seconds=20)
        self.task_call.assert_not_called()

    def test_native_below_threshold_does_not_dispatch(self):
        self.model.atomic_ocr_for_single_lines.side_effect = [
            model_output('70/200'), model_output('200/200'),
        ]
        runner = self.runner()
        self.assertFalse(runner.handle_ash_beacon_attack())
        self.assertTrue(runner._ash_fully_collected)
        self.task_call.assert_not_called()

    def test_valid_hundred_still_dispatches(self):
        self.model.atomic_ocr_for_single_lines.side_effect = [
            model_output('100/100'), model_output('200/200'),
        ]
        self.assertTrue(self.runner(white=True).handle_ash_beacon_attack())
        self.task_call.assert_called_once_with(task='OpsiAshBeacon')

    def test_dossier_only_keeps_daily_state_without_dispatch(self):
        self.model.atomic_ocr_for_single_lines.side_effect = [
            model_output('100/100'), model_output('200/200'),
        ]
        runner = self.runner(mode='current_dossier_only', white=True)
        self.assertFalse(runner.handle_ash_beacon_attack())
        self.assertTrue(runner._ash_fully_collected)
        self.task_call.assert_not_called()

    def test_disabled_task_does_not_read_or_dispatch(self):
        self.assertFalse(self.runner(enabled=False).handle_ash_beacon_attack())
        self.model.atomic_ocr_for_single_lines.assert_not_called()
        self.task_call.assert_not_called()

    def test_assist_wait_is_respected_for_valid_data(self):
        for minutes, expected in ((29, False), (30, False), (31, True)):
            with self.subTest(minutes=minutes):
                self.task_call.reset_mock()
                self.next_run = self.now + timedelta(minutes=minutes)
                self.model.atomic_ocr_for_single_lines.side_effect = [
                    model_output('100/100'), model_output('200/200'),
                ]
                self.assertEqual(self.runner(white=True).handle_ash_beacon_attack(), expected)
                self.assertEqual(self.task_call.call_count, int(expected))


if __name__ == '__main__':
    unittest.main()
