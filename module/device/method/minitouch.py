import asyncio
import json
import socket
import threading
import time
from functools import wraps
from typing import List

import websockets
from adbutils.errors import AdbError
from uiautomator2 import _Service

from module.base.decorator import Config, cached_property, del_cached_property, has_cached_property
from module.base.timer import Timer
from module.base.utils import *
from module.device.connection import Connection
from module.device.method.utils import RETRY_TRIES, handle_adb_error, handle_unknown_host_service, retry_sleep
from module.exception import EmulatorNotRunningError, RequestHumanTakeover, ScriptError
from module.logger import logger


def random_normal_distribution(a, b, n=5):
    output = np.mean(np.random.uniform(a, b, size=n))
    return output


def random_theta():
    theta = np.random.uniform(0, 2 * np.pi)
    return np.array([np.sin(theta), np.cos(theta)])


def random_rho(dis):
    return random_normal_distribution(-dis, dis)


def insert_swipe(p0, p3, speed=15, min_distance=10):
    """
    在起点和终点之间插入路径点，首先生成一条三次贝塞尔曲线。
    First generate a cubic bézier curve
    Args:
        p0: 起点坐标。
        p3: 终点坐标。
        speed: 平均移动速度，像素/10ms。
        min_distance: 最小点间距。

    Returns:
        路径点列表。

    Examples:
        > insert_swipe((400, 400), (600, 600), speed=20)
        [[400, 400], [406, 406], [416, 415], [429, 428], [444, 442], [462, 459], [481, 478], [504, 500], [527, 522],
        [545, 540], [560, 557], [573, 570], [584, 582], [592, 590], [597, 596], [600, 600]]
    """
    p0 = np.array(p0)
    p3 = np.array(p3)

    distance = np.linalg.norm(p3 - p0)

    # 贝塞尔曲线的随机控制点
    p1 = 2 / 3 * p0 + 1 / 3 * p3 + random_theta() * random_rho(distance * 0.1)
    p2 = 1 / 3 * p0 + 2 / 3 * p3 + random_theta() * random_rho(distance * 0.1)

    # 贝塞尔曲线上的随机 `t` 值，中间稀疏，两端密集
    segments = max(int(distance / speed) + 1, 5)
    lower = random_normal_distribution(-85, -60)
    upper = random_normal_distribution(80, 90)
    theta = np.arange(lower + 0., upper + 0.0001, (upper - lower) / segments)
    ts = np.sin(theta / 180 * np.pi)
    ts = np.sign(ts) * abs(ts) ** 0.9
    ts = (ts - min(ts)) / (max(ts) - min(ts))

    # 生成三次贝塞尔曲线
    points = []
    prev = (-100, -100)
    for t in ts:
        point = p0 * (1 - t) ** 3 + 3 * p1 * t * (1 - t) ** 2 + 3 * p2 * t ** 2 * (1 - t) + p3 * t ** 3
        point = point.astype(int).tolist()
        if np.linalg.norm(np.subtract(point, prev)) < min_distance:
            continue

        points.append(point)
        prev = point

    # 删除过近的点
    if len(points[1:]):
        distance = np.linalg.norm(np.subtract(points[1:], points[0]), axis=1)
        mask = np.append(True, distance > min_distance)
        points = np.array(points)[mask].tolist()
        if len(points) <= 1:
            points = [p0, p3]
    else:
        points = [p0, p3]

    return points


