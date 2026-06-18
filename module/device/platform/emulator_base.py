import os
import re
import typing as t
from dataclasses import dataclass

from module.device.platform.utils import cached_property, iter_folder


def abspath(path):
    return os.path.abspath(path).replace('\\', '/')


def get_serial_pair(serial):
    """
    根据 serial 推导对应的 serial 对。

    Args:
        serial (str): 设备序列号

    Returns:
        tuple: `127.0.0.1:5555+{X}` 和 `emulator-5554+{X}`，其中 0 <= X <= 32
    """
    if serial.startswith('127.0.0.1:'):
        try:
            port = int(serial[10:])
            if 5555 <= port <= 5555 + 32:
                return f'127.0.0.1:{port}', f'emulator-{port - 1}'
        except (ValueError, IndexError):
            pass
    if serial.startswith('emulator-'):
        try:
            port = int(serial[9:])
            if 5554 <= port <= 5554 + 32:
                return f'127.0.0.1:{port + 1}', f'emulator-{port}'
        except (ValueError, IndexError):
            pass

    return None, None


def remove_duplicated_path(paths):
    """
    去除重复路径（大小写不敏感），保留第一次出现的原始大小写形式。

    Args:
        paths (list[str]): 路径列表

    Returns:
        list[str]: 去重后的路径列表
    """
    paths = sorted(set(paths))
    dic = {}
    for path in paths:
        dic.setdefault(path.lower(), path)
    return list(dic.values())


@dataclass
class EmulatorInstanceBase:
    """模拟器实例的基类数据结构。"""
    # ADB 连接用的序列号
    serial: str
    # 模拟器实例名称，用于启停模拟器
    name: str
    # 模拟器 .exe 文件路径
    path: str
    # 特定模拟器的附加字段（可选）
    index: int = 0
    state: str = ''

    def __str__(self):
        return f'{self.type}(serial="{self.serial}", name="{self.name}", path="{self.path}")'

    @cached_property
    def type(self) -> str:
        """
        Returns:
            str: 模拟器类型，如 Emulator.NoxPlayer
        """
        return self.emulator.type

    @cached_property
    def emulator(self):
        """
        Returns:
            EmulatorBase: 当前实例对应的模拟器对象
        """
        return EmulatorBase(self.path)

    def __eq__(self, other):
        if isinstance(other, str) and self.type == other:
            return True
        if isinstance(other, list) and self.type in other:
            return True
        if isinstance(other, EmulatorInstanceBase):
            return super().__eq__(other) and self.type == other.type
        return super().__eq__(other)

    def __hash__(self):
        return hash(str(self))

    def __bool__(self):
        return True

    @cached_property
    def MuMuPlayer12_id(self):
        """
        将 MuMu 12 实例名称转换为实例 ID。
        示例名称:
            MuMuPlayer-12.0-3
            YXArkNights-12.0-1

        Returns:
            int: 实例 ID，如果不是 MuMu 12 实例则返回 None
        """
        res = re.search(r'MuMuPlayer(?:Global)?-12.0-(\d+)', self.name)
        if res:
            return int(res.group(1))
        res = re.search(r'YXArkNights-12.0-(\d+)', self.name)
        if res:
            return int(res.group(1))

        return None

    def mumu_vms_config(self, file):
        """
        获取 MuMu 虚拟机配置文件的绝对路径。

        Args:
            file (str): 配置文件名，如 customer_config.json

        Returns:
            str: 配置文件的绝对路径
        """
        return self.emulator.abspath(f'../vms/{self.name}/configs/{file}')

    @cached_property
    def LDPlayer_id(self):
        """
        将雷电模拟器实例名称转换为实例 ID。
        示例名称:
            leidian0
            leidian1

        Returns:
            int: 实例 ID，如果不是雷电模拟器实例则返回 None
        """
        res = re.search(r'leidian(\d+)', self.name)
        if res:
            return int(res.group(1))

        return None


