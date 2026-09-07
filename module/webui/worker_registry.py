"""将 WebUI worker 的身份写入父进程可读取的运行时登记文件。"""

import errno
import json
import os
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Iterator

from deploy.atomic import atomic_remove, atomic_replace, atomic_write


WORKER_REGISTRY_FILE = Path("./cache/webui-workers.json")
LEGACY_WORKER_REGISTRY_FILE = Path("./config/webui-workers.json")
DEFAULT_WORKER_REGISTRY_FILE = WORKER_REGISTRY_FILE
REGISTRY_LOCK_TIMEOUT = 10.0
REGISTRY_LOCK_RETRY_INTERVAL = 0.05

# 同一 Python 进程内先串行化，避免重复竞争系统级文件锁。
_registry_lock = threading.RLock()


class WorkerRegistryOwnershipError(RuntimeError):
    """当前进程无权修改 WebUI worker 登记。"""


class WorkerRegistryLockError(RuntimeError):
    """无法在限定时间内取得 WebUI worker 登记锁。"""


def _empty_registry(
    owner_pid: int | None = None,
    owner_created_at: float | None = None,
) -> dict:
    return {
        "owner_created_at": owner_created_at,
        "owner_pid": owner_pid,
        "workers": {},
    }


def _registry_lock_file(registry_file: Path | None = None) -> Path:
    """返回与登记文件同目录的跨进程锁文件路径。"""
    if registry_file is None:
        registry_file = WORKER_REGISTRY_FILE
    return registry_file.with_name(f"{registry_file.name}.lock")


def _legacy_registry_lock_file() -> Path:
    """返回旧登记文件对应的跨进程锁文件路径。"""
    return _registry_lock_file(LEGACY_WORKER_REGISTRY_FILE)


def _prepare_lock_file(lock_file: Path):
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_file.open("a+b")
    try:
        # msvcrt.locking() 不能锁定空文件，因此保留一个锁字节。
        if lock_file.stat().st_size == 0:
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        return handle
    except Exception:
        handle.close()
        raise


def _is_lock_conflict(exc: OSError) -> bool:
    return (
        isinstance(exc, PermissionError)
        or exc.errno in (errno.EACCES, errno.EAGAIN)
        or getattr(exc, "winerror", None) in (32, 33)
    )


def _acquire_file_lock(handle) -> None:
    deadline = time.monotonic() + REGISTRY_LOCK_TIMEOUT

    if os.name == "nt":
        import msvcrt

        def acquire() -> None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    else:
        try:
            import fcntl
        except ImportError as exc:
            raise WorkerRegistryLockError("当前平台不支持 worker 登记文件锁") from exc

        def acquire() -> None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    while True:
        try:
            acquire()
            return
        except OSError as exc:
            if not _is_lock_conflict(exc):
                raise WorkerRegistryLockError(f"无法锁定 worker 登记文件: {exc}") from exc
            if time.monotonic() >= deadline:
                raise WorkerRegistryLockError("等待 worker 登记文件锁超时") from exc
            time.sleep(REGISTRY_LOCK_RETRY_INTERVAL)


def _release_file_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked_file(lock_file: Path) -> Iterator[None]:
    """以系统级文件锁保护指定的运行时文件。"""
    handle = _prepare_lock_file(lock_file)
    acquired = False
    try:
        _acquire_file_lock(handle)
        acquired = True
        yield
    finally:
        if acquired:
            _release_file_lock(handle)
        handle.close()


def _legacy_registry_enabled() -> bool:
    """仅在默认运行时路径下启用旧文件迁移。"""
    return WORKER_REGISTRY_FILE == DEFAULT_WORKER_REGISTRY_FILE


def _record_is_alive(record: dict | None) -> bool:
    """保守判断登记的进程是否仍在运行。"""
    if record is None:
        return False
    if "created_at" not in record:
        return _pid_exists(record["pid"])
    try:
        return process_matches(record) is True
    except RuntimeError:
        # 无法确认旧进程状态时不能覆盖其登记，避免启动第二个 WebUI。
        return True