class Command:
    def __init__(
            self,
            operation: str,
            contact: int = 0,
            x: int = 0,
            y: int = 0,
            ms: int = 10,
            pressure: int = 100,
            mode: int = 0,
            text: str = ''
    ):
        """
        minitouch 命令，参考 https://github.com/openstf/minitouch#writable-to-the-socket

        Args:
            operation: 操作类型，c/r/d/m/u/w。
            contact: 触点索引。
            x: X 坐标。
            y: Y 坐标。
            ms: 等待时间（毫秒）。
            pressure: 压力值。
            mode: 模式。
            text: 文本内容。
        """
        self.operation = operation
        self.contact = contact
        self.x = x
        self.y = y
        self.ms = ms
        self.pressure = pressure
        self.mode = mode
        self.text = text

    def to_minitouch(self) -> str:
        """转换为写入 minitouch socket 的字符串。"""
        if self.operation == 'c':
            return f'{self.operation}\n'
        elif self.operation == 'r':
            return f'{self.operation}\n'
        elif self.operation == 'd':
            return f'{self.operation} {self.contact} {self.x} {self.y} {self.pressure}\n'
        elif self.operation == 'm':
            return f'{self.operation} {self.contact} {self.x} {self.y} {self.pressure}\n'
        elif self.operation == 'u':
            return f'{self.operation} {self.contact}\n'
        elif self.operation == 'w':
            return f'{self.operation} {self.ms}\n'
        else:
            return ''

    def to_maatouch_sync(self):
        if self.operation == 'c':
            return f'{self.operation}\n'
        elif self.operation == 'r':
            if self.mode:
                return f'{self.operation} {self.mode}\n'
            else:
                return f'{self.operation}\n'
        elif self.operation == 'd':
            if self.mode:
                return f'{self.operation} {self.contact} {self.x} {self.y} {self.pressure} {self.mode}\n'
            else:
                return f'{self.operation} {self.contact} {self.x} {self.y} {self.pressure}\n'
        elif self.operation == 'm':
            if self.mode:
                return f'{self.operation} {self.contact} {self.x} {self.y} {self.pressure} {self.mode}\n'
            else:
                return f'{self.operation} {self.contact} {self.x} {self.y} {self.pressure}\n'
        elif self.operation == 'u':
            if self.mode:
                return f'{self.operation} {self.contact} {self.mode}\n'
            else:
                return f'{self.operation} {self.ms}\n'
        elif self.operation == 'w':
            return f'{self.operation} {self.ms}\n'
        elif self.operation == 's':
            return f'{self.operation} {self.text}\n'
        else:
            return ''

    def to_atx_agent(self, max_x=1280, max_y=720) -> str:
        """
        转换为发送到 atx-agent 的字典格式，$DEVICE_URL/minitouch。
        参考 https://github.com/openatx/atx-agent#minitouch%E6%93%8D%E4%BD%9C%E6%96%B9%E6%B3%95
        """
        x, y = self.x / max_x, self.y / max_y
        if self.operation == 'c':
            out = dict(operation=self.operation)
        elif self.operation == 'r':
            out = dict(operation=self.operation)
        elif self.operation == 'd':
            out = dict(operation=self.operation, index=self.contact, pressure=self.pressure, xP=x, yP=y)
        elif self.operation == 'm':
            out = dict(operation=self.operation, index=self.contact, pressure=self.pressure, xP=x, yP=y)
        elif self.operation == 'u':
            out = dict(operation=self.operation, index=self.contact)
        elif self.operation == 'w':
            out = dict(operation=self.operation, milliseconds=self.ms)
        else:
            out = dict()
        return json.dumps(out)


