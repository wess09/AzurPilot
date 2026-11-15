"""验证公网候选、远程认证标记及双向代理，不接触真实游戏或公网隧道。"""

import asyncio
import hashlib
import hmac
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
from aiohttp import web
import pytest

from module.runtime.remote_cloudflare import CloudflareRemoteAccessProvider, RemoteIdentity
from module.runtime.remote_direct import DirectAccessServer, public_addresses


def test_only_public_interface_addresses_are_reported():
    addresses = ['127.0.0.1', '10.0.0.1', '100.64.0.1', '1.1.1.1', '192.0.2.1']
    entries = [SimpleNamespace(family=socket.AF_INET, address=address) for address in addresses]
    entries += [SimpleNamespace(family=socket.AF_INET6, address=address)
                for address in ['fe80::1%eth0', 'fc00::1', '2001:db8::1', '2606:4700:4700::1111']]
    with patch('psutil.net_if_addrs', return_value={'test': entries}):
        assert public_addresses() == {'ipv4': ['1.1.1.1'], 'ipv6': ['2606:4700:4700::1111']}


def test_default_reuses_existing_http_webui_port():
    async def scenario():
        provider = CloudflareRemoteAccessProvider()
        config = SimpleNamespace(WebuiPort=25548, WebuiHost='0.0.0.0', WebuiSSLCert=None,
                                 RemoteAccessPort=0, RemoteAccessPublicPort=0)
        with patch('module.runtime.setting.State.deploy_config', config), \
                patch.object(socket.socket, 'bind', side_effect=AssertionError('unexpected extra listener')):
            async with DirectAccessServer(provider).serve() as direct:
                assert direct.registration()['port'] == 25548
    asyncio.run(scenario())


def test_existing_webui_serves_device_health_and_probe(tmp_path):
    from starlette.testclient import TestClient
    from module.api.app import create_app
    from module.runtime.remote_cloudflare import cloudflare
    from tests.test_api import fixture

    identity = RemoteIdentity(tmp_path / 'identity')
    direct = DirectAccessServer(cloudflare)
    app = create_app(root=fixture(tmp_path), password='test-password',
                     manage_runtime=False, mount_mcp=False)
    with TestClient(app) as client:
        assert client.get('/api/v1/remote/probe?challenge=' + 'c' * 64).status_code == 503
        with patch.object(cloudflare, '_direct_server', direct), \
                patch.object(cloudflare, 'identity', return_value=identity):
            assert client.get('/healthz').json()['device_id'] == identity.load()['device_id']
            response = client.get('/api/v1/remote/probe?challenge=' + 'c' * 64)
            assert response.status_code == 200
            assert response.json()['proof'] == hmac.new(direct.probe_token.encode(), b'c' * 64, hashlib.sha256).hexdigest()
            assert direct.probe_token not in response.text
            assert client.get('/api/v1/remote/probe?challenge=invalid').status_code == 400


def test_http_and_websocket_proxy_preserve_remote_authentication(tmp_path):
    async def scenario():
        application = web.Application()

        async def endpoint(request):
            assert request.headers['x-azurpilot-remote-access'] == '1'
            if request.headers.get('Upgrade', '').lower() == 'websocket':
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        await ws.send_str(message.data)
                    elif message.type == aiohttp.WSMsgType.BINARY:
                        await ws.send_bytes(message.data)
                return ws
            return web.json_response({'query': request.query.get('value'), 'body': await request.text()})

        application.router.add_route('*', '/echo', endpoint)
        runner = web.AppRunner(application)
        await runner.setup()
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        upstream_port = listener.getsockname()[1]
        listener.setblocking(False)
        await web.SockSite(runner, listener).start()
        candidate = socket.socket()
        candidate.bind(('127.0.0.1', 0))
        direct_port = candidate.getsockname()[1]
        candidate.close()
        provider = CloudflareRemoteAccessProvider()
        config = SimpleNamespace(WebuiPort=upstream_port, WebuiHost='127.0.0.1', WebuiSSLCert=None,
                                 RemoteAccessPort=direct_port, RemoteAccessPublicPort=0)
        try:
            with patch('module.runtime.setting.State.deploy_config', config), \
                    patch.object(provider, 'identity', return_value=RemoteIdentity(tmp_path)):
                async with DirectAccessServer(provider).serve() as direct, aiohttp.ClientSession() as session:
                    base = f'http://127.0.0.1:{direct_port}'
                    async with session.post(base + '/echo?value=preserved', data='hello') as response:
                        assert await response.json() == {'query': 'preserved', 'body': 'hello'}
                    async with session.ws_connect(base + '/echo') as ws:
                        await ws.send_str('text')
                        assert (await ws.receive()).data == 'text'
                        await ws.send_bytes(b'bytes')
                        assert (await ws.receive()).data == b'bytes'
                    challenge = 'c' * 64
                    async with session.get(base + '/api/v1/remote/probe?challenge=' + challenge) as response:
                        data = await response.json()
                        assert data['proof'] == hmac.new(direct.probe_token.encode(), challenge.encode(), hashlib.sha256).hexdigest()
                        assert direct.probe_token not in str(data)
                    async with session.get(base + '/healthz') as response:
                        assert (await response.json())['device_id'] == provider.identity().load()['device_id']
        finally:
            await runner.cleanup()
    asyncio.run(scenario())


