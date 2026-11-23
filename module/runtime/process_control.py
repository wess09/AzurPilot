"""按进程身份终止子树；只有 multiprocessing 句柄负责回收自己的子进程。"""

import math
import os
import subprocess
import time
from pathlib import Path

PROCFS_PATH = Path("/proc")


def _warn(message: str):
    """记录警告日志。

    身份查询也供启动早期的登记模块使用，避免导入时初始化完整日志器。

    Args:
        message: 警告信息。
    """
    from module.logger import logger

    logger.warning(message)


def _proc_start_ticks(pid: int) -> int:
    """读取 Linux /proc/<pid>/stat 的启动时钟 tick。

    Android 的应用沙箱可能允许读取同 UID 进程的 stat，却拒绝全局
    /proc/stat。psutil.create_time() 依赖后者，所以用负的启动 tick 作为
    同一次开机内的稳定身份；负值也不会与 Unix 时间戳混淆。

    Args:
        pid: 进程 PID。

    Returns:
        int: 启动时钟 tick 数。

    Raises:
        ValueError: stat 内容异常或字段不足。
    """
    raw = (PROCFS_PATH / str(pid) / "stat").read_text(encoding="ascii")
    # comm 字段位于括号中且自身可含空格或右括号，从最后一个右括号切分。
    closing = raw.rfind(")")
    if closing < 0:
        raise ValueError("/proc stat 缺少进程名结束符")
    fields = raw[closing + 1 :].split()
    # fields[0] 是原始 stat 的第 3 字段 state；starttime 是第 22 字段。
    if len(fields) <= 19:
        raise ValueError("/proc stat 字段不足")
    start_ticks = int(fields[19])
    if start_ticks < 0:
        raise ValueError("/proc stat 启动时间无效")
    return start_ticks


def process_identity(pid: int) -> str | None:
    """读取 Linux 开机 ID 和进程启动刻度，避免校时改变进程身份。"""
    boot_id_file = PROCFS_PATH / "sys/kernel/random/boot_id"
    if os.name != "posix":
        return None
    try:
        boot_id = boot_id_file.read_text(encoding="ascii").strip()
    except (FileNotFoundError, PermissionError):
        # 非 Linux 系统或受限的 Android 沙箱继续使用现有身份机制。
        return None
    try:
        return f"{boot_id}:{_proc_start_ticks(pid)}"
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"无法读取进程 PID {pid} 的启动标识: {exc}") from exc


def process_created_at(pid: int, process=None) -> float:
    """返回可持久化的进程身份时间戳，兼容 Android 对 /proc/stat 的限制。

    Args:
        pid: 目标进程 PID。
        process: 可选的已有 psutil.Process 实例。

    Returns:
        float: 进程创建时间戳（Android 下可能为负的 tick 数）。

    Raises:
        RuntimeError: 缺少依赖或无法读取进程身份。
    """
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("缺少 psutil，无法读取进程身份") from exc
    try:
        if process is None:
            process = psutil.Process(pid)
        return process.create_time()
    except psutil.NoSuchProcess:
        raise
    except (psutil.AccessDenied, PermissionError):
        try:
            return -float(_proc_start_ticks(pid))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"无法读取进程 PID {pid} 的 Android /proc 身份: {exc}") from exc


def process_matches(record: dict) -> bool | None:
    """验证记录的进程身份是否匹配当前运行进程。

    同一活进程返回 True，PID 被操作系统复用返回 False，消失或僵尸进程返回 None。
    不调用 wait()/wait_procs()，避免抢走 multiprocessing 的 waitpid 结果。
    无法读取身份时抛出异常，调用方不能把权限拒绝或缺少依赖当成退出。

    Args:
        record: 包含 pid 与 created_at 的进程身份记录字典。

    Returns:
        bool | None: 匹配存活返回 True，PID 已复用返回 False，进程已不存在返回 None。

    Raises:
        RuntimeError: 记录无效或无法验证身份。
    """
    try:
        pid = int(record["pid"])
        created_at = float(record["created_at"])
        if pid <= 0 or not math.isfinite(created_at):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("进程身份记录无效") from exc
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("缺少 psutil，无法验证进程身份") from exc
    try:
        process = psutil.Process(pid)
        identity = record.get("identity")
        if identity is not None:
            if not isinstance(identity, str):
                raise RuntimeError("进程启动标识无效")
            actual_identity = process_identity(pid)
            if actual_identity is None:
                raise RuntimeError(f"无法读取进程 PID {pid} 的启动标识")
            if actual_identity != identity:
                return False
        elif abs(process_created_at(pid, process) - created_at) >= 0.01:
            return False
        if process.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
            return None
        return True
    except (psutil.NoSuchProcess, FileNotFoundError):
        return None
    except (psutil.Error, OSError) as exc:
        raise RuntimeError(f"无法验证进程 PID {pid}: {exc}") from exc


