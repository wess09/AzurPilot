"""AzurPilot 启动器：默认启动 WebUI，`--tui` 启动终端界面。

WebUI 模式下负责管理子进程（Uvicorn / FastAPI / Starlette）、处理热重载、
跨平台进程清理以及在独立子进程中执行 Python 依赖同步（uv sync）；
TUI 模式复用同一套存储初始化，直接在当前终端运行 Textual 界面。
"""

# 启动器行为参数集中在 module/base/runtime_params.py(WebUI 启动器域);
# 该模块零 import,对启动器最早期阶段无额外依赖。
from module.base.runtime_params import (
    DEPENDENCY_SYNC_START_RETRY_LIMIT,
    WEBUI_READY_TIMEOUT,
    WEBUI_RUNTIME_RETRY_LIMIT,
    WEBUI_STABLE_RUNTIME,
    WEBUI_START_RETRY_LIMIT,
)
import argparse
import errno
import os
import queue
import socket
import sys
import threading
import time
from multiprocessing import Event, Process, Queue, set_start_method
from pathlib import Path
from typing import Optional

if sys.platform != "win32":
    import resource
    try:
        _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        _target = 65536 if _hard == resource.RLIM_INFINITY else min(65536, _hard)
        if _soft < _target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (_target, _hard))
    except Exception:
        pass

from deploy.uv import (
    DEPENDENCY_SYNC_TIMEOUT,
    dependency_sync_service,
    log_command_output,
    redact_sensitive_text,
)
from module.logger import get_log_file_path, logger
from module.runtime import worker_registry
from module.runtime.process_control import pid_exists, stop_process, stop_process_tree
from module.runtime.setting import (
    State,
    clear_dependency_sync_pending,
    is_dependency_sync_pending,
)



DEPENDENCY_SYNC_RESPONSE_TIMEOUT = DEPENDENCY_SYNC_TIMEOUT + 60

# 退出码定义
EXIT_SUCCESS = 0
EXIT_STARTUP_FAILURE = 70              # 通用/未分类启动失败
EXIT_WORKER_CLEANUP_FAILURE = 71       # 残留 worker 未能回收，无法保证任务唯一
EXIT_DEPENDENCY_SYNC_FAILURE = 72      # 依赖同步未就绪或同步失败
EXIT_FRONTEND_BUILD_FAILURE = 73       # React 前端构建失败
EXIT_SUBPROCESS_SPAWN_FAILURE = 74     # WebUI 子进程连续启动失败
EXIT_PORT_LISTEN_TIMEOUT = 75          # WebUI 子进程端口监听/就绪超时
EXIT_WEBUI_RUNTIME_CRASH = 76          # WebUI 启动就绪后反复意外崩溃
EXIT_PROCESS_TERMINATE_FAILURE = 77    # WebUI 子进程未能终止/无法停止
EXIT_IPC_FAILURE = 78                  # 进程间通信或重载状态读取异常


class FatalStartupError(Exception):
    """启动阶段的致命错误。

    本进程无法再提供服务，需以非零退出码结束后由启动器报告。

    Attributes:
        reason (str): 失败原因说明。
        exit_code (int): 进程退出码。
    """

    def __init__(self, reason: str, exit_code: int = EXIT_STARTUP_FAILURE) -> None:
        """初始化致命启动异常。

        Args:
            reason (str): 失败原因。
            exit_code (int, optional): 退出码。默认为 EXIT_STARTUP_FAILURE。
        """
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code


def reload_requested(argv: list[str]) -> bool:
    """判断启动参数是否要求监听 Python 源码并自动重载。

    只接受精确的 ``-r`` / ``--reload``，避免把 pytest 的 ``-ra`` 或
    其他以 r 开头的短选项误判为重载开关。

    Args:
        argv (list[str]): 不含程序名的命令行参数列表。

    Returns:
        bool: 指定了 ``-r`` 或 ``--reload`` 时返回 True。
    """
    return any(arg in ("-r", "--reload") for arg in argv)


class SourceWatcher:
    """轮询项目内 Python 源码，检测到稳定的变更后请求重建 WebUI。

    启动器必须保持轻量，因此只用标准库轮询 mtime/size，不引入 watchdog。
    编辑器保存常伴随多次写入，故要求连续两轮快照一致且超过去抖时间才触发。

    Attributes:
        root (Path): 监听根目录，默认为 gui.py 所在目录。
        debounce (float): 变更稳定判定的最短秒数。
        baseline (dict | None): 上一次确认的源码快照。
    """

    EXCLUDED_DIRS = frozenset({
        ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
        "build", "dist", ".pytest_cache", ".ruff_cache", ".mypy_cache",
        ".idea", ".vscode", "log", "logs", "config", "tests",
        "cache", "dev_tools", "licenses", "docs", "assets", "bin",
    })
    MAX_FILES = 5000

    def __init__(self, root, debounce: float = 0.8, interval: float = 1.5) -> None:
        self.root = Path(root).resolve()
        self.debounce = debounce
        self.interval = interval
        self.last_scan = None
        self.baseline = None
        self.pending_since = None
        self.pending_snapshot = None

    @classmethod
    def _excluded(cls, name: str) -> bool:
        # tmp* 是运行期临时目录（测试/设备子进程会创建），不属于源码。
        return (name in cls.EXCLUDED_DIRS or name.startswith(".")
                or name.startswith("tmp"))

    def _scan(self, directory: str, state: dict) -> None:
        """递归扫描目录；DirEntry 复用目录枚举时的 stat 缓存，避免逐文件系统调用。"""
        try:
            with os.scandir(directory) as entries:
                items = list(entries)
        except OSError:
            return
        for entry in items:
            if len(state) >= self.MAX_FILES:
                return
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if not self._excluded(entry.name):
                    self._scan(entry.path, state)
            elif entry.name.endswith(".py"):
                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                state[entry.path] = (stat.st_mtime_ns, stat.st_size)

    def snapshot(self) -> dict[str, tuple[int, int]]:
        """扫描全部受监控的 .py 文件，返回路径到 (mtime_ns, size) 的映射。"""
        state = {}
        self._scan(str(self.root), state)
        return state

    @staticmethod
    def diff(old: dict, new: dict) -> list[str]:
        """列出新增、删除或内容指纹变化的文件路径。"""
        return sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))

    def poll(self) -> list[str]:
        """返回已稳定的变更路径；首次调用只建立基线，不触发重载。"""
        now = time.monotonic()
        if (self.baseline is not None and self.last_scan is not None
                and now - self.last_scan < self.interval):
            return []
        self.last_scan = now
        current = self.snapshot()
        if self.baseline is None:
            self.baseline = current
            return []
        changed = self.diff(self.baseline, current)
        if not changed:
            self.pending_since = None
            self.pending_snapshot = None
            return []
        if self.pending_snapshot != current:
            self.pending_since = time.monotonic()
            self.pending_snapshot = current
            return []
        if time.monotonic() - self.pending_since < self.debounce:
            return []
        self.baseline = current
        self.pending_since = None
        self.pending_snapshot = None
        return changed


