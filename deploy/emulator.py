import asyncio
import filecmp
import os
import re
import shutil
import subprocess
import winreg

from deploy.logger import logger
from deploy.utils import cached_property

asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


class VirtualBoxEmulator:
    UNINSTALL_REG = "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
    UNINSTALL_REG_2 = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"

    def __init__(self, name, root_path, adb_path, vbox_path, vbox_name):
        """初始化基于 VirtualBox 的模拟器配置。

        Args:
            name (str): 模拟器在 Windows 卸载列表中的名称。
            root_path (str): 从 uninstall.exe 到模拟器安装目录的相对路径。
            adb_path (str, list[str]): adb.exe 的相对路径，多个时传列表。
            vbox_path (str): VirtualBox 虚拟机文件夹的相对路径。
            vbox_name (str): 匹配 .vbox 文件名的正则表达式。
        """
        self.name = name
        self.root_path = root_path
        self.adb_path = adb_path if isinstance(adb_path, list) else [adb_path]
        self.vbox_path = vbox_path
        self.vbox_name = vbox_name

    @cached_property
    def root(self):
        """获取模拟器的根安装目录。

        Returns:
            str: 模拟器根安装目录路径。

        Raises:
            FileNotFoundError: 模拟器未安装。
        """
        if self.name == 'LDPlayer4':
            root = self.get_install_dir_from_reg('SOFTWARE\\leidian\\ldplayer', 'InstallDir')
            if root is not None:
                return root
        if self.name == 'LDPlayer9':
            root = self.get_install_dir_from_reg('SOFTWARE\\leidian\\ldplayer9', 'InstallDir')
            if root is not None:
                return root

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f'{self.UNINSTALL_REG}\\{self.name}', 0) as reg:
                res = winreg.QueryValueEx(reg, 'UninstallString')[0]
        except FileNotFoundError:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f'{self.UNINSTALL_REG_2}\\{self.name}', 0) as reg:
                res = winreg.QueryValueEx(reg, 'UninstallString')[0]

        file = re.search('"(.*?)"', res)
        file = file.group(1) if file else res
        root = os.path.abspath(os.path.join(os.path.dirname(file), self.root_path))
        return root

    def get_install_dir_from_reg(self, path, key):
        """从注册表获取模拟器安装目录。

        Args:
            path (str): 注册表路径，如 'SOFTWARE\\leidian\\ldplayer'。
            key (str): 注册表键名，如 'InstallDir'。

        Returns:
            str: 安装目录路径，未找到时返回 None。
        """
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0) as reg:
                root = winreg.QueryValueEx(reg, key)[0]
                if os.path.exists(root):
                    return root
        except FileNotFoundError:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0) as reg:
                root = winreg.QueryValueEx(reg, key)[0]
                if os.path.exists(root):
                    return root
        except FileNotFoundError:
            pass

        return None

    @cached_property
    def adb_binary(self):
        return [os.path.abspath(os.path.join(self.root, a)) for a in self.adb_path]

    @cached_property
    def adb_backup(self):
        files = []
        for adb in self.adb_binary:
            for n in range(10):
                backup = f'{adb}.bak{n}' if n else f'{adb}.bak'
                if os.path.exists(backup):
                    continue
                else:
                    files.append(backup)
                    break
        return files

    @cached_property
    def serial(self):
        """从虚拟机配置文件中解析 ADB 连接端口。

        Returns:
            list[str]: ADB 连接地址列表，如 ['127.0.0.1:62001', '127.0.0.1:62025']。
        """
        vbox = []
        for path, folders, files in os.walk(os.path.join(self.root, self.vbox_path)):
            for file in files:
                if re.match(self.vbox_name, file):
                    file = os.path.join(path, file)
                    vbox.append(file)

        serial = []
        for file in vbox:
            with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f.readlines():
                    # <Forwarding name="port2" proto="1" hostip="127.0.0.1" hostport="62026" guestport="5555"/>
                    res = re.search('<*?hostport="(.*?)".*?guestport="5555"/>', line)
                    if res:
                        serial.append(f'127.0.0.1:{res.group(1)}')

        return serial

    def adb_replace(self, adb):
        """将模拟器目录中的 ADB 备份为 xxx.bak 并替换为指定的 ADB。

        替换前需先调用 `adb kill-server`。

        Args:
            adb (str): adb.exe 的绝对路径。
        """
        for ori, bak in zip(self.adb_binary, self.adb_backup):
            logger.info(f'Replacing {ori}')
            try:
                if os.path.exists(ori):
                    if filecmp.cmp(adb, ori, shallow=True):
                        logger.info(f'{adb} is same as {ori}, skip')
                    else:
                        logger.info(f'{ori} -----> {bak}')
                        shutil.move(ori, bak)
                        logger.info(f'{adb} -----> {ori}')
                        shutil.copy(adb, ori)
                else:
                    logger.info(f'{ori} not exists, skip')
            except OSError as e:
                logger.warning(f'Failed to replace {ori}, {e}')

    def adb_recover(self):
        """恢复 ADB 替换，将备份文件还原到原始位置。"""
        for ori in self.adb_binary:
            logger.info(f'Recovering {ori}')
            bak = f'{ori}.bak'
            if os.path.exists(bak):
                logger.info(f'Delete {ori}')
                if os.path.exists(ori):
                    os.remove(ori)
                logger.info(f'{bak} -----> {ori}')
                shutil.move(bak, ori)
            else:
                logger.info(f'Not exists {bak}, skip')


