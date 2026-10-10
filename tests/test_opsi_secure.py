"""统计存储的明文读写、旧加密数据自动解密与故障隔离测试；全部数据位于临时目录。"""

import base64
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from Crypto.Cipher import AES, ChaCha20_Poly1305

from module.statistics.opsi_keys import KeyProvider, ProviderUnavailable
from module.statistics import opsi_secure

NOW = 1_800_000_000.0
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'opsi_encrypted_env'


@contextmanager
def db(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        yield conn


def make_cl1_db(path):
    """构造旧版明文 cl1 库（含大世界战斗数据与委托、科研等非大世界字段）。"""
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE cl1_data (instance TEXT, month TEXT, data_json TEXT, '
        'encrypted_blob BLOB, PRIMARY KEY (instance, month))'
    )
    data = {
        'battle_count': 120,
        'akashi_encounters': 3,
        'akashi_ap': 60,
        'akashi_ap_entries': [{'ts': '2026-09-01T10:00:00', 'amount': 20, 'base': 10, 'count': 2, 'source': 'cl1'}],
        'ap_snapshots': [{'ts': '2026-09-01T10:00:00', 'ap': 131, 'asset': 7500.5, 'source': 'cl1'}],
        'last_ap_notification': {'ts': '2026-09-01T10:00:00', 'ap': 131},
        'yellow_coin_snapshots': [{'ts': '2026-09-01T10:00:00', 'yellow_coin': 500, 'source': 'cl1'}],
        'coins_snapshots': [{'ts': '2026-09-01T10:00:00', 'yellow_coins': 500, 'purple_coins': 20, 'source': 'cl1'}],
        'coins_history_version': 2,
        'coins_cleanup_version': 1,
        'meow_battle_raw_count': 10,
        'meow_battle_count': 5.0,
        'meow_round_times': [{'duration': 60.5, 'hazard_level': 3}],
        'meow_battle_times': [20.5],
        'meow_hazard_stats': {'3': {'battle_raw_count': 4, 'effective_rounds': 2.0, 'round_times': [60.0], 'battle_times': [20.0]}},
        'siren_research_devices': {'cl1': 2, 'meow': {'3': 1}},
        'siren_research_device_entries': [{'ts': '2026-09-01T10:00:00', 'source': 'cl1', 'hazard_level': None}],
        'commission_income_entries': [{'ts': '2026-09-01T09:00:00', 'items': {'Gem': 5}, 'commission_count': 1, 'screenshots': []}],
        'research_drop_entries': [{'ts': '2026-09-01T09:00:00', 'project': 'D-737-MI', 'series': 9, 'items': {'Blueprint': 1}, 'imgid': 'x'}],
        'gem_commission_entries': [],
        'running_gem_commissions': [],
    }
    conn.execute(
        'INSERT INTO cl1_data VALUES (?, ?, ?, NULL)',
        ('inst', '2026-09', json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return data


class MemoryProvider(KeyProvider):
    name = 'isolated-test'

    def __init__(self):
        self.states = {}
        self.offline = False

    def load(self, slot):
        if self.offline:
            raise ProviderUnavailable('offline')
        return json.loads(json.dumps(self.states[slot])) if slot in self.states else None

    def save(self, slot, state):
        if self.offline:
            raise ProviderUnavailable('offline')
        self.states[slot] = json.loads(json.dumps(state))

    def delete(self, slot):
        self.states.pop(slot, None)


def legacy_ring(root, key, wrap=lambda x: x):
    directory = root / 'config' / 'opsi_secure'
    directory.mkdir(parents=True, exist_ok=True)
    ring = {'version': 1, 'wrapped_local': base64.b64encode(wrap(key)).decode(),
            'manifest': {'files': {'obsolete-code-path': 'obsolete-code-hash'}}, 'created': 'old', 'updated': 'old'}
    ring['mac'] = hmac.new(opsi_secure._subkey(key, 'opsi-stats/v1/keyring-mac'),
                           opsi_secure.canonical(ring), hashlib.sha256).hexdigest()
    (directory / 'keyring.json').write_bytes(opsi_secure.canonical(ring))
    return ring


def legacy_blob(key, kind, data):
    cipher = AES.new(opsi_secure._subkey(key, 'opsi-stats/v1/' + kind), AES.MODE_GCM,
                     nonce=os.urandom(12))
    cipher.update(('opsi-stats/v1/' + kind).encode())
    raw, tag = cipher.encrypt_and_digest(opsi_secure.canonical(data))
    return opsi_secure.LEGACY_PREFIX + base64.b64encode(cipher.nonce + raw + tag).decode()


def seal_v2(key, kind, obj, context, installation_id):
    """测试侧的 V2 封装：与已删除的写入器同格式（冻结的旧世界格式）。"""
    aad = dict(context, schema=2, algorithm=opsi_secure.ALGORITHM, installation_id=installation_id)
    cipher = ChaCha20_Poly1305.new(key=opsi_secure._subkey(key, 'opsi-stats/v2/' + kind), nonce=os.urandom(24))
    cipher.update(opsi_secure.canonical(aad))
    raw, tag = cipher.encrypt_and_digest(opsi_secure.canonical(obj))
    return opsi_secure.BLOB_PREFIX + base64.b64encode(cipher.nonce + raw + tag).decode()


def complete_file_fixture(root):
    """运行目录下生成旧格式文件夹具，避免把 log/ 运行数据加入仓库。"""
    state = json.loads((root / 'config' / 'opsi_secure' / 'state.json').read_bytes())['state']
    key = base64.b64decode(state['key'])
    installation = state['installation_id']
    records = {
        'log/cl1/alpha/ship_exp_data.json': ('ships', {'battle_times': [22.1, 24.5]}),
        'log/cl1/alpha/cl1_monthly.json': ('archives', {'2026-08': 96, '2026-08-akashi': 2}),
        'log/azurstat_meowofficer_farming.csv': ('loot', {'rows': [[level, 1800000000, 1, 20, 2, 0, 0] for level in range(1, 7)], 'header': ['hazard', 'timestamp', 'rounds', 'coin', 'plate', 'abyssal', 'obscure']}),
    }
    for name, (kind, data) in records.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = seal_v2(key, kind, data, opsi_secure.file_context(root, kind, path), installation)
        value = blob if kind == 'loot' else json.dumps({opsi_secure.WRAPPER_KEY: True, 'payload': blob})
        path.write_text(value, encoding='utf-8')
        if kind != 'loot':
            path.with_name(path.name + '.bak').write_text(value, encoding='utf-8')


def copy_fixture(case):
    directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    case.addCleanup(directory.cleanup)
    root = Path(directory.name) / 'env'
    shutil.copytree(FIXTURE, root)
    complete_file_fixture(root)
    return root


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.install_root(self.root)
        self.dpapi_patch = patch.object(opsi_secure, '_dpapi', side_effect=lambda x, decrypt=False: x)
        self.dpapi_patch.start()
        self.addCleanup(self.dpapi_patch.stop)

    def install_root(self, root):
        (root / 'config').mkdir(exist_ok=True)
        self.previous = opsi_secure._STORE
        opsi_secure.set_store(opsi_secure.StatsStore(root))
        self.addCleanup(opsi_secure.set_store, self.previous)


class PlaintextCodecTests(StoreCase):
    def test_decode_record_reads_plain_json_dicts_only(self):
        self.assertEqual(opsi_secure.decode_record('cl1', '{"a": 1, "b": [2]}'), {'a': 1, 'b': [2]})
        self.assertIsNone(opsi_secure.decode_record('cl1', 'not json'))
        self.assertIsNone(opsi_secure.decode_record('cl1', '[1, 2]'))
        self.assertIsNone(opsi_secure.decode_record('cl1', ''))
        self.assertIsNone(opsi_secure.decode_record('cl1', None))

    def test_decode_text_passthrough(self):
        self.assertEqual(opsi_secure.decode_text('今天的日报正文'), '今天的日报正文')
        self.assertIsNone(opsi_secure.decode_text(''))

    def test_serialize_roundtrip(self):
        payload = {'b': 2, 'a': [1, {'c': '中文'}]}
        self.assertEqual(opsi_secure.decode_record('x', opsi_secure.serialize_obj(payload)), payload)

    def test_missing_key_ciphertext_is_none_and_data_preserved(self):
        blob = opsi_secure.BLOB_PREFIX + base64.b64encode(b'x' * 60).decode()
        self.assertIsNone(opsi_secure.decode_record('cl1', blob, {'dataset': 'cl1'}))
        self.assertIsNone(opsi_secure.decode_text(blob, {'dataset': 'reports'}))

    def test_immediate_transaction_commits_and_rolls_back(self):
        path = self.root / 'config' / 'tx.db'
        with db(path) as conn:
            conn.execute('CREATE TABLE t (v INTEGER)')
        with closing(sqlite3.connect(path)) as conn:
            with opsi_secure.immediate_transaction(conn):
                conn.execute('INSERT INTO t VALUES (1)')
        with closing(sqlite3.connect(path)) as conn:
            with self.assertRaises(RuntimeError):
                with opsi_secure.immediate_transaction(conn):
                    conn.execute('INSERT INTO t VALUES (2)')
                    raise RuntimeError('boom')
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute('SELECT v FROM t').fetchall(), [(1,)])

    def test_durable_write_is_atomic_and_cleans_staging(self):
        path = self.root / 'log' / 'azurstat_meowofficer_farming.csv'
        opsi_secure.write_file('loot', path, 'a,b\n1,2\n')
        self.assertEqual(path.read_text(encoding='utf-8'), 'a,b\n1,2\n')
        with patch.object(opsi_secure.os, 'replace', side_effect=OSError('busy')):
            with self.assertRaises(OSError):
                opsi_secure.write_file('loot', path, 'changed')
        self.assertEqual(path.read_text(encoding='utf-8'), 'a,b\n1,2\n')
        self.assertEqual(list(path.parent.glob('*.stage')), [])


class FixtureMigrationTests(StoreCase):
    """用旧写入器生成的密文部署快照验证一次性解密。"""

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.root)
        shutil.copytree(FIXTURE, self.root)
        complete_file_fixture(self.root)

    def secure(self, instance='alpha', month='2026-09'):
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as conn:
            return conn.execute('SELECT secure_json FROM cl1_data WHERE instance=? AND month=?',
                                (instance, month)).fetchone()[0]

    def test_decrypt_all_converts_every_known_location(self):
        result = opsi_secure.decrypt_all()
        self.assertEqual(result, {'pending': False, 'decrypted': 15, 'quarantined': 0})
        secure = json.loads(self.secure())
        self.assertEqual(secure['battle_count'], 128)
        self.assertEqual(secure['siren_research_devices'], {'cl1': 2, 'meow': {'5': 1}})
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as conn:
            objects = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")}
            self.assertFalse({name for name in objects if name.startswith('__opsi_')})
        with closing(sqlite3.connect(self.root / 'config' / 'azurstats_local.db')) as conn:
            loot = json.loads(conn.execute(
                "SELECT secure_payload FROM opsi_items WHERE imgid='1790123456789'").fetchone()[0])
            self.assertEqual((loot['item'], loot['amount'], loot['hazard_level']), ('PlateT4', 2, 6))
            res = json.loads(conn.execute('SELECT opsi_payload FROM resource_snapshots').fetchone()[0])
            self.assertEqual((res['action_point'], res['purple_coin']), (233, 41))
        with closing(sqlite3.connect(self.root / 'config' / 'daily_summary.db')) as conn:
            event = json.loads(conn.execute(
                'SELECT secure_payload FROM daily_summary_cl1_events ORDER BY id LIMIT 1').fetchone()[0])
            self.assertEqual((event['duration_seconds'], event['estimated_exp']), (24.5, 312))
            report = conn.execute(
                "SELECT report_text FROM daily_summary_periods WHERE period_key='2026-09-03'").fetchone()[0]
            self.assertEqual(report, '今日完成委托 12 次，获得钻石 20。')
        ships = json.loads((self.root / 'log' / 'cl1' / 'alpha' / 'ship_exp_data.json').read_text(encoding='utf-8'))
        self.assertEqual(ships['battle_times'], [22.1, 24.5])
        # `.bak` 是主文件的字节拷贝，按主文件身份解密。
        backup_ships = json.loads(
            (self.root / 'log' / 'cl1' / 'alpha' / 'ship_exp_data.json.bak').read_text(encoding='utf-8'))
        self.assertEqual(backup_ships, ships)
        monthly = json.loads((self.root / 'log' / 'cl1' / 'alpha' / 'cl1_monthly.json').read_text(encoding='utf-8'))
        self.assertEqual(monthly, {'2026-08': 96, '2026-08-akashi': 2})
        csv_text = (self.root / 'log' / 'azurstat_meowofficer_farming.csv').read_text(encoding='utf-8')
        self.assertTrue(csv_text.startswith('hazard,timestamp'))
        # 备份目录：归档库变为真实数据库且内部行已解密，描述文件副本为明文 json。
        archived = self.root / 'AzurPilot_Data_Backup' / '2026-10-04'
        self.assertEqual((archived / 'cl1_data.db').read_bytes()[:16], b'SQLite format 3\x00')
        with closing(sqlite3.connect(archived / 'cl1_data.db')) as conn:
            self.assertEqual(json.loads(conn.execute(
                "SELECT secure_json FROM cl1_data WHERE instance='alpha'").fetchone()[0])['battle_count'], 128)
            self.assertFalse({row[0] for row in conn.execute("SELECT name FROM sqlite_master")
                              if row[0].startswith('__opsi_')})
        ring = json.loads((archived / 'opsi_secure' / 'keyring.json').read_text(encoding='utf-8'))
        self.assertEqual(ring['provider'], 'container-file')
        # 收尾：描述文件与本机状态移除，二跑为空操作。
        self.assertFalse((self.root / 'config' / 'opsi_secure' / 'keyring.json').exists())
        self.assertFalse((self.root / 'config' / 'opsi_secure' / 'state.json').exists())
        self.assertEqual(opsi_secure.pending_blobs(self.root), [])
        self.assertEqual(opsi_secure.decrypt_all(), {'pending': False, 'decrypted': 0, 'quarantined': 0})

    def test_migrated_data_readable_by_consumers(self):
        self.assertFalse(opsi_secure.decrypt_all()['pending'])
        from module.statistics.cl1_database import Cl1Database
        database = Cl1Database(self.root / 'config' / 'cl1_data.db')
        stats = database.get_stats('alpha', '2026-09')
        self.assertEqual(stats['battle_count'], 128)
        self.assertEqual(stats['meow_battle_count'], 22.0)
        self.assertNotIn(opsi_secure.MISSING_MARKER, stats)
        database.increment_battle_count('alpha')
        from datetime import datetime
        month = datetime.now().strftime('%Y-%m')
        with database.store.transaction(write=False) as conn:
            raw = conn.execute("SELECT battle_count FROM cl1_months WHERE instance='alpha' AND month=?", (month,)).fetchone()[0]
        self.assertEqual(raw, 1)
        from module.statistics.daily_summary_store import DailySummaryStore
        store = DailySummaryStore(self.root / 'config' / 'daily_summary.db')
        self.assertEqual(store.get_period('alpha', '2026-09-03')['report_text'],
                         '今日完成委托 12 次，获得钻石 20。')
        from module.statistics.ship_exp_stats import ShipExpStats
        ships = ShipExpStats(path=self.root / 'log' / 'cl1' / 'alpha' / 'ship_exp_data.json', instance_name='alpha')
        self.assertEqual(ships.data['battle_times'], [22.1, 24.5])

    def test_missing_key_keeps_everything_untouched_until_recovered(self):
        state = self.root / 'config' / 'opsi_secure' / 'state.json'
        blob_before = self.secure()
        state.rename(state.with_name('state.json.moved'))
        self.assertEqual(opsi_secure.decrypt_all(), {'pending': True, 'decrypted': 0, 'quarantined': 0})
        self.assertTrue((self.root / 'config' / 'opsi_secure' / 'keyring.json').exists())
        self.assertEqual(self.secure(), blob_before)
        state.with_name('state.json.moved').rename(state)
        self.assertFalse(opsi_secure.decrypt_all()['pending'])

    def test_unsupported_provider_keeps_ciphertext(self):
        ring_path = self.root / 'config' / 'opsi_secure' / 'keyring.json'
        ring = json.loads(ring_path.read_bytes())
        ring['provider'] = 'host-broker'
        ring_path.write_bytes(json.dumps(ring).encode())
        self.assertEqual(opsi_secure.decrypt_all(), {'pending': True, 'decrypted': 0, 'quarantined': 0})
        self.assertTrue(self.secure().startswith(opsi_secure.BLOB_PREFIX))


class QuarantineTests(StoreCase):
    def setUp(self):
        super().setUp()
        shutil.rmtree(self.root)
        shutil.copytree(FIXTURE, self.root)
        complete_file_fixture(self.root)
        with db(self.root / 'config' / 'cl1_data.db') as conn:
            good = conn.execute("SELECT secure_json FROM cl1_data WHERE instance='beta'").fetchone()[0]
            self.broken = good[:30] + ('A' if good[30] != 'A' else 'B') + good[31:]
            conn.execute("UPDATE cl1_data SET secure_json=? WHERE instance='beta'", (self.broken,))

    def test_undecryptable_row_is_kept_and_blocks_cleanup(self):
        result = opsi_secure.decrypt_all()
        self.assertEqual(result, {'pending': True, 'decrypted': 14, 'quarantined': 1})
        self.assertTrue((self.root / 'config' / 'opsi_secure' / 'keyring.json').exists())
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as conn:
            self.assertEqual(conn.execute(
                "SELECT secure_json FROM cl1_data WHERE instance='beta'").fetchone()[0], self.broken)
            self.assertEqual(json.loads(conn.execute(
                "SELECT secure_json FROM cl1_data WHERE instance='alpha'").fetchone()[0])['battle_count'], 128)
        # 再跑一次：好行不再重复解密，坏行仍被隔离。
        self.assertEqual(opsi_secure.decrypt_all(), {'pending': True, 'decrypted': 0, 'quarantined': 1})

    def test_unrecoverable_row_is_backed_up_and_stats_resume(self):
        """不可解码的旧记录保留并跳过，其余记录及后续统计正常写入。"""
        from module.statistics.cl1_database import Cl1Database
        database = Cl1Database(self.root / 'config' / 'cl1_data.db')
        original = (self.root / 'config' / 'cl1_data.db').read_bytes()
        database.store.ensure_ready()
        from module.persistence.snapshots import read_month
        with database.store.transaction(write=False) as connection:
            self.assertIsNone(read_month(connection, 'beta', '2026-09'))
            self.assertEqual(read_month(connection, 'alpha', '2026-09')['battle_count'], 128)
        database.increment_akashi_encounter('beta', '2026-09')
        self.assertEqual(database.get_stats('beta', '2026-09')['akashi_encounters'], 1)
        self.assertTrue(database.db_path.exists())
        self.assertEqual((self.root / 'config' / 'cl1_data.db').read_bytes(), original)
        self.assertTrue(list((self.root / 'config' / 'storage-backups').glob('*/sources.json')))
        self.assertTrue(list((self.root / 'config' / 'storage-backups').glob('*/unmigrated.json')))
        self.assertTrue((self.root / 'config' / 'opsi_secure' / 'keyring.json').exists())

    def test_transient_key_outage_keeps_original_row(self):
        """旧密钥暂不可用只跳过旧记录；原件与恢复材料保持原样。"""
        from module.statistics import opsi_keys
        from module.statistics.cl1_database import Cl1Database
        database = Cl1Database(self.root / 'config' / 'cl1_data.db')
        with patch.object(opsi_keys.ContainerFileProvider, 'load',
                          side_effect=opsi_keys.ProviderUnavailable('locked')):
            database.increment_akashi_encounter('beta', '2026-09')
        self.assertEqual(database.get_stats('beta', '2026-09')['akashi_encounters'], 1)
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as conn:
            self.assertEqual(conn.execute(
                "SELECT secure_json FROM cl1_data WHERE instance='beta'").fetchone()[0], self.broken)
        self.assertEqual(list((self.root / 'config' / 'opsi_secure').glob('unreadable-*.json')), [])


class V1MigrationTests(StoreCase):
    def setUp(self):
        super().setUp()
        self.key = os.urandom(32)
        self.full = make_cl1_db(self.root / 'config' / 'cl1_data.db')
        (self.root / 'log' / 'cl1' / 'inst').mkdir(parents=True)
        legacy_ring(self.root, self.key)
        secure = {key: value for key, value in self.full.items() if key in opsi_secure.CL1_SECURE_FIELDS}
        public = {key: value for key, value in self.full.items() if key not in opsi_secure.CL1_SECURE_FIELDS}
        with db(self.root / 'config' / 'cl1_data.db') as conn:
            conn.execute('ALTER TABLE cl1_data ADD COLUMN secure_json TEXT')
            conn.execute('UPDATE cl1_data SET data_json=?, secure_json=?',
                         (json.dumps(public), legacy_blob(self.key, 'cl1', secure)))
        self.csv = self.root / 'log' / 'azurstat_meowofficer_farming.csv'
        self.csv.write_text(legacy_blob(self.key, 'loot', {'header': ['hazard', 'timestamp', 'rounds', 'coin', 'plate', 'abyssal', 'obscure'], 'rows': [[level, 2, 1, 0, 0, 0, 0] for level in range(1, 7)]}),
                            encoding='utf-8')

    def test_v1_environment_decrypts_to_plaintext(self):
        result = opsi_secure.decrypt_all()
        self.assertEqual(result, {'pending': False, 'decrypted': 2, 'quarantined': 0})
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as conn:
            secure = json.loads(conn.execute('SELECT secure_json FROM cl1_data').fetchone()[0])
        self.assertEqual(secure['battle_count'], 120)
        self.assertEqual(self.csv.read_text(encoding='utf-8'), 'hazard,timestamp,rounds,coin,plate,abyssal,obscure\n' + ''.join(f'{level},2,1,0,0,0,0\n' for level in range(1, 7)))
        self.assertFalse((self.root / 'config' / 'opsi_secure' / 'keyring.json').exists())

    def test_v1_blob_read_before_migration(self):
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as conn:
            blob = conn.execute('SELECT secure_json FROM cl1_data').fetchone()[0]
        from module.statistics.cl1_database import Cl1Database
        database = Cl1Database(self.root / 'config' / 'cl1_data.db')
        data = database.get_stats('inst', '2026-09')
        self.assertEqual(data['battle_count'], 120)
        self.assertEqual(len(data['coins_snapshots']), 1)
        # 读取路径不整库改写；迁移仍需显式执行。
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as conn:
            self.assertEqual(conn.execute('SELECT secure_json FROM cl1_data').fetchone()[0], blob)

    def test_v1_row_with_wrong_mac_stays_quarantined(self):
        ring_path = self.root / 'config' / 'opsi_secure' / 'keyring.json'
        ring = json.loads(ring_path.read_bytes())
        ring['mac'] = 'f' * 64
        ring_path.write_bytes(json.dumps(ring).encode())
        result = opsi_secure.decrypt_all()
        self.assertTrue(result['pending'])
        self.assertTrue((self.root / 'config' / 'opsi_secure' / 'keyring.json').exists())


class WrapperTransitionTests(StoreCase):
    def test_decode_file_payload_unwraps_dict_and_plain(self):
        path = self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json'
        self.assertEqual(opsi_secure.decode_file_payload('ships', path, {'a': 1}), {'a': 1})
        wrapper = {opsi_secure.WRAPPER_KEY: True, 'payload': {'b': 2}}
        self.assertEqual(opsi_secure.decode_file_payload('ships', path, wrapper), {'b': 2})
        blob_wrapper = {opsi_secure.LEGACY_WRAPPER_KEY: True,
                        'payload': opsi_secure.BLOB_PREFIX + base64.b64encode(b'x' * 60).decode()}
        self.assertIsNone(opsi_secure.decode_file_payload('ships', path, blob_wrapper))
        self.assertIsNone(opsi_secure.decode_file_payload('ships', path, None))

    def test_ship_stats_backs_up_undecryptable_wrapper_and_restarts(self):
        from module.statistics.ship_exp_stats import ShipExpStats
        path = self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json'
        path.parent.mkdir(parents=True)
        blob = opsi_secure.BLOB_PREFIX + base64.b64encode(b'x' * 60).decode()
        path.write_bytes(json.dumps({opsi_secure.WRAPPER_KEY: True, 'payload': blob}).encode())
        original = path.read_bytes()
        stats = ShipExpStats(path=path, instance_name='inst')
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue((self.root / 'config' / 'azurpilot.db').exists())
        from module.persistence.snapshots import read_ship
        with stats.store.transaction(write=False) as connection:
            self.assertIsNone(read_ship(connection, 'inst'))
        self.assertTrue(list((self.root / 'config' / 'storage-backups').glob('*/sources.json')))
        self.assertTrue(list((self.root / 'config' / 'storage-backups').glob('*/unmigrated.json')))


class InitializeTests(StoreCase):
    def setUp(self):
        super().setUp()
        self.previous_done = opsi_secure._INIT_DONE
        opsi_secure._INIT_DONE = None
        self.addCleanup(self.restore_done)

    def restore_done(self):
        opsi_secure._INIT_DONE = self.previous_done

    def test_fresh_environment_reports_ready_without_side_effects(self):
        self.assertTrue(opsi_secure.initialize(timeout=10))
        self.assertEqual(sorted(path.name for path in (self.root / 'config').iterdir()), [])

    def test_slow_decryption_is_bounded_and_continues_in_background(self):
        release = threading.Event()
        calls = []

        def slow():
            calls.append(1)
            release.wait(10)
            return {'pending': False, 'decrypted': 0, 'quarantined': 0}

        with patch.object(opsi_secure, 'decrypt_all', side_effect=slow):
            started = time.monotonic()
            self.assertFalse(opsi_secure.initialize(timeout=0.2))
            self.assertLess(time.monotonic() - started, 5)
            self.assertTrue(calls)
        release.set()


if __name__ == '__main__':
    unittest.main()
