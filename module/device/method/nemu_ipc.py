import ctypes
import json
import os
import sys
import time
from functools import wraps

import cv2
import numpy as np

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.base.timer import Timer
from module.base.utils import ensure_time
from module.config.deep import deep_get
from module.device.env import IS_WINDOWS
from module.device.method.minitouch import insert_swipe, random_rectangle_point
from module.device.method.pool import JobTimeout, WORKER_POOL
from module.device.method.utils import RETRY_TRIES, retry_sleep
from module.device.platform import Platform
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.logger import logger


class NemuIpcIncompatible(Exception):
    pass


class NemuIpcError(Exception):
    pass


class CaptureStd:
    """
    捕获 Python 和 C 库的 stdout 和 stderr。
    参考: https://stackoverflow.com/questions/5081657/how-do-i-prevent-a-c-shared-library-to-print-on-stdout-in-python/17954769

    ```
    with CaptureStd() as capture:
        # 不会实际打印
        print('whatever')
    # 但会捕获到 capture.stdout 中
    print(f'Got stdout: "{capture.stdout}"')
    print(f'Got stderr: "{capture.stderr}"')
    ```
    """

    def __init__(self):
        self.stdout = b''
        self.stderr = b''

    def _redirect_stdout(self, to):
        sys.stdout.close()
        os.dup2(to, self.fdout)
        sys.stdout = os.fdopen(self.fdout, 'w')

    def _redirect_stderr(self, to):
        sys.stderr.close()
        os.dup2(to, self.fderr)
        sys.stderr = os.fdopen(self.fderr, 'w')

    def __enter__(self):
        self.fdout = sys.stdout.fileno()
        self.fderr = sys.stderr.fileno()
        self.reader_out, self.writer_out = os.pipe()
        self.reader_err, self.writer_err = os.pipe()
        self.old_stdout = os.dup(self.fdout)
        self.old_stderr = os.dup(self.fderr)

        file_out = os.fdopen(self.writer_out, 'w')
        file_err = os.fdopen(self.writer_err, 'w')
        self._redirect_stdout(to=file_out.fileno())
        self._redirect_stderr(to=file_err.fileno())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._redirect_stdout(to=self.old_stdout)
        self._redirect_stderr(to=self.old_stderr)
        os.close(self.old_stdout)
        os.close(self.old_stderr)

        self.stdout = self.recvall(self.reader_out)
        self.stderr = self.recvall(self.reader_err)
        os.close(self.reader_out)
        os.close(self.reader_err)

    @staticmethod
    def recvall(reader, length=1024) -> bytes:
        fragments = []
        while 1:
            chunk = os.read(reader, length)
            if chunk:
                fragments.append(chunk)
            else:
                break
        output = b''.join(fragments)
        return output