class CommandBuilder:
    """构建 minitouch 命令字符串。

    可用于自定义操作::

        with safe_connection(_DEVICE_ID) as connection:
            builder = CommandBuilder()
            builder.down(0, 400, 400, 50)
            builder.commit()
            builder.move(0, 500, 500, 50)
            builder.commit()
            builder.move(0, 800, 400, 50)
            builder.commit()
            builder.up(0)
            builder.commit()
            builder.publish(connection)

    """
    DEFAULT_DELAY = 0.05
    max_x = 1280
    max_y = 720

    def __init__(
            self,
            device,
            contact=0,
            handle_orientation=True,
    ):
        """
        Args:
            device: 设备实例。
        """
        self.device = device
        self.commands = []
        self.delay = 0
        self.contact = contact
        self.handle_orientation = handle_orientation

    @property
    def orientation(self):
        if self.handle_orientation:
            return self.device.orientation
        else:
            return 0

    def convert(self, x, y):
        max_x, max_y = self.device.max_x, self.device.max_y
        orientation = self.orientation

        if orientation == 0:
            pass
        elif orientation == 1:
            x, y = 720 - y, x
            max_x, max_y = max_y, max_x
        elif orientation == 2:
            x, y = 1280 - x, 720 - y
        elif orientation == 3:
            x, y = y, 1280 - x
            max_x, max_y = max_y, max_x
        else:
            raise ScriptError(f'Invalid device orientation: {orientation}')

        self.max_x, self.max_y = max_x, max_y
        if not self.device.config.DEVICE_OVER_HTTP:
            # 最大 X 和 Y 坐标可能（但通常不会）与显示尺寸匹配
            x, y = int(x / 1280 * max_x), int(y / 720 * max_y)
        else:
            # HTTP 模式下 max_x 和 max_y 默认为 1280 和 720，跳过显示尺寸匹配
            x, y = int(x), int(y)
        return x, y

    def commit(self):
        """添加 minitouch 命令：'c\n'。"""
        self.commands.append(Command(
            'c'
        ))
        return self

    def reset(self, mode=0):
        """添加 minitouch 命令：'r\n'。"""
        self.commands.append(Command(
            'r', mode=mode
        ))
        return self

    def wait(self, ms=10):
        """添加 minitouch 命令：'w <ms>\n'。"""
        self.commands.append(Command(
            'w', ms=ms
        ))
        self.delay += ms
        return self

    def up(self, mode=0):
        """添加 minitouch 命令：'u <contact>\n'。"""
        self.commands.append(Command(
            'u', contact=self.contact, mode=mode
        ))
        return self

    def down(self, x, y, pressure=100, mode=0):
        """添加 minitouch 命令：'d <contact> <x> <y> <pressure>\n'。"""
        x, y = self.convert(x, y)
        self.commands.append(Command(
            'd', x=x, y=y, contact=self.contact, pressure=pressure, mode=mode
        ))
        return self

    def move(self, x, y, pressure=100, mode=0):
        """添加 minitouch 命令：'m <contact> <x> <y> <pressure>\n'。"""
        x, y = self.convert(x, y)
        self.commands.append(Command(
            'm', x=x, y=y, contact=self.contact, pressure=pressure, mode=mode
        ))
        return self

    def clear(self):
        """清空当前命令列表。"""
        self.commands = []
        self.delay = 0
        return self

    def to_minitouch(self) -> str:
        out = ''.join([command.to_minitouch() for command in self.commands])
        self._check_empty(out)
        return out

    def to_maatouch_sync(self) -> str:
        out = ''.join([command.to_maatouch_sync() for command in self.commands])
        self._check_empty(out)
        return out

    def to_atx_agent(self) -> List[str]:
        out = [command.to_atx_agent(self.max_x, self.max_y) for command in self.commands]
        self._check_empty(out)
        return out

    def send(self):
        return self.device.minitouch_send(builder=self)

    def _check_empty(self, text=None):
        """
        检查命令列表是否为空。有效的命令列表必须包含除提交和等待之外的操作。

        Returns:
            命令列表是否为空。
        """
        empty = True
        for command in self.commands:
            if command.operation not in ['c', 'w', 's']:
                empty = False
                break
        if empty:
            logger.warning(f'Command list empty, sending it may cause unexpected behaviour: {text}')
        return empty


class MinitouchNotInstalledError(Exception):
    pass


class MinitouchOccupiedError(Exception):
    pass


class U2Service(_Service):
    def __init__(self, name, u2obj):
        self.name = name
        self.u2obj = u2obj
        self.service_url = self.u2obj.path2url("/services/" + name)


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Minitouch):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 无法处理
            except RequestHumanTakeover:
                break
            # ADB 服务被终止时
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
                    if self._minitouch_port:
                        self.adb_forward_remove(f'tcp:{self._minitouch_port}')
                    del_cached_property(self, '_minitouch_builder')
            # 模拟器关闭
            except ConnectionAbortedError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
                    if self._minitouch_port:
                        self.adb_forward_remove(f'tcp:{self._minitouch_port}')
                    del_cached_property(self, '_minitouch_builder')
            # MinitouchNotInstalledError: 从 minitouch 收到空数据
            except MinitouchNotInstalledError as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()
                    if self._minitouch_port:
                        self.adb_forward_remove(f'tcp:{self._minitouch_port}')
                    del_cached_property(self, '_minitouch_builder')
            # MinitouchOccupiedError: 连接 minitouch 超时
            except MinitouchOccupiedError as e:
                logger.error(e)

                def init():
                    self.restart_atx()
                    if self._minitouch_port:
                        self.adb_forward_remove(f'tcp:{self._minitouch_port}')
                    del_cached_property(self, '_minitouch_builder')
            # ADB 错误
            except AdbError as e:
                if handle_adb_error(e):
                    def init():
                        self.adb_reconnect()
                        if self._minitouch_port:
                            self.adb_forward_remove(f'tcp:{self._minitouch_port}')
                        del_cached_property(self, '_minitouch_builder')
                elif handle_unknown_host_service(e):
                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                        if self._minitouch_port:
                            self.adb_forward_remove(f'tcp:{self._minitouch_port}')
                        del_cached_property(self, '_minitouch_builder')
                else:
                    break
            except BrokenPipeError as e:
                logger.error(e)

                def init():
                    del_cached_property(self, '_minitouch_builder')
            # 无法处理 - 必须向上抛出以触发模拟器重启
            except EmulatorNotRunningError:
                raise
            # 未知异常，可能是图像损坏
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        if func.__name__ in ['_minitouch_builder']:
            logger.critical(f'重试 {func.__name__}() 失败')
            raise EmulatorNotRunningError

        logger.critical(f'重试 {func.__name__}() 失败')
        raise RequestHumanTakeover

    return retry_wrapper


