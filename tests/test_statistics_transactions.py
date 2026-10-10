"""用临时 SQLite 验证统计写者、委托及旧数据迁移的事务边界。"""

import json
import multiprocessing
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from Crypto.Cipher import AES

from module.statistics import cl1_database as database
from module.persistence import database as persistence


NOW = datetime(2026, 1, 1, 12)
MONTH = "2026-01"
ENTRY = {
    "name": "Gem", "duration": 8,
    "create_time": "2025-12-31T22:00:00", "finish_time": "2026-01-01T06:00:00",
}
MUTATIONS = [
    ("add_siren_research_device", ()),
    ("increment_battle_count", ()),
    ("increment_akashi_encounter", ()),
    ("add_akashi_ap_entry", (20, 10, 2, "cl1")),
    ("add_ap_snapshot", (100,)),
    ("set_last_ap_notification", (100,)),
    ("add_yellow_coin_snapshot", (500,)),
    ("add_coins_snapshot", (500, 20)),
    ("increment_meow_battle_count", (3,)),
    ("add_meow_round_time", (60, 3)),
    ("add_meow_battle_time", (20, 3)),
    ("increment_meow_akashi_encounter", (3,)),
    ("add_meow_akashi_ap", (3, 20)),
    ("add_gem_commission", (8, 60)),
    ("save_running_gem_commissions", ([],)),
    ("add_running_gem_commission", ({**ENTRY, "name": "new"},)),
    ("pop_running_gem_commission", ("Gem", 8, ENTRY["create_time"])),
    ("backfill_meow_stats", (2026, 1)),
]


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def process_writer(path, started, finished):
    """子进程只连接测试库，写入与父进程不同的指标。"""
    db = database.Cl1Database(Path(path))
    root = Path(path).parent.parent
    if not root.is_relative_to(Path(tempfile.gettempdir())):
        raise RuntimeError('测试目录未隔离')
    started.set()
    connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(lambda sql: started.set() if sql == "BEGIN IMMEDIATE" else None)
        return conn

    with patch.object(persistence.sqlite3, "connect", side_effect=traced_connect), \
            patch.object(database, "datetime", FixedDatetime):
        db.add_coins_snapshot("test", 800, 50)
        db.add_commission_income("test", {"Cube": 2})
    finished.set()


