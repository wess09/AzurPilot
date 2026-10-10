"""可在按住期间穿插截图与识别的连续触控会话。"""

import math
import threading
from time import monotonic

from module.exception import ScriptError
from module.logger import logger


LIVE_DRAG_METHODS = ('minitouch', 'MaaTouch', 'uiautomator2', 'scrcpy', 'nemu_ipc')


class LiveDrag:
    """调用方逐帧移动触点；离开上下文时释放，绝不回退为点击。"""

    def __init__(self, device, name):
        """初始化持续触控会话及其线程控制状态。"""
        self.device = device
        self.name = name
        self.method = device.config.Emulator_ControlMethod
        if self.method not in LIVE_DRAG_METHODS:
            raise ScriptError(f'{self.method} 不支持持续按住期间的截图反馈，请使用 MaaTouch 等控制方式')
        self.active = False
        self.point = None
        self._motion = None
        self._motion_stop = threading.Event()
        self._motion_wake = threading.Event()
        self._motion_lock = threading.Lock()
        self._destination = None
        self._speed = 0
        self._motion_error = None

    def __enter__(self):
        """进入触控会话并准备释放资源的上下文。"""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """退出会话时确保正在按住的触点被释放。"""
        try:
            self.up()
        except Exception as release_error:
            if exc_type is None:
                raise
            # 保留导致中断的原异常；释放失败也必须留下可诊断信息。
            logger.error(f'[设备-控制] 连续拖拽释放失败: {release_error}')

    def _send(self, operation, point):
        """通过所选触控后端提交当前触点操作。"""
        device = self.device
        if self.method in ('minitouch', 'MaaTouch'):
            builder = device.minitouch_builder if self.method == 'minitouch' else device.maatouch_builder
            if operation == 'up':
                builder.up().commit()
            else:
                getattr(builder, operation)(*point).commit()
            if self.method == 'MaaTouch':
                builder.send_sync(post_delay=False)
            else:
                builder.send(post_delay=False)
        elif self.method == 'uiautomator2':
            getattr(device.u2.touch, operation)(*point)
        elif self.method == 'nemu_ipc':
            if operation == 'up':
                device.nemu_ipc.up()
            else:
                device.nemu_ipc.down(*point)
        else:
            from module.device.method.scrcpy import const
            device.scrcpy_ensure_running()
            action = {'down': const.ACTION_DOWN, 'move': const.ACTION_MOVE, 'up': const.ACTION_UP}[operation]
            # 截图也使用这把锁，只锁单次发送，不能跨整个拖动会话持有。
            with device._scrcpy_control_socket_lock:
                device._scrcpy_control.touch(*point, action)

    def down(self, point):
        """按下并保持指定坐标上的触点。"""
        if self.active:
            raise ScriptError('连续拖拽已有活动触点')
        self.device.handle_control_check(self.name)
        self.point = tuple(map(int, point))
        self.active = True
        logger.info(f'[设备-控制] 连续拖拽按下 {self.point} @ {self.name}')
        self._send('down', self.point)

    def move(self, point):
        """将保持中的触点移动到目标坐标。"""
        if not self.active:
            raise ScriptError('连续拖拽尚未按下')
        self.hold()
        self.point = tuple(map(int, point))
        self._send('move', self.point)

    def glide(self, point, speed):
        """后台按单像素小步连续移动，主线程同时截图；速度单位为像素/秒。"""
        self.check_error()
        if not self.active or speed <= 0:
            raise ScriptError('平滑拖动需要活动触点和正速度')
        with self._motion_lock:
            self._destination = tuple(map(int, point))
            self._speed = float(speed)
        if self._motion is None:
            self._motion_stop.clear()
            self._motion = threading.Thread(target=self._glide_worker, daemon=True, name='live-drag-motion')
            self._motion.start()
        self._motion_wake.set()

    def _glide_worker(self):
        """在后台以受控的小步长持续移动触点。"""
        try:
            while not self._motion_stop.is_set():
                with self._motion_lock:
                    destination, speed, point = self._destination, self._speed, self.point
                if destination is None or point == destination:
                    self._motion_wake.wait()
                    self._motion_wake.clear()
                    continue
                started = monotonic()
                following = tuple(value + (1 if goal > value else -1 if goal < value else 0)
                                  for value, goal in zip(point, destination))
                # 每次最多改变一个像素，不用截图帧率作为触点移动的帧率。
                self.point = following
                self._send('move', following)
                duration = math.dist(point, following) / speed
                self._motion_stop.wait(max(.001, duration - (monotonic() - started)))
        except BaseException as exc:
            self._motion_error = exc

    def check_error(self):
        """把后台发送错误交回游戏线程，仍由上下文负责释放触点。"""
        if self._motion_error is not None:
            error, self._motion_error = self._motion_error, None
            raise error

    def _stop_motion(self):
        """停止正在执行的连续触点移动。"""
        if self._motion is not None:
            self._motion_stop.set()
            self._motion_wake.set()
            self._motion.join(timeout=5)
            if self._motion.is_alive():
                raise ScriptError('平滑触控发送未结束，无法继续操作设备')
            self._motion = None
            self._destination = None

    def hold(self):
        """停止移动并保持按下，随后可重新设定平滑目标或精调。"""
        self._stop_motion()
        self.check_error()

    def up(self):
        """释放触点并完成当前拖动会话。"""
        if self.active:
            self._stop_motion()
            self._send('up', self.point)
            self.active = False
            logger.info(f'[设备-控制] 连续拖拽释放 {self.point} @ {self.name}')
            self.check_error()
