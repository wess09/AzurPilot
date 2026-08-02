"""Windows 平台模拟器控制。继承 PlatformBase 和 EmulatorManager，
实现 Windows 上模拟器的启动、窗口聚焦和进程管理。"""

from __future__ import annotations
import ctypes
import re
import subprocess

import psutil

from deploy.Windows.utils import DataProcessInfo
from module.base.decorator import run_once
from module.base.timer import Timer
from module.device.connection_attr import ConnectionAttr
from module.device.platform.platform_base import PlatformBase
from module.device.platform.emulator_windows import Emulator, EmulatorInstance, EmulatorManager
from module.logger import logger


class EmulatorUnknown(Exception):
    """未知模拟器类型异常。"""
    pass


def get_focused_window():
    """获取当前前台窗口的句柄。"""
    return ctypes.windll.user32.GetForegroundWindow()


def set_focus_window(hwnd):
    """将指定窗口设置为前台窗口。"""
    ctypes.windll.user32.SetForegroundWindow(hwnd)


def get_window_text(hwnd):
    """获取窗口标题文本。"""
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ''
    buf = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def check_mumu_error_dialog():
    """
    检测 MuMu 模拟器的错误对话框（如权限冲突）。

    Returns:
        bool: True 表示检测到错误对话框
    """
    # MuMu12 错误对话框的窗口标题包含 "MuMu" 或 "NemuWindow"
    # 权限冲突对话框标题通常为 "MuMuPlayer" 或类似
    found = False

    def enum_callback(hwnd, _):
        nonlocal found
        text = get_window_text(hwnd)
        if text and ('MuMu' in text or 'Nemu' in text):
            # 检查是否为错误对话框（通常有较短标题且是弹出窗口）
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                # 枚举子窗口查找包含 "无法启动" 或 "冲突" 的文本
                child_found = [False]

                def child_callback(child_hwnd, __):
                    child_text = get_window_text(child_hwnd)
                    if child_text and ('无法启动' in child_text or '冲突' in child_text
                                       or 'error' in child_text.lower()
                                       or 'cannot' in child_text.lower()):
                        child_found[0] = True
                    return True

                ctypes.windll.user32.EnumChildWindows(
                    hwnd,
                    ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(child_callback),
                    0
                )
                if child_found[0]:
                    found = True
                    logger.warning(f'[设备-Windows] 检测到MuMu错误对话框: "{text}"')
        return True

    try:
        ctypes.windll.user32.EnumWindows(
            ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_callback),
            0
        )
    except Exception as e:
        logger.warning(f'[设备-Windows] 检查MuMu错误对话框失败: {e}')
    return found


def minimize_window(hwnd):
    """最小化指定窗口。"""
    ctypes.windll.user32.ShowWindow(hwnd, 6)


def get_window_title(hwnd):
    """
    获取指定窗口的标题文本。

    Args:
        hwnd: 窗口句柄

    Returns:
        str: 窗口标题
    """
    text_len_in_characters = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    string_buffer = ctypes.create_unicode_buffer(
        text_len_in_characters + 1)  # +1 用于 null 终止符 \0
    ctypes.windll.user32.GetWindowTextW(hwnd, string_buffer, text_len_in_characters + 1)
    return string_buffer.value


def flash_window(hwnd, flash=True):
    """闪烁指定窗口以吸引注意力。"""
    ctypes.windll.user32.FlashWindow(hwnd, flash)


