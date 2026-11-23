"""Quick Tunnel 生命周期、固定入口注册和可撤销的 AFA 配对凭据。"""

import asyncio
import hashlib
import json
import os
import re
import secrets
import socket
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

import aiohttp

from module.base import http
from deploy.atomic import atomic_write
from module.logger import logger

DEFAULT_REGISTRY = 'https://remote.azurpilot.com'
LEGACY_REGISTRY = 'https://ap-remote.108-186-180-52.sslip.io:8443'
TUNNEL_UNREADY_TIMEOUT = 120
REGISTRATION_INTERVAL = 600
REGISTRATION_MARGIN = 120
REGISTRATION_POLL_INTERVAL = 10
_store_lock = threading.RLock()
_pyflared_import_lock = threading.RLock()


class RemoteRegistryError(ValueError):
    """保留注册服务的错误码、状态与路由，不包含认证头或配对凭据。"""

    def __init__(self, status, code, message, method, path):
        self.status, self.code = status, code
        route = re.sub(r'/[a-zA-Z0-9_-]{16,80}$', '/<id>', path)
        super().__init__(f'远程注册服务：{message}（HTTP {status}，{method} {route}）')


class TunnelHealthError(ValueError):
    """保留 Cloudflare 公网响应状态，区分短暂故障与持续失效的入口。"""

    def __init__(self, status):
        self.status = status
        super().__init__(f'Quick Tunnel 公网健康检查返回 HTTP {status}')


def _device_id(value):
    """兼容简易部署解析器保留的引号；空值使用安装级随机 ID。"""
    value = str(value or '').strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    if value and not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', value):
        raise ValueError('CloudflareDeviceId 必须为 16–80 位字母、数字、下划线或连字符，或留空自动生成')
    return value