def _migrate_legacy_registry() -> Path:
    """在旧所有者退出后将登记文件迁移到缓存目录。

    以旧文件所有者的存活状态为准，不做两份文件的内容比较：
    - 旧所有者仍在运行：旧文件仍是权威登记，直接返回旧路径（新进程若与它
      抢同一个 WebUI 所有权，会由 claim_owner() 按存活状态拒绝）。
    - 旧所有者已退出：旧文件只是陈旧残留。写入两份文件的所有事务都在同一把
      跨进程锁内串行，内容不一致不代表存在并发会话，因此不抛冲突异常中止
      启动——清理残留，让缓存文件（或随后的空登记写入）成为唯一权威。
    """
    if not _legacy_registry_enabled() or not LEGACY_WORKER_REGISTRY_FILE.exists():
        return WORKER_REGISTRY_FILE

    legacy_registry = _read_registry(LEGACY_WORKER_REGISTRY_FILE)
    if _record_is_alive(_owner_record(legacy_registry)):
        return LEGACY_WORKER_REGISTRY_FILE

    try:
        if WORKER_REGISTRY_FILE.exists():
            # 缓存文件已存在（例如更早一次新版本会话的残留）：删除旧文件即可，
            # 缓存中的 owner/worker 由 claim_owner() 再做存活裁决。
            atomic_remove(LEGACY_WORKER_REGISTRY_FILE)
        else:
            # 缓存文件尚不存在：把旧登记原子搬到缓存路径，保留其中可能仍有
            # 存活的孤儿 worker 记录供父进程回收；随后的认领会按存活清理。
            WORKER_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            atomic_replace(LEGACY_WORKER_REGISTRY_FILE, WORKER_REGISTRY_FILE)
    except OSError as exc:
        raise RuntimeError(f"无法清理旧 worker 登记文件: {exc}") from exc
    return WORKER_REGISTRY_FILE


@contextmanager
def _locked_registry() -> Iterator[Path]:
    """以进程内锁和系统级文件锁保护一次完整的读改写事务。"""
    with _registry_lock:
        if _legacy_registry_enabled():
            # 即使旧登记尚未创建，也必须先锁旧路径。否则旧版本可能在
            # exists() 检查之后创建旧登记，导致两个版本各自认领所有者。
            with _locked_file(_legacy_registry_lock_file()):
                with _locked_file(_registry_lock_file()):
                    yield _migrate_legacy_registry()
        else:
            with _locked_file(_registry_lock_file()):
                yield WORKER_REGISTRY_FILE


def _read_registry(registry_file: Path) -> dict:
    try:
        raw = registry_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty_registry()
    except OSError as exc:
        raise RuntimeError(f"无法读取 worker 登记文件: {exc}") from exc

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("登记文件根节点不是对象")
        registry = parsed
        owner_pid = registry.get("owner_pid")
        owner_created_at = registry.get("owner_created_at")
        workers = registry.get("workers")
        if owner_pid is not None:
            owner_pid = int(owner_pid)
            if owner_created_at is not None:
                owner_created_at = float(owner_created_at)
        else:
            owner_created_at = None
        if not isinstance(workers, dict):
            raise ValueError("workers 不是对象")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        # 登记文件损坏/格式错误时按空登记处理，由后续写事务重建文件，
        # 避免一个损坏的残留文件在启动早期就中断后端。
        from module.logger import logger

        logger.warning(f"worker 登记文件 {registry_file} 格式无效，按空登记处理: {exc}")
        return _empty_registry()

    return {
        "owner_created_at": owner_created_at,
        "owner_pid": owner_pid,
        "workers": workers,
    }


def _write_registry(registry: dict, registry_file: Path) -> None:
    atomic_write(
        registry_file,
        json.dumps(registry, ensure_ascii=True, sort_keys=True),
    )


def _process_created_at(pid: int) -> float:
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception as exc:
        raise RuntimeError(f"无法读取 worker PID {pid} 的创建时间: {exc}") from exc


