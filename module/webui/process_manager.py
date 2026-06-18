import argparse
# 此文件专门用于管理 Alas 运行时各实例进程的生存周期及其子进程。
# 负责多账号多开时的进程池维护、状态（运行中、停止、异常）追踪及进程间通信的安全处理逻辑。
import os
import queue
import threading
import time
from multiprocessing import Process
from typing import Dict, List, Union

import inflection
from rich.console import Console, ConsoleRenderable

# 由于本文件不在 app.py 的同一进程或子进程中运行，
# 以下代码需要重复执行。
# 在导入 pywebio 之前先导入伪造模块，避免加载不必要的 PIL 模块。
from module.webui.fake_pil_module import *

import_fake_pil_module()

from module.logger import logger, set_file_logger, set_func_logger
from module.config.utils import DEFAULT_CONFIG_NAME
from module.submodule.submodule import load_mod
from module.submodule.utils import get_available_func, get_available_mod, get_available_mod_func, get_config_mod, \
    get_func_mod, list_mod_instance
from module.webui.setting import State


class ProcessManager:
    _processes: Dict[str, "ProcessManager"] = {}

    def __init__(self, config_name: str = DEFAULT_CONFIG_NAME) -> None:
        self.config_name = config_name
        self._renderable_queue: queue.Queue[ConsoleRenderable] = State.manager.Queue()
        self.renderables: List[ConsoleRenderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self._process: Process = None
        self._process_locks: Dict[str, threading.Lock] = {}
        self.thd_log_queue_handler: threading.Thread = None
        self._state_override: int = None
        self._state_override_deadline: float = None

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

    def _get_state_override(self) -> Union[int, None]:
        if self._state_override is None:
            return None
        if (
            self._state_override_deadline is not None
            and time.time() >= self._state_override_deadline
        ):
            self.clear_state_override()
            return None
        return self._state_override

    def start(self, func, ev: threading.Event = None) -> None:
        if not self.alive:
            if func is None:
                func = get_config_mod(self.config_name)
            args = (
                self.config_name,
                func,
                self._renderable_queue,
                ev,
            )
            self._process = Process(
                target=ProcessManager.run_process,
                args=args,
            )
            self._process.start()
            self.start_log_queue_handler()

    def start_log_queue_handler(self):
        if (
            self.thd_log_queue_handler is not None
            and self.thd_log_queue_handler.is_alive()
        ):
            return
        self.thd_log_queue_handler = threading.Thread(
            target=self._thread_log_queue_handler
        )
        self.thd_log_queue_handler.start()

    def stop(self) -> None:
        try:
            lock = self._process_locks[self.config_name]
        except KeyError:
            lock = threading.Lock()
            self._process_locks[self.config_name] = lock

        with lock:
            if self.alive:
                self._process.kill()
                self.renderables.append(
                    f"[{self.config_name}] exited. Reason: Manual stop\n"
                )
            if self.thd_log_queue_handler is not None:
                self.thd_log_queue_handler.join(timeout=1)
                if self.thd_log_queue_handler.is_alive():
                    logger.warning(
                        "Log queue handler thread does not stop within 1 seconds"
                    )
        logger.info(f"[{self.config_name}] exited")

    def _thread_log_queue_handler(self) -> None:
        while self.alive:
            try:
                log = self._renderable_queue.get(timeout=1)
            except queue.Empty:
                continue
            self.renderables.append(log)
            if len(self.renderables) > self.renderables_max_length:
                self.renderables = self.renderables[self.renderables_reduce_length :]
        logger.info("End of log queue handler loop")

    @property
    def alive(self) -> bool:
        if self._process is not None:
            return self._process.is_alive()
        else:
            return False

    @property
    def state(self) -> int:
        override_state = self._get_state_override()
        if override_state is not None:
            return override_state
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
        if config_name not in cls._processes:
            cls._processes[config_name] = ProcessManager(config_name)
        return cls._processes[config_name]

    @staticmethod
    def run_process(
        config_name, func: str, q: queue.Queue, e: threading.Event = None
    ) -> None:
        import sys
        if sys.platform != "win32":
            import resource
            try:
                _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                _target = 65536 if _hard == resource.RLIM_INFINITY else min(65536, _hard)
                if _soft < _target:
                    resource.setrlimit(resource.RLIMIT_NOFILE, (_target, _hard))
            except Exception:
                pass
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--electron", action="store_true", help="由 Electron 客户端运行时启用此参数。"
        )
        args, _ = parser.parse_known_args()
        State.electron = args.electron

        # 初始化日志器
        set_file_logger(name=config_name)
        if State.electron:
            # 参考 https://github.com/LmeSzinc/AzurLaneAutoScript/issues/2051
            logger.info("检测到 Electron 环境，移除标准输出日志处理器")
            from module.logger import console_hdlr
            logger.removeHandler(console_hdlr)
        set_func_logger(func=q.put)

        from module.config.config import AzurLaneConfig

        # 移除伪造的 PIL 模块，子进程需要使用真正的 PIL
        remove_fake_pil_module()

        # 设置环境变量，使预加载模块（如 al_ocr.py）可以提前读取配置
        os.environ['ALAS_CONFIG_NAME'] = config_name

        AzurLaneConfig.stop_event = e
        try:
            # 运行 AzurPilot
            if func == "alas":
                from alas import AzurLaneAutoScript

                if e is not None:
                    AzurLaneAutoScript.stop_event = e
                AzurLaneAutoScript(config_name=config_name).loop()
            elif func in get_available_func():
                from alas import AzurLaneAutoScript

                AzurLaneAutoScript(config_name=config_name).run(inflection.underscore(func), skip_first_screenshot=True)
            elif func in get_available_mod():
                mod = load_mod(func)

                if e is not None:
                    mod.set_stop_event(e)
                mod.loop(config_name)
            elif func in get_available_mod_func():
                getattr(load_mod(get_func_mod(func)), inflection.underscore(func))(config_name)
            else:
                logger.critical(f"杂鱼大叔，连功能模块都找不到吗？{func} 这种东西根本不存在啦~")
            if e is not None and e.is_set():
                logger.info(f"[{config_name}] exited. Reason: Update\n")
            else:
                logger.info(f"[{config_name}] exited. Reason: Finish\n")
        except Exception as ex:
            logger.exception(ex)

    @classmethod
    def running_instances(cls) -> List["ProcessManager"]:
        l = []
        for process in cls._processes.values():
            if process.alive:
                l.append(process)
        return l

    @staticmethod
    def restart_processes(
        instances: List[Union["ProcessManager", str]] = None, ev: threading.Event = None
    ):
        """
        更新重载后（或更新失败时），重启所有更新前正在运行的 AzurPilot 实例。

        Args:
            instances: 需要重启的实例列表，元素为 ProcessManager 或配置名称字符串。
            ev: 用于通知子进程执行更新的事件对象。
        """
        logger.hr("Restart alas")

        # 加载 MOD_CONFIG_DICT
        list_mod_instance()

        if instances is None:
            instances = []

        _instances = set()

        for instance in instances:
            if isinstance(instance, str):
                _instances.add(ProcessManager.get_manager(instance))
            elif isinstance(instance, ProcessManager):
                _instances.add(instance)

        try:
            with open("./config/reloadalas", mode="r") as f:
                for line in f.readlines():
                    line = line.strip()
                    _instances.add(ProcessManager.get_manager(line))
        except FileNotFoundError:
            pass

        for process in _instances:
            logger.info(f"Starting [{process.config_name}]")
            process.start(func=get_config_mod(process.config_name), ev=ev)

        try:
            os.remove("./config/reloadalas")
        except:
            pass
        logger.info("Start alas complete")
