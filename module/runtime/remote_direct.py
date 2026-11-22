"""公网候选地址发现及独立 HTTP/WS 入口，复用 WebUI 的认证网关。"""

import asyncio
import hashlib
import hmac
import ipaddress
import re
import secrets
import socket
from contextlib import asynccontextmanager

import aiohttp
from aiohttp import web
import psutil

from module.runtime.password_utils import REMOTE_ACCESS_HEADER


def public_addresses():
    """仅返回本机网卡上的公网地址，排除私网、共享地址及带作用域的 IPv6。"""
    result = {'ipv4': [], 'ipv6': []}
    try:
        interfaces = psutil.net_if_addrs()
    except (OSError, psutil.Error):
        return result
    for addresses in interfaces.values():
        for entry in addresses:
            if entry.family not in (socket.AF_INET, socket.AF_INET6) or '%' in entry.address:
                continue
            try:
                address = ipaddress.ip_address(entry.address)
            except ValueError:
                continue
            if not address.is_global or address.is_multicast or getattr(address, 'ipv4_mapped', None):
                continue
            family = 'ipv4' if address.version == 4 else 'ipv6'
            value = str(address)
            if value not in result[family]:
                result[family].append(value)
    return {family: sorted(addresses)[:4] for family, addresses in result.items()}


class DirectAccessServer:
    """将双栈 HTTP 入口转到本机 WebUI，所有转发均标记为远程访问。"""

    def __init__(self, provider):
        self.provider = provider
        self.probe_token = secrets.token_urlsafe(32)
        self.port = 0
        self.bound_families = set()

    def registration(self):
        """在本机重新发现地址，外部端口可与监听端口分别配置。"""
        from module.runtime.setting import State
        addresses = public_addresses()
        for family in addresses:
            if family not in self.bound_families:
                addresses[family] = []
        port = int(getattr(State.deploy_config, 'RemoteAccessPublicPort', 0) or self.port)
        if not 1 <= port <= 65535:
            raise ValueError('远程访问外部端口必须在 1–65535 之间')
        return {**addresses, 'port': port, 'probe_token': self.probe_token}

    def proof(self, challenge):
        """仅返回随机挑战的摘要，不通过探测接口暴露任何认证凭据。"""
        if not re.fullmatch(r'[a-f0-9]{32,128}', challenge):
            raise ValueError('无效探测挑战')
        return {
            'device_id': self.provider.identity().load()['device_id'],
            'proof': hmac.new(self.probe_token.encode(), challenge.encode(), hashlib.sha256).hexdigest(),
        }

    async def probe(self, request):
        """处理独立 HTTP 监听的挑战验证请求。"""
        try:
            result = self.proof(request.query.get('challenge', ''))
        except ValueError:
            raise web.HTTPBadRequest() from None
        return web.json_response(result, headers={'Cache-Control': 'no-store'})

    async def health(self, request):
        """为客户端提供无凭据的设备身份探测。"""
        return web.json_response({'status': 'ok', 'protocolVersion': 1,
                                  'device_id': self.provider.identity().load()['device_id']},
                                 headers={'Cache-Control': 'no-store'})

    async def proxy(self, request):
        """转发普通请求与 WebSocket，并在两端断开时回收对端连接。"""
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() not in ('connection', 'upgrade', 'transfer-encoding', 'host')}
        headers[REMOTE_ACCESS_HEADER] = '1'
        target = self.upstream + request.rel_url.raw_path_qs
        if request.headers.get('Upgrade', '').lower() == 'websocket':
            for key in list(headers):
                if key.lower().startswith('sec-websocket-'):
                    del headers[key]
            try:
                upstream = await self.session.ws_connect(target, headers=headers, max_msg_size=64*1024*1024)
            except (aiohttp.ClientError, TimeoutError):
                raise web.HTTPBadGateway() from None
            downstream = web.WebSocketResponse(max_msg_size=64*1024*1024, heartbeat=20)
            await downstream.prepare(request)

            async def forward(source, destination):
                async for message in source:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        await destination.send_str(message.data)
                    elif message.type == aiohttp.WSMsgType.BINARY:
                        await destination.send_bytes(message.data)

            tasks = [asyncio.create_task(forward(upstream, downstream)),
                     asyncio.create_task(forward(downstream, upstream))]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await upstream.close()
                await downstream.close()
            return downstream
        try:
            async with self.session.request(request.method, target, headers=headers,
                                            data=await request.read(), allow_redirects=False) as upstream:
                response = web.StreamResponse(status=upstream.status, headers={
                    key: value for key, value in upstream.headers.items()
                    if key.lower() not in ('connection', 'transfer-encoding')})
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (aiohttp.ClientError, TimeoutError):
            raise web.HTTPBadGateway() from None

    @asynccontextmanager
    async def serve(self):
        """在提供者事件循环内管理双栈监听；单个地址族不可用时仍保留另一族。"""
        from module.runtime.remote_access import _local_host
        from module.runtime.setting import State
        config = State.deploy_config
        default_port = config.WebuiPort + 1 if config.WebuiSSLCert else config.WebuiPort
        self.port = int(getattr(config, 'RemoteAccessPort', 0) or default_port)
        if not 1 <= self.port <= 65535 or self.port == config.WebuiPort and config.WebuiSSLCert:
            raise ValueError('直连 HTTP 端口必须在 1–65535 之间，且不能复用 HTTPS 端口')
        if self.port == config.WebuiPort:
            self.bound_families.update(('ipv4', 'ipv6'))
            try:
                yield self
            finally:
                self.bound_families.clear()
            return
        host = _local_host()
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        self.upstream = f'{"https" if config.WebuiSSLCert else "http"}://{host}:{config.WebuiPort}'
        async with aiohttp.ClientSession(auto_decompress=False,
                                        timeout=aiohttp.ClientTimeout(total=None, sock_connect=5)) as self.session:
            application = web.Application(client_max_size=64*1024*1024)
            application.router.add_get('/api/v1/remote/probe', self.probe)
            application.router.add_get('/healthz', self.health)
            application.router.add_route('*', '/{path:.*}', self.proxy)
            runner = web.AppRunner(application, access_log=None, shutdown_timeout=5)
            await runner.setup()
            try:
                for family, host, label in ((socket.AF_INET, '0.0.0.0', 'ipv4'),
                                            (socket.AF_INET6, '::', 'ipv6')):
                    listener = None
                    try:
                        listener = socket.socket(family, socket.SOCK_STREAM)
                        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        if family == socket.AF_INET6:
                            listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                        listener.bind((host, self.port))
                        listener.setblocking(False)
                        await web.SockSite(runner, listener).start()
                        self.bound_families.add(label)
                    except OSError:
                        if listener is not None:
                            listener.close()
                yield self
            finally:
                await runner.cleanup()
                self.bound_families.clear()
