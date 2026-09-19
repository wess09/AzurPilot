"""委托结算只操作临时 SQLite，验证提交、回滚、跨月及通知边界。"""

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from module.statistics import cl1_database as database


NOW = datetime(2026, 1, 1, 12)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def commission(name="Gem", create_time="2025-12-31T22:00:00", finish_time="2026-01-01T06:00:00", duration=8):
    return {"name": name, "create_time": create_time, "finish_time": finish_time, "duration": duration}


class TestCommissionSettlement(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        with patch.object(database.Cl1Database, "_get_legacy_decryption_keys", return_value=[]):
            self.db = database.Cl1Database(Path(self.directory.name) / "stats.db")
        fixed = patch.object(database, "datetime", FixedDatetime)
        fixed.start()
        self.addCleanup(fixed.stop)

    def seed(self, month, commissions, **values):
        data = {"running_gem_commissions": commissions, "battle_count": 123, **values}
        self.db.save_stats("test", month, data)

    def rows(self):
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            return conn.execute("SELECT month, data_json, encrypted_blob FROM cl1_data ORDER BY month").fetchall()

    def fail_current_month(self):
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            conn.execute("""
                CREATE TRIGGER reject_archive BEFORE INSERT ON cl1_data
                WHEN NEW.month = '2026-01'
                BEGIN SELECT RAISE(ABORT, 'archive rejected'); END
            """)

    def test_current_month_settlement_keeps_format_and_other_statistics(self):
        entry = commission()
        self.seed("2026-01", [entry])
        self.assertEqual(self.db.settle_gem_commission("test", 60, name="Gem", duration_hour=8), entry)
        stats = self.db.get_stats("test", "2026-01")
        self.assertEqual(stats["running_gem_commissions"], [])
        self.assertEqual(stats["battle_count"], 123)
        self.assertEqual(stats["gem_commission_entries"], [{
            "ts": NOW.isoformat(), "duration": 8, "reward": 60, "success": True,
        }])

    def test_cross_year_settlement_removes_previous_month_and_archives_current_month(self):
        entry = commission()
        self.seed("2025-12", [entry], other={"keep": True})
        self.seed("2026-01", [], commission_income_entries=[])
        self.assertEqual(self.db.settle_gem_commission("test", 50, name="Gem", create_time=entry["create_time"]), entry)
        previous = self.db.get_stats("test", "2025-12")
        current = self.db.get_stats("test", "2026-01")
        self.assertEqual(previous["running_gem_commissions"], [])
        self.assertEqual(previous["other"], {"keep": True})
        self.assertNotIn("gem_commission_entries", previous)
        self.assertEqual(current["gem_commission_entries"][0]["reward"], 50)

    def test_current_month_priority_and_exact_creation_time_are_preserved(self):
        old = commission(create_time="2025-12-30T22:00:00")
        new = commission(create_time="2026-01-01T00:00:00")
        self.seed("2025-12", [old])
        self.seed("2026-01", [new])
        self.assertEqual(self.db.settle_gem_commission("test", 60, name="Gem", duration_hour=8), new)
        self.assertEqual(self.db.get_stats("test", "2025-12")["running_gem_commissions"], [old])
        self.assertIsNone(self.db.settle_gem_commission("test", 60, name="Gem", create_time=new["create_time"]))
        self.assertEqual(self.db.settle_gem_commission("test", 60, name="Gem", create_time=old["create_time"]), old)

    def test_archive_write_failure_rolls_back_previous_month_removal(self):
        self.seed("2025-12", [commission()])
        before = self.rows()
        self.fail_current_month()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.settle_gem_commission("test", 60, name="Gem", duration_hour=8)
        self.assertEqual(self.rows(), before)

    def test_income_and_gem_settlement_commit_together(self):
        entry = commission()
        self.seed("2025-12", [entry])
        result = self.db.add_commission_income(
            "test", {"Gem": 60, "Cube": 2}, screenshots=["test/2026-01/reward.png"],
            gem_duration=8, completed_at=NOW,
        )
        self.assertEqual(result, entry)
        current = self.db.get_stats("test", "2026-01")
        self.assertEqual(current["commission_income_entries"], [{
            "ts": NOW.isoformat(), "items": {"Gem": 60, "Cube": 2},
            "commission_count": 1, "screenshots": ["test/2026-01/reward.png"],
        }])
        self.assertEqual(current["gem_commission_entries"][0]["reward"], 60)

    def test_income_failure_rolls_back_both_months(self):
        self.seed("2025-12", [commission()])
        self.seed("2026-01", [], commission_income_entries=[{"existing": True}])
        before = self.rows()
        self.fail_current_month()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_commission_income("test", {"Gem": 60}, gem_duration=8, completed_at=NOW)
        self.assertEqual(self.rows(), before)

    def test_sqlite_commit_failure_rolls_back_and_propagates(self):
        self.seed("2025-12", [commission()])
        before = self.rows()
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE guard_parent (id INTEGER PRIMARY KEY);
                CREATE TABLE guard_child (
                    parent_id INTEGER REFERENCES guard_parent(id) DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER fail_commit BEFORE INSERT ON cl1_data
                WHEN NEW.month = '2026-01'
                BEGIN INSERT INTO guard_child VALUES (1); END;
            """)
        connect = sqlite3.connect

        def checked_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            conn.execute("PRAGMA foreign_keys=ON")
            return conn

        with patch.object(database.sqlite3, "connect", side_effect=checked_connect):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.add_commission_income("test", {"Gem": 60}, gem_duration=8, completed_at=NOW)
        self.assertEqual(self.rows(), before)

    def test_reward_matching_chooses_earliest_finished_duration(self):
        latest = commission("latest", finish_time="2026-01-01T11:00:00")
        earliest = commission("earliest", finish_time="2026-01-01T06:00:00")
        future = commission("future", finish_time="2026-01-01T13:00:00")
        other = commission("other", duration=2, finish_time="2026-01-01T01:00:00")
        self.seed("2026-01", [latest, future, other, earliest])
        matched = self.db.add_commission_income("test", {"Gem": 60}, gem_duration=8, completed_at=NOW)
        self.assertEqual(matched, earliest)
        self.assertCountEqual(self.db.get_stats("test", "2026-01")["running_gem_commissions"], [latest, future, other])

    def test_unmatched_income_is_saved_without_inventing_gem_settlement(self):
        self.seed("2026-01", [commission(duration=2)])
        self.assertIsNone(self.db.add_commission_income("test", {"Gem": 60}, gem_duration=8, completed_at=NOW))
        stats = self.db.get_stats("test", "2026-01")
        self.assertEqual(len(stats["commission_income_entries"]), 1)
        self.assertNotIn("gem_commission_entries", stats)
        self.assertEqual(len(stats["running_gem_commissions"]), 1)

    def test_expired_batch_settles_only_due_valid_records_across_months(self):
        old = commission("old")
        due = commission("due", duration=2)
        future = commission("future", finish_time="2026-01-02T00:00:00")
        malformed = commission("malformed", finish_time="invalid")
        self.seed("2025-12", [old])
        self.seed("2026-01", [due, future, malformed])
        self.assertEqual(self.db.settle_expired_gem_commissions("test", now=NOW), 2)
        stats = self.db.get_stats("test", "2026-01")
        self.assertCountEqual(stats["running_gem_commissions"], [future, malformed])
        self.assertEqual([entry["reward"] for entry in stats["gem_commission_entries"]], [0, 0])
        self.assertEqual(self.db.settle_expired_gem_commissions("test", now=NOW), 0)

    def test_expired_batch_rolls_back_all_removals_when_archive_fails(self):
        self.seed("2025-12", [commission("old")])
        self.seed("2026-01", [commission("new")])
        before = self.rows()
        self.fail_current_month()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.settle_expired_gem_commissions("test", now=NOW)
        self.assertEqual(self.rows(), before)

    def test_concurrent_settlement_archives_running_record_once(self):
        self.seed("2025-12", [commission()])
        barrier = threading.Barrier(2)

        def settle():
            barrier.wait(timeout=3)
            return self.db.settle_gem_commission("test", 60, name="Gem", duration_hour=8)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: settle(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.db.get_stats("test", "2026-01")["gem_commission_entries"]), 1)

    def test_corrupt_data_is_not_overwritten_by_settlement(self):
        self.seed("2025-12", [commission()])
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            conn.execute("UPDATE cl1_data SET data_json='broken'")
        before = self.rows()
        with self.assertRaises(ValueError):
            self.db.settle_gem_commission("test", 60)
        self.assertEqual(self.rows(), before)

    def test_save_stats_reports_real_sqlite_write_failure(self):
        self.fail_current_month()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.save_stats("test", "2026-01", {"battle_count": 1})
        self.assertEqual(self.rows(), [])

    def test_async_save_failure_is_available_on_future(self):
        self.fail_current_month()
        future = self.db.async_save_stats("test", "2026-01", {"battle_count": 1})
        with self.assertRaises(sqlite3.IntegrityError):
            future.result(timeout=3)
        self.assertEqual(self.rows(), [])

    def test_failed_optional_legacy_migration_still_returns_decoded_data(self):
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            conn.execute("INSERT INTO cl1_data VALUES (?, ?, NULL, ?)", ("test", "2025-12", b"legacy"))
        decoded = {"battle_count": 12}
        with patch.object(self.db, "_decrypt", return_value=decoded), \
                patch.object(self.db, "save_stats", side_effect=sqlite3.OperationalError("readonly")):
            self.assertEqual(self.db.get_stats("test", "2025-12"), decoded)


class TestCommissionIncomeBoundary(unittest.TestCase):
    def setUp(self):
        from module.commission.commission import RewardCommission

        self.reward_class = RewardCommission
        self.handler = SimpleNamespace(
            config=SimpleNamespace(config_name="test"),
            _recognize_commission_income=Mock(return_value=({"Gem": 60}, ["image"])),
            _persist_commission_income=Mock(),
            _notify_commission_income=Mock(),
        )

    def test_persistence_failure_does_not_send_success_notification(self):
        self.handler._persist_commission_income.side_effect = sqlite3.OperationalError("readonly")
        self.assertFalse(self.reward_class._record_commission_income(self.handler))
        self.handler._notify_commission_income.assert_not_called()

    def test_notification_failure_does_not_repeat_or_reject_saved_income(self):
        self.handler._notify_commission_income.side_effect = RuntimeError("通知失败")
        self.assertTrue(self.reward_class._record_commission_income(self.handler))
        self.handler._persist_commission_income.assert_called_once_with({"Gem": 60}, ["image"])

    def test_empty_reward_batch_is_successful_noop(self):
        self.handler._commission_reward_images = []
        self.handler._recognize_commission_income = MethodType(self.reward_class._recognize_commission_income, self.handler)
        self.assertTrue(self.reward_class._record_commission_income(self.handler))
        self.handler._persist_commission_income.assert_not_called()

    def test_earlier_failed_reward_batch_blocks_final_expired_settlement(self):
        from module.commission import commission as module

        handler = MagicMock()
        handler.config = SimpleNamespace(
            config_name="test", DropRecord_CommissionRecord="do_not", SERVER="en",
            Commission_DetectShipDrop=False,
        )
        handler.stat.new.return_value.__enter__.return_value = None
        handler._record_commission_income.side_effect = [False, True]
        handler.ui_main_appear_then_click.return_value = False
        frame = -1

        def is_commission_page(*_, **__):
            nonlocal frame
            frame += 1
            return frame == 3

        def appear(button, **_):
            return button is [module.GET_ITEMS_1, module.EXP_INFO_S_REWARD, module.GET_ITEMS_1][frame]

        handler.ui_page_appear.side_effect = is_commission_page
        handler.appear.side_effect = appear
        timer = Mock()
        timer.reached.return_value = False
        with patch.object(module, "Timer", return_value=timer), patch.object(database, "db") as db:
            self.assertTrue(self.reward_class._commission_receive(handler))
        self.assertEqual(handler._record_commission_income.call_count, 2)
        db.settle_expired_gem_commissions.assert_not_called()