class CaptureNemuIpc(CaptureStd):
    instance = None

    def is_capturing(self):
        """
        仅在最顶层包装器中捕获，避免嵌套捕获。
        如果已有捕获正在进行，当前实例不做任何操作。
        """
        cls = self.__class__
        return isinstance(cls.instance, cls) and cls.instance != self

    def __enter__(self):
        if self.is_capturing():
            return self

        super().__enter__()
        CaptureNemuIpc.instance = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_capturing():
            return

        CaptureNemuIpc.instance = None
        super().__exit__(exc_type, exc_val, exc_tb)

        self.check_stdout()
        self.check_stderr()

    def check_stdout(self):
        if not self.stdout:
            return
        logger.info(f'NemuIpc stdout: {self.stdout}')

    def check_stderr(self):
        if not self.stderr:
            return
        logger.error(f'NemuIpc stderr: {self.stderr}')

        # 调用了旧版本的 MuMu12
        # 在 3.4.0 上测试
        # b'nemu_capture_display rpc error: 1783\r\n'
        # 在 3.7.3 上测试
        # b'nemu_capture_display rpc error: 1745\r\n'
        if b'error: 1783' in self.stderr or b'error: 1745' in self.stderr:
            raise NemuIpcIncompatible(
                f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version')
        # contact_id 不正确
        # b'nemu_capture_display cannot find rpc connection\r\n'
        if b'cannot find rpc connection' in self.stderr:
            raise NemuIpcError(self.stderr)
        # 模拟器已停止运行
        # b'nemu_capture_display rpc error: 1722\r\n'
        # MuMuVMMSVC.exe 已停止运行
        # b'nemu_capture_display rpc error: 1726\r\n'
        # 暂无已知处理方式
        if b'error: 1722' in self.stderr or b'error: 1726' in self.stderr:
            raise NemuIpcError('Emulator instance is probably dead')


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (NemuIpcImpl):
        """
        init = None
        for _ in range(RETRY_TRIES):
            # 重试时延长超时时间
            if func.__name__ == 'screenshot':
                timeout = retry_sleep(_)
                if timeout > 0:
                    kwargs['timeout'] = timeout
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 不可处理
            except RequestHumanTakeover:
                break
            # 不可处理
            except NemuIpcIncompatible as e:
                logger.error(e)
                break
            # 函数调用超时
            except JobTimeout:
                logger.warning(f'Func {func.__name__}() call timeout, retrying: {_}')

                def init():
                    pass
            # NemuIpcError
            except NemuIpcError as e:
                logger.error(e)

                def init():
                    self.reconnect()
            # 不可处理 - 必须向上抛出以触发模拟器重启
            except EmulatorNotRunningError:
                raise
            # 未知异常，可能是损坏的图像
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        if func.__name__ in ['connect_with_retry', 'screenshot', 'down', 'up']:
            logger.critical(f'重试 {func.__name__}() 失败')
            raise EmulatorNotRunningError

        logger.critical(f'重试 {func.__name__}() 失败')
        raise RequestHumanTakeover

    return retry_wrapper


class NemuIpcImpl:
    def __init__(self, nemu_folder: str, instance_id: int, display_id: int = 0):
        """
        Args:
            nemu_folder: MuMu12 安装路径，例如 E:/ProgramFiles/MuMuPlayer-12.0
            instance_id: 模拟器实例 ID，从 0 开始
            display_id: 如果未启用后台挂机保活，始终为 0
        """
        self.nemu_folder: str = nemu_folder
        self.instance_id: int = instance_id
        self.display_id: int = display_id

        # 尝试从多个路径加载 DLL
        list_dll = [
            # MuMuPlayer12
            os.path.abspath(os.path.join(nemu_folder, './shell/sdk/external_renderer_ipc.dll')),
            # MuMuPlayer12 5.0
            os.path.abspath(os.path.join(nemu_folder, './nx_device/12.0/shell/sdk/external_renderer_ipc.dll')),
        ]
        self.lib = None
        for ipc_dll in list_dll:
            if not os.path.exists(ipc_dll):
                continue
            try:
                self.lib = ctypes.CDLL(ipc_dll)
                break
            except OSError as e:
                logger.error(e)
                logger.error(f'ipc_dll={ipc_dll} exists, but cannot be loaded')
                continue
        if self.lib is None:
            # 未找到
            raise NemuIpcIncompatible(
                f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version. '
                f'None of the following path exists: {list_dll}')
        # 成功
        logger.info(
            f'NemuIpcImpl init, '
            f'nemu_folder={nemu_folder}, '
            f'ipc_dll={ipc_dll}, '
            f'instance_id={instance_id}, '
            f'display_id={display_id}'
        )
        self.connect_id: int = 0
        self.width = 0
        self.height = 0

    def connect(self, on_thread=True):
        if self.connect_id > 0:
            return

        if on_thread:
            connect_id = self.run_func(
                self.lib.nemu_connect,
                self.nemu_folder, self.instance_id
            )
        else:
            connect_id = self.lib.nemu_connect(self.nemu_folder, self.instance_id)
        if connect_id == 0:
            raise NemuIpcError(
                '连接失败，请检查 nemu_folder 是否正确以及模拟器是否正在运行'
            )

        self.connect_id = connect_id
        # logger.info(f'NemuIpc connected: {self.connect_id}')

    @retry
    def connect_with_retry(self, on_thread=True):
        self.connect(on_thread=on_thread)

    def disconnect(self):
        if self.connect_id == 0:
            return

        self.run_func(
            self.lib.nemu_disconnect,
            self.connect_id
        )

        # logger.info(f'NemuIpc disconnected: {self.connect_id}')
        self.connect_id = 0

    def reconnect(self):
        self.disconnect()
        self.connect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    @staticmethod
    def run_func(func, *args, on_thread=True, timeout=0.5):
        """
        Args:
            func: 要调用的同步函数
            *args:
            on_thread: 为 True 时在独立线程上运行 func
            timeout:

        Raises:
            JobTimeout: 函数调用超时时抛出
            NemuIpcIncompatible:
            NemuIpcError
        """
        if on_thread:
            # nemu_ipc 有时会超时，因此在独立线程上运行
            job = WORKER_POOL.start_thread_soon(func, *args)
            result = job.get_or_kill(timeout)
        else:
            result = func(*args)

        err = False
        if func.__name__ == '_screenshot':
            pass
        elif func.__name__ == 'nemu_connect':
            if result == 0:
                err = True
        else:
            if result > 0:
                err = True
        # 获取标准输出中实际的错误信息
        if err:
            logger.warning(f'Failed to call {func.__name__}, result={result}')
            with CaptureNemuIpc():
                func(*args)

        return result

    def get_resolution(self, on_thread=True):
        """
        获取模拟器分辨率，会设置 `self.width` 和 `self.height`。
        """
        if self.connect_id == 0:
            self.connect()

        width_ptr = ctypes.pointer(ctypes.c_int(0))
        height_ptr = ctypes.pointer(ctypes.c_int(0))
        nullptr = ctypes.POINTER(ctypes.c_int)()

        ret = self.run_func(
            self.lib.nemu_capture_display,
            self.connect_id, self.display_id, 0, width_ptr, height_ptr, nullptr,
            on_thread=on_thread
        )
        if ret > 0:
            raise NemuIpcError('nemu_capture_display failed during get_resolution()')
        self.width = width_ptr.contents.value
        self.height = height_ptr.contents.value

    def _screenshot(self):
        if self.connect_id == 0:
            self.connect(on_thread=False)
        self.get_resolution(on_thread=False)

        width_ptr = ctypes.pointer(ctypes.c_int(self.width))
        height_ptr = ctypes.pointer(ctypes.c_int(self.height))
        length = self.width * self.height * 4
        pixels_pointer = ctypes.pointer((ctypes.c_ubyte * length)())

        ret = self.lib.nemu_capture_display(
            self.connect_id, self.display_id, length, width_ptr, height_ptr, pixels_pointer,
        )
        if ret > 0:
            raise NemuIpcError('nemu_capture_display failed during screenshot()')

        # 返回 pixels_pointer 而非 image，避免通过 job 传递图像对象
        return pixels_pointer

    @retry
    def screenshot(self, timeout=0.5):
        """
        Args:
            timeout: 调用 nemu_ipc 的超时时间（秒）。
                会被 `@retry` 动态延长。

        Returns:
            np.ndarray: RGBA 色彩空间的图像数组。
                注意图像是上下颠倒的。
        """
        if self.connect_id == 0:
            self.connect()

        pixels_pointer = self.run_func(self._screenshot, timeout=timeout)

        # image = np.ctypeslib.as_array(pixels_pointer, shape=(self.height, self.width, 4))
        image = np.ctypeslib.as_array(pixels_pointer.contents).reshape((self.height, self.width, 4))
        return image

    def convert_xy(self, x, y):
        """
        将标准 ADB 坐标转换为 Nemu 坐标。
        调用此方法前必须先更新 `self.height`。

        Returns:
            int, int
        """
        x, y = int(x), int(y)
        x, y = self.height - y, x
        return x, y

    @retry
    def down(self, x, y):
        """
        触摸按下，连续的触摸按下会被视为滑动。
        """
        if self.connect_id == 0:
            self.connect()
        if self.height == 0:
            self.get_resolution()

        x, y = self.convert_xy(x, y)

        ret = self.run_func(
            self.lib.nemu_input_event_touch_down,
            self.connect_id, self.display_id, x, y
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_touch_down failed')

    @retry
    def up(self):
        """
        触摸抬起。
        """
        if self.connect_id == 0:
            self.connect()

        ret = self.run_func(
            self.lib.nemu_input_event_touch_up,
            self.connect_id, self.display_id
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_touch_up failed')

    @staticmethod
    def serial_to_id(serial: str):
        """
        从 serial 推断实例 ID。
        例如:
            "127.0.0.1:16384" -> 0
            "127.0.0.1:16416" -> 1
            端口 16414 到 16418 -> 1

        Returns:
            int: instance_id，推断失败时返回 None
        """
        try:
            port = int(serial.split(':')[1])
        except (IndexError, ValueError):
            return None
        index, offset = divmod(port - 16384 + 16, 32)
        offset -= 16
        if 0 <= index < 32 and offset in [-2, -1, 0, 1, 2]:
            return index
        else:
            return None


class NemuIpc(Platform):
    _screenshot_interval = Timer(0.1)

    @cached_property
    def nemu_ipc(self) -> NemuIpcImpl:
        """
        初始化 nemu ipc 实现。
        """
        # 优先使用已有设置
        if self.config.EmulatorInfo_path:
            folder = os.path.abspath(os.path.join(self.config.EmulatorInfo_path, '../../'))
            index = NemuIpcImpl.serial_to_id(self.serial)
            if index is not None:
                try:
                    return NemuIpcImpl(
                        nemu_folder=folder,
                        instance_id=index,
                        display_id=0
                    ).__enter__()
                except (NemuIpcIncompatible, NemuIpcError, JobTimeout) as e:
                    logger.error(e)
                    logger.error('Emulator info incorrect')

        # 搜索模拟器实例
        # 例如 E:\ProgramFiles\MuMuPlayer-12.0\shell\MuMuPlayer.exe
        # 安装路径为 E:\ProgramFiles\MuMuPlayer-12.0
        if self.emulator_instance is None:
            logger.error('无法使用 NemuIpc，因为未找到模拟器实例')
            raise RequestHumanTakeover
        if 'MuMuPlayerGlobal' in self.emulator_instance.path:
            logger.info(f'nemu_ipc 在 MuMuPlayerGlobal 上不可用, {self.emulator_instance.path}')
            raise RequestHumanTakeover
        try:
            impl = NemuIpcImpl(
                nemu_folder=self.emulator_instance.emulator.abspath('../'),
                instance_id=self.emulator_instance.MuMuPlayer12_id,
                display_id=0
            )
            impl.connect_with_retry()
            return impl
        except (NemuIpcIncompatible, NemuIpcError, JobTimeout) as e:
            logger.error(e)
            logger.error('Unable to initialize NemuIpc')
            raise RequestHumanTakeover

    def nemu_ipc_available(self) -> bool:
        if not IS_WINDOWS:
            return False
        if not self.is_mumu_family:
            return False
        if self.nemud_player_version == '':
            # >= 4.0 的版本在 getprop 中没有信息
            # 尝试初始化 nemu_ipc 来做最终检查
            pass
        else:
            # 有版本信息，可能是 MuMu6 或 MuMu12 3.x 版本
            if self.nemud_app_keep_alive == '':
                # 属性为空，可能是 MuMu6 或 MuMu12 < 3.5.6 版本
                return False
        try:
            _ = self.nemu_ipc
        except RequestHumanTakeover:
            return False
        return True

    @staticmethod
    def check_mumu_app_keep_alive_400(file):
        """
        在版本 >= 4.0 时从模拟器配置中检查 app_keep_alive。

        Args:
            file: E:/ProgramFiles/MuMuPlayer-12.0/vms/MuMuPlayer-12.0-1/config/customer_config.json

        Returns:
            bool: 是否成功读取文件
        """
        # 例如 E:\ProgramFiles\MuMuPlayer-12.0\shell\MuMuPlayer.exe
        # 配置路径为 E:\ProgramFiles\MuMuPlayer-12.0\vms\MuMuPlayer-12.0-1\config\customer_config.json
        try:
            with open(file, mode='r', encoding='utf-8') as f:
                s = f.read()
                data = json.loads(s)
        except FileNotFoundError:
            logger.warning(f'Failed to check check_mumu_app_keep_alive, file {file} not exists')
            return False
        value = deep_get(data, keys='customer.app_keptlive', default=None)
        logger.attr('customer.app_keptlive', value)
        if str(value).lower() == 'true':
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('Please turn off "Keep alive in the background" in the settings or MuMuPlayer')
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover
        return True

    def check_mumu_app_keep_alive(self):
        if not self.is_mumu_over_version_400:
            return super().check_mumu_app_keep_alive()

        # 优先使用已有设置
        if self.config.EmulatorInfo_path:
            index = NemuIpcImpl.serial_to_id(self.serial)
            if index is not None:
                file = os.path.abspath(os.path.join(
                    self.config.EmulatorInfo_path, f'../../vms/MuMuPlayer-12.0-{index}/configs/customer_config.json'))
                if self.check_mumu_app_keep_alive_400(file):
                    return True

        # 搜索模拟器实例
        if self.emulator_instance is None:
            logger.warning('检查 check_mumu_app_keep_alive 失败，因为 emulator_instance 为 None')
            return False
        name = self.emulator_instance.name
        file = self.emulator_instance.mumu_vms_config('customer_config.json')
        if self.check_mumu_app_keep_alive_400(file):
            return True

        return False

    def nemu_ipc_release(self):
        if has_cached_property(self, 'nemu_ipc'):
            self.nemu_ipc.disconnect()
        del_cached_property(self, 'nemu_ipc')
        logger.info('nemu_ipc released')

    def screenshot_nemu_ipc(self):
        image = self.nemu_ipc.screenshot()

        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
        cv2.flip(image, 0, dst=image)
        return image

    def click_nemu_ipc(self, x, y):
        down = ensure_time((0.010, 0.020))
        self.nemu_ipc.down(x, y)
        self.sleep(down)
        self.nemu_ipc.up()
        self.sleep(0.050 - down)

    def long_click_nemu_ipc(self, x, y, duration=1.0):
        self.nemu_ipc.down(x, y)
        self.sleep(duration)
        self.nemu_ipc.up()
        self.sleep(0.050)

    def swipe_nemu_ipc(self, p1, p2):
        points = insert_swipe(p0=p1, p3=p2)

        for point in points:
            self.nemu_ipc.down(*point)
            self.sleep(0.010)

        self.nemu_ipc.up()
        self.sleep(0.050)

    def drag_nemu_ipc(self, p1, p2, point_random=(-10, -10, 10, 10)):
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        points = insert_swipe(p0=p1, p3=p2, speed=20)

        for point in points:
            self.nemu_ipc.down(*point)
            self.sleep(0.010)

        self.nemu_ipc.down(*p2)
        self.sleep(0.140)
        self.nemu_ipc.down(*p2)
        self.sleep(0.140)

        self.nemu_ipc.up()
        self.sleep(0.050)
