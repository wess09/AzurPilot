"""隔离验证 Quick Tunnel 的身份、配对鉴权及进程恢复，不连接真实游戏。"""

import asyncio
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from module.api.protocol import ApiError
from module.api.socket import Gateway
from module.runtime.remote_cloudflare import CloudflareRemoteAccessProvider, RemoteIdentity, TunnelHealthError, registry_url


def test_device_identity_survives_restart_and_client_revocation():
    with tempfile.TemporaryDirectory() as directory:
        store = RemoteIdentity(directory)
        first = store.load()
        assert RemoteIdentity(directory).load() == first
        client_id, token = store.add_client()
        assert store.accepts(token)
        assert token not in store.path.read_text(encoding='utf-8')
        assert not store.accepts(secrets.token_urlsafe(32))
        gateway = Gateway(SimpleNamespace(configs=SimpleNamespace(directory=Path(directory))), 'webui-password')
        gateway.authenticate('paired', token)
        gateway.authenticate('owner', 'webui-password')
        store.remove_client(client_id)
        with pytest.raises(ApiError, match='访问密码不正确'):
            gateway.authenticate('revoked', token)


def test_invalid_registry_and_corrupted_identity_fail_closed():
    for url in ('http://example.com', 'https://user:password@example.com', 'file:///tmp',
                'https://example.com?key=secret', 'https://example.com#fragment'):
        with pytest.raises(ValueError):
            registry_url(url)
    assert registry_url('http://127.0.0.1:18882/') == 'http://127.0.0.1:18882'
    assert registry_url('https://ap-remote.108-186-180-52.sslip.io:8443/') == 'https://remote.azurpilot.com'
    with tempfile.TemporaryDirectory() as directory:
        store = RemoteIdentity(directory)
        store.load()
        store.path.write_text('{invalid', encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            store.load()
        assert store.path.read_text(encoding='utf-8') == '{invalid'


def test_quoted_empty_device_ids_are_repaired_without_losing_credentials():
    for empty in ('', '""', "''"):
        with tempfile.TemporaryDirectory() as directory:
            store = RemoteIdentity(directory, device_id=empty)
            first = store.load()
            client_id, token = store.add_client()
            data = json.loads(store.path.read_text())
            data['device_id'] = empty
            store.save(data)
            repaired = RemoteIdentity(directory, device_id=empty).load()
            assert len(repaired['device_id']) == 32
            assert repaired['device_id'] not in ('', '""', "''")
            assert repaired['device_key'] == first['device_key']
            assert store.accepts(token)
            assert repaired['clients'][0]['id'] == client_id
            assert RemoteIdentity(directory).load() == repaired
    with pytest.raises(ValueError, match='CloudflareDeviceId'):
        RemoteIdentity(device_id='invalid')


def test_failed_pair_creation_removes_unused_local_credential():
    with tempfile.TemporaryDirectory() as directory:
        provider = CloudflareRemoteAccessProvider()
        provider.address = 'https://example.com/d/test/'
        async def unavailable(*args):
            raise ValueError('HTTP 503')
        with patch.object(provider, 'identity', return_value=RemoteIdentity(directory)), \
                patch.object(provider, 'request', side_effect=unavailable):
            with pytest.raises(ValueError):
                provider.create_pairing()
        assert RemoteIdentity(directory).load()['clients'] == []


def test_stop_interrupts_reconnect_backoff_and_start_is_idempotent():
    provider = CloudflareRemoteAccessProvider()
    attempted = threading.Event()
    async def unavailable():
        attempted.set()
        raise ValueError('模拟注册暂不可用')
    with patch.object(provider, '_connect', side_effect=unavailable):
        provider.start()
        thread = provider.thread
        provider.start()
        assert provider.thread is thread
        assert attempted.wait(3)
        provider.stop()
        assert not provider.is_alive()
        assert provider.state == 'stopped'


def test_pyflared_import_uses_project_cache_when_user_data_is_denied():
    # 新进程保证 pyflared 尚未导入，真实覆盖它在导入阶段创建数据目录的行为。
    script = '''
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import platformdirs
original = platformdirs.user_data_dir
def deny_global(appname=None, appauthor=None, *args, **kwargs):
    if appname == "pyflared":
        raise PermissionError("全局库目录禁止写入")
    return original(appname, appauthor, *args, **kwargs)
platformdirs.user_data_dir = deny_global
from module.runtime import remote_cloudflare as remote
class ReachedProcess(Exception): pass
class FakeContext:
    async def stream_chunker(self, stream, channel): return b""
    async def __aenter__(self): raise ReachedProcess()
    async def __aexit__(self, *args): pass
original_context = remote._quick_tunnel_context
def initialize(service):
    original_context(service).cmd_args.close()
    return FakeContext()
config = SimpleNamespace(Password="test-password", WebuiSSLCert=None, WebuiHost="127.0.0.1", WebuiPort=25548)
with patch.object(remote, "_quick_tunnel_context", side_effect=initialize), patch("module.runtime.setting.State.deploy_config", config):
    try: asyncio.run(remote.CloudflareRemoteAccessProvider()._tunnel())
    except ReachedProcess: pass
    else: raise AssertionError("未进入实际 provider 的进程启动阶段")
from pyflared.core.repository import sqlite_file_name, user_data_dir
expected = Path.cwd() / "cache/cloudflare/pyflared/cache.db"
assert sqlite_file_name() == expected, sqlite_file_name()
assert expected.parent.is_dir()
assert platformdirs.user_data_dir is deny_global
assert user_data_dir("another-app", "another-author") == original("another-app", "another-author")
'''
    subprocess.run([sys.executable, '-c', script], check=True, capture_output=True,
                   text=True, encoding='utf-8', errors='replace', timeout=30)


def test_exception_groups_expose_the_actionable_failure():
    from module.runtime.remote_cloudflare import _failure_reason
    error = ExceptionGroup('tasks', [ValueError('远程注册服务返回 HTTP 503'),
                                   ExceptionGroup('nested', [PermissionError(13, '拒绝访问', 'cache/cloudflare')])])
    reason = _failure_reason(error)
    assert 'HTTP 503' in reason
    assert 'cache/cloudflare' in reason
    assert 'ExceptionGroup' not in reason


def test_quick_tunnel_registration_and_cleanup_use_current_url():
    class FakeProcess:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def __aiter__(self):
            async def events():
                yield SimpleNamespace(data=b'https://new-url.trycloudflare.com')
                await asyncio.Future()
            return events()
        async def stream_chunker(self, stream, channel):
            return b''

    async def scenario(directory):
        provider = CloudflareRemoteAccessProvider()
        registered = asyncio.Event()
        requests = []
        async def request(method, path, data=None):
            requests.append((method, path, data))
            if method == 'POST':
                registered.set()
                return {'url': 'https://registry.example/d/device/'}
            return {'ok': True}
        config = SimpleNamespace(Password='strong-password', WebuiSSLCert=None, WebuiHost='127.0.0.1', WebuiPort=25548)
        # pyflared 导入会初始化个人目录；隔离测试将它定向至夹具目录。
        with patch('platformdirs.user_data_dir', return_value=directory):
            import pyflared
        with patch.object(pyflared, 'run_quick_tunnel', return_value=FakeProcess()) as quick, \
                patch('module.runtime.setting.State.deploy_config', config), \
                patch.object(provider, 'identity', return_value=RemoteIdentity(directory)), \
                patch.object(provider, 'check_tunnel', return_value=None), \
                patch.object(provider, 'request', side_effect=request):
            task = asyncio.create_task(provider._tunnel())
            await asyncio.wait_for(registered.wait(), 3)
            assert provider.address == 'https://registry.example/d/device/'
            assert requests[0][2]['tunnel_url'] == 'https://new-url.trycloudflare.com'
            assert requests[0][1] == '/api/v1/devices/register'
            assert provider.get_connection_state() == 'cloudflare_ready'
            quick.assert_called_once_with('http://127.0.0.1:25548')
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert requests[-1][0] == 'DELETE'
            assert requests[-1][1].startswith('/api/v1/devices/')
            assert provider.address == ''
    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(scenario(directory))


@pytest.mark.parametrize('failed_step', ['probe', 'register'])
def test_network_failure_retries_without_reallocating_tunnel(failed_step):
    class Process:
        def __init__(self):
            self.entered = self.exited = 0
        async def __aenter__(self):
            self.entered += 1
            return self
        async def __aexit__(self, *args):
            self.exited += 1
        def __aiter__(self):
            async def events():
                yield SimpleNamespace(data=b'https://retained.trycloudflare.com')
                await asyncio.Future()
            return events()

    async def scenario(directory):
        provider, process = CloudflareRemoteAccessProvider(), Process()
        recovered = asyncio.Event()
        calls = []
        probes = []
        async def check_tunnel(url):
            probes.append(url)
            if failed_step == 'probe' and len(probes) == 1:
                raise ValueError('Quick Tunnel 公网健康检查域名解析失败')
        async def request(method, path, data=None):
            if method == 'POST':
                calls.append(data['tunnel_url'])
                if failed_step == 'register' and len(calls) == 1:
                    raise ValueError('远程注册服务返回 HTTP 503')
                recovered.set()
                return {'url': 'https://registry.example/d/device/'}
            return {'ok': True}
        config = SimpleNamespace(Password='strong-password', WebuiSSLCert=None,
                                 WebuiHost='127.0.0.1', WebuiPort=25548)
        with patch('module.runtime.setting.State.deploy_config', config), \
                patch('module.runtime.remote_cloudflare._quick_tunnel_context', return_value=process) as factory, \
                patch.object(provider, 'identity', return_value=RemoteIdentity(directory)), \
                patch.object(provider, 'check_tunnel', side_effect=check_tunnel), \
                patch.object(provider, 'request', side_effect=request):
            task = asyncio.create_task(provider._tunnel())
            await asyncio.wait_for(recovered.wait(), 5)
            assert provider.state == 'cloudflare_ready'
            assert calls == ['https://retained.trycloudflare.com'] * (2 if failed_step == 'register' else 1)
            assert probes == ['https://retained.trycloudflare.com'] * 2
            assert process.entered == 1 and process.exited == 0
            factory.assert_called_once()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert process.exited == 1
    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(scenario(directory))


def test_persistent_530_rebuilds_without_blocking_registered_entry(tmp_path):
    class Process:
        exited = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.exited = True

        def __aiter__(self):
            async def events():
                yield SimpleNamespace(data=b'https://unready.trycloudflare.com')
                await asyncio.Future()
            return events()

    async def scenario():
        provider, process = CloudflareRemoteAccessProvider(), Process()
        provider.address = 'https://registry.example/d/device/'
        provider.state = 'registered'
        config = SimpleNamespace(Password='test-password', WebuiSSLCert=None,
                                 WebuiHost='127.0.0.1', WebuiPort=25548)
        with patch('module.runtime.setting.State.deploy_config', config), \
                patch('module.runtime.remote_cloudflare.TUNNEL_UNREADY_TIMEOUT', 0), \
                patch('module.runtime.remote_cloudflare._quick_tunnel_context', return_value=process), \
                patch.object(provider, 'identity', return_value=RemoteIdentity(tmp_path)), \
                patch.object(provider, 'check_tunnel', side_effect=TunnelHealthError(530)):
            with pytest.raises(ExceptionGroup, match='TaskGroup'):
                await asyncio.wait_for(provider._tunnel(managed=True), 3)
            assert process.exited
            assert provider._tunnel_protocol == 'http2'
            assert provider.address == 'https://registry.example/d/device/'
            assert provider.state == 'registered'
            assert provider.error == ''
    asyncio.run(scenario())


def test_http2_context_passes_protocol_to_cloudflared():
    from module.runtime.remote_cloudflare import _quick_tunnel_context

    async def scenario():
        context = _quick_tunnel_context('http://127.0.0.1:25548', protocol='http2')
        arguments = await context.cmd_args
        assert arguments == ('tunnel', '--protocol', 'http2', '--no-autoupdate', '--url',
                             'http://127.0.0.1:25548')
    asyncio.run(scenario())


def test_requests_use_environment_proxy_without_origin_netrc_credentials(tmp_path):
    from aiohttp import web
    from module.runtime.remote_cloudflare import _request_proxy

    async def scenario():
        provider = CloudflareRemoteAccessProvider()
        identity = RemoteIdentity(tmp_path)
        requests = []
        async def proxy(request):
            requests.append(request.raw_path)
            if request.path == '/healthz':
                assert 'Authorization' not in request.headers
                return web.json_response({'status': 'ok', 'protocolVersion': 1})
            assert request.headers['Authorization'] == 'Bearer ' + identity.load()['device_key']
            assert await request.json() == {'tunnel_url': 'https://test.trycloudflare.com'}
            return web.json_response({'url': 'https://registry.example/d/device/'})

        app = web.Application()
        app.router.add_route('*', '/{path:.*}', proxy)
        runner = web.AppRunner(app)
        await runner.setup()
        server = await asyncio.get_running_loop().create_server(runner.server, '127.0.0.1', 0)
        proxy_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        netrc = tmp_path / 'netrc'
        netrc.write_text('machine ap-health.invalid login probe-user password probe-password\n')
        try:
            with patch.dict(os.environ, {'http_proxy': proxy_url, 'https_proxy': proxy_url,
                                         'no_proxy': '127.0.0.1,localhost', 'NETRC': str(netrc)}, clear=True), \
                    patch.object(provider, 'identity', return_value=identity), \
                    patch.object(provider, 'registry', return_value='http://registry.invalid'):
                assert _request_proxy('https://ap-health.invalid') == proxy_url
                assert _request_proxy('http://127.0.0.1') is None
                assert _request_proxy('http://localhost') is None
                await provider.check_tunnel('http://ap-health.invalid')
                result = await provider.request('POST', '/api/v1/devices/register', {
                    'tunnel_url': 'https://test.trycloudflare.com',
                })
                assert result['url'] == 'https://registry.example/d/device/'
            assert requests == ['http://ap-health.invalid/healthz',
                                'http://registry.invalid/api/v1/devices/register']
        finally:
            server.close()
            await server.wait_closed()
            await runner.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('kind, expected', [
    ('dns', '域名解析失败'), ('proxy', '代理连接失败'), ('proxy_http', 'HTTP 407'),
    ('certificate', '证书校验失败'), ('tls', 'TLS 握手失败'),
    ('connection', '错误码 10061'), ('timeout', '超时'), ('disconnected', 'ServerDisconnectedError'),
])
def test_public_probe_reports_specific_errors_without_sensitive_details(kind, expected):
    import ssl
    import aiohttp

    sensitive = 'proxy-user:proxy-password@private-host.invalid'
    errors = {
        'dns': aiohttp.ClientConnectorDNSError(None, OSError(11001, sensitive)),
        'proxy': aiohttp.ClientProxyConnectionError(None, OSError(10061, sensitive)),
        'proxy_http': aiohttp.ClientHttpProxyError(None, (), status=407, message=sensitive),
        'certificate': aiohttp.ClientConnectorCertificateError(None, ssl.SSLCertVerificationError(sensitive)),
        'tls': aiohttp.ClientConnectorSSLError(None, ssl.SSLError(sensitive)),
        'connection': aiohttp.ClientConnectorError(None, OSError(10061, sensitive)),
        'timeout': TimeoutError(sensitive),
        'disconnected': aiohttp.ServerDisconnectedError(sensitive),
    }
    with patch('aiohttp.ClientSession.get', side_effect=errors[kind]):
        with pytest.raises(ValueError, match=expected) as error:
            asyncio.run(CloudflareRemoteAccessProvider().check_tunnel('https://test.trycloudflare.com'))
    assert sensitive not in str(error.value)


def test_public_probe_requires_ap_protocol_and_never_follows_redirects():
    from aiohttp import web
    async def scenario():
        mode = 'unhealthy'
        redirected = []
        async def health(request):
            assert 'Authorization' not in request.headers
            if mode == 'redirect':
                raise web.HTTPFound('/unexpected')
            if mode == 'html':
                return web.Response(text='<html>代理错误页</html>', content_type='text/html')
            if mode == 'invalid_json':
                return web.Response(text='{invalid', content_type='application/json')
            if mode == 'array':
                return web.json_response([])
            return web.json_response({'status': 'ok', 'protocolVersion': 1 if mode == 'healthy' else 0})
        async def unexpected(request):
            redirected.append(True)
            return web.Response()
        app = web.Application()
        app.router.add_get('/healthz', health)
        app.router.add_get('/unexpected', unexpected)
        runner = web.AppRunner(app)
        await runner.setup()
        server = await asyncio.get_running_loop().create_server(runner.server, '127.0.0.1', 0)
        url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        try:
            provider = CloudflareRemoteAccessProvider()
            for mode in ('unhealthy', 'html', 'invalid_json', 'array'):
                with pytest.raises(ValueError, match='AP 协议'):
                    await provider.check_tunnel(url)
            mode = 'redirect'
            with pytest.raises(ValueError, match='HTTP 302'):
                await provider.check_tunnel(url)
            assert not redirected
            mode = 'healthy'
            await provider.check_tunnel(url)
        finally:
            server.close()
            await server.wait_closed()
            await runner.cleanup()
    asyncio.run(scenario())


def test_remote_registry_error_masks_id_and_pairing_status_handles_expired():
    from module.runtime.remote_cloudflare import RemoteRegistryError
    from module.api.remote_service import pairing_status

    err = RemoteRegistryError(404, 'PAIRING_EXPIRED', '配对已过期', 'GET', '/api/v1/pairings/1234567890abcdef1234')
    assert '/<id>' in str(err)
    assert '1234567890abcdef1234' not in str(err)
    assert err.code == 'PAIRING_EXPIRED'

    with patch('module.api.remote_service.cloudflare.request', side_effect=err):
        assert pairing_status('1234567890abcdef1234') == {'state': 'expired'}