class Minitouch(Connection):
    _minitouch_port: int = 0
    _minitouch_client: socket.socket = None
    _minitouch_pid: int
    _minitouch_ws: websockets.WebSocketClientProtocol
    max_x: int
    max_y: int
    _minitouch_init_thread = None

    @cached_property
    @retry
    def _minitouch_builder(self):
        self.minitouch_init()
        return CommandBuilder(self)

    @property
    def minitouch_builder(self):
        # 等待初始化线程完成
        if self._minitouch_init_thread is not None:
            self._minitouch_init_thread.join()
            del self._minitouch_init_thread
            self._minitouch_init_thread = None

        return self._minitouch_builder

    def early_minitouch_init(self):
        """
        在 Alas 实例开始截图时启动线程初始化 minitouch 连接。
        这将加速首次点击约 0.05 秒。
        """
        if has_cached_property(self, '_minitouch_builder'):
            return

        def early_minitouch_init_func():
            _ = self._minitouch_builder

        thread = threading.Thread(target=early_minitouch_init_func, daemon=True)
        self._minitouch_init_thread = thread
        thread.start()

    @Config.when(DEVICE_OVER_HTTP=False)
    def minitouch_init(self):
        logger.hr('MiniTouch init')
        max_x, max_y = 1280, 720
        max_contacts = 2
        max_pressure = 50

        # 尝试关闭已有连接
        if self._minitouch_client is not None:
            try:
                self._minitouch_client.close()
            except Exception as e:
                logger.error(e)
            del self._minitouch_client

        self.get_orientation()

        self._minitouch_port = self.adb_forward("localabstract:minitouch")

        # 无需手动启动，minitouch 已由 uiautomator2 启动
        # self.adb_shell([self.config.MINITOUCH_FILEPATH_REMOTE])

        retry_timeout = Timer(2).start()
        while 1:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(1)
            client.connect(('127.0.0.1', self._minitouch_port))
            self._minitouch_client = client

            # 获取 minitouch 服务端信息
            socket_out = client.makefile()

            # v <version>
            # 协议版本，通常为 1，无需使用
            try:
                out = socket_out.readline().replace("\n", "").replace("\r", "")
            except socket.timeout:
                client.close()
                raise MinitouchOccupiedError(
                    'Timeout when connecting to minitouch, '
                    'probably because another connection has been established'
                )
            logger.info(out)

            # ^ <max-contacts> <max-x> <max-y> <max-pressure>
            out = socket_out.readline().replace("\n", "").replace("\r", "")
            logger.info(out)
            try:
                _, max_contacts, max_x, max_y, max_pressure, *_ = out.split(" ")
                break
            except ValueError:
                client.close()
                if retry_timeout.reached():
                    raise MinitouchNotInstalledError(
                        'Received empty data from minitouch, '
                        'probably because minitouch is not installed'
                    )
                else:
                    # minitouch 可能启动没那么快
                    self.sleep(1)
                    continue

        # self.max_contacts = max_contacts
        self.max_x = int(max_x)
        self.max_y = int(max_y)
        # self.max_pressure = max_pressure

        # $ <pid>
        out = socket_out.readline().replace("\n", "").replace("\r", "")
        logger.info(out)
        _, pid = out.split(" ")
        self._minitouch_pid = pid

        logger.info(
            "minitouch running on port: {}, pid: {}".format(self._minitouch_port, self._minitouch_pid)
        )
        logger.info(
            "max_contact: {}; max_x: {}; max_y: {}; max_pressure: {}".format(
                max_contacts, max_x, max_y, max_pressure
            )
        )

    @Config.when(DEVICE_OVER_HTTP=False)
    def minitouch_send(self, builder: CommandBuilder):
        content = builder.to_minitouch()
        # logger.info("send operation: {}".format(content.replace("\n", "\\n")))
        byte_content = content.encode('utf-8')
        self._minitouch_client.sendall(byte_content)
        self._minitouch_client.recv(0)
        time.sleep(self.minitouch_builder.delay / 1000 + builder.DEFAULT_DELAY)
        builder.clear()

    @cached_property
    def _minitouch_loop(self):
        return asyncio.new_event_loop()

    def _minitouch_loop_run(self, event):
        """
        运行异步事件循环。

        Args:
            event: 异步函数。

        Raises:
            MinitouchOccupiedError: 连接被占用时抛出。
        """
        try:
            return self._minitouch_loop.run_until_complete(event)
        except websockets.ConnectionClosedError as e:
            # ConnectionClosedError: no close frame received or sent
            # ConnectionClosedError: sent 1011 (unexpected error) keepalive ping timeout; no close frame received
            logger.error(e)
            raise MinitouchOccupiedError(
                'ConnectionClosedError, '
                'probably because another connection has been established'
            )

    @Config.when(DEVICE_OVER_HTTP=True)
    def minitouch_init(self):
        logger.hr('MiniTouch init')
        self.max_x, self.max_y = 1280, 720
        self.get_orientation()

        logger.info('Stop minitouch service')
        s = U2Service('minitouch', self.u2)
        s.stop()
        while 1:
            if not s.running():
                break
            self.sleep(0.05)

        logger.info('Start minitouch service')
        s.start()
        while 1:
            if s.running():
                break
            self.sleep(0.05)

        # 'ws://127.0.0.1:7912/minitouch'
        url = re.sub(r"^https?://", 'ws://', self.serial) + '/minitouch'
        logger.attr('Minitouch', url)

        async def connect():
            ws = await websockets.connect(url)
            # 启动 @minitouch 服务
            logger.info(await ws.recv())
            # 连接 unix:@minitouch
            logger.info(await ws.recv())
            return ws

        self._minitouch_ws = self._minitouch_loop_run(connect())

    @Config.when(DEVICE_OVER_HTTP=True)
    def minitouch_send(self, builder: CommandBuilder):
        content = builder.to_atx_agent()

        async def send():
            for row in content:
                # logger.info("send operation: {}".format(row.replace("\n", "\\n")))
                await self._minitouch_ws.send(row)

        self._minitouch_loop_run(send())
        time.sleep(builder.delay / 1000 + builder.DEFAULT_DELAY)
        builder.clear()

    @retry
    def click_minitouch(self, x, y):
        builder = self.minitouch_builder
        builder.down(x, y).commit()
        builder.up().commit()
        builder.send()

    @retry
    def long_click_minitouch(self, x, y, duration=1.0):
        duration = int(duration * 1000)
        builder = self.minitouch_builder
        builder.down(x, y).commit().wait(duration)
        builder.up().commit()
        builder.send()

    @retry
    def swipe_minitouch(self, p1, p2):
        points = insert_swipe(p0=p1, p3=p2)
        builder = self.minitouch_builder

        builder.down(*points[0]).commit().wait(10)
        builder.send()

        for point in points[1:]:
            builder.move(*point).commit().wait(10)
        builder.send()

        builder.up().commit()
        builder.send()

    @retry
    def drag_minitouch(self, p1, p2, point_random=(-10, -10, 10, 10)):
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        points = insert_swipe(p0=p1, p3=p2, speed=20)
        builder = self.minitouch_builder

        builder.down(*points[0]).commit().wait(10)
        builder.send()

        for point in points[1:]:
            builder.move(*point).commit().wait(10)
        builder.send()

        builder.move(*p2).commit().wait(140)
        builder.move(*p2).commit().wait(140)
        builder.send()

    def island_swipe_hold_minitouch(self, p1, p2, hold_time):
        points = insert_swipe(p0=p1, p3=p2)
        builder = self.minitouch_builder
        builder.down(*points[0]).commit().wait(10)
        builder.send()
        for point in points[1:]:
            builder.move(*point).commit().wait(10)
        builder.send()
        builder.wait(hold_time)
        builder.send()
        builder.up().commit()
        builder.send()