def _signal_source_change(watcher: SourceWatcher, event) -> bool:
    """把稳定的源码变更转换为已有的重启事件；返回是否触发重载。"""
    changed = watcher.poll()
    if not changed:
        return False
    preview = ", ".join(
        os.path.relpath(path, watcher.root) for path in changed[:5]
    )
    if len(changed) > 5:
        preview += f" …共 {len(changed)} 个文件"
    logger.info("[GUI] 检测到 %d 个 Python 源码变更，准备重建 WebUI：%s",
                len(changed), preview)
    if any(Path(path).name == "gui.py" for path in changed):
        logger.warning("[GUI] gui.py 自身已变更：本次只重建 WebUI 子进程，"
                       "启动器逻辑需手动重启 gui.py 才会生效")
    event.set()
    return True


def _is_ipv6_unavailable_error(exc: OSError) -> bool:
    """判断 IPv6 地址族在当前系统中是否不可用。

    Args:
        exc (OSError): 捕获到的套接字系统异常。

    Returns:
        bool: 当前错误属于 IPv6 不支持时返回 True，否则返回 False。
    """
    errno_values = {
        errno.EAFNOSUPPORT,
        errno.EPROTONOSUPPORT,
        errno.EADDRNOTAVAIL,
        getattr(errno, "ENODEV", -1),
        getattr(errno, "ENOPROTOOPT", -1),
        getattr(errno, "EOPNOTSUPP", -1),
    }
    winerror_values = {10042, 10043, 10045, 10047, 10049}
    return exc.errno in errno_values or getattr(exc, "winerror", None) in winerror_values


def _create_dual_stack_sockets(
    port: int,
    backlog: int = 2048,
    *,
    allow_ipv6_fallback: bool = False,
) -> list[socket.socket]:
    """创建同端口的 IPv4/IPv6 WebUI socket，并可降级为 IPv4。

    Args:
        port (int): 绑定监听端口。
        backlog (int, optional): 套接字等待队列大小。默认为 2048。
        allow_ipv6_fallback (bool, optional): 是否允许在 IPv6 不可用时降级。默认为 False。

    Returns:
        list[socket.socket]: 创建并监听的套接字列表。

    Raises:
        OSError: 端口占用或绑定失败时抛出。
    """
    sockets = []
    listen_port = port
    try:
        for family, address in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
            listener = None
            try:
                listener = socket.socket(family, socket.SOCK_STREAM)
                if os.name != "nt":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                # WebUI 明确支持局域网/远程访问，因此双栈监听所有接口是产品行为；
                # 访问控制由 WebSocket 鉴权、Origin/远程访问网关等应用层边界负责。
                # codeql[py/bind-socket-all-network-interfaces]
                listener.bind((address, listen_port))
                listener.listen(backlog)
                listener.setblocking(False)
            except OSError as exc:
                if listener is not None:
                    listener.close()
                if (
                    family == socket.AF_INET6
                    and allow_ipv6_fallback
                    and _is_ipv6_unavailable_error(exc)
                ):
                    break
                raise
            sockets.append(listener)
            if listen_port == 0:
                listen_port = listener.getsockname()[1]
        return sockets
    except Exception:
        for listener in sockets:
            listener.close()
        raise


def _watch_server_started(server, ready_event: Event) -> None:
    """在 Uvicorn 完成监听后通知父进程。

    Args:
        server: Uvicorn Server 实例。
        ready_event (Event): 用于通知就绪的 multiprocessing.Event 事件。
    """
    while not server.started:
        if server.should_exit or server.force_exit:
            return
        time.sleep(0.1)
    ready_event.set()


def _run_uvicorn_server(config, ready_event: Optional[Event] = None, sockets=None) -> None:
    """运行 Uvicorn，并在端口实际监听后发送就绪信号。

    Args:
        config: uvicorn.Config 配置对象。
        ready_event (Optional[Event], optional): 就绪信号事件。默认为 None。
        sockets: 预先绑定的套接字列表。默认为 None。
    """
    import uvicorn

    server = uvicorn.Server(config)
    if ready_event is not None:
        threading.Thread(
            target=_watch_server_started,
            args=(server, ready_event),
            daemon=True,
            name="webui-ready-watcher",
        ).start()
    server.run(sockets=sockets)


