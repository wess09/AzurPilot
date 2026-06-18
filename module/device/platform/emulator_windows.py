import codecs
import os
import re
import typing as t
import winreg
from dataclasses import dataclass

# module/device/platform/emulator_base.py
# module/device/platform/emulator_windows.py
# 会在 Alas Easy Install 中使用，不应导入任何 Alas 模块。
from module.device.platform.emulator_base import EmulatorBase, EmulatorInstanceBase, EmulatorManagerBase, \
    remove_duplicated_path
from module.device.platform.utils import cached_property, iter_folder


@dataclass
class RegValue:
    """注册表值的数据结构。"""
    name: str
    value: str
    typ: int


def list_reg(reg) -> t.List[RegValue]:
    """
    列出注册表键下的所有值。

    Args:
        reg: 已打开的注册表键句柄

    Returns:
        list[RegValue]: 注册表值列表
    """
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
    """
    列出注册表键下的所有子键名称。

    Args:
        reg: 已打开的注册表键句柄

    Returns:
        list[RegValue]: 子键名称列表
    """
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


class EmulatorInstance(EmulatorInstanceBase):
    """Windows 平台的模拟器实例。"""

    @cached_property
    def emulator(self):
        """
        Returns:
            Emulator: 当前实例对应的 Windows 模拟器对象
        """
        return Emulator(self.path)