# 夜神模拟器
nox_player = VirtualBoxEmulator(
    name="Nox",
    root_path=".",
    adb_path=["./adb.exe", "./nox_adb.exe"],
    vbox_path="./BignoxVMS",
    vbox_name='.*.vbox$'
)
nox_player_64 = VirtualBoxEmulator(
    name="Nox64",
    root_path=".",
    adb_path=["./adb.exe", "./nox_adb.exe"],
    vbox_path="./BignoxVMS",
    vbox_name='.*.vbox$'
)
# 雷电模拟器
ld_player = VirtualBoxEmulator(
    name="LDPlayer",
    root_path=".",
    adb_path="./adb.exe",
    vbox_path="./vms",
    vbox_name='.*.vbox$'
)
ld_player_4 = VirtualBoxEmulator(
    name="LDPlayer4",
    root_path=".",
    adb_path="./adb.exe",
    vbox_path="./vms",
    vbox_name='.*.vbox$'
)
ld_player_9 = VirtualBoxEmulator(
    name="LDPlayer9",
    root_path=".",
    adb_path="./adb.exe",
    vbox_path="./vms",
    vbox_name='.*.vbox$'
)
# 逍遥模拟器
memu_player = VirtualBoxEmulator(
    name="MEmu",
    root_path="../",
    adb_path="./adb.exe",
    vbox_path="./MemuHyperv VMs",
    vbox_name='.*.memu$'
)
# MuMu 模拟器
mumu_player = VirtualBoxEmulator(
    name="Nemu",
    root_path=".",
    adb_path="./vmonitor/bin/adb_server.exe",
    vbox_path="./vms",
    vbox_name='.*.nemu$'
)


class EmulatorConnect:
    SUPPORTED_EMULATORS = [
        nox_player,
        nox_player_64,
        ld_player,
        ld_player_4,
        ld_player_9,
        memu_player,
        mumu_player
    ]

    def __init__(self, adb='adb.exe'):
        self.adb_binary = adb

    def _execute(self, cmd, timeout=10, output=True):
        """执行命令行命令。

        Args:
            cmd: 命令列表。
            timeout: 超时秒数，默认 10。
            output: 是否返回标准输出。

        Returns:
            str 或 int: output=True 时返回标准输出字符串，否则返回返回码。
        """
        if not output:
            cmd.extend(['>nul', '2>nul'])
        logger.info(' '.join(cmd))
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            ret_code = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            ret_code = 1
            logger.info(f'TimeoutExpired, stdout={stdout}, stderr={stderr}')
        if output:
            return stdout
        else:
            return ret_code

    @cached_property
    def emulators(self):
        """获取当前计算机上已安装的模拟器列表。

        Returns:
            list: 已安装的 VirtualBoxEmulator 实例列表。
        """
        emulators = []
        for emulator in self.SUPPORTED_EMULATORS:
            try:
                serial = emulator.serial
                emulators.append(emulator)
            except FileNotFoundError:
                continue
            if len(serial):
                logger.info(f'Emulator {emulator.name} found, instances: {serial}')

        return emulators

    def devices(self):
        """获取当前 ADB 已连接的设备列表。

        Returns:
            list[str]: 已连接设备的序列号列表。
        """
        result = self._execute([self.adb_binary, 'devices']).decode()
        devices = []
        for line in result.replace('\r\r\n', '\n').replace('\r\n', '\n').split('\n'):
            if line.startswith('List') or '\t' not in line:
                continue
            serial, status = line.split('\t')
            if status == 'device':
                devices.append(serial)

        logger.info(f'Devices: {devices}')
        return devices

    def adb_kill(self):
        # 直接杀进程，因为部分 ADB 不遵守 kill-server 协议
        logger.info('Kill all known ADB')
        for exe in [
            'adb.exe',
            'nox_adb.exe',
            'adb_server.exe',
            'HD-Adb.exe'
        ]:
            ret_code = self._execute(['taskkill', '/f', '/im', exe], output=False)
            if ret_code == 0:
                logger.info(f'Task {exe} killed')
            elif ret_code == 128:
                logger.info(f'Task {exe} not found')
            else:
                logger.info(f'Error occurred when killing task {exe}, return code {ret_code}')

    @cached_property
    def serial(self):
        """获取当前计算机上所有可用的模拟器序列号。

        Returns:
            list[str]: 所有可用的模拟器 ADB 序列号。
        """
        serial = ['127.0.0.1:7555']
        for emulator in self.emulators:
            serial += emulator.serial
            for s in emulator.serial:
                ip, port = s.split(':')
                port = int(port) - 1
                if 5554 <= int(port) < 5600:
                    serial.append(f'emulator-{port}')

        return serial

    def brute_force_connect(self):
        """暴力连接所有可用的模拟器实例。"""
        self.devices()

        async def connect():
            await asyncio.gather(
                *[asyncio.create_subprocess_exec(self.adb_binary, 'connect', serial) for serial in self.serial]
            )

        asyncio.run(connect())

        return self.devices()

    def adb_replace(self, adb=None):
        """替换模拟器中的 ADB 以避免版本冲突。

        不同版本的 ADB 启动时会互相终止。国产模拟器使用自带的 ADB，
        启动时会杀死 AzurPilot 正在使用的 adb.exe。替换模拟器中的 ADB 是最简单的解决方案。

        Args:
            adb (str): adb.exe 的绝对路径。
        """
        self.adb_kill()
        for emulator in self.emulators:
            emulator.adb_replace(adb if adb is not None else self.adb_binary)
        self.brute_force_connect()

    def adb_recover(self):
        """恢复 ADB 替换，将所有模拟器的 ADB 还原为原始版本。"""
        self.adb_kill()
        for emulator in self.emulators:
            emulator.adb_recover()
        self.brute_force_connect()


if __name__ == '__main__':
    emu = EmulatorConnect()
    logger.info(emu.brute_force_connect())
