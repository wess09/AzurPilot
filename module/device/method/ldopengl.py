"""雷电模拟器 OpenGL 截图后端。通过 LDPlayer 的原生 OpenGL 接口
直接读取渲染缓冲区，实现低延迟高质量截图。"""

import ctypes
import os
import subprocess
from dataclasses import dataclass
from functools import partial

import cv2
import numpy as np

from module.base.decorator import cached_property
from module.device.env import IS_WINDOWS
from module.device.method.retry import retry_backend, recover_unknown, retry_without_recovery
from module.device.method.utils import get_serial_pair
from module.device.platform import Platform
from module.exception import RequestHumanTakeover
from module.logger import logger


class LDOpenGLIncompatible(Exception):
    pass


class LDOpenGLError(Exception):
    pass


def bytes_to_str(b: bytes) -> str:
    for encoding in ['utf-8', 'gbk']:
        try:
            return b.decode(encoding)
        except UnicodeDecodeError:
            pass
    return str(b)


@dataclass
class DataLDPlayerInfo:
    # 模拟器实例索引，从 0 开始
    index: int
    # 实例名称
    name: str
    # 顶层窗口句柄
    topWnd: int
    # 绑定窗口句柄
    bndWnd: int
    # 实例是否正在运行，1 表示是，0 表示否
    sysboot: int
    # 实例进程的 PID，未运行时为 -1
    playerpid: int
    # vbox 进程的 PID，未运行时为 -1
    vboxpid: int
    # 分辨率
    width: int
    height: int
    dpi: int

    def __post_init__(self):
        self.index = int(self.index)
        self.name = bytes_to_str(self.name)
        self.topWnd = int(self.topWnd)
        self.bndWnd = int(self.bndWnd)
        self.sysboot = int(self.sysboot)
        self.playerpid = int(self.playerpid)
        self.vboxpid = int(self.vboxpid)
        self.width = int(self.width)
        self.height = int(self.height)
        self.dpi = int(self.dpi)


class LDConsole:
    def __init__(self, ld_folder: str):
        """
        Args:
            ld_folder: 雷电模拟器安装路径，例如 E:/ProgramFiles/LDPlayer9，
                该目录下应包含 `ldconsole.exe`。
        """
        self.ld_console = os.path.abspath(os.path.join(ld_folder, './ldconsole.exe'))

    def subprocess_run(self, cmd, timeout=10):
        """
        Args:
            cmd (list):
            timeout (int):

        Returns:
            bytes:
        """
        cmd = [self.ld_console] + cmd
        logger.info(f'执行: {cmd}')

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
        except FileNotFoundError as e:
            logger.warning(f'调用时警告 {cmd}, {str(e)}')
            raise LDOpenGLIncompatible(f'ld_folder does not have ldconsole.exe')
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.warning(f'调用超时 {cmd}, stdout={stdout}, stderr={stderr}')
        return stdout

    def list2(self):
        """
        > ldconsole.exe list2
        0,雷电模拟器,28053900,42935798,1,59776,36816,1280,720,240
        1,雷电模拟器-1,0,0,0,-1,-1,1280,720,240

        Returns:
            list[DataLDPlayerInfo]:
        """
        out = []
        data = self.subprocess_run(['list2'])
        for row in data.strip().split(b'\n'):
            row = row.strip()
            if not row:
                continue
            info = row.split(b',')
            # 检查字段数
            if len(info) != 10:
                logger.warning(f'雷电模拟器信息不足10部分: "{row}"')
                continue
            # 构建信息
            try:
                info = DataLDPlayerInfo(*info)
            except Exception as e:
                logger.warning(f'无法构建雷电模拟器信息 "{row}", {e}')
            out.append(info)
        return out


class IScreenShotClass:
    def __init__(self, ptr):
        self.ptr = ptr

        # 在类中定义，因为 ctypes.WINFUNCTYPE 仅在 Windows 上可用
        cap_type = ctypes.WINFUNCTYPE(ctypes.c_void_p)
        release_type = ctypes.WINFUNCTYPE(None)
        self.class_cap = cap_type(1, "IScreenShotClass_Cap")
        # 保持引用计数，防止 __del__ 时 IScreenShotClass_Cap 为空
        self.class_release = release_type(2, "IScreenShotClass_Release")

    def cap(self):
        return self.class_cap(self.ptr)

    def __del__(self):
        self.class_release(self.ptr)


def _retry_recover(self, error, trial):
    if isinstance(error, LDOpenGLIncompatible):
        logger.error(error)
        return None
    if isinstance(error, LDOpenGLError):
        logger.error(error)
        return retry_without_recovery
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-ldopengl')