class Emulator(EmulatorBase):
    """Windows 平台的模拟器类型识别和实例枚举。"""

    @classmethod
    def path_to_type(cls, path: str) -> str:
        """
        根据 .exe 文件路径判断模拟器类型（大小写不敏感）。

        Args:
            path: .exe 文件路径

        Returns:
            str: 模拟器类型，如 Emulator.NoxPlayer；如果不是模拟器则返回空字符串
        """
        folder, exe = os.path.split(path)
        folder, dir1 = os.path.split(folder)
        folder, dir2 = os.path.split(folder)
        exe = exe.lower()
        dir1 = dir1.lower()
        dir2 = dir2.lower()
        if exe == 'nox.exe':
            if dir2 == 'nox':
                return cls.NoxPlayer
            elif dir2 == 'nox64':
                return cls.NoxPlayer64
            else:
                return cls.NoxPlayer
        if exe in ['bluestacks.exe', 'bluestacksgp.exe']:
            if dir1 in ['bluestacks', 'bluestacks_cn', 'bluestackscn']:
                return cls.BlueStacks4
            elif dir1 in ['bluestacks_nxt', 'bluestacks_nxt_cn']:
                return cls.BlueStacks5
            else:
                return cls.BlueStacks4
        if exe == 'hd-player.exe':
            if dir1 in ['bluestacks', 'bluestacks_cn']:
                return cls.BlueStacks4
            elif dir1 in ['bluestacks_nxt', 'bluestacks_nxt_cn']:
                return cls.BlueStacks5
            else:
                return cls.BlueStacks5
        if exe == 'dnplayer.exe':
            if dir1 == 'ldplayer':
                return cls.LDPlayer3
            elif dir1 == 'ldplayer4':
                return cls.LDPlayer4
            elif dir1 == 'ldplayer9':
                return cls.LDPlayer9
            elif dir1 == 'ldplayer14':
                return cls.LDPlayer14
            else:
                return cls.LDPlayer3
        if exe == 'nemuplayer.exe':
            if dir2 == 'nemu':
                return cls.MuMuPlayer
            elif dir2 == 'nemu9':
                return cls.MuMuPlayerX
            else:
                return cls.MuMuPlayer
        if exe in ['mumuplayer.exe', 'mumunxmain.exe']:
            return cls.MuMuPlayer12
        if exe == 'memu.exe':
            return cls.MEmuPlayer

        return ''

    @staticmethod
    def multi_to_single(exe: str):
        """
        将多实例管理器路径转换为对应的单实例可执行文件路径。

        Args:
            exe (str): 模拟器可执行文件路径

        Yields:
            str: 模拟器可执行文件路径
        """
        if 'HD-MultiInstanceManager.exe' in exe:
            yield exe.replace('HD-MultiInstanceManager.exe', 'HD-Player.exe')
            yield exe.replace('HD-MultiInstanceManager.exe', 'Bluestacks.exe')
        elif 'MultiPlayerManager.exe' in exe:
            yield exe.replace('MultiPlayerManager.exe', 'Nox.exe')
        elif 'dnmultiplayer.exe' in exe:
            yield exe.replace('dnmultiplayer.exe', 'dnplayer.exe')
        elif 'NemuMultiPlayer.exe' in exe:
            yield exe.replace('NemuMultiPlayer.exe', 'NemuPlayer.exe')
        elif 'MuMuMultiPlayer.exe' in exe:
            yield exe.replace('MuMuMultiPlayer.exe', 'MuMuPlayer.exe')
        elif 'MuMuManager.exe' in exe:
            yield exe.replace('MuMuManager.exe', 'MuMuPlayer.exe')
        elif 'MEmuConsole.exe' in exe:
            yield exe.replace('MEmuConsole.exe', 'MEmu.exe')
        else:
            yield exe

    @staticmethod
    def single_to_console(exe: str):
        """
        将单实例可执行文件路径转换为对应的控制台工具路径。

        Args:
            exe (str): 模拟器可执行文件路径

        Returns:
            str: 模拟器控制台工具路径
        """
        if 'MuMuPlayer.exe' in exe:
            return exe.replace('MuMuPlayer.exe', 'MuMuManager.exe')
        # MuMuPlayer12 5.0
        elif 'MuMuNxMain.exe' in exe:
            return exe.replace('MuMuNxMain.exe', 'MuMuManager.exe')
        elif 'LDPlayer.exe' in exe:
            return exe.replace('LDPlayer.exe', 'ldconsole.exe')
        elif 'dnplayer.exe' in exe:
            return exe.replace('dnplayer.exe', 'ldconsole.exe')
        elif 'Bluestacks.exe' in exe:
            return exe.replace('Bluestacks.exe', 'bsconsole.exe')
        elif 'MEmu.exe' in exe:
            return exe.replace('MEmu.exe', 'memuc.exe')
        else:
            return exe

    @staticmethod
    def vbox_file_to_serial(file: str) -> str:
        """
        从 vbox 配置文件中解析 ADB 序列号。

        Args:
            file: vbox 配置文件路径

        Returns:
            str: 序列号，如 `127.0.0.1:5555`；未找到则返回空字符串
        """
        regex = re.compile('<*?hostport="(.*?)".*?guestport="5555"/>')
        try:
            with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f.readlines():
                    # <Forwarding name="port2" proto="1" hostip="127.0.0.1" hostport="62026" guestport="5555"/>
                    res = regex.search(line)
                    if res:
                        return f'127.0.0.1:{res.group(1)}'
            return ''
        except FileNotFoundError:
            return ''

    def iter_instances(self):
        """
        遍历当前模拟器中发现的所有实例。

        Yields:
            EmulatorInstance: 模拟器实例
        """
        if self == Emulator.NoxPlayerFamily:
            # ./BignoxVMS/{name}/{name}.vbox
            for folder in self.list_folder('./BignoxVMS', is_dir=True):
                for file in iter_folder(folder, ext='.vbox'):
                    serial = Emulator.vbox_file_to_serial(file)
                    if serial:
                        yield EmulatorInstance(
                            serial=serial,
                            name=os.path.basename(folder),
                            path=self.path,
                        )
        elif self == Emulator.BlueStacks5:
            # 获取 UserDefinedDir，BlueStacks 数据存储位置
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
            # 读取 {UserDefinedDir}/bluestacks.conf
            try:
                with open(self.abspath('./bluestacks.conf', folder), encoding='utf-8') as f:
                    content = f.read()
            except FileNotFoundError:
                return
            # bst.instance.Nougat64.adb_port="5555"
            emulators = re.findall(r'bst.instance.(\w+).status.adb_port="(\d+)"', content)
            for emulator in emulators:
                yield EmulatorInstance(
                    serial=f'127.0.0.1:{emulator[1]}',
                    name=emulator[0],
                    path=self.path,
                )
        elif self == Emulator.BlueStacks4:
            # ../Engine/Android
            regex = re.compile(r'^Android')
            for folder in self.list_folder('./Engine/ProgramData/Engine', is_dir=True):
                folder = os.path.basename(folder)
                res = regex.match(folder)
                if not res:
                    continue
                # BlueStacks4 的序列号不是静态的，每次启动模拟器都会递增
                # 假设统一使用 127.0.0.1:5555
                yield EmulatorInstance(
                    serial=f'127.0.0.1:5555',
                    name=folder,
                    path=self.path
                )
        elif self == Emulator.LDPlayerFamily:
            # ./vms/leidian0
            regex = re.compile(r'^leidian(\d+)$')
            for folder in self.list_folder('./vms', is_dir=True):
                folder = os.path.basename(folder)
                res = regex.match(folder)
                if not res:
                    continue
                # 雷电模拟器的 .vbox 文件中没有端口转发配置
                # 端口自动递增：5555, 5557, 5559 等
                port = int(res.group(1)) * 2 + 5555
                yield EmulatorInstance(
                    serial=f'127.0.0.1:{port}',
                    name=folder,
                    path=self.path
                )
        elif self == Emulator.MuMuPlayer:
            # MuMu 6 没有多实例功能，固定使用 7555 端口
            yield EmulatorInstance(
                serial='127.0.0.1:7555',
                name='',
                path=self.path,
            )
        elif self == Emulator.MuMuPlayerX:
            # vms/nemu-12.0-x64-default
            for folder in self.list_folder('../vms', is_dir=True):
                for file in iter_folder(folder, ext='.nemu'):
                    serial = Emulator.vbox_file_to_serial(file)
                    if serial:
                        yield EmulatorInstance(
                            serial=serial,
                            name=os.path.basename(folder),
                            path=self.path,
                        )
        elif self == Emulator.MuMuPlayer12:
            # vms/MuMuPlayer-12.0-0
            for folder in self.list_folder('../vms', is_dir=True):
                for file in iter_folder(folder, ext='.nemu'):
                    serial = Emulator.vbox_file_to_serial(file)
                    name = os.path.basename(folder)
                    if serial:
                        yield EmulatorInstance(
                            serial=serial,
                            name=name,
                            path=self.path,
                        )
                    # 适配 MuMu12 v4.0.4，默认实例在 vbox 配置中没有端口转发记录
                    else:
                        instance = EmulatorInstance(
                            serial=serial,
                            name=name,
                            path=self.path,
                        )
                        if instance.MuMuPlayer12_id:
                            instance.serial = f'127.0.0.1:{16384 + 32 * instance.MuMuPlayer12_id}'
                            yield instance
        elif self == Emulator.MEmuPlayer:
            # ./MemuHyperv VMs/{name}/{name}.memu
            for folder in self.list_folder('./MemuHyperv VMs', is_dir=True):
                for file in iter_folder(folder, ext='.memu'):
                    serial = Emulator.vbox_file_to_serial(file)
                    if serial:
                        yield EmulatorInstance(
                            serial=serial,
                            name=os.path.basename(folder),
                            path=self.path,
                        )

    def iter_adb_binaries(self) -> t.Iterable[str]:
        """
        遍历当前模拟器中找到的 adb 二进制文件路径。

        Yields:
            str: adb 二进制文件的绝对路径
        """
        if self == Emulator.NoxPlayerFamily:
            exe = self.abspath('./nox_adb.exe')
            if os.path.exists(exe):
                yield exe
        if self == Emulator.MuMuPlayerFamily:
            # 从 MuMu9\emulator\nemu9\EmulatorShell
            # 到 MuMu9\emulator\nemu9\vmonitor\bin\adb_server.exe
            exe = self.abspath('../vmonitor/bin/adb_server.exe')
            if os.path.exists(exe):
                yield exe

        # 所有模拟器都有 adb.exe
        exe = self.abspath('./adb.exe')
        if os.path.exists(exe):
            yield exe


