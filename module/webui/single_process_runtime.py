"""单进程实例的独立宿主进程。

WebUI 保持轻量，不导入 Pillow、OpenCV 或任务模块；这些依赖只在本模块启动的
专用宿主子进程中加载一次。宿主内每个 Alas 配置使用一个协作式线程，从而复用
Python、NumPy、OpenCV 与远程 OCR 客户端的进程内基础开销。
"""

from __future__ import annotations

import multiprocessing
import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any

from module.webui.runtime_host import (
    RuntimeHost,
    WorkerSpec,
    WorkerSpecValidationError,
    WorkerStatus,
    validate_worker_specs,
)


_ACTIVE_STATES = frozenset(
    (WorkerStatus.STARTING.value, WorkerStatus.RUNNING.value, WorkerStatus.STOPPING.value)
)
_TERMINAL_STATES = frozenset((WorkerStatus.STOPPED.value, WorkerStatus.FAILED.value))


@dataclass(slots=True)
class RuntimeWorkerState:
    """父 WebUI 进程保存的 worker 状态快照。"""

    status: str = WorkerStatus.STOPPED.value
    error: str | None = None
    updated_at: float = 0.0
    generation: int = 0
    accepted: bool = False


def _emit_host_event(event_queue, **event: Any) -> None:
    """尽力向父进程发送事件，父进程退出不应阻止宿主清理。"""
    event['timestamp'] = time.time()
    try:
        event_queue.put(event, block=False)
    except (OSError, EOFError, BrokenPipeError, queue.Full):
        pass


def _run_single_process_worker(
    control,
    config_name: str,
    func: str,
    renderable_queue,
    update_event,
    event_queue,
    ocr_address: str,
    generation: int,
    host_epoch: int,
) -> None:
    """在线程上下文中运行一个标准 Alas 实例。

    RuntimeHost 已经在调用本函数前进入 ``runtime_scope(config_name)``。本函数
    只在这里延迟导入图像和任务栈，确保 WebUI 父进程不会被它们污染。
    """
    from module.base.runtime_context import set_runtime_option
    from module.exception import OcrServerUnavailable, WorkerStop
    from module.logger import logger, reset_runtime_log_context, set_runtime_log_context

    def renderable_sink(renderable) -> None:
        try:
            renderable_queue.put(renderable)
        except (OSError, EOFError, BrokenPipeError, queue.Full):
            # WebUI 已退出时丢弃日志，不能让自动化线程因此失败。
            pass

    script = None
    terminal_state = WorkerStatus.STOPPED.value
    terminal_error = None
    log_context_ready = False

    try:
        control.add_external_stop_event(update_event)
        set_runtime_option('strict_ocr_server', True)
        set_runtime_log_context(config_name, renderable_sink)
        log_context_ready = True
        _emit_host_event(
            event_queue,
            kind='worker_state',
            config_name=config_name,
            status=WorkerStatus.RUNNING.value,
            generation=generation,
            host_epoch=host_epoch,
        )

        if control.is_set():
            raise WorkerStop

        from module.webui.setting import State

        configured_address = str(State.deploy_config.OcrClientAddress).strip()
        if not State.deploy_config.UseOcrServer:
            raise OcrServerUnavailable(
                '单进程实例要求 Deploy.Ocr.UseOcrServer=true'
            )
        if configured_address != ocr_address:
            raise OcrServerUnavailable(
                'OCR 服务地址在宿主启动后发生变化，拒绝在不一致配置下运行: '
                f'{configured_address} != {ocr_address}'
            )

        from module.ocr.rpc import wait_for_ocr_server

        if not wait_for_ocr_server(ocr_address, timeout=3):
            raise OcrServerUnavailable(
                f'远程 OCR 服务不可用: {ocr_address}'
            )

        if func != 'alas':
            raise RuntimeError(
                f'单进程宿主当前仅支持标准 Alas 实例，收到功能: {func}'
            )

        from alas import AzurLaneAutoScript

        script = AzurLaneAutoScript(config_name=config_name, stop_event=control)
        script.loop()
    except WorkerStop:
        logger.info(f'[{config_name}] 已退出。原因: 协作停止 | Reason: Stop')
    except BaseException as exc:
        terminal_state = WorkerStatus.FAILED.value
        terminal_error = ''.join(traceback.format_exception(exc))
        raise
    finally:
        if script is not None:
            try:
                script._stop_watchdog()
            except Exception:
                logger.exception('[Alas] 停止看门狗失败')
        _emit_host_event(
            event_queue,
            kind='worker_state',
            config_name=config_name,
            status=terminal_state,
            error=terminal_error,
            generation=generation,
            host_epoch=host_epoch,
        )
        if log_context_ready:
            reset_runtime_log_context()


