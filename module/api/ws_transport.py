"""WebUI WebSocket 分片。每个方向同一时间传输一条完整 JSON 消息。"""
from starlette.websockets import WebSocketDisconnect

FRAME_BYTES = 64 * 1024
REQUEST_BYTES = 8 * 1024 * 1024
RESPONSE_BYTES = 64 * 1024 * 1024
DATA_TOPICS = frozenset(('logs', 'preview'))


def frames(payload):
    """每个二进制消息以 0（还有后续）或 1（最后一片）开头。"""
    size = FRAME_BYTES - 1
    for offset in range(0, len(payload), size):
        end = offset + size
        yield bytes((int(end >= len(payload)),)) + payload[offset:end]


async def receive(ws, fragmented):
    """接收一条请求，拒绝混合类型、过大的消息和不完整的分片。"""
    if not fragmented:
        return (await ws.receive_text()).encode()
    payload = bytearray()
    while True:
        message = await ws.receive()
        if message['type'] == 'websocket.disconnect':
            raise WebSocketDisconnect(message['code'])
        if (text := message.get('text')) is not None and not payload:
            raw = text.encode()
            if len(raw) <= FRAME_BYTES:
                return raw
        if (part := message.get('bytes')) and 1 < len(part) <= FRAME_BYTES:
            final = part[0]
            if (final == 1 or final == 0 and len(part) == FRAME_BYTES):
                if len(payload) + len(part) - 1 > REQUEST_BYTES:
                    await ws.close(code=1009)
                    raise WebSocketDisconnect(1009)
                payload.extend(memoryview(part)[1:])
                if final:
                    return payload
                continue
        await ws.close(code=1002)
        raise WebSocketDisconnect(1002)
