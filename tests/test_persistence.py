"""总库结构、原生投影与兼容值的隔离验证。"""
import math
import sqlite3
import unittest

from module.persistence.database import create_schema, register_instance
from module.persistence.scheduler import read_persistent, read_program, save_persistent, save_program, read_observations, write_observation
from module.persistence.snapshots import read_month, read_ship, save_month, save_ship
from module.persistence.values import read_value, write_value
from module.scheduler.templates import default_program


class NativeStorageTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        create_schema(self.connection)

    def assertHealthy(self):
        self.assertEqual([], self.connection.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual('ok', self.connection.execute('PRAGMA integrity_check').fetchone()[0])

    def test_schema_is_strict_and_contains_no_payload_columns(self):
        tables = [row for row in self.connection.execute('PRAGMA table_list') if row['name'] != 'sqlite_sequence' and not row['name'].startswith('sqlite_')]
        self.assertEqual(56, len(tables))
        self.assertTrue(all(row['strict'] for row in tables))
        for table in tables:
            columns = {row['name'] for row in self.connection.execute(f'PRAGMA table_info({table["name"]})')}
            self.assertFalse(columns & {'data_json', 'secure_json', 'secure_payload', 'opsi_payload'})

    def test_month_partial_nested_and_unknown_fields_roundtrip(self):
        data = {'battle_count': None, 'custom': {'nested': [True, None, 2 ** 90, {}, []]},
                'akashi_ap_entries': [{'keep': True}, {'amount': 2 ** 90, 'count': None}, 42],
                'last_ap_notification': {}, 'meow_hazard_stats': {'2': {'round_times': [], 'custom': 7}, '02': None},
                'siren_research_devices': {'meow': {'2': 3, 'unknown': []}},
                'commission_income_entries': [{'keep': True}, {'items': {'Gem': 2 ** 90}, 'screenshots': [None, 'a.png', {}]}]}
        save_month(self.connection, 'alpha', '2026-10', data)
        self.assertEqual(data, read_month(self.connection, 'alpha', '2026-10'))
        self.assertEqual(1, self.connection.execute('SELECT COUNT(*) FROM commission_income_items').fetchone()[0])
        self.assertHealthy()

    def test_month_replacement_preserves_exact_field_set_and_cleans_values(self):
        save_month(self.connection, 'alpha', '2026-10', {'custom': {'a': [1]}, 'battle_count': 5})
        save_month(self.connection, 'alpha', '2026-10', {'replacement': True})
        self.assertEqual({'replacement': True}, read_month(self.connection, 'alpha', '2026-10'))
        self.assertEqual(1, self.connection.execute('SELECT COUNT(*) FROM typed_value_sets').fetchone()[0])
        self.assertHealthy()

    def test_all_month_families_and_samples_are_native(self):
        data = {'battle_count': 6, 'akashi_ap_entries': [{'ts': 'now', 'amount': 200, 'base': 200, 'count': 1, 'source': 'cl1'}],
                'meow_round_times': [{'duration': 100.5, 'hazard_level': 3}], 'meow_battle_times': [52.0],
                'meow_hazard_stats': {'3': {'battle_raw_count': 2, 'effective_rounds': 1.0, 'round_times': [110.0], 'battle_times': [55.0]}},
                'coins_snapshots': [{'ts': 'now', 'yellow_coins': 500, 'purple_coins': 10}],
                'siren_research_devices': {'cl1': 1, 'meow': {}}, 'ap_snapshots': [],
                'research_drop_entries': [{'ts': 'now', 'imgid': 'same', 'items': {'Plate': 1}}],
                'gem_commission_entries': [{'ts': 'now', 'duration': 2, 'reward': 0, 'success': False}]}
        save_month(self.connection, 'alpha', '2026-10', data)
        self.assertEqual(data, read_month(self.connection, 'alpha', '2026-10'))
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM typed_value_sets').fetchone()[0])
        self.assertHealthy()

    def test_partial_ship_and_average_are_preserved(self):
        data = {'battle_times': {'samples': [52.0], 'average': 17.0}, 'target_level': 125, 'ships': [],
                'daily_stats': {'2026-10-01': {}, 'custom': None}, 'custom': [2 ** 90, None]}
        save_ship(self.connection, 'alpha', data)
        self.assertEqual(data, read_ship(self.connection, 'alpha'))
        self.assertEqual(17.0, self.connection.execute('SELECT average_seconds FROM ship_exp_duration_groups').fetchone()[0])
        save_ship(self.connection, 'alpha', {})
        self.assertEqual({}, read_ship(self.connection, 'alpha'))
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM typed_value_sets').fetchone()[0])
        self.assertHealthy()

    def test_draft_duplicate_ids_and_dangling_edges_roundtrip(self):
        document = default_program().model_dump()
        document['nodes'].append(dict(document['nodes'][0]))
        document['nodes'][0]['position'] = {'custom': 2 ** 90}
        document['nodes'][1]['position'] = {}
        document['viewport'] = {}
        document['edges'][0]['target'] = 'missing'
        data = {'mode': 'native', 'draft': document, 'active': None, 'generation': 0}
        save_program(self.connection, 'alpha', data, 'revision')
        self.assertEqual(dict(data, revision='revision'), read_program(self.connection, 'alpha'))
        self.assertHealthy()

    def test_runtime_native_records_and_key_fallback(self):
        data = {'variables': {'custom': [True, None, 2 ** 90]}, 'records': {
            'lastExecuted': {'Main': 'now'}, 'rotation': {'key': 2}, 'cooldowns': {},
            'quotas': {'key': {'2026-10-09': 3}}, 'results': {'Main': {'status': 'completed', 'custom': None}},
            'lastResult': {}, 'custom': {'a': []}}, 'inFlight': 'Main'}
        save_persistent(self.connection, 'alpha', data)
        self.assertEqual(data, read_persistent(self.connection, 'alpha'))
        self.assertEqual(2, self.connection.execute('SELECT COUNT(*) FROM scheduler_counters').fetchone()[0])
        data['records']['quotas'] = {'empty': {}}
        save_persistent(self.connection, 'alpha', data)
        self.assertEqual(data, read_persistent(self.connection, 'alpha'))
        self.assertHealthy()

    def test_values_cannot_cross_instance_or_context(self):
        save_month(self.connection, 'alpha', '2026-10', {})
        save_month(self.connection, 'beta', '2026-10', {})
        value_id = write_value(self.connection, 'alpha', True, month='2026-10')
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("INSERT INTO cl1_compat_fields VALUES('beta','2026-10','bad','value',?)", (value_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("INSERT INTO scheduler_state_variables VALUES('alpha','bad',?)", (value_id,))
        self.assertEqual(True, read_value(self.connection, value_id))

    def test_special_floats_remain_statistics_only(self):
        save_ship(self.connection, 'alpha', {'custom': float('inf')})
        self.assertEqual(float('inf'), read_ship(self.connection, 'alpha')['custom'])
        save_month(self.connection, 'alpha', '2026-10', {'custom': float('nan')})
        self.assertTrue(math.isnan(read_month(self.connection, 'alpha', '2026-10')['custom']))
        register_instance(self.connection, 'alpha')
        with self.assertRaises(ValueError):
            write_value(self.connection, 'alpha', float('nan'), runtime=True)
        write_observation(self.connection, 'alpha', 'Oil', 100, 'old', 'fixture')
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.assertRaises(ValueError):
                write_observation(self.connection, 'alpha', 'Oil', value, 'new', 'fixture')
        self.assertEqual(read_observations(self.connection, 'alpha')['Oil']['Value'], 100)
        self.assertHealthy()
