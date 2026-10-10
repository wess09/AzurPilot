"""
MaaTouch 触控输入方法。

基于 MaaTouch 工具实现高性能的设备触控操作。
MaaTouch 是 minitouch 的增强替代方案，通过 WebSocket 协议与设备通信，
支持更高的触控采样率和更稳定的连接。提供点击、长按、滑动等触控操作，
滑动使用贝塞尔曲线插值生成自然轨迹。兼容 minitouch 的命令格式，
通过 ADB 端口转发建立 WebSocket 连接。
"""
import socket
import threading
import time
from functools import partial

from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.base.timer import Timer
from module.base.utils import *
from module.device.connection import Connection
from module.device.method.retry import retry_backend, recover_adb, recover_unknown
from module.device.method.minitouch import Command, CommandBuilder, insert_swipe
from module.exception import EmulatorNotRunningError
from module.logger import logger


def _retry_recover(self, error, trial):
    def reconnect():
        self.adb_reconnect()
        del_cached_property(self, '_maatouch_builder')

    if isinstance(error, (ConnectionResetError, ConnectionAbortedError, AdbError)):
        return recover_adb(self, error, reconnect=reconnect)
    if isinstance(error, MaaTouchSyncTimeout):
        logger.error(error)
        def reset():
            reconnect()
            self.reset_maatouch()
        return reset
    if isinstance(error, MaaTouchNotInstalledError):
        logger.error(error)
        def install():
            self.maatouch_install()
            del_cached_property(self, '_maatouch_builder')
        return install
    if isinstance(error, BrokenPipeError):
        logger.error(error)
        return lambda: del_cached_property(self, '_maatouch_builder')
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-MaaTouch')


class MaatouchBuilder(CommandBuilder):
    def __init__(
            self,
            device,
            contact=0,
            handle_orientation=False,
    ):
        """
        Args:
            device (MaaTouch): MaaTouch 设备实例。
        """

        super().__init__(device, contact, handle_orientation)

    def send(self):
        return self.device.maatouch_send(builder=self)

    def send_sync(self, mode=2, post_delay=True):
        return self.device.maatouch_send_sync(builder=self, mode=mode, post_delay=post_delay)

    def end(self):
        self.device.sleep(self.DEFAULT_DELAY)


class MaaTouchNotInstalledError(Exception):
    pass


class MaaTouchSyncTimeout(Exception):
    pass


