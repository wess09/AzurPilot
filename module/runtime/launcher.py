"""每个应用独立的启动器会话、命令状态与通知缓冲。"""
import asyncio
import sys
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from module.api.protocol import ApiError
from module.base.runtime_params import COMMAND_TIMEOUT, CONNECTION_EXPIRE
from module.runtime.launcher_trust import LauncherTrust
from module.runtime.password_utils import REMOTE_ACCESS_HEADER, is_local_client


def is_local_request(request):
    """直连回环与来源校验；经隧道或代理转发的请求不授予本机权限。"""
    return is_local_client(
        request.client.host if request.client else '', request.headers.get('host'),
        request.headers.get('origin'), request.headers.get(REMOTE_ACCESS_HEADER),
    ) and not any(request.headers.get(key) for key in ('forwarded', 'x-forwarded-for', 'x-forwarded-host'))


@dataclass
class LauncherConnection:
    socket: object
    loop: object
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(128))
    ready: bool = False
    #: 正在执行的调度器动作，保留引用避免任务被回收。
    tasks: set = field(default_factory=set)
    last_seen: float = field(default_factory=time.monotonic)


class LauncherService:
    """跨线程业务调用受锁保护，发送操作回到 WS 所属事件循环。"""

    def __init__(self, secret=None, runtime=None):
        self.trust = LauncherTrust(secret)
        self.runtime = runtime
        #: 托盘暂停时正在运行的实例；继续时按它恢复，为空则启动全部实例。
        self.paused = []
        self.lock = threading.RLock()
        self.connection = None
        self.commands = OrderedDict()
        self.notifications = OrderedDict()
        self.capabilities = []
        self.platform = sys.platform
        self.version = ''
        self.autostart = {'supported': False, 'enabled': None}

    async def attach(self, socket):
        connection = LauncherConnection(socket, asyncio.get_running_loop())
        with self.lock:
            previous = self.connection
            self._fail_pending('LAUNCHER_DISCONNECTED', '启动器连接已更换，请查询实际状态')
            self.connection = connection
        if previous:
            await previous.socket.close(code=1000)
        return connection

    def detach(self, connection):
        with self.lock:
            if self.connection is connection:
                self.connection = None
                self._fail_pending('LAUNCHER_DISCONNECTED', '启动器已断开，请查询实际状态')

    def hello(self, connection, params):
        with self.lock:
            if self.connection is not connection:
                raise ApiError('LAUNCHER_DISCONNECTED', '启动器会话已失效')
            if connection.ready:
                raise ApiError('INVALID_REQUEST', '启动器已完成握手')
            self.platform, self.version = params.platform, params.launcherVersion
            self.capabilities = params.capabilities
            self.autostart = params.autostart.model_dump()
            connection.ready = True
            return {'protocolVersion': 2, 'heartbeatSeconds': 15}

    def replay(self, connection):
        """握手响应先入队，客户端确认协议后才能收到缓冲通知。"""
        with self.lock:
            for message in self.notifications.values():
                self._enqueue(connection, message)

    def status(self):
        with self.lock:
            self._expire()
            connected = self.connection is not None and self.connection.ready
            return {'connected': connected, 'platform': self.platform, 'version': self.version,
                    'capabilities': list(self.capabilities) if connected else [],
                    'autostart': dict(self.autostart),
                    'commands': [dict(value) for value in self.commands.values()]}

    def set_autostart(self, enabled):
        with self.lock:
            self._expire()
            connection = self.connection
            if connection is None or not connection.ready:
                raise ApiError('LAUNCHER_DISCONNECTED', '启动器未连接')
            if 'autostart' not in self.capabilities or not self.autostart['supported']:
                raise ApiError('UNSUPPORTED', '当前启动器不支持开机自启')
            if sum(value['status'] == 'pending' for value in self.commands.values()) >= 32:
                raise ApiError('BUSY', '启动器命令队列已满')
            command_id = uuid.uuid4().hex
            self.commands[command_id] = {'id': command_id, 'status': 'pending',
                                         'deadline': time.time() + COMMAND_TIMEOUT}
            while len(self.commands) > 128:
                completed = next(key for key, value in self.commands.items() if value['status'] != 'pending')
                self.commands.pop(completed)
            message = {'type': 'request', 'id': command_id, 'method': 'autostart.set',
                       'params': {'enabled': enabled}, 'deadline': self.commands[command_id]['deadline']}
            connection.loop.call_soon_threadsafe(self._enqueue, connection, message)
            return {'commandId': command_id, 'status': 'pending'}

    def command(self, command_id):
        with self.lock:
            self._expire()
            if command_id not in self.commands:
                raise ApiError('NOT_FOUND', '启动器命令不存在')
            return dict(self.commands[command_id])

    def should_send(self, message):
        with self.lock:
            self._expire()
            return message.get('type') != 'request' or self.commands.get(message['id'], {}).get('status') == 'pending'

    def complete(self, connection, reply):
        with self.lock:
            if self.connection is not connection:
                return
            self._expire()
            command = self.commands.get(reply.id)
            if not command or command['status'] != 'pending':
                return
            if reply.ok:
                from module.api.launcher_protocol import AutostartState
                result = AutostartState.model_validate(reply.result).model_dump()
                self.autostart = result
                command.update(status='succeeded', result=result)
            else:
                command.update(status='failed', error=reply.error.model_dump())

    def report_state(self, params):
        with self.lock:
            self.autostart = params.autostart.model_dump()
        return {'accepted': True}

    def publish(self, notification):
        message = {'type': 'event', 'id': uuid.uuid4().hex, 'topic': 'notification', 'data': notification}
        with self.lock:
            self.notifications[message['id']] = message
            while len(self.notifications) > 100:
                self.notifications.popitem(last=False)
            connection = self.connection
            if connection and connection.ready:
                connection.loop.call_soon_threadsafe(self._enqueue, connection, message)

    def acknowledge(self, ids):
        with self.lock:
            for event_id in ids:
                self.notifications.pop(event_id, None)
        return {'accepted': True}

    def scheduler(self, action):
        """托盘暂停 / 继续调度器；在线程池中执行，单个实例失败不影响其余实例。

        Args:
            action: ``state`` 只查询；``pause`` 停止所有运行中的实例并记住它们；
                ``resume`` 重新启动被暂停的实例，没有记录时启动全部实例。

        Returns:
            dict: ``running`` 为当前运行中的实例名，``paused`` 为待恢复的实例名，
                ``errors`` 为失败实例的说明。
        """
        if self.runtime is None:
            raise ApiError('UNSUPPORTED', '调度器控制未启用')
        errors = []
        if action == 'pause':
            names = self._running_names()
            for name in names:
                try:
                    self.runtime.stop(name)
                except Exception as error:
                    errors.append(f'{name}: {error}')
            if names:
                with self.lock:
                    self.paused = names
        elif action == 'resume':
            running = set(self._running_names())
            with self.lock:
                targets = list(self.paused) or self.runtime.configs.names()
                self.paused = []
            for name in targets:
                if name in running:
                    continue
                try:
                    self.runtime.start(name)
                except Exception as error:
                    errors.append(f'{name}: {error}')
        with self.lock:
            paused = list(self.paused)
        return {'running': self._running_names(), 'paused': paused, 'errors': errors}

    @staticmethod
    def _running_names():
        from module.runtime.process_manager import ProcessManager
        return sorted({manager.config_name for manager in ProcessManager.running_instances()})

    def _enqueue(self, connection, message):
        if self.connection is not connection:
            return
        try:
            connection.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.detach(connection)
            connection.loop.create_task(connection.socket.close(code=1013))

    def _expire(self):
        for command in self.commands.values():
            if command['status'] == 'pending' and command['deadline'] <= time.time():
                command.update(status='expired', error={'code': 'TIMEOUT', 'message': '启动器响应超时，请查询实际状态'})
        connection = self.connection
        if connection and time.monotonic() - connection.last_seen > CONNECTION_EXPIRE:
            self.detach(connection)
            connection.loop.call_soon_threadsafe(lambda: connection.loop.create_task(connection.socket.close(code=1001)))

    def _fail_pending(self, code, message):
        for command in self.commands.values():
            if command['status'] == 'pending':
                command.update(status='failed', error={'code': code, 'message': message})

    async def close(self):
        with self.lock:
            connection = self.connection
            if connection:
                self.detach(connection)
            self.notifications.clear()
            self.trust.clear()
        if connection:
            await connection.socket.close(code=1001)