class EmulatorManager(EmulatorManagerBase):
    """Windows 平台的模拟器管理器，通过注册表和进程扫描发现已安装的模拟器。"""

    @staticmethod
    def iter_user_assist():
        """
        从 UserAssist 注册表项获取最近执行的程序列表。
        参考: https://github.com/forensicmatt/MonitorUserAssist

        Yields:
            str: 模拟器可执行文件路径，可能包含重复值
        """
        path = r'Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist'
        # {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}\xxx.exe
        regex_hash = re.compile(r'{.*}')
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as reg:
                folders = list_key(reg)
        except FileNotFoundError:
            return

        for folder in folders:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f'{path}\\{folder}\\Count') as reg:
                    for key in list_reg(reg):
                        key = codecs.decode(key.name, 'rot-13')
                        # 跳过带哈希的条目
                        if regex_hash.search(key):
                            continue
                        for file in Emulator.multi_to_single(key):
                            yield file
            except FileNotFoundError:
                # FileNotFoundError: [WinError 2] 系统找不到指定的文件。
                # 可能是缺少 "Count" 子目录的随机目录
                continue

    @staticmethod
    def iter_mui_cache():
        """
        遍历 MuiCache 注册表项中曾经运行过的模拟器可执行文件。
        参考: http://what-when-how.com/windows-forensic-analysis/registry-analysis-windows-forensic-analysis-part-8/

        Yields:
            str: 模拟器可执行文件路径，可能包含重复值
        """
        path = r'Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as reg:
                rows = list_reg(reg)
        except FileNotFoundError:
            return

        regex = re.compile(r'(^.*\.exe)\.')
        for row in rows:
            res = regex.search(row.name)
            if not res:
                continue
            for file in Emulator.multi_to_single(res.group(1)):
                yield file

    @staticmethod
    def get_install_dir_from_reg(path, key):
        """
        从注册表获取安装目录。

        Args:
            path (str): 注册表路径，如 f'SOFTWARE\\leidian\\ldplayer'
            key (str): 注册表值名，如 'InstallDir'

        Returns:
            str: 安装目录路径，未找到则返回 None
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
        """
        从注册表中遍历模拟器的卸载程序路径。

        Yields:
            str: 卸载程序的可执行文件路径
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
            'Nemu9',
            'MuMuPlayer',
            'MuMuPlayer-12.0',
            'MuMu Player 12.0',
            'MEmu',
        ]
        for path in known_uninstall_registry_path:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as reg:
                    software_list = list_key(reg)
            except FileNotFoundError:
                continue
            for software in software_list:
                if software not in known_emulator_registry_name:
                    continue
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f'{path}\\{software}') as software_reg:
                        uninstall = winreg.QueryValueEx(software_reg, 'UninstallString')[0]
                except FileNotFoundError:
                    continue
                if not uninstall:
                    continue
                # UninstallString 格式如:
                # C:\Program Files\BlueStacks_nxt\BlueStacksUninstaller.exe -tmp
                # "E:\ProgramFiles\Microvirt\MEmu\uninstall\uninstall.exe" -u
                # 提取 "" 中的路径
                res = re.search('"(.*?)"', uninstall)
                uninstall = res.group(1) if res else uninstall
                yield uninstall

    @staticmethod
    def iter_running_emulator():
        """
        遍历正在运行的模拟器可执行文件路径。

        Yields:
            str: 模拟器可执行文件路径，可能包含重复值
        """
        try:
            import psutil
        except ModuleNotFoundError:
            return
        # 由于这是一次性使用，直接访问 psutil._psplatform.Process
        # 以跳过 psutil.Process.is_running() 的调用开销。
        # 此方式仅需约 0.017 秒。
        for pid in psutil.pids():
            proc = psutil._psplatform.Process(pid)
            try:
                exe = proc.cmdline()
                exe = exe[0].replace(r'\\', '/').replace('\\', '/')
            except (psutil.AccessDenied, psutil.NoSuchProcess, IndexError, OSError):
                # psutil.AccessDenied
                # NoSuchProcess: 进程已不存在 (pid=xxx)
                # OSError: [WinError 87] 参数错误。: '(originated from ReadProcessMemory)'
                continue

            if Emulator.is_emulator(exe):
                yield exe

    @cached_property
    def all_emulators(self) -> t.List[Emulator]:
        """
        获取当前计算机上安装的所有模拟器。

        Returns:
            list[Emulator]: 模拟器列表
        """
        exe = set([])

        # MuiCache
        for file in EmulatorManager.iter_mui_cache():
            if Emulator.is_emulator(file) and os.path.exists(file):
                exe.add(file)

        # UserAssist
        for file in EmulatorManager.iter_user_assist():
            if Emulator.is_emulator(file) and os.path.exists(file):
                exe.add(file)

        # 雷电模拟器安装路径
        for path in [
            r'SOFTWARE\leidian\ldplayer',
            r'SOFTWARE\leidian\ldplayer9',
            r'SOFTWARE\leidian\ldplayer14',
        ]:
            ld = self.get_install_dir_from_reg(path, 'InstallDir')
            if ld:
                ld = abspath(os.path.join(ld, './dnplayer.exe'))
                if Emulator.is_emulator(ld) and os.path.exists(ld):
                    exe.add(ld)

        # 卸载注册表
        for uninstall in EmulatorManager.iter_uninstall_registry():
            # 从卸载程序所在目录查找模拟器可执行文件
            for file in iter_folder(abspath(os.path.dirname(uninstall)), ext='.exe'):
                if Emulator.is_emulator(file) and os.path.exists(file):
                    exe.add(file)
            # 从上级目录查找
            for file in iter_folder(abspath(os.path.join(os.path.dirname(uninstall), '../')), ext='.exe'):
                if Emulator.is_emulator(file) and os.path.exists(file):
                    exe.add(file)
            # MuMu 特定目录
            for file in iter_folder(abspath(os.path.join(os.path.dirname(uninstall), 'EmulatorShell')), ext='.exe'):
                if Emulator.is_emulator(file) and os.path.exists(file):
                    exe.add(file)

        # 正在运行的模拟器
        for file in EmulatorManager.iter_running_emulator():
            if os.path.exists(file):
                exe.add(file)

        # 去重
        exe = [Emulator(path).path for path in exe if Emulator.is_emulator(path)]
        exe = [Emulator(path) for path in remove_duplicated_path(exe)]
        return exe

    @cached_property
    def all_emulator_instances(self) -> t.List[EmulatorInstance]:
        """
        获取当前计算机上安装的所有模拟器实例。

        Returns:
            list[EmulatorInstance]: 模拟器实例列表
        """
        instances = []
        for emulator in self.all_emulators:
            instances += list(emulator.iter_instances())

        instances: t.List[EmulatorInstance] = sorted(instances, key=lambda x: str(x))
        return instances


if __name__ == '__main__':
    self = EmulatorManager()
    for emu in self.all_emulator_instances:
        print(emu)