def run_single_process_host(command_queue, event_queue, ready_event, host_epoch: int) -> None:
    """宿主子进程入口；顶层仅加载标准库，图像栈在此后才按需导入。"""
    from module.webui.fake_pil_module import remove_fake_pil_module

    # WebUI 父进程为减小自身内存会注入假 PIL；专用宿主需要真实 Pillow。
    remove_fake_pil_module()

    # 线程创建的后台任务不会自动继承实例 ContextVar。共享宿主整个生命周期
    # 都要求远程 OCR，因此在进程级别再设一道禁止本地模型回退的保护。
    from module.ocr.rpc import ModelProxy

    ModelProxy.set_require_remote_server(True)

    host = RuntimeHost()
    parent_process = multiprocessing.parent_process()
    log_forward_stop = threading.Event()

    def forward_runtime_logs() -> None:
        """把线程宿主自身的生命周期日志转发给父 WebUI。"""
        while not log_forward_stop.is_set():
            for record in host.drain_logs(max_items=100):
                _emit_host_event(
                    event_queue,
                    kind='runtime_log',
                    config_name=record.config_name,
                    level=record.level,
                    message=record.message,
                    traceback_text=record.traceback_text,
                    host_epoch=host_epoch,
                )
            log_forward_stop.wait(0.1)
        for record in host.drain_logs():
            _emit_host_event(
                event_queue,
                kind='runtime_log',
                config_name=record.config_name,
                level=record.level,
                message=record.message,
                traceback_text=record.traceback_text,
                host_epoch=host_epoch,
            )

    log_forward_thread = threading.Thread(
        target=forward_runtime_logs,
        name='AzurPilotRuntimeLogForwarder',
        daemon=True,
    )
    log_forward_thread.start()
    _emit_host_event(event_queue, kind='ready', host_epoch=host_epoch)
    ready_event.set()

    command_channel_closed = False
    try:
        while True:
            if parent_process is not None:
                try:
                    if not parent_process.is_alive():
                        command_channel_closed = True
                        break
                except (OSError, ValueError, AssertionError):
                    command_channel_closed = True
                    break
            try:
                command = command_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                command_channel_closed = True
                break

            action = command.get('action')
            config_name = command.get('config_name')
            if action == 'start':
                try:
                    _emit_host_event(
                        event_queue,
                        kind='worker_state',
                        config_name=config_name,
                        status=WorkerStatus.STARTING.value,
                        generation=command['generation'],
                        host_epoch=host_epoch,
                    )
                    host.start_worker(
                        config_name,
                        _run_single_process_worker,
                        config_name,
                        command['func'],
                        command['renderable_queue'],
                        command.get('update_event'),
                        event_queue,
                        command['ocr_address'],
                        command['generation'],
                        host_epoch,
                        generation=command['generation'],
                    )
                except Exception as exc:
                    _emit_host_event(
                        event_queue,
                        kind='worker_state',
                        config_name=config_name,
                        status=WorkerStatus.FAILED.value,
                        error=''.join(traceback.format_exception(exc)),
                        generation=command.get('generation'),
                        host_epoch=host_epoch,
                    )
            elif action == 'stop':
                handle = host.get_worker(config_name)
                if (
                    handle is not None
                    and handle.is_alive()
                    and command.get('generation') == getattr(handle, 'generation', None)
                ):
                    handle.request_stop(command.get('reason'))
                    _emit_host_event(
                        event_queue,
                        kind='worker_state',
                        config_name=config_name,
                        status=WorkerStatus.STOPPING.value,
                        generation=command.get('generation'),
                        host_epoch=host_epoch,
                    )
                # 线程已退出时由 _run_single_process_worker 的 finally 上报真实
                # STOPPED/FAILED，不能在这里抢先伪造 STOPPED 覆盖失败状态。
            elif action == 'shutdown':
                timeout = command.get('timeout')
                result = host.shutdown(timeout=timeout, reason=command.get('reason'))
                _emit_host_event(
                    event_queue,
                    kind='shutdown_complete',
                    complete=all(result.values()),
                    request_id=command.get('request_id'),
                    host_epoch=host_epoch,
                )
                if all(result.values()):
                    break
    finally:
        result = host.shutdown(timeout=2, reason='单进程宿主命令通道关闭')
        log_forward_stop.set()
        log_forward_thread.join(timeout=1)
        if command_channel_closed and not all(result.values()):
            # 父进程已失去命令通道且仍有无法协作停止的线程。此时不能让非 daemon
            # 线程继续保活并控制设备，直接结束整个专用宿主交给父级进程树兜底。
            os._exit(1)


