"""总库首次转换与恢复验证，所有旧源、密钥和安全材料均为临时夹具。"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from Crypto.Cipher import AES

from module.persistence.database import BusinessDatabase
from module.persistence.migration import MigrationError, assert_no_workers
from module.persistence.snapshots import read_month, read_ship, save_month
from module.scheduler.store import ProgramStore, ConflictError
from module.statistics import opsi_secure
from tests.opsi_test_support import install_store
from tests.test_opsi_secure import copy_fixture, legacy_blob, legacy_ring, seal_v2


class MigrationProcessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.interpreter = self.root / '.venv' / 'Scripts' / 'python.exe'
        self.base_interpreter = self.root / 'python' / 'python.exe'

    def process(self, pid, executable, arguments, *, cwd=None):
        command = [str(executable), *arguments]
        process = Mock()
        process.pid = pid
        process.info = {'pid': pid, 'cmdline': command}
        process.cmdline.return_value = command
        process.exe.return_value = str(executable)
        process.cwd.return_value = str(cwd or self.root)
        process.parents.return_value = []
        return process

    def scan(self, current, processes):
        with patch('psutil.Process', return_value=current), \
                patch('psutil.process_iter', return_value=processes), \
                patch('module.persistence.migration.sys.platform', 'win32'), \
                patch('module.persistence.migration.sys.executable', str(self.interpreter)):
            assert_no_workers(self.root)

    def test_uv_and_windows_redirector_do_not_block_current_entry(self):
        for entry in ('gui.py', 'alas.py', 'tui.py', 'mcp_server_sse.py'):
            for explicit_python in (False, True):
                with self.subTest(entry=entry, explicit_python=explicit_python):
                    current = self.process(os.getpid(), self.base_interpreter, [entry])
                    redirector = self.process(1000001, self.interpreter, [entry])
                    uv = self.process(1000002, self.root / 'uv.exe',
                                      ['run', *(['python'] if explicit_python else []), entry])
                    shell = self.process(1000003, self.root / 'powershell.exe', [])
                    current.parents.return_value = [redirector, uv, shell]
                    self.scan(current, [uv, redirector, current, shell])

    def test_another_entry_still_blocks_with_the_same_command(self):
        current = self.process(os.getpid(), self.base_interpreter, ['gui.py'])
        redirector = self.process(1000001, self.interpreter, ['gui.py'])
        old = self.process(1000002, self.base_interpreter, ['gui.py'])
        current.parents.return_value = [redirector]
        with self.assertRaisesRegex(MigrationError, 'PID 1000002'):
            self.scan(current, [redirector, old])

    def test_python_ancestor_running_an_entry_is_not_exempt(self):
        current = self.process(os.getpid(), self.base_interpreter, ['gui.py'])
        parent = self.process(1000001, self.base_interpreter, ['gui.py'])
        current.parents.return_value = [parent]
        with self.assertRaisesRegex(MigrationError, 'PID 1000001'):
            self.scan(current, [parent])

    def test_matching_interpreter_with_different_arguments_is_not_a_redirector(self):
        current = self.process(os.getpid(), self.base_interpreter, ['gui.py'])
        parent = self.process(1000001, self.interpreter, ['alas.py'])
        current.parents.return_value = [parent]
        with self.assertRaisesRegex(MigrationError, 'PID 1000001'):
            self.scan(current, [parent])

    def test_registered_worker_is_checked_before_launcher_exemptions(self):
        current = self.process(os.getpid(), self.base_interpreter, ['gui.py'])
        redirector = self.process(1000001, self.interpreter, ['gui.py'])
        current.parents.return_value = [redirector]
        registry = self.root / 'cache' / 'webui-workers.json'
        registry.parent.mkdir()
        registry.write_text(json.dumps({'workers': {'inst': {'pid': redirector.pid}}}), encoding='utf-8')
        with patch('module.runtime.process_control.process_matches', return_value=True):
            with self.assertRaisesRegex(MigrationError, '旧业务 worker.*PID 1000001'):
                self.scan(current, [redirector])

    def test_unverified_parent_is_not_exempt(self):
        import psutil
        current = self.process(os.getpid(), self.base_interpreter, ['gui.py'])
        parent = self.process(1000001, self.interpreter, ['gui.py'])
        parent.exe.side_effect = psutil.AccessDenied(parent.pid)
        current.parents.return_value = [parent]
        with self.assertRaisesRegex(MigrationError, 'PID 1000001'):
            self.scan(current, [parent])

    def test_entry_from_another_installation_does_not_block(self):
        current = self.process(os.getpid(), self.base_interpreter, ['gui.py'])
        other = self.process(1000001, self.base_interpreter, ['gui.py'], cwd=self.root / 'other')
        self.scan(current, [other])

    def test_uv_startup_migrates_temp_data_with_both_command_forms(self):
        from module.statistics.cl1_legacy import derive_legacy_key
        uv = shutil.which('uv')
        if uv is None:
            self.skipTest('未安装 uv，无法验证实际启动链')
        project = Path(__file__).resolve().parents[1]
        script = (
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(project)!r})\n"
            "from module.persistence.database import initialize\n"
            "database = initialize(Path(__file__).parent / 'config')\n"
            "print('migration-ready')\n"
        )
        for arguments in (['gui.py'], ['python', 'gui.py']):
            with self.subTest(arguments=arguments):
                root = self.root / ('direct' if len(arguments) == 1 else 'python')
                config = root / 'config'
                config.mkdir(parents=True)
                (root / 'gui.py').write_text(script, encoding='utf-8')
                source = config / 'cl1_data.db'
                cipher = AES.new(derive_legacy_key('unavailable-fixture-device'), AES.MODE_GCM)
                encrypted, tag = cipher.encrypt_and_digest(b'{"battle_count":9}')
                with closing(sqlite3.connect(source)) as connection, connection:
                    connection.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT,encrypted_blob BLOB)')
                    connection.execute('INSERT INTO cl1_data VALUES(?,?,?,NULL)',
                                       ('inst', '2026-09', '{"battle_count":7}'))
                    connection.execute('INSERT INTO cl1_data VALUES(?,?,NULL,?)',
                                       ('inst', '2026-03', cipher.nonce + tag + encrypted))
                original = source.read_bytes()
                result = subprocess.run([uv, 'run', '--no-sync', '--project', str(project), *arguments],
                                        cwd=root, capture_output=True, encoding='utf-8', errors='replace', timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('migration-ready', result.stdout)
                self.assertIn('[存储迁移]', result.stdout)
                self.assertIn('总库已就绪', result.stdout)
                self.assertTrue((config / 'azurpilot.migrated').is_file())
                self.assertEqual(source.read_bytes(), original)
                report = json.loads(next((config / 'storage-backups').glob('*/unmigrated.json')).read_text(encoding='utf-8'))
                self.assertEqual(report[0]['identity'], {'instance': 'inst', 'month': '2026-03'})
                with closing(sqlite3.connect(config / 'azurpilot.db')) as connection:
                    self.assertEqual(connection.execute('SELECT battle_count FROM cl1_months').fetchone()[0], 7)
                    self.assertIsNone(read_month(connection, 'inst', '2026-03'))
                    self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
                    self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.config = self.root / 'config'
        self.config.mkdir()
        self.store = install_store(self, self.root)
        self.database = BusinessDatabase(self.config)

    def old_cl1(self, data):
        path = self.config / 'cl1_data.db'
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT,secure_json TEXT,encrypted_blob BLOB)')
            connection.execute('INSERT INTO cl1_data VALUES(?,?,?,NULL,NULL)', ('inst', '2026-09', json.dumps(data)))
        return path

    def encrypted_cl1(self, data, device_id):
        from module.statistics.cl1_legacy import derive_legacy_key
        source = self.old_cl1({})
        cipher = AES.new(derive_legacy_key(device_id), AES.MODE_GCM)
        encrypted, tag = cipher.encrypt_and_digest(json.dumps(data).encode('utf-8'))
        blob = cipher.nonce + tag + encrypted
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute('UPDATE cl1_data SET data_json=NULL,encrypted_blob=?', (blob,))
        return source

    def test_migration_logs_stages_and_existing_database_without_snapshot_contents(self):
        sensitive_value = 'private-snapshot-fixture'
        self.old_cl1({'extra': sensitive_value})
        with self.assertLogs('alas', level='INFO') as captured:
            self.database.ensure_ready()
        messages = '\n'.join(captured.output)
        stages = ('等待总库初始化锁', '首次初始化总库', '检查旧运行入口',
                  '[备份 1/1]', '[转换 1/1]', '开始处理表 cl1_data：共 1 条',
                  '表 cl1_data 处理完成', '检查临时总库的外键与完整性',
                  '切换正式总库', '迁移完成', '总库已就绪')
        positions = [messages.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(sensitive_value, messages)
        self.assertIn('耗时', messages)
        with self.assertLogs('alas', level='INFO') as captured:
            BusinessDatabase(self.config).ensure_ready()
        self.assertIn('已完成迁移，无需再次解密旧数据', '\n'.join(captured.output))
        with self.assertNoLogs('alas', level='INFO'):
            self.database.ensure_ready()

    def test_waiting_for_install_lock_is_logged_before_acquiring_it(self):
        with self.assertLogs('alas', level='INFO') as captured:
            with patch('module.persistence.database.config_transaction', side_effect=TimeoutError('fixture lock')):
                with self.assertRaises(TimeoutError):
                    self.database.ensure_ready()
        self.assertIn('等待总库初始化锁', '\n'.join(captured.output))
        self.assertFalse(self.database.path.exists())

    def test_large_table_reports_progress_without_logging_values(self):
        from module.persistence.migration import _source_rows
        with closing(sqlite3.connect(':memory:')) as source:
            source.execute('CREATE TABLE records(value TEXT)')
            source.executemany('INSERT INTO records VALUES(?)', [('private-row-fixture',)] * 3)
            with self.assertLogs('alas', level='INFO') as captured, \
                    patch('module.persistence.migration.time.perf_counter', side_effect=[0, 2, 2.5, 5, 5]):
                rows = list(_source_rows(source, 'records', 'SELECT * FROM records'))
        self.assertEqual(len(rows), 3)
        messages = '\n'.join(captured.output)
        self.assertIn('已处理 1/3 条', messages)
        self.assertNotIn('已处理 2/3 条', messages)
        self.assertIn('已处理 3/3 条', messages)
        self.assertIn('处理完成：3 条', messages)
        self.assertNotIn('private-row-fixture', messages)

    def test_unreadable_snapshot_files_are_backed_up_and_skipped_without_empty_projections(self):
        cases = (b'', b' \r\n\t', b'{"private":', b'\xff\xfeinvalid',
                 b'{"__opsi_secure_v2__":true}',
                 b'{"__opsi_secure_v1__":true,"payload":"broken"}')
        for index, raw in enumerate(cases):
            for kind, filename in (('ships', 'ship_exp_data.json'), ('archives', 'cl1_monthly.json')):
                with self.subTest(index=index, kind=kind):
                    root = self.root / f'{kind}-{index}'
                    root.mkdir()
                    install_store(self, root)
                    database = BusinessDatabase(root / 'config')
                    source = root / 'log' / 'cl1' / 'broken' / filename
                    source.parent.mkdir(parents=True)
                    source.write_bytes(raw)
                    valid = root / 'log' / 'cl1' / 'readable' / filename
                    valid.parent.mkdir()
                    expected = {'target_level': 120} if kind == 'ships' else {'2026-09': {'battle_count': 7}}
                    valid.write_text(json.dumps(expected), encoding='utf-8')
                    with self.assertLogs('alas', level='INFO') as captured:
                        database.ensure_ready()
                    self.assertEqual(source.read_bytes(), raw)
                    backup = next((database.directory / 'storage-backups').iterdir())
                    self.assertEqual((backup / source.relative_to(root)).read_bytes(), raw)
                    report = json.loads((backup / 'unmigrated.json').read_text(encoding='utf-8'))
                    self.assertEqual(len(report), 1)
                    self.assertEqual(report[0]['kind'], kind)
                    self.assertEqual(report[0]['identity'], {'file': filename})
                    messages = '\n'.join(captured.output)
                    self.assertIn('跳过不可读旧快照文件', messages)
                    self.assertIn('迁移完成', messages)
                    self.assertNotIn('"private":', messages)
                    with database.transaction(write=False) as connection:
                        if kind == 'ships':
                            self.assertIsNone(read_ship(connection, 'broken'))
                            self.assertEqual(read_ship(connection, 'readable'), expected)
                        else:
                            self.assertIsNone(read_month(connection, 'broken', '2026-09'))
                            self.assertEqual(read_month(connection, 'readable', '2026-09'), expected['2026-09'])
                    with patch('module.persistence.migration.LegacyDecoder.file', side_effect=AssertionError('不能重复导入')):
                        BusinessDatabase(database.directory).ensure_ready()

    def test_snapshot_file_supports_bom_and_direct_v1_v2_ciphertext_read_only(self):
        from module.persistence.migration import LegacyDecoder
        key = b'x' * 32
        legacy_ring(self.root, key)
        fixture = copy_fixture(self)
        state = json.loads((fixture / 'config' / 'opsi_secure' / 'state.json').read_bytes())['state']
        import base64
        v2_key = base64.b64decode(state['key'])
        for version in ('plain', 'v1', 'v2'):
            for kind, filename in (('ships', 'ship_exp_data.json'), ('archives', 'cl1_monthly.json')):
                for quoted in (False, True):
                    with self.subTest(version=version, kind=kind, quoted=quoted):
                        root = fixture if version == 'v2' else self.root
                        install_store(self, root)
                        source = root / 'log' / 'cl1' / 'direct' / filename
                        source.parent.mkdir(parents=True, exist_ok=True)
                        expected = {'keep': [None, {}, [], 2 ** 80]}
                        if version == 'plain':
                            text = json.dumps(expected)
                        elif version == 'v1':
                            text = legacy_blob(key, kind, expected)
                        else:
                            text = seal_v2(v2_key, kind, expected, opsi_secure.file_context(root, kind, source),
                                           state['installation_id'])
                        if quoted and version != 'plain':
                            text = json.dumps(text)
                        raw = ('\ufeff' + text + '\r\n').encode('utf-8')
                        source.write_bytes(raw)
                        ring = root / 'config' / 'opsi_secure' / ('state.json' if version == 'v2' else 'keyring.json')
                        material = ring.read_bytes()
                        with patch.object(opsi_secure, '_dpapi', side_effect=lambda value, decrypt=False: value), \
                                patch.object(opsi_secure, 'decrypt_all', side_effect=AssertionError('不能改写旧文件')):
                            decoded = LegacyDecoder(root).file(kind, source, source)
                        self.assertEqual(decoded, expected)
                        self.assertEqual(source.read_bytes(), raw)
                        self.assertEqual(ring.read_bytes(), material)
                        self.assertFalse((root / 'config' / 'azurpilot.db').exists())

    def test_unreadable_direct_ciphertext_is_reported_and_other_data_migrates(self):
        self.old_cl1({'battle_count': 7})
        source = self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json'
        source.parent.mkdir(parents=True)
        source.write_text(legacy_blob(b'x' * 32, 'ships', {'target_level': 120}), encoding='utf-8')
        original = source.read_bytes()
        self.database.ensure_ready()
        with self.database.transaction(write=False) as connection:
            self.assertIsNone(read_ship(connection, 'inst'))
            self.assertEqual(read_month(connection, 'inst', '2026-09'), {'battle_count': 7})
        self.assertEqual(source.read_bytes(), original)
        report = json.loads(next((self.config / 'storage-backups').glob('*/unmigrated.json')).read_text(encoding='utf-8'))
        self.assertEqual(report[0]['kind'], 'ships')
        self.assertIn('密文无法解码', report[0]['reason'])

    def test_readable_snapshot_with_invalid_structure_still_blocks_cutover(self):
        source = self.root / 'log' / 'cl1' / 'inst' / 'ship_exp_data.json'
        source.parent.mkdir(parents=True)
        source.write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, '旧文件快照不是字典'):
            self.database.ensure_ready()
        self.assertFalse(self.database.path.exists())
        self.assertEqual(source.read_text(encoding='utf-8'), '[]')

    def test_entire_aes_snapshot_uses_saved_device_id_without_refreshing_it(self):
        expected = {'battle_count': 7, 'commission_income_entries': [{'keep': True}], 'extra': [None, 2 ** 80]}
        source = self.encrypted_cl1(expected, 'old-device')
        identity = self.root / 'log' / 'device_id.json'
        identity.parent.mkdir()
        identity.write_text('{"device_id":"old-device","keep":true}', encoding='utf-8')
        original, material = source.read_bytes(), identity.read_bytes()
        with patch('module.base.device_id.get_device_id', side_effect=AssertionError('不得刷新设备 ID')), \
                patch('module.base.device_id._start_refresh_timer', side_effect=AssertionError('不得启动刷新定时器')), \
                patch('module.base.device_id.generate_device_id', return_value='current-device'):
            self.database.ensure_ready()
        with self.database.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'inst', '2026-09'), expected)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(identity.read_bytes(), material)
        backups = list((self.config / 'storage-backups').iterdir())
        self.assertEqual((backups[0] / 'log' / 'device_id.json').read_bytes(), material)
        self.assertFalse((backups[0] / 'unmigrated.json').exists())

    def test_unreadable_month_is_skipped_and_other_months_migrate_without_source_changes(self):
        source = self.encrypted_cl1({'battle_count': 9}, 'lost-device')
        expected = {'battle_count': 7, 'keep': [None, {}, []]}
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute('INSERT INTO cl1_data VALUES(?,?,?,NULL,NULL)',
                               ('inst', '2026-08', json.dumps(expected)))
        archive = self.root / 'log' / 'cl1' / 'inst' / 'cl1_monthly.json'
        archive.parent.mkdir(parents=True)
        archive.write_text(json.dumps({'2026-09': {'battle_count': 999}, '2026-07': {'battle_count': 2}}), encoding='utf-8')
        identity = self.root / 'log' / 'device_id.json'
        identity.write_text('{"device_id":"current-device"}', encoding='utf-8')
        original, material = source.read_bytes(), identity.read_bytes()
        with self.assertLogs('alas', level='INFO') as captured, \
                patch('module.base.device_id.get_device_id', side_effect=AssertionError('不得刷新设备 ID')), \
                patch('module.base.device_id.generate_device_id', return_value='current-device'):
            self.database.ensure_ready()
        messages = '\n'.join(captured.output)
        self.assertIn('开始解密整行 AES 月度快照', messages)
        self.assertIn('跳过不可读旧密文', messages)
        self.assertIn('已跳过 1 条', messages)
        self.assertIn('unmigrated.json', messages)
        self.assertIn('迁移完成', messages)
        self.assertNotIn('current-device', messages)
        self.assertNotIn('lost-device', messages)
        with self.database.transaction(write=False) as connection:
            self.assertIsNone(read_month(connection, 'inst', '2026-09'))
            self.assertEqual(read_month(connection, 'inst', '2026-08'), expected)
            self.assertEqual(read_month(connection, 'inst', '2026-07'), {'battle_count': 2})
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(identity.read_bytes(), material)
        backup = next((self.config / 'storage-backups').iterdir())
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as source_connection, \
                closing(sqlite3.connect(backup / 'config' / source.name)) as saved_connection:
            self.assertEqual(saved_connection.execute('SELECT * FROM cl1_data').fetchall(),
                             source_connection.execute('SELECT * FROM cl1_data').fetchall())
        report = json.loads((backup / 'unmigrated.json').read_text(encoding='utf-8'))
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]['source'], 'config' + os.sep + 'cl1_data.db')
        self.assertEqual(report[0]['identity'], {'instance': 'inst', 'month': '2026-09'})
        self.assertTrue(self.database.marker.exists())
        with patch('module.persistence.migration.LegacyDecoder.cl1', side_effect=AssertionError('不能重复导入')):
            BusinessDatabase(self.config).ensure_ready()

    def test_duplicate_month_still_blocks_when_first_row_is_unreadable(self):
        source = self.encrypted_cl1({'battle_count': 1}, 'lost-device')
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute("INSERT INTO cl1_data VALUES('inst','2026-09','{}',NULL,NULL)")
        original = source.read_bytes()
        with patch('module.base.device_id.generate_device_id', return_value='current-device'):
            with self.assertRaisesRegex(MigrationError, '重复月份'):
                self.database.ensure_ready()
        self.assertFalse(self.database.path.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_decodable_ciphertext_with_invalid_structure_is_not_silently_skipped(self):
        source = self.encrypted_cl1([], 'current-device')
        original = source.read_bytes()
        with patch('module.base.device_id.generate_device_id', return_value='current-device'):
            with self.assertRaisesRegex(MigrationError, '快照不是有效对象'):
                self.database.ensure_ready()
        self.assertFalse(self.database.path.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_unreadable_drop_row_does_not_prevent_readable_rows_from_migrating(self):
        source = self.config / 'azurstats_local.db'
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute('CREATE TABLE opsi_items(id INTEGER PRIMARY KEY,imgid TEXT,item TEXT,amount INTEGER,secure_payload TEXT)')
            connection.execute('INSERT INTO opsi_items VALUES(19,?,?,?,?)',
                               ('unknown', 'PlateT4', 2, opsi_secure.BLOB_PREFIX + 'unreadable'))
            connection.execute("INSERT INTO opsi_items VALUES(20,'readable','PlateT4',3,NULL)")
        original = source.read_bytes()
        self.database.ensure_ready()
        with self.database.transaction(write=False) as connection:
            self.assertEqual([tuple(row) for row in connection.execute('SELECT id,imgid,amount FROM opsi_items')],
                             [(20, 'readable', 3)])
        self.assertEqual(source.read_bytes(), original)
        report = json.loads(next((self.config / 'storage-backups').glob('*/unmigrated.json')).read_text(encoding='utf-8'))
        self.assertEqual(report[0]['identity'], {'table': 'opsi_items', 'rowid': 19})

    def test_plain_sources_preserve_fields_ids_watermarks_and_database_priority(self):
        expected = {'battle_count': 7, 'commission_income_entries': [{'keep': True}],
                    'last_ap_notification': None, 'unknown': [None, {}, [], 2 ** 80]}
        source = self.old_cl1(expected)
        original = source.read_bytes()
        archive = self.root / 'log' / 'cl1' / 'inst' / 'cl1_monthly.json'
        archive.parent.mkdir(parents=True)
        archive.write_text(json.dumps({'2026-09': 999, '2026-08': {'battle_count': 2}}), encoding='utf-8')
        ships = archive.with_name('ship_exp_data.json')
        ships.write_text('{"target_level": null, "ships": [{"level": 0}], "battle_times": {"average": 17, "samples": [52]}}', encoding='utf-8')
        statistics = self.config / 'azurstats_local.db'
        with closing(sqlite3.connect(statistics)) as connection, connection:
            connection.executescript('''CREATE TABLE resource_flows(id INTEGER PRIMARY KEY, instance TEXT, ts TEXT,
                resource TEXT,amount INTEGER,task TEXT,operation TEXT,evidence TEXT,run_id TEXT,event_key TEXT);
                CREATE TABLE resource_balances(instance TEXT,resource TEXT,value INTEGER,ts TEXT,run_id TEXT,cursor INTEGER);
                CREATE TABLE opsi_items(id INTEGER PRIMARY KEY,imgid TEXT,item TEXT,amount INTEGER);''')
            connection.execute("INSERT INTO resource_flows VALUES(41,'inst','old','Oil',-10,'Task','Buy','confirmed',NULL,'event')")
            connection.execute("INSERT INTO resource_balances VALUES('inst','Oil',100,'old',NULL,41)")
            connection.execute("INSERT INTO opsi_items VALUES(19,'shared-image','PlateT4',2)")
        self.database.ensure_ready()
        with self.database.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'inst', '2026-09'), expected)
            self.assertEqual(read_month(connection, 'inst', '2026-08'), {'battle_count': 2})
            self.assertEqual(read_ship(connection, 'inst')['battle_times'], {'average': 17, 'samples': [52]})
            self.assertEqual(connection.execute('SELECT id FROM resource_flows').fetchone()[0], 41)
            self.assertEqual(connection.execute('SELECT cursor FROM resource_balances').fetchone()[0], 41)
            row = connection.execute('SELECT id,instance FROM opsi_items').fetchone()
            self.assertEqual(tuple(row), (19, None))
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue(self.database.marker.exists())
        self.assertEqual(len(list((self.config / 'storage-backups').glob('*/sources.json'))), 1)

    def test_failed_decode_keeps_sources_and_does_not_switch_then_retries(self):
        path = self.old_cl1({'keep': True})
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE cl1_data SET data_json='broken'")
        original = path.read_bytes()
        with self.assertLogs('alas', level='INFO') as captured:
            with self.assertRaises(MigrationError):
                self.database.ensure_ready()
        messages = '\n'.join(captured.output)
        self.assertIn('阶段未完成：[转换 1/1]', messages)
        self.assertIn('cl1_data.db', messages)
        self.assertIn('原件保留', messages)
        self.assertNotIn('迁移完成：', messages)
        self.assertFalse(self.database.path.exists())
        self.assertFalse(self.database.marker.exists())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.config.glob('azurpilot.*.tmp*')), [])
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('UPDATE cl1_data SET data_json=?', ('{"keep": true}',))
        self.database.ensure_ready()
        with self.database.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'inst', '2026-09'), {'keep': True})

    def test_conflicting_months_fail_without_repairing_original(self):
        path = self.old_cl1({'battle_count': 1})
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("INSERT INTO cl1_data VALUES('inst','2026-09','{}',NULL,NULL)")
        original = path.read_bytes()
        with self.assertRaises(MigrationError):
            self.database.ensure_ready()
        self.assertFalse(self.database.path.exists())
        self.assertEqual(path.read_bytes(), original)

    def test_running_old_worker_blocks_install_before_cutover(self):
        cache = self.root / 'cache'
        cache.mkdir()
        (cache / 'webui-workers.json').write_text(json.dumps({'workers': {'inst': {'pid': 12345}}}), encoding='utf-8')
        with patch('module.runtime.process_control.process_matches', return_value=True):
            with self.assertRaises(MigrationError):
                self.database.ensure_ready()
        self.assertFalse(self.database.path.exists())
        self.assertFalse(self.database.marker.exists())

    def test_marker_crash_repairs_from_migration_record_and_missing_database_never_reimports(self):
        self.old_cl1({'battle_count': 1})
        with patch.object(self.database, '_write_marker', side_effect=OSError('模拟切换后的崩溃')):
            with self.assertRaises(OSError):
                self.database.ensure_ready()
        self.assertTrue(self.database.path.exists())
        self.assertFalse(self.database.marker.exists())
        recovered = BusinessDatabase(self.config)
        recovered.ensure_ready()
        self.assertTrue(recovered.marker.exists())
        recovered.path.unlink()
        with self.assertRaises(FileNotFoundError):
            recovered.ensure_ready()

    def test_v1_encrypted_payload_does_not_retire_keys_or_rewrite_original(self):
        key = b'x' * 32
        legacy_ring(self.root, key)
        expected = {'battle_count': 8, 'ap_snapshots': [], 'siren_research_devices': {'cl1': 2, 'meow': {}}}
        path = self.old_cl1({'keep': True})
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('UPDATE cl1_data SET secure_json=?', (legacy_blob(key, 'cl1', expected),))
        original = path.read_bytes()
        ring = self.config / 'opsi_secure' / 'keyring.json'
        material = ring.read_bytes()
        with patch.object(opsi_secure, '_dpapi', side_effect=lambda value, decrypt=False: value), \
                patch.object(opsi_secure, 'decrypt_all', side_effect=AssertionError('迁移不能改写旧数据')):
            self.database.ensure_ready()
        with self.database.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'inst', '2026-09'), dict(expected, keep=True))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(ring.read_bytes(), material)

    def test_v2_deployment_fixture_is_read_only_and_all_sources_migrate(self):
        root = copy_fixture(self)
        from module.persistence.migration import source_files, fingerprint
        install_store(self, root)
        database = BusinessDatabase(root / 'config')
        original = {path: fingerprint(path) for path in source_files(database)}
        material = (root / 'config' / 'opsi_secure' / 'state.json').read_bytes()
        with patch.object(opsi_secure, '_dpapi', side_effect=lambda value, decrypt=False: value):
            database.ensure_ready()
        with database.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'alpha', '2026-09')['battle_count'], 128)
            self.assertGreater(connection.execute('SELECT COUNT(*) FROM opsi_items').fetchone()[0], 0)
            self.assertGreater(connection.execute('SELECT COUNT(*) FROM daily_summary_periods').fetchone()[0], 0)
            self.assertIsNotNone(read_ship(connection, 'alpha'))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM farming_aggregates').fetchone()[0], 6)
        self.assertEqual({path: fingerprint(path) for path in original}, original)
        self.assertEqual((root / 'config' / 'opsi_secure' / 'state.json').read_bytes(), material)

    def test_wal_backup_contains_committed_rows(self):
        self.database.ensure_ready()
        with closing(self.database.connect(factory=sqlite3.Connection)) as writer:
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('BEGIN IMMEDIATE')
            save_month(writer, 'inst', '2026-09', {'battle_count': 9})
            writer.commit()
            self.assertTrue(self.database.path.with_name('azurpilot.db-wal').stat().st_size > 0)
            backup = self.root / 'backup.db'
            self.database.backup(backup)
            with closing(sqlite3.connect(backup)) as saved:
                self.assertEqual(saved.execute('SELECT battle_count FROM cl1_months').fetchone()[0], 9)

    def test_new_flow_ids_follow_a_watermark_even_when_old_rows_were_cleaned(self):
        path = self.config / 'azurstats_local.db'
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript('''CREATE TABLE resource_flows(id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance TEXT,ts TEXT,resource TEXT,amount INTEGER,task TEXT,operation TEXT,evidence TEXT,run_id TEXT,event_key TEXT);
                CREATE TABLE resource_balances(instance TEXT,resource TEXT,value INTEGER,ts TEXT,run_id TEXT,cursor INTEGER);
                INSERT INTO resource_flows VALUES(100,'inst','old','Oil',-10,'Task','Buy','confirmed',NULL,'old');
                DELETE FROM resource_flows;
                INSERT INTO resource_balances VALUES('inst','Oil',100,'old',NULL,90);''')
        self.database.ensure_ready()
        with self.database.transaction() as connection:
            cursor = connection.execute("INSERT INTO resource_flows(instance,ts,resource,amount,task,operation,evidence,event_key) VALUES('inst','new','Oil',-2,'Task','Buy','confirmed','new')")
            self.assertEqual(cursor.lastrowid, 101)

    def test_old_scheduler_sqlite_and_json_keep_drafts_runtime_and_priority(self):
        from module.scheduler.templates import default_program
        document = default_program().model_dump()
        directory = self.config / 'scheduler'
        directory.mkdir()
        path = directory / 'inst.sqlite3'
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript('''CREATE TABLE programs(id INTEGER PRIMARY KEY,mode TEXT,draft TEXT,active TEXT,
                generation INTEGER,revision TEXT); CREATE TABLE variables(name TEXT,value TEXT);
                CREATE TABLE records(name TEXT,value TEXT); CREATE TABLE runtime(id INTEGER PRIMARY KEY,in_flight TEXT);
                CREATE TABLE observations(resource TEXT,value REAL,resource_limit REAL,total REAL,observed_at TEXT,source TEXT);''')
            connection.execute('INSERT INTO programs VALUES(1,?,?,NULL,3,?)', ('native', json.dumps(document), 'revision'))
            connection.execute('INSERT INTO variables VALUES(?,?)', ('huge', str(2 ** 100)))
            connection.execute("INSERT INTO records VALUES('rotation','{\"node\": 2}')")
            connection.execute("INSERT INTO runtime VALUES(1,'Commission')")
        (directory / 'programs').mkdir()
        (directory / 'programs' / 'inst.json').write_text(json.dumps(ProgramStore.default()), encoding='utf-8')
        program = ProgramStore(store=self.database)
        self.assertEqual(program.get('inst')['revision'], 'revision')
        self.assertEqual(program.persistent('inst'), {'variables': {'huge': 2 ** 100}, 'records': {'rotation': {'node': 2}}, 'inFlight': 'Commission'})
        self.assertTrue(path.exists())

    def test_single_instance_slice_restore_and_rename_preserve_other_statistics(self):
        store = ProgramStore(store=self.database)
        for name in ('first', 'other'):
            current = store.get(name)
            store.update(name, current['revision'])
            store.save_persistent(name, {'variables': {'name': name}})
            store.observe(name, 'Oil', 20, 'old-time', 'fixture')
        with self.database.transaction() as connection:
            save_month(connection, 'first', '2026-09', {'battle_count': 5})
        backup = self.root / 'archive'
        other = store.get('other')
        store.archive('first', backup)
        self.assertFalse(store.exists('first'))
        self.assertEqual(store.get('other'), other)
        slice_path = backup / 'business' / 'first.sqlite3'
        with closing(sqlite3.connect(slice_path)) as connection:
            self.assertEqual(connection.execute('SELECT instance FROM scheduler_programs').fetchall(), [('first',)])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM cl1_months').fetchone()[0], 0)
        store.restore('first', slice_path)
        store.relocate('first', 'renamed')
        self.assertEqual(store.persistent('renamed')['variables'], {'name': 'first'})
        self.assertFalse(store.exists('first'))
        self.assertEqual(store.get('other'), other)
        with self.database.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'first', '2026-09'), {'battle_count': 5})
            self.assertIsNone(read_month(connection, 'renamed', '2026-09'))

    def test_slice_rejects_live_target_and_restore_does_not_overwrite_runtime(self):
        store = ProgramStore(store=self.database)
        store.save_persistent('inst', {'variables': {'keep': 1}})
        with self.assertRaises(ValueError):
            store.backup('inst', self.database.path)
        path = self.root / 'inst.sqlite3'
        store.backup('inst', path)
        with self.assertRaises(ConflictError):
            store.restore('inst', path)
        self.assertEqual(store.persistent('inst')['variables'], {'keep': 1})

    def test_explicit_statistics_export_roundtrip_and_late_conflict_rolls_back(self):
        from dev_tools.business_storage import check, export_statistics, import_statistics
        from module.persistence.snapshots import save_ship
        with self.database.transaction() as connection:
            save_month(connection, 'inst', '2026-09', {'keep': [None, {}, [], 2 ** 100]})
            save_ship(connection, 'inst', {'target_level': None, 'ships': [{'level': 0, 'extra': True}]})
        path = self.root / 'statistics.json'
        export_statistics(self.database, 'inst', path)
        other = BusinessDatabase(self.root / 'restored')
        import_statistics(other, 'inst', path)
        self.assertEqual(len(check(other)), 56)
        with other.transaction(write=False) as connection:
            self.assertEqual(read_month(connection, 'inst', '2026-09'), {'keep': [None, {}, [], 2 ** 100]})
            self.assertEqual(read_ship(connection, 'inst')['target_level'], None)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['months'] = {'2026-08': {'battle_count': 2}, **data['months']}
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(FileExistsError):
            import_statistics(other, 'inst', path)
        with other.transaction(write=False) as connection:
            self.assertIsNone(read_month(connection, 'inst', '2026-08'))
