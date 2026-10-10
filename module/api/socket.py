"""单连接会话、认证、事件订阅及慢客户端背压。"""
import asyncio
import contextlib
import json
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import anyio
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from module.api.protocol import ApiError, AuthParams, Request, SubscribeParams, failure, response
from module.logger import logger
from module.runtime.password_utils import REMOTE_ACCESS_HEADER, is_local_client

# 重主题仍按各自节奏采样；日志由 worker 队列逐条到达事件直接唤醒。
TOPIC_INTERVAL = {'overview': 1, 'instances': 2}
TICK = min(TOPIC_INTERVAL.values())


class Gateway:
    """WebSocket 接入网关。

    负责全站 WebSocket 连接限流、跨域校验、密码认证速率限制及会话生命周期管理。

    Attributes:
        router: API 路由分发器。
        password: 访问密码字符串。
        connections: 当前活跃连接计数。
        workers: 限制并发执行业务任务的工作协程信号量。
        failures: 记录客户端 IP 失败认证次数及锁定时长的有序字典。
    """

    def __init__(self, router, password):
        """初始化接入网关。

        Args:
            router: API 路由分发器。
            password: 访问密码。
        """
        self.router = router
        self.password = str(password or '')
        if self.router is not None:
            self.router.access_password = self.password
        self.connections = 0
        self.workers = asyncio.Semaphore(8)
        self.failures = OrderedDict()

    async def endpoint(self, ws: WebSocket):
        """WebSocket 连接端点入口。

        处理跨域预检、并发连接数限制及会话运行。

        Args:
            ws: Starlette WebSocket 连接对象。
        """
        origin = ws.headers.get('origin')
        # WebSocket 不受浏览器 CORS 保护，必须在升级前验证来源。
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or parsed.netloc != ws.headers.get('host'):
                await ws.close(code=1008)
                return
        if self.connections >= 32:
            await ws.close(code=1013)
            return
        self.connections += 1
        try:
            await Session(self, ws, self.is_local(ws)).run()
        finally:
            self.connections -= 1

    @staticmethod
    def is_local(ws: WebSocket) -> bool:
        """判定客户端是否为本机直连。

        启动器内嵌窗口与本机浏览器免密访问，其余远程客户端仍需密码。

        Args:
            ws: Starlette WebSocket 连接对象。

        Returns:
            bool: 属于本机直连返回 True，否则返回 False。
        """
        client = ws.client.host if ws.client else ''
        return is_local_client(
            client,
            ws.headers.get('host'),
            ws.headers.get('origin'),
            ws.headers.get(REMOTE_ACCESS_HEADER),
        )

    def authenticate(self, peer: str, password: str):
        """校验客户端密码并执行防爆破速率限制。

        Args:
            peer: 客户端主机或 IP 地址。
            password: 提交的访问密码。

        Raises:
            ApiError: 尝试过于频繁被限流 (RATE_LIMITED) 或密码不正确 (UNAUTHORIZED)。
        """
        now = time.monotonic()
        count, until = self.failures.get(peer, (0, 0))
        if until > now:
            raise ApiError('RATE_LIMITED', '登录尝试过于频繁，请稍后重试')
        if not secrets.compare_digest(password.encode(), self.password.encode()):
            count += 1
            self.failures[peer] = (count, now + min(60, count * 2))
            if len(self.failures) > 1024:
                self.failures.popitem(last=False)
            raise ApiError('UNAUTHORIZED', '访问密码不正确')
        self.failures.pop(peer, None)