class SingleProcessRuntime:
    """父 WebUI 进程对专用线程宿主的控制器。"""

    READY_TIMEOUT = 15.0
    START_CONFIRM_TIMEOUT = 5.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process = None
        self._command_queue = None
        self._event_queue = None
        self._ready_event = None
        self._event_thread = None
        self._states: dict[str, RuntimeWorkerState] = {}
        self._specs: dict[str, WorkerSpec] = {}
        self._renderable_queues: dict[str, Any] = {}
        self._state_changed = threading.Condition(self._lock)
        self._shutdown_complete = threading.Event()
        self._shutdown_success = False
        self._host_epoch = 0
        self._shutdown_request_id = 0
        self._pending_shutdown: tuple[int, int] | None = None

    @staticmethod
    def _process_alive(process) -> bool:
        try:
            return process is not None and process.is_alive()
        except (OSError, ValueError, AssertionError):
            return False

    def _start_event_thread_locked(self) -> None:
        event_queue = self._event_queue
        process = self._process
        host_epoch = self._host_epoch
        if event_queue is None or process is None:
            return
        thread = threading.Thread(
            target=self._event_loop,
            args=(event_queue, process, host_epoch),
            name='AzurPilotRuntimeEvents',
            daemon=True,
        )
        self._event_thread = thread
        thread.start()

    def _ensure_host_locked(self) -> bool:
        if self._process_alive(self._process):
            return True

        self._discard_dead_host_locked()
        command_queue = multiprocessing.Queue()
        event_queue = multiprocessing.Queue()
        ready_event = multiprocessing.Event()
        self._host_epoch += 1
        host_epoch = self._host_epoch
        process = multiprocessing.Process(
            target=run_single_process_host,
            args=(command_queue, event_queue, ready_event, host_epoch),
            name='AzurPilotRuntimeHost',
        )
        process.start()
        self._process = process
        self._command_queue = command_queue
        self._event_queue = event_queue
        self._ready_event = ready_event
        self._shutdown_complete.clear()
        self._shutdown_success = False
        self._pending_shutdown = None
        self._start_event_thread_locked()

        if ready_event.wait(self.READY_TIMEOUT):
            return True

        self._terminate_host_locked()
        return False

    def ensure_host(self) -> bool:
        """确保专用宿主已就绪，供上层先完成 PID 登记后再启动 worker。"""
        with self._lock:
            return self._ensure_host_locked()

    def host_pid(self) -> int | None:
        """返回当前存活宿主的 PID。"""
        with self._lock:
            if not self._process_alive(self._process):
                return None
            try:
                return int(self._process.pid)
            except (TypeError, ValueError, AttributeError):
                return None

    @staticmethod
    def _validate_transferable(value: Any, name: str) -> None:
        """在入队前验证对象可被 Windows spawn 的 IPC 队列序列化。"""
        if value is None:
            return
        from multiprocessing.reduction import ForkingPickler

        try:
            ForkingPickler.dumps(value)
        except Exception as exc:
            raise TypeError(
                f'{name} 不能通过单进程宿主 IPC 传递；请使用 Manager 代理对象'
            ) from exc

    def _discard_dead_host_locked(self) -> None:
        if self._process_alive(self._process):
            return
        for state in self._states.values():
            if state.status in _ACTIVE_STATES:
                state.status = WorkerStatus.FAILED.value
                state.error = '单进程宿主进程已退出'
                state.updated_at = time.time()
        self._specs = {
            name: spec
            for name, spec in self._specs.items()
            if self._states.get(name, RuntimeWorkerState()).status in _ACTIVE_STATES
        }
        self._process = None
        self._command_queue = None
        self._event_queue = None
        self._ready_event = None
        self._pending_shutdown = None
        self._renderable_queues.clear()
        self._state_changed.notify_all()

    def _mark_host_failed_locked(self, reason: str) -> None:
        """记录宿主级故障，并唤醒等待启动/停止结果的调用方。"""
        now = time.time()
        for state in self._states.values():
            if state.status in _ACTIVE_STATES:
                state.status = WorkerStatus.FAILED.value
                state.error = reason
                state.updated_at = now
                state.accepted = True
        self._specs.clear()
        self._state_changed.notify_all()

    def _apply_worker_state_event_locked(self, event: dict[str, Any]) -> None:
        """在持有控制器锁时合并同一 worker 的状态事件。"""
        name = event.get('config_name')
        if not name:
            return

        state = self._states.setdefault(name, RuntimeWorkerState())
        generation = event.get('generation')
        if generation is None or generation != state.generation:
            return

        status = event.get('status', WorkerStatus.FAILED.value)
        # 同一代次的事件可能因队列顺序在 worker 已失败/停止后才到达。
        # 保留第一个终态，避免 shutdown 的 STOPPED 覆盖原始 FAILED。
        if state.status in _TERMINAL_STATES:
            return

        state.status = status
        state.error = event.get('error')
        state.updated_at = event.get('timestamp', time.time())
        state.accepted = True
        if state.status in _TERMINAL_STATES:
            self._specs.pop(name, None)
        self._state_changed.notify_all()

    def _event_loop(self, event_queue, process, host_epoch: int) -> None:
        while True:
            try:
                event = event_queue.get(timeout=0.2)
            except queue.Empty:
                if not self._process_alive(process):
                    with self._lock:
                        # 宿主可能刚好已由 start_worker 重建。旧事件线程不能把
                        # 新宿主当作死亡实例处理，更不能直接退出而遗留无人消费的
                        # 新事件队列。
                        if (
                            event_queue is not self._event_queue
                            or process is not self._process
                            or host_epoch != self._host_epoch
                        ):
                            return
                        self._discard_dead_host_locked()
                    return
                continue
            except (EOFError, OSError):
                with self._lock:
                    if (
                        event_queue is not self._event_queue
                        or process is not self._process
                        or host_epoch != self._host_epoch
                    ):
                        return
                    self._mark_host_failed_locked('单进程宿主事件通道已断开')
                    # 事件通道断开时即使宿主 PID 仍存活，也不能继续让线程控制
                    # 设备；终止当前宿主，后续启动请求会建立新的一代宿主。
                    if self._process_alive(process):
                        self._terminate_host_locked()
                    else:
                        self._discard_dead_host_locked()
                return

            kind = event.get('kind')
            if kind == 'worker_state':
                with self._lock:
                    if event.get('host_epoch') != host_epoch:
                        continue
                    self._apply_worker_state_event_locked(event)
            elif kind == 'runtime_log':
                if event.get('host_epoch') != host_epoch:
                    continue
                with self._lock:
                    renderable_queue = self._renderable_queues.get(event.get('config_name'))
                if renderable_queue is not None:
                    message = event.get('message', '')
                    traceback_text = event.get('traceback_text')
                    if traceback_text:
                        message = f'{message}\n{traceback_text}'
                    try:
                        renderable_queue.put(message)
                    except (OSError, EOFError, BrokenPipeError, queue.Full):
                        pass
            elif kind == 'shutdown_complete':
                with self._lock:
                    if (
                        event.get('host_epoch') != host_epoch
                        or event.get('request_id') != self._pending_shutdown_request_id()
                    ):
                        continue
                    self._shutdown_success = bool(event.get('complete'))
                    self._shutdown_complete.set()
                    self._state_changed.notify_all()

    def _pending_shutdown_request_id(self) -> int | None:
        """返回当前宿主等待确认的关闭请求 ID。调用方必须持有锁。"""
        if self._pending_shutdown is None:
            return None
        host_epoch, request_id = self._pending_shutdown
        if host_epoch != self._host_epoch:
            return None
        return request_id

    def start_worker(
        self,
        spec: WorkerSpec,
        func: str,
        renderable_queue,
        update_event=None,
    ) -> bool:
        """验证规格后请求宿主启动实例线程。

        ``renderable_queue`` 和 ``update_event`` 必须是 multiprocessing.Manager
        代理或其他可被 spawn 序列化的对象；普通 ``threading.Event`` 会被同步
        拒绝，避免 feeder 线程异步报错后留下假启动状态。
        """
        with self._lock:
            config_name = str(spec.config_name).strip()
            current = self._states.get(config_name)
            if current is not None and current.status in _ACTIVE_STATES:
                return True

            normalized_specs = validate_worker_specs((*self._specs.values(), spec))
            spec = normalized_specs[-1]
            self._validate_transferable(renderable_queue, 'renderable_queue')
            self._validate_transferable(update_event, 'update_event')

            if not self._ensure_host_locked():
                state = self._states.setdefault(spec.config_name, RuntimeWorkerState())
                state.status = WorkerStatus.FAILED.value
                state.error = '单进程宿主在超时内未就绪'
                state.updated_at = time.time()
                state.accepted = True
                return False

            self._specs[spec.config_name] = spec
            previous = self._states.get(spec.config_name)
            generation = 1 if previous is None else previous.generation + 1
            self._states[spec.config_name] = RuntimeWorkerState(
                status=WorkerStatus.STARTING.value,
                updated_at=time.time(),
                generation=generation,
            )
            self._renderable_queues[spec.config_name] = renderable_queue
            try:
                self._command_queue.put(
                    {
                        'action': 'start',
                        'config_name': spec.config_name,
                        'func': func,
                        'renderable_queue': renderable_queue,
                        'update_event': update_event,
                        'ocr_address': spec.ocr_address,
                        'generation': generation,
                    }
                )
            except (OSError, EOFError, BrokenPipeError):
                self._discard_dead_host_locked()
                return False

            deadline = time.monotonic() + self.START_CONFIRM_TIMEOUT
            while True:
                state = self._states.get(spec.config_name)
                if state is None or state.generation != generation:
                    return False
                if state.accepted:
                    if state.status in _TERMINAL_STATES:
                        raise RuntimeError(
                            f'单进程 worker {spec.config_name} 启动后立即结束: '
                            f'{state.error or state.status}'
                        )
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    state.status = WorkerStatus.FAILED.value
                    state.error = '单进程宿主未确认启动请求'
                    state.updated_at = time.time()
                    self._specs.pop(spec.config_name, None)
                    try:
                        self._command_queue.put(
                            {
                                'action': 'stop',
                                'config_name': spec.config_name,
                                'reason': '启动确认超时',
                                'generation': generation,
                            }
                        )
                    except (OSError, EOFError, BrokenPipeError):
                        pass
                    raise RuntimeError(
                        f'单进程宿主未确认 {spec.config_name} 的启动请求，已拒绝回退独立进程'
                    )
                self._state_changed.wait(remaining)

    def is_alive(self, config_name: str) -> bool:
        with self._lock:
            self._discard_dead_host_locked()
            state = self._states.get(config_name)
            return state is not None and state.status in _ACTIVE_STATES

    def status(self, config_name: str) -> str:
        with self._lock:
            self._discard_dead_host_locked()
            state = self._states.get(config_name)
            return WorkerStatus.STOPPED.value if state is None else state.status

    def error(self, config_name: str) -> str | None:
        with self._lock:
            state = self._states.get(config_name)
            return None if state is None else state.error

    def stop_worker(
        self,
        config_name: str,
        timeout: float,
        reason: str,
    ) -> bool:
        """请求单个线程停止；超时后绝不在此误杀共享宿主。"""
        with self._lock:
            self._discard_dead_host_locked()
            state = self._states.get(config_name)
            if state is None or state.status in _TERMINAL_STATES:
                return True
            command_queue = self._command_queue
            if command_queue is None:
                return False
            state.status = WorkerStatus.STOPPING.value
            state.updated_at = time.time()
            try:
                command_queue.put(
                    {
                        'action': 'stop',
                        'config_name': config_name,
                        'reason': reason,
                        'generation': state.generation,
                    }
                )
            except (OSError, EOFError, BrokenPipeError):
                self._discard_dead_host_locked()
                return False

        deadline = time.monotonic() + max(timeout, 0)
        while time.monotonic() < deadline:
            if not self.is_alive(config_name):
                return True
            time.sleep(0.05)
        return not self.is_alive(config_name)

    def running_names(self) -> set[str]:
        with self._lock:
            self._discard_dead_host_locked()
            return {
                name for name, state in self._states.items() if state.status in _ACTIVE_STATES
            }

    def shutdown(self, timeout: float, force: bool = False) -> bool:
        """停止全部线程并关闭宿主；仅在 WebUI 清理时允许进程级兜底。"""
        with self._lock:
            self._discard_dead_host_locked()
            if self._process is None:
                return True
            self._shutdown_complete.clear()
            self._shutdown_success = False
            self._shutdown_request_id += 1
            request_id = self._shutdown_request_id
            self._pending_shutdown = (self._host_epoch, request_id)
            try:
                self._command_queue.put(
                    {
                        'action': 'shutdown',
                        'timeout': timeout,
                        'reason': 'WebUI 正在关闭',
                        'generations': {
                            name: state.generation
                            for name, state in self._states.items()
                            if state.status in _ACTIVE_STATES
                        },
                        'request_id': request_id,
                    }
                )
            except (OSError, EOFError, BrokenPipeError):
                if force:
                    return self._terminate_host_locked()
                return False

        finished = self._shutdown_complete.wait(max(timeout, 0) + 1)
        with self._lock:
            if finished and self._shutdown_success:
                process = self._process
                if process is not None:
                    process.join(timeout=2)
                if not self._process_alive(process):
                    self._discard_dead_host_locked()
                    return True
                if force:
                    return self._terminate_host_locked()
                return False
            if force:
                return self._terminate_host_locked()
            return False

    def _terminate_host_locked(self) -> bool:
        """强制结束专用宿主，确认退出后才丢弃控制器引用。"""
        process = self._process
        if process is not None:
            try:
                process.terminate()
                process.join(timeout=3)
                if self._process_alive(process):
                    process.kill()
                    process.join(timeout=2)
            except (OSError, ValueError, AssertionError):
                return False
            if self._process_alive(process):
                return False
        self._process = None
        self._command_queue = None
        self._event_queue = None
        self._ready_event = None
        self._specs.clear()
        self._renderable_queues.clear()
        self._pending_shutdown = None
        return True


__all__ = [
    'RuntimeWorkerState',
    'SingleProcessRuntime',
    'WorkerSpec',
    'WorkerSpecValidationError',
    'run_single_process_host',
]
