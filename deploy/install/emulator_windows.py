import os
import re
import typing as t
import winreg
from dataclasses import dataclass

from module.base.decorator import cached_property
from module.config.utils import iter_folder


@dataclass
class RegValue:
    name: str
    value: str
    typ: int


def list_reg(reg) -> t.List[RegValue]:
    """列出注册表键下的所有值。"""
    rows = []
    index = 0
    try:
        while 1:
            value = RegValue(*winreg.EnumValue(reg, index))
            index += 1
            rows.append(value)
    except OSError:
        pass
    return rows


def list_key(reg) -> t.List[RegValue]:
    """列出注册表键下的所有子键。"""
    rows = []
    index = 0
    try:
        while 1:
            value = winreg.EnumKey(reg, index)
            index += 1
            rows.append(value)
    except OSError:
        pass
    return rows


def abspath(path):
    return os.path.abspath(path).replace('\\', '/')


@dataclass
class EmulatorInstance:
    # ADB 连接序列号
    serial: str
    # 模拟器实例名称，用于启动/停止模拟器
    name: str
    # 模拟器 .exe 文件路径
    path: str

    def __str__(self):
        return f'{self.emulator}(serial="{self.serial}", name="{self.name}", path="{self.path}")'

    @cached_property
    def emulator(self) -> str:
        """获取模拟器类型。

        Returns:
            str: 模拟器类型，如 Emulator.NoxPlayer。
        """
        return Emulator.path_to_emulator(self.path)

    @cached_property
    def start_command(self) -> t.List[str]:
        """获取模拟器启动命令。"""
        if self.emulator in [Emulator.NoxPlayer, Emulator.NoxPlayer64]:
            # Nox.exe -clone:Nox64_7
            return [self.path, f'-clone:{self.name}']
        return []

    @cached_property
    def quit_command(self) -> t.List[str]:
        """获取模拟器退出命令。"""
        if self.emulator in [Emulator.NoxPlayer, Emulator.NoxPlayer64]:
            # Nox.exe -clone:Nox64_7 -quit
            return [self.path, f'-clone:{self.name}', '-quit']
        return []