def test_direct_ready_does_not_allocate_cloudflare(tmp_path):
    async def scenario():
        provider = CloudflareRemoteAccessProvider()
        registered = asyncio.Event()
        calls = []

        @asynccontextmanager
        async def serve(_):
            yield SimpleNamespace(registration=lambda: {'ipv4': ['1.1.1.1'], 'ipv6': [], 'port': 25549,
                                                         'probe_token': 'p' * 43})

        async def request(method, path, data=None):
            calls.append((method, data))
            registered.set()
            return {'url': 'https://registry.example/d/test/', 'endpoints': [{'url': 'http://1.1.1.1:25549'}],
                    'fallback_required': False}

        with patch('module.runtime.setting.State.deploy_config', SimpleNamespace(Password='test-password')), \
                patch.object(provider, 'identity', return_value=RemoteIdentity(tmp_path)), \
                patch.object(provider, 'request', side_effect=request), \
                patch.object(DirectAccessServer, 'serve', serve), patch.object(provider, '_tunnel') as tunnel:
            task = asyncio.create_task(provider._connect())
            await asyncio.wait_for(registered.wait(), 3)
            assert provider.state == 'direct_ready'
            assert provider.address
            tunnel.assert_not_called()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert calls[0][1]['tunnel_url'] == ''
            assert calls[-1][0] == 'DELETE'
    asyncio.run(scenario())


@pytest.mark.parametrize('unavailable', ['socket.socket.bind', 'module.runtime.remote_direct.socket.socket'])
def test_unavailable_listener_reports_no_direct_candidates(unavailable):
    async def scenario():
        provider = CloudflareRemoteAccessProvider()
        config = SimpleNamespace(WebuiPort=25548, WebuiHost='127.0.0.1', WebuiSSLCert=None,
                                 RemoteAccessPort=25549, RemoteAccessPublicPort=0)
        with patch('module.runtime.setting.State.deploy_config', config), \
                patch(unavailable, side_effect=OSError('listener unavailable')), \
                patch('module.runtime.remote_direct.public_addresses', return_value={
                    'ipv4': ['1.1.1.1'], 'ipv6': ['2606:4700:4700::1111']}):
            async with DirectAccessServer(provider).serve() as direct:
                registration = direct.registration()
                assert registration['ipv4'] == []
                assert registration['ipv6'] == []
                assert registration['port'] == 25549
    asyncio.run(scenario())


def test_no_direct_route_starts_cloudflare(tmp_path):
    async def scenario():
        provider = CloudflareRemoteAccessProvider()
        started = asyncio.Event()

        @asynccontextmanager
        async def serve(_):
            yield SimpleNamespace(registration=lambda: {'ipv4': [], 'ipv6': [], 'port': 25549,
                                                         'probe_token': 'p' * 43})

        async def request(method, path, data=None):
            return {'url': 'https://registry.example/d/test/', 'endpoints': [], 'fallback_required': True}

        async def tunnel(managed=False):
            assert managed
            started.set()
            await asyncio.Future()

        with patch('module.runtime.setting.State.deploy_config', SimpleNamespace(Password='test-password')), \
                patch.object(provider, 'identity', return_value=RemoteIdentity(tmp_path)), \
                patch.object(provider, 'request', side_effect=request), \
                patch.object(DirectAccessServer, 'serve', serve), patch.object(provider, '_tunnel', tunnel):
            task = asyncio.create_task(provider._connect())
            await asyncio.wait_for(started.wait(), 3)
            assert provider.address == 'https://registry.example/d/test/'
            assert provider.state == 'registered'
            assert not provider._tunnel_ready
            assert provider.error == ''
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
