"""损坏旧快照只从已冻结的备份恢复，迁移不得改写旧源。"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from module.persistence.database import BusinessDatabase
from module.persistence.migration import LegacyDecoder, MigrationError
from module.persistence.snapshots import read_month, read_ship
from module.statistics import opsi_secure
from tests.opsi_test_support import install_store
from tests.test_opsi_secure import copy_fixture, seal_v2


class SnapshotRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        install_store(self, self.root)

    def sources(self, root, filename, primary, backup):
        source = root / 'log' / 'cl1' / 'inst' / filename
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(primary)
        previous = source.with_name(source.name + '.bak')
        previous.write_bytes(backup)
        return source, previous

    def test_damaged_snapshot_recovers_from_backup_and_preserves_both_sources(self):
        for kind, filename in (('ships', 'ship_exp_data.json'), ('archives', 'cl1_monthly.json')):
            for index, raw in enumerate((b'', b' \r\n\t', b'{"private":', b'\xff')):
                with self.subTest(kind=kind, raw=raw):
                    root = self.root / f'{kind}-{index}'
                    root.mkdir()
                    install_store(self, root)
                    expected = {'target_level': 120, 'keep': [None, {}, 2 ** 80]}
                    data = expected if kind == 'ships' else {'2026-09': expected}
                    saved = json.dumps(data).encode('utf-8')
                    source, previous = self.sources(root, filename, raw, saved)
                    database = BusinessDatabase(root / 'config')
                    with self.assertLogs('alas', level='INFO') as captured:
                        database.ensure_ready()
                    self.assertTrue(database.marker.exists())
                    backup = next((database.directory / 'storage-backups').iterdir())
                    for path, content in ((source, raw), (previous, saved)):
                        self.assertEqual(path.read_bytes(), content)
                        self.assertEqual((backup / path.relative_to(root)).read_bytes(), content)
                    report = json.loads((backup / 'unmigrated.json').read_text(encoding='utf-8'))
                    self.assertEqual(len(report), 1)
                    self.assertEqual(report[0]['source'], str(source.relative_to(root)))
                    self.assertEqual(report[0]['recovered_from'], str(previous.relative_to(root)))
                    with database.transaction(write=False) as connection:
                        actual = read_ship(connection, 'inst') if kind == 'ships' else read_month(connection, 'inst', '2026-09')
                        self.assertEqual(actual, expected)
                        self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                        self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
                    self.assertIn('已从旧快照备份恢复', '\n'.join(captured.output))
                    self.assertNotIn('"private":', '\n'.join(captured.output))
                    with patch.object(LegacyDecoder, 'file', side_effect=AssertionError('不能重复导入')):
                        BusinessDatabase(database.directory).ensure_ready()

    def test_valid_primary_keeps_priority_over_backup(self):
        for kind, filename in (('ships', 'ship_exp_data.json'), ('archives', 'cl1_monthly.json')):
            with self.subTest(filename=filename):
                source, _ = self.sources(self.root, filename, b'{"keep":7}', b'{"keep":9}')
                self.assertEqual(LegacyDecoder(self.root).file(kind, source, source), {'keep': 7})

    def test_recovered_archive_only_fills_months_missing_from_database(self):
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as connection, connection:
            connection.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT)')
            connection.execute('INSERT INTO cl1_data VALUES(?,?,?)', ('inst', '2026-09', '{"battle_count":7}'))
        self.sources(self.root, 'cl1_monthly.json', b'',
                     b'{"2026-09":{"battle_count":9},"2026-08":{"battle_count":3}}')
        database = BusinessDatabase(self.root / 'config')
        with self.assertLogs('alas', level='INFO'):
            database.ensure_ready()
        with database.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'inst', '2026-09'), {'battle_count': 7})
            self.assertEqual(read_month(connection, 'inst', '2026-08'), {'battle_count': 3})

    def test_backup_decode_uses_frozen_copy_and_original_file_context(self):
        import base64
        root = copy_fixture(self)
        install_store(self, root)
        state = json.loads((root / 'config' / 'opsi_secure' / 'state.json').read_bytes())['state']
        key = base64.b64decode(state['key'])
        source, previous = self.sources(root, 'ship_exp_data.json', b'', b'broken-original-backup')
        saved_copy = root / 'frozen' / 'ship_exp_data.json'
        saved_copy.parent.mkdir()
        saved_copy.write_bytes(b'')
        expected = {'target_level': 120}
        encrypted = seal_v2(key, 'ships', expected, opsi_secure.file_context(root, 'ships', source),
                            state['installation_id']).encode('utf-8')
        saved_copy.with_name(saved_copy.name + '.bak').write_bytes(encrypted)
        material = (root / 'config' / 'opsi_secure' / 'state.json').read_bytes()
        with patch.object(opsi_secure, '_dpapi', side_effect=lambda value, decrypt=False: value), \
                patch.object(opsi_secure, 'decrypt_all', side_effect=AssertionError('不能改写旧文件')):
            decoder = LegacyDecoder(root)
            self.assertEqual(decoder.file('ships', source, saved_copy), expected)
        self.assertEqual(source.read_bytes(), b'')
        self.assertEqual(previous.read_bytes(), b'broken-original-backup')
        self.assertEqual((root / 'config' / 'opsi_secure' / 'state.json').read_bytes(), material)

    def test_unreadable_backup_is_reported_without_blocking_other_instances(self):
        for index, invalid in enumerate((b'{', b'[]')):
            with self.subTest(invalid=invalid):
                root = self.root / str(index)
                root.mkdir()
                install_store(self, root)
                source, previous = self.sources(root, 'ship_exp_data.json', b'', invalid)
                valid = root / 'log' / 'cl1' / 'other' / source.name
                valid.parent.mkdir()
                valid.write_text('{"target_level":120}', encoding='utf-8')
                database = BusinessDatabase(root / 'config')
                with self.assertLogs('alas', level='INFO'):
                    database.ensure_ready()
                with database.transaction(write=False) as connection:
                    self.assertIsNone(read_ship(connection, 'inst'))
                    self.assertEqual(read_ship(connection, 'other'), {'target_level': 120})
                report = json.loads(next((database.directory / 'storage-backups').glob('*/unmigrated.json')).read_bytes())
                self.assertEqual({entry['source'] for entry in report},
                                 {str(path.relative_to(root)) for path in (source, previous)})
                self.assertFalse(any('recovered_from' in entry for entry in report))

    def test_valid_json_with_invalid_structure_still_blocks_cutover(self):
        source, _ = self.sources(self.root, 'ship_exp_data.json', b'[]', b'{"keep":7}')
        database = BusinessDatabase(self.root / 'config')
        with self.assertLogs('alas', level='INFO'), self.assertRaisesRegex(MigrationError, '旧文件快照不是字典'):
            database.ensure_ready()
        self.assertFalse(database.path.exists())
        self.assertFalse(database.marker.exists())
        self.assertEqual(source.read_bytes(), b'[]')


if __name__ == '__main__':
    unittest.main()
