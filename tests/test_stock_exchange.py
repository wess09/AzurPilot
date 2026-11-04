"""股票实例 v2 接入测试：隔离网络、配置和历史，不运行真实游戏。"""
import base64
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from module.base import http
from module.api.protocol import ApiError
from module.api.stock_exchange_service import StockExchangeService, exchange_url
from module.scheduler.store import ProgramStore


class StockExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'config').mkdir()
        self.config = self.root / 'config' / 'test.json'
        self.now = datetime.now()
        self.config.write_text(json.dumps({'Alas': {}, 'Dashboard': {'ActionPoint': {'Total': 8000, 'Record': self.now.isoformat()}}}), encoding='utf-8')
        def path(name):
            result = self.root / 'config' / (name + '.json')
            if not result.exists():
                raise ApiError('NOT_FOUND', '实例不存在')
            return result
        self.configs = SimpleNamespace(root=self.root, path=Mock(side_effect=path), read=Mock(side_effect=lambda name: (json.loads(path(name).read_text()), 'revision')))
        self.service = StockExchangeService(self.configs)
        self.service.start = Mock()
        self.addCleanup(self.service.close)
        self.stock = None
        self.points = {}
        self.calls = []
        self.service._remote = Mock(side_effect=self.remote)

    def remote(self, path, method='GET', body=None, *args):
        self.calls.append((path, body))
        action = path.rsplit('/', 1)[1]
        identity, key = self.service._identity('test')
        self.assertEqual(identity, body['instanceId'])
        points = body.get('points', [])
        text = f"mmex-v2\n{action}\n{identity}\n{body['publicKey']}\n{body['issuedAt']}\n{body.get('username', '')}\n" + json.dumps(points, separators=(',', ':')) + '\n'
        key.public_key().verify(base64.b64decode(body['signature']), text.encode())
        if action == 'register':
            self.stock = self.stock or {'id': 1, 'symbol': 'MM000001', 'name': body['username'], 'price': 0, 'observedAt': 0, 'bound': False}
        if action in ('register', 'status'):
            if self.stock is None:
                return {'status': 404, 'data': {'error': {'code': 'STOCK_NOT_REGISTERED'}}}
            return {'status': 200, 'data': {'stock': self.stock, 'bindingCode': 'MMEX-FIXTURE-BINDING', 'exchangeUrl': 'https://stock.azurpilot.com', 'cursor': max(self.points, default=0)}}
        if action == 'report':
            self.points.update({point['t']: point['p'] for point in points})
        if action == 'manifest':
            from module.api.stock_exchange_history import SHANGHAI
            months = {}
            for stamp, total in sorted(self.points.items()):
                month = datetime.fromtimestamp(stamp / 1000, SHANGHAI).strftime('%Y-%m')
                months.setdefault(month, []).append((stamp, total))
            return {'status': 200, 'data': {'months': [{'month': month, 'count': len(values), 'digest': hashlib.sha256(''.join(f'{t}:{p}\n' for t, p in values).encode()).hexdigest()} for month, values in months.items()]}}
        return {'status': 200, 'data': {'cursor': max(self.points, default=0), 'accepted': len(points)}}

    def register(self):
        return self.service.register('test', '实例股票', 'stock-public-v2-20261101')

    def test_registration_separates_stock_from_trading_account(self):
        self.assertFalse(self.service.status('test')['registered'])
        result = self.register()
        self.assertTrue(result['registered'])
        self.assertFalse(result['bound'])
        self.assertEqual('实例股票', result['stock']['name'])
        self.assertEqual('MMEX-FIXTURE-BINDING', result['bindingCode'])
        self.assertFalse(hasattr(self.service, 'sessions'))
        self.assertFalse(hasattr(self.service, 'request'))
        self.assertNotIn('privateKey', json.dumps(result))
        self.assertNotIn('actionPoints', json.dumps(result))
        self.assertEqual({'instanceId', 'publicKey', 'issuedAt', 'username', 'signature'}, set(next(body for path, body in self.calls if path.endswith('/register'))))

    def test_registered_instance_resumes_without_player_login(self):
        self.register()
        self.service.close()
        cold = StockExchangeService(self.configs)
        cold.start = Mock()
        cold._remote = Mock(side_effect=self.remote)
        self.addCleanup(cold.close)
        self.assertIn('test', cold.monitors)
        cold.sync_once('test', force=True)
        self.assertTrue(self.points)
        self.assertFalse(hasattr(cold, 'sessions'))

    def test_only_new_and_corrected_millisecond_samples_are_uploaded(self):
        self.register()
        self.service.sync_once('test', force=True)
        original = dict(self.points)
        self.calls.clear()
        self.service.sync_once('test', force=True)
        self.assertFalse(any(path.endswith('/report') for path, _ in self.calls))
        store = ProgramStore(self.root / 'config')
        store.observe('test', 'ActionPoint', {'Total': 8100}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
        self.calls.clear()
        self.service.sync_once('test', force=True)
        report = next(body for path, body in self.calls if path.endswith('/report'))
        self.assertEqual(1, len(report['points']))
        self.assertEqual(8100, report['points'][0]['p'])
        self.assertGreater(report['points'][0]['t'], 1_000_000_000_000)
        store.observe('test', 'ActionPoint', {'Total': 8200}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
        self.service.sync_once('test', force=True)
        self.assertEqual(len(original) + 1, len(self.points))
        self.assertEqual(8200, self.points[report['points'][0]['t']])

    def test_background_detects_new_history_without_full_rescan_or_manifest(self):
        self.register()
        self.service.sync_once('test', force=True)
        store = ProgramStore(self.root / 'config')
        store.observe('test', 'ActionPoint', {'Total': 8300}, (self.now + timedelta(seconds=2)).isoformat(), 'fixture')
        self.calls.clear()
        self.service.sync_once('test')
        reports = [body for path, body in self.calls if path.endswith('/report')]
        self.assertEqual(1, len(reports))
        self.assertEqual([8300], [point['p'] for point in reports[0]['points']])
        self.assertFalse(any(path.endswith('/manifest') for path, _ in self.calls))

    def test_upload_failure_retries_without_losing_history(self):
        self.register()
        with patch.object(self.service, '_remote', side_effect=ApiError('STOCK_UNAVAILABLE', '隔离断网')):
            with self.assertRaises(ApiError):
                self.service.sync_once('test', force=True)
        self.assertEqual({}, self.points)
        self.service.sync_once('test', force=True)
        self.assertTrue(self.points)
        self.assertFalse(self.service.history.pending['test'])

    def test_month_manifest_repairs_older_missing_point(self):
        self.register()
        self.service.sync_once('test', force=True)
        expected = dict(self.points)
        self.points.clear()
        self.service.sync_once('test', force=True)
        self.assertEqual(expected, self.points)
        self.assertTrue(any(path.endswith('/manifest') for path, _ in self.calls))

    def test_unavailable_exchange_does_not_change_local_identity(self):
        self.register()
        identity = self.service.status('test')['instanceId']
        with patch.object(self.service, '_remote', side_effect=ApiError('STOCK_UNAVAILABLE', '隔离断网')):
            result = self.service.status('test', refresh=True)
        self.assertEqual(identity, result['instanceId'])
        self.assertTrue(result['registered'])

    def test_binding_state_is_refreshed_without_trading_session(self):
        self.register()
        self.stock['bound'] = True
        result = self.service.status('test', refresh=True)
        self.assertTrue(result['bound'])
        self.assertFalse(hasattr(self.service, 'sessions'))

    def test_default_origin_and_origin_validation(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual('https://stock.azurpilot.com', exchange_url())
        for value in ('http://example.com', 'https://user:secret@example.com', 'https://example.com/path', 'https://example.com?x=1'):
            with self.subTest(value=value), patch.dict('os.environ', {'STOCK_EXCHANGE_URL': value}):
                with self.assertRaises(ApiError):
                    exchange_url()

    def test_remote_uses_shared_transport_and_azurpilot_user_agent(self):
        response = MagicMock(content=b'{"ok":true}', status_code=200)
        response.__enter__.return_value = response
        with patch.dict('os.environ', {'STOCK_EXCHANGE_URL': 'https://stock.azurpilot.com'}), \
                patch('module.base.http.niquests.Session.request', return_value=response) as send:
            reply = StockExchangeService._remote(self.service, '/v2/instance/report', 'POST', {'points': []})
        self.assertEqual(('POST', 'https://stock.azurpilot.com/api/v2/instance/report'), send.call_args.args)
        self.assertEqual(http.USER_AGENT, send.call_args.kwargs['headers']['User-Agent'])
        self.assertEqual('application/json', send.call_args.kwargs['headers']['Content-Type'])
        self.assertEqual(b'{"points":[]}', send.call_args.kwargs['data'])
        self.assertEqual(12, send.call_args.kwargs['timeout'])
        self.assertEqual({'status': 200, 'data': {'ok': True}}, reply)

    def test_remote_preserves_v2_error_code_from_shared_transport_response(self):
        response = MagicMock(content=b'{"error":{"code":"STOCK_DELETED","message":"deleted"}}', status_code=410)
        response.__enter__.return_value = response
        with patch('module.api.stock_exchange_service.http.request', return_value=response):
            reply = StockExchangeService._remote(self.service, '/v2/instance/status')
        self.assertEqual(410, reply['status'])
        with self.assertRaises(ApiError) as caught:
            self.service._accepted(reply)
        self.assertEqual('STOCK_DELETED', caught.exception.code)

    def test_remote_maps_shared_transport_failures_to_unavailable(self):
        for error in (http.RequestException('fixture'), TimeoutError('fixture'), OSError('fixture')):
            with self.subTest(error=type(error).__name__), \
                    patch('module.api.stock_exchange_service.http.request', side_effect=error):
                with self.assertRaises(ApiError) as caught:
                    StockExchangeService._remote(self.service, '/v2/instance/status')
                self.assertEqual('STOCK_UNAVAILABLE', caught.exception.code)

    def test_remote_rejects_invalid_json_from_shared_transport(self):
        response = MagicMock(content=b'<html>fixture</html>', status_code=502)
        response.__enter__.return_value = response
        with patch('module.api.stock_exchange_service.http.request', return_value=response):
            with self.assertRaises(ApiError) as caught:
                StockExchangeService._remote(self.service, '/v2/instance/status')
        self.assertEqual('STOCK_INVALID_RESPONSE', caught.exception.code)

    def test_remote_deletion_stops_upload_and_persists_across_restart(self):
        self.register()
        self.service.sync_once('test', force=True)
        def deleted(*_args, **_kwargs):
            return {'status': 410, 'data': {'error': {'code': 'STOCK_DELETED', 'message': '股票已删除'}}}
        self.service._remote = Mock(side_effect=deleted)
        self.service.sync_once('test', force=True)
        self.assertNotIn('test', self.service.monitors)
        self.assertTrue(self.service.bindings['test']['deleted'])
        self.service._remote.reset_mock()
        self.service.sync_once('test', force=True)
        self.assertTrue(self.service.status('test', refresh=True)['deleted'])
        self.service._remote.assert_not_called()
        self.service.close()
        cold = StockExchangeService(self.configs)
        self.addCleanup(cold.close)
        cold.start = Mock()
        cold._remote = Mock(side_effect=AssertionError('删除后不应发起网络请求'))
        self.assertNotIn('test', cold.monitors)
        self.assertTrue(cold.status('test', refresh=True)['deleted'])
        cold.sync_once('test', force=True)
        with self.assertRaises(ApiError) as caught:
            cold.register('test', '不能复活')
        self.assertEqual('STOCK_DELETED', caught.exception.code)
        cold._remote.assert_not_called()

    def test_deleted_remote_identity_without_local_binding_is_remembered(self):
        self.service._remote = Mock(return_value={'status': 410, 'data': {'error': {'code': 'STOCK_DELETED', 'message': '股票已删除'}}})
        result = self.service.status('test', refresh=True)
        self.assertTrue(result['deleted'])
        self.service._remote.reset_mock()
        self.assertTrue(self.service.status('test', refresh=True)['deleted'])
        self.service._remote.assert_not_called()

    def test_new_stock_requires_explicit_public_notice_confirmation(self):
        with self.assertRaises(ApiError) as caught:
            self.service.register('test', '未确认股票')
        self.assertEqual('STOCK_NOTICE_REQUIRED', caught.exception.code)
        self.assertFalse(self.calls)

    def test_register_rejects_empty_name(self):
        for name in ('', '  ', '测', '测' * 33, '测\n试', '测\x00试'):
            with self.assertRaises(ApiError):
                self.service.register('test', name)


if __name__ == '__main__':
    unittest.main()
