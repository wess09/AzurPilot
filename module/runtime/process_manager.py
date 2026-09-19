"""
实例进程管理器。

管理 Alas 多实例运行时的进程生命周期，包括进程池维护、状态追踪
（运行中/停止/异常）及进程间通信的安全处理逻辑。
"""

import argparse

# 此文件专门用于管理 Alas 运行时各实例进程的生存周期及其子进程。
# 负责多账号多开时的进程池维护、状态（运行中、停止、异常）追踪及进程间通信的安全处理逻辑。
from collections.abc import Sequence
import os
import queue
import uuid
import threading
import time
from multiprocessing import Process
from typing import Dict, List, Union

import inflection
from rich.console import ConsoleRenderable
from rich.text import Text

from module.logger import logger, set_file_logger, set_func_logger
from module.config.utils import DEFAULT_CONFIG_NAME
from module.submodule.submodule import load_mod
from module.submodule.utils import (
    get_available_func,
    get_available_mod,
    get_available_mod_func,
    get_config_mod,
    get_func_mod,
    list_mod_instance,
)
from module.runtime.setting import State
from module.runtime.process_control import is_process_alive, stop_process, stop_process_tree
from module.runtime.worker_events import ExitEvent, TaskEvent, WorkerResult
from module.runtime.worker_registry import (
    get_workers,
    is_current_owner,
    process_matches,
    register_worker,
    unregister_worker,
)

_STOP_ACTION_UNSET = object()


