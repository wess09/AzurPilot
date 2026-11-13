"""APU imports remain consistent across updates and service restarts."""

import io
import json
import tempfile
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from module.api.app import create_app
from module.api.plugin_service import PluginService
from tests.test_api import fixture


def package(manifest, files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        for name, contents in (files or {}).items():
            archive.writestr(name, contents)
    return output.getvalue()


def test_install_update_and_remove():
    with tempfile.TemporaryDirectory() as directory:
        service = PluginService(Path(directory))
        manifest = {'id': 'bridge', 'name': 'Bridge', 'version': '1', 'apiVersion': 1}
        data = package(manifest, {'styles/main.css': 'body {}'})
        service.install(data)
        assert service.list() == [{'manifest': manifest, 'enabled': False, 'revision': sha256(data).hexdigest()}]
        assert service.set_enabled('bridge', True)
        updated = {**manifest, 'version': '2'}
        data = package(updated)
        service.install(data)
        assert PluginService(Path(directory)).list() == [{'manifest': updated, 'enabled': True, 'revision': sha256(data).hexdigest()}]
        assert service.remove('bridge')
        assert not service.remove('bridge')


def test_invalid_update_does_not_replace_installed_package():
    with tempfile.TemporaryDirectory() as directory:
        service = PluginService(Path(directory))
        manifest = {'id': 'bridge', 'name': 'Bridge', 'version': '1', 'apiVersion': 1}
        data = package(manifest)
        service.install(data)
        with pytest.raises(ValueError):
            service.install(package({**manifest, 'version': '2'}, {'../outside': 'bad'}))
        assert service.list() == [{'manifest': manifest, 'enabled': False, 'revision': sha256(data).hexdigest()}]


def test_page_and_panel_icons_must_exist_in_package():
    with tempfile.TemporaryDirectory() as directory:
        service = PluginService(Path(directory))
        manifest = {'id': 'bridge', 'name': 'Bridge', 'version': '1', 'apiVersion': 1,
                    'pages': [{'id': 'view', 'title': 'View', 'entry': 'ui/index.html', 'icon': 'assets/star.svg'}],
                    'panels': [{'id': 'panel', 'title': 'Panel', 'entry': 'ui/index.html', 'icon': 'assets/star.svg'}]}
        files = {'ui/index.html': '<p>ok</p>'}
        with pytest.raises(ValueError):
            service.install(package(manifest, files))
        data = package(manifest, {**files, 'assets/star.svg': '<svg xmlns="http://www.w3.org/2000/svg"/>'})
        service.install(data)
        stored = service.list()[0]['manifest']
        assert stored['pages'][0]['icon'] == 'assets/star.svg'
        assert stored['panels'][0]['icon'] == 'assets/star.svg'


def test_http_import_requires_auth_and_survives_restart():
    with tempfile.TemporaryDirectory() as directory:
        root = fixture(directory)
        manifest = {'id': 'bridge', 'name': 'Bridge', 'version': '1', 'apiVersion': 1,
                    'permissions': ['storage'], 'pages': [{'id': 'view', 'title': 'View', 'entry': 'ui/index.html'}],
                    'theme': {'styles': {'scheduler': 'style.css'}}}
        data = package(manifest, {'ui/index.html': '<script></script>', 'style.css': ':scope {color:red}'})
        revision = sha256(data).hexdigest()
        asset_url = f'/api/v1/plugins/bridge/{revision}'

        def app():
            return create_app(root=root, password='secret', manage_runtime=False, mount_mcp=False)

        with TestClient(app()) as client:
            assert client.get('/api/v1/plugins').status_code == 401
            assert client.post('/api/v1/plugins', content=data).status_code == 401
            with client.websocket_connect('/api/v1/ws') as ws:
                ws.receive_json()
                ws.send_json({'v': 1, 'type': 'request', 'id': 'login', 'method': 'auth.login', 'params': {'password': 'secret'}})
                assert ws.receive_json()['ok']
                ws.send_json({'v': 1, 'type': 'request', 'id': 'token', 'method': 'plugins.access', 'params': {}})
                token = ws.receive_json()['result']['token']
            headers = {'x-azurpilot-plugin-token': token}
            response = client.post('/api/v1/plugins', headers=headers, content=data)
            assert response.status_code == 200
            assert client.get(f'{asset_url}/ui/index.html').status_code == 404
            assert client.patch('/api/v1/plugins/bridge', headers=headers, json={'enabled': True}).status_code == 200
            view = client.get(f'{asset_url}/ui/index.html')
            assert view.status_code == 200
            assert 'sandbox allow-scripts' in view.headers['Content-Security-Policy']
            assert f'http://testserver{asset_url}/' in view.headers['Content-Security-Policy']
            assert '@scope ([data-apu-component="scheduler"])' in client.get(f'{asset_url}/style.css?component=scheduler').text
            service = client.app.state.gateway.router.plugins
            assert service.storage('bridge', 'testpilot', 'favorites', 'set', ['Guild']) == {'value': ['Guild']}
        restarted = PluginService(root / 'config')
        assert restarted.list() == [{'manifest': manifest, 'enabled': True, 'revision': revision}]
        assert restarted.storage('bridge', 'testpilot', 'favorites', 'get', None) == {'value': ['Guild']}
        assert restarted.storage('bridge', 'other', 'favorites', 'get', None) == {'value': None}


@pytest.mark.parametrize('css', [
    '@import "other.css";',
    ':scope { background: url(https://example.com/pixel.png) }',
    ':scope { background: image-set("https://example.com/pixel.png" 1x) }',
    '@media (width > 1px) { @font-face { font-family: unauthorized } }',
])
def test_theme_css_rejects_unscoped_or_external_rules(tmp_path, css):
    service = PluginService(tmp_path)
    manifest = {'id': 'bridge', 'name': 'Bridge', 'version': '1', 'apiVersion': 1,
                'theme': {'styles': {'scheduler': 'style.css'}}}
    with pytest.raises(ValueError):
        service.install(package(manifest, {'style.css': css}))
