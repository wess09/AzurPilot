"""按进程身份终止子树；只有 multiprocessing 句柄负责回收自己的子进程。"""

import math
import os
import subprocess
import time


def _warn(message):
    # 身份查询也供启动早期的登记模块使用，避免导入时初始化完整日志器。
    from module.logger import logger

    logger.warning(message)


def process_matches(record: dict) -> bool | None:
    """同一活进程返回 True，PID 复用返回 False，消失或僵尸返回 None。

    不调用 wait()/wait_procs()，避免抢走 multiprocessing 的 waitpid 结果。
    无法读取身份时抛出异常，调用方不能把权限拒绝或缺少依赖当成退出。
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
        if abs(process.create_time() - created_at) >= 0.01:
            return False
        if process.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
            return None
        return True
    except psutil.NoSuchProcess:
        return None
    except psutil.Error as exc:
        raise RuntimeError(f"无法验证进程 PID {pid}: {exc}") from exc


def pid_exists(pid: int) -> bool:
    """仅供缺少身份的旧登记判断消失；该结果不能授权终止。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def is_process_alive(process) -> bool:
    """通过本地句柄查询状态，由 multiprocessing 自己执行非阻塞回收。"""
    if process is None:
        return False
    try:
        return process.is_alive()
    except (ValueError, AssertionError):
        return False
    except OSError:
        return True


def _may_signal(record) -> bool:
    if record is None:
        return True
    matches = process_matches(record)
    if matches is False:
        raise RuntimeError(f"PID {record['pid']} 已复用，拒绝终止未知进程")
    return matches is True


def stop_process(process, timeout=5, kill_timeout=3, record=None) -> bool:
    """通过本地句柄逐级 terminate/kill，并保留其退出码与 join 语义。"""
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


def _kill_record(record) -> bool:
    """每次发送信号前重验创建时间，单个子进程消失不跳过其余子树。"""
    try:
        import psutil

        if not _may_signal(record):
            return True
        process = psutil.Process(record["pid"])
        # psutil 的信号方法还会校验该对象的创建时间，缩小 PID 复用窗口。
        if abs(process.create_time() - record["created_at"]) >= 0.01:
            return False
        process.kill()
        return True
    except ImportError:
        return False
    except psutil.NoSuchProcess:
        return True
    except (psutil.Error, RuntimeError) as exc:
        _warn(f"无法终止进程 {record['pid']}: {exc}")
        return False


def _kill_root(record) -> bool:
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


def wait_process_records(records, timeout=3) -> bool:
    """只轮询身份和运行状态，僵尸交给各自父进程回收。"""
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


def stop_process_tree(process=None, *, record=None, name="进程", timeout=5, kill_timeout=3) -> bool:
    """先记录并终止后代，再停止根进程，确认所有已记录成员均已退出。

    本地句柄支持有界的优雅停止和强制升级；无句柄时必须提供持久化身份。
    枚举失败时保持登记以便重试，不退回仅凭 PID 的盲目终止。
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
            record = {"pid": parent.pid, "created_at": parent.create_time()}
            if not is_process_alive(process):
                return stop_process(process, timeout=0)
        else:
            if process is not None and process.pid != record["pid"]:
                return False
            if not _may_signal(record):
                if process is not None:
                    return stop_process(process, timeout=0, record=record)
                return True
            parent = psutil.Process(record["pid"])
        if abs(parent.create_time() - record["created_at"]) >= 0.01:
            return False
        children = []
        for child in parent.children(recursive=True):
            try:
                children.append({"pid": child.pid, "created_at": child.create_time()})
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