class LDOpenGLImpl:
    def __init__(self, ld_folder: str, instance_id: int):
        """
        Args:
            ld_folder: 雷电模拟器安装路径，例如 E:/ProgramFiles/LDPlayer9
            instance_id: 模拟器实例 ID，从 0 开始
        """
        ldopengl_dll = os.path.abspath(os.path.join(ld_folder, './ldopengl64.dll'))
        logger.info(
            f'[设备-ldopengl] LDOpenGL init, '
            f'ld_folder={ld_folder}, '
            f'ldopengl_dll={ldopengl_dll}, '
            f'instance_id={instance_id}'
        )
        # 加载 DLL
        try:
            self.lib = ctypes.WinDLL(ldopengl_dll)
        except OSError as e:
            logger.error(e)
            if not os.path.exists(ldopengl_dll):
                raise LDOpenGLIncompatible(
                    f'ldopengl_dll={ldopengl_dll} does not exist, '
                    f'ldopengl requires LDPlayer >= 9.0.78, please check your version'
                )
            else:
                raise LDOpenGLIncompatible(
                    f'ldopengl_dll={ldopengl_dll} exist, '
                    f'but cannot be loaded'
                )
        # 加载 DLL 后获取信息，这样 DLL 是否存在可作为版本检查
        self.console = LDConsole(ld_folder)
        self.info = self.get_player_info_by_index(instance_id)

        self.lib.CreateScreenShotInstance.restype = ctypes.c_void_p

        # 获取截图实例
        instance_ptr = ctypes.c_void_p(self.lib.CreateScreenShotInstance(instance_id, self.info.playerpid))
        self.screenshot_instance = IScreenShotClass(instance_ptr)

    def get_player_info_by_index(self, instance_id: int):
        """
        Args:
            instance_id:

        Returns:
            DataLDPlayerInfo:

        Raises:
            LDOpenGLError:
        """
        for info in self.console.list2():
            if info.index == instance_id:
                logger.info(f'[设备-ldopengl] 匹配雷电模拟器实例: {info}')
                if not info.sysboot:
                    raise LDOpenGLError('尝试连接雷电模拟器实例，但模拟器未运行')
                return info
        raise LDOpenGLError(f'No LDPlayer instance with index {instance_id}')

    @retry
    def screenshot(self):
        """
        Returns:
            np.ndarray: BGR 色彩空间的图像数组。
                注意图像是上下颠倒的。
        """
        width, height = self.info.width, self.info.height

        img_ptr = self.screenshot_instance.cap()
        # ValueError: 空指针访问
        if img_ptr is None:
            raise LDOpenGLError('图像指针为空')

        img = ctypes.cast(img_ptr, ctypes.POINTER(ctypes.c_ubyte * (height * width * 3))).contents

        image = np.ctypeslib.as_array(img).reshape((height, width, 3))
        return image

    @staticmethod
    def serial_to_id(serial: str):
        """
        从 serial 推断实例 ID。
        例如:
            "127.0.0.1:5555" -> 0
            "127.0.0.1:5557" -> 1
            "emulator-5554" -> 0

        Returns:
            int: instance_id，推断失败时返回 None
        """
        serial, _ = get_serial_pair(serial)
        if serial is None:
            return None
        try:
            port = int(serial.split(':')[1])
        except (IndexError, ValueError):
            return None
        if 5555 <= port <= 5555 + 32:
            return int((port - 5555) // 2)
        return None


class LDOpenGL(Platform):
    @cached_property
    def ldopengl(self):
        """
        初始化 ldopengl 实现。
        """
        # 优先使用已有设置
        if self.config.EmulatorInfo_path:
            folder = os.path.abspath(os.path.join(self.config.EmulatorInfo_path, '../'))
            index = LDOpenGLImpl.serial_to_id(self.serial)
            if index is not None:
                try:
                    return LDOpenGLImpl(
                        ld_folder=folder,
                        instance_id=index,
                    )
                except (LDOpenGLIncompatible, LDOpenGLError) as e:
                    logger.error(e)
                    logger.error('[设备-ldopengl] 模拟器信息不正确')

        # 搜索模拟器实例
        # 例如 E:/ProgramFiles/LDPlayer9/dnplayer.exe
        # 安装路径为 E:/ProgramFiles/LDPlayer9
        if self.emulator_instance is None:
            logger.error('[设备-ldopengl] 无法使用 LDOpenGL，因为未找到模拟器实例')
            raise RequestHumanTakeover
        try:
            return LDOpenGLImpl(
                ld_folder=self.emulator_instance.emulator.abspath('./'),
                instance_id=self.emulator_instance.LDPlayer_id,
            )
        except (LDOpenGLIncompatible, LDOpenGLError) as e:
            logger.error(e)
            logger.error('[设备-ldopengl] 无法初始化 LDOpenGL')
            raise RequestHumanTakeover

    def ldopengl_available(self) -> bool:
        if not IS_WINDOWS:
            return False
        if not self.is_ldplayer_bluestacks_family:
            return False
        logger.attr('模拟器信息', self.config.EmulatorInfo_Emulator)
        if self.config.EmulatorInfo_Emulator not in ['LDPlayer9', 'LDPlayer14']:
            return False

        try:
            _ = self.ldopengl
        except RequestHumanTakeover:
            return False
        return True

    def screenshot_ldopengl(self):
        image = self.ldopengl.screenshot()

        # 指针数据的像素排列顺序不同（y 轴正方向向上），需要先垂直翻转
        image = cv2.flip(image, 0)

        # 方向处理已统一在screenshot.py的_handle_orientated_image()方法中处理，避免重复旋转

        # 将色彩空间从 BGR 转换为 RGB
        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=image)
        return image