def func(
    ev: Optional[Event],
    dependency_sync_event: Optional[Event] = None,
    ready_event: Optional[Event] = None,
):
    """主函数：运行 Web 服务。

    Args:
        ev: 可选的重启事件，用于热重载功能。
        dependency_sync_event: 请求父进程同步依赖的事件。
        ready_event: Uvicorn 完成监听后通知父进程的事件。

    Raises:
        Exception: WebUI 启动失败时向外抛出。
    """
    # WebUI 子进程的日志只落独立文件；stdout/stderr 保持原样，任务子进程照常继承控制台。
    from module.logger import set_console_logger, set_file_logger
    try:
        set_file_logger('webui')
        logger.info('[GUI] WebUI 服务开始初始化，后续详细日志：%s', logger.log_file)
        set_console_logger(False)
    except OSError:
        logger.warning('[GUI] WebUI 文件日志不可用，继续输出到控制台')

    import argparse
    import asyncio
    import uvicorn

    # 平台特定的asyncio配置
    if sys.platform == "darwin":
        # macOS: 禁用fork安全检查以避免Mach端口冲突
        os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    elif sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    State.restart_event = ev
    State.dependency_sync_event = dependency_sync_event

    from deploy.frontend import ensure_frontend
    ensure_frontend()

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="AzurPilot Web 服务")
    parser.add_argument(
        "--host",
        type=str,
        help="监听主机。默认使用部署设置中的WebuiHost",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="监听端口。默认使用部署设置中的WebuiPort",
    )
    parser.add_argument(
        "-k", "--key", type=str, help="AzurPilot密码。默认无密码"
    )
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="已废弃，React 静态资源始终由本地提供",
    )
    parser.add_argument(
        "--electron", action="store_true", help="由Electron客户端运行"
    )
    parser.add_argument(
        "--ssl-key", dest="ssl_key", type=str, help="SSL密钥文件路径，用于HTTPS支持"
    )
    parser.add_argument(
        "--ssl-cert", type=str, help="SSL证书文件路径，用于HTTPS支持"
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="启动时运行指定配置的AzurPilot",
    )
    # -r/--reload 是父启动器参数；这里保持 parse_known_args 忽略它，
    # 不声明同名选项，避免 --r 缩写与 --run 产生歧义。
    args, _ = parser.parse_known_args()

    # 配置服务器设置
    host = args.host or State.deploy_config.WebuiHost or "0.0.0.0"
    port = args.port or int(State.deploy_config.WebuiPort) or 25548
    ssl_key = args.ssl_key or State.deploy_config.WebuiSSLKey
    ssl_cert = args.ssl_cert or State.deploy_config.WebuiSSLCert
    ssl = ssl_key is not None and ssl_cert is not None
    State.electron = args.electron
    State.webui_host = host

    # 记录启动器配置
    logger.hr("Launcher config")
    logger.attr("Host", host)
    logger.attr("Port", port)
    logger.attr("SSL", ssl)
    logger.attr("Electron", args.electron)
    logger.attr("Reload", ev is not None)

    # Electron客户端特定处理
    if State.electron:
        # https://github.com/LmeSzinc/AzurLaneAutoScript/issues/2051
        logger.info("[GUI] 检测到 Electron，移除标准输出日志处理器")
        from module.logger import set_console_logger
        set_console_logger(False)

    # 验证SSL配置
    if ssl_cert is None and ssl_key is not None:
        logger.error("[GUI] 提供了SSL密钥但未提供证书。请同时提供SSL密钥和证书。")
    elif ssl_key is None and ssl_cert is not None:
        logger.error("[GUI] 提供了SSL证书但未提供密钥。请同时提供SSL密钥和证书。")

    # 通配地址显式创建两个 socket，避免 Windows 将 IPv6 wildcard 作为仅 IPv6 监听。
    try:
        uvicorn_options = {
            "host": host,
            "port": port,
            "factory": True,
            # 文件接口允许 8 MiB；普通请求仍由 Session 按 1 MiB 校验。
            "ws_max_size": 8 * 1024 * 1024,
            "ws_max_queue": 16,
        }
        if ssl:
            uvicorn_options.update(
                ssl_keyfile=ssl_key,
                ssl_certfile=ssl_cert,
            )

        if host in ("0.0.0.0", "::", "[::]"):
            if host in ("::", "[::]"):
                uvicorn_options["host"] = "::"
            config = uvicorn.Config("module.api.app:create_app", **uvicorn_options)
            sockets = _create_dual_stack_sockets(
                port,
                backlog=config.backlog,
                allow_ipv6_fallback=host == "0.0.0.0",
            )
            try:
                if len(sockets) == 2:
                    logger.info(
                        f"[GUI] WebUI 同时监听 IPv4 0.0.0.0:{port} 与 IPv6 [::]:{port}"
                    )
                else:
                    logger.warning(
                        f"[GUI] 系统未启用 IPv6，WebUI 仅监听 IPv4 0.0.0.0:{port}"
                    )
                _run_uvicorn_server(config, ready_event=ready_event, sockets=sockets)
            finally:
                for listener in sockets:
                    listener.close()
        else:
            config = uvicorn.Config("module.api.app:create_app", **uvicorn_options)
            _run_uvicorn_server(config, ready_event=ready_event)
    except Exception as e:
        logger.exception_context(
            title='WebUI 服务启动失败',
            exc=e,
            impact='WebUI 进程将退出，无法管理 AzurPilot。',
            action='检查端口是否被占用、SSL 证书和密钥是否匹配，并确认依赖已通过 uv sync --frozen 安装。',
            level=50,
        )
        raise


def _stop_process(process, timeout=5) -> bool:
    """通过本地句柄逐级停止服务，退出结果由 multiprocessing 回收。

    Args:
        process: 进程对象。
        timeout (int, optional): 超时秒数。默认为 5。

    Returns:
        bool: 进程已停止返回 True，否则返回 False。
    """
    return stop_process(process, timeout=timeout)