class Emulator:
    NoxPlayer = 'NoxPlayer'
    NoxPlayer64 = 'NoxPlayer64'
    BlueStacks4 = 'BlueStacks4'
    BlueStacks5 = 'BlueStacks5'
    LDPlayer3 = 'LDPlayer3'
    LDPlayer4 = 'LDPlayer4'
    LDPlayer9 = 'LDPlayer9'
    MumuAppPlayer = 'MumuAppPlayer'
    MemuPlayer = 'MemuPlayer'

    @classmethod
    def path_to_emulator(cls, path: str) -> str:
        """根据可执行文件路径判断模拟器类型。

        Args:
            path: .exe 文件路径。

        Returns:
            str: 模拟器类型，如 Emulator.NoxPlayer，无法识别时返回空字符串。
        """
        folder, exe = os.path.split(path)
        folder, dir1 = os.path.split(folder)
        folder, dir2 = os.path.split(folder)
        if exe == 'Nox.exe':
            if dir2 == 'Nox':
                return cls.NoxPlayer
            elif dir2 == 'Nox64':
                return cls.NoxPlayer64
            else:
                return cls.NoxPlayer
        if exe == 'Bluestacks.exe':
            return cls.BlueStacks4
        if exe == 'HD-Player.exe':
            return cls.BlueStacks5
        if exe == 'dnplayer.exe':
            if dir1 == 'LDPlayer':
                return cls.LDPlayer3
            elif dir1 == 'LDPlayer4':
                return cls.LDPlayer4
            elif dir1 == 'LDPlayer9':
                return cls.LDPlayer9
            else:
                return cls.LDPlayer3
        if exe == 'NemuPlayer.exe':
            return cls.MumuAppPlayer
        if exe == 'MEmu.exe':
            return cls.MemuPlayer

        return ''

    @classmethod
    def is_emulator(cls, path: str) -> bool:
        return bool(cls.path_to_emulator(path))

    def __init__(self, path):
        self.path = path.replace('\\', '/')

        self.dir = os.path.dirname(path)
        self.emu = Emulator.path_to_emulator(path)

    def __str__(self):
        return f'{self.emu}(path="{self.path}")'

    __repr__ = __str__

    def __hash__(self):
        return hash(self.path)

    def abspath(self, path, folder=None):
        if folder is None:
            folder = self.dir
        return abspath(os.path.join(folder, path))

    @staticmethod
    def vbox_file_to_serial(file: str) -> str:
        """从 vbox 虚拟机配置文件中解析 ADB 端口。

        Args:
            file: vbox 文件路径。

        Returns:
            str: ADB 序列号，如 '127.0.0.1:5555'，未找到时返回空字符串。
        """
        regex = re.compile('<*?hostport="(.*?)".*?guestport="5555"/>')
        with open(file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f.readlines():
                # <Forwarding name="port2" proto="1" hostip="127.0.0.1" hostport="62026" guestport="5555"/>
                res = regex.search(line)
                if res:
                    return f'127.0.0.1:{res.group(1)}'
        return ''

    def iter_instances(self):
        """遍历模拟器中的所有实例。

        Yields:
            EmulatorInstance: 找到的模拟器实例。
        """
        if self.emu in [Emulator.NoxPlayer, Emulator.NoxPlayer64]:
            # 夜神模拟器：./BignoxVMS/{name}/{name}.vbox
            for folder in iter_folder(self.abspath('./BignoxVMS'), is_dir=True):
                for file in iter_folder(folder, ext='.vbox'):
                    serial = self.vbox_file_to_serial(file)
                    if serial:
                        yield EmulatorInstance(
                            serial=serial,
                            name=os.path.basename(folder),
                            path=self.path,
                        )
        elif self.emu == Emulator.BlueStacks5:
            # 获取 BlueStacks 数据存储目录 UserDefinedDir
            folder = None
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt") as reg:
                    folder = winreg.QueryValueEx(reg, 'UserDefinedDir')[0]
            except FileNotFoundError:
                pass
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt_cn") as reg:
                    folder = winreg.QueryValueEx(reg, 'UserDefinedDir')[0]
            except FileNotFoundError:
                pass
            if not folder:
                return
            # 读取 bluestacks.conf 配置文件
            with open(self.abspath('./bluestacks.conf', folder), encoding='utf-8') as f:
                content = f.read()
            # 配置格式：bst.instance.Nougat64.adb_port="5555"
            emulators = re.findall(r'bst.instance.(\w+).status.adb_port="(\d+)"', content)
            for emulator in emulators:
                yield EmulatorInstance(
                    serial=f'127.0.0.1:{emulator[1]}',
                    name=emulator[0],
                    path=self.path,
                )
        elif self.emu in [Emulator.LDPlayer3, Emulator.LDPlayer4, Emulator.LDPlayer9]:
            # 雷电模拟器：./vms/leidian0
            try:
                folders = list(iter_folder(self.abspath('./vms'), is_dir=True))
            except FileNotFoundError:
                return
            regex = re.compile(r'^leidian(\d+)$')
            for folder in folders:
                folder = os.path.basename(folder)
                res = regex.match(folder)
                if not res:
                    continue
                # 雷电模拟器没有 .vbox 端口转发配置，端口自动递增：5555, 5557, 5559, ...
                port = int(res.group(1)) * 2 + 5555
                yield EmulatorInstance(
                    serial=f'127.0.0.1:{port}',
                    name=folder,
                    path=self.path
                )
        elif self.emu == Emulator.MumuAppPlayer:
            # MuMu 模拟器没有多开功能，固定端口 7555
            yield EmulatorInstance(
                serial='127.0.0.1:7555',
                name='',
                path=self.path,
            )
        elif self.emu == Emulator.MemuPlayer:
            # 逍遥模拟器：./MemuHyperv VMs/{name}/{name}.memu
            for folder in iter_folder(self.abspath('./MemuHyperv VMs'), is_dir=True):
                for file in iter_folder(folder, ext='.memu'):
                    serial = self.vbox_file_to_serial(file)
                    if serial:
                        yield EmulatorInstance(
                            serial=serial,
                            name=os.path.basename(folder),
                            path=self.path,
                        )


class EmulatorManager:
    @staticmethod
    def get_install_dir_from_reg(path, key):
        """从注册表获取模拟器安装目录。

        Args:
            path (str): 注册表路径，如 'SOFTWARE\\leidian\\ldplayer'。
            key (str): 注册表键名，如 'InstallDir'。

        Returns:
            str: 安装目录路径，未找到时返回 None。
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as reg:
                root = winreg.QueryValueEx(reg, key)[0]
                return root
        except FileNotFoundError:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as reg:
                root = winreg.QueryValueEx(reg, key)[0]
                return root
        except FileNotFoundError:
            pass

        return None

    @staticmethod
    def iter_uninstall_registry():
        """遍历注册表中已知模拟器的卸载程序路径。

        Yields:
            str: 卸载程序的文件路径。
        """
        known_uninstall_registry_path = [
            r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
            r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
        ]
        known_emulator_registry_name = [
            'Nox',
            'Nox64',
            'BlueStacks',
            'BlueStacks_nxt',
            'BlueStacks_cn',
            'BlueStacks_nxt_cn',
            'LDPlayer',
            'LDPlayer4',
            'LDPlayer9',
            'leidian',
            'leidian4',
            'leidian9',
            'Nemu',
            'MEmu',
        ]
        for path in known_uninstall_registry_path:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as reg:
                for software in list_key(reg):
                    if software not in known_emulator_registry_name:
                        continue
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f'{path}\\{software}') as software_reg:
                        uninstall = winreg.QueryValueEx(software_reg, 'UninstallString')[0]
                        if not uninstall:
                            continue
                        # UninstallString 格式如：
                        # C:\Program Files\BlueStacks_nxt\BlueStacksUninstaller.exe -tmp
                        # "E:\ProgramFiles\Microvirt\MEmu\uninstall\uninstall.exe" -u
                        # 提取引号中的路径
                        res = re.search('"(.*?)"', uninstall)
                        uninstall = res.group(1) if res else uninstall
                        yield uninstall

    @cached_property
    def all_emulators(self) -> t.List[Emulator]:
        """获取当前计算机上所有已安装的模拟器。"""
        exe = set([])

        # 通过 MuiCache 注册表查找已运行过的模拟器
        path = r'Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache'
        regex = re.compile(r'(^.*\.exe)\.')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as reg:
            for row in list_reg(reg):
                res = regex.search(row.name)
                if res:
                    file = res.group(1)
                    if Emulator.is_emulator(file) and os.path.exists(file):
                        exe.add(file)

        # 雷电模拟器安装路径
        for path in [r'SOFTWARE\leidian\ldplayer',
                     r'SOFTWARE\leidian\ldplayer9']:
            ld = self.get_install_dir_from_reg(path, 'InstallDir')
            if ld:
                ld = abspath(os.path.join(ld, './dnplayer.exe'))
                if Emulator.is_emulator(ld) and os.path.exists(ld):
                    exe.add(ld)

        # 通过卸载注册表查找模拟器
        for uninstall in self.iter_uninstall_registry():
            # 从卸载程序目录中查找模拟器可执行文件
            for file in iter_folder(abspath(os.path.dirname(uninstall)), ext='.exe'):
                if Emulator.is_emulator(file) and os.path.exists(file):
                    exe.add(file)
            for file in iter_folder(abspath(os.path.join(os.path.dirname(uninstall), '../')), ext='.exe'):
                if Emulator.is_emulator(file) and os.path.exists(file):
                    exe.add(file)

        exe = [Emulator(path).path for path in exe if Emulator.is_emulator(path)]
        exe = sorted(set(exe))
        exe = [Emulator(path) for path in exe]
        return exe

    @cached_property
    def all_emulator_instances(self) -> t.List[EmulatorInstance]:
        """获取当前计算机上所有已安装的模拟器实例。"""
        instances = []
        for emulator in self.all_emulators:
            instances += list(emulator.iter_instances())

        instances: t.List[EmulatorInstance] = sorted(instances, key=lambda x: str(x))
        return instances


if __name__ == '__main__':
    self = EmulatorManager()
    for emu in self.all_emulator_instances:
        print(emu)
