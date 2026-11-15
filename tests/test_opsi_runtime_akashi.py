"""验证明石异步统计确实落库，提交失败不输出成功次数。"""

import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.statistics import cl1_database as database
from module.statistics import opsi_runtime
from tests.opsi_test_support import install_store
from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming


class TestAkashiAsyncPersistence(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        install_store(self, self.directory.name)
        self.db = database.Cl1Database(db_path=Path(self.directory.name) / 'config' / 'cl1_data.db')
        self.config = SimpleNamespace(config_name='test')

    @staticmethod
    def wait_completed(future):
        callbacks_finished = threading.Event()
        future.add_done_callback(lambda _: callbacks_finished.set())
        future.result(timeout=10)
        if not callbacks_finished.wait(timeout=10):
            raise AssertionError('统计完成回调没有执行')

    def test_game_thread_does_not_wait_for_pending_database_write(self):
        pending = Future()
        db = Mock()
        db.async_increment_akashi_encounter.return_value = pending
        with patch.object(database, 'db', db), patch.object(opsi_runtime.logger, 'attr') as log:
            self.assertIs(opsi_runtime.record_cl1_akashi_encounter(self.config), pending)
            log.assert_not_called()
            db.async_get_stats.assert_not_called()
            pending.set_result(1)
            log.assert_called_once_with('侵蚀1明石月度次数', 1)

    def test_every_encounter_is_committed_and_logs_real_count(self):
        with patch.object(database, 'db', self.db), patch.object(opsi_runtime.logger, 'attr') as log:
            futures = [opsi_runtime.record_cl1_akashi_encounter(self.config) for _ in range(30)]
            for future in futures:
                self.wait_completed(future)
            month = opsi_runtime.datetime.now().strftime('%Y-%m')
            self.assertEqual(self.db.get_stats('test', month)['akashi_encounters'], 30)
            self.assertEqual([call.args[1] for call in log.call_args_list], list(range(1, 31)))

    def test_failed_transaction_never_logs_success_or_changes_count(self):
        callbacks_finished = threading.Event()
        with (
            patch.object(database, 'db', self.db),
            patch.object(self.db, '_save_stats_in_connection', side_effect=RuntimeError('写入失败')),
            patch.object(self.db, '_increment_month_scalar', side_effect=RuntimeError('写入失败')),
            patch.object(opsi_runtime.logger, 'attr') as log,
            patch.object(opsi_runtime.logger, 'exception') as failure,
        ):
            future = opsi_runtime.record_cl1_akashi_encounter(self.config)
            future.add_done_callback(lambda _: callbacks_finished.set())
            with self.assertRaisesRegex(RuntimeError, '写入失败'):
                future.result(timeout=10)
            self.assertTrue(callbacks_finished.wait(timeout=10))
            log.assert_not_called()
            failure.assert_called_once()
        month = opsi_runtime.datetime.now().strftime('%Y-%m')
        self.assertEqual(self.db.get_stats('test', month)['akashi_encounters'], 0)

    def test_explicit_event_month_is_kept_when_background_worker_crosses_month(self):
        self.assertEqual(self.db.increment_akashi_encounter('test', '2026-09'), 1)
        self.assertEqual(self.db.get_stats('test', '2026-09')['akashi_encounters'], 1)
        self.assertEqual(self.db.get_stats('test', '2026-10')['akashi_encounters'], 0)

    def make_meow(self, hazard_level=5):
        return SimpleNamespace(config=self.config, zone=SimpleNamespace(hazard_level=hazard_level))

    def test_meow_game_thread_does_not_wait_or_log_before_commit(self):
        pending = Future()
        db = Mock()
        db.async_increment_meow_akashi_encounter.return_value = pending
        with patch.object(database, 'db', db), patch.object(opsi_runtime.logger, 'attr') as log:
            self.assertIs(opsi_runtime.record_meow_akashi_encounter(self.make_meow()), pending)
            log.assert_not_called()
            db.async_get_meow_stats.assert_not_called()
            month = opsi_runtime.datetime.now().strftime('%Y-%m')
            db.async_increment_meow_akashi_encounter.assert_called_once_with('test', 5, month)
            pending.set_result(3)
            log.assert_called_once_with('耄耋相接明石月度次数', '侵蚀5: 3')

    def test_meow_counts_are_committed_separately_for_each_hazard_level(self):
        with patch.object(database, 'db', self.db), patch.object(opsi_runtime.logger, 'attr') as log:
            for hazard_level in (2, 5):
                futures = [opsi_runtime.record_meow_akashi_encounter(self.make_meow(hazard_level)) for _ in range(30)]
                for future in futures:
                    self.wait_completed(future)
            month = opsi_runtime.datetime.now().strftime('%Y-%m')
            stats = self.db.get_stats('test', month)
            self.assertEqual(stats['meow_hazard_stats']['2']['akashi_encounters'], 30)
            self.assertEqual(stats['meow_hazard_stats']['5']['akashi_encounters'], 30)
            self.assertEqual(stats['akashi_encounters'], 0)
            expected = [f'侵蚀{hazard}: {count}' for hazard in (2, 5) for count in range(1, 31)]
            self.assertEqual([call.args[1] for call in log.call_args_list], expected)

    def test_failed_meow_transaction_never_logs_success_or_changes_count(self):
        callbacks_finished = threading.Event()
        with (
            patch.object(database, 'db', self.db),
            patch.object(self.db, '_save_stats_in_connection', side_effect=RuntimeError('写入失败')),
            patch.object(self.db, '_increment_meow_counter_field', side_effect=RuntimeError('写入失败')),
            patch.object(opsi_runtime.logger, 'attr') as log,
            patch.object(opsi_runtime.logger, 'exception') as failure,
        ):
            future = opsi_runtime.record_meow_akashi_encounter(self.make_meow())
            future.add_done_callback(lambda _: callbacks_finished.set())
            with self.assertRaisesRegex(RuntimeError, '写入失败'):
                future.result(timeout=10)
            self.assertTrue(callbacks_finished.wait(timeout=10))
            log.assert_not_called()
            failure.assert_called_once()
        month = opsi_runtime.datetime.now().strftime('%Y-%m')
        self.assertNotIn('5', self.db.get_stats('test', month).get('meow_hazard_stats', {}))

    def test_meow_month_is_captured_before_async_submission(self):
        pending = Future()
        db = Mock()
        db.async_increment_meow_akashi_encounter.return_value = pending
        event_time = Mock()
        event_time.now.return_value.strftime.return_value = '2026-09'
        with patch.object(database, 'db', db), patch.object(opsi_runtime, 'datetime', event_time):
            opsi_runtime.record_meow_akashi_encounter(self.make_meow())
        db.async_increment_meow_akashi_encounter.assert_called_once_with('test', 5, '2026-09')
        self.assertEqual(self.db.increment_meow_akashi_encounter('test', 5, '2026-09'), 1)
        stats = self.db.get_stats('test', '2026-09')['meow_hazard_stats']
        self.assertEqual(stats['5']['akashi_encounters'], 1)
        self.assertNotIn('5', self.db.get_stats('test', '2026-10').get('meow_hazard_stats', {}))

    def test_invalid_meow_hazard_does_not_submit_or_log_success(self):
        with patch.object(database, 'db', Mock()) as db, patch.object(opsi_runtime.logger, 'attr') as log:
            self.assertIsNone(opsi_runtime.record_meow_akashi_encounter(self.make_meow(1)))
            db.async_increment_meow_akashi_encounter.assert_not_called()
            log.assert_not_called()
        self.assertIsNone(self.db.increment_meow_akashi_encounter('test', 1))

    def test_meow_solved_akashi_marker_is_consumed_once_across_rounds(self):
        main = OpsiMeowfficerFarming.__new__(OpsiMeowfficerFarming)
        main._solved_map_event = {'is_akashi'}
        with patch.object(opsi_runtime, 'record_meow_akashi_encounter') as record:
            main._meow_record_akashi_if_solved()
            main._meow_record_akashi_if_solved()
        record.assert_called_once_with(main)
        self.assertNotIn('is_akashi', main._solved_map_event)


if __name__ == '__main__':
    unittest.main()