def _wait_for_webui_ready(process, ready_event: Event, timeout=WEBUI_READY_TIMEOUT) -> bool:
    """等待 WebUI 完成 ASGI 启动和 socket 监听。

    Args:
        process: WebUI 进程对象。
        ready_event (Event): 就绪通知事件。
        timeout (int, optional): 最长等待超时时间（秒）。默认为 WEBUI_READY_TIMEOUT。

    Returns:
        bool: 在超时时间内成功就绪且进程存活返回 True，否则返回 False。
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if ready_event.wait(min(0.2, remaining)):
            return process.is_alive()
        if not process.is_alive():
            return False


def _stop_process_tree(process, name: str) -> bool:
    """统一回收服务进程树，保留根进程的 multiprocessing 退出状态。

    Args:
        process: 进程对象或进程树根。
        name (str): 进程名称（用于日志展示）。

    Returns:
        bool: 进程树成功终止返回 True，否则返回 False。
    """
    return stop_process_tree(process, name=name, timeout=0)


def _stop_registered_worker(pid: int, name: str, record: dict) -> bool:
    """按持久化身份回收 worker，不按缓存 PID 发信号。

    Args:
        pid (int): worker 进程 PID。
        name (str): worker 标识名称。
        record (dict): 登记的进程属性记录。

    Returns:
        bool: 成功终止返回 True，否则返回 False。
    """
    if record.get("pid") != pid:
        return False
    return stop_process_tree(record=record, name=f"worker {name}", timeout=0)


def _stop_registered_workers(
    owner_pid: int | None,
    discard_reused: bool = False,
) -> bool:
    """回收指定 WebUI 所登记的 worker，覆盖根进程已异常退出的场景。

    Args:
        owner_pid (int | None): 所属父 WebUI 进程 PID。
        discard_reused (bool, optional): 是否丢弃 PID 已被系统复用的陈旧记录。默认为 False。

    Returns:
        bool: 全部关联 worker 均被安全停止并清除登记返回 True，否则返回 False。
    """
    if owner_pid is None:
        return True
    try:
        workers = worker_registry.get_workers(owner_pid)
    except RuntimeError as exc:
        logger.error(f"[GUI] 无法读取 WebUI worker 登记: {exc}")
        return False

    stopped = True
    for name, record in workers.items():
        try:
            pid = int(record["pid"])
            matches = worker_registry.process_matches(record)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            logger.error(f"[GUI] worker 登记无效 ({name}): {exc}")
            stopped = False
            continue
        if matches is None:
            continue
        if not matches:
            if discard_reused:
                logger.warning(
                    f"[GUI] worker PID 已复用，丢弃旧 owner 的陈旧登记: {name} (PID: {pid})"
                )
            else:
                logger.error(
                    f"[GUI] worker PID 已复用，拒绝终止未知进程: {name} (PID: {pid})"
                )
                stopped = False
            continue
        stopped = _stop_registered_worker(pid, name, record) and stopped

    if stopped:
        try:
            worker_registry.clear_owner(owner_pid)
        except RuntimeError as exc:
            logger.error(f"[GUI] 无法清除 WebUI worker 登记: {exc}")
            return False
    return stopped


def _pid_exists(pid: int) -> bool:
    """检查指定 PID 的进程是否存在。

    Args:
        pid (int): 进程 ID。

    Returns:
        bool: 存在返回 True，不存在返回 False。
    """
    return pid_exists(pid)


def _recover_orphaned_workers() -> bool:
    """启动前回收上次异常退出的 WebUI worker。

    Returns:
        bool: 成功回收或无需回收返回 True，存在活跃旧实例冲突或清理失败返回 False。
    """
    try:
        owner_record = worker_registry.get_owner_record()
    except RuntimeError as exc:
        logger.error(f"[GUI] 无法读取旧 WebUI worker 登记: {exc}")
        return False
    if owner_record is None:
        return True

    owner_pid = owner_record["pid"]
    try:
        owner_matches = worker_registry.process_matches(owner_record)
    except RuntimeError as exc:
        # 兼容旧登记文件：没有创建时间时，只有确认 PID 已消失才能安全回收。
        if not _pid_exists(owner_pid):
            logger.warning(
                f"[GUI] 旧 WebUI 所有者登记缺少身份信息，回收已退出实例 (PID: {owner_pid})"
            )
            return _stop_registered_workers(owner_pid, discard_reused=True)
        logger.error(
            f"[GUI] 无法验证旧 WebUI 所有者 (PID: {owner_pid}): {exc}，拒绝启动第二个 WebUI"
        )
        return False

    if owner_matches is True:
        logger.error(
            f"[GUI] 检测到仍在运行的 WebUI 所有者 (PID: {owner_pid})，拒绝启动第二个 WebUI"
        )
        return False
    if owner_matches is False:
        logger.warning(
            f"[GUI] 旧 WebUI 所有者 PID 已复用，回收其登记的 worker (PID: {owner_pid})"
        )
    else:
        logger.warning(f"[GUI] 回收上次异常退出 WebUI 的 worker (PID: {owner_pid})")
    return _stop_registered_workers(owner_pid, discard_reused=True)


def _stop_dependency_sync_service_tree(process) -> bool:
    """终止卡住的依赖同步服务及其 uv 子进程。

    Args:
        process: 同步服务进程对象。

    Returns:
        bool: 成功停止返回 True，否则返回 False。
    """
    return _stop_process_tree(process, "依赖同步服务")


def _stop_webui_process_tree(process) -> bool:
    """终止 WebUI 及其 AzurPilot worker 子进程，避免重启后重复控制设备。

    Args:
        process: WebUI 进程对象。

    Returns:
        bool: 根进程及所有登记的 worker 均成功停止返回 True，否则返回 False。
    """
    root_stopped = _stop_process_tree(process, "WebUI")
    if not root_stopped:
        # 根 WebUI 仍可能继续创建或管理 worker，不能清除其登记。
        return False
    owner_pid = getattr(process, "pid", None) if process is not None else None
    workers_stopped = _stop_registered_workers(owner_pid, discard_reused=True)
    return root_stopped and workers_stopped


def _start_dependency_sync_service():
    """启动空闲的依赖同步服务，避免 WebUI 进程修改自身环境。

    Returns:
        tuple[Process, Queue, Queue]: 进程对象、请求队列、响应队列。
    """
    request_queue = Queue()
    response_queue = Queue()
    process = Process(
        target=dependency_sync_service,
        args=(request_queue, response_queue),
        daemon=True,
        name="dependency-sync",
    )
    process.start()
    logger.info(f"[GUI] 依赖同步服务已启动 (PID: {process.pid})")
    return process, request_queue, response_queue


def _start_dependency_sync_service_with_retry():
    """有限重试启动依赖同步服务，避免启动器因单次进程错误直接崩溃。

    Returns:
        tuple[Process, Queue, Queue] | None: 启动成功返回元组，全部尝试失败返回 None。
    """
    for attempt in range(1, DEPENDENCY_SYNC_START_RETRY_LIMIT + 1):
        try:
            return _start_dependency_sync_service()
        except Exception as exc:
            logger.exception_context(
                title='依赖同步服务启动失败',
                exc=exc,
                impact='当前 WebUI 无法安全执行自动更新依赖。',
                action='检查系统进程权限和 Python 环境；启动器会有限重试。',
                level=50,
            )
            if attempt < DEPENDENCY_SYNC_START_RETRY_LIMIT:
                logger.warning(
                    f"[GUI] 依赖同步服务启动失败，将在 {attempt} 秒后重试 "
                    f"({attempt}/{DEPENDENCY_SYNC_START_RETRY_LIMIT})"
                )
                time.sleep(attempt)
    return None


def _stop_dependency_sync_service(process, request_queue) -> bool:
    """停止依赖同步服务，确保启动器关闭时不遗留后端进程。

    Args:
        process: 依赖同步进程对象。
        request_queue: 请求消息队列。

    Returns:
        bool: 服务已成功终止返回 True，终止失败返回 False。
    """
    if not process:
        return True
    if not process.is_alive():
        try:
            process.join(timeout=0)
        except (OSError, ValueError, AssertionError):
            pass
        return True

    try:
        request_queue.put("shutdown")
        process.join(timeout=5)
    except Exception as exc:
        logger.warning(f"[GUI] 停止依赖同步服务失败: {exc}")

    if process.is_alive():
        return _stop_dependency_sync_service_tree(process)
    return True


def _sync_dependencies(
    process,
    request_queue,
    response_queue,
    timeout=DEPENDENCY_SYNC_RESPONSE_TIMEOUT,
) -> bool:
    """向独立服务请求同步，并将完整 uv 输出写入 GUI 日志。

    Args:
        process: 依赖同步子进程。
        request_queue: 请求队列。
        response_queue: 响应队列。
        timeout (int, optional): 超时时间（秒）。默认为 DEPENDENCY_SYNC_RESPONSE_TIMEOUT。

    Returns:
        bool: 同步成功返回 True，失败或超时返回 False。
    """
    logger.hr("Update Dependencies", 0)
    if not process or not process.is_alive():
        logger.critical("Dependency sync service is not running")
        return False

    try:
        request_queue.put("sync")
    except (OSError, EOFError, ValueError, queue.Full) as exc:
        logger.critical(f"依赖同步请求发送失败，WebUI 不会重启: {exc}")
        return False
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.critical(f"依赖同步在 {timeout} 秒后超时，WebUI 不会重启")
            return False
        try:
            result = response_queue.get(timeout=min(1, remaining))
        except queue.Empty:
            if not process.is_alive():
                logger.critical("Dependency sync service exited unexpectedly")
                return False
            continue
        except (OSError, EOFError, ValueError) as exc:
            logger.critical(f"依赖同步服务通信失败，WebUI 不会重启: {exc}")
            return False

        command = result.get("command") or []
        if command:
            logger.info(f"Execute: {redact_sensitive_text(command)}")
        log_command_output(logger, result.get("output", ""))
        if result.get("success"):
            logger.info("Dependency sync success")
            return True

        error = redact_sensitive_text(result.get("error", "unknown error"))
        logger.critical(f"uv sync failed: {error}")
        return False


def _complete_pending_dependency_sync(
    process,
    request_queue,
    response_queue,
    *,
    force: bool = False,
) -> bool:
    """完成更新遗留的依赖同步，并仅在成功后清除持久化标记。

    Args:
        process: 同步子进程。
        request_queue: 请求队列。
        response_queue: 响应队列。
        force (bool, optional): 是否强制同步。默认为 False。

    Returns:
        bool: 无待处理或同步完成返回 True，读取失败或同步失败返回 False。
    """
    try:
        pending = is_dependency_sync_pending()
    except OSError as exc:
        logger.critical(f"无法读取依赖同步待处理状态，WebUI 不会启动: {exc}")
        return False

    if not pending and not force:
        return True

    if pending:
        logger.warning("检测到未完成的依赖同步，将在启动 WebUI 前恢复")
    if not _sync_dependencies(process, request_queue, response_queue):
        return False

    if pending:
        try:
            clear_dependency_sync_pending()
        except OSError as exc:
            logger.critical(f"无法清除依赖同步待处理状态，WebUI 不会启动: {exc}")
            return False
    return True


def _prepare_dependency_sync_before_webui_start(
    service,
    request_queue,
    response_queue,
    *,
    force: bool = False,
):
    """在创建 WebUI 前完成必要的依赖同步，失败时拒绝启动子进程。

    Args:
        service: 当前同步服务进程。
        request_queue: 请求队列。
        response_queue: 响应队列。
        force (bool, optional): 是否强制触发同步。默认为 False。

    Returns:
        tuple[bool, Process | None, Queue | None, Queue | None]:
            就绪状态、服务进程、请求队列、响应队列。
    """
    try:
        pending = is_dependency_sync_pending()
    except OSError as exc:
        logger.error_context(
            title='无法读取启动前依赖同步状态',
            exc=exc,
            impact='无法确认 Python 环境是否与已更新代码匹配，WebUI 不会启动。',
            action='检查 config 目录读写权限后重新启动。',
            level=50,
        )
        return False, service, request_queue, response_queue

    sync_required = pending or force
    if not sync_required:
        return True, service, request_queue, response_queue

    if service is not None:
        # 更新后必须使用新源码创建同步服务，不能复用旧环境中的服务进程。
        if not _stop_dependency_sync_service(service, request_queue):
            logger.error_context(
                title='依赖同步服务未能停止',
                reason='旧依赖同步服务或其 uv 子进程仍在运行。',
                impact='继续同步可能并发修改 Python 环境，WebUI 不会启动。',
                action='结束残留 dependency-sync/uv 进程后重新启动。',
                level=50,
            )
            return False, service, request_queue, response_queue
        service = None
        request_queue = None
        response_queue = None

    service_data = _start_dependency_sync_service_with_retry()
    if service_data is None:
        logger.error_context(
            title='依赖同步服务无法启动',
            reason='连续多次创建依赖同步子进程失败。',
            impact='当前环境需要同步，WebUI 未启动以避免运行在不匹配的依赖中。',
            action='检查系统进程权限和 Python 环境后重新启动。',
            level=50,
        )
        return False, None, None, None

    service, request_queue, response_queue = service_data
    if not _complete_pending_dependency_sync(
        service,
        request_queue,
        response_queue,
        force=sync_required,
    ):
        logger.error_context(
            title='创建 WebUI 前依赖同步失败',
            reason='检测到更新或待处理的依赖同步状态，但同步未能完成。',
            impact='为避免以不匹配的 Python 环境启动 WebUI，父进程将退出。',
            action='检查 uv sync 输出、磁盘权限和 Python 环境后重新启动。',
            level=50,
        )
        return False, service, request_queue, response_queue
    return True, service, request_queue, response_queue


def run_webui_supervisor(watch_sources: bool = False) -> int:
    """监督热重载 WebUI 子进程及其独立依赖同步服务，返回本进程退出码。

    Args:
        watch_sources (bool): 监听项目内 .py 变更，稳定后复用重启通道重建 WebUI。

    Returns:
        int: 退出状态码（0 表示正常退出，非零表示发生致命故障）。
    """
    watcher = SourceWatcher(Path(__file__).resolve().parent) if watch_sources else None
    if watcher is not None:
        watcher.poll()  # 建立基线，避免把启动时已有的源码当作变更
        logger.info("[GUI] 已启用 Python 源码监听：%s（仅 .py，去抖 %.1f 秒）",
                    watcher.root, watcher.debounce)
        logger.warning("[GUI] 源码变更会终止当前 WebUI 及其 AzurPilot worker 后重建，"
                       "请勿在挂机任务中使用 -r")
    fatal_error: Optional[FatalStartupError] = None
    should_exit = False
    process = None
    service = None
    service_request_queue = None
    service_response_queue = None
    startup_failures = 0
    runtime_failures = 0
    force_dependency_sync = False
    logger.info('[GUI] 检查并回收上次异常退出的 worker')
    if not _recover_orphaned_workers():
        fatal_error = FatalStartupError(
            "残留 worker 未能回收，无法保证设备控制任务唯一",
            exit_code=EXIT_WORKER_CLEANUP_FAILURE,
        )
        logger.error(
            "[GUI] AzurPilot Web服务启动失败：%s (退出码: %d)",
            fatal_error.reason,
            fatal_error.exit_code,
        )
        return fatal_error.exit_code
    try:
        while not should_exit:
            logger.info('[GUI] 检查依赖同步状态，准备 WebUI 启动环境')
            stage_started = time.perf_counter()
            (
                ready_to_start,
                service,
                service_request_queue,
                service_response_queue,
            ) = _prepare_dependency_sync_before_webui_start(
                service,
                service_request_queue,
                service_response_queue,
                force=force_dependency_sync,
            )
            if not ready_to_start:
                raise FatalStartupError(
                    "依赖同步未就绪，WebUI 无法启动",
                    exit_code=EXIT_DEPENDENCY_SYNC_FAILURE,
                )
            force_dependency_sync = False
            logger.info('[GUI] 依赖已就绪，耗时 %.2f 秒', time.perf_counter() - stage_started)

            # 首次安装前端依赖可能较慢，必须在子进程监听计时开始前完成。
            logger.info('[GUI] 检查前端静态资源，必要时安装依赖并构建')
            stage_started = time.perf_counter()
            from deploy.frontend import ensure_frontend
            try:
                ensure_frontend()
                logger.info('[GUI] 前端静态资源已就绪，耗时 %.2f 秒', time.perf_counter() - stage_started)
            except Exception as exc:
                logger.exception_context(
                    title='React 前端构建失败',
                    exc=exc,
                    impact='前端静态资源不可用，停止创建 WebUI 子进程。',
                    action='检查 Node.js 安装和 npm 输出，修复后重新启动。',
                    level=50,
                )
                raise FatalStartupError(
                    "React 前端构建失败",
                    exit_code=EXIT_FRONTEND_BUILD_FAILURE,
                ) from exc

            event = Event()
            dependency_sync_event = Event()
            ready_event = Event()
            process = None
            try:
                process = Process(
                    target=func,
                    args=(event, dependency_sync_event, ready_event),
                    name="gui",
                )
                process.start()
            except Exception as exc:
                _stop_webui_process_tree(process)
                startup_failures += 1
                logger.exception_context(
                    title='WebUI 子进程启动失败',
                    exc=exc,
                    impact='当前 WebUI 无法提供服务。',
                    action='检查进程权限和系统资源；启动失败会自动有限重试。',
                    level=50,
                )
                if startup_failures >= WEBUI_START_RETRY_LIMIT:
                    raise FatalStartupError(
                        "WebUI 子进程连续启动失败",
                        exit_code=EXIT_SUBPROCESS_SPAWN_FAILURE,
                    )
                time.sleep(startup_failures)
                continue
            logger.info(f"[GUI] 启动AzurPilot Web服务 (PID: {process.pid})")
            logger.info('[GUI] 等待 WebUI 服务完成监听（超时 %s 秒）；服务日志：%s',
                        WEBUI_READY_TIMEOUT, get_log_file_path('webui').resolve())

            try:
                ready = _wait_for_webui_ready(process, ready_event)
            except KeyboardInterrupt:
                logger.info("[GUI] 收到KeyboardInterrupt，退出中...")
                should_exit = True
                _stop_webui_process_tree(process)
                break

            if not ready:
                stopped = _stop_webui_process_tree(process)
                startup_failures += 1
                if not stopped:
                    logger.error_context(
                        title='WebUI 子进程启动失败且无法停止',
                        reason='子进程未在就绪期限内监听，且终止后仍存活。',
                        impact='继续启动新 WebUI 会产生端口冲突。',
                        action='手动结束残留 gui.py 子进程后重新启动。',
                        level=50,
                    )
                    raise FatalStartupError(
                        "WebUI 子进程未就绪且无法停止",
                        exit_code=EXIT_PROCESS_TERMINATE_FAILURE,
                    )
                elif startup_failures >= WEBUI_START_RETRY_LIMIT:
                    logger.error_context(
                        title='WebUI 子进程未能完成启动',
                        reason=f'连续 {startup_failures} 次未在 {WEBUI_READY_TIMEOUT} 秒内完成监听。',
                        impact='WebUI 未启动，父进程将退出。',
                        action='检查端口占用、WebUI 日志和 Python 环境后重新启动。',
                        level=50,
                    )
                    raise FatalStartupError(
                        f'连续 {startup_failures} 次未在 {WEBUI_READY_TIMEOUT} 秒内完成监听',
                        exit_code=EXIT_PORT_LISTEN_TIMEOUT,
                    )
                else:
                    logger.warning(
                        f"[GUI] WebUI 未就绪，将在 {startup_failures} 秒后重试 "
                        f"({startup_failures}/{WEBUI_START_RETRY_LIMIT})"
                    )
                    time.sleep(startup_failures)
                continue

            startup_failures = 0
            ready_at = time.monotonic()
            logger.info(f"[GUI] WebUI 服务已就绪 (PID: {process.pid})")

            while not should_exit:
                if watcher is not None:
                    # 监听是开发辅助能力，扫描异常不能让监督器退出。
                    try:
                        _signal_source_change(watcher, event)
                    except Exception as exc:
                        logger.warning("[GUI] 源码监听扫描失败，本轮跳过：%s", exc)
                try:
                    # 等待重启事件，超时1秒；监听器每轮轮询一次源码快照
                    restart_triggered = event.wait(1)
                except KeyboardInterrupt:
                    logger.info("[GUI] 收到KeyboardInterrupt，退出中...")
                    should_exit = True
                    break
                except Exception as e:
                    logger.exception_context(
                        title='WebUI 重启事件处理失败',
                        exc=e,
                        impact='WebUI 将停止热重载并退出。',
                        action='检查 WebUI 子进程状态和系统进程权限。',
                        level=50,
                    )
                    raise FatalStartupError(
                        "WebUI 重启事件处理失败",
                        exit_code=EXIT_IPC_FAILURE,
                    ) from e

                if restart_triggered:
                    logger.info("[GUI] 重启事件触发，终止当前服务...")
                    if not _stop_webui_process_tree(process):
                        logger.error_context(
                            title='WebUI 子进程未能停止',
                            reason='已发送 terminate 和 kill，但旧 WebUI 子进程仍然存活。',
                            impact='继续拉起新 WebUI 会与旧进程争抢监听端口。',
                            action='检查系统进程权限，手动结束残留的 gui.py 子进程后重新启动。',
                            level=50,
                        )
                        raise FatalStartupError(
                            "重启时旧 WebUI 子进程未能停止",
                            exit_code=EXIT_PROCESS_TERMINATE_FAILURE,
                        )
                    try:
                        force_dependency_sync = dependency_sync_event.is_set()
                    except OSError as exc:
                        logger.error_context(
                            title='无法读取依赖同步状态',
                            exc=exc,
                            impact='无法确认更新后的环境是否已同步，WebUI 不会重启。',
                            action='检查 config 目录读写权限后重新启动。',
                            level=50,
                        )
                        raise FatalStartupError(
                            "无法读取依赖同步状态",
                            exit_code=EXIT_IPC_FAILURE,
                        ) from exc
                    if force_dependency_sync:
                        logger.info("[GUI] 检测到更新请求，创建替代 WebUI 前将同步依赖")
                    break
                elif not process.is_alive():
                    if time.monotonic() - ready_at >= WEBUI_STABLE_RUNTIME:
                        runtime_failures = 0
                    runtime_failures += 1
                    if runtime_failures >= WEBUI_RUNTIME_RETRY_LIMIT:
                        logger.error_context(
                            title='AzurPilot Web 服务反复意外退出',
                            reason=(
                                f'已连续 {runtime_failures} 次在稳定运行前退出（最近退出码 {process.exitcode}），'
                                '且没有收到正常重启事件。'
                            ),
                            impact='WebUI 不再提供服务，父进程将退出以避免无限崩溃循环。',
                            action='查看对应的 GUI 日志和子进程错误现场后重新启动。',
                            level=50,
                        )
                        raise FatalStartupError(
                            "WebUI 反复意外退出",
                            exit_code=EXIT_WEBUI_RUNTIME_CRASH,
                        )
                    else:
                        logger.warning(
                            f"[GUI] WebUI 意外退出（退出码 {process.exitcode}），将在 {runtime_failures} 秒后重试 "
                            f"({runtime_failures}/{WEBUI_RUNTIME_RETRY_LIMIT})"
                        )
                        time.sleep(runtime_failures)
                    break

            # 确保子进程完全退出；清理失败时不能创建替代 WebUI。
            if not _stop_webui_process_tree(process):
                if fatal_error is None:
                    logger.error_context(
                        title='WebUI 子进程清理失败',
                        reason='子进程已退出或需要重启，但关联 worker 未能确认回收。',
                        impact='继续启动新 WebUI 可能保留重复的设备控制任务。',
                        action='检查残留 gui.py/worker 进程后重新启动。',
                        level=50,
                    )
                    raise FatalStartupError(
                        "WebUI 子进程清理失败，关联 worker 未能回收",
                        exit_code=EXIT_WORKER_CLEANUP_FAILURE,
                    )
    except FatalStartupError as exc:
        # 致命路径统一收敛到此，只决定退出码；错误现场已在各自分支记录。
        fatal_error = exc
    finally:
        _stop_webui_process_tree(process)
        _stop_dependency_sync_service(service, service_request_queue)
        if fatal_error is None:
            logger.info("[GUI] AzurPilot Web服务已成功退出")
        else:
            logger.error(
                "[GUI] AzurPilot Web服务启动失败：%s (退出码: %d)",
                fatal_error.reason,
                fatal_error.exit_code,
            )

    return fatal_error.exit_code if fatal_error is not None else EXIT_SUCCESS


def tui_request(argv: list[str]) -> tuple[bool, Optional[str]]:
    """解析 ``--tui [INSTANCE]``，判断是否进入终端界面模式。

    启动器允许未知参数原样传给 WebUI 子进程，因此这里使用
    ``parse_known_args`` 且不注册 ``--help``，避免抢占其他入口的参数。

    Args:
        argv (list[str]): 不含程序名的命令行参数。

    Returns:
        tuple[bool, Optional[str]]: 是否请求 TUI；请求时的实例名（未指定为 None）。
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--tui",
        nargs="?",
        const="",
        default=None,
        metavar="INSTANCE",
        help="启动终端界面，可选指定配置实例名",
    )
    try:
        args, _ = parser.parse_known_args(argv)
    except SystemExit:
        # 参数本身有误时保持启动器原有行为：当作未请求 TUI。
        return False, None
    if args.tui is None:
        return False, None
    return True, args.tui or None


