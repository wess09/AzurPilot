"""启动器独立 WS 入口：回环鉴权、严格方法分发与有界收发。"""
import asyncio
import json
import time
from collections import deque

from pydantic import ValidationError
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from module.api.launcher_protocol import INCOMING_METHODS, SCHEDULER_METHODS, LauncherRequest, LauncherResponse
from module.api.protocol import ApiError
from module.logger import logger
from module.runtime.launcher import is_local_request


class LauncherGateway:
    def __init__(self, service):
        self.service = service
        self.failures = deque(maxlen=15)

    async def endpoint(self, ws):
        if not is_local_request(ws):
            await ws.close(code=1008)
            return
        now = time.monotonic()
        while self.failures and now - self.failures[0] > 300:
            self.failures.popleft()
        authorization = ws.headers.get('authorization', '')
        if (len(self.failures) >= 15 or not authorization.startswith('Bearer ')
                or not self.service.trust.check_secret(authorization[7:])):
            if len(self.failures) < 15:
                self.failures.append(now)
            await ws.close(code=1008)
            return
        await ws.accept()
        connection = await self.service.attach(ws)
        writer = asyncio.create_task(self.writer(ws, connection))
        received = deque(maxlen=128)
        request_times = deque()
        try:
            while self.service.connection is connection:
                frame = await asyncio.wait_for(ws.receive(), timeout=45 if connection.ready else 5)
                if self.service.connection is not connection:
                    break
                if frame['type'] == 'websocket.disconnect':
                    break
                raw = frame.get('text')
                if raw is None:
                    await ws.close(code=1003)
                    break
                if len(raw.encode('utf-8')) > 65536:
                    await ws.close(code=1009)
                    break
                connection.last_seen = time.monotonic()
                request_times.append(connection.last_seen)
                while request_times and connection.last_seen - request_times[0] >= 1:
                    request_times.popleft()
                if len(request_times) > 30:
                    await ws.close(code=1008)
                    break
                request_id = ''
                replay = False
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict) and isinstance(data.get('id'), str):
                        request_id = data['id'][:100]
                    if isinstance(data, dict) and data.get('type') == 'response':
                        if not connection.ready:
                            raise ApiError('UNAUTHORIZED', '请先完成握手')
                        self.service.complete(connection, LauncherResponse.model_validate(data))
                        continue
                    request = LauncherRequest.model_validate(data)
                    if request.id in received:
                        raise ApiError('DUPLICATE_REQUEST', '请求 ID 已使用')
                    received.append(request.id)
                    model = INCOMING_METHODS.get(request.method)
                    if model is None:
                        raise ApiError('METHOD_NOT_FOUND', '未知启动器方法')
                    params = model.model_validate(request.params)
                    if request.method == 'session.hello':
                        result = self.service.hello(connection, params)
                        replay = True
                    elif not connection.ready:
                        raise ApiError('UNAUTHORIZED', '请先完成握手')
                    elif request.method == 'state.report':
                        result = self.service.report_state(params)
                    elif request.method == 'notifications.ack':
                        result = self.service.acknowledge(params.ids)
                    elif request.method == 'login.issue':
                        result = self.service.trust.issue()
                    elif request.method in SCHEDULER_METHODS:
                        connection.tasks.add(asyncio.create_task(
                            self.scheduler(connection, request.id, SCHEDULER_METHODS[request.method])))
                        continue
                    else:
                        result = {'pong': True}
                    message = {'type': 'response', 'id': request.id, 'ok': True, 'result': result}
                except (ValidationError, ValueError, TypeError):
                    message = self.failure(request_id, 'INVALID_PARAMS', '启动器报文或参数无效')
                except ApiError as error:
                    message = self.failure(request_id, error.code, error.message)
                self.service._enqueue(connection, message)
                if replay:
                    self.service.replay(connection)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            self.service.detach(connection)
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            if ws.application_state.name != 'DISCONNECTED' and ws.client_state.name != 'DISCONNECTED':
                await ws.close(code=1001)

    async def scheduler(self, connection, request_id, action):
        """在线程池执行调度器动作，完成后把响应放回该连接的发送队列。"""
        try:
            result = await asyncio.to_thread(self.service.scheduler, action)
            message = {'type': 'response', 'id': request_id, 'ok': True, 'result': result}
        except ApiError as error:
            message = self.failure(request_id, error.code, error.message)
        except Exception:
            logger.exception(f'启动器调度器动作 {action} 失败')
            message = self.failure(request_id, 'SCHEDULER_FAILED', '调度器操作失败，请查看日志')
        finally:
            connection.tasks.discard(asyncio.current_task())
        self.service._enqueue(connection, message)

    async def writer(self, ws, connection):
        try:
            while True:
                message = await connection.queue.get()
                if self.service.should_send(message):
                    await asyncio.wait_for(ws.send_json(message), timeout=5)
        except (WebSocketDisconnect, asyncio.TimeoutError, OSError):
            self.service.detach(connection)
            if ws.application_state.name != 'DISCONNECTED' and ws.client_state.name != 'DISCONNECTED':
                await ws.close(code=1013)

    @staticmethod
    def failure(request_id, code, message):
        return {'type': 'response', 'id': request_id, 'ok': False, 'error': {'code': code, 'message': message}}


def routes(service):
    return [WebSocketRoute('/api/v2/launcher/ws', LauncherGateway(service).endpoint),
            Route('/api/launcher/{path:path}', removed, methods=['GET', 'POST']),
            Route('/launcher-login', removed)]


async def removed(request):
    """旧协议明确 404，不能落入 SPA 回退并返回网页。"""
    return Response(status_code=404)