class PlatformWindows(PlatformBase, EmulatorManager):
    """Windows 平台的模拟器控制接口。"""

    def __init__(self, config, *, connect: bool = True):
        """
        Args:
            config: AzurLaneConfig 实例或配置名称
            connect: 是否立即建立 ADB 连接。
                     AlasPlus 在仅需要模拟器发现/启停控制
                     且模拟器当前离线时使用 connect=False，
                     以避免过早抛出 EmulatorNotRunningError。
        """
        if connect:
            # 原始行为：走完整的 Connection.__init__ 流程，
            # 包括 detect_device() 和 adb_connect()
            super().__init__(config)
        else:
            # 轻量初始化：仅准备 config/adb_client/serial，
            # 不调用 adb_connect()，因此可以在模拟器尚未运行时
            # 安全使用 emulator_instance/emulator_start()
            ConnectionAttr.__init__(self, config)

    @classmethod
    def execute(cls, command, wait=False, timeout=30):
        """
        执行外部命令。

        Args:
            command (str): 要执行的命令
            wait (bool): 是否同步等待命令完成（默认False异步执行）
            timeout (int): 同步执行时的超时秒数（默认30秒）

        Returns:
            subprocess.Popen: 异步执行时返回子进程对象
            subprocess.CompletedProcess: 同步执行时返回完成结果
        """
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        logger.info(f'[设备-Windows] 执行: {command}')

        if wait:
            # 同步执行，等待命令完成
            # 用于需要确保命令执行完毕的场景（如MuMu12的shutdown_player）
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    timeout=timeout,
                    close_fds=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                logger.info(f'[设备-Windows] 命令完成，返回码: {result.returncode}')
                return result
            except subprocess.TimeoutExpired:
                logger.warning(f'[设备-Windows] 命令超时 {timeout} 秒')
                return None
        else:
            # 异步执行，不等待完成
            # 通过 `cmd /c start` 启动进程，使其脱离 Alas 进程树。
            # 之前使用的 `start_new_session=True` 在 Windows 上仅等同于
            # `CREATE_NEW_PROCESS_GROUP`，不会改变父子进程关系，
            # `taskkill /T` 仍会终止子进程，导致关闭 Alas 时模拟器被一并关闭。
            # 使用 `cmd /c start` 后，cmd.exe 会立即退出，
            # 目标进程的父进程变为已退出的 cmd.exe，从而脱离 Alas 进程树。
            proc = subprocess.Popen(
                f'start "" /b {command}',
                shell=True,
                close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # 等待 cmd.exe 退出，确保目标进程已脱离 Alas 进程树
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f'[设备-Windows] 启动命令未在 5 秒内退出: {command}')
            return proc

    @classmethod
    def kill_process_by_regex(cls, regex: str) -> int:
        """
        终止命令行匹配给定正则表达式的进程。

        Args:
            regex: 正则表达式

        Returns:
            int: 已终止的进程数量
        """
        count = 0

        for proc in psutil.process_iter():
            cmdline = DataProcessInfo(proc=proc, pid=proc.pid).cmdline
            if re.search(regex, cmdline):
                logger.info(f'[设备-Windows] 终止模拟器: {cmdline}')
                proc.kill()
                count += 1

        return count

    def _emulator_start(self, instance: EmulatorInstance):
        """
        启动模拟器（不含错误处理）。

        Args:
            instance: 模拟器实例
        """
        exe: str = instance.emulator.path
        if instance == Emulator.MuMuPlayer:
            # NemuPlayer.exe
            # 路径可能包含空格，需要引号包裹以便 `cmd /c start` 正确解析
            self.execute(f'"{exe}"')
        elif instance == Emulator.MuMuPlayerX:
            # NemuPlayer.exe -m nemu-12.0-x64-default
            self.execute(f'"{exe}" -m {instance.name}')
        elif instance == Emulator.MuMuPlayer12:
            # MuMuManager.exe api -v 0 launch_player
            # Launch via MuMuManager instead of MuMuPlayer.exe/MuMuNxMain.exe.
            # MuMuNxMain.exe is a GUI singleton, if two instances get launched at the same time,
            # the second launch request is handed over to a MuMuNxMain.exe that is still initializing
            # and gets silently dropped, while MuMuManager queues requests in backend service.
            if instance.MuMuPlayer12_id is None:
                logger.warning(f'[设备-Windows] 无法从名称 {instance.name} 获取MuMu实例索引')
            self.execute(f'"{Emulator.single_to_console(exe)}" api -v {instance.MuMuPlayer12_id} launch_player')
        elif instance == Emulator.LDPlayerFamily:
            # ldconsole.exe launch --index 0
            self.execute(f'"{Emulator.single_to_console(exe)}" launch --index {instance.LDPlayer_id}')
        elif instance == Emulator.NoxPlayerFamily:
            # Nox.exe -clone:Nox_1
            self.execute(f'"{exe}" -clone:{instance.name}')
        elif instance == Emulator.BlueStacks5:
            # HD-Player.exe --instance Pie64
            self.execute(f'"{exe}" --instance {instance.name}')
        elif instance == Emulator.BlueStacks4:
            # Bluestacks.exe -vmname Android_1
            self.execute(f'"{exe}" -vmname {instance.name}')
        elif instance == Emulator.MEmuPlayer:
            # MEmu.exe MEmu_0
            self.execute(f'"{exe}" {instance.name}')
        elif instance.type == 'SSH':
            logger.info('[设备-Windows] 通过远程命令启动SSH模拟器')
            self.run_remote_ssh_command(getattr(self.config, 'EmulatorInfo_RemoteStartCommand', ''))
        else:
            raise EmulatorUnknown(f'Cannot start an unknown emulator instance: {instance}')

    def _emulator_stop(self, instance: EmulatorInstance):
        """
        停止模拟器（不含错误处理）。

        Args:
            instance: 模拟器实例
        """
        exe: str = instance.emulator.path
        if instance == Emulator.MuMuPlayer:
            # MuMu6 没有多实例功能，终止一个意味着终止全部
            # 共有 4 个进程:
            # "C:\Program Files\NemuVbox\Hypervisor\NemuHeadless.exe" --comment nemu-6.0-x64-default --startvm
            # "E:\ProgramFiles\MuMu\emulator\nemu\EmulatorShell\NemuPlayer.exe"
            # E:\ProgramFiles\MuMu\emulator\nemu\EmulatorShell\NemuService.exe
            # "C:\Program Files\NemuVbox\Hypervisor\NemuSVC.exe" -Embedding
            self.kill_process_by_regex(
                rf'('
                rf'NemuHeadless.exe'
                rf'|NemuPlayer.exe\"'
                rf'|NemuPlayer.exe$'
                rf'|NemuService.exe'
                rf'|NemuSVC.exe'
                rf')'
            )
        elif instance == Emulator.MuMuPlayerX:
            # MuMu X 有 3 个进程:
            # "E:\ProgramFiles\MuMu9\emulator\nemu9\EmulatorShell\NemuPlayer.exe" -m nemu-12.0-x64-default -s 0 -l
            # "C:\Program Files\Muvm6Vbox\Hypervisor\Muvm6Headless.exe" --comment nemu-12.0-x64-default --startvm xxx
            # "C:\Program Files\Muvm6Vbox\Hypervisor\Muvm6SVC.exe" --Embedding
            self.kill_process_by_regex(
                rf'('
                rf'NemuPlayer.exe.*-m {instance.name}'
                rf'|Muvm6Headless.exe'
                rf'|Muvm6SVC.exe'
                rf')'
            )
        elif instance == Emulator.MuMuPlayer12:
            # MuMuManager.exe api -v 1 shutdown_player
            # 使用同步执行等待关闭完成，避免异步执行导致的实例查找失败
            if instance.MuMuPlayer12_id is None:
                logger.warning(f'[设备-Windows] 无法从名称 {instance.name} 获取MuMu实例索引')
            logger.info('[设备-Windows] MuMuPlayer12 关闭: 使用同步执行')
            self.execute(
                f'"{Emulator.single_to_console(exe)}" api -v {instance.MuMuPlayer12_id} shutdown_player',
                wait=True,
                timeout=30
            )
        elif instance == Emulator.LDPlayerFamily:
            # ldconsole.exe quit --index 0
            self.execute(f'"{Emulator.single_to_console(exe)}" quit --index {instance.LDPlayer_id}')
        elif instance == Emulator.NoxPlayerFamily:
            # Nox.exe -clone:Nox_1 -quit
            self.execute(f'"{exe}" -clone:{instance.name} -quit')
        elif instance == Emulator.BlueStacks5:
            # BlueStacks 有 2 个进程:
            # C:\Program Files\BlueStacks_nxt_cn\HD-Player.exe --instance Pie64
            # C:\Program Files\BlueStacks_nxt_cn\BstkSVC.exe -Embedding
            self.kill_process_by_regex(
                rf'('
                rf'HD-Player.exe.*"--instance" "{instance.name}"'
                rf')'
            )
        elif instance == Emulator.BlueStacks4:
            # E:\Program Files (x86)\BluestacksCN\bsconsole.exe quit --name Android
            self.execute(f'"{Emulator.single_to_console(exe)}" quit --name {instance.name}')
        elif instance == Emulator.MEmuPlayer:
            # F:\Program Files\Microvirt\MEmu\memuc.exe stop -n MEmu_0
            self.execute(f'"{Emulator.single_to_console(exe)}" stop -n {instance.name}')
        elif instance.type == 'SSH':
            logger.info('[设备-Windows] 通过远程命令停止SSH模拟器')
            self.run_remote_ssh_command(getattr(self.config, 'EmulatorInfo_RemoteStopCommand', ''))
        else:
            raise EmulatorUnknown(f'Cannot stop an unknown emulator instance: {instance}')

    def _emulator_function_wrapper(self, func: callable):
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
        except OSError as e:
            msg = str(e)
            # OSError: [WinError 740] 请求的操作需要提升。
            if 'WinError 740' in msg:
                logger.error('[设备-Windows] 启动/停止MuMu需要以管理员身份运行')
        except EmulatorUnknown as e:
            logger.error(e)
        except Exception as e:
            logger.exception(e)

        logger.error(f'[设备-Windows] 模拟器函数 {func.__name__}() 失败')
        return False

    def emulator_start_watch(self):
        """
        监控模拟器启动过程，等待启动完成。

        Returns:
            bool: True 表示启动完成，False 表示超时
        """
        logger.hr('模拟器启动', level=2)
        current_window = get_focused_window()
        serial = self.emulator_instance.serial
        logger.info(f'[设备-Windows] 当前窗口: {current_window}')

        def adb_connect():
            m = self.adb_client.connect(self.serial)
            if 'connected' in m:
                # Connected to 127.0.0.1:59865
                # Already connected to 127.0.0.1:59865
                return False
            elif '(10061)' in m:
                # cannot connect to 127.0.0.1:55555:
                # No connection could be made because the target machine actively refused it. (10061)
                return False
            else:
                return True

        @run_once
        def show_online(m):
            logger.info(f'[设备-Windows] 模拟器在线: {m}')

        @run_once
        def show_ping(m):
            logger.info(f'[设备-Windows] 命令ping: {m}')

        @run_once
        def show_package(m):
            logger.info(f'[设备-Windows] 找到碧蓝航线应用包: {m}')

        interval = Timer(0.5).start()
        timeout = Timer(180).start()
        new_window = 0
        while 1:
            interval.wait()
            interval.reset()
            if timeout.reached():
                logger.warning(f'[设备-Windows] 模拟器启动超时')
                return False

            try:
                # 检查模拟器窗口是否弹出
                if current_window != 0 and new_window == 0:
                    new_window = get_focused_window()
                    if current_window != new_window:
                        logger.info(f'[设备-Windows] 新窗口出现: {new_window}，焦点返回')
                        set_focus_window(current_window)
                    else:
                        new_window = 0

                # 检查设备连接
                devices = self.list_device().select(serial=serial)
                if devices:
                    device = devices.first_or_none()
                    if device.status == 'device':
                        # 模拟器已上线
                        pass
                    if device.status == 'offline':
                        self.adb_client.disconnect(serial)
                        adb_connect()
                        continue
                else:
                    # 尝试连接
                    adb_connect()
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
            except (ConnectionResetError, ConnectionAbortedError) as e:
                # [WinError 10054] 远程主机强迫关闭了一个现有的连接。
                # 模拟器启动期间经常出现
                logger.info(e)
                continue
            except Exception as e:
                logger.exception(e)
                continue

            # MuMu 权限冲突等错误对话框检测
            # 检测到错误对话框时立即终止等待，返回 False 触发重试
            if check_mumu_error_dialog():
                logger.warning('[设备-Windows] 检测到MuMu错误对话框，中止启动监视')
                return False

        if new_window != 0 and new_window != current_window:
            logger.info(f'[设备-Windows] 最小化新窗口: {new_window}')
            minimize_window(new_window)
        if current_window:
            logger.info(f'[设备-Windows] 取消闪烁当前窗口: {current_window}')
            flash_window(current_window, flash=False)
        if new_window:
            logger.info(f'[设备-Windows] 闪烁新窗口: {new_window}')
            flash_window(new_window, flash=True)
        logger.info('[设备-Windows] 模拟器启动完成')
        return True

    def emulator_start(self):
        """
        启动模拟器，最多重试 3 次。
        针对 MuMu12 等模拟器添加实例查找失败后的等待重试机制，
        以及权限冲突时的强制进程清理。
        """
        logger.hr('模拟器启动', level=1)

        # 检查是否为 MuMuPlayer12，添加实例查找失败的处理逻辑
        emulator_type = getattr(self.config, 'EmulatorInfo_Emulator', '')
        is_mumu12 = emulator_type == 'MuMuPlayer12' or (
            hasattr(self, '_emulator_instance') and
            self._emulator_instance and
            self._emulator_instance.type == 'MuMuPlayer12'
        )

        for attempt in range(3):
            # 先停止（MuMu12 已使用同步执行确保关闭完成）
            if not self._emulator_function_wrapper(self._emulator_stop):
                return False

            # MuMu12: 等待一小段时间确保进程状态稳定
            if is_mumu12:
                import time
                # 检测是否有残留进程导致权限冲突
                # 权限冲突通常由 MuMuManager/MuMuPlayer 僵死进程引起
                has_mumu_process = False
                for proc in psutil.process_iter(['name', 'cmdline']):
                    try:
                        name = proc.info['name'] or ''
                        if name.lower() in ('mumuplayer.exe', 'mumumanager.exe',
                                            'nemuplayer.exe', 'nemuheadless.exe'):
                            has_mumu_process = True
                            logger.warning(f'[设备-Windows] 检测到MuMu残留进程: {name} (PID={proc.pid})')
                            proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                if has_mumu_process:
                    logger.info('[设备-Windows] MuMuPlayer12: 已终止残留进程，等待5秒')
                    time.sleep(5)
                else:
                    logger.info('[设备-Windows] MuMuPlayer12: 等待2秒让进程状态稳定')
                    time.sleep(2)

            # 再启动
            if self._emulator_function_wrapper(self._emulator_start):
                # 成功
                if self.emulator_start_watch():
                    return True
                logger.warning('[设备-Windows] 模拟器启动监视失败，重试中')
                if self._emulator_function_wrapper(self._emulator_stop):
                    continue
                else:
                    return False
            else:
                # 启动失败，停止后重试
                if self._emulator_function_wrapper(self._emulator_stop):
                    continue
                else:
                    return False

        logger.error('[设备-Windows] 尝试3次启动模拟器失败，已停止')
        return False

    def emulator_stop(self):
        """停止模拟器，最多重试 3 次。"""
        logger.hr('模拟器停止', level=1)
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

        logger.error('[设备-Windows] 尝试3次停止模拟器失败，已停止')
        return False


if __name__ == '__main__':
    self = PlatformWindows('alas')
    d = self.emulator_instance
    print(d)
