"""四个统计存储在明文语义下的集成测试。

覆盖原生业务列、旧文件只读转换、部分快照保留及业务接口一致性。
"""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from module.statistics import opsi_secure, resource_stats
from module.statistics.azurstats import AzurStats
from module.statistics.cl1_database import Cl1Database
from module.statistics.ship_exp_stats import ShipExpStats


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'config').mkdir()
        (self.root / 'log' / 'cl1' / 'inst').mkdir(parents=True)


class Cl1StoreIntegration(StoreCase):
    def make_db(self):
        return Cl1Database(db_path=self.root / 'config' / 'cl1_data.db')

    def raw(self, sql, params=()):
        conn = sqlite3.connect(self.root / 'config' / 'azurpilot.db')
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def month(self):
        return datetime.now().strftime('%Y-%m')

    def test_writes_split_public_and_secure_columns_as_plaintext(self):
        db = self.make_db()
        db.increment_battle_count('inst', 3)
        db.add_ap_snapshot('inst', 131, source='cl1')
        db.add_commission_income('inst', {'Gem': 5})
        self.assertEqual(self.raw('SELECT battle_count FROM cl1_months')[0][0], 3)
        self.assertEqual(self.raw('SELECT ap FROM action_point_snapshots')[0][0], 131)
        self.assertEqual(self.raw('SELECT item,amount FROM commission_income_items')[0], ('Gem', 5))
        data = db.get_stats('inst', self.month())
        self.assertEqual(data['battle_count'], 3)
        self.assertEqual(len(data['ap_snapshots']), 1)
        self.assertEqual(len(data['commission_income_entries']), 1)
        db.increment_akashi_encounter('inst')
        self.assertEqual(db.get_stats('inst', self.month())['akashi_encounters'], 1)

    def test_legacy_whole_row_reads_and_splits_on_next_write(self):
        path = self.root / 'config' / 'cl1_data.db'
        data = {'battle_count': 7, 'commission_income_entries': [{'keep': True}]}
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT)')
            conn.execute('INSERT INTO cl1_data VALUES(?,?,?)', ('inst', self.month(), json.dumps(data)))
        original = path.read_bytes()
        db = self.make_db()
        self.assertEqual(db.get_stats('inst', self.month()), data)
        db.increment_battle_count('inst', 1)
        self.assertEqual(self.raw('SELECT battle_count FROM cl1_months')[0][0], 8)
        self.assertEqual(db.get_stats('inst', self.month())['commission_income_entries'], [{'keep': True}])
        self.assertEqual(path.read_bytes(), original)


class AzurstatsIntegration(StoreCase):
    ROW = {
        'imgid': 'img-1', 'server': 'cn', 'zone': 'NA海域', 'zone_type': 'abyssal',
        'zone_id': 5, 'hazard_level': 6, 'item': 'PlateGeneralT4', 'amount': 3,
        'tag': 'gold', 'device_id': 'dev-1', 'instance': 'inst',
        'genre': 'opsi_meowfficer_farming', 'combat_count': 2, 'created_at': 1_789_000_000,
    }

    def setUp(self):
        super().setUp()
        self.db_patch = patch.object(AzurStats, 'LOCAL_DB', str(self.root / 'config' / 'azurstats_local.db'))
        self.csv_patch = patch.object(
            AzurStats, 'LOCAL_MEOW_CSV', str(self.root / 'log' / 'azurstat_meowofficer_farming.csv'))
        self.db_patch.start()
        self.csv_patch.start()
        self.addCleanup(self.csv_patch.stop)
        self.addCleanup(self.db_patch.stop)
        AzurStats._ensure_local_db()

    def raw(self, sql, params=()):
        conn = sqlite3.connect(self.root / 'config' / 'azurpilot.db')
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def test_insert_stores_plaintext_payload_and_load_merges(self):
        AzurStats._insert_local_opsi_items([dict(self.ROW), dict(self.ROW, imgid='img-2', amount=7)])
        rows = self.raw('SELECT item,amount,hazard_level FROM opsi_items ORDER BY id')
        self.assertEqual(rows, [('PlateGeneralT4', 3, 6), ('PlateGeneralT4', 7, 6)])
        loaded = AzurStats.load_opsi_drop_rows(instance='inst', device_id='dev-1')
        self.assertEqual([row['item'] for row in loaded], ['PlateGeneralT4', 'PlateGeneralT4'])
        self.assertEqual([row['amount'] for row in loaded], [3, 7])

    def test_monthly_totals_across_old_and_new_rows(self):
        # 旧行：物品字段写在普通列（没有载荷列）。
        with sqlite3.connect(self.root / 'config' / 'azurpilot.db') as conn:
            conn.execute("INSERT INTO opsi_items (imgid, device_id, instance, genre, created_at, item, amount, hazard_level) "
                         "VALUES ('img-0', 'dev-1', 'inst', 'opsi_meowfficer_farming', ?, 'PlateT4', 3, 6)",
                         (int(datetime(2026, 9, 1).timestamp()),))
        AzurStats._insert_local_opsi_items([dict(self.ROW, item='PlateT4', amount=4)])
        totals = AzurStats.get_meow_loot_monthly_totals(year=2026, month=9, device_id='dev-1', instance='inst')
        self.assertEqual(totals[6]['Plate'], 7)

    def test_farming_csv_is_plaintext_and_readable(self):
        AzurStats._insert_local_opsi_items([dict(self.ROW)])
        data = AzurStats.get_meowofficer_farming(instance='inst')
        self.assertEqual(self.raw('SELECT count(*) FROM farming_aggregates')[0][0], 6)
        self.assertEqual(list((self.root / 'log').glob('azurstat_meowofficer_farming*.csv')), [])
        np.testing.assert_allclose(AzurStats.load_meowofficer_farming(instance='inst'), data)