class MaaTouch(Connection):
    """
    实现与 scrcpy 相同功能、接口类似 minitouch 的控制方案。
    https://github.com/MaaAssistantArknights/MaaTouch
    """
    max_x: int
    max_y: int
    _maatouch_stream: socket.socket = None
    _maatouch_stream_storage = None
    _maatouch_init_thread = None
    _maatouch_orientation: int = None

    @cached_property
    @retry(on_exhausted=EmulatorNotRunningError)
    def _maatouch_builder(self):
        self.maatouch_init()
        return MaatouchBuilder(self)

    @property
    def maatouch_builder(self):
        # 等待初始化线程完成
        if self._maatouch_init_thread is not None:
            self._maatouch_init_thread.join()
            del self._maatouch_init_thread
            self._maatouch_init_thread = None

        # 返回空的 builder
        self._maatouch_builder.clear()
        return self._maatouch_builder

    def early_maatouch_init(self):
        """
        在 Alas 实例开始截图时启动线程初始化 maatouch 连接。
        这将加速首次点击约 0.2 ~ 0.4 秒。
        """
        if has_cached_property(self, '_maatouch_builder'):
            return

        def early_maatouch_init_func():
            _ = self._maatouch_builder

        thread = threading.Thread(target=early_maatouch_init_func, daemon=True)
        self._maatouch_init_thread = thread
        thread.start()

    def on_orientation_change_maatouch(self):
        """
        MaaTouch 在启动时缓存设备方向。
        方向改变时需要重启。
        """
        if self._maatouch_orientation is None:
            return
        if self.orientation == self._maatouch_orientation:
            return

        logger.info(f'方向已变更 {self._maatouch_orientation} => {self.orientation}, re-init MaaTouch')
        del_cached_property(self, '_maatouch_builder')
        self.early_maatouch_init()

    def maatouch_init(self):
        logger.hr('[设备-MaaTouch] 初始化')
        max_x, max_y = 1280, 720
        max_contacts = 2
        max_pressure = 50

        # 尝试关闭已有连接
        if self._maatouch_stream is not None:
            try:
                self._maatouch_stream.close()
            except Exception as e:
                logger.error(e)
            del self._maatouch_stream
        if self._maatouch_stream_storage is not None:
            del self._maatouch_stream_storage

        # MaaTouch 在启动时缓存设备方向
        super(MaaTouch, self).get_orientation()
        self._maatouch_orientation = self.orientation

        # CLASSPATH=/data/local/tmp/maatouch app_process / com.shxyke.MaaTouch.App
        stream = self.adb_shell(
            [f'CLASSPATH={self.config.MAATOUCH_FILEPATH_REMOTE}', 'app_process', '/', 'com.shxyke.MaaTouch.App'],
            stream=True,
            recvall=False
        )
        # 防止 shell stream 被删除导致 socket 关闭
        self._maatouch_stream_storage = stream
        stream = stream.conn
        stream.settimeout(10)
        self._maatouch_stream = stream

        retry_timeout = Timer(5).start()
        while 1:
            # v <version>
            # 协议版本，通常为 1，无需使用
            # 获取 maatouch 服务端信息
            socket_out = stream.makefile()

            # ^ <max-contacts> <max-x> <max-y> <max-pressure>
            out = socket_out.readline().replace("\n", "").replace("\r", "")
            logger.info(out)
            if out.strip() == 'Aborted':
                stream.close()
                raise MaaTouchNotInstalledError(
                    'Received "Aborted" MaaTouch, '
                    'probably because MaaTouch is not installed'
                )
            try:
                _, max_contacts, max_x, max_y, max_pressure = out.split(" ")
                break
            except ValueError:
                stream.close()
                if retry_timeout.reached():
                    raise MaaTouchNotInstalledError(
                        'Received empty data from MaaTouch, '
                        'probably because MaaTouch is not installed'
                    )
                else:
                    # maatouch 可能启动没那么快
                    self.sleep(1)
                    continue

        # self.max_contacts = max_contacts
        self.max_x = int(max_x)
        self.max_y = int(max_y)
        # self.max_pressure = max_pressure

        # $ <pid>
        out = socket_out.readline().replace("\n", "").replace("\r", "")
        logger.info(out)
        # _, pid = out.split(" ")
        # self._maatouch_pid = pid

        # 同步超时 2 秒
        stream.settimeout(2)
        logger.info(
            "MaaTouch stream connected"
        )
        logger.info(
            "max_contact: {}; max_x: {}; max_y: {}; max_pressure: {}".format(
                max_contacts, max_x, max_y, max_pressure
            )
        )

    def maatouch_send(self, builder: MaatouchBuilder):
        """
        向 MaaTouch 守护进程发送无同步触控指令序列。

        Args:
            builder: 构建完成的 MaaTouch 命令构造器。
        """
        content = builder.to_minitouch()
        # logger.info("send operation: {}".format(content.replace("\n", "\\n")))
        byte_content = content.encode('utf-8')
        self._maatouch_stream.sendall(byte_content)
        self._maatouch_stream.recv(0)
        self.sleep(builder.delay / 1000 + builder.DEFAULT_DELAY)
        builder.clear()

    def maatouch_send_sync(self, builder: MaatouchBuilder, mode=2, post_delay=True):
        """
        向 MaaTouch 守护进程发送带有时间戳同步标识的触控指令序列。

        Args:
            builder: 构建完成的 MaaTouch 命令构造器。
            mode: 注入模式，默认为 2（等待系统触控分发确认）。
            post_delay: 是否追加常规手势结束延时；连续触点由调用方控制移动速率。

        Raises:
            MaaTouchSyncTimeout: 同步响应超时。
            MaaTouchNotInstalledError: MaaTouch 进程异常终止或未安装。
        """
        # 设置最后一条命令的注入模式
        for command in builder.commands[::-1]:
            if command.operation in ['r', 'd', 'm', 'u']:
                command.mode = mode
                break

        # 添加 maatouch 同步命令：'s <timestamp>\n'
        timestamp = str(int(time.time() * 1000))
        builder.commands.insert(0, Command(
            's', text=timestamp
        ))

        # 发送
        content = builder.to_maatouch_sync()
        # logger.info("send operation: {}".format(content.replace("\n", "\\n")))
        byte_content = content.encode('utf-8')
        self._maatouch_stream.sendall(byte_content)
        self._maatouch_stream.recv(0)

        # 等待操作完成
        # 命令批次里可能带 w <ms> 的长等待（例如岛屿行走要保持数秒），
        # 服务端要等这批命令执行完才回显，读超时必须按实际等待时间放宽，否则会误判超时。
        # 注意：socket.makefile() 会把"当时"的超时固化进文件对象，
        # 必须先把超时设好再 makefile，否则放宽的超时不会生效。
        self._maatouch_stream.settimeout(max(2.0, builder.delay / 1000 + 2.0))
        socket_out = self._maatouch_stream.makefile()
        max_trial = 3
        for n in range(3):
            try:
                out = socket_out.readline()
            except socket.timeout as e:
                raise MaaTouchSyncTimeout(str(e))
            out = out.strip()
            # logger.info(out)

            if out == timestamp:
                break
            if out == 'Killed':
                raise MaaTouchNotInstalledError('MaaTouch died, probably because version incompatible')
            if n == max_trial - 1:
                raise MaaTouchSyncTimeout('Too many incorrect sync response')
            time.sleep(0.001)

        # logger.info(f'Delay: {builder.delay}')
        # logger.info(f'Waiting control {time.time() - start}')
        if post_delay:
            self.sleep(builder.DEFAULT_DELAY)
        builder.clear()

    def maatouch_install(self):
        """推送 MaaTouch 二进制文件到设备。"""
        logger.hr('[设备-MaaTouch] 安装')
        self.adb_push(self.config.MAATOUCH_FILEPATH_LOCAL, self.config.MAATOUCH_FILEPATH_REMOTE)

    def maatouch_uninstall(self):
        """移除设备上的 MaaTouch 文件。"""
        logger.hr('[设备-MaaTouch] 卸载')
        self.adb_shell(["rm", self.config.MAATOUCH_FILEPATH_REMOTE])

    @retry
    def click_maatouch(self, x, y):
        """
        通过 MaaTouch 执行点击操作。

        Args:
            x: 点击横坐标。
            y: 点击纵坐标。
        """
        builder = self.maatouch_builder
        builder.down(x, y).commit()
        builder.up().commit()
        builder.send_sync()

    @retry
    def long_click_maatouch(self, x, y, duration=1.0):
        """
        通过 MaaTouch 执行长按操作。

        Args:
            x: 长按横坐标。
            y: 长按纵坐标。
            duration: 长按持续时间（秒）。
        """
        duration = int(duration * 1000)
        builder = self.maatouch_builder
        builder.down(x, y).wait(duration).commit()
        builder.up().commit()
        builder.send_sync()

    @retry
    def swipe_maatouch(self, p1, p2):
        """
        通过 MaaTouch 执行贝塞尔曲线平滑滑动操作。

        Args:
            p1: 滑动起点坐标 (x, y)。
            p2: 滑动终点坐标 (x, y)。
        """
        points = insert_swipe(p0=p1, p3=p2)
        builder = self.maatouch_builder

        builder.down(*points[0]).commit().wait(10)
        builder.send_sync()

        for point in points[1:]:
            builder.move(*point).wait(10)
        builder.commit()
        builder.send_sync()

        builder.up().commit()
        builder.send_sync()

    @retry
    def drag_maatouch(self, p1, p2, point_random=(-10, -10, 10, 10), hold_duration=0.0):
        """
        通过 MaaTouch 执行拖拽操作。

        Args:
            p1: 拖拽起始坐标 (x, y)。
            p2: 拖拽释放坐标 (x, y)。
            point_random: 起始和结束坐标的随机抖动范围 (x_min, y_min, x_max, y_max)。
            hold_duration: 到达终点后的按住停顿时间（秒）。
        """
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        points = insert_swipe(p0=p1, p3=p2, speed=20)
        builder = self.maatouch_builder

        builder.down(*points[0]).commit().wait(10)
        builder.send_sync()

        for point in points[1:]:
            builder.move(*point).commit().wait(10)
        builder.send_sync()

        builder.move(*p2).commit().wait(140)
        builder.move(*p2).commit().wait(140)
        builder.send_sync()

        hold_duration = ensure_time(hold_duration) - 0.28
        hold_ms = int(max(0.0, hold_duration) * 1000)
        if hold_ms > 0:
            builder.move(*p2).commit().wait(hold_ms)
            builder.send_sync()

        builder.up().commit()
        builder.send_sync()

    @retry
    def island_swipe_hold_maatouch(self, p1, p2, hold_time):
        """岛屿行走专用：拖到偏移点后保持 hold_time 毫秒。

        与 drag_maatouch 的差别：
        - 保持时间整段一次下发（sync 读超时已按等待时长放宽），避免多次 sync 期间
          手指仍按在偏移点上导致角色多走；
        - 抬手不等待回显，抬手命令发出即结束，进一步减少多走的时间；
        - 无论中途是否出错，都保证发送抬手命令，否则角色会一直朝该方向走。

        Args:
            p1 (tuple): 摇杆中心。
            p2 (tuple): 偏移点。
            hold_time (int, float): 保持时间，单位毫秒。
        """
        hold_ms = int(hold_time)
        p1 = np.array(p1)
        p2 = np.array(p2)
        points = insert_swipe(p0=p1, p3=p2, speed=20)
        builder = self.maatouch_builder
        try:
            # 按下 + 滑到偏移点后立即发送；保持时间由**客户端**计时，
            # 因为 maatouch 的 sync 命令被插在批次最前面，服务端读到就回显，
            # 用它计时会提前返回（表现为时长被拉长/错位）。
            builder.down(*p1).commit().wait(10)
            for point in points[1:]:
                builder.move(*point).commit().wait(10)
            builder.send()
            self.sleep(max(0, hold_ms) / 1000)
        finally:
            try:
                builder.up().commit()
                builder.send()
            except Exception as error:
                logger.warning(f'[设备-MaaTouch] 岛屿行走抬手失败，尝试 reset: {error}')
                try:
                    self.reset_maatouch()
                except Exception as reset_error:
                    logger.warning(f'[设备-MaaTouch] 岛屿行走 reset 也失败: {reset_error}')

    @retry
    def reset_maatouch(self):
        """重置 MaaTouch 触控状态并释放所有活动触控点。"""
        builder = self.maatouch_builder
        builder.reset().commit()
        builder.send_sync()
