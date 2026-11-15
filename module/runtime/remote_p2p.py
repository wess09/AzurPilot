"""WebRTC DataChannel 隧道协议帧及 PeerServer 生命周期。"""

import asyncio
import json
import re
import struct
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from urllib.parse import quote, urlsplit

import aiohttp
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from module.runtime.password_utils import REMOTE_ACCESS_HEADER

MAX_FRAME_PAYLOAD = 49152
MAX_STREAM_BODY = 64 * 1024 * 1024
SIGNAL_POLL_INTERVAL = 2
MAX_SIGNAL_CONCURRENCY = 4
FRAME_HEADER = struct.Struct('>BHI')
FRAME_HEADER_SIZE = FRAME_HEADER.size
_METHOD = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


class FrameType(IntEnum):
    """P2P 隧道协议 v1 的二进制帧类型。"""

    HTTP_OPEN = 1
    HTTP_HEAD = 2
    DATA = 3
    DONE = 4
    WS_OPEN = 5
    WS_TEXT = 6
    WS_BIN = 7
    WS_CLOSE = 8
    PING = 9
    PONG = 10
    WS_END = 11


class FrameDecodeError(ValueError):
    """收到不完整、超限或不符合协议的二进制帧。"""


@dataclass(frozen=True, slots=True)
class Frame:
    """一条已解码的 P2P 隧道帧。"""

    type: FrameType
    stream_id: int
    payload: bytes = b''

    def encode(self):
        return encode_frame(self.type, self.stream_id, self.payload)


def encode_frame(frame_type, stream_id, payload=b''):
    """编码单帧；payload 上限为 49152 字节。"""
    try:
        frame_type = FrameType(frame_type)
    except (TypeError, ValueError):
        raise ValueError(f'未知 P2P 帧类型：{frame_type}') from None
    if isinstance(stream_id, bool) or not isinstance(stream_id, int) or not 1 <= stream_id <= 65535:
        raise ValueError('P2P streamId 必须是 1–65535')
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError('P2P 帧 payload 必须是 bytes')
    payload = bytes(payload)
    if len(payload) > MAX_FRAME_PAYLOAD:
        raise ValueError(f'P2P 帧 payload 不能超过 {MAX_FRAME_PAYLOAD} 字节')
    return FRAME_HEADER.pack(frame_type, stream_id, len(payload)) + payload


