from __future__ import annotations
import os
import re
import subprocess
import time

import psutil

from module.base.decorator import run_once
from module.base.timer import Timer
from module.device.platform.platform_base import PlatformBase
from module.device.platform.emulator_mac import (
    EmulatorMac,
    EmulatorInstanceMac,
    EmulatorManagerMac,
)
from module.logger import logger


class PlatformMac(PlatformBase, EmulatorManagerMac):
    """
    macOS 平台的模拟器控制接口。
    支持 BlueStacks Air 和 MuMu Pro。
    """

    @classmethod
    def execute(cls, command, wait=True):
        """
        执行外部命令。

        Args:
            command (str): 要执行的命令
            wait (bool): 是否等待命令完成

        Returns:
            subprocess.CompletedProcess 或 subprocess.Popen: 命令执行结果
        """
        # 在 Mac 上使用 shell=True 执行复杂命令
        logger.info(f'Execute: {command}')
        if wait:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True
            )
            return result
        else:
            return subprocess.Popen(command, shell=True)

    @classmethod
    def kill_process_by_regex(cls, regex: str) -> int:
        """
        终止名称匹配给定正则表达式的进程。

        Args:
            regex: 匹配进程名称的正则表达式

        Returns:
            int: 已终止的进程数量
        """
        count = 0
        for proc in psutil.process_iter():
            try:
                name = proc.name()
                if re.search(regex, name, re.IGNORECASE):
                    logger.info(f'Kill emulator process: {name}')
                    proc.kill()
                    count += 1
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return count

    @classmethod
    def renice_process_by_regex(cls, regex: str, priority: int = -20) -> int:
        """
        修改匹配正则表达式的进程优先级。

        Args:
            regex: 匹配进程名称的正则表达式
            priority: Nice 值（-20 最高优先级，19 最低优先级）

        Returns:
            int: 已修改优先级的进程数量
        """
        count = 0
        for proc in psutil.process_iter():
            try:
                name = proc.name()
                if re.search(regex, name, re.IGNORECASE):
                    pid = proc.pid
                    # 使用 sudo renice 设置优先级（需要管理员密码）
                    result = subprocess.run(
                        f'sudo -n renice -n {priority} -p {pid}',
                        shell=True,
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0:
                        logger.info(f'Reniced process {name} (PID: {pid}) to priority {priority}')
                        count += 1
                    else:
                        logger.warning(f'Failed to renice {name}: {result.stderr.strip()}')
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return count

    def boost_emulator_priority(self, instance: EmulatorInstanceMac):
        """
        启动后提升模拟器进程优先级。

        Args:
            instance: 要提升优先级的模拟器实例
        """
        if instance == EmulatorMac.BlueStacksAir:
            time.sleep(3)
            self.renice_process_by_regex(r'BlueStacks', -20)

        elif instance == EmulatorMac.MuMuPro:
            time.sleep(3)
            self.renice_process_by_regex(r'MuMuEmulator|MuMuPlayer', -20)

        else:
            if instance.name:
                time.sleep(3)
                self.renice_process_by_regex(instance.name, -20)

    def boost_running_emulator_priority(self):
        """
        提升当前正在运行的模拟器的进程优先级。
        在 Alas 启动且检测到已有模拟器运行时调用。
        """
        # 尝试提升 MuMu 进程优先级
        count = self.renice_process_by_regex(r'MuMuEmulator|MuMuPlayer', -20)
        if count > 0:
            logger.info(f'Boosted priority for {count} MuMu process(es)')
            return

        # 尝试提升 BlueStacks 进程优先级
        count = self.renice_process_by_regex(r'BlueStacks', -20)
        if count > 0:
            logger.info(f'Boosted priority for {count} BlueStacks process(es)')
            return

        logger.info('No running emulator processes found to boost')

    def _emulator_start(self, instance: EmulatorInstanceMac):
        """
        启动模拟器（不含错误处理）。

        Args:
            instance: 模拟器实例
        """
        exe: str = instance.emulator.path

        if instance == EmulatorMac.BlueStacksAir:
            # 使用 open 命令启动 BlueStacks Air 应用
            # 先查找应用包
            app_path = EmulatorMac.find_app_bundle('BlueStacks')
            if app_path:
                self.execute(f'open -a "{app_path}"', wait=False)
            else:
                raise Exception('BlueStacks Air app not found')

        elif instance == EmulatorMac.MuMuPro:
            # macOS 上的 MuMu 正确启动流程:
            # 1. open -a MuMuPlayer.app - 启动主程序
            # 2. mumutool open <index> - 启动模拟器实例
            app_path = EmulatorMac.find_app_bundle('MuMu')
            if app_path:
                # 步骤 1: 启动 MuMuPlayer 主程序
                self.execute(f'open -a "{app_path}"', wait=False)
                time.sleep(3)
                # 步骤 2: 使用 mumutool 启动指定的模拟器实例
                mumu_bin_path = os.path.join(app_path, 'Contents/MacOS/mumutool')
                if os.path.exists(mumu_bin_path):
                    # 使用 instance.index 打开指定实例
                    instance_index = getattr(instance, 'index', 0)
                    self.execute(f'"{mumu_bin_path}" open {instance_index}', wait=False)
                else:
                    logger.warning(f'mumutool not found at {mumu_bin_path}, using fallback')
                    # 回退: 尝试 MuMuEmulator.app 结构
                    mumu_emulator_app = os.path.join(app_path, 'Contents/MacOS/MuMuEmulator.app')
                    if os.path.exists(mumu_emulator_app):
                        self.execute(f'open "{mumu_emulator_app}"', wait=False)
            else:
                raise Exception('MuMu Pro app not found')

        else:
            # 通用回退: 尝试通过路径打开
            if os.path.exists(exe):
                self.execute(f'open "{exe}"', wait=False)
            else:
                raise Exception(f'Cannot start unknown emulator: {instance}')

    def _emulator_stop(self, instance: EmulatorInstanceMac):
        """
        停止模拟器（不含错误处理）。

        Args:
            instance: 模拟器实例
        """
        if instance == EmulatorMac.BlueStacksAir:
            # 尝试查找并终止 BlueStacks 进程
            killed = self.kill_process_by_regex(r'BlueStacks')
            if killed == 0:
                # 回退: 使用 osascript 退出应用
                self.execute('osascript -e \'tell application "BlueStacks" to quit\'', wait=True)

        elif instance == EmulatorMac.MuMuPro:
            # 使用 mumutool 关闭指定实例
            app_path = EmulatorMac.find_app_bundle('MuMu')
            if app_path:
                mumu_bin_path = os.path.join(app_path, 'Contents/MacOS/mumutool')
                if os.path.exists(mumu_bin_path):
                    # 使用 instance.index 关闭指定实例
                    instance_index = getattr(instance, 'index', 0)
                    self.execute(f'"{mumu_bin_path}" close {instance_index}', wait=True)
                    time.sleep(2)

            # 注意: 不使用 osascript 退出，因为这会关闭所有实例
            # 而是确保指定的进程已停止
            # 仅终止特定的 MuMu 模拟器进程（如果仍在运行）
            # 实例名称可用于定位特定实例的进程

        else:
            # 通用回退: 按实例名称终止进程
            if instance.name:
                self.kill_process_by_regex(instance.name)

    def _emulator_function_wrapper(self, func):
        """
        模拟器启停操作的统一包装器，处理异常。

        Args:
            func (callable): _emulator_start 或 _emulator_stop

        Returns:
            bool: 是否成功
        """
        try:
            func(self.emulator_instance)
            return True
        except Exception as e:
            logger.exception(e)

        logger.error(f'Emulator function {func.__name__}() failed')
        return False

    def emulator_start_watch(self):
        """
        监控模拟器启动过程，等待启动完成。

        Returns:
            bool: True 表示启动完成，False 表示超时
        """
        logger.hr('Emulator start', level=2)
        serial = self.emulator_instance.serial

        @run_once
        def show_online(m):
            logger.info(f'Emulator online: {m}')

        @run_once
        def show_ping(m):
            logger.info(f'Command ping: {m}')

        @run_once
        def show_package(m):
            logger.info(f'Found azurlane packages: {m}')

        interval = Timer(0.5).start()
        timeout = Timer(180).start()

        while 1:
            interval.wait()
            interval.reset()
            if timeout.reached():
                logger.warning(f'Emulator start timeout')
                return False

            try:
                # 检查设备连接
                devices = self.list_device().select(serial=serial)
                if devices:
                    device = devices.first_or_none()
                    if device.status == 'device':
                        pass
                    if device.status == 'offline':
                        self.adb_client.disconnect(serial)
                        self.adb_client.connect(serial)
                        continue
                else:
                    # 尝试连接
                    self.adb_client.connect(serial)
                    continue
                show_online(devices.first_or_none())

                # 检查命令可用性
                try:
                    pong = self.adb_shell(['echo', 'pong'])
                except Exception as e:
                    logger.info(e)
                    continue
                show_ping(pong)

                # 检查碧蓝航线包名
                packages = self.list_known_packages(show_log=False)
                if len(packages):
                    pass
                else:
                    continue
                show_package(packages)

                # 所有检查通过
                break
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                logger.info(e)
                continue
            except Exception as e:
                logger.exception(e)
                continue

        logger.info('Emulator start completed')
        return True

    def emulator_start(self):
        """启动模拟器，最多重试 3 次。"""
        logger.hr('Emulator start', level=1)
        self.run_remote_ssh_command()
        for _ in range(3):
            # 先停止
            if not self._emulator_function_wrapper(self._emulator_stop):
                return False
            # 再启动
            if self._emulator_function_wrapper(self._emulator_start):
                # 成功
                # 提升模拟器进程优先级
                self.boost_emulator_priority(self.emulator_instance)
                self.emulator_start_watch()
                return True
            else:
                # 启动失败，停止后重试
                if self._emulator_function_wrapper(self._emulator_stop):
                    continue
                else:
                    return False

        logger.error('Failed to start emulator 3 times, stopped')
        return False

    def emulator_stop(self):
        """停止模拟器，最多重试 3 次。"""
        logger.hr('Emulator stop', level=1)
        for _ in range(3):
            # 停止
            if self._emulator_function_wrapper(self._emulator_stop):
                # 成功
                return True
            else:
                # 停止失败，启动后重试
                if self._emulator_function_wrapper(self._emulator_start):
                    continue
                else:
                    return False

        logger.error('Failed to stop emulator 3 times, stopped')
        return False


if __name__ == '__main__':
    from module.config import AzurLaneConfig
    config = AzurLaneConfig(config_name='alas')
    self = PlatformMac(config)
    d = self.emulator_instance
    print(d)
