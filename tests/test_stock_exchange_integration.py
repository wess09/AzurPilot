"""通过真实回环 Go / Postgres 验证股票接入；需显式指定隔离测试环境。"""
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError
from unittest.mock import patch

from module.api.stock_exchange_service import StockExchangeService
from module.api.stock_exchange_history import SHANGHAI
from module.scheduler.store import ProgramStore


REQUIRED = ('EXCHANGE_INTEGRATION_URL', 'EXCHANGE_INTEGRATION_DATABASE_URL',
            'EXCHANGE_INTEGRATION_BOT_TOKEN')


@unittest.skipUnless(all(os.environ.get(name) for name in REQUIRED) and
                     (os.environ.get('EXCHANGE_INTEGRATION_PSQL') or os.environ.get('EXCHANGE_INTEGRATION_PG_CONTAINER')),
                     '未配置回环 Go / Postgres 集成环境')
class StockExchangeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ['EXCHANGE_INTEGRATION_URL'].rstrip('/')
        self.database = os.environ['EXCHANGE_INTEGRATION_DATABASE_URL']
        for address in (self.url, self.database):
            if urlparse(address).hostname not in ('127.0.0.1', 'localhost', '::1'):
                self.fail('集成测试仅允许回环服务')
        if '_test' not in urlparse(self.database).path:
            self.fail('集成测试数据库名称必须包含 _test')
        self.environment = patch.dict(os.environ, {'STOCK_EXCHANGE_URL': self.url})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'config').mkdir()
        self.now = datetime.now() - timedelta(seconds=10)
        self.path = self.root / 'config' / 'integration.json'
        self.path.write_text(json.dumps({'Alas': {}, 'Dashboard': {'ActionPoint': {'Total': 8000, 'Record': self.now.isoformat()}}}), encoding='utf-8')
        self.configs = SimpleNamespace(root=self.root, path=lambda name: self.root / 'config' / (name + '.json'),
                                      read=lambda name: (json.loads((self.root / 'config' / (name + '.json')).read_text()), 'fixture'))
        self.store = ProgramStore(self.root / 'config')
        self.store.database.ensure_ready()
        self.service = self.new_service()
        self.calls = []
        actual = self.service._remote
        def record_request(path, method='POST', body=None):
            self.calls.append((path, body))
            return actual(path, method, body)
        self.service._remote = record_request

    def new_service(self):
        service = StockExchangeService(self.configs)
        # 手动驱动真实同步，确保能逐步断言增量数量；未替换 HTTP 或持久化实现。
        service.start = lambda: None
        self.addCleanup(service.close)
        return service

    def request(self, path, body=None, bot=False):
        headers = {'Content-Type': 'application/json'}
        if bot:
            headers['Authorization'] = 'Bearer ' + os.environ['EXCHANGE_INTEGRATION_BOT_TOKEN']
        payload = None if body is None else json.dumps(body, separators=(',', ':')).encode()
        with urlopen(Request(self.url + '/api/v2' + path, data=payload, headers=headers), timeout=15) as response:
            return json.load(response)

    def manifest(self):
        return self.service._accepted(self.service._remote('/v2/instance/manifest', 'POST', self.service._signed('integration', 'manifest')))

    def test_real_registration_increment_correction_and_manifest_repair(self):
        self.assertFalse(self.service.status('integration')['registered'])
        suffix = secrets.token_hex(5)
        registered = self.service.register('integration', '集成股票' + suffix, 'stock-public-v2-20261101')
        self.assertTrue(registered['registered'])
        self.assertFalse(registered['bound'])
        self.assertTrue(registered['bindingCode'])
        stock_id = registered['stock']['id']
        self.service.sync_once('integration', force=True)
        self.assertEqual(800000, self.service.status('integration', refresh=True)['stock']['price'])
        self.calls.clear()
        self.service.sync_once('integration')
        self.assertFalse(any(path.endswith('/report') for path, _ in self.calls))

        recorded = (self.now + timedelta(seconds=1)).isoformat()
        self.store.observe('integration', 'ActionPoint', {'Total': 8100}, recorded, 'integration')
        self.service.sync_once('integration')
        delta = [body for path, body in self.calls if path.endswith('/report')]
        self.assertEqual(1, len(delta))
        self.assertEqual([8100], [point['p'] for point in delta[0]['points']])
        self.assertEqual(810000, self.service.status('integration', refresh=True)['stock']['price'])

        self.store.observe('integration', 'ActionPoint', {'Total': 8200}, recorded, 'integration')
        self.service.sync_once('integration')
        self.assertEqual(820000, self.service.status('integration', refresh=True)['stock']['price'])
        manifest = self.manifest()
        self.assertEqual(2, sum(month['count'] for month in manifest['months']))
        points = sorted([(int(self.now.timestamp() * 1000), 8000), (int(datetime.fromisoformat(recorded).timestamp() * 1000), 8200)])
        digest = hashlib.sha256(''.join(f'{t}:{p}\n' for t, p in points).encode()).hexdigest()
        self.assertEqual(digest, manifest['months'][0]['digest'])

        # 仅在已审查的独立 _test 数据库中删除本测试股票的一条历史，验证真实摘要修补。
        if os.environ.get('EXCHANGE_INTEGRATION_PSQL'):
            command = [os.environ['EXCHANGE_INTEGRATION_PSQL'], self.database]
        else:
            parsed = urlparse(self.database)
            command = ['docker', 'exec', os.environ['EXCHANGE_INTEGRATION_PG_CONTAINER'], 'psql',
                       '-U', parsed.username or 'postgres', '-d', parsed.path.lstrip('/')]
        deleted = subprocess.run([*command, '-X', '-v', 'ON_ERROR_STOP=1', '-c',
                                  f"DELETE FROM mmex_v2_history WHERE stock_id={int(stock_id)} AND time_ms={points[0][0]} "
                                  f"AND EXISTS (SELECT 1 FROM mmex_v2_entities WHERE kind='stock' AND id='{int(stock_id)}' "
                                  f"AND data->>'instanceId'='{registered['instanceId']}')"],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(0, deleted.returncode, '隔离测试历史删除失败')
        self.assertEqual(1, sum(month['count'] for month in self.manifest()['months']))
        self.service.sync_once('integration', force=True)
        self.assertEqual(digest, self.manifest()['months'][0]['digest'])

    def test_real_bot_registration_binding_and_restart_sync(self):
        suffix = secrets.token_hex(5)
        registered = self.service.register('integration', '绑定股票' + suffix, 'stock-public-v2-20261101')
        stock_id = registered['stock']['id']
        self.service.sync_once('integration', force=True)
        official = 'integration-app:openid-' + suffix
        account = self.request('/bot/register', {'officialUserId': official, 'username': '集成用户' + suffix, 'requestId': 'register-' + suffix}, bot=True)
        self.assertTrue(account['forcePasswordChange'])
        bound = self.request('/bot/bind', {'officialUserId': official, 'bindingCode': registered['bindingCode']}, bot=True)
        self.assertEqual(stock_id, bound['stock']['id'])
        self.assertTrue(self.service.status('integration', refresh=True)['bound'])

        self.service.close()
        resumed = self.new_service()
        self.assertIn('integration', resumed.monitors)
        self.assertTrue(resumed.status('integration')['bound'])
        self.store.observe('integration', 'ActionPoint', {'Total': 8300}, (self.now + timedelta(seconds=2)).isoformat(), 'integration')
        resumed.sync_once('integration')
        self.assertEqual(830000, resumed.status('integration', refresh=True)['stock']['price'])
        self.assertEqual(2, sum(month['count'] for month in self.manifest()['months']))

    @unittest.skipUnless(os.environ.get('EXCHANGE_INTEGRATION_ADMIN_PASSWORD'), '未配置隔离管理员测试密码')
    def test_real_admin_deletion_stops_relay_and_requires_rebinding(self):
        suffix = secrets.token_hex(5)
        registered = self.service.register('integration', '真实删除股票' + suffix, 'stock-public-v2-20261101')
        self.service.sync_once('integration', force=True)
        official = 'integration-app:delete-' + suffix
        account = self.request('/bot/register', {'officialUserId': official, 'username': '删除用户' + suffix, 'requestId': 'register-' + suffix}, bot=True)
        player = build_opener(HTTPCookieProcessor())
        admin = build_opener(HTTPCookieProcessor())
        def browser(opener, path, payload, method='POST'):
            request = Request(self.url + '/api/v2' + path, data=json.dumps(payload).encode(), method=method, headers={'Content-Type': 'application/json'})
            with opener.open(request, timeout=15) as response:
                return json.load(response)
        browser(player, '/auth/login', {'username': account['username'], 'password': account['password']})
        browser(player, '/auth/password', {'currentPassword': account['password'], 'password': 'Integration-Secure-Password!91'})
        self.request('/bot/bind', {'officialUserId': official, 'bindingCode': registered['bindingCode']}, bot=True)
        browser(admin, '/admin/login', {'password': os.environ['EXCHANGE_INTEGRATION_ADMIN_PASSWORD']})
        browser(admin, '/admin/stocks/' + str(registered['stock']['id']), {'confirmed': True}, 'DELETE')
        with self.assertRaises(HTTPError) as denied:
            self.request('/bot/portfolio?officialUserId=' + official, bot=True)
        with denied.exception as response:
            self.assertEqual('BINDING_REQUIRED', json.load(response)['error']['code'])
        self.service.sync_once('integration', force=True)
        self.assertTrue(self.service.status('integration', refresh=True)['deleted'])
        self.assertNotIn('integration', self.service.monitors)
        count = len(self.calls)
        self.service.sync_once('integration', force=True)
        self.assertEqual(count, len(self.calls))
        self.service.close()
        resumed = self.new_service()
        self.assertTrue(resumed.status('integration', refresh=True)['deleted'])
        self.assertNotIn('integration', resumed.monitors)
        replacement_path = self.root / 'config' / 'replacement.json'
        data = json.loads(self.path.read_text())
        data.pop('_stockInstance', None)
        replacement_path.write_text(json.dumps(data), encoding='utf-8')
        replacement = resumed.register('replacement', '替代股票' + suffix, 'stock-public-v2-20261101')
        bound = self.request('/bot/bind', {'officialUserId': official, 'bindingCode': replacement['bindingCode']}, bot=True)
        self.assertEqual(replacement['stock']['id'], bound['stock']['id'])

    def test_real_manifest_month_uses_shanghai_boundary(self):
        self.service.register('integration', '月份股票' + secrets.token_hex(5), 'stock-public-v2-20261101')
        boundary = datetime.now(SHANGHAI).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        points = [(int((boundary - timedelta(milliseconds=1)).timestamp() * 1000), 7000),
                  (int(boundary.timestamp() * 1000), 7100)]
        report = self.service._signed('integration', 'report', points=points)
        report['backfill'] = True
        self.service._accepted(self.service._remote('/v2/instance/report', 'POST', report))
        actual = {row['month']: row['count'] for row in self.manifest()['months']}
        self.assertEqual({(boundary - timedelta(milliseconds=1)).strftime('%Y-%m'): 1,
                          boundary.strftime('%Y-%m'): 1}, actual)


if __name__ == '__main__':
    unittest.main()