class Session:
    """单个 WebSocket 连接会话。

    管理连接的双向数据收发、请求处理、事件发布订阅与背压控制。

    Attributes:
        gateway: 所属的网关实例。
        ws: 底层 WebSocket 连接对象。
        authorized: 当前连接是否已通过认证或处于免密模式。
        queue: 发送消息缓冲队列。
        subscription: 当前客户端的事件订阅参数。
        sequence: 推送事件单调自增序号。
        cache: 各主题最后一次推送数据的指纹缓存。
        responses: 已处理请求 ID 缓存（防止重复执行）。
        log_cursor: 日志游标序号。
        logs_initialized: 日志订阅是否已完成初次加载。
        window: 速率统计时间窗口起点。
        requests: 窗口内请求计数。
        topic_seen: 各主题最后采样时间戳。
        logs_changed: 日志更新通知事件。
        preview_changed: 预览帧更新通知事件。
        preview_pending: 待发送的最新的预览帧数据。
    """

    def __init__(self, gateway: Gateway, ws: WebSocket, local: bool = False):
        """初始化 WebSocket 会话。

        Args:
            gateway: 网关实例。
            ws: Starlette WebSocket 连接对象。
            local: 是否为本机免密直连。
        """
        self.gateway, self.ws = gateway, ws
        self.authorized = local or not bool(gateway.password)
        self.queue = asyncio.Queue(maxsize=32)
        self.subscription = SubscribeParams(topics=[])
        self.sequence = 0
        self.cache = {}
        self.responses = OrderedDict()
        self.log_cursor = 0
        self.logs_initialized = False
        self.window = time.monotonic()
        self.requests = 0
        self.topic_seen = {}
        self.logs_changed = asyncio.Event()
        self.preview_changed = asyncio.Event()
        self.preview_pending = None
        self.stock_changed = asyncio.Event()
        self.stock_update = {}

    async def enqueue(self, message: dict):
        """将消息放入发送队列，遇到慢客户端时主动断开连接以实现背压保护。

        Args:
            message: 待发送的消息字典。

        Raises:
            WebSocketDisconnect: 发送队列已满触发慢客户端断开。
        """
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            await self.ws.close(code=1013, reason='客户端读取过慢，请重新连接')
            raise WebSocketDisconnect(1013)

    async def event(self, topic: str, data: dict):
        """构造并入队事件通知消息。

        Args:
            topic: 消息主题。
            data: 事件载荷数据。
        """
        message = {'v': 1, 'type': 'event', 'topic': topic, 'data': data}
        if topic == 'preview':
            if self.preview_pending is None:
                await self.enqueue({'previewSlot': True})
            self.preview_pending = message
        else:
            await self.enqueue(message)

    async def writer(self):
        """消息发送循环任务，持续从队列读取并向客户端发送 JSON 数据。"""
        while True:
            message = await self.queue.get()
            if message.get('previewSlot'):
                message, self.preview_pending = self.preview_pending, None
                if (not message or 'preview' not in self.subscription.topics
                        or message['data']['instance'] != self.subscription.instance):
                    continue
            if message.get('type') == 'event':
                self.sequence += 1
                message['seq'] = self.sequence
            await asyncio.wait_for(self.ws.send_json(message), timeout=10)

    async def run(self):
        """启动会话主生命周期，协调读写协程与数据生产者的并发运行。"""
        await self.ws.accept()
        writer = asyncio.create_task(self.writer())
        producer = asyncio.create_task(self.producer())
        reader = asyncio.create_task(self.reader())
        logs = asyncio.create_task(self.log_producer())
        preview = asyncio.create_task(self.preview_producer())
        stock = asyncio.create_task(self.stock_producer())
        await self.event('session', {'authRequired': not self.authorized, 'protocolVersion': 1})
        tasks = [writer, producer, reader, logs, preview, stock]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            # ASGI 服务器可能在客户端退出时取消整个会话作用域。
            # 屏蔽外层取消，确保收发任务实际结束后再归还连接槽位。
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                with contextlib.suppress(RuntimeError):
                    await self.ws.close()

    async def reader(self):
        """消息读取与分发协程，持续解析客户端请求并入队响应。"""
        while True:
            raw = await asyncio.wait_for(self.ws.receive_text(), timeout=60 if self.authorized else 30)
            request_id = None
            decoded = None
            try:
                size = len(raw.encode())
                if size > 8 * 1024 * 1024:
                    raise ApiError('INVALID_REQUEST', '请求超过 8 MiB 限制')
                now = time.monotonic()
                if now - self.window > 1:
                    self.window, self.requests = now, 0
                self.requests += 1
                decoded = json.loads(raw)
                if isinstance(decoded, dict) and isinstance(decoded.get('id'), str):
                    request_id = decoded['id'][:100]
                request = Request.model_validate(decoded)
                if size > 1024 * 1024 and request.method not in ('mind.import', 'mind.recognize', 'mind.save', 'mind.calculate'):
                    raise ApiError('INVALID_REQUEST', '请求超过 1 MiB 限制')
                if request.method in ('stock.request', 'stock.status'):
                    self.requests -= 1
                if self.requests > 30 and request.method not in ('stock.request', 'stock.status'):
                    raise ApiError('RATE_LIMITED', '请求过于频繁')
                request_id = request.id
                if request.method == 'accounts.manage' and not self.gateway.is_local(self.ws) and self.ws.url.scheme != 'wss':
                    raise ApiError('TLS_REQUIRED', '远程账号操作必须通过 HTTPS/WSS 连接')
                if request_id in self.responses:
                    raise ApiError('DUPLICATE_REQUEST', '请求 ID 已使用，请检查状态后使用新 ID')
                if request.method == 'auth.login':
                    params = AuthParams.model_validate(request.params)
                    peer = self.ws.client.host if self.ws.client else 'unknown'
                    self.gateway.authenticate(peer, params.password)
                    self.authorized = True
                    result = {'authenticated': True}
                elif not self.authorized:
                    raise ApiError('UNAUTHORIZED', '请先登录')
                elif request.method == 'events.subscribe':
                    subscription = SubscribeParams.model_validate(request.params)
                    if any(topic != 'instances' for topic in subscription.topics):
                        self.gateway.router.configs.path(subscription.instance)
                    self.subscription = subscription
                    self.cache.clear()
                    self.log_cursor = 0
                    self.logs_initialized = False
                    self.topic_seen.clear()
                    self.logs_changed.set()
                    self.preview_changed.set()
                    self.stock_changed.set()
                    result = {'topics': subscription.topics, 'instance': subscription.instance}
                else:
                    async with self.gateway.workers:
                        result = await asyncio.to_thread(self.gateway.router.dispatch, request.method, request.params)
                reply = response(request_id, result)
            except ValidationError as exc:
                # 错误详情不包含输入，避免密码或私有配置被回显。
                reply = failure(request_id, ApiError('INVALID_PARAMS', '请求格式或参数不正确',
                                [{'path': list(e['loc']), 'type': e['type']} for e in exc.errors()]))
            except ApiError as exc:
                reply = failure(request_id, exc)
            except (ValueError, PermissionError) as exc:
                reply = failure(request_id, ApiError('INVALID_PARAMS', str(exc)))
            except Exception:
                if isinstance(decoded, dict) and decoded.get('method') == 'accounts.manage':
                    logger.error('账号 API 执行失败，敏感上下文已隐藏')
                else:
                    logger.exception('WebSocket API 执行失败')
                reply = failure(request_id, ApiError('INTERNAL_ERROR', '服务暂时无法完成请求，请检查服务日志'))
            if request_id:
                self.responses[request_id] = True
                if len(self.responses) > 128:
                    self.responses.popitem(last=False)
            await self.enqueue(reply)

    async def producer(self):
        """定期采样订阅的主题（实例列表、总览与统计）并推送差异。"""
        while True:
            await asyncio.sleep(TICK)
            if not self.authorized:
                continue
            subscription = self.subscription
            runtime = self.gateway.router.runtime
            for topic in subscription.topics:
                try:
                    if topic in ('logs', 'preview', 'stock'):
                        continue
                    if (now := time.monotonic()) - self.topic_seen.get(topic, 0) < TOPIC_INTERVAL.get(topic, 2):
                        continue
                    self.topic_seen[topic] = now
                    if topic == 'instances':
                        action = runtime.instances
                    elif topic == 'overview':
                        action = lambda: runtime.overview(subscription.instance)
                    async with self.gateway.workers:
                        data = await asyncio.to_thread(action)
                    # 用户切换实例期间完成的旧结果不允许覆盖新工作区。
                    if subscription is not self.subscription:
                        break
                    fingerprint = json.dumps(data, sort_keys=True, default=str)
                    if self.cache.get(topic) != fingerprint:
                        self.cache[topic] = fingerprint
                        await self.event(topic, data)
                except ApiError as exc:
                    fingerprint = f'{exc.code}:{exc.message}'
                    if subscription is self.subscription and self.cache.get(topic) != fingerprint:
                        self.cache[topic] = fingerprint
                        await self.event('subscription.error', {'topic': topic, 'instance': subscription.instance,
                                                               'code': exc.code, 'message': exc.message})
                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception:
                    logger.exception('订阅数据读取失败')
                    if self.cache.get(topic) != 'INTERNAL_ERROR':
                        self.cache[topic] = 'INTERNAL_ERROR'
                        await self.event('subscription.error', {'topic': topic, 'instance': subscription.instance,
                                                               'code': 'INTERNAL_ERROR', 'message': '订阅暂时不可用，请检查服务日志'})
            if subscription.instance and (time.monotonic() - self.topic_seen.get('statistics', 0)) >= 1:
                self.topic_seen['statistics'] = time.monotonic()
                try:
                    from module.api.statistics_service import get_statistics_fingerprint
                    stats_fp = await asyncio.to_thread(get_statistics_fingerprint, subscription.instance, self.gateway.router.configs.directory)
                    if subscription is self.subscription:
                        old_fp = self.cache.get('statistics')
                        if old_fp is not None and old_fp != stats_fp:
                            self.cache['statistics'] = stats_fp
                            await self.event('statistics', {'instance': subscription.instance, 'updatedAt': time.time()})
                        elif old_fp is None:
                            self.cache['statistics'] = stats_fp
                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception:
                    pass

    async def stock_producer(self):
        """交易所提交事件直接唤醒 WebSocket，不占用请求处理线程。"""
        loop = asyncio.get_running_loop()
        unsubscribe = None

        def changed(data):
            if data.get('instance') not in (None, self.subscription.instance):
                return
            if not loop.is_closed():
                def wake():
                    self.stock_update.update(data)
                    self.stock_changed.set()
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(wake)

        try:
            while True:
                await self.stock_changed.wait()
                self.stock_changed.clear()
                subscription = self.subscription
                if not self.authorized or 'stock' not in subscription.topics:
                    if unsubscribe:
                        unsubscribe()
                        unsubscribe = None
                    self.stock_update = {}
                    continue
                if unsubscribe is None:
                    service = await asyncio.to_thread(lambda: self.gateway.router.stock_exchange)
                    unsubscribe = service.subscribe(changed)
                update, self.stock_update = self.stock_update, {}
                if subscription is self.subscription:
                    await self.event('stock', {**update, 'instance': subscription.instance})
        finally:
            if unsubscribe:
                unsubscribe()

    async def log_producer(self):
        """日志生产者协程。

        日志到达后立即读取增量；初始化或重置成批发送，实时新增逐条发送。
        """
        from module.runtime.log_hub import hub
        loop = asyncio.get_running_loop()

        def changed(instance):
            if instance == self.subscription.instance and not loop.is_closed():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(self.logs_changed.set)

        hub.subscribe(changed)
        try:
            while True:
                await self.logs_changed.wait()
                self.logs_changed.clear()
                subscription = self.subscription
                if not self.authorized or 'logs' not in subscription.topics:
                    continue
                initial = not self.logs_initialized
                try:
                    async with self.gateway.workers:
                        data = await asyncio.to_thread(
                            self.gateway.router.runtime.logs, subscription.instance, self.log_cursor
                        )
                    if subscription is not self.subscription:
                        continue
                    entries = data['entries']
                    if not entries and not data['reset']:
                        self.log_cursor = data['cursor']
                        self.logs_initialized = True
                        continue
                    if initial or data['reset']:
                        self.log_cursor = data['cursor']
                        self.logs_initialized = True
                        await self.event('logs', data)
                        continue
                    for entry in entries:
                        self.log_cursor = entry['id']
                        await self.event('logs', {
                            'instance': data['instance'], 'cursor': entry['id'],
                            'reset': False, 'entries': [entry],
                        })
                    self.log_cursor = data['cursor']
                    self.logs_initialized = True
                except ApiError as exc:
                    if subscription is self.subscription:
                        await self.event('subscription.error', {
                            'topic': 'logs', 'instance': subscription.instance,
                            'code': exc.code, 'message': exc.message,
                        })
                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception:
                    logger.exception('日志订阅读取失败')
                    if subscription is self.subscription:
                        await self.event('subscription.error', {
                            'topic': 'logs', 'instance': subscription.instance,
                            'code': 'INTERNAL_ERROR', 'message': '日志订阅暂时不可用，请检查服务日志',
                        })
        finally:
            hub.unsubscribe(changed)

    async def preview_producer(self):
        """预览帧生产者协程。

        收到新帧即推送；慢浏览器合并为最新帧，不产生多余的截图请求。
        """
        from module.runtime.preview import hub
        loop = asyncio.get_running_loop()

        def changed(instance):
            if instance == self.subscription.instance and not loop.is_closed():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(self.preview_changed.set)

        hub.subscribe(changed)
        try:
            while True:
                await self.preview_changed.wait()
                self.preview_changed.clear()
                subscription = self.subscription
                if not self.authorized or 'preview' not in subscription.topics:
                    continue
                frame = hub.get(subscription.instance)
                await self.event('preview', frame)
        finally:
            hub.unsubscribe(changed)
