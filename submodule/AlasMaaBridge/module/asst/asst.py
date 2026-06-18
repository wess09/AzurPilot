import ctypes
import json
import os
import pathlib
import platform
from typing import Union, Optional

from .utils import InstanceOptionType, JSON


class Asst:
    """MAA 核心库的 Python 封装。

    通过 ctypes 调用 MaaCore.dll 提供的 C 接口，实现任务管理和设备控制。
    """

    CallBackType = ctypes.CFUNCTYPE(
        None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
    """回调函数类型。

    Args:
        message: 消息类型，对应 Message 枚举值。
        details: JSON 格式的详细信息字符串。
        arg: 用户自定义参数指针。
    """

    @staticmethod
    def load(path: Union[pathlib.Path, str], incremental_path: Optional[Union[pathlib.Path, str, list]] = None,
             user_dir: Optional[Union[pathlib.Path, str]] = None) -> bool:
        """加载 MAA 核心库及资源文件。

        根据当前平台加载对应的动态库（Windows: MaaCore.dll, macOS: libMaaCore.dylib,
        Linux: libMaaCore.so），并设置环境变量和加载资源。

        Args:
            path: DLL 及资源所在的文件夹路径。
            incremental_path: 增量资源所在的文件夹路径，可以是单个路径或路径列表。
            user_dir: 用户数据（日志、调试图片等）的写入文件夹路径。

        Returns:
            bool: 是否加载成功。
        """

        platform_values = {
            'windows': {
                'libpath': 'MaaCore.dll',
                'environ_var': 'PATH'
            },
            'darwin': {
                'libpath': 'libMaaCore.dylib',
                'environ_var': 'DYLD_LIBRARY_PATH'
            },
            'linux': {
                'libpath': 'libMaaCore.so',
                'environ_var': 'LD_LIBRARY_PATH'
            }
        }

        platform_type = platform.system().lower()
        if platform_type == 'windows':
            lib_import_func = ctypes.WinDLL
        else:
            lib_import_func = ctypes.CDLL

        Asst.__libpath = pathlib.Path(path) / platform_values[platform_type]['libpath']
        try:
            os.environ[platform_values[platform_type]['environ_var']] += os.pathsep + str(path)
        except KeyError:
            os.environ[platform_values[platform_type]['environ_var']] = os.pathsep + str(path)
        Asst.__lib = lib_import_func(str(Asst.__libpath))
        Asst.__set_lib_properties()

        ret: bool = True
        if user_dir:
            ret &= Asst.__lib.AsstSetUserDir(str(user_dir).encode('utf-8'))

        ret &= Asst.__lib.AsstLoadResource(str(path).encode('utf-8'))
        if incremental_path:
            if isinstance(incremental_path, list):
                for i_path in incremental_path:
                    ret &= Asst.__lib.AsstLoadResource(
                        str(i_path).encode('utf-8'))
            else:
                ret &= Asst.__lib.AsstLoadResource(
                    str(incremental_path).encode('utf-8'))

        return ret

    def __init__(self, callback: CallBackType = None, arg=None):
        """创建 MAA 助手实例。

        Args:
            callback: 回调函数，用于接收任务执行过程中的消息通知。
            arg: 传递给回调函数的自定义参数。
        """

        if callback:
            self.__ptr = Asst.__lib.AsstCreateEx(callback, arg)
        else:
            self.__ptr = Asst.__lib.AsstCreate()

    def __del__(self):
        Asst.__lib.AsstDestroy(self.__ptr)
        self.__ptr = None

    def set_instance_option(self, option_type: InstanceOptionType, option_value: str):
        """设置实例的额外配置选项。

        参见 ${MaaAssistantArknights}/src/MaaCore/Assistant.cpp#set_instance_option

        Args:
            option_type: 配置类型，如触控模式、是否暂停下干员等。
            option_value: 配置值。

        Returns:
            bool: 是否设置成功。
        """
        return Asst.__lib.AsstSetInstanceOption(self.__ptr,
                                                int(option_type), option_value.encode('utf-8'))

    def connect(self, adb_path: str, address: str, config: str = 'General'):
        """连接到安卓设备。

        通过 ADB 建立与目标设备的连接，用于后续的任务执行。

        Args:
            adb_path: adb 程序的路径。
            address: 设备的 ADB 地址和端口，如 127.0.0.1:5555。
            config: ADB 配置名称，可参考 resource/config.json。

        Returns:
            bool: 是否连接成功。
        """
        return Asst.__lib.AsstConnect(self.__ptr,
                                      adb_path.encode('utf-8'), address.encode('utf-8'), config.encode('utf-8'))

    TaskId = int

    def append_task(self, type_name: str, params: JSON = {}) -> TaskId:
        """添加一个新任务到任务队列。

        Args:
            type_name: 任务类型名称，请参考 docs/集成文档.md。
            params: 任务参数字典，请参考 docs/集成文档.md。

        Returns:
            TaskId: 任务 ID，可用于 set_task_params 接口动态修改参数。
        """
        return Asst.__lib.AsstAppendTask(self.__ptr, type_name.encode('utf-8'),
                                         json.dumps(params, ensure_ascii=False).encode('utf-8'))

    def set_task_params(self, task_id: TaskId, params: JSON) -> bool:
        """动态修改已添加任务的参数。

        Args:
            task_id: 任务 ID，来自 append_task 的返回值。
            params: 任务参数字典，格式同 append_task。

        Returns:
            bool: 是否修改成功。
        """
        return Asst.__lib.AsstSetTaskParams(self.__ptr, task_id, json.dumps(params, ensure_ascii=False).encode('utf-8'))

    def start(self) -> bool:
        """开始执行任务队列中的任务。

        Returns:
            bool: 是否成功启动。
        """
        return Asst.__lib.AsstStart(self.__ptr)

    def stop(self) -> bool:
        """停止当前执行并清空任务队列。

        Returns:
            bool: 是否成功停止。
        """
        return Asst.__lib.AsstStop(self.__ptr)

    def running(self) -> bool:
        """检查任务是否正在执行中。

        Returns:
            bool: 是否正在运行。
        """
        return Asst.__lib.AsstRunning(self.__ptr)

    @staticmethod
    def log(level: str, message: str) -> None:
        """向 MAA 日志系统写入一条日志。

        Args:
            level: 日志等级标签，如 DEBUG、INFO、WARN、ERROR。
            message: 日志内容。
        """

        Asst.__lib.AsstLog(level.encode('utf-8'), message.encode('utf-8'))

    def get_version(self) -> str:
        """获取当前加载的 MAA 核心库版本号。

        Returns:
            str: 版本号字符串。
        """
        return Asst.__lib.AsstGetVersion().decode('utf-8')

    @staticmethod
    def __set_lib_properties():
        Asst.__lib.AsstSetUserDir.restype = ctypes.c_bool
        Asst.__lib.AsstSetUserDir.argtypes = (
            ctypes.c_char_p,)

        Asst.__lib.AsstLoadResource.restype = ctypes.c_bool
        Asst.__lib.AsstLoadResource.argtypes = (
            ctypes.c_char_p,)

        Asst.__lib.AsstCreate.restype = ctypes.c_void_p
        Asst.__lib.AsstCreate.argtypes = ()

        Asst.__lib.AsstCreateEx.restype = ctypes.c_void_p
        Asst.__lib.AsstCreateEx.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p,)

        Asst.__lib.AsstDestroy.argtypes = (ctypes.c_void_p,)

        Asst.__lib.AsstSetInstanceOption.restype = ctypes.c_bool
        Asst.__lib.AsstSetInstanceOption.argtypes = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p,)

        Asst.__lib.AsstConnect.restype = ctypes.c_bool
        Asst.__lib.AsstConnect.argtypes = (
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,)

        Asst.__lib.AsstAppendTask.restype = ctypes.c_int
        Asst.__lib.AsstAppendTask.argtypes = (
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)

        Asst.__lib.AsstSetTaskParams.restype = ctypes.c_bool
        Asst.__lib.AsstSetTaskParams.argtypes = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)

        Asst.__lib.AsstStart.restype = ctypes.c_bool
        Asst.__lib.AsstStart.argtypes = (ctypes.c_void_p,)

        Asst.__lib.AsstStop.restype = ctypes.c_bool
        Asst.__lib.AsstStop.argtypes = (ctypes.c_void_p,)

        Asst.__lib.AsstRunning.restype = ctypes.c_bool
        Asst.__lib.AsstRunning.argtypes = (ctypes.c_void_p,)

        Asst.__lib.AsstGetVersion.restype = ctypes.c_char_p

        Asst.__lib.AsstLog.restype = None
        Asst.__lib.AsstLog.argtypes = (
            ctypes.c_char_p, ctypes.c_char_p)