def decode_frame(data):
    """解码一个完整二进制帧，拒绝截断、尾随数据和超限 payload。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError('P2P 帧数据必须是 bytes')
    data = bytes(data)
    if len(data) < FRAME_HEADER_SIZE:
        raise FrameDecodeError('P2P 帧头不完整')
    raw_type, stream_id, length = FRAME_HEADER.unpack_from(data)
    if length > MAX_FRAME_PAYLOAD:
        raise FrameDecodeError(f'P2P 帧 payload 超过 {MAX_FRAME_PAYLOAD} 字节')
    if len(data) != FRAME_HEADER_SIZE + length:
        raise FrameDecodeError('P2P 帧长度与帧头不一致')
    if not stream_id:
        raise FrameDecodeError('P2P streamId 不能为 0')
    try:
        frame_type = FrameType(raw_type)
    except ValueError:
        raise FrameDecodeError(f'未知 P2P 帧类型：{raw_type}') from None
    return Frame(frame_type, stream_id, data[FRAME_HEADER_SIZE:])


class FrameDecoder:
    """按字节流增量提取完整帧，供可能合并的 DataChannel 消息使用。"""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        """追加字节并返回当前缓冲区可解码的完整帧。"""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError('P2P 帧数据必须是 bytes')
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= FRAME_HEADER_SIZE:
            length = FRAME_HEADER.unpack_from(self.buffer)[2]
            frame_size = FRAME_HEADER_SIZE + length
            if length > MAX_FRAME_PAYLOAD:
                raise FrameDecodeError(f'P2P 帧 payload 超过 {MAX_FRAME_PAYLOAD} 字节')
            if len(self.buffer) < frame_size:
                break
            frames.append(decode_frame(self.buffer[:frame_size]))
            del self.buffer[:frame_size]
        return frames


@dataclass(slots=True)
class _HttpStream:
    method: str
    path: str
    headers: dict
    body: bytearray = field(default_factory=bytearray)


@dataclass(slots=True)
class _WsStream:
    websocket: object = None
    reader: asyncio.Task = None
    message_type: FrameType = None
    body: bytearray = field(default_factory=bytearray)


@dataclass(slots=True)
class _ChannelState:
    decoder: FrameDecoder = field(default_factory=FrameDecoder)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    http: dict = field(default_factory=dict)
    ws: dict = field(default_factory=dict)
    closed: bool = False


class PeerServer:
    """管理 P2P 隧道所用的共享 HTTP 会话与任务生命周期。"""

    def __init__(self, provider):
        self.provider = provider
        self.session = None
        self.upstream = ''
        self._tasks = set()
        self._channels = {}
        self._signal_tasks = {}
        self._peer_connections = {}

    @asynccontextmanager
    async def serve(self):
        """创建本机 WebUI 上游会话；上下文退出时统一回收资源。"""
        from module.runtime.setting import State

        try:
            from module.runtime.remote_access import _local_host
            host = _local_host()
        except AttributeError:
            host = '127.0.0.1'
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        config = State.deploy_config
        self.upstream = (
            f'{"https" if getattr(config, "WebuiSSLCert", None) else "http"}://'
            f'{host}:{getattr(config, "WebuiPort", 0)}'
        )
        self.session = aiohttp.ClientSession(
            auto_decompress=False,
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=5),
        )
        try:
            self.track(asyncio.create_task(self._poll_signals()))
            yield self
        finally:
            await self.cleanup()

    def track(self, task):
        """登记后台任务，并在结束时从集合移除。"""
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task):
        self._tasks.discard(task)
        self._signal_tasks = {key: value for key, value in self._signal_tasks.items() if value is not task}
        if not task.cancelled():
            task.exception()

    async def _ice_servers(self):
        """按直连 STUN 主机生成候选，并保留公共 STUN 兜底。"""
        hostname = ''
        try:
            data = await self.provider.request('GET', '/api/v1/devices/' + quote(
                self.provider.identity().load()['device_id'], safe='',
            ) + '/resolve')
            if isinstance(data, dict) and isinstance(data.get('stun'), str):
                hostname = data['stun']
        except Exception:
            hostname = ''
        if not hostname:
            hostname = urlsplit(self.provider.registry()).hostname
        if not hostname:
            return []
        if ':' in hostname:
            hostname = f'[{hostname}]'
        urls = [
            f'stun:{hostname}:3478',
            f'stun:{hostname}:34788',
            'stun:stun.cloudflare.com:3478',
            'stun:stun.l.google.com:19302',
        ]
        return [RTCIceServer(urls=[url]) for url in urls]

    async def _poll_signals(self):
        """每两秒拉取待应答 offer，并限制同时进行的 WebRTC 协商数量。"""
        device_id = quote(self.provider.identity().load()['device_id'], safe='')
        path = f'/api/v1/devices/{device_id}/signal/pending'
        while True:
            try:
                result = await self.provider.request('GET', path)
                requests = result.get('requests', []) if isinstance(result, dict) else []
            except asyncio.CancelledError:
                raise
            except Exception:
                requests = []
            if isinstance(requests, list):
                for request in requests[:MAX_SIGNAL_CONCURRENCY * 2]:
                    if len(self._signal_tasks) >= MAX_SIGNAL_CONCURRENCY:
                        break
                    if not isinstance(request, dict):
                        continue
                    signal_id, offer = request.get('id'), request.get('offer')
                    if (not isinstance(signal_id, str) or not signal_id
                            or not isinstance(offer, str) or not offer
                            or signal_id in self._signal_tasks
                            or signal_id in self._peer_connections):
                        continue
                    task = self.track(asyncio.create_task(self._answer_signal(signal_id, offer)))
                    self._signal_tasks[signal_id] = task
            await asyncio.sleep(SIGNAL_POLL_INTERVAL)

    async def _answer_signal(self, signal_id, offer):
        """为单个 offer 建立无数据通道的应答连接并回传本地 SDP。"""
        device_id = quote(self.provider.identity().load()['device_id'], safe='')
        peer = RTCPeerConnection(RTCConfiguration(iceServers=await self._ice_servers()))
        self._peer_connections[signal_id] = peer

        def datachannel(channel):
            if getattr(channel, 'label', 'tunnel') != 'tunnel':
                channel.close()
                return
            self._handle_channel(channel)

        def connection_state():
            if peer.connectionState in ('closed', 'failed'):
                if self._peer_connections.get(signal_id) is peer:
                    self._peer_connections.pop(signal_id, None)

        peer.on('datachannel', datachannel)
        peer.on('connectionstatechange', connection_state)
        try:
            await peer.setRemoteDescription(RTCSessionDescription(sdp=offer, type='offer'))
            await peer.setLocalDescription(await peer.createAnswer())
            await self.provider.request(
                'POST',
                f'/api/v1/devices/{device_id}/signal/{quote(signal_id, safe="")}/answer',
                {'answer': peer.localDescription.sdp},
            )
        except (asyncio.CancelledError, Exception):
            self._peer_connections.pop(signal_id, None)
            close = peer.close()
            if asyncio.iscoroutine(close):
                await close
            raise

    def _handle_channel(self, channel):
        """把 DataChannel 消息串行送入协议分发器并登记回收。"""
        state = _ChannelState()
        self._channels[id(channel)] = (channel, state)

        def received(message):
            if state.closed:
                return
            if not isinstance(message, (bytes, bytearray, memoryview)):
                self._close_channel_silently(channel)
                return
            state.queue.put_nowait(bytes(message))

        def closed(*_args):
            state.queue.put_nowait(None)

        channel.on('message', received)
        channel.on('close', closed)
        return self.track(asyncio.create_task(self._channel_worker(channel, state)))

    async def _channel_worker(self, channel, state):
        try:
            while not state.closed:
                message = await state.queue.get()
                if message is None:
                    break
                try:
                    for frame in state.decoder.feed(message):
                        await self._dispatch_frame(channel, state, frame)
                except (FrameDecodeError, TypeError, ValueError):
                    self._close_channel_silently(channel)
                    break
        finally:
            await self._cleanup_channel(channel, state)

    async def _dispatch_frame(self, channel, state, frame):
        if frame.type == FrameType.PING:
            self._handle_ping(channel, frame)
            return
        if frame.type == FrameType.PONG:
            raise ValueError('P2P 客户端不能发送 PONG')
        if frame.type == FrameType.HTTP_OPEN:
            await self._handle_http(channel, state, frame)
            return
        if frame.stream_id in state.http and frame.type in (FrameType.DATA, FrameType.DONE):
            await self._handle_http(channel, state, frame)
            return
        if frame.type == FrameType.WS_OPEN:
            await self._handle_ws(channel, state, frame)
            return
        if frame.stream_id in state.ws and frame.type in (
            FrameType.DATA, FrameType.WS_TEXT, FrameType.WS_BIN, FrameType.WS_CLOSE, FrameType.WS_END
        ):
            await self._handle_ws(channel, state, frame)
            return
        if frame.type in (FrameType.HTTP_HEAD, FrameType.HTTP_OPEN, FrameType.DONE,
                          FrameType.WS_TEXT, FrameType.WS_BIN, FrameType.WS_CLOSE, FrameType.WS_END):
            raise ValueError('P2P 帧类型与流状态不匹配')

    def _handle_ping(self, channel, frame):
        if frame.payload:
            self._close_channel_silently(channel)
            return
        self._send(channel, FrameType.PONG, frame.stream_id)

    def _send(self, channel, frame_type, stream_id, payload=b''):
        try:
            channel.send(encode_frame(frame_type, stream_id, payload))
            return True
        except (RuntimeError, ValueError, OSError):
            self._close_channel_silently(channel)
            return False

    @staticmethod
    def _json_payload(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()

    @staticmethod
    def _request_target(value):
        if not isinstance(value, str) or '\r' in value or '\n' in value:
            raise ValueError('P2P 请求路径无效')
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or parsed.path.startswith('//'):
            raise ValueError('P2P 请求路径必须是本机绝对路径')
        return value

    @staticmethod
    def _header_map(value):
        if not isinstance(value, dict):
            raise ValueError('P2P 请求头必须是对象')
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise ValueError('P2P 请求头必须是字符串')
            if '\r' in key or '\n' in key or '\r' in item or '\n' in item:
                raise ValueError('P2P 请求头包含换行')
            result[key] = item
        return result

    @staticmethod
    def _json_frame(value):
        payload = PeerServer._json_payload(value)
        if len(payload) > MAX_FRAME_PAYLOAD:
            raise ValueError('P2P JSON 帧超过单帧上限')
        return payload

    async def _handle_http(self, channel, state, frame):
        if frame.type == FrameType.HTTP_OPEN:
            if frame.stream_id in state.http or frame.stream_id in state.ws:
                raise ValueError('P2P streamId 重复')
            try:
                request = json.loads(frame.payload.decode('utf-8'))
            except (UnicodeError, ValueError):
                raise ValueError('P2P HTTP_OPEN 不是有效 JSON') from None
            if not isinstance(request, dict):
                raise ValueError('P2P HTTP_OPEN 必须是对象')
            method = request.get('m')
            if not isinstance(method, str) or not _METHOD.fullmatch(method):
                raise ValueError('P2P HTTP 方法无效')
            state.http[frame.stream_id] = _HttpStream(
                method=method,
                path=self._request_target(request.get('p')),
                headers=self._header_map(request.get('h', {})),
            )
            return
        stream = state.http.get(frame.stream_id)
        if stream is None:
            return
        if frame.type == FrameType.DATA:
            if len(stream.body) + len(frame.payload) > MAX_STREAM_BODY:
                state.http.pop(frame.stream_id, None)
                self._send(channel, FrameType.HTTP_HEAD, frame.stream_id,
                           self._json_frame({'s': 413, 'h': {}}))
                self._send(channel, FrameType.DONE, frame.stream_id)
                return
            stream.body.extend(frame.payload)
            return
        if frame.type != FrameType.DONE:
            raise ValueError('P2P HTTP 流收到无效帧')
        state.http.pop(frame.stream_id, None)
        self.track(asyncio.create_task(self._send_http(channel, frame.stream_id, stream)))

    async def _send_http(self, channel, stream_id, stream):
        headers = {key: value for key, value in stream.headers.items()
                   if key.lower() not in ('connection', 'upgrade', 'transfer-encoding', 'host')}
        headers = {key: value for key, value in headers.items()
                   if key.lower() != REMOTE_ACCESS_HEADER}
        headers[REMOTE_ACCESS_HEADER] = '1'
        try:
            async with self.session.request(
                stream.method,
                self.upstream + stream.path,
                headers=headers,
                data=bytes(stream.body),
                allow_redirects=False,
            ) as response:
                response_headers = {
                    key: value for key, value in response.headers.items()
                    if key.lower() not in ('connection', 'transfer-encoding')
                }
                head = self._json_frame({'s': response.status, 'h': response_headers})
                if not self._send(channel, FrameType.HTTP_HEAD, stream_id, head):
                    return
                async for chunk in response.content.iter_chunked(MAX_FRAME_PAYLOAD):
                    for offset in range(0, len(chunk), MAX_FRAME_PAYLOAD):
                        if not self._send(channel, FrameType.DATA, stream_id,
                                          chunk[offset:offset + MAX_FRAME_PAYLOAD]):
                            return
                self._send(channel, FrameType.DONE, stream_id)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            head = self._json_frame({'s': 502, 'h': {'Content-Type': 'text/plain; charset=utf-8'}})
            if self._send(channel, FrameType.HTTP_HEAD, stream_id, head):
                self._send(channel, FrameType.DATA, stream_id, b'Bad Gateway')
                self._send(channel, FrameType.DONE, stream_id)

    async def _handle_ws(self, channel, state, frame):
        if frame.type == FrameType.WS_OPEN:
            if frame.stream_id in state.http or frame.stream_id in state.ws:
                raise ValueError('P2P streamId 重复')
            try:
                request = json.loads(frame.payload.decode('utf-8'))
            except (UnicodeError, ValueError):
                raise ValueError('P2P WS_OPEN 不是有效 JSON') from None
            if not isinstance(request, dict):
                raise ValueError('P2P WS_OPEN 必须是对象')
            headers = self._header_map(request.get('h', {}))
            stream = _WsStream()
            state.ws[frame.stream_id] = stream
            headers = {
                key: value for key, value in headers.items()
                if key.lower() not in ('connection', 'upgrade', 'transfer-encoding', 'host')
                and not key.lower().startswith('sec-websocket-')
                and key.lower() != REMOTE_ACCESS_HEADER
            }
            headers[REMOTE_ACCESS_HEADER] = '1'
            try:
                stream.websocket = await self.session.ws_connect(
                    self.upstream + self._request_target(request.get('p')),
                    headers=headers,
                    max_msg_size=MAX_STREAM_BODY,
                )
            except (aiohttp.ClientError, TimeoutError, ValueError):
                state.ws.pop(frame.stream_id, None)
                self._send(channel, FrameType.WS_CLOSE, frame.stream_id)
                return
            stream.reader = self.track(asyncio.create_task(
                self._forward_ws(channel, state, frame.stream_id, stream)))
            return

        stream = state.ws.get(frame.stream_id)
        if stream is None:
            return
        if frame.type in (FrameType.WS_TEXT, FrameType.WS_BIN):
            if stream.message_type is not None:
                self._abort_ws(channel, state, frame.stream_id, stream)
                return
            stream.message_type = frame.type
            stream.body.extend(frame.payload)
        elif frame.type == FrameType.DATA:
            if stream.message_type is None:
                self._abort_ws(channel, state, frame.stream_id, stream)
                return
            stream.body.extend(frame.payload)
        elif frame.type == FrameType.WS_END:
            if stream.message_type is None:
                self._abort_ws(channel, state, frame.stream_id, stream)
                return
            if len(stream.body) > MAX_STREAM_BODY:
                self._abort_ws(channel, state, frame.stream_id, stream)
                return
            body = bytes(stream.body)
            message_type = stream.message_type
            stream.message_type, stream.body = None, bytearray()
            try:
                if message_type == FrameType.WS_TEXT:
                    await stream.websocket.send_str(body.decode('utf-8'))
                else:
                    await stream.websocket.send_bytes(body)
            except (UnicodeError, RuntimeError, aiohttp.ClientError):
                self._abort_ws(channel, state, frame.stream_id, stream)
        elif frame.type == FrameType.WS_CLOSE:
            if frame.payload:
                self._abort_ws(channel, state, frame.stream_id, stream)
                return
            await self._close_ws(channel, state, frame.stream_id, stream)
        else:
            raise ValueError('P2P WS 流收到无效帧')

    async def _forward_ws(self, channel, state, stream_id, stream):
        try:
            while True:
                message = await stream.websocket.receive()
                if message.type == aiohttp.WSMsgType.TEXT:
                    self._send_ws_message(channel, state, stream_id, FrameType.WS_TEXT,
                                          message.data.encode())
                elif message.type == aiohttp.WSMsgType.BINARY:
                    self._send_ws_message(channel, state, stream_id, FrameType.WS_BIN, message.data)
                elif message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                      aiohttp.WSMsgType.ERROR):
                    break
        finally:
            await self._close_ws(channel, state, stream_id, stream)

    def _send_ws_message(self, channel, state, stream_id, frame_type, body):
        if len(body) > MAX_STREAM_BODY:
            self._abort_ws(channel, state, stream_id, state.ws.get(stream_id))
            return
        if not self._send(channel, frame_type, stream_id, body[:MAX_FRAME_PAYLOAD]):
            return
        for offset in range(MAX_FRAME_PAYLOAD, len(body), MAX_FRAME_PAYLOAD):
            if not self._send(channel, FrameType.DATA, stream_id,
                              body[offset:offset + MAX_FRAME_PAYLOAD]):
                return
        self._send(channel, FrameType.WS_END, stream_id)

    def _abort_ws(self, channel, state, stream_id, stream):
        state.ws.pop(stream_id, None)
        self._send(channel, FrameType.WS_CLOSE, stream_id)
        if stream is not None and stream.websocket is not None:
            self.track(asyncio.create_task(stream.websocket.close()))

    async def _close_ws(self, channel, state, stream_id, stream):
        active = state.ws.get(stream_id) is stream
        if active:
            state.ws.pop(stream_id, None)
        if stream.reader is not None and stream.reader is not asyncio.current_task():
            stream.reader.cancel()
        if stream.websocket is not None:
            await stream.websocket.close()
        if active:
            self._send(channel, FrameType.WS_CLOSE, stream_id)

    def _close_channel_silently(self, channel):
        entry = self._channels.get(id(channel))
        if entry is not None:
            entry[1].closed = True
            entry[1].queue.put_nowait(None)
        try:
            channel.close()
        except Exception:
            pass

    async def _cleanup_channel(self, channel, state):
        state.closed = True
        self._channels.pop(id(channel), None)
        state.http.clear()
        websockets = [stream.websocket for stream in state.ws.values() if stream.websocket is not None]
        state.ws.clear()
        for websocket in websockets:
            await websocket.close()
        try:
            channel.close()
        except Exception:
            pass

    async def cleanup(self):
        """取消未完成任务并关闭共享会话，可安全重复调用。"""
        tasks = list(self._tasks)
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        peers = list(self._peer_connections.values())
        self._peer_connections.clear()
        for peer in peers:
            close = peer.close()
            if asyncio.iscoroutine(close):
                await close
        if self.session is not None:
            await self.session.close()
            self.session = None
