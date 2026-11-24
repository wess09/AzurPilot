"""背景 HTTP 上传与代抓沿用 WebSocket 的授权边界。"""
import tempfile
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from module.api.app import create_app
from tests.test_api import fixture


class BackgroundAuthTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = fixture(directory.name)
        library = patch('module.api.app.LIBRARY_DIR', self.root / 'background-library')
        library.start()
        self.addCleanup(library.stop)

    def app(self, password='test-secret'):
        return create_app(root=self.root, password=password, manage_runtime=False, mount_mcp=False)

    def token(self, client, password='test-secret'):
        with client.websocket_connect('/api/v1/ws') as ws:
            session = ws.receive_json()
            if session['data']['authRequired']:
                ws.send_json({'v': 1, 'type': 'request', 'id': 'login', 'method': 'auth.login',
                              'params': {'password': password}})
                self.assertTrue(ws.receive_json()['ok'])
            ws.send_json({'v': 1, 'type': 'request', 'id': 'token', 'method': 'background.access', 'params': {}})
            return ws.receive_json()['result']['token']

    def test_unauthenticated_websocket_cannot_issue_token(self):
        with TestClient(self.app()) as client, client.websocket_connect('/api/v1/ws') as ws:
            self.assertTrue(ws.receive_json()['data']['authRequired'])
            ws.send_json({'v': 1, 'type': 'request', 'id': 'token', 'method': 'background.access', 'params': {}})
            self.assertEqual('UNAUTHORIZED', ws.receive_json()['error']['code'])

    def test_missing_or_invalid_token_cannot_fetch_or_upload(self):
        with TestClient(self.app()) as client, patch('module.api.app.proxy_fetch') as fetch, \
                patch('module.api.app.gallery_add_bytes') as add:
            for token in ('', 'invalid', '非法令牌'):
                with self.subTest(token=token):
                    response = client.get('/api/v1/background/media', params={'url': 'https://example.com/a.png', 'token': token})
                    self.assertEqual(401, response.status_code)
            self.assertEqual(401, client.post('/api/v1/background/gallery').status_code)
            self.assertEqual(401, client.post('/api/v1/background/gallery', headers={'x-azurpilot-background-token': 'invalid'}).status_code)
            fetch.assert_not_called()
            add.assert_not_called()

    def test_authenticated_token_supports_media_and_upload(self):
        with TestClient(self.app()) as client, patch('module.api.app.proxy_fetch', return_value=(b'image', 'image/png')) as fetch, \
                patch('module.api.app.gallery_add_bytes', return_value={'id': 'sample'}) as add:
            token = self.token(client)
            self.assertNotEqual('test-secret', token)
            for headers, params in (({}, {'token': token}), ({'x-azurpilot-background-token': token}, {})):
                response = client.get('/api/v1/background/media', headers=headers, params={'url': 'https://example.com/a.png', **params})
                self.assertEqual(200, response.status_code)
                self.assertEqual(b'image', response.content)
            self.assertEqual(2, fetch.call_count)
            response = client.post('/api/v1/background/gallery', headers={'x-azurpilot-background-token': token},
                                   files={'file': ('test.png', b'image', 'image/png')})
            self.assertEqual(200, response.status_code)
            add.assert_called_once_with(b'image', 'test.png', 'image/png', legacy=False)
            # 媒体 URL 中的令牌不能通过查询参数授权上传。
            self.assertEqual(401, client.post('/api/v1/background/gallery', params={'token': token}).status_code)
            self.assertEqual(1, add.call_count)

    def test_new_application_rejects_previous_token(self):
        with TestClient(self.app()) as client:
            old_token = self.token(client)
        with TestClient(self.app()) as client, patch('module.api.app.proxy_fetch') as fetch:
            self.assertNotEqual(old_token, self.token(client))
            response = client.get('/api/v1/background/media', params={'url': 'https://example.com/a.png', 'token': old_token})
            self.assertEqual(401, response.status_code)
            fetch.assert_not_called()

    def test_passwordless_mode_can_issue_background_token(self):
        with TestClient(self.app(password='')) as client, patch('module.api.app.proxy_fetch', return_value=(b'image', 'image/png')):
            response = client.get('/api/v1/background/media', params={'url': 'https://example.com/a.png', 'token': self.token(client)})
            self.assertEqual(200, response.status_code)
