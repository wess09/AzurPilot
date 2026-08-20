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
import subprocess
import threading
import time
from multiprocessing import Process
from typing import Dict, List, Union

import inflection
from rich.console import Console, ConsoleRenderable
from rich.text import Text

# 由于本文件不在 app.py 的同一进程或子进程中运行，
# 以下代码需要重复执行。
# 在导入 pywebio 之前先导入伪造模块，避免加载不必要的 PIL 模块。
from module.webui.fake_pil_module import *

import_fake_pil_module()

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
from module.webui.setting import State
from module.webui.worker_registry import (
    get_workers,
    is_current_owner,
    process_matches,
    register_worker,
    unregister_worker,
)


SINGLE_PROCESS_HOST_REGISTRY_NAME = '__single_process_host__'


class SingleProcessUnsafeError(RuntimeError):
    """单进程宿主无法安全接管时，禁止静默回退到另一套进程。"""


class ProcessManager:
    _processes: Dict[str, "ProcessManager"] = {}
    _managers_lock = threading.RLock()
    _lifecycle_locks: Dict[str, threading.RLock] = {}
    _lifecycle_locks_lock = threading.Lock()
    _single_process_runtime = None
    _single_process_runtime_lock = threading.RLock()
    MANUAL_STOP_ACTION_TIMEOUT = 30
    SINGLE_PROCESS_STOP_TIMEOUT = 20

    def __init__(self, config_name: str = DEFAULT_CONFIG_NAME) -> None:
        self.config_name = config_name
        self._renderable_queue: queue.Queue[ConsoleRenderable] = State.manager.Queue()
        self.renderables: List[ConsoleRenderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self._process: Process | None = None
        self._uses_single_process = False
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

    @classmethod
    def _get_single_process_runtime(cls):
        """惰性创建 WebUI 共享的专用线程宿主控制器。"""
        with cls._single_process_runtime_lock:
            if cls._single_process_runtime is None:
                from module.webui.single_process_runtime import SingleProcessRuntime

                cls._single_process_runtime = SingleProcessRuntime()
            return cls._single_process_runtime

    def _build_single_process_spec(self):
        """从配置生成单进程宿主所需的只读兼容性规格。"""
        from module.config.config_updater import ConfigUpdater
        from module.config.deep import deep_get
        from module.config.server import to_server
        from module.webui.runtime_host import WorkerSpec, WorkerSpecValidationError

        data = ConfigUpdater().read_file(self.config_name)
        if self.config_name == SINGLE_PROCESS_HOST_REGISTRY_NAME:
            raise WorkerSpecValidationError(
                f'配置名 {self.config_name} 被单进程宿主登记保留，不能作为实例名'
            )
        package = str(
            deep_get(data, 'Alas.Emulator.PackageName', default='auto')
        ).strip()
        serial = str(deep_get(data, 'Alas.Emulator.Serial', default='auto')).strip()
        screenshot_method = deep_get(
            data, 'Alas.Emulator.ScreenshotMethod', default='auto'
        )
        control_method = deep_get(
            data, 'Alas.Emulator.ControlMethod', default='auto'
        )

        if package.casefold() == 'auto':
            raise WorkerSpecValidationError(
                f'{self.config_name} 的 Emulator.PackageName 为 auto；'
                '单进程模式要求显式游戏包名'
            )
        if serial.casefold() == 'auto':
            raise WorkerSpecValidationError(
                f'{self.config_name} 的 Emulator.Serial 为 auto；'
                '单进程模式要求显式且唯一的设备地址'
            )
        if str(control_method).strip().casefold() == 'auto':
            raise WorkerSpecValidationError(
                f'{self.config_name} 的 Emulator.ControlMethod 为 auto；'
                '单进程模式要求显式控制方式'
            )
        if str(screenshot_method).strip().casefold() == 'auto':
            raise WorkerSpecValidationError(
                f'{self.config_name} 的 Emulator.ScreenshotMethod 为 auto；'
                '单进程模式要求显式截图方式，避免解析到进程级 Nemu IPC'
            )

        return WorkerSpec(
            config_name=self.config_name,
            server=to_server(package),
            package=package,
            emulator_server_name=serial,
            use_ocr_server=bool(State.deploy_config.UseOcrServer),
            ocr_address=str(State.deploy_config.OcrClientAddress).strip() or None,
            control_method=str(control_method),
            screenshot_method=str(screenshot_method),
        )

    def _try_start_single_process_worker(
        self,
        func: str,
        ev: threading.Event | None,
    ) -> bool:
        """尝试通过共享宿主启动实例；失败时让调用方回退独立进程。"""
        if not getattr(State.deploy_config, 'SingleProcessInstances', False):
            return False
        if func != 'alas':
            # 其他模块暂未完成线程级全局状态隔离。共享宿主有活动实例时，
            # 不能让它们静默回退到独立进程，否则可能与宿主线程控制同一设备。
            cls = self.__class__
            with cls._single_process_runtime_lock:
                runtime = cls._single_process_runtime
                if runtime is not None and runtime.host_pid() is not None:
                    if runtime.running_names():
                        raise SingleProcessUnsafeError(
                            '共享宿主已有活动实例，非标准 Alas 任务不能回退为独立进程；'
                            '请先停止共享实例或关闭单进程模式'
                        )
            logger.info(
                f'[{self.config_name}] 功能 {func} 不在单进程宿主支持范围内，使用独立进程'
            )
            return False

        from module.webui.runtime_host import WorkerSpecValidationError

        try:
            spec = self._build_single_process_spec()
            # 在创建/登记宿主前先校验首个规格，避免无 OCR、Nemu IPC 等不兼容
            # 配置留下一个空宿主并阻塞后续安全回退。
            from module.webui.runtime_host import validate_worker_specs

            validate_worker_specs((spec,))
            runtime = self._get_single_process_runtime()
            runtime._validate_transferable(self._renderable_queue, 'renderable_queue')
            runtime._validate_transferable(ev, 'update_event')
            cls = self.__class__
            with cls._single_process_runtime_lock:
                cls._ensure_single_process_host_registered(runtime)
        except WorkerSpecValidationError as exc:
            # 缺少显式包名/设备地址时仍可安全回退到原有独立进程；其余
            # 规格冲突必须阻止启动，不能绕过设备唯一性检查。
            if 'auto' in str(exc).casefold() or '未指定' in str(exc):
                cls = self.__class__
                with cls._single_process_runtime_lock:
                    runtime = cls._single_process_runtime
                    if runtime is not None and runtime.host_pid() is not None:
                        if runtime.running_names():
                            raise SingleProcessUnsafeError(
                                '共享宿主已有活动实例，不能让 auto 设备配置回退为独立进程；'
                                '请先为该实例填写显式包名和唯一设备地址'
                            ) from exc
                        # 仅清理此前校验失败留下的空宿主；不让它继续占用一个
                        # 可被后续显式规格复用的解释器。
                        if not runtime.shutdown(timeout=2, force=True):
                            raise SingleProcessUnsafeError(
                                '无法清理空闲共享宿主，拒绝 auto 配置回退'
                            ) from exc
                        try:
                            unregistered = unregister_worker(
                                os.getpid(), SINGLE_PROCESS_HOST_REGISTRY_NAME
                            )
                        except Exception as cleanup_exc:
                            raise SingleProcessUnsafeError(
                                f'无法清理空闲共享宿主登记: {cleanup_exc}'
                            ) from exc
                        if not unregistered:
                            raise SingleProcessUnsafeError(
                                '无法确认空闲共享宿主登记归属，拒绝 auto 配置回退'
                            ) from exc
                        if State.process_registry is not None:
                            State.process_registry.pop(
                                SINGLE_PROCESS_HOST_REGISTRY_NAME, None
                            )
                        cls._single_process_runtime = None
                logger.warning(
                    f'[{self.config_name}] 单进程模式配置尚未满足要求: {exc}；使用独立进程'
                )
                return False
            raise SingleProcessUnsafeError(str(exc)) from exc
        except SingleProcessUnsafeError:
            raise
        except Exception as exc:
            raise SingleProcessUnsafeError(
                f'共享宿主登记或启动准备失败，拒绝回退独立进程: {exc}'
            ) from exc

        try:
            started = runtime.start_worker(
                spec=spec,
                func=func,
                renderable_queue=self._renderable_queue,
                update_event=ev,
            )
        except WorkerSpecValidationError as exc:
            raise SingleProcessUnsafeError(str(exc)) from exc
        except Exception as exc:
            # 请求已写入共享宿主后，不能假设宿主没有启动线程；保守地拒绝
            # 本次启动，避免再拉起第二个进程控制同一设备。
            raise SingleProcessUnsafeError(
                f'共享宿主启动请求失败，拒绝回退独立进程: {exc}'
            ) from exc

        if not started:
            raise SingleProcessUnsafeError(
                f'[{self.config_name}] 单进程宿主未能确认启动，拒绝回退独立进程'
            )

        self._uses_single_process = True
        self._process = None
        return True

    @classmethod
    def _ensure_single_process_host_registered(cls, runtime) -> None:
        """把共享宿主登记为一个独立 PID，供 WebUI 崩溃监督器回收。"""
        records = get_workers(os.getpid())
        record = records.get(SINGLE_PROCESS_HOST_REGISTRY_NAME)
        host_pid = runtime.host_pid()

        if record is not None:
            try:
                record_pid = int(record['pid'])
                matches = process_matches(record)
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                raise SingleProcessUnsafeError(
                    f'共享宿主登记无效，拒绝启动: {exc}'
                ) from exc
            if matches is True:
                if host_pid != record_pid:
                    raise SingleProcessUnsafeError(
                        f'已有共享宿主 PID {record_pid}，当前控制器 PID {host_pid} 不一致'
                    )
                return
            if matches is False:
                raise SingleProcessUnsafeError(
                    f'共享宿主登记 PID {record_pid} 已被复用，拒绝启动'
                )
            # 进程已退出，当前 WebUI 拥有该登记时可以清理陈旧记录。
            unregister_worker(os.getpid(), SINGLE_PROCESS_HOST_REGISTRY_NAME)
            if State.process_registry is not None:
                State.process_registry.pop(SINGLE_PROCESS_HOST_REGISTRY_NAME, None)

        if host_pid is None:
            if not runtime.ensure_host():
                raise SingleProcessUnsafeError('共享宿主进程未能就绪')
            host_pid = runtime.host_pid()
        if host_pid is None:
            raise SingleProcessUnsafeError('无法获取共享宿主 PID，拒绝启动')

        try:
            register_worker(os.getpid(), SINGLE_PROCESS_HOST_REGISTRY_NAME, host_pid)
        except Exception as exc:
            runtime.shutdown(timeout=2, force=True)
            raise SingleProcessUnsafeError(
                f'无法登记共享宿主 PID {host_pid}: {exc}'
            ) from exc
        if State.process_registry is not None:
            State.process_registry[SINGLE_PROCESS_HOST_REGISTRY_NAME] = host_pid

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
                    if func is None:
                        func = get_config_mod(self.config_name)
                    # 与独立进程路径一致，先验证当前配置没有陈旧或无法确认的
                    # worker 登记；单进程分支不能绕过这道防重复控制检查。
                    _pid, _, _verified = self._registered_worker()
                    if not _verified and _pid is not None:
                        logger.warning(
                            f"[{self.config_name}] Worker 登记不一致，拒绝启动以避免重复"
                        )
                        return
                    try:
                        single_started = self._try_start_single_process_worker(func, ev)
                    except SingleProcessUnsafeError as exc:
                        logger.error(
                            f"[{self.config_name}] 单进程启动被安全检查拒绝: {exc}"
                        )
                        return
                    if single_started:
                        self.start_log_queue_handler()
                        return
                    # alive 在登记不可验证时保守返回 False；
                    # 此处再次确认登记状态，防止在登记不一致时启动重复 worker。
                    _pid, _, _verified = self._registered_worker()
                    if not _verified and _pid is not None:
                        logger.warning(
                            f"[{self.config_name}] Worker 登记不一致，拒绝启动以避免重复"
                        )
                        return
                    args = (
                        self.config_name,
                        func,
                        self._renderable_queue,
                        ev,
                    )
                    process = Process(
                        target=ProcessManager.run_process,
                        args=args,
                    )
                    self._uses_single_process = False
                    self._process = process
                    try:
                        process.start()
                        self._register_process(process.pid)
                    except Exception:
                        self._terminate_unregistered_process(process)
                        self._process = None
                        raise
                    self.start_log_queue_handler()
            finally:
                State.cleanup_lock.release()
        finally:
            State.restart_lock.release()

    def start_log_queue_handler(self) -> None:
        log_queue_handler = self.thd_log_queue_handler
        if log_queue_handler is not None and log_queue_handler.is_alive():
            return
        self.thd_log_queue_handler = threading.Thread(
            target=self._thread_log_queue_handler
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

    def stop_by_user(self) -> bool:
        """停止 worker 后执行用户配置的收尾动作。

        该入口仅供 WebUI 的停止按钮使用。更新、WebUI 清理和 MCP 仍调用
        ``stop()``，从而避免非用户停止意外关闭游戏或模拟器。
        """
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
        if self._uses_single_process:
            runtime = self.__class__._single_process_runtime
            was_alive = runtime is not None and runtime.is_alive(self.config_name)
            stopped = (
                runtime.stop_worker(
                    self.config_name,
                    timeout=self.SINGLE_PROCESS_STOP_TIMEOUT,
                    reason='用户或 WebUI 请求停止',
                )
                if runtime is not None
                else True
            )
            if stopped:
                self._uses_single_process = False
                if was_alive:
                    self.renderables.append(
                        Text(f'[{self.config_name}] exited. Reason: Manual stop\n')
                    )
            else:
                logger.error(
                    f'[{self.config_name}] 单进程 worker 未在 '
                    f'{self.SINGLE_PROCESS_STOP_TIMEOUT}s 内协作停止'
                )

            log_queue_handler = self.thd_log_queue_handler
            if log_queue_handler is not None:
                log_queue_handler.join(timeout=1)
            return stopped, was_alive

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
        if pid is not None and not pid_verified:
            # _registered_worker 可能已通过 join(0) 回收了僵尸句柄；
            # 若句柄已被清理说明 worker 已确认退出，视为成功停止。
            if self._is_process_alive(self._process):
                logger.error(
                    f"[{self.config_name}] worker PID {pid} 身份无法确认，拒绝终止未知进程"
                )
                stopped = False
            else:
                logger.info(
                    f"[{self.config_name}] worker PID {pid} 本地句柄已回收，确认已退出"
                )
                stopped = True
        elif pid is not None:
            if local_process_alive and process is not None:
                # 优先使用本地 Process 句柄的 terminate/kill，
                # 比 taskkill 更可靠。
                stopped = ProcessManager._stop_local_process(process)
                if not stopped:
                    # 本地句柄失败时回退到 taskkill 终止进程树
                    stopped = self._kill_registered_process_tree(pid, record)
                    if stopped:
                        process.join(timeout=3)
                        stopped = not self._is_process_alive(process)
            else:
                stopped = self._kill_registered_process_tree(pid, record)
                if stopped and process is not None:
                    process.join(timeout=3)
                    stopped = not self._is_process_alive(process)
        if stopped:
            self._process = None
            stopped = self._unregister_process()
            if stopped and pid is not None:
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
        """终止超时的收尾进程，避免停止按钮无限阻塞。"""
        try:
            process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
        except (OSError, ValueError, AssertionError):
            logger.warning("[WebUI-进程管理] 终止停止收尾进程失败")

    @staticmethod
    def run_manual_stop_action(config_name: str) -> None:
        """独立进程入口，延迟导入以避免 WebUI 父进程加载设备依赖。"""
        from module.webui.scheduler_stop import run_stop_action

        run_stop_action(config_name)

    @staticmethod
    def _is_process_alive(process: Process | None) -> bool:
        """读取本地进程状态，回收僵尸句柄并将失效句柄视为已退出。

        已退出但未 join 的 multiprocessing.Process 句柄在 join() 之前
        仍报告 is_alive() == True（僵尸状态）。此方法调用 join(timeout=0)
        回收僵尸句柄，避免活性检查在整个 stop 流程中误判。
        join(timeout=0) 对仍在运行的进程完全不阻塞。
        """
        try:
            if process is None:
                return False
            if not process.is_alive():
                return False
            # 尝试 join(0) 回收已退出但未 join 的僵尸进程句柄
            process.join(timeout=0)
            return process.is_alive()
        except (OSError, ValueError, AssertionError):
            return False

    @staticmethod
    def _stop_local_process(process: Process) -> bool:
        """使用本地 Process 句柄逐级终止 worker，优先于 taskkill。

        先 terminate() 等待 5 秒，超时则 kill() 等待 3 秒。
        taskkill 可能因权限或进程状态问题静默失败；
        本地句柄的 terminate/kill 更可靠。
        注意：此方法仅终止根进程，不处理子进程树。
        调用方应在失败时回退到 _kill_process_tree。
        """
        try:
            process.terminate()
        except (OSError, ValueError, AssertionError):
            pass
        process.join(timeout=5)
        if process.is_alive():
            try:
                process.kill()
            except (OSError, ValueError, AssertionError):
                pass
            process.join(timeout=3)
        return not process.is_alive()

    @classmethod
    def _terminate_unregistered_process(cls, process: Process) -> None:
        """通过本地进程句柄回滚启动失败的未登记 worker。"""
        if not cls._is_process_alive(process):
            try:
                process.join(timeout=0)
            except (OSError, ValueError, AssertionError):
                pass
            return

        try:
            # Process 句柄绑定创建时的子进程，可避免按已复用 PID 误杀其他进程。
            process.terminate()
            process.join(timeout=3)
            if cls._is_process_alive(process):
                process.kill()
                process.join(timeout=3)
        except (OSError, ValueError, AssertionError):
            pass

    def _kill_registered_process_tree(self, pid: int, record: dict | None) -> bool:
        """在 taskkill 前再次校验登记身份，缩小 PID 复用窗口。"""
        if record is None:
            logger.error(f"[{self.config_name}] worker PID {pid} 缺少持久化身份记录")
            return False
        try:
            matches = process_matches(record)
        except RuntimeError as exc:
            logger.error(f"[{self.config_name}] 无法再次验证 worker PID {pid}: {exc}")
            return False

        if matches is True:
            return self._kill_process_tree(pid)
        if matches is None:
            logger.info(f"[{self.config_name}] worker PID {pid} 已在终止前退出")
            return True

        logger.error(
            f"[{self.config_name}] worker PID {pid} 已复用，拒绝终止未知进程"
        )
        return False

    @staticmethod
    def _kill_process_tree(pid: int) -> bool:
        """终止 worker 及其派生进程，避免关闭 WebUI 后任务留在后台。"""
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=3,
                )
                if result.returncode == 0:
                    return ProcessManager._wait_pid_exit(pid, timeout=3)
                if not ProcessManager._pid_exists(pid):
                    return True
                logger.warning(f"[WebUI-进程管理] 停止工作进程失败 PID {pid}: taskkill 返回 {result.returncode}")
                return False
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning(f"[WebUI-进程管理] 停止工作进程失败 PID {pid}: {exc}")
                return False
        else:
            try:
                import psutil

                parent = psutil.Process(pid)
                for child in reversed(parent.children(recursive=True)):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
            except (ImportError, psutil.Error if "psutil" in locals() else OSError):
                pass
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            return True
        return ProcessManager._wait_pid_exit(pid, timeout=3)

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _wait_pid_exit(pid: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not ProcessManager._pid_exists(pid):
                return True
            time.sleep(0.1)
        return not ProcessManager._pid_exists(pid)

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
            except (TypeError, ValueError):
                logger.error(f"[{self.config_name}] worker PID 登记无效")
                return expected_pid, None, False
            except Exception as exc:
                logger.error(f"[{self.config_name}] 无法读取 worker PID 登记: {exc}")
                return expected_pid, None, False

        try:
            expected_pid = int(expected_pid) if expected_pid is not None else None
        except (TypeError, ValueError):
            logger.error(f"[{self.config_name}] 本地 worker PID 无效")
            return None, None, False

        if expected_pid is not None and cached_pid not in (None, expected_pid):
            logger.error(
                f"[{self.config_name}] 本地 worker PID {expected_pid} 与共享登记 {cached_pid} 不一致"
            )
            return expected_pid, None, False

        pid = expected_pid if expected_pid is not None else cached_pid
        if pid is None:
            return None, None, True

        try:
            if not is_current_owner(os.getpid()):
                logger.error(
                    f"[{self.config_name}] 当前 WebUI 不拥有 worker 登记，拒绝操作 PID {pid}"
                )
                return pid, None, False
            record = get_workers(os.getpid()).get(self.config_name)
            try:
                record_pid = int(record["pid"])
            except (KeyError, TypeError, ValueError):
                record_pid = None
            if not isinstance(record, dict) or record_pid != pid:
                logger.error(
                    f"[{self.config_name}] worker PID {pid} 缺少匹配的持久化登记"
                )
                return pid, None, False
            matches = process_matches(record)
        except RuntimeError as exc:
            logger.error(f"[{self.config_name}] 无法验证 worker PID {pid}: {exc}")
            return pid, None, False

        if matches is True:
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

    def _thread_log_queue_handler(self) -> None:
        while self.alive:
            try:
                log = self._renderable_queue.get(timeout=1)
            except queue.Empty:
                continue
            self.renderables.append(log)
            if len(self.renderables) > self.renderables_max_length:
                self.renderables = self.renderables[self.renderables_reduce_length :]
        logger.info("日志队列处理循环结束")

    @property
    def alive(self) -> bool:
        with self._get_lifecycle_lock(self.config_name):
            if self._uses_single_process:
                runtime = self.__class__._single_process_runtime
                return runtime is not None and runtime.is_alive(self.config_name)
            if self._is_process_alive(self._process):
                return True
            pid, pid_verified = self._registered_pid()
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
        if self._uses_single_process:
            runtime = self.__class__._single_process_runtime
            if runtime is not None:
                status = runtime.status(self.config_name)
                if status == 'failed':
                    return 3
                if status in ('starting', 'running', 'stopping'):
                    return 1
                if status == 'stopped' and not self.renderables:
                    return 2
        if self.alive:
            return 1
        elif len(self.renderables) == 0:
            return 2
        else:
            console = Console(no_color=True)
            tail = self.renderables[-8:]
            rendered_tail = []
            for renderable in tail:
                with console.capture() as capture:
                    console.print(renderable)
                rendered_tail.append(capture.get().strip())
            s = rendered_tail[-1] if rendered_tail else ""
            tail_text = "\n".join(rendered_tail)

            if ("Reason: Manual stop" in s) or ("原因: 手动停止" in s):
                return 2

            update_marker_hit = (
                ("Reason: Update" in s)
                or ("原因: 更新" in s)
                or ("检测到更新事件" in s)
            )
            update_tail_hit = (
                ("Reason: Update" in tail_text)
                or ("原因: 更新" in tail_text)
                or ("检测到更新事件" in tail_text)
            )
            if update_marker_hit:
                return 4

            if ("Reason: Finish" in s) or ("原因: 完成" in s):
                # 在更新流程中，部分代码路径可能会在更新退出日志之后追加 "Finish"。
                if update_tail_hit:
                    return 4
                return 2
            elif "此版本为演示用途" in s:
                return 2
            elif update_tail_hit:
                return 4
            else:
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
        q: queue.Queue[ConsoleRenderable],
        e: threading.Event | None = None,
    ) -> None:
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

        if os.environ.get("DEMO") == "1":
            logger.info("[WebUI-进程] 日志3")
            time.sleep(1)
            logger.info("[WebUI-进程] 日志2")
            time.sleep(1)
            logger.info("[WebUI-进程] 日志1")
            time.sleep(1)
            logger.info("[WebUI] 此版本为演示用途")
            return

        # 移除伪造的 PIL 模块，子进程需要使用真正的 PIL
        remove_fake_pil_module()

        # 设置环境变量，使预加载模块（如 al_ocr.py）可以提前读取配置
        os.environ["ALAS_CONFIG_NAME"] = config_name

        try:
            # 运行 AzurPilot
            if func == "alas":
                from alas import AzurLaneAutoScript

                AzurLaneAutoScript(config_name=config_name, stop_event=e).loop()
            elif func in get_available_func():
                from alas import AzurLaneAutoScript

                AzurLaneAutoScript(config_name=config_name, stop_event=e).run(
                    inflection.underscore(func), skip_first_screenshot=True
                )
            elif func in get_available_mod():
                mod = load_mod(func)

                if mod is None:
                    logger.critical(f"[WebUI] 无法加载功能模块：{func}")
                    return

                if e is not None:
                    mod.set_stop_event(e)
                mod.loop(config_name)
            elif func in get_available_mod_func():
                getattr(load_mod(get_func_mod(func)), inflection.underscore(func))(
                    config_name
                )
            else:
                logger.critical(
                    f"[WebUI] 杂鱼大叔，连功能模块都找不到吗？{func} 这种东西根本不存在啦~"
                )
            if e is not None and e.is_set():
                logger.info(f"[{config_name}] exited. Reason: Update\n")
            else:
                logger.info(f"[{config_name}] exited. Reason: Finish\n")
        except Exception as ex:
            logger.exception(ex)

    @classmethod
    def running_instances(cls) -> List["ProcessManager"]:
        with cls._managers_lock:
            names = set(cls._processes)
        if State.process_registry is not None:
            names.update(State.process_registry.keys())
        # 共享线程宿主以特殊登记名占用一个 PID，但不是可点击的 Alas 配置实例；
        # 不能把它交给普通 stop()，否则会跳过宿主的协作收尾流程。
        names.discard(SINGLE_PROCESS_HOST_REGISTRY_NAME)
        return [cls.get_manager(name) for name in names if cls.get_manager(name).alive]

    @classmethod
    def shutdown_single_process_runtime(cls, timeout: float = 25) -> bool:
        """在 WebUI 收尾时关闭专用线程宿主。

        单个 worker 的 stop 超时不能杀掉共享宿主；但 WebUI 本身退出时，专用宿主
        没有其他所有者，允许在协作停止失败后终止整个子进程作为最终兜底。
        """
        with cls._single_process_runtime_lock:
            runtime = cls._single_process_runtime
        if runtime is None:
            return True

        success = runtime.shutdown(timeout=timeout, force=True)
        if success:
            try:
                if not unregister_worker(os.getpid(), SINGLE_PROCESS_HOST_REGISTRY_NAME):
                    success = False
            except Exception as exc:
                logger.warning(f'无法清除共享宿主登记: {exc}')
                success = False
            if success and State.process_registry is not None:
                State.process_registry.pop(SINGLE_PROCESS_HOST_REGISTRY_NAME, None)
        if success:
            with cls._single_process_runtime_lock:
                if cls._single_process_runtime is runtime:
                    cls._single_process_runtime = None
            with cls._managers_lock:
                managers = tuple(cls._processes.values())
            for manager in managers:
                manager._uses_single_process = False
        return success

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
