"""交易所实例代理测试：隔离配置、身份和网络，不运行真实游戏。"""
import json
import hashlib
import io
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from contextlib import closing
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.protocol import ApiError
from module.api.stock_exchange_identity import binding_key, load_identity, make_report
from module.api.stock_exchange_service import StockExchangeService, action_snapshot, exchange_url
from module.scheduler.store import ProgramStore


class StockExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'project').resolve()
        self.root.mkdir()
        (self.root / 'config').mkdir()
        self.config = self.root / 'config' / 'test.json'
        self.row = {'Alas': {}, 'Dashboard': {'ActionPoint': {'Total': 8000, 'Value': 100, 'Record': datetime.now().isoformat()}}}
        self.save()
        def config_path(name):
            path = self.root / 'config' / (name + '.json')
            if not path.exists():
                raise ApiError('NOT_FOUND', '实例不存在')
            return path
        self.configs = SimpleNamespace(root=self.root, path=Mock(side_effect=config_path),
                                       read=Mock(side_effect=lambda name: (json.loads(config_path(name).read_text()), 'revision')))
        self.service = StockExchangeService(self.configs)
        self.service.start = Mock()
        self.addCleanup(self.service.close)
        self.player = None
        self.history = {}
        self.service._remote = Mock(side_effect=self.remote)

    def save(self):
        if self.config.exists():
            self.row.update({key: value for key, value in json.loads(self.config.read_text()).items() if key == '_stockInstance'})
        self.config.write_text(json.dumps(self.row), encoding='utf-8')

    def remote(self, path, method='GET', body=None, token='', instance_key='', etag=''):
        data = {'ok': True}
        if path in ('/register', '/login'):
            report = body['report']
            identity, key = self.service._identity('test')
            self.player = {'id': 1, 'username': body['username'], 'quote': {'price': report['actionPoints'] * 100, 'observedAt': report['observedAt']},
                           'binding': {'key': binding_key(identity, key), 'instanceId': identity, 'publicKey': report['publicKey']}}
            data = {'token': 'actual-session-secret', 'uploadToken': 'a' * 64, 'player': self.player}
        if path == '/account':
            data = {'player': self.player}
        if path == '/quote-history':
            report = body['report']
            self.history.update({point['time']: point['actionPoints'] for point in report['points']})
        if path.startswith('/quote-history/manifest?'):
            month = path.rsplit('=', 1)[1]
            from module.api.stock_exchange_history import SHANGHAI
            points = sorted((t, ap) for t, ap in self.history.items() if datetime.fromtimestamp(t / 1000, SHANGHAI).strftime('%Y-%m') == month)
            data = {'count': len(points), 'digest': hashlib.sha256(''.join(f'{t}:{ap}\n' for t, ap in points).encode()).hexdigest()}
        return {'status': 201 if path == '/register' else 200, 'data': data, 'etag': '', 'serverTime': int(time.time())}

    def register(self):
        return self.service.request('test', '/register', 'POST', {'username': '实例测试', 'password': 'strong-password', 'recaptchaToken': 'recaptcha-test-token', 'acceptedNotice': '2026-10-03'})

    def test_new_quotes_upload_without_fixed_interval(self):
        self.register()
        observed = self.player['quote']['observedAt'] + 1
        self.service.last_upload['test'] = 100
        self.service._remote.reset_mock()
        with patch('module.api.stock_exchange_service.time.monotonic', return_value=100), \
                patch.object(self.service, '_read_snapshot', return_value={'instance': 'test', 'observedAt': observed, 'actionPoints': 8100}):
            self.service._sync_instance('test', False)
        self.assertEqual(1, self.service._remote.call_count)
        self.assertEqual('/quotes', self.service._remote.call_args.args[0])
        self.assertEqual((observed, 8100), self.service.uploaded['test'])

    def test_event_stream_notifies_disconnect_and_recovery_without_credentials(self):
        def stream(revision):
            value = io.BytesIO(f'event: stock\ndata: {{"revision":{revision},"serverTime":123}}\n\n'.encode())
            value.headers = Message()
            value.headers['Content-Type'] = 'text/event-stream'
            return value
        updates = []
        def receive(data):
            updates.append(data)
            if data.get('revision') == 2:
                self.service.stop.set()
        self.service.listeners.add(receive)
        with patch('module.api.stock_exchange_service.urlopen', side_effect=[stream(1), stream(2)]):
            self.service._listen_events()
        self.assertEqual([True, False, True], [value['online'] for value in updates])
        self.assertEqual([1, 2], [value['revision'] for value in updates if 'revision' in value])
        self.assertNotIn('token', json.dumps(updates))

    def test_new_registration_backfills_whole_month_before_signup(self):
        from module.api.stock_exchange_history import SHANGHAI, history_point
        now = datetime.now(SHANGHAI)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        points = [{'ts': (start + (now - start) * (i / 3002)).isoformat(), 'ap_total': 7000 + i % 40}
                  for i in range(3001)]
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as db, db:
            db.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT,encrypted_blob BLOB,PRIMARY KEY(instance,month))')
            db.execute('INSERT INTO cl1_data VALUES(?,?,?,NULL)', ('test', now.strftime('%Y-%m'), json.dumps({'ap_snapshots': points})))
        self.register()
        expected = {history_point(row['ap_total'], row['ts'])[0]: row['ap_total'] for row in points}
        current = self.row['Dashboard']['ActionPoint']
        expected[history_point(current['Total'], current['Record'])[0]] = current['Total']
        # 开户后的网络失败不会丢掉已认证的整月队列，重启无需重新登录也能补传。
        with patch.object(self.service, '_remote', side_effect=ApiError('STOCK_UNAVAILABLE', '隔离断网夹具')):
            with self.assertRaises(ApiError):
                self.service.sync_once('test', force=True)
        cold = StockExchangeService(self.configs)
        cold.start = Mock()
        cold._remote = self.service._remote
        self.addCleanup(cold.close)
        for _ in range(5):
            cold.sync_once('test', force=True)
        self.assertEqual(expected, self.history)
        self.assertFalse(cold.status('test')['authenticated'])
        reports = [call.args[2]['report'] for call in self.service._remote.call_args_list
                   if call.args[0] == '/quote-history']
        self.assertTrue(any(report['count'] == len(expected) and report['digest'] for report in reports))

    def test_existing_binding_backfills_legacy_month_after_upgrade(self):
        from module.api.stock_exchange_history import SHANGHAI, history_point
        older = datetime.now(SHANGHAI).replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        with closing(sqlite3.connect(self.root / 'config' / 'cl1_data.db')) as db, db:
            db.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT,encrypted_blob BLOB,PRIMARY KEY(instance,month))')
            db.execute('INSERT INTO cl1_data VALUES(?,?,?,NULL)',
                       ('test', older.strftime('%Y-%m'), json.dumps({'ap_snapshots': [{'ts': older.isoformat(), 'ap_total': 6000}]})))
        # 模拟升级前已经开户、已有认证历史和队列，但未导入旧统计的账户。
        with patch.object(self.service.history, '_import_legacy_history', return_value=''):
            self.register()
            self.service.sync_once('test', force=True)
        self.assertNotIn(history_point(6000, older.isoformat())[0], self.history)
        self.service.close()
        cold = StockExchangeService(self.configs)
        cold.start = Mock()
        cold._remote = self.service._remote
        self.addCleanup(cold.close)
        for _ in range(2):
            cold.sync_once('test', force=True)
        self.assertEqual(6000, self.history[history_point(6000, older.isoformat())[0]])
        self.assertTrue(cold.status('test')['bound'])
        self.assertFalse(cold.status('test')['authenticated'])

    def test_unreadable_current_legacy_month_allows_register_login_and_live_sync(self):
        from module.api.stock_exchange_history import SHANGHAI, history_point
        older = datetime.now(SHANGHAI).replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        ProgramStore(self.root / 'config').database.ensure_ready()
        path = self.root / 'config' / 'cl1_data.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE cl1_data(instance TEXT,month TEXT,data_json TEXT,encrypted_blob BLOB,PRIMARY KEY(instance,month))')
            db.execute('INSERT INTO cl1_data VALUES(?,?,?,NULL)', ('test', older.strftime('%Y-%m'), 'broken-json'))
        self.assertEqual(201, self.register()['status'])
        self.assertTrue(self.service.status('test')['bound'])
        self.assertIn('当月旧统计', self.service.status('test')['message'])
        self.service.request('test', '/logout', 'POST', {})
        logged = self.service.request('test', '/login', 'POST', {'username': '实例测试', 'password': 'strong-password', 'recaptchaToken': 'recaptcha-test-token'})
        self.assertEqual(200, logged['status'])
        self.row['Dashboard']['ActionPoint'].update(Total=8100, Record=datetime.now().isoformat())
        self.save()
        current = self.row['Dashboard']['ActionPoint']
        ProgramStore(self.root / 'config').observe('test', 'ActionPoint', {'Total': 8100}, current['Record'], 'fixture')
        self.service.sync_once('test', force=True)
        self.assertEqual(8100, self.service.status('test')['snapshot']['actionPoints'])
        self.assertEqual(8100, self.history[history_point(8100, current['Record'])[0]])
        self.assertIn('当月旧统计', self.service.status('test')['message'])
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('UPDATE cl1_data SET data_json=?', (json.dumps({'ap_snapshots': [{'ts': older.isoformat(), 'ap_total': 6000}]}),))
        # 配置没有变化时状态读取也会在下一轮扫描重试并清除提示。
        self.service.history.scanned['test'] = 0
        self.assertNotIn('当月旧统计', self.service.status('test')['message'])
        self.service.sync_once('test', force=True)
        self.assertEqual(6000, self.history[history_point(6000, older.isoformat())[0]])

    def test_total_zero_and_missing_record(self):
        self.assertEqual(8000, action_snapshot(self.row, 'test')['actionPoints'])
        self.assertIsNone(action_snapshot({'Dashboard': {'ActionPoint': {'Total': True, 'Record': datetime.now().isoformat()}}}, 'test'))
        self.assertIsNone(action_snapshot({'Dashboard': {'ActionPoint': {'Value': 100}}}, 'test'))
        self.row['Dashboard']['ActionPoint']['Total'] = 0
        self.assertEqual(0, action_snapshot(self.row, 'test')['actionPoints'])

    def test_instance_identity_persists_and_does_not_copy_by_name(self):
        first, key = load_identity(self.root, 'test')
        again, same_key = load_identity(self.root, 'test')
        (self.root / 'config' / 'copy.json').write_bytes(self.config.read_bytes())
        second, other_key = load_identity(self.root, 'copy')
        self.assertEqual(first, again)
        self.assertEqual(binding_key(first, key), binding_key(again, same_key))
        self.assertNotEqual(first, second)
        self.assertNotEqual(binding_key(first, key), binding_key(second, other_key))
        report = make_report(first, key, 987654, 0)
        self.assertEqual(987654, report['actionPoints'])
        self.assertNotIn('image', report)
        self.assertNotIn('evidence', report)

    def test_native_proxy_hides_credentials_and_preserves_binding_after_logout_restart(self):
        result = self.register()
        self.assertEqual('instance-session', result['data']['token'])
        self.assertNotIn('actual-session-secret', json.dumps(result))
        self.assertNotIn('a' * 64, json.dumps(result))
        self.assertNotIn('privateKey', json.dumps(result))
        self.assertTrue(self.service.status('test')['authenticated'])
        self.service.request('test', '/logout', 'POST', {})
        self.assertFalse(self.service.status('test')['authenticated'])
        self.assertTrue(self.service.status('test')['bound'])
        with self.assertRaises(ApiError):
            self.register()
        reloaded = StockExchangeService(self.configs)
        reloaded.start = Mock()
        self.addCleanup(reloaded.close)
        self.assertEqual(self.service.status('test')['instanceId'], reloaded.status('test')['instanceId'])
        self.assertEqual('实例测试', reloaded.status('test')['boundUsername'])
        self.assertFalse(reloaded.status('test')['authenticated'])

    def test_admin_rename_refreshes_saved_binding_without_changing_identity(self):
        self.register()
        original = dict(self.service.bindings['test'])
        self.player['username'] = '管理员改名账户'
        account = self.service.request('test', '/account')
        self.assertEqual('管理员改名账户', account['data']['player']['username'])
        self.assertEqual('管理员改名账户', self.service.status('test')['boundUsername'])
        saved = self.service.protection.read_file('bindings.json')[self.service.status('test')['instanceId']]
        self.assertEqual('管理员改名账户', saved['username'])
        for field in ('playerId', 'bindingKey', 'uploadToken', 'url'):
            self.assertEqual(original[field], saved[field])
        self.service.request('test', '/logout', 'POST', {})
        reply = self.service.request('test', '/login', 'POST', {'username': '管理员改名账户', 'password': 'new-password', 'recaptchaToken': 'test'})
        self.assertEqual('instance-session', reply['data']['token'])
        self.assertEqual(original['playerId'], self.service.bindings['test']['playerId'])
        self.assertEqual(original['bindingKey'], self.service.bindings['test']['bindingKey'])

    def test_unchanged_records_do_not_upload_or_reread_config(self):
        self.register()
        self.service.sync_once(force=True)  # 初始原始记录也须持久补传。
        self.service.sync_once(force=True)  # 首次月摘要校对。
        self.service._remote.reset_mock()
        reads = self.configs.read.call_count
        with patch.object(self.service, '_identity', wraps=self.service._identity) as identities:
            for _ in range(3):
                self.service.sync_once()
            identities.assert_not_called()
        self.service._remote.assert_not_called()
        self.assertEqual(reads, self.configs.read.call_count)
        self.row['Dashboard']['ActionPoint'].update(Total=8100, Record=(datetime.now() + timedelta(seconds=16)).isoformat())
        self.save()
        ProgramStore(self.root / 'config').observe('test', 'ActionPoint', {'Total': 8100}, self.row['Dashboard']['ActionPoint']['Record'], 'fixture')
        self.service.sync_once(force=True)
        live = [call for call in self.service._remote.call_args_list if call.args[0] == '/quotes']
        self.assertEqual(1, len(live))
        path, method, body, token, instance_key = live[0].args
        self.assertEqual('/quotes', path)
        self.assertEqual(8100, body['report']['actionPoints'])
        self.assertEqual('a' * 64, token)
        self.assertEqual(self.service.status('test')['bindingKey'], instance_key)
        self.assertNotIn('image', json.dumps(body))
        self.service.sync_once(force=True)
        live = [call for call in self.service._remote.call_args_list if call.args[0] == '/quotes']
        self.assertEqual(1, len(live))
        uploads = [call for call in self.service._remote.call_args_list if call.args[0] == '/quote-history' and call.args[2]['report']['points']]
        self.assertEqual(1, len(uploads))

    def test_runtime_observation_can_update_unchanged_dashboard(self):
        directory = self.root / 'config' / 'scheduler'
        directory.mkdir()
        with closing(sqlite3.connect(directory / 'test.sqlite3')) as conn, conn:
            conn.execute('CREATE TABLE observations (resource TEXT, total INTEGER, observed_at TEXT)')
            conn.execute('INSERT INTO observations VALUES (?, ?, ?)', ('ActionPoint', 9000, (datetime.now() + timedelta(seconds=1)).isoformat()))
        self.assertEqual(9000, self.service.status('test')['snapshot']['actionPoints'])

    def test_browser_cannot_replace_instance_or_access_admin(self):
        for path, body in [('/register', {'report': {}}), ('/orders', {'instanceId': 'other'}), ('/console/settings', {})]:
            with self.assertRaises(ApiError):
                self.service.request('test', path, 'POST', body)
        self.service._remote.assert_not_called()

    def test_registration_without_action_record_starts_at_zero(self):
        self.row['Dashboard']['ActionPoint'].pop('Record')
        self.save()
        result = self.register()
        self.assertEqual(0, result['data']['player']['quote']['price'])
        self.assertTrue(self.service.status('test')['bound'])

    def test_origin_is_environment_controlled(self):
        for target in ['http://evil.test', 'https://user:pass@evil.test', 'file:///tmp/data', 'https://stock.nanoda.work/api']:
            with patch.dict('os.environ', {'STOCK_EXCHANGE_URL': target}), self.assertRaises(ApiError):
                exchange_url()
        with patch.dict('os.environ', {'STOCK_EXCHANGE_URL': 'http://127.0.0.1:8080'}):
            self.assertEqual('http://127.0.0.1:8080', exchange_url())

    def test_game_credentials_are_authenticated_ciphertext(self):
        self.register()
        identity, key = self.service._identity('test')
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
        import base64
        private = base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
        for path in self.root.rglob('*'):
            if path.is_file():
                content = path.read_bytes()
                self.assertNotIn(private, content)
                self.assertNotIn(('a' * 64).encode(), content)
                self.assertNotIn(b'actual-session-secret', content)
        envelope = json.loads(self.service.path.read_bytes())
        self.assertEqual(1, envelope['version'])
        self.assertNotIn('test', envelope)

    def test_binding_corruption_blocks_live_and_cold_services(self):
        self.register()
        self.service.path.write_text('{broken', encoding='utf-8')
        self.service._remote.reset_mock()
        with self.assertRaises(ApiError):
            self.service.request('test', '/account')
        cold = StockExchangeService(self.configs)
        self.addCleanup(cold.close)
        self.assertIsNotNone(cold.storage_error)
        with self.assertRaises(ApiError):
            cold.status('test')
        self.service._remote.assert_not_called()

    def test_identity_tampering_and_loss_block_cached_keys(self):
        self.register()
        identity = self.service.status('test')['instanceId']
        path = self.service.protection.file_path('identities/' + identity + '.json')
        original = path.read_bytes()
        path.write_bytes(original[:-1] + b'!')
        with self.assertRaises(ApiError):
            self.service._identity('test')
        self.service._remote.reset_mock()
        with self.assertRaises(ApiError):
            self.service.request('test', '/account')
        self.service._remote.assert_not_called()
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(ApiError):
            self.service._identity('test')
        self.assertFalse(path.exists())

    def test_valid_old_binding_file_cannot_be_replayed(self):
        self.register()
        original = self.service.path.read_bytes()
        self.player['username'] = '新的玩家名称'
        self.service.request('test', '/account')
        self.service.path.write_bytes(original)
        with self.assertRaises(ApiError):
            self.service.status('test')

    def test_persistent_key_or_registry_loss_never_recreates_identity(self):
        self.register()
        identity = self.service.status('test')['instanceId']
        protected = self.service.protection.file_path('identities/' + identity + '.json').read_bytes()
        key_path = self.service.protection.key_path
        key = key_path.read_bytes()
        key_path.unlink()
        with self.assertRaises(ApiError):
            self.service.status('test')
        key_path.write_bytes(key)
        self.service.protection.state_path.unlink()
        with self.assertRaises(ApiError):
            self.service.status('test')
        self.assertEqual(protected, self.service.protection.file_path('identities/' + identity + '.json').read_bytes())

    def test_dashboard_edits_do_not_become_signed_game_observations(self):
        self.register()
        self.row['Dashboard']['ActionPoint'].update(Total=9999, Record=(datetime.now() + timedelta(seconds=30)).isoformat())
        self.save()
        self.service.sync_once(force=True)
        self.assertEqual(8000, self.service.status('test')['snapshot']['actionPoints'])
        reports = [call.args[2]['report'] for call in self.service._remote.call_args_list if call.args[0] in ('/quotes', '/quote-history')]
        self.assertFalse(any(report.get('actionPoints') == 9999 or any(point['actionPoints'] == 9999 for point in report.get('points', [])) for report in reports))

    def test_external_rename_preserves_player_identity_history_and_session(self):
        self.register()
        original = self.service.status('test')
        source = ProgramStore(self.root / 'config').history.path('test')
        self.config.rename(self.root / 'config' / 'renamed.json')
        renamed = self.service.status('renamed')
        self.assertEqual(original['instanceId'], renamed['instanceId'])
        self.assertTrue(renamed['bound'])
        self.assertTrue(renamed['authenticated'])
        self.assertNotIn('test', self.service.monitors)
        self.assertFalse(source.exists())
        self.assertTrue(ProgramStore(self.root / 'config').history.path('renamed').exists())
        self.assertEqual(8000, renamed['snapshot']['actionPoints'])
        cold = StockExchangeService(self.configs)
        cold.start = Mock()
        self.addCleanup(cold.close)
        self.assertEqual(original['instanceId'], cold.status('renamed')['instanceId'])
        self.assertTrue(cold.status('renamed')['bound'])

    def test_external_delete_then_same_name_recreate_cannot_inherit_player(self):
        self.register()
        original = self.service.status('test')['instanceId']
        self.config.unlink()
        self.service.sync_once()
        self.assertNotIn('test', self.service.sessions)
        self.assertNotIn('test', self.service.monitors)
        self.row.pop('_stockInstance', None)
        self.save()
        status = self.service.status('test')
        self.assertNotEqual(original, status['instanceId'])
        self.assertFalse(status['bound'])
        self.assertFalse(status['authenticated'])
        self.assertIsNone(status['snapshot'])

    def test_offline_same_name_replacement_is_also_a_new_instance(self):
        self.register()
        original = self.service.status('test')['instanceId']
        self.config.write_text(json.dumps({'Alas': {}}), encoding='utf-8')
        cold = StockExchangeService(self.configs)
        cold.start = Mock()
        self.addCleanup(cold.close)
        status = cold.status('test')
        self.assertNotEqual(original, status['instanceId'])
        self.assertFalse(status['bound'])
        self.assertIsNone(status['snapshot'])

    def test_copy_does_not_inherit_player_or_source_history(self):
        self.register()
        original = self.service.status('test')['instanceId']
        (self.root / 'config' / 'copy.json').write_bytes(self.config.read_bytes())
        status = self.service.status('copy')
        self.assertNotEqual(original, status['instanceId'])
        self.assertFalse(status['bound'])
        self.assertIsNone(status['snapshot'])

    def test_restoring_deleted_config_identity_does_not_restore_binding(self):
        self.register()
        original = self.config.read_bytes()
        self.config.unlink()
        self.service.sync_once()
        self.config.write_bytes(original)
        with self.assertRaises(ApiError):
            self.service.status('test')

    def test_legacy_identity_binding_and_history_migrate_without_rebinding(self):
        import base64
        import uuid
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
        identity, key = str(uuid.uuid4()), Ed25519PrivateKey.generate()
        private = base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
        old = self.service.path.parent / 'identities' / (hashlib.sha256(b'test').hexdigest() + '.json')
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({'instanceId': identity, 'privateKey': private}), encoding='utf-8')
        self.service.path.write_text(json.dumps({'test': {'playerId': 1, 'username': '旧版玩家', 'bindingKey': binding_key(identity, key),
                                                          'uploadToken': 'a' * 64, 'url': 'https://stock.nanoda.work'}}), encoding='utf-8')
        database = ProgramStore(self.root / 'config').history.path('test')
        database.parent.mkdir()
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('CREATE TABLE action_point_history(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at TEXT NOT NULL UNIQUE,total INTEGER NOT NULL)')
            db.execute('INSERT INTO action_point_history(observed_at,total) VALUES(?,?)', (self.row['Dashboard']['ActionPoint']['Record'], 8000))
            db.execute('CREATE TABLE observations(resource TEXT PRIMARY KEY,total INTEGER,observed_at TEXT)')
        cold = StockExchangeService(self.configs)
        cold.start = Mock()
        self.addCleanup(cold.close)
        status = cold.status('test')
        self.assertEqual(identity, status['instanceId'])
        self.assertEqual('旧版玩家', status['boundUsername'])
        self.assertEqual(8000, status['snapshot']['actionPoints'])
        self.assertFalse(old.exists())
        self.assertNotIn(private.encode(), cold.protection.file_path('identities/' + identity + '.json').read_bytes())
        self.assertNotIn(('a' * 64).encode(), cold.path.read_bytes())

    def test_api_copy_export_patch_and_delete_respect_stable_identity(self):
        from tests.test_api import fixture
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from module.config.config_updater import ConfigUpdater
        root = Path(self.temp.name) / 'managed'
        root.mkdir()
        fixture(root)
        configs = ConfigService(root)
        identity, _ = load_identity(root, 'testpilot')
        store = ProgramStore(root / 'config')
        store.observe('testpilot', 'ActionPoint', {'Total': 8000}, datetime.now().isoformat(), 'fixture')
        self.assertNotIn('_stockInstance', configs.export('testpilot'))
        configs.create('copied', source='testpilot')
        self.assertIsNone(configs.read('copied')[0]['_stockInstance'])
        self.assertNotEqual(identity, load_identity(root, 'copied')[0])
        updated = configs.patch('testpilot', '', [ConfigChange(path='Alas.Emulator.Serial', value='fixture-emulator')])
        self.assertNotIn('_stockInstance', updated['values'])
        self.assertEqual(identity, configs.read('testpilot')[0]['_stockInstance'])
        self.assertEqual(identity, ConfigUpdater().config_update(configs.read('testpilot')[0])['_stockInstance'])
        revision = configs.read('testpilot')[1]
        configs.delete('testpilot', revision)
        configs.create('testpilot')
        replacement, _ = load_identity(root, 'testpilot')
        self.assertNotEqual(identity, replacement)
        self.assertFalse(store.history.path('testpilot').exists())
        self.assertEqual({}, store.observations('testpilot'))


if __name__ == '__main__':
    unittest.main()
