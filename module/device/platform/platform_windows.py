"""Windows 平台模拟器控制。继承 PlatformBase 和 EmulatorManager，
实现 Windows 上模拟器的启动、窗口聚焦和进程管理。"""

from __future__ import annotations
import ctypes
import json
import os
import re
import subprocess
import threading
import time
from functools import wraps
from ctypes import wintypes

import psutil

from deploy.Windows.utils import DataProcessInfo
from module.base.decorator import run_once
from module.base.runtime_params import (
    EMULATOR_START_DIALOG_CHECK_INTERVAL,
    EMULATOR_START_PROGRESS_INTERVAL,
    MUMU12_DEEP_WAIT_TIMEOUT,
    MUMU12_STATE_POLL_INTERVAL,
    MUMU12_STOP_WAIT_TIMEOUT,
)
from module.base.timer import Timer
from module.config.utils import read_run_param
from module.device.connection_attr import ConnectionAttr
from module.device.platform.platform_base import PlatformBase
from module.device.platform.emulator_windows import Emulator, EmulatorInstance, EmulatorManager
from module.exception import EmulatorOpBusy
from module.logger import logger


class EmulatorUnknown(Exception):
    """未知模拟器类型异常。"""
    pass


# 模拟器启动监视的等待时长（秒），按「本次尝试之前已连续失败几次」取值：
#   第 1 次尝试 60 秒 → 连续失败后 90 → 120 → 180 → 300（上限）
# 实机实测正常冷启动约 16~30 秒，60 秒对好设备够用；持续起不来时才逐级放宽。
# 注意：实测也出现过「第一次等满 180 秒没上线、重来一次 14 秒就起来」的情况，
# 所以缩短首轮会多付一次「关掉重来」的代价——这是拿响应速度换的，可以接受。
EMULATOR_START_WATCH_TIMEOUTS = (60, 90, 120, 180, 300)
# 启动监视间隔常量集中在 module/base/runtime_params.py（设备域），
# 可调参数走 WebUI「运行参数」页（RunParams.Device）。

# MuMu12 启动前需要清理的僵死进程名（小写）。
# MuMuNxMain.exe 是 nx_main 新版布局的启动器主窗口：它卡在加载态时不清理掉，
# 后面的 launch_player 只会把启动请求交给这个僵死的启动器，表现为
# "窗口一直转圈、模拟器起不来"。
MUMU12_RESIDUE_PROCESS_NAMES = (
    'mumuplayer.exe', 'mumunxmain.exe', 'mumumanager.exe',
    'nemuplayer.exe', 'nemuheadless.exe',
)

# 深度重启时结束的全部 MuMu 进程名（小写）。
# 定位：设备较差时「连续重启都起不来」的最后一招，把实例、后台服务、虚拟机
# 进程全部结束，让 MuMu 从零开始。用进程名而不是安装目录路径匹配——实测
# MuMuVMMHeadless.exe / MuMuVMMSVC.exe 并不在 MuMu 安装目录下，按路径抓不到。
MUMU12_DEEP_PROCESS_NAMES = (
    'mumuplayer.exe', 'mumunxmain.exe', 'mumumultiplayer.exe', 'mumumanager.exe',
    'mumuplayerservice.exe', 'mumuvmmheadless.exe', 'mumuvmmsvc.exe',
    'nemuplayer.exe', 'nemuheadless.exe',
)


def run_mumu_manager(exe, args, timeout=15):
    """执行 MuMuManager 命令并返回其标准输出。

    与 PlatformWindows.execute 的区别：这里需要读取命令输出（如 info 返回的
    JSON），而且会被轮询高频调用，因此不写日志以免刷屏。

    Args:
        exe (str): MuMu 主程序路径，会被转换成同目录的 MuMuManager.exe。
        args (str): MuMuManager 子命令，如 'info -v all'。
        timeout (int): 超时秒数。

    Returns:
        str: 命令的标准输出；执行失败返回空字符串。
    """
    manager = Emulator.single_to_console(exe).replace('\\', '/')
    command = f'"{manager}" {args}'
    try:
        result = subprocess.run(
            command,
            shell=True,
            timeout=timeout,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
        )
    except subprocess.TimeoutExpired:
        logger.warning(f'[设备-Windows] MuMuManager 命令超时 {timeout} 秒: {command}')
        return ''
    except OSError as e:
        logger.warning(f'[设备-Windows] MuMuManager 命令执行失败: {command} ({e})')
        return ''
    return result.stdout or ''