class EmulatorBase:
    """模拟器基类，定义模拟器类型常量和通用接口。"""
    # 此处的值必须与 argument.yaml 中 EmulatorInfo.Emulator.option 保持一致
    NoxPlayer = 'NoxPlayer'
    NoxPlayer64 = 'NoxPlayer64'
    NoxPlayerFamily = [NoxPlayer, NoxPlayer64]
    BlueStacks4 = 'BlueStacks4'
    BlueStacks5 = 'BlueStacks5'
    BlueStacks4HyperV = 'BlueStacks4HyperV'
    BlueStacks5HyperV = 'BlueStacks5HyperV'
    BlueStacksFamily = [BlueStacks4, BlueStacks5]
    LDPlayer3 = 'LDPlayer3'
    LDPlayer4 = 'LDPlayer4'
    LDPlayer9 = 'LDPlayer9'
    LDPlayer14 = 'LDPlayer14'
    LDPlayerFamily = [LDPlayer3, LDPlayer4, LDPlayer9, LDPlayer14]
    MuMuPlayer = 'MuMuPlayer'
    MuMuPlayerX = 'MuMuPlayerX'
    MuMuPlayer12 = 'MuMuPlayer12'
    MuMuPlayerFamily = [MuMuPlayer, MuMuPlayerX, MuMuPlayer12]
    MEmuPlayer = 'MEmuPlayer'
    # Mac 模拟器
    BlueStacksAir = 'BlueStacksAir'
    MuMuPro = 'MuMuPro'
    MacEmulatorFamily = [BlueStacksAir, MuMuPro]
    SSH = 'SSH'

    @classmethod
    def path_to_type(cls, path: str) -> str:
        """
        根据 .exe 文件路径判断模拟器类型。

        Args:
            path: .exe 文件路径

        Returns:
            str: 模拟器类型，如 Emulator.NoxPlayer；如果不是模拟器则返回空字符串
        """
        return ''

    def iter_instances(self) -> t.Iterable[EmulatorInstanceBase]:
        """
        遍历当前模拟器中发现的所有实例。

        Yields:
            EmulatorInstanceBase: 模拟器实例
        """
        pass

    def iter_adb_binaries(self) -> t.Iterable[str]:
        """
        遍历当前模拟器中找到的 adb 二进制文件路径。

        Yields:
            str: adb 二进制文件的绝对路径
        """
        pass

    def __init__(self, path):
        # .exe 文件路径
        self.path = path.replace('\\', '/')
        # 模拟器安装目录
        self.dir = os.path.dirname(path)
        # str: 模拟器类型，如果不是模拟器则为空字符串
        self.type = self.__class__.path_to_type(path)

    def __eq__(self, other):
        if isinstance(other, str) and self.type == other:
            return True
        if isinstance(other, list) and self.type in other:
            return True
        return super().__eq__(other)

    def __str__(self):
        return f'{self.type}(path="{self.path}")'

    __repr__ = __str__

    def __hash__(self):
        return hash(self.path)

    def __bool__(self):
        return True

    def abspath(self, path, folder=None):
        if folder is None:
            folder = self.dir
        return abspath(os.path.join(folder, path))

    @classmethod
    def is_emulator(cls, path: str) -> bool:
        """
        判断给定路径是否为模拟器。

        Args:
            path: .exe 文件路径

        Returns:
            bool: 是否为模拟器
        """
        return bool(cls.path_to_type(path))

    def list_folder(self, folder, is_dir=False, ext=None):
        """
        安全地列出文件夹中的文件。

        Args:
            folder: 文件夹路径（相对于模拟器目录）
            is_dir: 是否只列目录
            ext: 文件扩展名过滤

        Returns:
            list[str]: 文件路径列表
        """
        folder = self.abspath(folder)
        return list(iter_folder(folder, is_dir=is_dir, ext=ext))


class EmulatorManagerBase:
    """模拟器管理器基类，提供模拟器发现和枚举的通用接口。"""

    @staticmethod
    def iter_running_emulator():
        """
        遍历正在运行的模拟器可执行文件路径。

        Yields:
            str: 模拟器可执行文件路径，可能包含重复值
        """
        return

    @cached_property
    def all_emulators(self) -> t.List[EmulatorBase]:
        """
        获取当前计算机上安装的所有模拟器。

        Returns:
            list[EmulatorBase]: 模拟器列表
        """
        return []

    @cached_property
    def all_emulator_instances(self) -> t.List[EmulatorInstanceBase]:
        """
        获取当前计算机上安装的所有模拟器实例。

        Returns:
            list[EmulatorInstanceBase]: 模拟器实例列表
        """
        return []

    @cached_property
    def all_emulator_serials(self) -> t.List[str]:
        """
        获取当前计算机上所有可能的设备序列号。

        Returns:
            list[str]: 序列号列表
        """
        out = []
        for emulator in self.all_emulator_instances:
            out.append(emulator.serial)
            # 同时添加 `emulator-5554` 格式的序列号
            port_serial, emu_serial = get_serial_pair(emulator.serial)
            if emu_serial:
                out.append(emu_serial)
        return out

    @cached_property
    def all_adb_binaries(self) -> t.List[str]:
        """
        获取当前计算机上所有模拟器的 adb 二进制文件路径。

        Returns:
            list[str]: adb 二进制文件路径列表
        """
        out = []
        for emulator in self.all_emulators:
            for exe in emulator.iter_adb_binaries():
                out.append(exe)
        return out