class ProcessManager:
    _processes: Dict[str, "ProcessManager"] = {}
    _managers_lock = threading.RLock()
    _lifecycle_locks: Dict[str, threading.RLock] = {}
    _lifecycle_locks_lock = threading.Lock()
    MANUAL_STOP_ACTION_TIMEOUT = 30

    def __init__(self, config_name: str = DEFAULT_CONFIG_NAME) -> None:
        self.config_name = config_name
        self._renderable_queue: queue.Queue[ConsoleRenderable | TaskEvent | ExitEvent] = State.manager.Queue()
        self._preview_queue = None
        self.current_task = None
        self.run_id = None
        self.exit_result: WorkerResult | None = None
        self._worker_observed = False
        self._runtime_lock = threading.RLock()
        self._queue_lock = threading.Lock()
        self.renderables: List[ConsoleRenderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self._process: Process | None = None
        self.thd_log_queue_handler: threading.Thread | None = None
        self._state_override: int | None = None
        self._state_override_deadline: float | None = None

    @classmethod
    def _get_lifecycle_lock(cls, config_name: str) -> threading.RLock:
        """返回配置实例共享的生命周期锁。"""
        with cls._lifecycle_locks_lock:
            try:
                return cls._lifecycle_locks[config_name]
            except KeyError:
                lock = threading.RLock()
                cls._lifecycle_locks[config_name] = lock
                return lock

    def set_state_override(self, state: int, duration: float = 10) -> None:
        """
        强制设置临时的 UI 状态，用于图标测试。

        Args:
            state: 状态值（1=运行中, 2=停止, 3=错误, 4=更新）
            duration: 覆盖持续时间（秒），为 0 或 None 时持续生效直到手动清除
        """
        if state not in (1, 2, 3, 4):
            raise ValueError(f"Invalid state override: {state}")
        self._state_override = state
        if duration and duration > 0:
            self._state_override_deadline = time.time() + duration
        else:
            self._state_override_deadline = None

    def clear_state_override(self) -> None:
        self._state_override = None
        self._state_override_deadline = None

    def _get_state_override(self) -> int | None:
        if self._state_override is None:
            return None
        if (
            self._state_override_deadline is not None
            and time.time() >= self._state_override_deadline
        ):
            self.clear_state_override()
            return None
        return self._state_override

    def start(self, func: str | None, ev: threading.Event | None = None) -> None:
        # 更新事务持有 restart_lock；清理过程持有 cleanup_lock。请求线程不能在事务
        # 期间长期阻塞；同线程的 RLock 重入仍允许更新失败后的实例恢复。
        if not State.restart_lock.acquire(blocking=False):
            logger.info(f"[{self.config_name}] WebUI 更新或重启事务进行中，拒绝启动 worker")
            return
        try:
            if not State.cleanup_lock.acquire(blocking=False):
                logger.info(f"[{self.config_name}] WebUI 清理进行中，拒绝启动 worker")
                return
            try:
                with self._get_lifecycle_lock(self.config_name):
                    if State._restart_requested or State._clearup:
                        logger.warning(
                            f"[{self.config_name}] WebUI 正在重启或已清理，拒绝启动 worker"
                        )
                        return
                    if self.alive:
                        return
                    # alive 在登记不可验证时保守返回 False；
                    # 此处再次确认登记状态，防止在登记不一致时启动重复 worker。
                    _pid, _, _verified = self._registered_worker()
                    if not _verified:
                        logger.warning(
                            f"[{self.config_name}] Worker 登记不一致，拒绝启动以避免重复"
                        )
                        return
                    if func is None:
                        func = get_config_mod(self.config_name)
                    with self._runtime_lock:
                        self.current_task = None
                        self.run_id = uuid.uuid4().hex
                        self.exit_result = None
                        # 每轮独立队列，旧读线程不会消费新 worker 的事件。
                        self._renderable_queue = State.manager.Queue()
                        self._queue_lock = threading.Lock()
                    self._preview_queue = State.manager.Queue(maxsize=2)
                    from module.runtime.preview import hub
                    hub.publish(self.config_name, {"instance": self.config_name, "image": None, "capturedAt": None})
                    args = (
                        self.config_name,
                        func,
                        self._renderable_queue,
                        ev,
                        self._preview_queue,
                        self.run_id,
                    )
                    process = Process(
                        target=ProcessManager.run_process,
                        args=args,
                    )
                    self._process = process
                    try:
                        process.start()
                        self._register_process(process.pid)
                    except Exception:
                        self._terminate_unregistered_process(process)
                        # 回滚失败时仍保留可信句柄，alive 会阻止重复启动。
                        if not self._is_process_alive(process):
                            self._process = None
                        self.exit_result = WorkerResult.ERROR
                        raise
                    self.start_log_queue_handler()
            finally:
                State.cleanup_lock.release()
        finally:
            State.restart_lock.release()

    def start_log_queue_handler(self) -> None:
        threading.Thread(target=self._thread_preview_queue_handler,
                         args=(self._preview_queue, self.run_id), daemon=True).start()
        self.thd_log_queue_handler = threading.Thread(
            target=self._thread_log_queue_handler,
            args=(self._renderable_queue, self._process, self.run_id, self._queue_lock),
        )
        self.thd_log_queue_handler.start()

    def stop(self) -> bool:
        """停止 worker 进程树，并返回是否确认全部结束。"""
        with self._get_lifecycle_lock(self.config_name):
            stopped, _ = self._stop_worker_locked()
        if stopped:
            logger.info(f"[{self.config_name}] 已退出")
        else:
            logger.warning(f"[{self.config_name}] worker 未完全停止")
        return stopped

    def stop_by_user(self, action: object = _STOP_ACTION_UNSET) -> bool:
        """停止 worker 后执行用户配置的收尾动作。

        该入口仅供 WebUI 的停止按钮使用。更新、WebUI 清理和 MCP 仍调用
        ``stop()``，从而避免非用户停止意外关闭游戏或模拟器。

        ``stay_there`` 直接复用最初的强制停止路径，不启动收尾进程，确保
        停止行为和响应速度与未引入停止后动作前完全一致。未传入动作时保留
        旧调用行为，由独立收尾进程重新读取配置。
        """
        if action is not _STOP_ACTION_UNSET:
            from module.runtime.scheduler_stop import normalize_stop_action

            if normalize_stop_action(action) == "stay_there":
                return self.stop()

        with self._get_lifecycle_lock(self.config_name):
            stopped, should_run_action = self._stop_worker_locked()
            if stopped and should_run_action:
                self._run_manual_stop_action_locked()

        if stopped:
            logger.info(f"[{self.config_name}] 已退出")
        else:
            logger.warning(f"[{self.config_name}] worker 未完全停止")
        return stopped

    def _stop_worker_locked(self) -> tuple[bool, bool]:
        """在实例生命周期锁内终止 worker，并返回是否可执行收尾动作。"""
        process = self._process
        local_process_alive = self._is_process_alive(process)

        if local_process_alive:
            pid, record, pid_verified = self._registered_worker(process.pid)
        else:
            pid, record, pid_verified = self._registered_worker()

        # 只有验证过的登记 worker 或当前存活的本地句柄才允许触发后续动作，
        # 避免清理失效登记时关闭了无关实例的游戏或模拟器。
        should_run_action = (pid is not None and pid_verified) or local_process_alive

        # _registered_worker 可能已通过 join(0) 回收僵尸句柄，
        # 或 worker 在此期间自然退出。同步本地活性状态，
        # 避免因过时的 local_process_alive 误判 stop 失败。
        if local_process_alive and not self._is_process_alive(self._process):
            local_process_alive = False

        stopped = pid is None and not local_process_alive
        if not pid_verified:
            logger.error(f"[{self.config_name}] worker 身份无法确认，保留登记并拒绝终止")
            stopped = False
        elif pid is not None:
            stopped = stop_process_tree(
                process if local_process_alive else None,
                record=record,
                name=f"worker {self.config_name}",
                timeout=5 if local_process_alive else 0,
            )
        if stopped:
            self._process = None
            stopped = self._unregister_process()
            if stopped and pid is not None:
                with self._runtime_lock:
                    self.exit_result = WorkerResult.MANUAL_STOP
                    self.current_task = None
                self.renderables.append(
                    Text(f"[{self.config_name}] exited. Reason: Manual stop\n")
                )
        if not stopped:
            logger.error(f"[{self.config_name}] 停止工作进程失败 PID {pid}")
        log_queue_handler = self.thd_log_queue_handler
        if log_queue_handler is not None:
            log_queue_handler.join(timeout=1)
            if log_queue_handler.is_alive():
                logger.warning(
                    "[WebUI-进程管理] 日志队列处理线程未在 1 秒内停止"
                )

        return stopped, should_run_action

    def _run_manual_stop_action_locked(self) -> None:
        """在 worker 退出后运行独立收尾进程，并限制其最长运行时间。"""
        process = Process(
            target=ProcessManager.run_manual_stop_action,
            args=(self.config_name,),
        )
        try:
            process.start()
        except Exception:
            logger.exception(f"[{self.config_name}] 启动停止收尾进程失败")
            return

        process.join(timeout=self.MANUAL_STOP_ACTION_TIMEOUT)
        try:
            alive = process.is_alive()
        except (OSError, ValueError, AssertionError):
            alive = False
        if alive:
            logger.warning(
                f"[{self.config_name}] 停止收尾动作超过 "
                f"{self.MANUAL_STOP_ACTION_TIMEOUT} 秒，正在终止"
            )
            self._terminate_manual_stop_action(process)
            return

        exitcode = getattr(process, "exitcode", None)
        if exitcode not in (None, 0):
            logger.warning(f"[{self.config_name}] 停止收尾进程异常退出: {exitcode}")

    @staticmethod
    def _terminate_manual_stop_action(process: Process) -> None:
        """终止超时收尾进程及其子树，避免遗留设备操作。"""
        if not stop_process_tree(process, name="停止收尾", timeout=1, kill_timeout=1):
            logger.warning("[WebUI-进程管理] 终止停止收尾进程失败")

    @staticmethod
    def run_manual_stop_action(config_name: str) -> None:
        """独立进程入口，延迟导入以避免 WebUI 父进程加载设备依赖。"""
        from module.runtime.scheduler_stop import run_stop_action

        run_stop_action(config_name)

    _is_process_alive = staticmethod(is_process_alive)

    @classmethod
    def _terminate_unregistered_process(cls, process: Process) -> None:
        """通过本地句柄回滚登记失败的进程及其子树。"""
        if not stop_process_tree(process, name="未登记 worker", timeout=3):
            logger.warning("[WebUI-进程管理] 回滚未登记 worker 失败")
            # 树枚举可能被拒绝，但刚创建的 Process 句柄仍可安全终止根进程。
            stop_process(process, timeout=3)

    def _registered_worker(
        self, expected_pid: int | None = None
    ) -> tuple[int | None, dict | None, bool]:
        """返回已验证的 worker 身份；调用方必须持有生命周期锁。"""
        registry = State.process_registry
        cached_pid = None
        if registry is not None:
            try:
                cached_pid = registry.get(self.config_name)
                cached_pid = int(cached_pid) if cached_pid is not None else None
            except Exception as exc:
                logger.warning(f"[{self.config_name}] 无法读取 worker PID 缓存: {exc}")
        try:
            expected_pid = int(expected_pid) if expected_pid is not None else None
        except (TypeError, ValueError):
            return None, None, False

        pid = expected_pid if expected_pid is not None else cached_pid
        try:
            record = get_workers(os.getpid()).get(self.config_name)
            if record is None:
                # 缓存只用于兼容；缺少身份的缓存 PID 不能授权终止或重复启动。
                return pid, None, pid is None
            record_pid = int(record["pid"])
            if expected_pid is not None and expected_pid != record_pid:
                logger.error(f"[{self.config_name}] 本地 worker 与持久化身份不一致")
                return expected_pid, None, False
            pid = record_pid
            if not is_current_owner(os.getpid()):
                logger.error(f"[{self.config_name}] 当前 WebUI 不拥有 worker 登记")
                return pid, None, False
            matches = process_matches(record)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            logger.error(f"[{self.config_name}] 无法验证 worker PID {pid}: {exc}")
            return pid, None, False

        if matches is True:
            if registry is not None and cached_pid != pid:
                try:
                    registry[self.config_name] = pid
                except Exception as exc:
                    logger.warning(f"[{self.config_name}] 无法修复 worker PID 缓存: {exc}")
            return pid, record, True

        if matches is False:
            logger.error(
                f"[{self.config_name}] worker PID {pid} 已复用，清除过期登记但不终止该进程"
            )
        else:
            logger.info(f"[{self.config_name}] worker PID {pid} 已退出，清除过期登记")

        unregistered = self._unregister_process()
        if expected_pid is not None:
            # process_matches 已确认进程死亡（返回 None）或 PID 已复用
            # （返回 False），本地句柄可能是未 join 的僵尸。
            # 尝试 join 回收僵尸句柄，避免将已死进程误报为存活。
            try:
                process = self._process
                if process is not None and process.pid == expected_pid:
                    process.join(timeout=0)
            except (OSError, ValueError, AssertionError):
                pass
            # join 后若句柄不再报告存活，说明已是僵尸，已回收。
            if not self._is_process_alive(self._process):
                self._process = None
                if unregistered:
                    return None, None, True
            return expected_pid, None, False
        if unregistered:
            return None, None, True
        return pid, None, False

    def _registered_pid(self) -> tuple[int | None, bool]:
        """返回登记的 worker PID 及其身份是否已被持久化记录确认。"""
        pid, _, verified = self._registered_worker()
        return pid, verified

    def _register_process(self, pid: int | None) -> None:
        if pid is None:
            return
        register_worker(os.getpid(), self.config_name, pid)
        if State.process_registry is not None:
            State.process_registry[self.config_name] = pid

    def _unregister_process(self) -> bool:
        try:
            if not unregister_worker(os.getpid(), self.config_name):
                logger.error(
                    f"[{self.config_name}] 当前 WebUI 不拥有 worker 登记，拒绝清除"
                )
                return False
        except Exception as exc:
            logger.exception_context(
                title='无法清除 worker 登记',
                exc=exc,
                impact='父进程会在下一次重启前再次验证该 PID。',
                action='检查 config 目录写入权限。',
                level=40,
            )
            return False
        if State.process_registry is not None:
            State.process_registry.pop(self.config_name, None)
        return True

    def _thread_preview_queue_handler(self, output, run_id):
        """从子进程接收已编码截图并通知浏览器，不访问设备。"""
        from module.runtime.preview import hub
        while self.run_id == run_id:
            try:
                frame = output.get(timeout=0.5)
                with self._get_lifecycle_lock(self.config_name):
                    if frame.pop('runId', None) == self.run_id:
                        hub.publish(self.config_name, frame)
            except queue.Empty:
                if not self.alive:
                    return
            except (EOFError, OSError):
                return

    def _consume_worker_message(self, message, run_id) -> None:
        """状态只接受当前轮事件；已确认的最终结果不被迟到事件覆盖。"""
        with self._runtime_lock:
            if run_id != self.run_id:
                return
            if isinstance(message, (TaskEvent, ExitEvent)):
                if message.run_id != self.run_id:
                    return
                if self.exit_result is not None:
                    return
                if isinstance(message, TaskEvent):
                    self.current_task = message.command
                else:
                    self.exit_result = message.result
                    self.current_task = None
                return
            self.renderables.append(message)
            if len(self.renderables) > self.renderables_max_length:
                self.renderables = self.renderables[self.renderables_reduce_length :]

    def _drain_worker_queue(self, output, run_id, queue_lock=None) -> None:
        """已确认 worker 退出后排空队列，包含其最后一次同步 put。"""
        if queue_lock is None:
            queue_lock = self._queue_lock
        with queue_lock:
            while True:
                try:
                    message = output.get_nowait()
                except (queue.Empty, EOFError, OSError):
                    return
                self._consume_worker_message(message, run_id)

    def _thread_log_queue_handler(self, output, process, run_id, queue_lock=None) -> None:
        # 锁与队列一起绑定本轮，旧线程的阻塞读取不影响新轮状态。
        if queue_lock is None:
            queue_lock = self._queue_lock
        while True:
            try:
                with queue_lock:
                    message = output.get(timeout=0.2)
                    self._consume_worker_message(message, run_id)
            except queue.Empty:
                # 检查本轮句柄，不取生命周期锁，避免 stop 持锁 join 时互相等待。
                if not self._is_process_alive(process):
                    self._drain_worker_queue(output, run_id, queue_lock)
                    break
            except (EOFError, OSError):
                break
        logger.info("日志队列处理循环结束")

    @property
    def alive(self) -> bool:
        with self._get_lifecycle_lock(self.config_name):
            if self._is_process_alive(self._process):
                self._worker_observed = True
                return True
            pid, pid_verified = self._registered_pid()
            if pid is not None:
                self._worker_observed = True
            if not pid_verified:
                # 登记验证失败且本地句柄已死时，保守默认已退出，
                # 避免 alert 属性持续阻塞日志线程和状态展示。
                # start() 通过额外的 _registered_worker 检查防止重复启动。
                return False
            return pid is not None

    @property
    def state(self) -> int:
        override_state = self._get_state_override()
        if override_state is not None:
            return override_state
        # 整轮读取保持生命周期锁，避免把旧句柄退出码用于新轮事件。
        with self._get_lifecycle_lock(self.config_name):
            process = self._process
            if self.alive:
                return 1
            if self.run_id is not None:
                self._drain_worker_queue(self._renderable_queue, self.run_id)
            with self._runtime_lock:
                if self.exit_result == WorkerResult.MANUAL_STOP:
                    return 2
                try:
                    exitcode = getattr(process, "exitcode", None)
                except (OSError, ValueError, AssertionError):
                    exitcode = None
                if isinstance(exitcode, int) and exitcode != 0:
                    return 3
                if self.exit_result == WorkerResult.UPDATE:
                    return 4
                if self.exit_result == WorkerResult.FINISHED:
                    return 2
                # 从未启动的实例默认停止；缺失最终结果的退出一律视为异常。
                if self.run_id is None and self.exit_result is None and not self._worker_observed:
                    return 2
                return 3

    @classmethod
    def get_manager(cls, config_name: str) -> "ProcessManager":
        """
        获取指定配置名称的进程管理器，不存在时自动创建。

        Args:
            config_name: 配置实例名称（如 'alas'）

        Returns:
            对应的 ProcessManager 实例。
        """
        with cls._managers_lock:
            if config_name not in cls._processes:
                cls._processes[config_name] = ProcessManager(config_name)
            return cls._processes[config_name]

    @classmethod
    def is_running(cls, config_name: str) -> bool:
        """检查指定配置实例是否正在运行。"""
        with cls._managers_lock:
            manager = cls._processes.get(config_name)
        return manager is not None and manager.alive

    @classmethod
    def remove_manager(cls, config_name: str) -> None:
        """移除指定配置实例的进程管理器。"""
        with cls._managers_lock:
            cls._processes.pop(config_name, None)

    @staticmethod
    def run_process(
        config_name,
        func: str,
        q: queue.Queue[ConsoleRenderable | TaskEvent | ExitEvent],
        e: threading.Event | None = None,
        preview_queue=None,
        run_id=None,
    ) -> None:
        """统一发布最终结果，包括调度器通过 SystemExit 退出的路径。"""
        from module.runtime.worker_events import initialize

        initialize(q.put, run_id)
        result = WorkerResult.ERROR
        try:
            result = ProcessManager._run_process(config_name, func, q, e, preview_queue, run_id)
        except SystemExit as exc:
            if exc.code in (None, 0):
                result = WorkerResult.UPDATE if e is not None and e.is_set() else WorkerResult.FINISHED
            raise
        except Exception as exc:
            logger.exception(exc)
        finally:
            q.put(ExitEvent(run_id, result))

    @staticmethod
    def _run_process(config_name, func, q, e, preview_queue, run_id) -> WorkerResult:
        import sys

        if sys.platform != "win32":
            import resource

            try:
                _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                _target = (
                    65536 if _hard == resource.RLIM_INFINITY else min(65536, _hard)
                )
                if _soft < _target:
                    resource.setrlimit(resource.RLIMIT_NOFILE, (_target, _hard))
            except Exception:
                pass
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--electron",
            action="store_true",
            help="由 Electron 客户端运行时启用此参数。",
        )
        args, _ = parser.parse_known_args()
        State.electron = args.electron

        # 初始化日志器
        set_file_logger(name=config_name)
        if State.electron:
            # 参考 https://github.com/LmeSzinc/AzurLaneAutoScript/issues/2051
            logger.info("[WebUI] 检测到 Electron 环境，移除标准输出日志处理器")
            from module.logger import console_hdlr

            logger.removeHandler(console_hdlr)
        set_func_logger(func=q.put)
        if preview_queue is not None:
            from module.runtime.preview import initialize
            initialize(config_name, preview_queue, q.put, run_id)

        if os.environ.get("DEMO") == "1":
            logger.info("[WebUI-进程] 日志3")
            time.sleep(1)
            logger.info("[WebUI-进程] 日志2")
            time.sleep(1)
            logger.info("[WebUI-进程] 日志1")
            time.sleep(1)
            logger.info("[WebUI] 此版本为演示用途")
            return WorkerResult.FINISHED

        from module.config.config import AzurLaneConfig


        # 设置环境变量，使预加载模块（如 al_ocr.py）可以提前读取配置
        os.environ["ALAS_CONFIG_NAME"] = config_name

        if e is not None:
            AzurLaneConfig.stop_event = e
        try:
            # 运行 AzurPilot
            single_task = False
            if func == "alas":
                from alas import AzurLaneAutoScript

                if e is not None:
                    AzurLaneAutoScript.stop_event = e
                task_result = AzurLaneAutoScript(config_name=config_name).loop()
            elif func in get_available_func():
                from alas import AzurLaneAutoScript

                single_task = True
                task_result = AzurLaneAutoScript(config_name=config_name).run(
                    inflection.underscore(func), skip_first_screenshot=True
                )
            elif func in get_available_mod():
                mod = load_mod(func)

                if mod is None:
                    logger.critical(f"[WebUI] 无法加载功能模块：{func}")
                    return WorkerResult.ERROR

                if e is not None:
                    mod.set_stop_event(e)
                task_result = mod.loop(config_name)
            elif func in get_available_mod_func():
                task_result = getattr(load_mod(get_func_mod(func)), inflection.underscore(func))(
                    config_name
                )
            else:
                logger.critical(
                    f"[WebUI] 杂鱼大叔，连功能模块都找不到吗？{func} 这种东西根本不存在啦~"
                )
                return WorkerResult.ERROR
            if task_result is False or (single_task and task_result == "recoverable"):
                return WorkerResult.ERROR
            if e is not None and e.is_set():
                logger.info(f"[{config_name}] exited. Reason: Update\n")
                return WorkerResult.UPDATE
            else:
                logger.info(f"[{config_name}] exited. Reason: Finish\n")
                return WorkerResult.FINISHED
        except Exception as ex:
            logger.exception(ex)
            return WorkerResult.ERROR

    @classmethod
    def running_instances(cls) -> List["ProcessManager"]:
        with cls._managers_lock:
            names = set(cls._processes)
        try:
            names.update(get_workers(os.getpid()))
        except RuntimeError as exc:
            logger.warning(f"无法读取 worker 身份登记: {exc}")
        if State.process_registry is not None:
            names.update(State.process_registry.keys())
        return [cls.get_manager(name) for name in names if cls.get_manager(name).alive]

    @staticmethod
    def restart_processes(
        instances: Sequence[Union["ProcessManager", str]] | None = None,
        ev: threading.Event | None = None,
    ) -> None:
        """
        更新重载后（或更新失败时），重启所有更新前正在运行的 AzurPilot 实例。

        Args:
            instances: 需要重启的实例列表，元素为 ProcessManager 或配置名称字符串。
            ev: 用于通知子进程执行更新的事件对象。
        """
        logger.hr("[WebUI-进程管理] 重启 Alas")

        # 加载 MOD_CONFIG_DICT
        list_mod_instance()

        if instances is None:
            instances = []

        _instances: set[ProcessManager] = set()

        for instance in instances:
            if isinstance(instance, str):
                _instances.add(ProcessManager.get_manager(instance))
            elif isinstance(instance, ProcessManager):
                _instances.add(instance)

        try:
            with open("./config/reloadalas", mode="r", encoding="utf-8") as f:
                for line in f.readlines():
                    line = line.strip()
                    _instances.add(ProcessManager.get_manager(line))
        except FileNotFoundError:
            pass

        for process in _instances:
            logger.info(f"启动中 [{process.config_name}]")
            process.start(func=get_config_mod(process.config_name), ev=ev)

        try:
            os.remove("./config/reloadalas")
        except:
            pass
        logger.info("[WebUI-进程管理] 启动 Alas 完成")
