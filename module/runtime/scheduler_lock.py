"""保证同一配置同一时间只有一个调度器进程在操作模拟器。

WebUI 的 worker 登记只约束它自己启动的进程；直接运行 ``alas.py`` 或脚本
不会经过登记。两个调度器同时控制同一模拟器时，会互相抢占 minitouch
连接、打断点击并并发写入配置，因此在调度循环入口按配置名加系统级文件锁。
进程退出（包括被强制结束）时系统会自动释放锁，不会留下需要手动清理的状态。
"""

import os
import time
from pathlib import Path

from module.runtime.worker_registry import _is_lock_conflict, _prepare_lock_file

SCHEDULER_LOCK_DIR = Path('./cache/scheduler-locks')
# WebUI 更新重启时，旧 worker 可能仍在退出；短暂等待避免误判为重复启动。
SCHEDULER_LOCK_TIMEOUT = 15.0
SCHEDULER_LOCK_RETRY_INTERVAL = 0.5


class SchedulerLockConflict(RuntimeError):
    """同一配置已有其他调度器进程持有锁。"""


def _try_lock(handle) -> None:
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def acquire_scheduler_lock(config_name, timeout=SCHEDULER_LOCK_TIMEOUT):
    """取得指定配置的调度器独占锁。

    Args:
        config_name (str): 配置名。
        timeout (float): 锁被占用时的最长等待秒数。

    Returns:
        持有锁的文件句柄，需保持打开直到调度器退出。

    Raises:
        SchedulerLockConflict: 超时后锁仍被其他进程持有。
        OSError: 锁文件无法创建或加锁时出现非冲突错误。
    """
    handle = _prepare_lock_file(SCHEDULER_LOCK_DIR / f'{config_name}.lock')
    deadline = time.monotonic() + timeout
    while True:
        try:
            _try_lock(handle)
            return handle
        except OSError as exc:
            if not _is_lock_conflict(exc):
                handle.close()
                raise
            if time.monotonic() >= deadline:
                handle.close()
                raise SchedulerLockConflict(
                    f'配置 {config_name} 已有其他调度器进程在运行'
                ) from exc
            time.sleep(SCHEDULER_LOCK_RETRY_INTERVAL)


def release_scheduler_lock(handle) -> None:
    """释放调度器锁；句柄为 None 时忽略。"""
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # 关闭句柄同样会释放锁，解锁失败不影响退出。
        pass
    finally:
        handle.close()
