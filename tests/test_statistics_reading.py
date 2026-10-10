"""报表读取的展示路径：不产生写入副作用，缺数据时明确降级。"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from module.api.statistics_service import _report, report, get_statistics_fingerprint
from module.statistics.cl1_database import Cl1Database
from module.statistics.ship_exp_stats import ShipExpStats
from tests.test_opsi_secure import make_cl1_db


class StatisticsReadingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'config').mkdir()
        (self.root / 'log' / 'cl1' / 'inst').mkdir(parents=True)
        make_cl1_db(self.root / 'config/cl1_data.db')
        self.database = Cl1Database(self.root / 'config/cl1_data.db')
        self.ships = self.root / 'log/cl1/inst/ship_exp_data.json'
        self.ships.write_text('{"battle_times": {"samples": [52.0], "average": 52.0}}', encoding='utf-8')
        self.configs = SimpleNamespace(directory=self.root / 'config', path=lambda _: self.root / 'config/inst.json')
        self.enterContext(patch('module.statistics.cl1_database.db', self.database))
        self.enterContext(patch('module.statistics.opsi_month.cl1_db', self.database))
        self.enterContext(patch('module.statistics.ship_exp_stats.ShipExpStats',
            side_effect=lambda **kwargs: ShipExpStats(path=self.ships, **kwargs)))

    def get_report(self, reader=report, category='opsi'):
        return reader(self.configs, 'inst', category, '2026-09', 7, 'month')

    def test_report_read_has_no_write_side_effects(self):
        for category in ('opsi', 'action', 'ships'):
            with self.subTest(category=category):
                expected = self.get_report(_report, category)
                before = (self.database.db_path.read_bytes(), self.ships.read_bytes())
                self.assertEqual(self.get_report(category=category), expected)
                self.assertEqual((self.database.db_path.read_bytes(), self.ships.read_bytes()), before)

    def test_meow_compatibility_is_in_memory_until_explicit_backfill(self):
        data = self.database.get_stats('inst', '2026-09')
        data.pop('meow_battle_raw_count')
        self.database.save_stats('inst', '2026-09', data)
        before = self.database.db_path.read_bytes()
        with patch.object(self.database, '_stats_transaction', side_effect=AssertionError('展示不能进入写事务')):
            result = self.database.get_meow_stats('inst', 2026, 9)
        self.assertGreater(result['battle_count'], 0)
        self.assertEqual(self.database.db_path.read_bytes(), before)
        self.assertNotIn('meow_battle_raw_count', self.database.get_stats('inst', '2026-09'))
        self.assertTrue(self.database.backfill_meow_stats('inst', 2026, 9))
        self.assertEqual(self.database.get_stats('inst', '2026-09')['meow_battle_raw_count'], result['battle_count'])

    def test_fingerprint_tracks_wal_changes_without_overview_events(self):
        original = get_statistics_fingerprint('inst', self.root / 'config')
        from module.api import statistics_service
        stat = statistics_service.os.stat

        def changed(path, **kwargs):
            if str(path).endswith('azurpilot.db-wal'):
                return SimpleNamespace(st_mtime_ns=987654321, st_size=4096)
            return stat(path, **kwargs)

        with patch.object(statistics_service.os, 'stat', side_effect=changed):
            self.assertNotEqual(get_statistics_fingerprint('inst', self.root / 'config'), original)


if __name__ == '__main__':
    unittest.main()