def _owner_record(registry: dict) -> dict | None:
    owner_pid = registry["owner_pid"]
    if owner_pid is None:
        return None
    record = {"pid": owner_pid}
    if registry["owner_created_at"] is not None:
        record["created_at"] = registry["owner_created_at"]
    return record


def _require_current_owner(registry: dict, owner_pid: int) -> None:
    """确认调用者 PID 仍是登记文件中的同一 WebUI 进程。"""
    try:
        expected_pid = int(owner_pid)
    except (TypeError, ValueError) as exc:
        raise WorkerRegistryOwnershipError(f"无效的 WebUI 所有者 PID: {owner_pid}") from exc

    record = _owner_record(registry)
    if record is None or record["pid"] != expected_pid:
        raise WorkerRegistryOwnershipError(
            f"worker 登记所有者不匹配: {registry['owner_pid']} != {expected_pid}"
        )
    if "created_at" not in record:
        raise WorkerRegistryOwnershipError("worker 登记所有者缺少进程身份信息")

    try:
        created_at = _process_created_at(expected_pid)
    except RuntimeError as exc:
        raise WorkerRegistryOwnershipError(
            f"无法验证 WebUI 所有者 PID {expected_pid}: {exc}"
        ) from exc
    if abs(created_at - record["created_at"]) < 0.01:
        return
    raise WorkerRegistryOwnershipError(
        f"WebUI 所有者 PID {expected_pid} 身份不匹配，拒绝修改登记"
    )


def is_current_owner(owner_pid: int) -> bool:
    """返回 PID 是否仍对应登记文件中的当前 WebUI 所有者。"""
    with _locked_registry() as registry_file:
        registry = _read_registry(registry_file)
        try:
            _require_current_owner(registry, owner_pid)
        except WorkerRegistryOwnershipError:
            return False
        return True


def filter_live_workers(workers: dict[str, dict]) -> dict[str, dict]:
    """筛出仍存活的 worker 登记，供所有权认领/回收决策使用。

    无法确认进程状态时按存活保守处理（宁可不覆盖，也不漏回收）。
    """
    return {
        name: record
        for name, record in workers.items()
        if _record_is_alive(record)
    }


def claim_owner(owner_pid: int) -> None:
    """原子地声明当前 WebUI 进程为 worker 登记文件的唯一所有者。"""
    try:
        owner_pid = int(owner_pid)
    except (TypeError, ValueError) as exc:
        raise WorkerRegistryOwnershipError(f"无效的 WebUI 所有者 PID: {owner_pid}") from exc
    owner_created_at = _process_created_at(owner_pid)

    with _locked_registry() as registry_file:
        registry = _read_registry(registry_file)
        previous_owner = _owner_record(registry)
        if previous_owner is not None:
            same_owner = (
                previous_owner["pid"] == owner_pid
                and previous_owner.get("created_at") is not None
                and abs(previous_owner["created_at"] - owner_created_at) < 0.01
            )
            if same_owner:
                # 同一 WebUI 的重复初始化必须保留已登记的 worker。
                return

            if "created_at" not in previous_owner:
                raise WorkerRegistryOwnershipError(
                    "旧 WebUI 所有者缺少进程身份信息，拒绝覆盖其 worker 登记"
                )
            try:
                previous_owner_alive = process_matches(previous_owner)
            except RuntimeError as exc:
                raise WorkerRegistryOwnershipError(
                    f"无法验证旧 WebUI 所有者: {exc}"
                ) from exc
            if previous_owner_alive is True:
                raise WorkerRegistryOwnershipError(
                    f"WebUI 所有者仍在运行 (PID: {previous_owner['pid']})，拒绝启动第二个 WebUI"
                )
            # 旧所有者已确认退出。其登记的 worker 可能是同进程树一并消亡的
            # 失效记录（崩溃残留），也可能是仍存活的孤儿进程（需父进程回收）
            # ——只统计存活的 worker：全部失效即可安全重置登记实现启动自愈。
            live_workers = filter_live_workers(registry["workers"])
            if live_workers:
                raise WorkerRegistryOwnershipError(
                    f"旧 WebUI 仍有存活的 worker 登记 {sorted(live_workers)}，"
                    "必须先由父进程完成回收"
                )

        _write_registry(_empty_registry(owner_pid, owner_created_at), registry_file)


