import errno
import os
import queue
import socket
import sys
import threading
import time
from multiprocessing import Event, Process, Queue, set_start_method
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
from module.logger import logger
from module.runtime.setting import (
    State,
    clear_dependency_sync_pending,
    is_dependency_sync_pending,
)
from module.runtime import worker_registry
from module.runtime.process_control import pid_exists, stop_process, stop_process_tree


WEBUI_READY_TIMEOUT = 120
WEBUI_START_RETRY_LIMIT = 3
WEBUI_RUNTIME_RETRY_LIMIT = 3
WEBUI_STABLE_RUNTIME = 60
DEPENDENCY_SYNC_START_RETRY_LIMIT = 3
DEPENDENCY_SYNC_RESPONSE_TIMEOUT = DEPENDENCY_SYNC_TIMEOUT + 60


def _is_ipv6_unavailable_error(exc: OSError) -> bool:
    """判断 IPv6 地址族在当前系统中是否不可用。"""
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
    """创建同端口的 IPv4/IPv6 WebUI socket，并可降级为 IPv4。"""
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
    """在 Uvicorn 完成监听后通知父进程。"""
    while not server.started:
        if server.should_exit or server.force_exit:
            return
        time.sleep(0.1)
    ready_event.set()


def _run_uvicorn_server(config, ready_event: Optional[Event] = None, sockets=None) -> None:
    """运行 Uvicorn，并在端口实际监听后发送就绪信号。"""
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
    """
    主函数：运行Web服务。

    Args:
        ev: 可选的重启事件，用于热重载功能
        dependency_sync_event: 请求父进程同步依赖的事件
        ready_event: Uvicorn 完成监听后通知父进程的事件
    """
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
        from module.logger import console_hdlr
        logger.removeHandler(console_hdlr)

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
            "ws_max_size": 1048576,
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
    """通过本地句柄逐级停止服务，退出结果由 multiprocessing 回收。"""
    return stop_process(process, timeout=timeout)


def _wait_for_webui_ready(process, ready_event: Event, timeout=WEBUI_READY_TIMEOUT) -> bool:
    """等待 WebUI 完成 ASGI 启动和 socket 监听。"""
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
    """统一回收服务进程树，保留根进程的 multiprocessing 退出状态。"""
    return stop_process_tree(process, name=name, timeout=0)


def _stop_registered_worker(pid: int, name: str, record: dict) -> bool:
    """按持久化身份回收 worker，不按缓存 PID 发信号。"""
    if record.get("pid") != pid:
        return False
    return stop_process_tree(record=record, name=f"worker {name}", timeout=0)


def _stop_registered_workers(
    owner_pid: int | None,
    discard_reused: bool = False,
) -> bool:
    """回收指定 WebUI 所登记的 worker，覆盖根进程已异常退出的场景。"""
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
    return pid_exists(pid)


def _recover_orphaned_workers() -> bool:
    """启动前回收上次异常退出的 WebUI worker。"""
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
    """终止卡住的依赖同步服务及其 uv 子进程。"""
    return _stop_process_tree(process, "依赖同步服务")


def _stop_webui_process_tree(process) -> bool:
    """终止 WebUI 及其 AzurPilot worker 子进程，避免重启后重复控制设备。"""
    root_stopped = _stop_process_tree(process, "WebUI")
    if not root_stopped:
        # 根 WebUI 仍可能继续创建或管理 worker，不能清除其登记。
        return False
    owner_pid = getattr(process, "pid", None) if process is not None else None
    workers_stopped = _stop_registered_workers(owner_pid, discard_reused=True)
    return root_stopped and workers_stopped


def _start_dependency_sync_service():
    """启动空闲的依赖同步服务，避免 WebUI 进程修改自身环境。"""
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
    """有限重试启动依赖同步服务，避免启动器因单次进程错误直接崩溃。"""
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
    """停止依赖同步服务，确保启动器关闭时不遗留后端进程。"""
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
    """向独立服务请求同步，并将完整 uv 输出写入 GUI 日志。"""
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
    """完成更新遗留的依赖同步，并仅在成功后清除持久化标记。"""
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
    """在创建 WebUI 前完成必要的依赖同步，失败时拒绝启动子进程。"""
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