class ResourceStatsIntegration(StoreCase):
    SNAPSHOT = {'Oil': 14000, 'Coin': 180000, 'ActionPoint': 131, 'YellowCoin': 500, 'PurpleCoin': 20}

    def setUp(self):
        super().setUp()
        self.db_patch = patch.object(resource_stats, '_LOCAL_DB', str(self.root / 'config' / 'azurstats_local.db'))
        self.ensured_patch = patch.object(resource_stats, '_table_ensured', False)
        self.db_patch.start()
        self.ensured_patch.start()
        self.addCleanup(self.ensured_patch.stop)
        self.addCleanup(self.db_patch.stop)

    def raw(self, sql):
        conn = sqlite3.connect(self.root / 'config' / 'azurpilot.db')
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def test_snapshot_stores_only_opsi_columns_in_plaintext_payload(self):
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT))
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT, ActionPoint=160))
        rows = self.raw('SELECT oil,action_point,purple_coin FROM resource_snapshots ORDER BY id')
        self.assertEqual(rows, [(14000, 131, 20), (14000, 160, 20)])
        timeline = resource_stats.get_resource_timeline('inst')
        self.assertEqual([row['action_point'] for row in timeline], [131, 160])
        with patch.object(resource_stats, '_overlay_opsi_snapshot', side_effect=AssertionError('不得读取载荷')):
            public = resource_stats.get_resource_timeline('inst', include_opsi=False)
        self.assertEqual([row['oil'] for row in public], [14000, 14000])
        self.assertTrue(all(row['action_point'] is None for row in public))

    def test_interval_summary_covers_opsi_currencies(self):
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT))
        start = datetime.now()
        resource_stats.record_resource_snapshot('inst', dict(self.SNAPSHOT, ActionPoint=160))
        summary = resource_stats.get_resource_interval_summary('inst', start, datetime.now() + timedelta(minutes=1))
        self.assertEqual(summary['resources']['ActionPoint']['delta'], 29)
        self.assertEqual(summary['resources']['Oil']['delta'], 0)

    def test_legacy_columns_without_payload_stay_readable(self):
        resource_stats._ensure_table()
        with sqlite3.connect(self.root / 'config' / 'azurpilot.db') as conn:
            conn.execute("INSERT INTO resource_snapshots (instance, ts, oil, action_point, yellow_coin, purple_coin) "
                         "VALUES ('inst', '2026-09-01T10:00:00', 12000, 100, 400, 15)")
        timeline = resource_stats.get_resource_timeline('inst')
        self.assertEqual(timeline[0]['action_point'], 100)
        self.assertEqual(timeline[0]['purple_coin'], 15)


class ShipExpIntegration(StoreCase):
    def make_stats(self):
        return ShipExpStats(path=self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json')

    def test_save_is_plain_json_and_reload_matches(self):
        stats = self.make_stats()
        stats.data = {'battle_times': {'samples': [52.0], 'average': 52.0}, 'target_level': 125}
        stats._save()
        with sqlite3.connect(stats._path) as conn:
            self.assertEqual(conn.execute('SELECT target_level FROM ship_exp_checks').fetchone()[0], 125)
            self.assertEqual(conn.execute('SELECT average_seconds FROM ship_exp_duration_groups').fetchone()[0], 52.0)
        fresh = self.make_stats()
        self.assertEqual(fresh.data, stats.data)

    def test_legacy_wrapped_file_loads_and_rewrites_plain(self):
        import base64
        import os
        from tests.test_opsi_secure import seal_v2
        from module.statistics.opsi_secure import file_context
        key = os.urandom(32)
        directory = self.root / 'config' / 'opsi_secure'
        directory.mkdir(parents=True)
        (directory / 'keyring.json').write_bytes(json.dumps(
            {'version': 2, 'algorithm': opsi_secure.ALGORITHM, 'installation_id': 'inst-id',
             'provider': 'container-file'}).encode())
        (directory / 'state.json').write_bytes(json.dumps(
            {'slot': 'x', 'state': {'phase': 'ready', 'key': base64.b64encode(key).decode(),
                                    'installation_id': 'inst-id'}}).encode())
        path = self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json'
        blob = seal_v2(key, 'ships', {'target_level': 130}, file_context(self.root, 'ships', path), 'inst-id')
        path.write_bytes(json.dumps({opsi_secure.WRAPPER_KEY: True, 'payload': blob}).encode())
        previous = opsi_secure._STORE
        opsi_secure.set_store(opsi_secure.StatsStore(self.root))
        self.addCleanup(opsi_secure.set_store, previous)
        stats = self.make_stats()
        self.assertEqual(stats.data['target_level'], 130)
        stats._save()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['payload'], blob)
        self.assertEqual(self.make_stats().data['target_level'], 130)


if __name__ == '__main__':
    unittest.main()
