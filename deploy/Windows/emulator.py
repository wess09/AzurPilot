import asyncio
import filecmp
import os
import shutil
import sys
import typing as t
from dataclasses import dataclass

from deploy.Windows.alas import AlasManager
from deploy.Windows.logger import logger
from deploy.Windows.utils import cached_property

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


@dataclass
class DataAdbDevice:
    serial: str
    status: str


class EmulatorManager(AlasManager):
    @cached_property
    def emulator_manager(self):
        from module.device.platform.emulator_windows import EmulatorManager
        return EmulatorManager()

    def adb_kill(self):
        # 直接杀进程，因为部分 ADB 不遵守 kill-server 协议
        logger.hr('Kill all known ADB', level=2)
        for proc in self.iter_process_by_names([
            'adb.exe',
            'nox_adb.exe',
            'adb_server.exe',
            'HD-Adb.exe'
        ]):
            logger.info(proc)
            self.kill_process(proc)

    def adb_devices(self):
        """获取当前 ADB 已连接的设备列表。

        Returns:
            list[DataAdbDevice]: 已连接的设备列表。
        """
        logger.hr('Adb deivces', level=2)
        result = self.subprocess_execute([self.adb, 'devices'])
        devices = []
        for line in result.replace('\r\r\n', '\n').replace('\r\n', '\n').split('\n'):
            if line.startswith('List') or '\t' not in line:
                continue
            serial, status = line.split('\t')
            device = DataAdbDevice(
                serial=serial,
                status=status,
            )
            devices.append(device)
            logger.info(device)
        return devices

    def brute_force_connect(self):
        """暴力连接所有可用的模拟器实例。"""
        devices = self.adb_devices()

        # 断开离线设备
        for device in devices:
            if device.status == 'offline':
                self.subprocess_execute([self.adb, 'disconnect', device.serial])

        # 获取所有模拟器序列号
        list_serial = self.emulator_manager.all_emulator_serials

        logger.hr('Brute force connect', level=2)

        async def _connect(serial):
            try:
                await asyncio.create_subprocess_exec(self.adb, 'connect', serial)
            except Exception as e:
                logger.info(e)

        async def connect():
            await asyncio.gather(
                *[_connect(serial) for serial in list_serial]
            )

        asyncio.run(connect())

        return self.adb_devices()

    @staticmethod
    def adb_path_to_backup(adb, new_backup=True):
        """获取 ADB 的备份文件路径。

        Args:
            adb (str): ADB 二进制文件路径。
            new_backup (bool): True 返回新的备份路径，False 返回已有的备份路径。

        Returns:
            str: 备份文件路径。
        """
        for n in range(10):
            backup = f'{adb}.bak{n}' if n else f'{adb}.bak'
            if os.path.exists(backup):
                if new_backup:
                    continue
                else:
                    return backup
            else:
                if new_backup:
                    return backup
                else:
                    continue

        # 备份数量过多时覆盖第一个
        return f'{adb}.bak'

    def iter_adb_to_replace(self) -> t.Iterable[str]:
        for adb in self.emulator_manager.all_adb_binaries:
            if filecmp.cmp(adb, self.adb, shallow=True):
                logger.info(f'{adb} is same as {self.adb}, skip')
                continue
            else:
                yield adb

    def adb_replace(self):
        """将模拟器目录中的 ADB 备份并替换为指定的 ADB。

        替换前必须先调用 `adb kill-server`。
        """
        replace = list(self.iter_adb_to_replace())
        if not replace:
            logger.info('No need to replace')
            return

        self.adb_kill()
        for adb in replace:
            logger.info(f'Replacing {adb}')
            bak = self.adb_path_to_backup(adb, new_backup=True)
            try:
                logger.info(f'{adb} -----> {bak}')
                shutil.move(adb, bak)
                logger.info(f'{self.adb} -----> {adb}')
                shutil.copy(self.adb, adb)
            except OSError as e:
                logger.warning(f'Failed to replace {adb}, {e}')

    def adb_recover(self):
        """恢复 ADB 替换，将备份文件还原到原始位置。"""
        for adb in self.emulator_manager.all_adb_binaries:
            logger.info(f'Recovering {adb}')
            bak = self.adb_path_to_backup(adb, new_backup=False)
            if os.path.exists(bak):
                logger.info(f'Delete {adb}')
                if os.path.exists(adb):
                    os.remove(adb)
                logger.info(f'{bak} -----> {adb}')
                shutil.move(bak, adb)
            else:
                logger.info('No backup available, skip')
                continue


if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(__file__), '../../'))
    self = EmulatorManager()
    self.brute_force_connect()
