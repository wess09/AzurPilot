"""短猫统计实例隔离：真临时 SQLite、假掉落解析及独立进程，不接触用户数据。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import importlib.util
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

# 机器可能同时跑着模拟器/正式自动化，内存紧张时 OpenBLAS 初始化会卡
# “MemorTimeout” 20 秒（spawn 子进程引导同样受影响）；本测试只验证
# SQLite 跨进程串行化，单线程即可。
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

import numpy as np

from module.statistics import opsi_secure
from tests.opsi_test_support import install_store


GENRE = 'opsi_meowfficer_farming'
OLD_SCHEMA = '''CREATE TABLE opsi_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, imgid TEXT NOT NULL, server TEXT,
    zone TEXT, zone_type TEXT, zone_id INTEGER, hazard_level INTEGER, item TEXT,
    amount INTEGER, tag TEXT, device_id TEXT, genre TEXT, combat_count INTEGER,
    created_at INTEGER)'''


def module_stub(name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def load_source(name, relative, replacements):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module


def load_statistics(directory):
    """仅导入待测统计实现，日志、配置、设备身份与图像工具全部隔离。"""
    module = load_source('_instance_azurstats_test', 'module/statistics/azurstats.py', {
        'module.base.utils': module_stub('module.base.utils', area_pad=Mock(), save_image=Mock()),
        'module.logger': module_stub('module.logger', logger=Mock()),
        'module.statistics.drop_cleanup': module_stub('module.statistics.drop_cleanup',
                                                     cleanup_drop_screenshots_if_due=Mock()),
        'module.statistics.utils': module_stub('module.statistics.utils', pack=lambda images: images[0]),
        'module.base.device_id': module_stub('module.base.device_id', get_device_id=lambda: 'one-machine'),
    })
    module.AzurStats.LOCAL_DB = str(Path(directory) / 'config' / 'azurstats_local.db')
    module.AzurStats.LOCAL_MEOW_CSV = str(Path(directory) / 'log' / 'azurstat_meowofficer_farming.csv')
    return module


def item_row(instance, amount=100, imgid='same-image', month=9, item='OperationCoin', device='one-machine'):
    return dict(imgid=imgid, server='cn', zone='测试', zone_type='safe', zone_id=1,
                hazard_level=3, item=item, amount=amount, tag='', device_id=device,
                genre=GENRE, combat_count=2, created_at=int(datetime(2026, month, 15, 12).timestamp()),
                instance=instance)


def process_operation(directory, started, finished, operation):
    """子进程持独立模块和 Python 锁，验证真正的 SQLite 进程间串行化。"""
    if not Path(directory).is_relative_to(Path(tempfile.gettempdir())):
        raise RuntimeError('测试目录未隔离')
    module = load_statistics(directory)
    started.set()
    connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(lambda sql: started.set() if sql == 'BEGIN IMMEDIATE' else None)
        return conn

    with patch.object(module.sqlite3, 'connect', side_effect=traced_connect):
        if operation == 'migrate':
            module.AzurStats._ensure_local_db()
        else:
            module.AzurStats._insert_local_opsi_items([item_row('account_a', 300, imgid='new-image')])
            module.AzurStats.get_meowofficer_farming(instance='account_a')
    finished.set()


@dataclass
class ParsedItem:
    imgid: str = ''
    server: str = 'cn'
    zone: str = '测试'
    zone_type: str = 'safe'
    zone_id: int = 1
    hazard_level: int = 3
    item: str = 'OperationCoin'
    amount: int = 0
    tag: str = ''


class FakeScene:
    def load_file(self, image):
        self.amount = image

    def parse_scene(self):
        return [ParsedItem(amount=self.amount), ParsedItem(item='PlateT4', amount=2)]


class TestStatisticsInstanceIsolation(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        (Path(self.directory) / 'log').mkdir()
        install_store(self, self.directory)
        self.module = load_statistics(self.directory)
        self.stats = self.module.AzurStats
        self.api = load_source('_instance_statistics_api_test', 'module/api/statistics_service.py', {
            'module.api.protocol': module_stub('module.api.protocol', ApiError=ValueError),
        })
        self.enterContext(patch.dict(sys.modules, {
            'module.statistics.azurstats': self.module,
            'module.statistics.cl1_database': module_stub('module.statistics.cl1_database', db=Mock()),
        }))
        self.enterContext(patch.object(self.stats, '_ensure_local_parser', return_value=FakeScene))
        self.configs = SimpleNamespace(directory=Path(self.directory) / 'config', path=Mock(side_effect=lambda name: Path(self.directory) / f'{name}.json'))

    def record(self, instance, amount):
        stats = self.stats(SimpleNamespace(config_name=instance))
        self.assertTrue(stats.commit([amount], GENRE, local=True, combat_count=2))

    def rows(self, instance):
        """取「短猫掉落收益」表：大世界掉落页里还多了收获明细与掉落记录两张表，
        按标题取才不会被页面版式变化带跑。"""
        tables = self.api.report(self.configs, instance, 'loot', None, 7, 'month')['tables']
        return next(table for table in tables if table['title'] == '短猫掉落收益')['rows']

    def create_old_database(self):
        row = item_row(None, 5000, imgid='old-image', month=7)
        row.pop('instance')
        with closing(sqlite3.connect(self.stats.LOCAL_DB)) as conn, conn:
            conn.execute(OLD_SCHEMA)
            columns = ','.join(row)
            conn.execute(f'INSERT INTO opsi_items ({columns}) VALUES ({",".join("?" for _ in row)})',
                         tuple(row.values()))
        return row

    def test_capture_parser_database_cache_and_api_keep_two_instances_separate(self):
        self.record('account_a', 100)
        self.record('account_b', 900)
        self.assertEqual(self.rows('account_a')[0][2:5], [1.0, 100.0, 2.0])
        self.assertEqual(self.rows('account_b')[0][2:5], [1.0, 900.0, 2.0])
        stored = self.stats._load_local_opsi_items()
        self.assertEqual([row['instance'] for row in stored], ['account_a', 'account_a', 'account_b', 'account_b'])
        self.assertNotEqual(self.stats._meowofficer_farming_path('account_a'),
                            self.stats._meowofficer_farming_path('account_b'))
        self.assertEqual(self.api.refresh_loot(self.configs, 'account_a'), {'refreshed': True})
        self.assertEqual(self.rows('account_b')[0][2:4], [1.0, 900.0])

    def test_old_database_migration_preserves_shared_rows_without_assigning_them(self):
        old = self.create_old_database()
        self.stats._ensure_local_db()
        migrated = self.stats._load_local_opsi_items()
        self.assertEqual(len(migrated), 1)
        self.assertIsNone(migrated[0]['instance'])
        self.assertEqual({key: migrated[0][key] for key in old}, old)
        self.assertEqual(migrated[0]['id'], 1)
        self.record('account_a', 100)
        self.record('account_b', 900)
        self.assertEqual(self.rows('account_a')[0][2:4], [1.0, 100.0])
        self.assertEqual(self.rows('account_b')[0][2:4], [1.0, 900.0])
        self.assertEqual(self.rows('new_account'), [])
        notes = self.api.report(self.configs, 'account_a', 'loot', None, 7, 'month')['notes']
        self.assertIn('历史共享', ''.join(notes))
        self.assertIsNone(self.stats._load_local_opsi_items()[0]['instance'])

    def test_legacy_csv_is_preserved_and_never_used_as_instance_fallback(self):
        legacy = np.zeros((6, 7))
        legacy[:, 0] = np.arange(1, 7)
        legacy[2, 1:4] = [1000000000, 77, 9999]
        path = Path(self.stats.LOCAL_MEOW_CSV)
        np.savetxt(path, legacy, delimiter=',', header=','.join(self.stats.meowofficer_farming_labels), comments='')
        before = path.read_bytes()
        np.testing.assert_array_equal(self.stats.load_meowofficer_farming(), legacy)
        self.assertEqual(self.rows('account_a'), [])
        self.record('account_a', 100)
        self.assertEqual(path.read_bytes(), before)
        np.testing.assert_array_equal(self.stats.load_meowofficer_farming(), legacy)
        # 损坏的缓存不影响全局文件；读取回退到重算路径。

    def test_scoped_queries_filter_months_device_and_legacy_data(self):
        self.stats._insert_local_opsi_items([
            item_row('account_a', 2, month=9, item='PlateT4'),
            item_row('account_b', 9, month=8, item='PlateT4'),
            item_row(None, 99, month=7, item='PlateT4'),
            item_row('account_a', 999, month=6, item='PlateT4', device='another-machine'),
        ])
        self.assertEqual(self.stats.get_meow_loot_monthly_totals(year=2026, month=9, instance='account_a')[3]['Plate'], 2)
        self.assertEqual(self.stats.get_meow_loot_monthly_totals(year=2026, month=9, instance='account_b')[3]['Plate'], 0)
        self.assertEqual(self.stats.get_meow_loot_monthly_totals(year=2026, month=7, instance='account_a')[3]['Plate'], 0)
        self.assertEqual(self.stats.get_meow_loot_available_months(instance='account_a'), [(2026, 9)])
        self.assertEqual(self.stats.get_meow_loot_available_months(instance='account_b'), [(2026, 8)])
        self.assertEqual(self.stats.get_meow_loot_available_months(), [(2026, 9), (2026, 8), (2026, 7)])
        self.assertEqual(len(self.stats._load_local_opsi_items(device_id='one-machine', instance='account_a')), 1)
        with patch.object(self.module, 'get_device_id', return_value='another-machine'):
            self.assertEqual(self.rows('account_b'), [])

    def test_legacy_global_export_counts_identical_image_ids_in_each_instance(self):
        self.stats._insert_local_opsi_items([item_row('account_a', 100), item_row('account_b', 900)])
        global_data = self.stats.get_meowofficer_farming()
        np.testing.assert_array_equal(global_data[2, 2:4], [2, 500])
        np.testing.assert_array_equal(self.stats.load_meowofficer_farming(), global_data)
        self.assertEqual(self.rows('account_a')[0][2:4], [1.0, 100.0])

    def test_old_offline_rows_without_instance_stay_shared(self):
        row = item_row(None)
        row.pop('instance')
        self.stats._insert_local_opsi_items([row])
        self.assertIsNone(self.stats._load_local_opsi_items()[0]['instance'])
        self.assertEqual(self.rows('account_a'), [])

    def test_missing_legacy_cache_is_rebuilt_from_shared_details(self):
        self.create_old_database()
        cached = self.stats.load_meowofficer_farming()
        np.testing.assert_array_equal(cached[2, 2:4], [1, 5000])
        self.assertEqual(self.rows('account_a'), [])

    def test_cache_name_preserves_instance_identity_without_path_escaping(self):
        names = ['account_a', 'account_b', 'Account_A', '../account_a', '账号_A']
        paths = [Path(self.stats._meowofficer_farming_path(name)) for name in names]
        self.assertEqual(len(set(paths)), len(names))
        self.assertTrue(all(path.parent == Path(self.directory) / 'log' for path in paths))

    def test_concurrent_api_refreshes_keep_each_cache_and_existing_columns(self):
        self.stats._insert_local_opsi_items([item_row('account_a', 100), item_row('account_b', 900)])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda name: self.api.refresh_loot(self.configs, name), ['account_a', 'account_b']))
        self.assertEqual(results, [{'refreshed': True}, {'refreshed': True}])
        self.assertEqual(self.rows('account_a')[0][2:4], [1.0, 100.0])
        self.assertEqual(self.rows('account_b')[0][2:4], [1.0, 900.0])
        report = self.api.report(self.configs, 'account_a', 'loot', None, 7, 'month')
        meow = next(table for table in report['tables'] if table['title'] == '短猫掉落收益')
        self.assertEqual(len(meow['columns']), 7)
        self.assertEqual(report['instance'], 'account_a')

    def test_cache_replacement_failure_preserves_previous_complete_file(self):
        self.record('account_a', 100)
        before = self.stats.load_meowofficer_farming(instance='account_a')
        self.stats._insert_local_opsi_items([item_row('account_a', 300, imgid='new-image')])
        with self.stats._database().transaction() as conn:
            conn.execute("CREATE TRIGGER reject_cache BEFORE INSERT ON farming_aggregates BEGIN SELECT RAISE(ABORT, 'disk full'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.stats.get_meowofficer_farming(instance='account_a')
        np.testing.assert_array_equal(self.stats.load_meowofficer_farming(instance='account_a'), before)
        with self.stats._database().transaction() as conn:
            conn.execute('DROP TRIGGER reject_cache')
        self.api.refresh_loot(self.configs, 'account_a')
        self.assertEqual(self.rows('account_a')[0][2:4], [2.0, 200.0])

    def test_read_during_cache_write_sees_the_previous_complete_version(self):
        self.record('account_a', 100)
        self.stats._insert_local_opsi_items([item_row('account_a', 300, imgid='new-image')])
        write = self.stats._write_meowofficer_farming
        observed = []
        def inspect_write(*args, **kwargs):
            write(*args, **kwargs)
            observed.append(self.stats.load_meowofficer_farming(instance='account_a')[2, 3])
        with patch.object(self.stats, '_write_meowofficer_farming', side_effect=inspect_write):
            self.stats.get_meowofficer_farming(instance='account_a')
        self.assertEqual(observed, [100])
        self.assertEqual(self.rows('account_a')[0][2:4], [2.0, 200.0])

    def test_file_occupancy_keeps_previous_cache_until_next_attempt(self):
        self.record('account_a', 100)
        before = self.stats.load_meowofficer_farming(instance='account_a')
        self.stats._insert_local_opsi_items([item_row('account_a', 300, imgid='new-image')])
        with self.stats._database().transaction() as writer:
            with self.assertRaises(sqlite3.OperationalError):
                with self.stats._database().transaction(timeout=0) as competing:
                    competing.execute('DELETE FROM farming_aggregates')
            np.testing.assert_array_equal(self.stats.load_meowofficer_farming(instance='account_a'), before)
        self.stats.get_meowofficer_farming(instance='account_a')
        self.assertEqual(self.rows('account_a')[0][2:4], [2.0, 200.0])

    def stop_process(self, process):
        if process.is_alive():
            process.terminate()
        process.join(5)

    @unittest.skipUnless(sys.platform == "win32", "需要共享本机临时凭据")
    def test_two_processes_migrate_old_schema_once_after_sqlite_lock_is_released(self):
        self.create_old_database()
        context = multiprocessing.get_context('spawn')
        processes = []
        with closing(sqlite3.connect(self.stats.LOCAL_DB)) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            for _ in range(2):
                started, finished = context.Event(), context.Event()
                process = context.Process(target=process_operation,
                                          args=(self.directory, started, finished, 'migrate'))
                process.start()
                self.addCleanup(self.stop_process, process)
                processes.append((process, finished))
                # 机器可能同时跑着正式自动化与模拟器，spawn 冷启动余量给足。
                self.assertTrue(started.wait(30))
                self.assertFalse(finished.is_set())
        for process, finished in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(finished.is_set())
        rows = self.stats._load_local_opsi_items()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['instance'])
        with closing(sqlite3.connect(self.stats._database().path)) as conn:
            self.assertEqual([row[1] for row in conn.execute('PRAGMA table_info(opsi_items)')].count('instance'), 1)

    @unittest.skipUnless(sys.platform == "win32", "需要共享本机临时凭据")
    def test_cross_process_insert_and_refresh_cannot_be_overwritten_by_older_snapshot(self):
        self.record('account_a', 100)
        context = multiprocessing.get_context('spawn')
        started, finished = context.Event(), context.Event()
        paused, release = threading.Event(), threading.Event()
        write = self.stats._write_meowofficer_farming

        def pause_write(data, instance=None, **kwargs):
            paused.set()
            if not release.wait(10):
                raise TimeoutError('未释放汇总写入')
            return write(data, instance=instance, **kwargs)

        process = context.Process(target=process_operation,
                                  args=(self.directory, started, finished, 'record'))
        with patch.object(self.stats, '_write_meowofficer_farming', side_effect=pause_write), \
                ThreadPoolExecutor(max_workers=1) as pool:
            refresh = pool.submit(self.stats.get_meowofficer_farming, instance='account_a')
            try:
                self.assertTrue(paused.wait(5))
                process.start()
                self.addCleanup(self.stop_process, process)
                self.assertTrue(started.wait(30))
                self.assertFalse(finished.is_set())
                with closing(sqlite3.connect(self.stats._database().path, timeout=0)) as probe:
                    with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                        probe.execute('BEGIN IMMEDIATE')
            finally:
                release.set()
            refresh.result(timeout=5)
        process.join(10)
        self.assertEqual(process.exitcode, 0)
        self.assertTrue(finished.is_set())
        self.assertEqual(self.rows('account_a')[0][2:4], [2.0, 200.0])


if __name__ == '__main__':
    unittest.main()