class TestStatisticsTransactions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config" / "azurpilot.db"
        with nullcontext():
            self.db = database.Cl1Database(self.path)
            self.other = database.Cl1Database(self.path)
        fixed = patch.object(database, "datetime", FixedDatetime)
        fixed.start()
        self.addCleanup(fixed.stop)
        self.seed()

    def seed(self):
        self.db.save_stats("test", MONTH, {
            "battle_count": 10,
            "meow_battle_count": 2,
            "meow_round_times": [{"duration": 60, "hazard_level": 3}],
            "running_gem_commissions": [ENTRY],
            "commission_income_entries": [{"existing": True}],
            "unknown_field": {"keep": True},
        })

    def rows(self):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute("SELECT * FROM cl1_months ORDER BY instance, month").fetchall()

    def assert_serialized(self, first, second, pause_target="_get_stats_in_connection", owner=None):
        """第一写者读完后暂停，确认第二写者等待同一写锁。"""
        read_done = threading.Event()
        release = threading.Event()
        competing_begin = threading.Event()
        original = getattr(owner or self.db, pause_target)
        connect = sqlite3.connect

        def paused(*args, **kwargs):
            result = original(*args, **kwargs)
            if not read_done.is_set():
                read_done.set()
                if not release.wait(5):
                    raise TimeoutError("未放行第一个统计写者")
            return result

        def traced_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            if threading.current_thread().name.startswith("stats-other"):
                conn.set_trace_callback(
                    lambda sql: competing_begin.set() if sql == "BEGIN IMMEDIATE" else None
                )
            return conn

        with patch.object(owner or self.db, pause_target, side_effect=paused), \
                patch.object(persistence.sqlite3, "connect", side_effect=traced_connect), \
                ThreadPoolExecutor(max_workers=1) as first_pool, \
                ThreadPoolExecutor(max_workers=1, thread_name_prefix="stats-other") as second_pool:
            first_future = first_pool.submit(first)
            try:
                self.assertTrue(read_done.wait(5), "第一个写者未在事务中读取")
                with closing(connect(self.path, timeout=0)) as probe:
                    with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                        probe.execute("BEGIN IMMEDIATE")
                def competing_writer():
                    competing_begin.set()
                    return second()
                second_future = second_pool.submit(competing_writer)
                self.assertTrue(competing_begin.wait(5), "第二个写者未进入协调入口")
                self.assertFalse(second_future.done(), "第二个写者绕过了读改写事务的锁")
            finally:
                release.set()
            first_result = first_future.result(timeout=5)
            second_result = second_future.result(timeout=5)
        return first_result, second_result

    def test_all_legacy_mutations_preserve_concurrent_commission_income(self):
        for name, args in MUTATIONS:
            with self.subTest(method=name):
                self.seed()
                self.assert_serialized(
                    lambda: getattr(self.db, name)("test", *args),
                    lambda: self.other.add_commission_income("test", {"Cube": 2}),
                )
                stats = self.db.get_stats("test", MONTH)
                self.assertEqual(stats["commission_income_entries"], [
                    {"existing": True},
                    {"ts": NOW.isoformat(), "items": {"Cube": 2}, "commission_count": 1, "screenshots": []},
                ])
                self.assertEqual(stats["unknown_field"], {"keep": True})

    def test_independent_process_waits_and_preserves_both_metrics(self):
        context = multiprocessing.get_context("spawn")
        started, finished = context.Event(), context.Event()
        process = context.Process(target=process_writer, args=(str(self.path), started, finished))
        with self.db._stats_transaction() as conn:
            data = self.db._get_stats_in_connection(conn, "test", MONTH)
            process.start()
            try:
                self.assertTrue(started.wait(10))
                self.assertFalse(finished.is_set())
                data["battle_count"] += 1
                self.db._save_stats_in_connection(conn, "test", MONTH, data)
            except BaseException:
                process.terminate()
                process.join(5)
                raise
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
            self.fail("子进程未在提交释放锁后结束")
        self.assertEqual(process.exitcode, 0)
        stats = self.db.get_stats("test", MONTH)
        self.assertEqual(stats["battle_count"], 11)
        self.assertEqual(stats["coins_snapshots"][0]["purple_coins"], 50)
        self.assertEqual(len(stats["commission_income_entries"]), 2)

    def test_concurrent_increments_and_snapshots_keep_both_fields(self):
        self.assert_serialized(
            lambda: self.db.increment_battle_count("test"),
            lambda: self.other.increment_akashi_encounter("test"),
        )
        self.assert_serialized(
            lambda: self.db.add_yellow_coin_snapshot("test", 900),
            lambda: self.other.add_ap_snapshot("test", 100),
        )
        stats = self.db.get_stats("test", MONTH)
        self.assertEqual(stats["battle_count"], 11)
        self.assertEqual(stats["akashi_encounters"], 1)
        self.assertEqual(stats["ap_snapshots"][0]["yellow_coin"], 900)

    def test_all_mutations_reject_corrupt_rows_without_replacing_them(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM typed_value_nodes WHERE parent_no IS NULL")
        before = self.rows()
        for name, args in MUTATIONS:
            with self.subTest(method=name), self.assertRaises(ValueError):
                getattr(self.db, name)("test", *args)
            self.assertEqual(self.rows(), before)

    def test_sqlite_read_error_propagates_without_empty_snapshot_write(self):
        before = self.rows()
        connect = sqlite3.connect

        def denied_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            conn.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ else sqlite3.SQLITE_OK)
            return conn

        with patch.object(persistence.sqlite3, "connect", side_effect=denied_connect):
            with self.assertRaises(sqlite3.DatabaseError):
                self.db.increment_battle_count("test")
        self.assertEqual(self.rows(), before)

    def test_all_mutations_roll_back_write_failures(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("""CREATE TRIGGER reject_write BEFORE INSERT ON cl1_months
                BEGIN SELECT RAISE(ABORT, 'write rejected'); END""")
        before = self.rows()
        for name, args in MUTATIONS:
            with self.subTest(method=name), self.assertRaises(sqlite3.IntegrityError):
                getattr(self.db, name)("test", *args)
            self.assertEqual(self.rows(), before)

    def test_commit_failure_rolls_back_and_releases_lock(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE child (id REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)")
            conn.execute("CREATE TRIGGER reject_commit BEFORE INSERT ON cl1_months BEGIN INSERT INTO child VALUES (1); END")
        before = self.rows()
        connect = sqlite3.connect

        def checked_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            conn.execute("PRAGMA foreign_keys = ON")
            return conn

        for name, args in MUTATIONS:
            with self.subTest(method=name), patch.object(persistence.sqlite3, "connect", side_effect=checked_connect):
                with self.assertRaises(sqlite3.IntegrityError):
                    getattr(self.db, name)("test", *args)
            self.assertEqual(self.rows(), before)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DROP TRIGGER reject_commit")
        self.other.increment_battle_count("test")
        self.assertEqual(self.db.get_stats("test", MONTH)["battle_count"], 11)

    def encrypted_seed(self):
        """在另一个临时配置目录中迁移旧 AES 整行，确认原件保留。"""
        data = self.db.get_stats('test', MONTH)
        key = b'x' * 32
        cipher = AES.new(key, AES.MODE_GCM)
        payload, tag = cipher.encrypt_and_digest(json.dumps(data).encode())
        legacy = self.path.parent.parent / 'legacy' / 'cl1_data.db'
        legacy.parent.mkdir()
        with closing(sqlite3.connect(legacy)) as conn, conn:
            conn.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT,encrypted_blob BLOB)')
            conn.execute('INSERT INTO cl1_data VALUES(?,?,NULL,?)', ('test', MONTH, cipher.nonce + tag + payload))
        original = legacy.read_bytes()
        self.enterContext(patch('module.statistics.cl1_legacy.derive_legacy_key', return_value=key))
        self.db = database.Cl1Database(legacy)
        self.other = database.Cl1Database(legacy)
        self.path = self.db.db_path
        self.assertEqual(self.db.get_stats('test', MONTH), data)
        self.assertEqual(legacy.read_bytes(), original)
        return data

    def test_read_migration_keeps_following_commission_commit(self):
        original = self.encrypted_seed()
        self.assertEqual(self.db.get_stats("test", MONTH), original)
        self.other.add_commission_income("test", {"Cube": 2})
        self.assertEqual(len(self.db.get_stats("test", MONTH)["commission_income_entries"]), 2)

    def test_failed_optional_read_migration_still_returns_decrypted_data(self):
        original = self.encrypted_seed()
        before = self.rows()
        with patch.object(database.Cl1Database, '_save_stats_in_connection',
                          side_effect=sqlite3.OperationalError('disk busy')):
            self.assertEqual(self.db.get_stats("test", MONTH), original)
        self.assertEqual(self.rows(), before)

    def test_json_migration_does_not_overwrite_new_commission_income(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM cl1_months")
        source = self.path.parent.parent / "log" / "cl1" / "test" / "cl1_monthly.json"
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps({MONTH: 42}), encoding='utf-8')
        self.assert_serialized(
            lambda: self.db.migrate_from_json(source, "test"),
            lambda: self.other.add_commission_income("test", {"Cube": 2}),
            pause_target="_empty_data",
        )
        stats = self.db.get_stats("test", MONTH)
        self.assertEqual(stats["battle_count"], 42)
        self.assertEqual(len(stats["commission_income_entries"]), 1)
        self.assertTrue(source.exists())
        self.assertEqual(json.loads(source.read_bytes())[MONTH], 42)

    def test_pop_previous_month_preserves_archive_month_and_exact_match(self):
        self.db.save_stats("test", "2025-12", {"running_gem_commissions": [ENTRY], "battle_count": 30})
        self.db.save_running_gem_commissions("test", [])
        self.assertEqual(self.db.pop_running_gem_commission("test", "Gem", 8, ENTRY["create_time"]), ENTRY)
        self.assertEqual(self.db.get_stats("test", "2025-12"), {"running_gem_commissions": [], "battle_count": 30})
        self.assertEqual(self.db.get_stats("test", MONTH)["battle_count"], 10)

    def test_explicit_save_stats_remains_a_full_snapshot_replacement(self):
        self.db.save_stats("test", MONTH, {"replacement": True})
        self.assertEqual(self.db.get_stats("test", MONTH), {"replacement": True})


class Cl1SchemaRepairTests(unittest.TestCase):
    """外部工具改坏 cl1_data 唯一键：构造 Cl1Database 即按原结构重建，数据保留、写入恢复。"""

    def setUp(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config" / "cl1_data.db"
        self.path.parent.mkdir(parents=True)

    def make_broken_db(self):
        """重现现场形态：三列主键（含 secure_json）的外部重建表。"""
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE "cl1_data" ("instance" TEXT, "month" TEXT, "encrypted_blob" BLOB,'
                         ' "data_json" TEXT, "secure_json" TEXT, PRIMARY KEY("instance","month","secure_json"))')
            conn.execute("INSERT INTO cl1_data (instance, month, data_json) VALUES (?, ?, ?)",
                         ("test", "2026-01", json.dumps({"battle_count": 5})))

    def repair(self):
        result = database.Cl1Database(self.path)
        result.store.ensure_ready()
        return result

    def test_broken_unique_key_is_repaired_and_writable(self):
        self.make_broken_db()
        before = self.path.read_bytes()
        migrated = self.repair()
        self.assertEqual(migrated.get_stats('test', '2026-01'), {'battle_count': 5})
        migrated.save_stats('test', '2026-01', {'battle_count': 6})
        self.assertEqual(migrated.get_stats('test', '2026-01'), {'battle_count': 6})
        self.assertEqual(self.path.read_bytes(), before)
        with migrated.store.transaction(write=False) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM cl1_months').fetchone()[0], 1)

    def test_intact_unique_key_is_left_alone(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE cl1_data (instance TEXT, month TEXT, data_json TEXT,"
                         " encrypted_blob BLOB, secure_json TEXT, PRIMARY KEY (instance, month))")
            conn.execute("INSERT INTO cl1_data VALUES ('test', '2026-01', '{}', NULL, NULL)")
            before = conn.execute("SELECT sql FROM sqlite_master WHERE name='cl1_data'").fetchone()[0]
        self.repair()
        with closing(sqlite3.connect(self.path)) as conn:
            after = conn.execute("SELECT sql FROM sqlite_master WHERE name='cl1_data'").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