def pid_exists(pid: int) -> bool:
    """检测指定 PID 是否存在于系统中。

    仅供缺少身份记录的旧登记判断消失；该结果不能单独授权执行终止操作。

    Args:
        pid: 进程 PID。

    Returns:
        bool: PID 存在返回 True，不存在返回 False。
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def is_process_alive(process) -> bool:
    """通过本地句柄查询进程存活状态，由 multiprocessing 自己执行非阻塞回收。

    Args:
        process: multiprocessing.Process 或包含 is_alive() 的句柄。

    Returns:
        bool: 存活返回 True，否则返回 False。
    """
    if process is None:
        return False
    try:
        return process.is_alive()
    except (ValueError, AssertionError):
        return False
    except OSError:
        return True


def _may_signal(record: dict | None) -> bool:
    """检查是否允许向目标进程记录发送控制信号。

    Args:
        record: 进程身份记录字典。

    Returns:
        bool: 允许发送信号返回 True。

    Raises:
        RuntimeError: PID 已被复用时抛出异常以阻止向无关进程发信号。
    """
    if record is None:
        return True
    matches = process_matches(record)
    if matches is False:
        raise RuntimeError(f"PID {record['pid']} 已复用，拒绝终止未知进程")
    return matches is True


def stop_process(process, timeout: float = 5, kill_timeout: float = 3, record: dict = None) -> bool:
    """通过本地句柄逐级 terminate/kill，并保留其退出码与 join 语义。

    Args:
        process: multiprocessing 进程句柄。
        timeout: terminate 后的等待超时时间（秒）。
        kill_timeout: kill 后的等待超时时间（秒）。
        record: 可选的身份校验记录。

    Returns:
        bool: 进程已停止返回 True，未能停止返回 False。
    """
    if process is None:
        return True
    try:
        for method, wait in (("terminate", timeout), ("kill", kill_timeout)):
            if not is_process_alive(process):
                try:
                    process.join(timeout=0)
                except (ValueError, AssertionError):
                    # 已 close 或从未 start 的句柄没有可回收的子进程。
                    pass
                return True
            if _may_signal(record):
                try:
                    getattr(process, method)()
                except OSError as exc:
                    _warn(f"进程 {process.pid} 的 {method} 失败: {exc}")
            process.join(timeout=wait)
        return not is_process_alive(process)
    except (OSError, ValueError, AssertionError, RuntimeError) as exc:
        _warn(f"无法确认本地进程已停止: {exc}")
        return False


def _kill_record(record: dict) -> bool:
    """每次发送信号前重新验证创建时间，单个子进程消失不跳过其余子树。

    Args:
        record: 子进程身份记录字典。

    Returns:
        bool: 操作成功返回 True，失败返回 False。
    """
    try:
        import psutil

        process = psutil.Process(record["pid"])
        if not _may_signal(record):
            return True
        if record.get("identity") is None and abs(
            process_created_at(record["pid"], process) - record["created_at"]
        ) >= 0.01:
            return False
        # 负身份表示 Android /proc 启动 tick；此时 psutil.kill() 会再次调用
        # 依赖 /proc/stat 的 create_time()，改为在已验证身份后直接发信号。
        if record["created_at"] < 0 and os.name != "nt":
            import signal

            os.kill(record["pid"], signal.SIGKILL)
        else:
            process.kill()
        return True
    except ImportError:
        return False
    except psutil.NoSuchProcess:
        return True
    except (psutil.Error, RuntimeError) as exc:
        _warn(f"无法终止进程 {record['pid']}: {exc}")
        return False


def _kill_root(record: dict) -> bool:
    """终止进程树的根进程。

    Args:
        record: 根进程身份记录。

    Returns:
        bool: 发起终止成功返回 True，失败返回 False。
    """
    if os.name != "nt":
        return _kill_record(record)
    try:
        if not _may_signal(record):
            return True
        result = subprocess.run(
            ["taskkill", "/PID", str(record["pid"]), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=5,
        )
        # taskkill 返回非零也可能是进程刚退出，由后面的身份轮询作最终确认。
        if result.returncode:
            _warn(f"taskkill 返回 {result.returncode}: PID {record['pid']}")
        return True
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        _warn(f"终止进程树失败: {exc}")
        return False


def wait_process_records(records: list[dict], timeout: float = 3) -> bool:
    """轮询检测一组进程身份记录是否均已完全退出。

    只轮询身份和运行状态，僵尸进程交给各自父进程回收。

    Args:
        records: 进程记录列表。
        timeout: 等待超时时间（秒）。

    Returns:
        bool: 均已退出返回 True，超时或发生异常返回 False。
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            states = [process_matches(record) for record in records]
        except RuntimeError as exc:
            _warn(f"无法确认进程树已退出: {exc}")
            return False
        if all(state is None for state in states):
            return True
        if any(state is False for state in states):
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.1, remaining))