class RemoteIdentity:
    """保存安装级设备身份与配对凭据摘要；测试可传入临时目录。"""

    def __init__(self, directory='config', device_id=''):
        self.path = Path(directory) / 'remote-access.json'
        self.device_id = _device_id(device_id)

    def load(self):
        """读取稳定身份；首次启用时生成，损坏文件不自动覆盖。"""
        with _store_lock:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding='utf-8'))
                value = _device_id(data['device_id']) or self.device_id or uuid.uuid4().hex
                if value != data['device_id']:
                    # 旧版把引号空值保存为 ID，服务器从未接受；修正时保留密钥及授权。
                    data['device_id'] = value
                    self.save(data)
                return data
            data = {'device_id': self.device_id or uuid.uuid4().hex,
                    'device_key': secrets.token_urlsafe(32), 'clients': []}
            self.save(data)
            return data

    def save(self, data):
        """原子保存身份并限制 POSIX 文件权限。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(str(self.path), json.dumps(data, ensure_ascii=False))
        if os.name != 'nt':
            self.path.chmod(0o600)

    def add_client(self):
        """为一次配对生成独立凭据，避免共享 WebUI 密码。"""
        with _store_lock:
            data = self.load()
            if len(data['clients']) >= 20:
                raise ValueError('配对设备已达上限，请先移除旧配对')
            token, client_id = secrets.token_urlsafe(32), uuid.uuid4().hex
            data['clients'].append({'id': client_id, 'hash': hashlib.sha256(token.encode()).hexdigest(),
                                    'created_at': int(time.time())})
            self.save(data)
            return client_id, token

    def remove_client(self, client_id):
        """撤销指定客户端；下次鉴权立即拒绝该凭据。"""
        with _store_lock:
            data = self.load()
            data['clients'] = [item for item in data['clients'] if item['id'] != client_id]
            self.save(data)

    def accepts(self, token):
        """检查凭据摘要；未启用过远程访问时不创建身份文件。"""
        if not token or not self.path.exists():
            return False
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with _store_lock:
            return any(secrets.compare_digest(item['hash'], hashed) for item in self.load()['clients'])


def registry_url(value):
    """要求注册 API 使用 HTTPS；回环地址例外用于隔离测试。"""
    if value.rstrip('/') == LEGACY_REGISTRY:
        value = DEFAULT_REGISTRY
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme != 'https' and not (
                parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')))):
        raise ValueError('远程注册服务器必须使用 HTTPS')
    return value.rstrip('/')


def _request_proxy(url):
    """沿用环境或系统代理及绕过规则，不为目标主机读取 .netrc 凭据。"""
    parsed = urlsplit(url)
    if proxy_bypass(parsed.hostname):
        return None
    return getproxies().get(parsed.scheme)


def _quick_tunnel_context(service, protocol=None):
    """将 pyflared 0.1.0 的导入期数据放入项目缓存，不改写其他库的目录。"""
    import platformdirs

    # 上游在导入 repository 时直接建库，尚未提供数据目录参数。
    # 仅重定向它自己的应用标识；导入结束立即恢复 platformdirs 的公开入口。
    with _pyflared_import_lock:
        original = platformdirs.user_data_dir

        def project_data_dir(appname=None, appauthor=None, *args, **kwargs):
            if appname == 'pyflared' and appauthor == 'Azmain':
                return str(Path(__file__).resolve().parents[2] / 'cache' / 'cloudflare' / 'pyflared')
            return original(appname, appauthor, *args, **kwargs)

        platformdirs.user_data_dir = project_data_dir
        try:
            from pyflared import run_quick_tunnel
        finally:
            platformdirs.user_data_dir = original
    context = run_quick_tunnel(service)
    if protocol:
        command = context.cmd_args

        async def arguments():
            values = await command
            return (*values[:1], '--protocol', protocol, *values[1:])

        context.cmd_args = arguments()
    return context


def _failure_reason(error):
    """展开并发异常组，向界面提供可定位且不包含凭据的失败原因。"""
    if isinstance(error, BaseExceptionGroup):
        return '；'.join(dict.fromkeys(_failure_reason(item) for item in error.exceptions))
    if isinstance(error, PermissionError):
        return f'权限不足，无法访问 {error.filename}' if error.filename else '本地文件或进程权限不足'
    if isinstance(error, ValueError):
        return str(error)
    return type(error).__name__


class CloudflareRemoteAccessProvider:
    """在专用线程运行 pyflared，每次进程启动重建 Tunnel 并续约固定入口。"""

    def __init__(self):
        self.thread = None
        self.stop_event = threading.Event()
        self.loop = None
        self.task = None
        self.state, self.address, self.error = 'stopped', '', ''
        self.tunnel_url = ''
        self.retry_after = 0
        self._tunnel_ready = False
        self._tunnel_protocol = None
        self._direct_server = None
        self._peer_server = None
        self._legacy_registry = False
        self._lock = threading.Lock()

    def identity(self):
        """返回当前安装的设备身份仓库。"""
        from module.runtime.setting import State
        return RemoteIdentity(device_id=getattr(State.deploy_config, 'CloudflareDeviceId', '') or '')

    def registry(self):
        """返回经过校验的注册服务地址。"""
        from module.runtime.setting import State
        return registry_url(getattr(State.deploy_config, 'CloudflareRegistry', DEFAULT_REGISTRY))

    async def request(self, method, path, data=None):
        """调用注册服务，禁止跟随跳转，凭据只通过 Authorization 传输。"""
        if not path.startswith('/api/v1/'):
            raise ValueError(f'远程注册 API 路径必须以 /api/v1/ 开头：{method} {path}')
        identity = self.identity().load()
        url = self.registry() + path
        async with http.AsyncSession(timeout=15) as session:
            # Keep proxy discovery without allowing .netrc to replace device auth.
            session.trust_env = False
            proxy = _request_proxy(url)
            response = await session.request(
                method, url, json=data, proxies={'http': proxy, 'https': proxy} if proxy else {},
                headers={'Authorization': 'Bearer ' + identity['device_key']},
                allow_redirects=False, stream=True,
            )
            async with response:
                if response.status_code != 200:
                    try:
                        error = json.loads(await response.raw.read(4096, decode_content=True))
                    except (ValueError, UnicodeError):
                        error = {}
                    if not isinstance(error, dict):
                        error = {}
                    message = error.get('error')
                    message = message[:160] if isinstance(message, str) else '请求失败'
                    code = error.get('code', '')
                    if response.status_code == 404 and message == '配对已过期':
                        code = 'PAIRING_EXPIRED'
                    elif response.status_code == 404 and not code:
                        code, message = 'API_NOT_FOUND', '注册接口不存在，请检查 AP 与服务端版本'
                    raise RemoteRegistryError(response.status_code, code, message, method, path)
                return await response.json()

    @asynccontextmanager
    async def signal_events(self):
        """监听服务端事件，使用设备凭据鉴权并遵守现有代理配置。"""
        identity = self.identity().load()
        url = f"{self.registry()}/api/v1/devices/{identity['device_id']}/signal/events"
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url, proxy=_request_proxy(url), allow_redirects=False,
                headers={'Authorization': 'Bearer ' + identity['device_key'], 'Accept': 'text/event-stream'},
            ) as response:
                response.raise_for_status()
                if response.status != 200 or response.content_type != 'text/event-stream':
                    raise ValueError('远程注册服务未返回信令事件流')
                yield response.content

    def start(self):
        """幂等启动后台线程，不阻塞 WebUI 启动。"""
        with self._lock:
            if self.is_alive():
                return
            self.stop_event.clear()
            self.state, self.error = 'starting', ''
            self.thread = threading.Thread(target=self._run, name='quick-tunnel', daemon=True)
            self.thread.start()

    def stop(self):
        """取消 Tunnel 并等待子进程回收；服务端租约作为异常退出的兜底。"""
        with self._lock:
            self.stop_event.set()
            if self.loop and self.task and not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self.task.cancel)
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=20)
            self.address, self.tunnel_url, self.state = '', '', 'stopped'

    def is_alive(self):
        """返回监督线程是否仍在运行。"""
        return bool(self.thread and self.thread.is_alive())

    def get_state(self):
        """沿用远程访问状态码：就绪为 1，启动为 2，停止或失败为 0。"""
        return 1 if self.address else 2 if self.is_alive() else 0

    def get_entry_point(self):
        """返回固定入口，注册失败时不展示旧地址。"""
        return self.address or None

    def get_connection_state(self):
        """返回界面使用的连接状态。"""
        return self.state

    def get_error(self):
        """返回不包含设备密钥的错误描述。"""
        return self.error

    def _run(self):
        async def supervise():
            self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
            delay = 30
            while not self.stop_event.is_set():
                try:
                    await self._connect()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    self.state, self.address, self.tunnel_url = 'failed', '', ''
                    reason = _failure_reason(exc)
                    self.error = f'Quick Tunnel 暂不可用（{reason}），正在重试'
                    logger.warning(self.error)
                if not self.stop_event.is_set():
                    await asyncio.sleep(max(delay, self.retry_after))
                    self.retry_after = 0
                    delay = min(delay * 2, 300)
        try:
            asyncio.run(supervise())
        except asyncio.CancelledError:
            pass
        finally:
            self.loop, self.task = None, None

    async def _connect(self):
        """先注册直连候选；按服务端结果或客户端请求启动 Cloudflare。"""
        from module.runtime.remote_direct import DirectAccessServer
        from module.runtime.remote_p2p import PeerServer
        from module.runtime.setting import State
        from module.runtime.password_utils import is_webui_password_set
        if not is_webui_password_set(State.deploy_config.Password):
            raise ValueError('请先设置 WebUI 访问密码')
        identity = self.identity().load()
        tunnel_task = None
        retry_at = 0
        delay = 2
        registered_at = 0
        lease_seconds = 180
        last_registration = None
        result = {}
        try:
            async with DirectAccessServer(self).serve() as direct, PeerServer(self).serve() as peer:
                self._direct_server = direct
                self._peer_server = peer
                while not self.stop_event.is_set():
                    if tunnel_task and tunnel_task.done():
                        try:
                            tunnel_task.result()
                        except (Exception, asyncio.CancelledError) as exc:
                            logger.warning(f'Cloudflare 正在恢复（{_failure_reason(exc)}）')
                        tunnel_task = None
                        self.tunnel_url, self._tunnel_ready = '', False
                        retry_at = time.monotonic() + max(30, self.retry_after)
                        self.retry_after = 0
                    try:
                        registration = {
                            'device_id': identity['device_id'], 'name': socket.gethostname()[:80],
                            'tunnel_url': self.tunnel_url if self._tunnel_ready else '',
                        }
                        if not self._legacy_registry:
                            registration['direct'] = {**direct.registration(), 'p2p': True}
                        interval = (REGISTRATION_INTERVAL if result.get('signal_events') is True
                                    and lease_seconds >= REGISTRATION_INTERVAL + REGISTRATION_MARGIN
                                    else REGISTRATION_POLL_INTERVAL)
                        if registration != last_registration or time.monotonic() - registered_at >= interval:
                            result = await self.request('POST', '/api/v1/devices/register', registration)
                            lease = result.get('lease_seconds')
                            lease_seconds = lease if type(lease) is int and lease > 0 else 180
                            registered_at = time.monotonic()
                            last_registration = registration
                    except RemoteRegistryError as exc:
                        if exc.status == 400 and not self._legacy_registry:
                            self._legacy_registry = True
                            continue
                        # 旧注册服务仍不可用时保留 Quick Tunnel，避免远程入口彻底中断。
                        if exc.status == 400 and not tunnel_task and time.monotonic() >= retry_at:
                            tunnel_task = asyncio.create_task(self._tunnel(managed=True))
                        if not self._tunnel_ready:
                            self.address, self.state = '', 'failed'
                        self.error = str(exc)
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 15)
                        continue
                    except (aiohttp.ClientError, http.RequestException, TimeoutError, ValueError) as exc:
                        if time.monotonic() - registered_at >= lease_seconds:
                            self.address, self.state = '', 'failed'
                        self.error = f'远程入口正在恢复（{_failure_reason(exc)}）'
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 15)
                        continue
                    delay = 2
                    endpoints = result.get('endpoints', [])
                    self.address = result['url']
                    self.state = 'direct_ready' if endpoints else 'cloudflare_ready' if self._tunnel_ready else 'registered'
                    self.error = ''
                    if ((result.get('fallback_required', True) or peer.fallback_requested)
                            and not tunnel_task and time.monotonic() >= retry_at):
                        tunnel_task = asyncio.create_task(self._tunnel(managed=True))
                    await asyncio.sleep(REGISTRATION_POLL_INTERVAL)
        finally:
            self._direct_server = None
            self._peer_server = None
            if tunnel_task:
                tunnel_task.cancel()
                await asyncio.gather(tunnel_task, return_exceptions=True)
            self.address, self.tunnel_url, self._tunnel_ready = '', '', False
            try:
                await self.request('DELETE', '/api/v1/devices/' + identity['device_id'])
            except (aiohttp.ClientError, http.RequestException, TimeoutError, ValueError):
                pass

    async def _tunnel(self, managed=False):
        from module.runtime.remote_access import _local_host
        from module.runtime.setting import State
        from module.runtime.password_utils import is_webui_password_set

        # Tunnel 的公网 Host 会触发现有网关鉴权；拒绝暴露无口令的实例。
        if not is_webui_password_set(State.deploy_config.Password):
            raise ValueError('请先设置 WebUI 访问密码')
        host = _local_host()
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        scheme = 'https' if State.deploy_config.WebuiSSLCert else 'http'
        if not managed:
            self.state, self.address, self.error = 'starting', '', ''
        service = f'{scheme}://{host}:{State.deploy_config.WebuiPort}'
        context = (_quick_tunnel_context(service, protocol=self._tunnel_protocol)
                   if self._tunnel_protocol else _quick_tunnel_context(service))
        from pyflared.shared.types import ChunkSignal
        diagnostic = ''
        async def safe_chunker(stream, channel):
            nonlocal diagnostic
            line = await stream.readline()
            if not line:
                return ChunkSignal.EOF
            if b'429 Too Many Requests' in line or b'error code: 1015' in line:
                diagnostic = 'Cloudflare Quick Tunnel 请求过于频繁（HTTP 429），等待十分钟后重试'
                self.retry_after = 600
            elif b'failed to dial to edge' in line or b'TLS handshake timeout' in line:
                diagnostic = 'Cloudflare 边缘连接超时，请检查网络能否连接 7844 端口'
            match = re.search(rb'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            return match.group(0) if match else ChunkSignal.SKIP
        context.stream_chunker = safe_chunker
        async with context as process:
            ready = asyncio.get_running_loop().create_future()
            async def drain():
                async for event in process:
                    url = event.data.decode().strip()
                    parsed = urlsplit(url)
                    if parsed.scheme == 'https' and (parsed.hostname or '').endswith('.trycloudflare.com'):
                        self.tunnel_url = url
                        if not ready.done():
                            ready.set_result(url)
                raise ValueError(diagnostic or 'cloudflared 进程已退出，等待重建 Quick Tunnel')
            async def heartbeat():
                try:
                    async with asyncio.timeout(90):
                        await ready
                except TimeoutError:
                    raise ValueError(diagnostic or 'Cloudflare 在 90 秒内未分配 Quick Tunnel 地址') from None
                identity = self.identity().load()
                delay = 2
                unready_since = None
                while True:
                    try:
                        # CLI 输出 URL 只表示分配成功，公网健康检查成功才能宣告可访问。
                        await self.check_tunnel(self.tunnel_url)
                        unready_since = None
                        self._tunnel_ready = True
                        if managed:
                            await asyncio.sleep(60)
                            continue
                        registered = await self.request('POST', '/api/v1/devices/register', {
                            'device_id': identity['device_id'], 'name': socket.gethostname()[:80],
                            'tunnel_url': self.tunnel_url,
                        })
                    except (aiohttp.ClientError, http.RequestException, TimeoutError, ValueError) as exc:
                        if isinstance(exc, TunnelHealthError) and exc.status == 530:
                            if unready_since is None:
                                unready_since = time.monotonic()
                            if time.monotonic() - unready_since >= TUNNEL_UNREADY_TIMEOUT:
                                self._tunnel_protocol = 'http2'
                                raise ValueError('Cloudflare 入口持续不可达，使用 HTTP/2 重建隧道') from None
                        else:
                            unready_since = None
                        # 注册或探测瞬断只重试同一 URL，不销毁健康进程重新申请 Tunnel。
                        self._tunnel_ready = False
                        if not managed:
                            self.address, self.state = '', 'failed'
                        reason = '网络请求超时' if isinstance(exc, TimeoutError) else _failure_reason(exc)
                        message = f'Quick Tunnel 正在恢复（{reason}），保留当前隧道重试'
                        if managed:
                            logger.warning(message)
                        else:
                            self.error = message
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 60)
                    else:
                        self.address, self.state, self.error = registered['url'], 'cloudflare_ready', ''
                        delay = 2
                        await asyncio.sleep(60)
            try:
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(drain())
                    tasks.create_task(heartbeat())
            finally:
                self._tunnel_ready = False
                if not managed:
                    self.address = ''
                    try:
                        await self.request('DELETE', '/api/v1/devices/' + self.identity().load()['device_id'])
                    except (aiohttp.ClientError, http.RequestException, TimeoutError, ValueError):
                        pass

    async def check_tunnel(self, url):
        """验证公网 AP 健康接口；不跟随跳转，也不携带 WebUI 或设备凭据。"""
        url = url.rstrip('/') + '/healthz'
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                async with session.get(url, allow_redirects=False, proxy=_request_proxy(url)) as response:
                    if response.status != 200:
                        raise TunnelHealthError(response.status)
                    try:
                        data = await response.json()
                    except (ValueError, aiohttp.ContentTypeError):
                        raise ValueError('Quick Tunnel 公网健康检查未返回 AP 协议') from None
                    if not isinstance(data, dict) or data.get('status') != 'ok' or data.get('protocolVersion') != 1:
                        raise ValueError('Quick Tunnel 公网健康检查未返回 AP 协议')
        except TimeoutError:
            raise ValueError('Quick Tunnel 公网健康检查超时，请检查网络或代理') from None
        except aiohttp.ClientConnectorCertificateError:
            raise ValueError('Quick Tunnel 公网健康检查 TLS 证书校验失败，请检查系统时间、受信任证书和代理') from None
        except aiohttp.ClientSSLError:
            raise ValueError('Quick Tunnel 公网健康检查 TLS 握手失败，请检查代理和 HTTPS 连接') from None
        except aiohttp.ClientProxyConnectionError:
            raise ValueError('Quick Tunnel 公网健康检查代理连接失败，请检查系统或环境变量中的代理设置') from None
        except aiohttp.ClientHttpProxyError as exc:
            raise ValueError(f'Quick Tunnel 公网健康检查代理拒绝连接（HTTP {exc.status}），请检查代理设置') from None
        except aiohttp.ClientConnectorDNSError:
            raise ValueError('Quick Tunnel 公网健康检查域名解析失败，请检查 DNS 或代理设置') from None
        except aiohttp.ClientConnectorError as exc:
            code = getattr(exc.os_error, 'winerror', None) or exc.os_error.errno
            raise ValueError(f'Quick Tunnel 公网健康检查连接失败（错误码 {code}），请检查网络或代理') from None
        except aiohttp.ClientError as exc:
            raise ValueError(f'Quick Tunnel 公网健康检查请求失败（{type(exc).__name__}），请检查网络或代理') from None

    def create_pairing(self):
        """由本机 AP 发起配对；服务器生成六位码与扫描凭据。"""
        if not self.address:
            raise ValueError('请先启用远程访问并等待连接就绪')
        identity = self.identity()
        client_id, token = identity.add_client()
        try:
            result = asyncio.run(self.request('POST', '/api/v1/pairings', {
                'device_id': identity.load()['device_id'], 'access_token': token,
            }))
        except Exception:
            identity.remove_client(client_id)
            raise
        return {**result, 'client_id': client_id}


cloudflare = CloudflareRemoteAccessProvider()
