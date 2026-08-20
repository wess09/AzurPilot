"""单进程实例运行时的线程宿主基础设施。

该模块刻意只依赖 Python 标准库。它不读取 WebUI 状态、不导入任务模块，也
不尝试隔离现有模块中的全局状态；上层必须在启动前完成配置和运行时兼容性
校验。这里仅负责线程的可观测生命周期、协作式停止和结构化运行时日志。
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkerStatus(str, Enum):
    """线程 worker 的生命周期状态。"""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        """返回该状态是否代表线程已经结束。"""
        return self in (self.STOPPED, self.FAILED)


class RuntimeHostError(RuntimeError):
    """运行时宿主的基础异常。"""


class RuntimeHostClosedError(RuntimeHostError):
    """已关闭的宿主被要求启动新 worker。"""


class WorkerAlreadyRunningError(RuntimeHostError):
    """同一配置名已有未结束的 worker。"""


class WorkerSpecValidationError(RuntimeHostError, ValueError):
    """单进程 worker 的前置条件不满足。"""


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    """启动 worker 前由上层从配置提取的不可变运行时规格。

    ``RuntimeHost`` 不知道配置文件格式，因此将共享解释器中不能分叉的关键信息
    显式传入。当前校验只做保守的一致性检查，不会连接 ADB 或 OCR 服务。
    """

    config_name: str
    server: str
    package: str
    emulator_server_name: str
    use_ocr_server: bool
    ocr_address: str | None = None
    control_method: str | None = None
    screenshot_method: str | None = None


def _normalized_text(value: str | None) -> str:
    """返回去除首尾空白后的文本，None 规范为单个空字符串。"""
    return "" if value is None else str(value).strip()


def _is_nemu_ipc(value: str | None) -> bool:
    """返回控制或截图方法是否为进程全局的 Nemu IPC 后端。"""
    normalized = _normalized_text(value).casefold().replace("_", "").replace("-", "")
    return normalized == "nemuipc"


def _runtime_scope(config_name: str):
    """延迟进入实例运行时上下文。

    基础宿主可以单独测试和复用，因此不在模块导入阶段依赖项目运行时上下文。
    每个 worker 的 target 都会自动在 ``module.base.runtime_context`` 提供的
    对应配置名作用域中执行。导入失败必须传播，避免单进程模式在未隔离状态时
    静默继续执行。
    """
    from module.base.runtime_context import runtime_scope

    return runtime_scope(config_name)


def validate_worker_specs(specs: Iterable[WorkerSpec]) -> tuple[WorkerSpec, ...]:
    """验证可以放入同一 Python 解释器的 worker 规格。

    同一个解释器中的服务器选择、应用包和 OCR 客户端配置会被底层模块缓存或
    以全局状态保存。因此所有实例必须使用一致值；设备地址则必须明确且唯一，
    防止两个线程控制同一模拟器。

    Args:
        specs: 需要共同运行的 worker 规格。

    Returns:
        规范化后的不可变规格元组，顺序与输入一致。

    Raises:
        WorkerSpecValidationError: 任一规格缺失必要值或彼此不兼容。
    """
    normalized: list[WorkerSpec] = []
    config_names: set[str] = set()
    device_names: set[str] = set()

    for raw_spec in specs:
        if not isinstance(raw_spec, WorkerSpec):
            raise WorkerSpecValidationError(
                f"worker 规格必须是 WorkerSpec，实际为 {type(raw_spec).__name__}"
            )

        config_name = _normalized_text(raw_spec.config_name)
        server = _normalized_text(raw_spec.server)
        package = _normalized_text(raw_spec.package)
        emulator_server_name = _normalized_text(raw_spec.emulator_server_name)
        ocr_address = _normalized_text(raw_spec.ocr_address) or None
        control_method = _normalized_text(raw_spec.control_method) or None
        screenshot_method = _normalized_text(raw_spec.screenshot_method) or None

        if not config_name:
            raise WorkerSpecValidationError("worker 配置名不能为空")
        if config_name in config_names:
            raise WorkerSpecValidationError(f"重复的 worker 配置名: {config_name}")
        if not server:
            raise WorkerSpecValidationError(f"{config_name} 未指定服务器")
        if not package:
            raise WorkerSpecValidationError(f"{config_name} 未指定游戏包名")
        if not emulator_server_name:
            raise WorkerSpecValidationError(f"{config_name} 未指定模拟器设备地址")
        if emulator_server_name.casefold() == "auto":
            raise WorkerSpecValidationError(
                f"{config_name} 使用了 auto 设备地址；单进程模式要求显式设备地址"
            )
        if emulator_server_name in device_names:
            raise WorkerSpecValidationError(
                f"多个 worker 使用同一设备地址: {emulator_server_name}"
            )
        if _is_nemu_ipc(control_method) or _is_nemu_ipc(screenshot_method):
            raise WorkerSpecValidationError(
                f"{config_name} 使用 Nemu IPC；该后端会修改进程级标准输出，"
                "不能进入单进程线程宿主"
            )
        if (control_method or '').casefold() == 'auto' or (
            screenshot_method or ''
        ).casefold() == 'auto':
            raise WorkerSpecValidationError(
                f"{config_name} 使用 auto 设备 I/O 方式；单进程模式要求显式选择，"
                "以免解析到进程级后端"
            )
        if not bool(raw_spec.use_ocr_server):
            raise WorkerSpecValidationError(
                f"{config_name} 未启用 OCR 服务；单进程模式禁止本地 OCR 回退"
            )
        if bool(raw_spec.use_ocr_server) and not ocr_address:
            raise WorkerSpecValidationError(
                f"{config_name} 启用了 OCR 服务但未指定服务地址"
            )

        config_names.add(config_name)
        device_names.add(emulator_server_name)
        normalized.append(
            WorkerSpec(
                config_name=config_name,
                server=server,
                package=package,
                emulator_server_name=emulator_server_name,
                use_ocr_server=bool(raw_spec.use_ocr_server),
                ocr_address=ocr_address,
                control_method=control_method,
                screenshot_method=screenshot_method,
            )
        )

    if not normalized:
        return ()

    first = normalized[0]
    for spec in normalized[1:]:
        if spec.server != first.server:
            raise WorkerSpecValidationError(
                "单进程模式要求所有实例使用同一服务器: "
                f"{first.config_name}={first.server}, {spec.config_name}={spec.server}"
            )
        if spec.package != first.package:
            raise WorkerSpecValidationError(
                "单进程模式要求所有实例使用同一游戏包名: "
                f"{first.config_name}={first.package}, {spec.config_name}={spec.package}"
            )
        if spec.use_ocr_server != first.use_ocr_server:
            raise WorkerSpecValidationError("单进程模式要求所有实例使用相同的 OCR 服务开关")
        if spec.use_ocr_server and spec.ocr_address != first.ocr_address:
            raise WorkerSpecValidationError(
                "单进程模式要求所有实例使用同一 OCR 服务地址: "
                f"{first.config_name}={first.ocr_address}, "
                f"{spec.config_name}={spec.ocr_address}"
            )

    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class RuntimeLogRecord:
    """由运行时宿主产生的结构化日志记录。"""

    timestamp: float
    config_name: str
    level: str
    message: str
    traceback_text: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    """worker 失败的轻量快照，不保留原始异常及其对象图。"""

    exception_type: str
    message: str
    traceback_text: str


class WorkerControl:
    """交给单个 worker 的协作式控制器。

    worker 应在每个可中断边界检查 ``is_stop_requested()`` 或调用 ``wait()``。
    Python 无法安全地强制终止任意线程，因此该控制器是停止语义的唯一保证。
    """

    def __init__(
        self,
        config_name: str,
        emit_log: Callable[[str, str], None] | None = None,
    ) -> None:
        self.config_name = config_name
        self.stop_event = threading.Event()
        self._emit_log = emit_log
        self._lock = threading.Lock()
        self._stop_reason: str | None = None
        self._stop_requested_at: float | None = None
        self._external_stop_events: list[Any] = []

    @property
    def stop_reason(self) -> str | None:
        """返回首次停止请求携带的原因。"""
        with self._lock:
            return self._stop_reason

    @property
    def reason(self) -> str | None:
        """``stop_reason`` 的简写兼容别名。"""
        return self.stop_reason

    @property
    def stop_requested_at(self) -> float | None:
        """返回首次请求停止的单调时间戳。"""
        with self._lock:
            return self._stop_requested_at

    def request_stop(self, reason: str | None = None) -> bool:
        """请求 worker 尽快停止。

        Returns:
            仅首次设置停止事件时返回 ``True``，后续请求返回 ``False``。
        """
        normalized_reason = _normalized_text(reason) or None
        with self._lock:
            first_request = not self.stop_event.is_set()
            if first_request:
                self._stop_reason = normalized_reason
                self._stop_requested_at = time.monotonic()
                self.stop_event.set()
            return first_request

    def is_stop_requested(self) -> bool:
        """返回是否已请求停止。"""
        if self.stop_event.is_set():
            return True
        with self._lock:
            events = tuple(self._external_stop_events)
        for event in events:
            try:
                if event.is_set():
                    return True
            except Exception:
                continue
        return False

    def is_set(self) -> bool:
        """兼容 ``threading.Event`` 的 ``is_set`` 接口。"""
        return self.is_stop_requested()

    def add_external_stop_event(self, event: Any | None) -> None:
        """附加更新事务等进程间停止事件。"""
        if event is None:
            return
        with self._lock:
            if event not in self._external_stop_events:
                self._external_stop_events.append(event)

    def wait(self, timeout: float | None = None) -> bool:
        """等待停止请求，返回值与 ``threading.Event.wait`` 一致。"""
        if self.is_stop_requested():
            return True
        deadline = None if timeout is None else time.monotonic() + max(timeout, 0)
        while True:
            if deadline is None:
                wait_time = 0.2
            else:
                wait_time = max(0.0, min(0.2, deadline - time.monotonic()))
            if self.stop_event.wait(wait_time) or self.is_stop_requested():
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False

    def log(self, level: str, message: str) -> None:
        """向宿主日志队列写入一条运行时日志。"""
        if self._emit_log is not None:
            self._emit_log(str(level), str(message))


WorkerTarget = Callable[..., Any]


@dataclass(slots=True)
class ThreadWorkerHandle:
    """一个线程 worker 的可查询生命周期句柄。"""

    config_name: str
    control: WorkerControl
    thread: threading.Thread
    generation: int | None = None
    _status: WorkerStatus = WorkerStatus.STARTING
    started_at: float | None = None
    stopped_at: float | None = None
    result: Any = None
    failure: WorkerFailure | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def status(self) -> WorkerStatus:
        """返回当前线程状态。"""
        with self._lock:
            return self._status

    @property
    def error(self) -> WorkerFailure | None:
        """失败信息的兼容别名。"""
        with self._lock:
            return self.failure

    @property
    def traceback(self) -> str | None:
        """失败时返回格式化 traceback。"""
        with self._lock:
            return None if self.failure is None else self.failure.traceback_text

    def is_alive(self) -> bool:
        """返回底层线程是否仍在运行。"""
        return self.thread.is_alive()

    def request_stop(self, reason: str | None = None) -> bool:
        """向该 worker 发送协作式停止请求。"""
        changed = self.control.request_stop(reason)
        with self._lock:
            if self._status in (WorkerStatus.STARTING, WorkerStatus.RUNNING):
                self._status = WorkerStatus.STOPPING
        return changed

    def join(self, timeout: float | None = None) -> bool:
        """等待线程结束，返回线程是否已退出。"""
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def _mark_running(self) -> None:
        with self._lock:
            if self._status == WorkerStatus.STARTING:
                self._status = WorkerStatus.RUNNING
                self.started_at = time.monotonic()

    def _mark_stopped(self, result: Any) -> None:
        with self._lock:
            self.result = result
            self.stopped_at = time.monotonic()
            if self._status != WorkerStatus.FAILED:
                self._status = WorkerStatus.STOPPED

    def _mark_failed(self, failure: WorkerFailure) -> None:
        with self._lock:
            self.failure = failure
            self.stopped_at = time.monotonic()
            self._status = WorkerStatus.FAILED


class RuntimeHost:
    """在单个解释器中管理多个协作式线程 worker。

    该类不启动进程，也不执行模块级隔离。集成层应将其放进专用宿主进程，并在
    调用 ``start_worker`` 前以 ``validate_worker_specs`` 验证全部实例规格。
    """

    def __init__(self, log_queue: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._workers: dict[str, ThreadWorkerHandle] = {}
        self._closed = False
        self._log_queue = log_queue if log_queue is not None else queue.Queue()

    @property
    def closed(self) -> bool:
        """返回宿主是否已拒绝新 worker。"""
        with self._lock:
            return self._closed

    def get_worker(self, config_name: str) -> ThreadWorkerHandle | None:
        """按配置名查找 worker 句柄。"""
        with self._lock:
            return self._workers.get(config_name)

    def workers(self) -> Mapping[str, ThreadWorkerHandle]:
        """返回当前 worker 映射的只读快照。"""
        with self._lock:
            return dict(self._workers)

    def start_worker(
        self,
        config_name: str,
        target: WorkerTarget,
        *args: Any,
        daemon: bool = False,
        generation: int | None = None,
        **kwargs: Any,
    ) -> ThreadWorkerHandle:
        """启动一个 worker 线程。

        ``target`` 会以 ``target(control, *args, **kwargs)`` 调用。结束的同名
        worker 可以重新启动；正在停止的 worker 则必须先完成退出，避免同一配置
        同时操控两套状态。
        """
        config_name = _normalized_text(config_name)
        if not config_name:
            raise ValueError("worker 配置名不能为空")
        if not callable(target):
            raise TypeError("worker target 必须可调用")

        with self._lock:
            if self._closed:
                raise RuntimeHostClosedError("运行时宿主已关闭，不能启动新 worker")
            existing = self._workers.get(config_name)
            # 状态可能已在 target 返回后更新为终态，但线程仍处于 finally 中清理
            # 对应的 RuntimeContext。必须等待线程真正退出，避免旧线程清掉新
            # worker 使用同一 config_name 注册的上下文。
            if existing is not None and existing.is_alive():
                raise WorkerAlreadyRunningError(f"worker 已在运行: {config_name}")

            def emit_log(level: str, message: str) -> None:
                self._publish_log(config_name, level, message)

            control = WorkerControl(config_name, emit_log)
            handle_ref: list[ThreadWorkerHandle] = []
            def runner() -> None:
                self._run_worker(handle_ref[0], target, args, kwargs)

            thread = threading.Thread(
                target=runner,
                name=f"AzurPilotRuntime-{config_name}",
                daemon=daemon,
            )
            handle = ThreadWorkerHandle(config_name, control, thread, generation=generation)
            handle_ref.append(handle)
            self._workers[config_name] = handle
            self._publish_log(config_name, "INFO", "worker 正在启动")
            try:
                thread.start()
            except BaseException as exc:
                failure = WorkerFailure(
                    exception_type=type(exc).__name__,
                    message=str(exc),
                    traceback_text="".join(traceback.format_exception(exc)),
                )
                handle._mark_failed(failure)
                self._publish_log(
                    config_name,
                    "ERROR",
                    f"worker 启动失败: {failure.exception_type}: {failure.message}",
                    failure.traceback_text,
                )
                raise RuntimeHostError(f"无法启动 worker {config_name}") from exc
            return handle

    def stop_worker(
        self,
        config_name: str,
        timeout: float | None = None,
        reason: str | None = "宿主请求停止",
    ) -> bool:
        """请求停止一个 worker，并最多等待 ``timeout`` 秒。

        返回 ``True`` 仅表示线程已退出，不表示任务成功完成。超时后线程不会被
        强制杀死，调用方应保留宿主进程级的兜底终止策略。
        """
        handle = self.get_worker(config_name)
        if handle is None:
            return True
        requested = handle.request_stop(reason)
        if requested:
            self._publish_log(config_name, "INFO", "已请求 worker 停止")
        return handle.join(timeout)

    def stop_all(
        self,
        timeout: float | None = None,
        reason: str | None = "宿主请求停止",
    ) -> dict[str, bool]:
        """向所有 worker 请求停止，并返回每个线程的结束确认结果。"""
        with self._lock:
            handles = list(self._workers.values())

        for handle in handles:
            if handle.request_stop(reason):
                self._publish_log(handle.config_name, "INFO", "已请求 worker 停止")

        deadline = None if timeout is None else time.monotonic() + max(timeout, 0)
        stopped: dict[str, bool] = {}
        for handle in handles:
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
            stopped[handle.config_name] = handle.join(remaining)
        return stopped

    def shutdown(
        self,
        timeout: float | None = None,
        reason: str | None = "宿主正在关闭",
    ) -> dict[str, bool]:
        """关闭宿主、拒绝新 worker，并协作式停止现有 worker。"""
        with self._lock:
            self._closed = True
        return self.stop_all(timeout=timeout, reason=reason)

    def drain_logs(self, max_items: int | None = None) -> list[RuntimeLogRecord]:
        """按 FIFO 顺序非阻塞读取宿主日志。"""
        if max_items is not None and max_items < 0:
            raise ValueError("max_items 不能小于 0")
        if max_items == 0:
            return []

        records: list[RuntimeLogRecord] = []
        while max_items is None or len(records) < max_items:
            try:
                record = self._log_queue.get_nowait()
            except queue.Empty:
                break
            records.append(record)
        return records

    def _run_worker(
        self,
        handle: ThreadWorkerHandle,
        target: WorkerTarget,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        try:
            if handle.control.is_stop_requested():
                handle._mark_stopped(None)
                self._publish_log(handle.config_name, "INFO", "worker 在执行前已停止")
                return

            handle._mark_running()
            self._publish_log(handle.config_name, "INFO", "worker 已启动")
            try:
                with _runtime_scope(handle.config_name):
                    result = target(handle.control, *args, **kwargs)
            except BaseException as exc:
                failure = WorkerFailure(
                    exception_type=type(exc).__name__,
                    message=str(exc),
                    traceback_text="".join(traceback.format_exception(exc)),
                )
                handle._mark_failed(failure)
                self._publish_log(
                    handle.config_name,
                    "ERROR",
                    f"worker 异常退出: {failure.exception_type}: {failure.message}",
                    failure.traceback_text,
                )
                return

            handle._mark_stopped(result)
            if handle.control.is_stop_requested():
                self._publish_log(handle.config_name, "INFO", "worker 已停止")
            else:
                self._publish_log(handle.config_name, "INFO", "worker 已完成")
        finally:
            self._clear_worker_runtime_context(handle.config_name)

    def _clear_worker_runtime_context(self, config_name: str) -> None:
        """释放已结束 worker 的实例上下文，避免宿主长期运行时积累状态。"""
        try:
            from module.base.runtime_context import clear_runtime_context
        except (ImportError, AttributeError) as exc:
            self._publish_log(
                config_name,
                "WARNING",
                f"无法加载运行态清理器: {type(exc).__name__}: {exc}",
            )
            return

        try:
            clear_runtime_context(config_name)
        except Exception as exc:
            self._publish_log(
                config_name,
                "WARNING",
                f"运行态清理失败: {type(exc).__name__}: {exc}",
            )

    def _publish_log(
        self,
        config_name: str,
        level: str,
        message: str,
        traceback_text: str | None = None,
    ) -> None:
        record = RuntimeLogRecord(
            timestamp=time.time(),
            config_name=config_name,
            level=_normalized_text(level).upper() or "INFO",
            message=str(message),
            traceback_text=traceback_text,
        )
        try:
            put_nowait = getattr(self._log_queue, "put_nowait", None)
            if put_nowait is not None:
                put_nowait(record)
            else:
                self._log_queue.put(record, block=False)
        except (queue.Full, AttributeError, TypeError):
            # 日志积压不能阻塞或终止游戏 worker。外部队列不符合非阻塞接口时也
            # 只丢弃本条运行时诊断，不影响生命周期状态。
            pass


__all__ = [
    "RuntimeHost",
    "RuntimeHostClosedError",
    "RuntimeHostError",
    "RuntimeLogRecord",
    "ThreadWorkerHandle",
    "WorkerAlreadyRunningError",
    "WorkerControl",
    "WorkerFailure",
    "WorkerSpec",
    "WorkerSpecValidationError",
    "WorkerStatus",
    "validate_worker_specs",
]