def stop_process_tree(process=None, *, record: dict = None, name: str = "进程",
                      timeout: float = 5, kill_timeout: float = 3) -> bool:
    """先记录并终止后代，再停止根进程，确认所有已记录成员均已退出。

    本地句柄支持有界的优雅停止和强制升级；无句柄时必须提供持久化身份。
    枚举失败时保持登记以便重试，不退回仅凭 PID 的盲目终止。

    Args:
        process: 可选的本地进程句柄。
        record: 可选的根进程身份记录字典。
        name: 日志输出使用的友好进程标识名称。
        timeout: 优雅终止等待时间（秒）。
        kill_timeout: 强制终止等待时间（秒）。

    Returns:
        bool: 进程树全部退出返回 True，否则返回 False。
    """
    if process is None and record is None:
        return True
    if record is None and not is_process_alive(process):
        return stop_process(process, timeout=0)
    try:
        import psutil
    except ImportError:
        _warn(f"缺少 psutil，无法确认{name}进程树")
        return False
    try:
        if record is None:
            parent = psutil.Process(process.pid)
            record = {"pid": parent.pid, "created_at": process_created_at(parent.pid, parent)}
            if not is_process_alive(process):
                return stop_process(process, timeout=0)
        else:
            if process is not None and process.pid != record["pid"]:
                return False
            parent = psutil.Process(record["pid"])
            if not _may_signal(record):
                if process is not None:
                    return stop_process(process, timeout=0, record=record)
                return True
        # 已验证的 Linux 启动标识不受系统校时影响，不再比较墙钟时间。
        if record.get("identity") is None and abs(
            process_created_at(parent.pid, parent) - record["created_at"]
        ) >= 0.01:
            return False
        children = []
        for child in parent.children(recursive=True):
            try:
                children.append({"pid": child.pid, "created_at": process_created_at(child.pid, child)})
            except psutil.NoSuchProcess:
                continue
    except psutil.NoSuchProcess:
        stopped = stop_process(process, timeout=0, record=record) if process is not None else True
        exited = wait_process_records([record], timeout=kill_timeout) if record else True
        return stopped and exited
    except (psutil.Error, RuntimeError, KeyError, TypeError, ValueError) as exc:
        _warn(f"无法确认{name}进程树身份: {exc}")
        return False

    stopped = True
    for child_record in reversed(children):
        stopped = _kill_record(child_record) and stopped
    # 后代未确认退出时保留根进程及亲子关系，后续仍能按根登记重新枚举。
    if not stopped or not wait_process_records(children, timeout=kill_timeout):
        return False
    if process is not None:
        root_stopped = stop_process(process, timeout=timeout, kill_timeout=kill_timeout, record=record)
        if not root_stopped:
            root_stopped = _kill_root(record)
            try:
                process.join(timeout=kill_timeout)
                root_stopped = not is_process_alive(process) and root_stopped
            except (OSError, ValueError, AssertionError):
                root_stopped = False
    else:
        root_stopped = _kill_root(record)
    exited = wait_process_records([record, *children], timeout=kill_timeout)
    return root_stopped and exited
