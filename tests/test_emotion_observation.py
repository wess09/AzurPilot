"""被动相位学习的时间、完整舰队、独立对照及真实保存事务验证。"""

import copy
import json
import random
import tempfile
import time
import unittest
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dev_tools.emotion_simulate import LuaOracle, ShipSpec, BASE, US
from module.combat.emotion_state import EmotionRecoveryState, PERIOD_US, time_us
from module.config.config import AzurLaneConfig
from module.retire.fleet_emotion import learn_fleet_emotion, screenshot_window
from module.retire.fleet_management import FleetManagement


class ObservationStateTests(unittest.TestCase):
    def state(self, value=100):
        return EmotionRecoveryState.calibrate(value, BASE, 'dormitory_floor_2', True, False)

    def test_async_categories_preserve_phase_and_shrink_range(self):
        state = self.state()
        t40, t60 = BASE + timedelta(seconds=40), BASE + timedelta(seconds=60)
        self.assertTrue(state.observe([(106, t40, t40), (106, t60, t60)]))
        self.assertEqual([(1, 60 * US + 1, 106)], state.segments)
        self.assertEqual((106, 106), (state.lower, state.upper))
        state.advance(BASE + timedelta(seconds=360))
        self.assertEqual(106, state.value)
        state.advance(BASE + timedelta(seconds=421))
        self.assertEqual(112, state.value)

    def test_different_read_times_do_not_imply_the_higher_value_is_fleet_minimum(self):
        state = self.state()
        self.assertTrue(state.observe([(106, BASE + timedelta(seconds=60), BASE + timedelta(seconds=60)),
                                       (100, BASE + timedelta(seconds=40), BASE + timedelta(seconds=40))]))
        self.assertEqual((100, 106), (state.lower, state.upper))

    def test_window_straddling_tick_does_not_claim_exact_time(self):
        state = self.state()
        self.assertTrue(state.observe([(106, BASE + timedelta(seconds=59), BASE + timedelta(seconds=61))]))
        state.advance(BASE + timedelta(seconds=420))
        self.assertEqual((106, 112), (state.lower, state.upper))

    def test_contradiction_invalid_times_and_intermediate_integer_keep_state(self):
        for points, begin, end in [(103, 60, 60), (90, 60, 60), (106, 60, 59),
                                   (106, -1, 2), (106, 0, 31), (True, 60, 60)]:
            state = self.state()
            original = state.export()
            self.assertFalse(state.observe([(points, BASE + timedelta(seconds=begin), BASE + timedelta(seconds=end))]))
            self.assertEqual(original, state.export())

    def test_v1_compatibility_v2_gaps_and_gap_safe_merge(self):
        state = self.state()
        data = {**state.export(), 'version': 1}
        state = EmotionRecoveryState.restore(data, 100, BASE, state.recover, True, False)
        data = {**state.export(), 'segments': [[0, 10, 100], [20, 30, 100]]}
        state = EmotionRecoveryState.restore(json.loads(json.dumps(data)), 100, BASE, state.recover, True, False)
        state.consume(2)
        state.advance(BASE + timedelta(seconds=360))
        self.assertEqual([(0, 10, 104), (20, 30, 104)], state.segments)
        data['version'] = 1
        with self.assertRaises(ValueError):
            EmotionRecoveryState.restore(data, 100, BASE, state.recover, True, False)

    def test_fragment_limit_abandons_whole_observation(self):
        state = self.state()
        state.segments = [(i * 3, i * 3 + 1, 100) for i in range(64)]
        original = state.export()
        self.assertFalse(state.observe([(100, BASE, BASE)]))
        self.assertEqual(original, state.export())
        data = {**original, 'segments': original['segments'] + [[200, 201, 100]]}
        with self.assertRaises(ValueError):
            EmotionRecoveryState.restore(data, 100, BASE, state.recover, True, False)

    def test_random_true_phase_is_never_filtered_out(self):
        rng = random.Random(1092026)
        spec = ShipSpec('dormitory_floor_2', True)
        for case in range(120):
            initial, origin = rng.randrange(45, 141), rng.randrange(US)
            phase = rng.randrange(PERIOD_US)
            oracle = LuaOracle(spec, initial, origin, phase)
            state = EmotionRecoveryState.calibrate(initial, BASE + timedelta(microseconds=origin), spec.recover, True, False)
            actual_phase = (time_us(BASE) + oracle.next_tick) % PERIOD_US
            cursor = origin
            for step in range(40):
                if oracle.values[0] >= 4:
                    state.advance(BASE + timedelta(microseconds=cursor))
                    state.consume(4)
                    oracle.consume(0, 4)
                observations = []
                previous = copy.deepcopy(state)
                for _ in range(2):
                    width = rng.choice((100_000, US, 30 * US))
                    begin = cursor + rng.randrange(70 * US, 110 * US)
                    sample = begin + rng.randrange(width + 1)
                    oracle.advance(sample)
                    points = oracle.values[0]
                    end = begin + width
                    observations.append((points, BASE + timedelta(microseconds=begin), BASE + timedelta(microseconds=end)))
                    oracle.advance(end)
                    cursor = end
                self.assertTrue(state.observe(observations), (case, step))
                previous.advance(state.record)
                self.assertLessEqual(state.recovered_at(42), previous.recovered_at(42))
                self.assertTrue(any(a <= actual_phase < b for a, b, _ in state.segments), (case, step))
                self.assertLessEqual(abs(state.value - oracle.values[0]), 3)
                self.assertLessEqual(len(state.segments), 64)


