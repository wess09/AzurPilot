"""验证 P2P 帧协议、HTTP 隧道、保活及信令应答，不建立真实 WebRTC 回环。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from module.runtime.remote_p2p import (
    MAX_FRAME_PAYLOAD,
    Frame,
    FrameDecoder,
    FrameType,
    PeerServer,
    decode_frame,
    encode_frame,
)


class FakeDataChannel:
    def __init__(self):
        self.handlers = {}
        self.frames = []
        self.closed = False

    def on(self, event, callback):
        self.handlers[event] = callback

    def send(self, data):
        self.frames.append(decode_frame(data))

    def close(self):
        if self.closed:
            return
        self.closed = True
        callback = self.handlers.get('close')
        if callback:
            callback()

    def emit(self, frame):
        self.handlers['message'](frame)


class StubProvider:
    def __init__(self):
        self.pending = {'requests': []}
        self.calls = []
        self.answered = asyncio.Event()

    def identity(self):
        return SimpleNamespace(load=lambda: {'device_id': '1234567890abcdef1234'})

    def registry(self):
        return 'https://signal.example'

    async def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method == 'GET':
            requests, self.pending['requests'] = self.pending['requests'], []
            return {'requests': requests}
        self.answered.set()
        return {'ok': True}


async def wait_for_frame(channel, frame_type, timeout=2):
    async with asyncio.timeout(timeout):
        while not any(frame.type == frame_type for frame in channel.frames):
            await asyncio.sleep(0.01)


def test_frame_codec_roundtrip():
    frames = []
    for index, frame_type in enumerate(FrameType, start=1):
        payload = b'' if frame_type in (
            FrameType.DONE, FrameType.WS_CLOSE, FrameType.PING, FrameType.PONG, FrameType.WS_END
        ) else b'payload-' + bytes([index])
        frames.append(Frame(frame_type, index, payload))
    frames.append(Frame(FrameType.DATA, 65535, b'x' * MAX_FRAME_PAYLOAD))
    encoded = [frame.encode() for frame in frames]

    decoder = FrameDecoder()
    decoded = []
    for data in encoded:
        encoded_frame = b''.join([data[:2], data[2:5], data[5:]])
        decoded.extend(decoder.feed(encoded_frame[:6]))
        decoded.extend(decoder.feed(encoded_frame[6:]))

    assert decoded == frames
    assert [decode_frame(data) for data in encoded] == frames


async def _http_tunnel_scenario():
    received = {}

    async def echo(request):
        received['remote_access'] = request.headers.get('x-azurpilot-remote-access')
        received['host'] = request.headers.get('Host')
        received['query'] = request.query.get('value')
        received['body'] = await request.read()
        return web.Response(body=b'response', headers={'Connection': 'keep-alive', 'X-Test': 'yes'})

    application = web.Application()
    application.router.add_route('*', '/echo', echo)
    upstream = TestServer(application)
    await upstream.start_server()
    upstream_port = upstream.port
    provider = StubProvider()
    channel = FakeDataChannel()
    config = SimpleNamespace(WebuiPort=upstream_port, WebuiHost='127.0.0.1', WebuiSSLCert=None)
    try:
        with patch('module.runtime.setting.State.deploy_config', config), \
                patch('module.runtime.remote_access.State.webui_host', '127.0.0.1'):
            async with PeerServer(provider).serve() as peer:
                peer.upstream = str(upstream.make_url('/')).rstrip('/')
                peer._handle_channel(channel)
                channel.emit(encode_frame(FrameType.HTTP_OPEN, 3, json.dumps({
                    'm': 'POST',
                    'p': '/echo?value=kept',
                    'h': {'Host': 'untrusted.invalid', 'X-Input': 'yes', 'Connection': 'keep-alive'},
                }).encode()))
                channel.emit(encode_frame(FrameType.DATA, 3, b'request-'))
                channel.emit(encode_frame(FrameType.DATA, 3, b'body'))
                channel.emit(encode_frame(FrameType.DONE, 3))
                await wait_for_frame(channel, FrameType.DONE)
    finally:
        await upstream.close()

    assert received == {
        'remote_access': '1',
        'host': f'127.0.0.1:{upstream_port}',
        'query': 'kept',
        'body': b'request-body',
    }
    assert [frame.type for frame in channel.frames] == [
        FrameType.HTTP_HEAD, FrameType.DATA, FrameType.DONE,
    ]
    head = json.loads(channel.frames[0].payload)
    assert head['s'] == 200
    assert head['h']['X-Test'] == 'yes'
    assert 'Connection' not in head['h']
    assert channel.frames[1].payload == b'response'


def test_http_tunnel_uses_upstream_and_remote_authentication():
    asyncio.run(_http_tunnel_scenario())


async def _ping_scenario():
    channel = FakeDataChannel()
    server = PeerServer(StubProvider())
    try:
        server._handle_channel(channel)
        channel.emit(encode_frame(FrameType.PING, 9))
        await wait_for_frame(channel, FrameType.PONG)
    finally:
        await server.cleanup()

    assert channel.frames == [Frame(FrameType.PONG, 9)]


def test_ping_returns_pong():
    asyncio.run(_ping_scenario())


async def _signal_scenario():
    class FakePeerConnection:
        instances = []

        def __init__(self, configuration):
            self.configuration = configuration
            self.handlers = {}
            self.localDescription = None
            self.connectionState = 'new'
            self.closed = False
            self.__class__.instances.append(self)

        def on(self, event, callback):
            self.handlers[event] = callback

        async def setRemoteDescription(self, description):
            self.remoteDescription = description

        async def createAnswer(self):
            return SimpleNamespace(sdp='local-answer', type='answer')

        async def setLocalDescription(self, description):
            self.localDescription = description
            self.connectionState = 'connecting'
            self.handlers['connectionstatechange']()

        def close(self):
            self.closed = True

    provider = StubProvider()
    provider.pending['requests'] = [{'id': 'signal-1', 'offer': 'remote-offer'}]

    async def request(method, path, data=None):
        if path.endswith('/resolve'):
            return {'stun': '192.0.2.1'}
        return await StubProvider.request(provider, method, path, data)

    provider.request = request
    config = SimpleNamespace()
    try:
        with patch('module.runtime.setting.State.deploy_config', config), \
                patch('module.runtime.remote_access.State.webui_host', None), \
                patch('module.runtime.remote_p2p.RTCPeerConnection', FakePeerConnection):
            server = PeerServer(provider)
            async with server.serve():
                await asyncio.wait_for(provider.answered.wait(), 2)
                peer = FakePeerConnection.instances[-1]
                assert server._peer_connections['signal-1'] is peer
                peer.connectionState = 'connected'
                peer.handlers['connectionstatechange']()
                assert server._peer_connections['signal-1'] is peer
                peer.connectionState = 'closed'
                peer.closed = True
                peer.handlers['connectionstatechange']()
                assert 'signal-1' not in server._peer_connections
    finally:
        provider.answered.set()

    assert provider.calls[-1] == (
        'POST',
        '/api/v1/devices/1234567890abcdef1234/signal/signal-1/answer',
        {'answer': 'local-answer'},
    )
    peer = FakePeerConnection.instances[-1]
    assert 'connectionstatechange' in peer.handlers
    assert peer.remoteDescription.sdp == 'remote-offer'
    assert peer.localDescription.sdp == 'local-answer'
    assert peer.closed
    assert [ice.urls for ice in peer.configuration.iceServers] == [
        ['stun:192.0.2.1:3478'],
        ['stun:192.0.2.1:34788'],
        ['stun:stun.cloudflare.com:3478'],
        ['stun:stun.l.google.com:19302'],
    ]


def test_signal_pending_creates_answer():
    asyncio.run(_signal_scenario())