def configure_tui_console() -> None:
    """为 TUI 启用 Windows ANSI 色彩与 UTF-8 输出，忽略不可重定向的输出流。"""
    if sys.platform == "win32":
        try:
            # 让 Windows 传统控制台识别 ANSI 转义序列。
            os.system("")
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def run_tui(instance: Optional[str] = None) -> int:
    """在当前终端运行 Textual 终端界面。

    调用前需已完成 ``module.persistence.database.initialize()``；
    界面运行期间移除控制台日志 handler，避免后台日志破坏全屏渲染。

    Args:
        instance (Optional[str], optional): 启动时选中的配置实例名。默认为 None。

    Returns:
        int: 进程退出码，0 表示正常退出。
    """
    configure_tui_console()
    # 标记当前进程运行于 TUI 全屏环境；业务子进程据此关闭控制台日志。
    os.environ["AZURPILOT_TUI"] = "1"

    try:
        import textual  # noqa: F401
    except ImportError:
        print(
            "缺少 textual 依赖，请先运行：uv sync\n"
            "或安装：uv add textual",
            file=sys.stderr,
        )
        return 1

    # 进入界面之前移除控制台日志处理器，避免后台日志污染终端渲染。
    try:
        from module.logger import console_hdlr
        logger.removeHandler(console_hdlr)
    except Exception:
        pass

    from module.tui.app import AzurPilotTUI

    app = AzurPilotTUI(default_instance=instance)
    try:
        app.run()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        # Textual 已退出终端，这里把异常打印到标准错误便于排查。
        print(f"TUI 运行异常：{exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """初始化普通业务数据，按 ``--tui`` 启动终端界面，否则启动 WebUI。"""
    # Windows 父进程保留启动日志；文件不可写时继续输出到控制台。
    try:
        logger.set_file_logger('gui-launcher')
    except OSError:
        logger.warning('[GUI] 启动文件日志不可用，继续输出到控制台')
    logger.info('[GUI] 开始检查普通业务存储；启动日志：%s', logger.log_file or '控制台')
    try:
        from module.persistence.database import initialize
        initialize()
    except Exception as exc:
        logger.error_context(
            title='普通业务数据初始化失败',
            reason=str(exc),
            exc=exc,
            impact='WebUI 尚未启动，旧数据与迁移备份保留。',
            action='查看 GUI 日志中的异常原因，修复后重试；不要删除旧数据库或迁移标记。',
            level=50,
        )
        return EXIT_STARTUP_FAILURE
    logger.info('[GUI] 存储已就绪，继续启动')

    tui_requested, tui_instance = tui_request(sys.argv[1:])
    if tui_requested:
        logger.info('[GUI] 进入终端界面（TUI）模式')
        return run_tui(tui_instance)

    # 设置multiprocessing启动方式为spawn（macOS兼容性要求）
    try:
        set_start_method("spawn", force=True)
        # 额外的macOS环境配置
        if os.name == "posix" and sys.platform == "darwin":
            os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    except RuntimeError:
        logger.warning("[GUI] 无法设置spawn启动方式，可能使用fork（macOS上不推荐）")

    # -r 既开启源码监听，也强制进入监督模式（覆盖 EnableReload=false）。
    watch_sources = reload_requested(sys.argv[1:])
    if watch_sources or State.deploy_config.EnableReload:
        if watch_sources:
            logger.info('[GUI] 进入源码监听热重载监督模式（-r/--reload）')
        else:
            logger.info('[GUI] 进入热重载监督模式')
        return run_webui_supervisor(watch_sources=watch_sources)
    else:
        # 非重载模式：直接运行
        logger.info('[GUI] 进入直接运行模式')
        func(None, None)
        return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