class FleetObservationTests(unittest.TestCase):
    def test_existing_ship_change_writers_rebuild_atomic_state(self):
        from module.campaign.gems_farming import GemsFarming, GemsEmotion
        from module.campaign.ambush_1_1 import Ambush11, AmbushEmotion
        from module.config.config import name_to_function
        from module.config.utils import read_file, write_file
        import module.combat.emotion as production
        from dev_tools.emotion_simulate import QuietLogger

        @contextmanager
        def directory_for_transaction():
            directory = tempfile.TemporaryDirectory()
            try:
                yield directory.name
            finally:
                # Windows 删除刚释放的事务锁文件可能短暂返回目录非空；只重试清理。
                for attempt in range(3):
                    try:
                        directory.cleanup()
                        break
                    except OSError as exc:
                        if getattr(exc, 'winerror', None) != 145 or attempt == 2:
                            raise
                        time.sleep(0.05)
                self.assertFalse(Path(directory.name).exists())

        stamp = BASE + timedelta(microseconds=123456)
        for task, runner_class, tracker_class in [('GemsFarming', GemsFarming, GemsEmotion),
                                                  ('ThreeOilLowCost', GemsFarming, GemsEmotion),
                                                  ('Ambush11', Ambush11, AmbushEmotion)]:
            for index in (1, 2):
                worker = AzurLaneConfig.__new__(AzurLaneConfig)
                worker.data = worker.config_update({})
                worker.modified, worker.bound, worker.overridden = {}, {}, {}
                worker.auto_update = False
                worker.data[task]['Fleet']['FleetOrder'] = (
                    'fleet1_all_fleet2_standby' if index == 1 else 'fleet1_standby_fleet2_all')
                worker.bind(task)
                worker.task = name_to_function(task)
                runner = runner_class.__new__(runner_class)
                runner.config = worker
                runner.campaign = SimpleNamespace(config=worker)
                with directory_for_transaction() as directory, \
                        patch('module.config.config.current_time', return_value=stamp), \
                        patch.object(production, 'current_time', return_value=stamp), \
                        patch.object(production, 'logger', QuietLogger()), \
                        patch.object(AzurLaneConfig, 'config_override'):
                    path = str(Path(directory) / 'anonymous.json')
                    worker.config_name = 'anonymous'
                    worker._loaded_data = copy.deepcopy(worker.data)
                    write_file(path, worker.data)
                    worker.read_file = lambda name: worker.config_update(read_file(path))
                    worker.write_file = lambda name, data: write_file(path, data)
                    worker.auto_update = True
                    with patch('module.config.config.filepath_config', return_value=path):
                        runner.set_emotion(81)
                        tracker = tracker_class(worker)
                        tracker.check_reduce(1)
                        tracker.reduce(index)
                self.assertEqual(79, getattr(worker, f'Emotion_Fleet{index}Value'))
                self.assertEqual(stamp, getattr(worker, f'Emotion_Fleet{index}Record'))
                self.assertEqual(stamp.isoformat(timespec='microseconds'),
                                 getattr(worker, f'Emotion_Fleet{index}RecoveryState')['record'])

    def fixture(self):
        state = EmotionRecoveryState.calibrate(100, BASE, 'dormitory_floor_2', True, False)
        fields = {'Mode': 'calculate'}
        for i in (1, 2):
            fields.update({f'Fleet{i}Value': 100, f'Fleet{i}Record': BASE,
                           f'Fleet{i}Recover': state.recover, f'Fleet{i}Oath': True, f'Fleet{i}Onsen': False,
                           f'Fleet{i}RecoveryState': state.export()})
        task = {'Emotion': fields, 'Campaign': {'Mode': 'normal'},
                'Fleet': {'Fleet1': 3, 'Fleet2': 4, 'FleetOrder': 'fleet1_all_fleet2_standby'}}
        data = {'Main': task, 'General': {'PublicEmotion': {'Enable': False, 'Tasks': 'Main, Event'}}}
        config = SimpleNamespace(data=data, modified={})
        known = {f'ship{i}' for i in range(6)}
        result = {category: {'3': [{'name': f'ship{i}', 'level': 125, 'emotion': 106}
                                  for i in indices]} for category, indices in [('vanguard', range(3)), ('main', range(3, 6))]}
        windows = {'vanguard': (BASE + timedelta(seconds=60), BASE + timedelta(seconds=60)),
                   'main': (BASE + timedelta(seconds=61), BASE + timedelta(seconds=61))}
        return config, result, windows, known

    def test_physical_fleet_mapping_does_not_assume_logical_number(self):
        config, result, windows, known = self.fixture()
        self.assertEqual(1, learn_fleet_emotion(config, result, windows, known))
        self.assertEqual({'Main.Emotion.Fleet1Value', 'Main.Emotion.Fleet1Record',
                          'Main.Emotion.Fleet1RecoveryState'}, set(config.modified))
        self.assertEqual(106, config.modified['Main.Emotion.Fleet1Value'])

    def test_incomplete_unknown_names_duplicates_bad_time_and_hard_skip(self):
        for kind in ('partial', 'null', 'name', 'duplicate', 'time', 'hard', 'onsen', 'legacy'):
            config, result, windows, known = self.fixture()
            if kind == 'partial':
                result['main']['3'].pop()
            elif kind == 'null':
                result['main']['3'][0]['emotion'] = None
            elif kind == 'name':
                result['main']['3'][0]['name'] = 'unconfirmed'
            elif kind == 'duplicate':
                result['main']['3'][0]['name'] = 'ship0'
            elif kind == 'time':
                windows['main'] = None
            elif kind == 'hard':
                config.data['Main']['Campaign']['Mode'] = 'hard'
            elif kind == 'onsen':
                config.data['Main']['Emotion']['Fleet1Onsen'] = True
            else:
                config.data['Main']['Emotion']['Fleet1RecoveryState'] = None
            self.assertEqual(0, learn_fleet_emotion(config, result, windows, known), kind)
            self.assertEqual({}, config.modified)

    def test_shared_tasks_must_use_one_identical_physical_fleet(self):
        for scenario in ('same', 'different', 'dual', 'unknown'):
            config, result, windows, known = self.fixture()
            config.data['Event'] = copy.deepcopy(config.data['Main'])
            fields = config.data['Main']['Emotion']
            shared = config.data['General']['PublicEmotion']
            shared.update({key.replace('Fleet1', 'Fleet'): value for key, value in fields.items() if key.startswith('Fleet1')})
            shared['Enable'] = True
            if scenario == 'different':
                config.data['Event']['Fleet']['Fleet1'] = 2
            elif scenario == 'dual':
                config.data['Event']['Fleet']['FleetOrder'] = 'fleet1_mob_fleet2_boss'
            elif scenario == 'unknown':
                shared['Tasks'] = 'Main, Missing'
            count = learn_fleet_emotion(config, result, windows, known)
            self.assertEqual(1 if scenario in ('same', 'unknown') else 0, count)
            self.assertEqual(scenario == 'same', 'General.PublicEmotion.FleetRecoveryState' in config.modified)

    def test_capture_window_uses_existing_matching_frame_only(self):
        image = object()
        device = SimpleNamespace(config=SimpleNamespace(Emulator_ScreenshotMethod='ADB', Error_SaveError=True), image=image)
        device.screenshot_deque = deque([{'time': BASE, 'image': object()},
                                        {'time': BASE + timedelta(milliseconds=100), 'image': image}])
        self.assertEqual((BASE, BASE + timedelta(milliseconds=100)), screenshot_window(device))
        for method in ('scrcpy', 'DroidCast', 'azurpilot_android', 'unknown'):
            device.config.Emulator_ScreenshotMethod = method
            self.assertIsNone(screenshot_window(device))
        device.config.Emulator_ScreenshotMethod = 'ADB'
        device.image = object()
        self.assertIsNone(screenshot_window(device))
        device.image = image
        device.screenshot_deque[-1]['time'] = BASE - timedelta(microseconds=1)
        self.assertIsNone(screenshot_window(device))

    def test_real_json_save_and_mapping_change_conflict(self):
        from module.api.config_service import ConfigService
        from module.config.utils import read_file, write_file
        from tests.test_api import fixture

        for conflict in (False, True):
            config, result, windows, known = self.fixture()
            with tempfile.TemporaryDirectory() as directory:
                service = ConfigService(fixture(directory))
                path = str(service.path('testpilot'))
                disk = service.read('testpilot')[0]
                disk['Main'].update(config.data['Main'])
                disk['General'].update(config.data['General'])
                write_file(path, disk)
                worker = AzurLaneConfig.__new__(AzurLaneConfig)
                worker.data = worker.config_update(copy.deepcopy(disk))
                worker._loaded_data = copy.deepcopy(worker.data)
                worker.config_name = 'testpilot'
                worker.bound, worker.modified, worker.overridden = {}, {}, {}
                worker.read_file = lambda name: worker.config_update(read_file(path))
                worker.write_file = lambda name, data: write_file(path, data)
                self.assertEqual(1, learn_fleet_emotion(worker, result, windows, known))
                if conflict:
                    disk['Main']['Fleet']['Fleet1'] = 2
                    write_file(path, disk)
                runner = FleetManagement.__new__(FleetManagement)
                runner.config = worker
                with patch('module.config.config.filepath_config', return_value=path):
                    runner._save_result(result)
                saved = json.loads(service.path('testpilot').read_text(encoding='utf-8'))
                self.assertEqual(100 if conflict else 106, saved['Main']['Emotion']['Fleet1Value'])
                self.assertEqual(result, saved['FleetInfo']['FleetInfo']['Result'])
                if not conflict:
                    fields = saved['Main']['Emotion']
                    restored = EmotionRecoveryState.restore(fields['Fleet1RecoveryState'], fields['Fleet1Value'],
                                                             datetime.fromisoformat(fields['Fleet1Record']),
                                                             fields['Fleet1Recover'], True, False)
                    self.assertEqual((106, 106), (restored.lower, restored.upper))


if __name__ == '__main__':
    unittest.main()
