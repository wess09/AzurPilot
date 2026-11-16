"""报表读取的展示路径：不产生写入副作用，缺数据时明确降级。"""
import tempfile
import unittest
from datetime import datetime
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

    def test_meow_battle_average_accepts_mixed_sample_formats(self):
        cases = [
            ([], 0.0),
            ([20.5, 39.5], 30.0),
            ([{'duration': 12, 'hazard_level': 3}, {'duration': 19}], 15.5),
            ([10.0, {'duration': 20, 'hazard_level': 5}, 30], 20.0),
            ([10.125, {'duration': 20}, None, {}, {'duration': None},
              {'duration': 'invalid'}, {'duration': {}}, 'invalid'], 15.06),
            ([None, {}, {'duration': None}, {'duration': 'invalid'}], 0.0),
        ]
        for samples, expected in cases:
            with self.subTest(samples=samples):
                data = self.database.get_stats('inst', '2026-09')
                data['meow_battle_times'] = samples
                self.database.save_stats('inst', '2026-09', data)
                with patch.object(self.database, '_stats_transaction', side_effect=AssertionError('展示不能进入写事务')):
                    result = self.database.get_meow_stats('inst', 2026, 9)
                self.assertEqual(result['avg_battle_time'], expected)
                self.assertEqual(result['battle_times'], samples)
                self.assertEqual(self.database.get_stats('inst', '2026-09')['meow_battle_times'], samples)

    def test_meow_hazard_averages_accept_mixed_battle_samples(self):
        data = self.database.get_stats('inst', '2026-09')
        data['meow_battle_times'] = [10, {'duration': 50, 'hazard_level': 5}]
        data['meow_hazard_stats']['3']['battle_times'] = [10, {'duration': 30}, None]
        data['meow_hazard_stats']['5'] = {
            'battle_raw_count': 3, 'effective_rounds': 1.0,
            'battle_times': [{'duration': 30}, 50, {'duration': None}],
        }
        self.database.save_stats('inst', '2026-09', data)
        result = self.database.get_meow_stats('inst', 2026, 9)
        self.assertEqual(result['avg_battle_time'], 30.0)
        for hazard, expected in ((3, 20.0), (5, 40.0)):
            with self.subTest(hazard=hazard):
                self.assertEqual(result['by_hazard'][str(hazard)]['avg_battle_time'], expected)
                filtered = self.database.get_meow_stats('inst', 2026, 9, hazard_level=hazard)
                self.assertEqual(filtered['avg_battle_time'], expected)

    def test_report_handles_legacy_and_new_meow_battle_samples(self):
        with patch('module.statistics.cl1_database.datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 1, 12)
            self.database.add_meow_battle_time('inst', 39.5, hazard_level=3)
        samples = self.database.get_stats('inst', '2026-09')['meow_battle_times']
        self.assertEqual(samples, [20.5, {'duration': 39.5, 'hazard_level': 3}])
        before = self.database.db_path.read_bytes()
        with patch.object(self.database, '_stats_transaction', side_effect=AssertionError('展示不能进入写事务')):
            result = self.database.get_meow_stats('inst', 2026, 9)
            report_data = self.get_report()
        self.assertEqual(result['avg_battle_time'], 30.0)
        meow_table = next(table for table in report_data['tables'] if table['key'] == 'meow_runs')
        self.assertEqual(meow_table['rows'][0][3], 29.75)
        self.assertEqual(self.database.db_path.read_bytes(), before)

    def test_fingerprint_tracks_wal_changes_without_overview_events(self):
        original = get_statistics_fingerprint('inst', self.root / 'config')
        stat = Path.stat

        def changed(path, **kwargs):
            if str(path).endswith('azurpilot.db-wal'):
                return SimpleNamespace(st_mtime_ns=987654321, st_size=4096)
            return stat(path, **kwargs)

        with patch.object(Path, 'stat', new=changed):
            self.assertNotEqual(get_statistics_fingerprint('inst', self.root / 'config'), original)


if __name__ == '__main__':
    unittest.main()
