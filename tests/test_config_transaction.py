"""验证配置事务在进程间互斥，并保留运行器之外的并发修改。"""
import json
import copy
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from module.config.transaction import config_transaction


def increment(path, count):
    for _ in range(count):
        with config_transaction(path):
            file = Path(path)
            data = json.loads(file.read_text())
            data['value'] += 1
            file.write_text(json.dumps(data))


class ConfigTransactionTests(unittest.TestCase):
    def test_exploration_clear_resets_own_checkpoint_and_preserves_purchase_record(self):
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from tests.test_api import fixture

        for mode in ('monthly', 'smart'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                service = ConfigService(fixture(directory))
                data = service.get('testpilot')['values']
                monthly = data['OpsiExplore']['OpsiExplore']
                monthly.update(ExploreProgress='已完成百分之100.00', LastZone=121,
                               MeowfficerCleanupState={'reset': '2026-11-01T00:00:00', 'phase': 'done'})
                scheduling = data['OpsiScheduling']
                scheduling['OpsiSmartExplore']['Progress'] = '已开荒 34/72，阶段：开荒'
                scheduling['Storage']['Storage'] = {'SmartExplore': {'next': [30, 7, 0]},
                                                     'ActionPointPurchase': {'phase': 'done'}, 'Unrelated': 12}
                service.path('testpilot').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                before = copy.deepcopy(data)
                path = ('OpsiExplore.OpsiExplore.ExploreProgress' if mode == 'monthly'
                        else 'OpsiScheduling.OpsiSmartExplore.Progress')
                result = service.patch('testpilot', None, [ConfigChange(path=path, value='')])['values']
                if mode == 'monthly':
                    expected = before['OpsiExplore']['OpsiExplore']
                    expected.update(ExploreProgress='', LastZone=0, MeowfficerCleanupState=None)
                else:
                    before['OpsiScheduling']['OpsiSmartExplore']['Progress'] = ''
                    before['OpsiScheduling']['Storage']['Storage'].pop('SmartExplore')
                self.assertEqual(result, before)

    def test_exploration_progress_only_allows_empty_text_and_clear_is_atomic(self):
        from module.api.config_service import ConfigService
        from module.api.protocol import ApiError, ConfigChange
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            for path in ('OpsiExplore.OpsiExplore.ExploreProgress', 'OpsiScheduling.OpsiSmartExplore.Progress'):
                for value in ('fake 100%', None, False, {}, []):
                    with self.subTest(path=path, value=value), self.assertRaises(ApiError):
                        service.patch('testpilot', None, [ConfigChange(path=path, value=value)])
            original = service.path('testpilot').read_bytes()
            with self.assertRaises(ApiError):
                service.patch('testpilot', None, [
                    ConfigChange(path='OpsiExplore.OpsiExplore.ExploreProgress', value=''),
                    ConfigChange(path='OpsiExplore.OpsiExplore.MeowfficerCleanupState', value=None),
                ])
            self.assertEqual(service.path('testpilot').read_bytes(), original)

    def test_stale_worker_cannot_undo_same_field_edit(self):
        from module.config.config import AzurLaneConfig
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from tests.test_api import fixture

        for reload_before_save in (False, True):
            with self.subTest(reload_before_save=reload_before_save), tempfile.TemporaryDirectory() as directory:
                service = ConfigService(fixture(directory))
                worker = AzurLaneConfig.__new__(AzurLaneConfig)
                worker.config_name = 'testpilot'
                path = str(service.path('testpilot'))
                with patch('module.config.config.filepath_config', return_value=path), patch(
                    'module.config.config_updater.filepath_config', return_value=path
                ), patch.object(AzurLaneConfig, 'config_override'):
                    worker.data = worker.read_file('testpilot')
                    worker._loaded_data = copy.deepcopy(worker.data)
                    worker.modified = {'Alas.Emulator.Serial': 'stale-worker', 'Main.Scheduler.Enable': True}
                    service.patch('testpilot', None, [ConfigChange(path='Alas.Emulator.Serial', value='user-edit')])
                    if reload_before_save:
                        worker.load()
                    worker.save()
                saved = service.get('testpilot')['values']
                self.assertEqual('user-edit', saved['Alas']['Emulator']['Serial'])
                self.assertTrue(saved['Main']['Scheduler']['Enable'])

    def test_stale_worker_save_preserves_frontend_edit(self):
        from module.config.config import AzurLaneConfig
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            original = service.get('testpilot')
            worker = AzurLaneConfig.__new__(AzurLaneConfig)
            worker.config_name = 'testpilot'
            worker.data = original['values']
            worker.modified = {'Main.Scheduler.Enable': True}
            pending = worker.modified
            service.patch('testpilot', original['revision'], [
                ConfigChange(path='Alas.Emulator.Serial', value='frontend-edit'),
            ])
            path = str(service.path('testpilot'))
            with patch('module.config.config.filepath_config', return_value=path), patch(
                'module.config.config_updater.filepath_config', return_value=path
            ):
                worker.save()
            saved = service.get('testpilot')['values']
            self.assertEqual('frontend-edit', saved['Alas']['Emulator']['Serial'])
            self.assertTrue(saved['Main']['Scheduler']['Enable'])
            self.assertIs(pending, worker.modified)
            self.assertEqual({}, pending)

    def test_processes_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'instance.json'
            path.write_text('{"value": 0}')
            context = multiprocessing.get_context('spawn')
            processes = [context.Process(target=increment, args=(str(path), 30)) for _ in range(3)]
            try:
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(timeout=15)
                    self.assertEqual(0, process.exitcode)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=3)
            self.assertEqual(90, json.loads(path.read_text())['value'])

    def test_nested_same_thread_lock_is_reentrant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'instance.json'
            with config_transaction(path), config_transaction(path):
                path.write_text('{}')
            self.assertEqual('{}', path.read_text())


    def test_emotion_edit_refreshes_record_time(self):
        """改写情绪值同时重置时间戳，否则 update() 会把旧时间戳后的恢复量重复计入。"""
        from datetime import datetime

        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            service.patch('testpilot', None, [
                ConfigChange(path='Main.Emotion.Fleet1Value', value=85),
            ])
            emotion = service.get('testpilot')['values']['Main']['Emotion']
            self.assertEqual(85, emotion['Fleet1Value'])
            elapsed = datetime.now() - datetime.fromisoformat(emotion['Fleet1Record'])
            self.assertLess(elapsed.total_seconds(), 30,
                            f"Fleet1Record 未随 Fleet1Value 刷新：{emotion['Fleet1Record']}")

    def test_emotion_edit_does_not_reapply_recovery(self):
        """改写情绪值后按新时间戳计算恢复量，不再把改值之前的恢复量重复计入。

        Record 是只读字段，用户只能改 Value，因此这里直接写文件模拟运行器数小时前
        写入的时间戳。
        """
        import json

        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from module.combat.emotion import FleetEmotion
        from module.exception import RequestHumanTakeover
        from module.config.config import AzurLaneConfig
        from tests.test_api import fixture

        def build(path):
            config = AzurLaneConfig.__new__(AzurLaneConfig)
            config.config_name = 'testpilot'
            config.modified = {}
            config.bound = {}
            config.overridden = {}
            config.auto_update = False
            config.root = path.parent.parent
            config.data = config.config_update(json.loads(path.read_text(encoding='utf-8')))
            config.bind('Main')
            return config

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            path = service.path('testpilot')
            data = json.loads(path.read_text(encoding='utf-8'))
            data['Main']['Emotion']['Fleet1Value'] = 85
            data['Main']['Emotion']['Fleet1Record'] = '2020-01-01 00:00:00'
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            stale = FleetEmotion(build(path), '1')
            with self.assertRaises(RequestHumanTakeover):
                stale.update()

            service.patch('testpilot', None, [
                ConfigChange(path='Main.Emotion.Fleet1Value', value=85),
            ])
            refreshed = FleetEmotion(build(path), '1')
            refreshed.current = 85
            refreshed.update()
            self.assertLessEqual(refreshed.current - 85, 1,
                                 f'改值后仍重复计入恢复量，current={refreshed.current}')

    def test_emotion_calibration_uses_final_settings_and_invalidates_after_change(self):
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange, ApiError
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            changes = [ConfigChange(path='Main.Emotion.Fleet1Value', value=85),
                       ConfigChange(path='Main.Emotion.Fleet1Oath', value=True),
                       ConfigChange(path='Main.Emotion.Fleet1Recover', value='dormitory_floor_2')]
            fields = service.patch('testpilot', None, changes)['values']['Main']['Emotion']
            self.assertEqual(['dormitory_floor_2', True, False], fields['Fleet1RecoveryState']['signature'])
            self.assertEqual([[0, 360_000_000, 85]], fields['Fleet1RecoveryState']['segments'])
            service.patch('testpilot', None, [ConfigChange(path='Main.Emotion.Fleet1Oath', value=False)])
            self.assertIsNone(service.read('testpilot')[0]['Main']['Emotion']['Fleet1RecoveryState'])
            for value in (-1, 151, True, 85.5):
                with self.subTest(value=value), self.assertRaises(ApiError):
                    service.patch('testpilot', None, [ConfigChange(path='Main.Emotion.Fleet1Value', value=value)])
            with self.assertRaises(ApiError):
                service.patch('testpilot', None, [ConfigChange(path='Main.Emotion.Fleet1RecoveryState', value={})])

    def test_same_value_calibration_cannot_be_overwritten_by_stale_worker(self):
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from module.config.config import AzurLaneConfig
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            worker = AzurLaneConfig.__new__(AzurLaneConfig)
            worker.config_name = 'testpilot'
            path = str(service.path('testpilot'))
            with patch('module.config.config.filepath_config', return_value=path), patch(
                'module.config.config_updater.filepath_config', return_value=path
            ), patch.object(AzurLaneConfig, 'config_override'):
                worker.data = worker.config_update(service.read('testpilot')[0])
                worker._loaded_data = copy.deepcopy(worker.data)
                worker.modified, worker.bound, worker.overridden = {}, {}, {}
                worker.auto_update = False
                worker.bind('Main')
                original = worker.Emotion_Fleet1Value
                expected = service.patch('testpilot', None, [
                    ConfigChange(path='Main.Emotion.Fleet1Value', value=original)
                ])['values']['Main']['Emotion']
                worker.Emotion_Fleet1Value = original - 2
                worker.Emotion_Fleet1Record = worker.Emotion_Fleet1Record
                worker.Emotion_Fleet1RecoveryState = None
                worker.save()
                self.assertEqual(expected, service.read('testpilot')[0]['Main']['Emotion'])

    def test_public_emotion_calibration_is_atomic_and_same_value_can_recalibrate(self):
        from datetime import datetime, timedelta
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            now = datetime(2026, 10, 9, microsecond=123456)
            with patch('module.api.config_service.current_time', return_value=now):
                fields = service.patch('testpilot', None, [
                    ConfigChange(path='General.PublicEmotion.FleetValue', value=85),
                    ConfigChange(path='General.PublicEmotion.FleetRecover', value='dormitory_floor_1'),
                    ConfigChange(path='General.PublicEmotion.FleetOath', value=True),
                ])['values']['General']['PublicEmotion']
            self.assertEqual(['dormitory_floor_1', True, False], fields['FleetRecoveryState']['signature'])
            self.assertEqual(now, datetime.fromisoformat(fields['FleetRecord']))
            self.assertEqual(now, datetime.fromisoformat(fields['FleetRecoveryState']['record']))
            now += timedelta(microseconds=1)
            with patch('module.api.config_service.current_time', return_value=now):
                fields = service.patch('testpilot', None, [
                    ConfigChange(path='General.PublicEmotion.FleetValue', value=85)
                ])['values']['General']['PublicEmotion']
            self.assertEqual(now, datetime.fromisoformat(fields['FleetRecord']))
            self.assertEqual([[0, 360_000_000, 85]], fields['FleetRecoveryState']['segments'])

if __name__ == '__main__':
    unittest.main()