def emulator_op_exclusive(name):
    """装饰器：保证同一时刻只有一个模拟器启停操作真正作用于模拟器。

    emulator_stop / emulator_start 不只是发命令，它们会真的关闭并重启模拟器
    （关窗口、杀进程、反复重试）。两个操作并发执行时必然互相踩踏：一个线程
    刚发出启动命令，另一个线程随即 shutdown，模拟器在冷启动完成前被反复
    打断，表现为"窗口一直卡在加载、永远起不来"。
    拿不到锁的一方直接抛 EmulatorOpBusy，由调用方跳过本轮。

    注意：锁必须覆盖操作的**全过程**（含内部 3 次重试与最长数分钟的启动
    监视），而不是只包住发命令那一下——否则超时后被放弃的调用线程仍会
    继续关/开模拟器，踩踏依旧。

    Args:
        name (str): 操作名称，用于日志与异常信息。

    Raises:
        EmulatorOpBusy: 已有启停操作在进行，本次被跳过。
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self._emulator_op_lock.acquire(blocking=False):
                logger.warning(f'[设备-Windows] 已有模拟器启停操作正在进行，跳过本次{name}')
                raise EmulatorOpBusy(f'{name}: 另一个模拟器启停操作正在进行')
            try:
                return func(self, *args, **kwargs)
            finally:
                self._emulator_op_lock.release()
        return wrapper
    return decorator


def get_focused_window():
    """获取当前前台窗口的句柄。"""
    get_foreground_window = ctypes.windll.user32.GetForegroundWindow
    get_foreground_window.restype = wintypes.HWND
    return get_foreground_window() or 0


def set_focus_window(hwnd):
    """将指定窗口设置为前台窗口。"""
    ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))


def get_window_process_id(hwnd):
    """获取窗口所属进程；窗口已销毁时返回 0。"""
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def get_process_window(pid):
    """按进程定位唯一可见主窗口，多个候选窗口时不猜测目标。"""
    if pid <= 0:
        return 0

    user32 = ctypes.windll.user32
    user32.GetWindow.restype = wintypes.HWND
    windows = []

    def enum_callback(hwnd, _):
        handle = wintypes.HWND(hwnd)
        if (user32.IsWindowVisible(handle)
                and not user32.GetWindow(handle, 4)  # GW_OWNER，排除附属弹窗。
                and get_window_process_id(hwnd) == pid):
            windows.append(hwnd)
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_callback)
    if not user32.EnumWindows(callback, 0):
        return 0
    return windows[0] if len(windows) == 1 else 0


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
    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 6)


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
    ctypes.windll.user32.FlashWindow(wintypes.HWND(hwnd), flash)


class PlatformWindows(PlatformBase, EmulatorManager):
    """Windows 平台的模拟器控制接口。"""

    # 进程内模拟器启停互斥锁，见 emulator_op_exclusive。
    # 类属性：alas.py 每轮恢复都会新建 Platform 实例，甚至绕过 Platform
    # 直接调用 Device.emulator_start()，只有挂在类上才能让所有调用方共享
    # 同一把锁。WebUI / MCP 等独立进程各有一把，互不影响。
    _emulator_op_lock = threading.Lock()

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
            # 短命 cmd 断开进程树关系；启动器的 Job 归属需要另外显式脱离。
            # 仅在启动器声明允许时请求 breakaway，旧 Job 不允许此标志会拒绝启动。
            creationflags = subprocess.CREATE_NO_WINDOW
            if os.environ.get('ALAS_LAUNCHER_JOB_BREAKAWAY') == '1':
                creationflags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
            # 模拟器不是 ALAS worker，不能继承退出清理标记或 WebUI 信任密钥。
            environment = {
                key: value for key, value in os.environ.items()
                if key.upper() not in {
                    'ALAS_LAUNCHER_PID', 'ALAS_LAUNCHER_JOB_BREAKAWAY', 'ALAS_WEBUI_TRUST_SECRET',
                }
            }
            proc = subprocess.Popen(
                f'start "" /b {command}',
                shell=True,
                close_fds=True,
                creationflags=creationflags,
                env=environment,
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
            # 通过 MuMuManager 启动而非 MuMuPlayer.exe/MuMuNxMain.exe
            # MuMuNxMain.exe 为 GUI 单例，若同时启动两个实例，第二个启动请求会被转发到正在初始化的 MuMuNxMain.exe 并被静默丢弃
            # 而 MuMuManager 会在后台服务中排队处理请求
            if instance.MuMuPlayer12_id is None:
                logger.warning(f'[设备-Windows] 无法从名称 {instance.name} 获取MuMu实例索引')
            self.execute(f'"{Emulator.single_to_console(exe)}" api -v {instance.MuMuPlayer12_id} launch_player')
        elif instance == Emulator.LDPlayer14 or instance == Emulator.LDPlayer9:
            # ldconsole.exe launch --index 0 --mini
            # 雷电9及以上版本支持 `--mini` 启动为最小化窗口，`--hide` 启动为无前端窗口
            self.execute(f'"{Emulator.single_to_console(exe)}" launch --index {instance.LDPlayer_id} --mini')
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

    def _mumu12_instances(self, exe):
        """查询 MuMu12 全部实例的信息。

        MuMuManager 的 info 子命令返回 JSON，字段包括 is_process_started、
        is_android_started、player_state、pid、headless_pid 等，用于按实例
        精确判断状态，而不是靠进程名猜测。

        Args:
            exe (str): MuMu 主程序路径。

        Returns:
            dict | None: {实例号: 信息}；命令不可用或输出无法解析时返回 None
                （旧版 MuMu 没有 info 子命令，调用方需回退旧逻辑）。
        """
        text = run_mumu_manager(exe, 'info -v all')
        start = text.find('{')
        if start < 0:
            return None
        try:
            data = json.loads(text[start:])
        except ValueError:
            logger.warning(f'[设备-Windows] 无法解析 MuMuManager info 输出: {text[:200]}')
            return None
        if not isinstance(data, dict):
            return None
        # 兼容 info -v <单个实例> 的返回形式（实例字段直接铺在顶层）
        if 'index' in data:
            return {str(data['index']): data}
        return data

    def _mumu12_other_instance_running(self, exe, index):
        """判断除本实例外是否还有其他 MuMu 实例正在运行。

        多开时各实例共用启动器、后台服务等进程，按进程名清理会误伤正在
        运行的其它实例，因此只有确认没有别的实例在跑时才允许这么做。

        Args:
            exe (str): MuMu 主程序路径。
            index (int | None): 本实例的实例号。

        Returns:
            bool | None: True/False 为判定结果；None 表示无法判定（查询失败）。
        """
        info = self._mumu12_instances(exe)
        if info is None:
            return None
        for key, entry in info.items():
            if str(key) == str(index):
                continue
            if isinstance(entry, dict) and entry.get('is_process_started'):
                return True
        return False

    def _clean_mumu12_residue(self, exe, index):
        """清理 MuMu12 的僵死进程，为重新启动做准备。

        多开安全：MuMu 各实例共用启动器与后台服务进程，按进程名清理会误伤
        正在运行的其它实例。因此先查询实例状态，只有确认没有别的实例在跑
        时才按名字清理；无法判定时同样不清理——宁可少清理，不可误杀。

        Args:
            exe (str): MuMu 主程序路径。
            index (int | None): 本实例的实例号。
        """
        others = self._mumu12_other_instance_running(exe, index)
        if others is None:
            logger.info('[设备-Windows] 无法确认其它 MuMu 实例状态，跳过按进程名清理')
            return
        if others:
            logger.info(
                '[设备-Windows] 检测到其它 MuMu 实例正在运行，'
                '跳过按进程名清理（避免误伤多开）'
            )
            return

        has_mumu_process = False
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                name = proc.info['name'] or ''
                if name.lower() in MUMU12_RESIDUE_PROCESS_NAMES:
                    has_mumu_process = True
                    logger.warning(f'[设备-Windows] 检测到MuMu残留进程: {name} (PID={proc.pid})')
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if has_mumu_process:
            # 不在这里固定 sleep：调用方紧接着会用 _mumu12_wait_stopped
            # 轮询确认实例真的没了，比盲等更准也更快
            logger.info('[设备-Windows] MuMuPlayer12: 已终止残留进程，等待实例释放')

    @staticmethod
    def _mumu_deep_processes_alive():
        """检查深度重启名单里是否还有 MuMu 进程存活。"""
        for proc in psutil.process_iter(['name']):
            try:
                if (proc.info['name'] or '').lower() in MUMU12_DEEP_PROCESS_NAMES:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    def _deep_clean_mumu12(self, exe):
        """深度重启：结束 MuMu 的全部进程，让 MuMu 从零开始。

        与 _clean_mumu12_residue 的区别：

        1. 不检查多开——用户显式开启深度重启，即表示接受「其它实例会被一并
           中断」，日志会写清楚结束掉了什么，便于事后确认发生了什么；
        2. 覆盖后台服务与虚拟机进程，而不只是实例进程。

        只有「连续重启都起不来」时才会走到这里，属于最后一招逃生口。实测全杀
        之后 MuMuManager 仍能正常拉起实例（16 秒就绪），服务会自动重新启动。

        Args:
            exe (str): MuMu 主程序路径。

        Returns:
            bool: True 表示名单里的 MuMu 进程都已退出。
        """
        # 先礼貌关闭全部实例，让 MuMu 自己释放一遍再动手。
        # 这一步失败（MuMuManager 不可用等）不影响后续按进程名清理，
        # 深度重启本身是最后手段，不能因为它的一部分失败就把恢复流程打断。
        manager = Emulator.single_to_console(exe).replace('\\', '/')
        try:
            self.execute(f'"{manager}" control -v all shutdown', wait=True, timeout=60)
        except Exception as e:
            logger.warning(f'[设备-Windows] 深度重启：关闭全部实例失败，继续清理进程: {e}')

        killed = 0
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info['name'] or ''
                if name.lower() in MUMU12_DEEP_PROCESS_NAMES:
                    logger.warning(f'[设备-Windows] 深度重启：结束进程 {name} (PID={proc.pid})')
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        logger.info(f'[设备-Windows] 深度重启：已结束 MuMu 全部进程（{killed} 个）')

        deep_wait = read_run_param(
            self.config, 'Device_Mumu12DeepWaitTimeout', MUMU12_DEEP_WAIT_TIMEOUT, 10, 120)
        deadline = time.monotonic() + deep_wait
        while time.monotonic() < deadline:
            if not self._mumu_deep_processes_alive():
                logger.info('[设备-Windows] 深度重启：MuMu 进程已全部退出')
                return True
            time.sleep(1)
        logger.warning(
            f'[设备-Windows] 深度重启：仍有 MuMu 进程未退出'
            f'（已等 {deep_wait} 秒，继续启动流程）'
        )
        return False

    def _mumu12_wait_stopped(self, exe, index):
        """等待 MuMu12 实例真正关闭后再返回。

        MuMuManager 的 shutdown 是异步的：命令 1 秒内就返回，实例还要 2~3 秒
        才真正停止。若在此期间发出 launch，启动请求会被吞掉——命令报告成功
        （player launch: result=0），实例却永远起不来。
        实机复现：shutdown 后等 2 秒启动必失败，等确认关闭后启动 17 秒成功。

        Args:
            exe (str): MuMu 主程序路径。
            index (int | None): 本实例的实例号。

        Returns:
            bool: True 表示已确认关闭（或无法查询状态，调用方按旧逻辑继续）；
                False 表示等待超时，实例仍未关闭。
        """
        if index is None:
            return True
        stop_wait = read_run_param(
            self.config, 'Device_Mumu12StopWaitTimeout', MUMU12_STOP_WAIT_TIMEOUT, 10, 300)
        poll_interval = read_run_param(
            self.config, 'Device_Mumu12StatePollInterval', MUMU12_STATE_POLL_INTERVAL, 1, 30)
        deadline = time.monotonic() + stop_wait
        while 1:
            info = self._mumu12_instances(exe)
            if info is None:
                # 查询不可用（旧版 MuMu / 命令失败）：保持旧行为，短暂等待即可
                time.sleep(poll_interval)
                return True
            entry = info.get(str(index))
            if not isinstance(entry, dict) or not entry.get('is_process_started'):
                logger.info(f'[设备-Windows] MuMuPlayer12 实例 {index} 已确认关闭')
                return True
            if time.monotonic() >= deadline:
                logger.warning(
                    f'[设备-Windows] MuMuPlayer12 实例 {index} 在 '
                    f'{stop_wait} 秒内仍未关闭，继续启动流程'
                )
                return False
            time.sleep(poll_interval)

    def _get_emulator_window(self):
        """定位当前实例的窗口；查询失败或归属不明确时跳过窗口操作。"""
        instance = self.emulator_instance
        exe = instance.emulator.path
        if instance == Emulator.MuMuPlayer12:
            info = self._mumu12_instances(exe)
            entry = (info or {}).get(str(instance.MuMuPlayer12_id))
            if not isinstance(entry, dict) or not entry.get('is_process_started'):
                return 0
            try:
                pid = int(entry.get('pid', 0))
            except (TypeError, ValueError):
                return 0
            # 新版 GUI 可能由多个实例共享，不能把共享进程当作某个实例。
            if any(other is not entry and isinstance(other, dict)
                   and other.get('is_process_started') and str(other.get('pid')) == str(pid)
                   for other in info.values()):
                return 0
            return get_process_window(pid)

        if instance == Emulator.LDPlayerFamily:
            try:
                result = subprocess.run(
                    [Emulator.single_to_console(exe), 'list2'],
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    capture_output=True,
                    text=True,
                    errors='replace',
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.warning(f'[设备-Windows] 无法查询雷电实例窗口: {e}')
                return 0
            if result.returncode:
                return 0
            for line in result.stdout.splitlines():
                fields = line.split(',')
                if len(fields) < 7 or fields[0] != str(instance.LDPlayer_id):
                    continue
                try:
                    hwnd, pid = int(fields[2]), int(fields[5])
                except ValueError:
                    return 0
                if (hwnd > 0 and pid > 0 and get_window_process_id(hwnd) == pid
                        and ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd))):
                    return hwnd
            return 0

        if instance == Emulator.MuMuPlayer:
            marker = []  # MuMu6 只有单实例。
        elif instance == Emulator.MuMuPlayerX:
            marker = ['-m', instance.name]
        elif instance == Emulator.NoxPlayerFamily:
            marker = [f'-clone:{instance.name}']
        elif instance == Emulator.BlueStacks5:
            marker = ['--instance', instance.name]
        elif instance == Emulator.BlueStacks4:
            marker = ['-vmname', instance.name]
        elif instance == Emulator.MEmuPlayer:
            marker = [instance.name]
        else:
            return 0

        path = os.path.normcase(os.path.abspath(exe))
        pids = []
        for proc in psutil.process_iter(['exe', 'cmdline']):
            try:
                process_exe = proc.info['exe']
                if not process_exe or os.path.normcase(os.path.abspath(process_exe)) != path:
                    continue
                args = (proc.info['cmdline'] or [])[1:]
                if not marker or any(args[i:i + len(marker)] == marker for i in range(len(args))):
                    pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return get_process_window(pids[0]) if len(pids) == 1 else 0

    def emulator_start_watch(self, timeout=None):
        """
        监控模拟器启动过程，等待启动完成。

        Args:
            timeout (int | float | None): 本次监视的等待秒数。
                默认取 EMULATOR_START_WATCH_TIMEOUTS 的首项（首次尝试）。

        Returns:
            bool: True 表示启动完成，False 表示超时
        """
        if timeout is None:
            timeout = EMULATOR_START_WATCH_TIMEOUTS[0]
        logger.hr('模拟器启动', level=2)
        logger.info(f'[设备-Windows] 模拟器启动监视开始，最长等待 {timeout} 秒')
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
        timeout_timer = Timer(timeout).start()
        progress = Timer(read_run_param(
            self.config, 'Device_EmulatorStartProgressInterval',
            EMULATOR_START_PROGRESS_INTERVAL, 10, 300)).start()
        dialog_check = Timer(read_run_param(
            self.config, 'Device_EmulatorStartDialogCheckInterval',
            EMULATOR_START_DIALOG_CHECK_INTERVAL, 1, 30)).start()
        while 1:
            interval.wait()
            interval.reset()
            if timeout_timer.reached():
                logger.warning(
                    f'[设备-Windows] 模拟器启动超时'
                    f'（已等待 {round(timeout_timer.current_time())} 秒）'
                )
                return False

            # 定期打印进度：启动过程可能静默数分钟，需要让日志体现
            # "确实还在等"，否则看起来像卡死
            if progress.reached_and_reset():
                logger.info(
                    f'[设备-Windows] 等待模拟器启动中，'
                    f'已等待 {round(timeout_timer.current_time())}/{timeout} 秒'
                )

            # MuMu 权限冲突等错误对话框检测
            # 检测到错误对话框时立即终止等待，返回 False 触发重试，
            # 不必白白等满整个监视超时
            if dialog_check.reached_and_reset() and check_mumu_error_dialog():
                logger.warning('[设备-Windows] 检测到MuMu错误对话框，中止启动监视')
                return False

            try:
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

        # 按实例重新定位窗口，不把用户启动期间切换到的应用当作模拟器。
        new_window = self._get_emulator_window()
        if new_window:
            if current_window and current_window != new_window and get_focused_window() == new_window:
                logger.info(f'[设备-Windows] 模拟器窗口获得焦点，返回原窗口: {current_window}')
                set_focus_window(current_window)
            logger.info(f'[设备-Windows] 最小化模拟器窗口: {new_window}')
            minimize_window(new_window)
            logger.info(f'[设备-Windows] 闪烁新窗口: {new_window}')
            flash_window(new_window, flash=True)
        else:
            logger.info('[设备-Windows] 未能确认本实例窗口，跳过最小化')
        logger.info('[设备-Windows] 模拟器启动完成')
        return True

    @emulator_op_exclusive('启动模拟器')
    def emulator_start(self, deep=False, failures=0):
        """
        启动模拟器，尝试一次。

        不在一次调用里连试多次：重试交给调用方按调度轮次进行，等待时间随之
        逐级放宽。好设备通常 60 秒内就能起来，没必要一上来就等几分钟；持续
        起不来时才靠 EMULATOR_START_WATCH_TIMEOUTS 逐级加长。

        整个启停过程持有模拟器启停锁（见 emulator_op_exclusive）：
        若已有启停操作在跑，直接抛 EmulatorOpBusy，不做任何动作——
        这正是避免"刚启动就被另一个线程关掉"的关键。

        Args:
            deep (bool): 是否执行深度重启（结束 MuMu 全部进程，含后台服务与
                虚拟机）。仅由调用方在「连续重启都失败」时置为 True；
                非 MuMu12 平台忽略此参数。
            failures (int): 本次尝试之前已经连续失败过几次，用来选取启动
                监视的等待时长；非 MuMu12 平台忽略。

        Returns:
            bool: True 表示模拟器已上线。
        """
        logger.hr('模拟器启动', level=1)

        watch_timeout = EMULATOR_START_WATCH_TIMEOUTS[
            min(max(failures, 0), len(EMULATOR_START_WATCH_TIMEOUTS) - 1)
        ]

        # 检查是否为 MuMuPlayer12，添加实例查找失败的处理逻辑
        emulator_type = getattr(self.config, 'EmulatorInfo_Emulator', '')
        is_mumu12 = emulator_type == 'MuMuPlayer12' or (
            hasattr(self, '_emulator_instance') and
            self._emulator_instance and
            self._emulator_instance.type == 'MuMuPlayer12'
        )

        # 先停止（MuMu12 已使用同步执行确保关闭完成）
        if not self._emulator_function_wrapper(self._emulator_stop):
            return False

        # MuMu12: 清场并确认实例真的停下来了再启动
        if is_mumu12:
            index = self.emulator_instance.MuMuPlayer12_id
            exe = self.emulator_instance.emulator.path
            if deep:
                # 深度重启：结束 MuMu 全部进程（不检查多开）
                self._deep_clean_mumu12(exe)
            else:
                # 清理僵死的启动器/播放器进程（多开时自动跳过，见方法注释）
                self._clean_mumu12_residue(exe, index)
            # shutdown 是异步的，必须确认实例真的停了再启动，
            # 否则启动请求会被吞掉（命令报成功、实例起不来）
            self._mumu12_wait_stopped(exe, index)

        # 再启动
        if not self._emulator_function_wrapper(self._emulator_start):
            logger.error('[设备-Windows] 启动模拟器命令失败')
            return False

        if self.emulator_start_watch(timeout=watch_timeout):
            return True

        logger.warning(
            f'[设备-Windows] 模拟器启动监视失败（已等待 {watch_timeout} 秒）。'
            f'本轮不再重试，交给调度器下一轮带着更长的等待时间重来'
        )
        return False

    @emulator_op_exclusive('停止模拟器')
    def emulator_stop(self):
        """停止模拟器，最多重试 3 次。

        同样持有模拟器启停锁：不做"别人正在启动、我顺手关掉"的事。
        """
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