def run_webui_supervisor() -> None:
    """监督热重载 WebUI 子进程及其独立依赖同步服务。"""
    should_exit = False
    process = None
    service = None
    service_request_queue = None
    service_response_queue = None
    startup_failures = 0
    runtime_failures = 0
    force_dependency_sync = False
    if not _recover_orphaned_workers():
        return
    try:
        while not should_exit:
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
                should_exit = True
                break
            force_dependency_sync = False

            # 首次安装前端依赖可能较慢，必须在子进程监听计时开始前完成。
            from deploy.frontend import ensure_frontend
            try:
                ensure_frontend()
            except Exception as exc:
                logger.exception_context(
                    title='React 前端构建失败',
                    exc=exc,
                    impact='前端静态资源不可用，停止创建 WebUI 子进程。',
                    action='检查 Node.js 安装和 npm 输出，修复后重新启动。',
                    level=50,
                )
                break

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
                    should_exit = True
                else:
                    time.sleep(startup_failures)
                continue
            logger.info(f"[GUI] 启动AzurPilot Web服务 (PID: {process.pid})")

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
                    should_exit = True
                elif startup_failures >= WEBUI_START_RETRY_LIMIT:
                    logger.error_context(
                        title='WebUI 子进程未能完成启动',
                        reason=f'连续 {startup_failures} 次未在 {WEBUI_READY_TIMEOUT} 秒内完成监听。',
                        impact='WebUI 未启动，父进程将退出。',
                        action='检查端口占用、WebUI 日志和 Python 环境后重新启动。',
                        level=50,
                    )
                    should_exit = True
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
                try:
                    # 等待重启事件，超时1秒
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
                    should_exit = True
                    break

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
                        should_exit = True
                        break
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
                        should_exit = True
                        break
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
                                f'已连续 {runtime_failures} 次在稳定运行前退出，'
                                '且没有收到正常重启事件。'
                            ),
                            impact='WebUI 不再提供服务，父进程将退出以避免无限崩溃循环。',
                            action='查看对应的 GUI 日志和子进程错误现场后重新启动。',
                            level=50,
                        )
                        should_exit = True
                    else:
                        logger.warning(
                            f"[GUI] WebUI 意外退出，将在 {runtime_failures} 秒后重试 "
                            f"({runtime_failures}/{WEBUI_RUNTIME_RETRY_LIMIT})"
                        )
                        time.sleep(runtime_failures)
                    break

            # 确保子进程完全退出；清理失败时不能创建替代 WebUI。
            if not _stop_webui_process_tree(process):
                if not should_exit:
                    logger.error_context(
                        title='WebUI 子进程清理失败',
                        reason='子进程已退出或需要重启，但关联 worker 未能确认回收。',
                        impact='继续启动新 WebUI 可能保留重复的设备控制任务。',
                        action='检查残留 gui.py/worker 进程后重新启动。',
                        level=50,
                    )
                should_exit = True
    finally:
        _stop_webui_process_tree(process)
        _stop_dependency_sync_service(service, service_request_queue)
        logger.info("[GUI] AzurPilot Web服务已成功退出")


if __name__ == "__main__":
    # 设置multiprocessing启动方式为spawn（macOS兼容性要求）
    try:
        set_start_method("spawn", force=True)
        # 额外的macOS环境配置
        if os.name == "posix" and sys.platform == "darwin":
            os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    except RuntimeError:
        logger.warning("[GUI] 无法设置spawn启动方式，可能使用fork（macOS上不推荐）")

    if State.deploy_config.EnableReload:
        run_webui_supervisor()
    else:
        # 非重载模式：直接运行
        func(None, None)