def register_worker(owner_pid: int, config_name: str, pid: int) -> None:
    """登记已启动的 worker，以便父进程在 WebUI 异常退出后回收它。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"无效的 worker PID: {pid}") from exc

    with _locked_registry() as registry_file:
        registry = _read_registry(registry_file)
        _require_current_owner(registry, owner_pid)
        registry["workers"][config_name] = {
            "created_at": _process_created_at(pid),
            "pid": pid,
        }
        _write_registry(registry, registry_file)


def unregister_worker(owner_pid: int, config_name: str) -> bool:
    """移除已正常退出的 worker 登记，返回是否仍拥有该登记。"""
    with _locked_registry() as registry_file:
        registry = _read_registry(registry_file)
        try:
            _require_current_owner(registry, owner_pid)
        except WorkerRegistryOwnershipError:
            return False
        registry["workers"].pop(config_name, None)
        _write_registry(registry, registry_file)
        return True


def get_workers(owner_pid: int) -> dict[str, dict]:
    """返回指定 WebUI 所登记的 worker 快照。"""
    with _locked_registry() as registry_file:
        registry = _read_registry(registry_file)
        if registry["owner_pid"] != owner_pid:
            return {}
        return deepcopy(registry["workers"])


def get_owner() -> int | None:
    """返回当前登记文件所有者的 PID。"""
    with _locked_registry() as registry_file:
        return _read_registry(registry_file)["owner_pid"]


def get_owner_record() -> dict | None:
    """返回 WebUI 所有者的 PID 与创建时间，供父进程验证进程身份。"""
    with _locked_registry() as registry_file:
        registry = _read_registry(registry_file)
        return _owner_record(registry)


def clear_owner(owner_pid: int) -> bool:
    """在 worker 已确认结束后清除指定 WebUI 的登记。"""
    with _locked_registry() as registry_file:
        registry = _read_registry(registry_file)
        record = _owner_record(registry)
        if record is None:
            return True
        if record["pid"] != owner_pid:
            raise WorkerRegistryOwnershipError(
                f"worker 登记所有者不匹配: {record['pid']} != {owner_pid}"
            )

        if owner_pid == os.getpid():
            _require_current_owner(registry, owner_pid)
        elif "created_at" not in record:
            if _pid_exists(owner_pid):
                raise WorkerRegistryOwnershipError(
                    f"旧 WebUI 所有者 PID {owner_pid} 仍存在，拒绝清除登记"
                )
        else:
            try:
                owner_matches = process_matches(record)
            except RuntimeError as exc:
                raise WorkerRegistryOwnershipError(
                    f"无法验证旧 WebUI 所有者 PID {owner_pid}: {exc}"
                ) from exc
            if owner_matches is True:
                raise WorkerRegistryOwnershipError(
                    f"WebUI 所有者仍在运行 (PID: {owner_pid})，拒绝清除登记"
                )

        _write_registry(_empty_registry(), registry_file)
        return True


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def process_matches(record: dict) -> bool | None:
    """确认登记 PID 仍指向同一进程；不存在时返回 ``None``。"""
    try:
        pid = int(record["pid"])
        created_at = float(record["created_at"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("worker 登记记录无效")

    try:
        import psutil

        process = psutil.Process(pid)
        return abs(process.create_time() - created_at) < 0.01
    except Exception as exc:
        try:
            if not os.path.exists(f"/proc/{pid}") and os.name != "nt":
                return None
        except OSError:
            pass
        try:
            import psutil

            if isinstance(exc, psutil.NoSuchProcess):
                return None
        except ImportError:
            pass
        raise RuntimeError(f"无法验证 worker PID {pid}: {exc}") from exc
