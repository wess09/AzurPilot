"""远程访问服务。

默认使用 localshare 的 P2P bootstrap：优先 WebRTC 直连/TURN 中继，失败后回到
localshare SSH 反向隧道。`cloudflare` 模式使用 Quick Tunnel 与设备固定入口。
"""
from module.base.runtime_params import P2P_SETUP_TIMEOUT, SSH_RECONNECT_DELAY, SSH_RECONNECT_MAX_DELAY
import asyncio
import base64
import fnmatch
import ipaddress
import json
import os
import shlex
import threading
import time
from dataclasses import dataclass
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING, List, Optional, Tuple
from urllib.parse import urlsplit

from module.base.ssh import clear_ssh_host_key
from module.config.utils import random_id
from module.logger import logger
from module.runtime.password_utils import REMOTE_ACCESS_HEADER
from module.runtime.setting import State

if TYPE_CHECKING:
    from module.runtime.task_handler import TaskHandler

HTTP_BODY_CHUNK = 12 * 1024
HOST_KEY_CHANGED_MARKER = "REMOTE HOST IDENTIFICATION HAS CHANGED"


class ParseError(Exception):
    """远程访问配置或响应解析异常。"""
    pass


class RemoteDependencyError(Exception):
    """缺少远程访问所需的可选依赖库异常。"""
    pass


class RemoteSignalError(Exception):
    """P2P 信令服务器交互异常。"""
    pass


@dataclass
class RemoteAccessInfo:
    """远程访问运行元数据状态对象。

    Attributes:
        address: 当前对外公开的 Web 访问地址。
        fallback_address: 回退的 SSH 访问地址。
        peer_id: 当前节点分配的 P2P 对等标识。
        signal_url: 信令服务器 WebSocket 地址。
        ice_servers: 服务端返回的 STUN/TURN 服务器配置列表。
        connection_state: 当前连接状态描述。
        error: 记录的错误信息。
    """
    address: Optional[str] = None
    fallback_address: Optional[str] = None
    peer_id: Optional[str] = None
    signal_url: Optional[str] = None
    ice_servers: Optional[list] = None
    connection_state: str = "stopped"
    error: str = ""


def am_i_the_only_thread() -> bool:
    """判断当前线程是否是进程中唯一的非守护线程。

    Returns:
        bool: 当前线程是唯一的非守护存活线程返回 True，否则返回 False。
    """
    alive_none_daemonic_thread_cnt = sum(
        1
        for t in threading.enumerate()
        if (t.is_alive() and not t.daemon) or t is threading.current_thread()
    )
    return alive_none_daemonic_thread_cnt == 1


def _parse_host_port(value: Optional[str]) -> Tuple[str, int]:
    """解析形如 host:port 的字符串。

    Args:
        value: 待解析的字符串。

    Returns:
        Tuple[str, int]: (主机名, 端口号)。

    Raises:
        ParseError: 解析格式错误。
    """
    try:
        server, port = str(value or "").rsplit(":", 1)
        return server, int(port)
    except (TypeError, ValueError) as e:
        raise ParseError(f"Failed to parse SSH server [{value}]") from e


def _parse_host_port_default(value: Optional[str], default_port: int) -> Tuple[str, int]:
    """解析 host:port 字符串，若无端口则使用默认端口。

    Args:
        value: 待解析的字符串。
        default_port: 默认端口号。

    Returns:
        Tuple[str, int]: (主机名, 端口号)。
    """
    text = str(value or "").strip()
    if ":" not in text:
        return text, default_port
    return _parse_host_port(text)


def _csv_or_json_list(value, default=None) -> List[str]:
    """将 CSV 或 JSON 格式的字符串解析为字符串列表。

    Args:
        value: 原始值。
        default: 默认列表。

    Returns:
        List[str]: 解析后的字符串列表。
    """
    if value in (None, ""):
        return list(default or [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [item.strip() for item in text.split(",") if item.strip()]


def _default_redirect_hosts(primary_host: str) -> List[str]:
    """根据主服务器域名自动推导允许重定向的域名白名单通配符。

    Args:
        primary_host: 主服务器域名。

    Returns:
        List[str]: 允许的重定向域名列表。
    """
    host = (primary_host or "").strip().lower()
    if not host:
        return []
    parts = host.split(".")
    hosts = [host]
    if len(parts) >= 2:
        base = ".".join(parts[-2:])
        hosts.append(f"*.{base}")
    if len(parts) >= 3:
        base = ".".join(parts[-3:])
        hosts.append(f"*.{base}")
    return list(dict.fromkeys(hosts))


def _is_private_redirect_host(host: str) -> bool:
    """检查重定向目标是否为私有、回环或保留网络地址。

    Args:
        host: 主机名或 IP。

    Returns:
        bool: 属于受限私有网络返回 True，否则返回 False。
    """
    value = (host or "").strip("[]").lower()
    if value in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any((
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    ))


def _local_host() -> str:
    """获取本地 WebUI 绑定的可连接主机地址。

    Returns:
        str: 本地主机 IP 或主机名。
    """
    host = State.webui_host or State.deploy_config.WebuiHost
    if host in ("0.0.0.0", "::", "[::]"):
        return "127.0.0.1"
    return host


def _remote_mode() -> str:
    """获取配置的远程访问模式。

    Returns:
        str: 'ssh'、'webrtc'、'auto' 或 'cloudflare'。
    """
    mode = getattr(State.deploy_config, "RemoteAccessMode", "auto")
    mode = str(mode or "auto").strip().lower()
    if mode not in ("ssh", "webrtc", "auto", "cloudflare"):
        logger.warning(f"[WebUI] 未知远程访问模式 [{mode}]，回退到 auto")
        return "auto"
    return mode


def _json_list(value, default=None) -> list:
    """解析 JSON 列表或逗号分隔串。

    Args:
        value: 原始值。
        default: 默认列表。

    Returns:
        list: 解析结果列表。
    """
    if value in (None, ""):
        return list(default or [])
    if isinstance(value, list):
        return value
    text = str(value).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else list(default or [])
    except json.JSONDecodeError:
        return [item.strip() for item in text.split(",") if item.strip()]


def _configured_ice_servers(remote_servers=None) -> List[dict]:
    """整合本地配置与服务端下发的 ICE (STUN/TURN) 服务器列表。

    Args:
        remote_servers: 可选的服务端下发列表。

    Returns:
        List[dict]: 格式化后的 ICE 服务器配置字典列表。
    """
    if remote_servers:
        return remote_servers

    servers = []
    stun = _json_list(
        getattr(State.deploy_config, "StunServers", None),
        ["stun:stun.l.google.com:19302"],
    )
    if stun:
        servers.append({"urls": stun})

    turn = _json_list(getattr(State.deploy_config, "TurnServers", None))
    if turn:
        servers.append({"urls": turn})
    return servers


def _signal_url_from_ssh_server() -> str:
    """由 SSH 服务器配置推导默认的信令服务器 WebSocket 地址。

    Returns:
        str: 信令服务器 URL。
    """
    configured = getattr(State.deploy_config, "SignalingServer", None)
    if configured:
        return configured

    server, _port = _parse_host_port(State.deploy_config.SSHServer)
    scheme = "wss"
    return f"{scheme}://{server}/signal"


def _format_signal_error(error: Exception, signal_url: str) -> str:
    """格式化信令连接失败的友好错误提示。

    Args:
        error: 异常对象。
        signal_url: 信令地址。

    Returns:
        str: 格式化后的错误描述。
    """
    status = getattr(error, "status", None)
    message = getattr(error, "message", "") or str(error)
    request_info = getattr(error, "request_info", None)
    url = getattr(request_info, "real_url", None) or signal_url
    if status:
        return f"P2P 信令连接失败（HTTP {status}: {message}），已继续使用 SSH 远程访问：{url}"
    return f"P2P 信令连接失败（{message}），已继续使用 SSH 远程访问：{url}"


class RemoteAccessProvider:
    """远程访问底层提供者抽象基类。"""

    def start(self) -> None:
        """启动远程访问后台服务。"""
        raise NotImplementedError

    def stop(self) -> None:
        """停止远程访问后台服务。"""
        raise NotImplementedError

    def is_alive(self) -> bool:
        """检查后台服务是否存活。"""
        raise NotImplementedError

    def get_state(self) -> int:
        """获取当前状态码。"""
        raise NotImplementedError

    def get_entry_point(self) -> Optional[str]:
        """获取当前对外公开的访问 URL。"""
        raise NotImplementedError

    def get_connection_state(self) -> str:
        """获取详细连接状态字符串。"""
        return "stopped"

    def get_error(self) -> str:
        """获取记录的错误信息。"""
        return ""


class SSHRemoteAccessProvider(RemoteAccessProvider):
    """基于 OpenSSH 反向隧道的远程访问提供者。

    Attributes:
        process: 运行中的 SSH 命令行子进程对象。
        thread: 守护线程对象。
        stop_event: 停止通知事件。
        notfound: 是否未找到 ssh 可执行文件。
        info: 远程访问状态元数据。
    """

    def __init__(self) -> None:
        """初始化 SSH 远程访问提供者。"""
        self.process: Optional[Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.notfound = False
        self.info = RemoteAccessInfo()

    def _max_redirects(self) -> int:
        """获取允许的最大重定向跳转次数。"""
        try:
            return max(0, int(getattr(State.deploy_config, "MaxRedirects", 2) or 0))
        except (TypeError, ValueError):
            logger.warning("无效的MaxRedirects，回退到2")
            return 2

    def _redirect_hosts(self, primary_host: str) -> List[str]:
        """获取允许的重定向域名列表。"""
        configured = _csv_or_json_list(getattr(State.deploy_config, "AllowedRedirectHosts", None))
        return configured or _default_redirect_hosts(primary_host)

    def _validate_redirect_target(self, ssh_server: str, primary_host: str) -> Tuple[str, int]:
        """校验重定向目标服务器是否安全合规。

        Args:
            ssh_server: 重定向目标地址。
            primary_host: 原始服务器域名。

        Returns:
            Tuple[str, int]: (主机名, 端口)。

        Raises:
            ParseError: 目标为空、属于私有网段或不在白名单内。
        """
        host, port = _parse_host_port_default(ssh_server, 1022)
        host = host.strip().lower()
        if not host:
            raise ParseError("Redirect ssh_server host is empty")
        if _is_private_redirect_host(host):
            raise ParseError(f"Refuse redirect to private host [{host}]")
        allowed_hosts = [item.lower() for item in self._redirect_hosts(primary_host)]
        if allowed_hosts and not any(fnmatch.fnmatch(host, pattern) for pattern in allowed_hosts):
            raise ParseError(f"Refuse redirect to untrusted host [{host}], allowed hosts: {allowed_hosts}")
        return host, port

    def _terminate_process(self) -> None:
        """终止当前正在运行的 SSH 子进程。"""
        if self.process and self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(timeout=3)
            except Exception:
                pass

    def _start_ssh_process(
        self,
        local_host: str,
        local_port: int,
        server: str,
        server_port: int,
        remote_port: str,
    ) -> Optional[Popen]:
        """构造参数并启动 SSH 反向端口转发子进程。

        Args:
            local_host: 本地转发目标主机。
            local_port: 本地转发目标端口。
            server: 远程 SSH 主机名。
            server_port: 远程 SSH 端口。
            remote_port: 申请的远程转发端口。

        Returns:
            Optional[Popen]: 启动成功的 Popen 实例；若未找到 ssh 命令则返回 None。
        """
        bin_path = State.deploy_config.SSHExecutable
        known_hosts = os.devnull
        clear_ssh_host_key(server, server_port, ssh_executable=bin_path)
        cmd = (
            f"{bin_path} -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile={known_hosts} "
            f"-oGlobalKnownHostsFile={known_hosts} "
            f"-oLogLevel=ERROR "
            f"-oServerAliveInterval=15 "
            f"-oServerAliveCountMax=3 "
            f"-oExitOnForwardFailure=yes "
            f"-R {remote_port}:{local_host}:{local_port} "
            f"-p {server_port} {server} -- --output json"
        )
        args = shlex.split(cmd)
        logger.debug(f"[WebUI-远程访问] 远程访问服务命令: {cmd}")

        if self.process is not None and self.process.poll() is None:
            logger.warning(f"终止之前的SSH进程 [{self.process.pid}]")
            self.process.kill()
        try:
            self.process = Popen(args, stdout=PIPE, stderr=PIPE)
        except FileNotFoundError:
            logger.critical(
                f"无法找到SSH可执行文件{bin_path}，请安装OpenSSH或在deploy.yaml中指定SSHExecutable"
            )
            self.notfound = True
            self.info.error = "ssh_not_found"
            return None

        logger.info(f"远程访问进程PID: {self.process.pid}")
        return self.process

    def _run(
        self,
        local_host: str = "127.0.0.1",
        local_port: int = 25548,
        server: str = "app.pywebio.online",
        server_port: int = 1022,
        remote_port: str = "/",
        setup_timeout: int = 60,
    ) -> Optional[str]:
        """执行单次连接生命周期；若服务要求改名则返回下一轮使用的用户名。

        Args:
            local_host: 本地主机。
            local_port: 本地端口。
            server: 远程服务器地址。
            server_port: 远程端口。
            remote_port: 远程路径或端口。
            setup_timeout: 连接建连超时时间（秒）。

        Returns:
            Optional[str]: 新分配的用户名（若有）。
        """
        primary_user, primary_host = server.rsplit("@", 1) if "@" in server else ("", server)
        current_server = server
        current_port = server_port
        success = False
        redirects = 0

        while True:
            process = self._start_ssh_process(
                local_host=local_host,
                local_port=local_port,
                server=current_server,
                server_port=current_port,
                remote_port=remote_port,
            )
            if process is None:
                return

            def timeout_killer(wait_sec, target_process):
                time.sleep(wait_sec)
                if not success and target_process.poll() is None:
                    logger.info("连接超时，终止SSH进程")
                    target_process.kill()

            threading.Thread(
                target=timeout_killer,
                args=(setup_timeout, process),
                daemon=True,
            ).start()

            stdout = process.stdout.readline().decode("utf8")
            logger.debug(f"[WebUI-远程访问] SSH 服务器标准输出: {stdout}")
            try:
                connection_info = json.loads(stdout)
            except json.JSONDecodeError:
                if process.poll() is None:
                    process.kill()
                stderr = process.stderr.read().decode("utf8", errors="replace")
                if HOST_KEY_CHANGED_MARKER in stderr.upper():
                    clear_ssh_host_key(current_server, current_port)
                    self.info.error = "ssh_host_key_changed"
                elif stderr:
                    self.info.error = stderr.strip()
                    logger.error(f"SSH远程访问在注册前退出: {stderr.strip()}")
                else:
                    self.info.error = "invalid_provider_response"
                break

            status = connection_info.get("status", "fail")
            if status == "redirect":
                redirects += 1
                if redirects > self._max_redirects():
                    self.info.error = "too_many_redirects"
                    logger.error("SSH重定向响应过多")
                    self._terminate_process()
                    break
                ssh_server = connection_info.get("ssh_server")
                try:
                    redirect_host, redirect_port = self._validate_redirect_target(ssh_server, primary_host)
                except ParseError as e:
                    self.info.error = str(e)
                    logger.error(str(e))
                    self._terminate_process()
                    break
                redirect_user = connection_info.get("ssh_user") or primary_user or State.deploy_config.SSHUser
                current_server = f"{redirect_user}@{redirect_host}" if redirect_user else redirect_host
                current_port = redirect_port
                logger.info(f"远程访问重定向到 {redirect_host}:{redirect_port}")
                self._terminate_process()
                continue

            if status != "success":
                message = connection_info.get("message", "")
                self.info.error = message or status or "remote_access_failed"
                logger.info(
                    "Failed to establish remote access, this is the error message "
                    f"from service provider: {message}"
                )
                # 失败回包不代表连接建立；回收本次进程后交给外层退避重试。
                self._terminate_process()
                self.info.connection_state = "stopped"
                self.info.address = None
                new_username = connection_info.get("change_username", None)
                if isinstance(new_username, str) and new_username:
                    logger.info(f"服务器请求更改用户名，更改为: {new_username}")
                    State.deploy_config.SSHUser = new_username
                    return new_username
                return

            success = True
            self.info.address = connection_info.get("address")
            self.info.fallback_address = connection_info.get("fallback_address") or self.info.address
            self.info.peer_id = connection_info.get("peer_id")
            self.info.signal_url = connection_info.get("signal_url")
            self.info.ice_servers = connection_info.get("ice_servers")
            self.info.connection_state = "ssh_forward"
            self.info.error = ""
            logger.debug(f"[WebUI-远程访问] 远程访问 URL: {self.info.address}")
            break

        while (
            not self.stop_event.is_set()
            and not am_i_the_only_thread()
            and self.process
            and self.process.poll() is None
        ):
            time.sleep(1)

        if self.process and self.process.poll() is None:
            if self.stop_event.is_set():
                logger.info("停止SSH远程访问服务")
            else:
                logger.info("应用进程退出，终止SSH进程")
            self.process.kill()
        elif self.process:
            stderr = self.process.stderr.read().decode("utf8")
            if stderr:
                logger.error(f"PyWebIO应用远程访问服务错误: {stderr}")
                self.info.error = stderr.strip()
            else:
                logger.info("PyWebIO应用远程访问服务退出.")
        self.info.connection_state = "stopped"
        self.info.address = None

    def start(self) -> None:
        """启动 SSH 远程访问后台守护线程。"""
        if self.thread is not None and self.thread.is_alive():
            return

        self.stop_event.clear()
        self.notfound = False
        server, server_port = _parse_host_port(State.deploy_config.SSHServer)
        if State.deploy_config.SSHUser is None:
            logger.info("SSHUser未设置，生成随机用户")
            State.deploy_config.SSHUser = random_id(24)

        target = f"{State.deploy_config.SSHUser}@{server}"
        self.thread = threading.Thread(
            target=self._thread_main,
            kwargs={
                "server": target,
                "server_port": server_port,
                "local_host": _local_host(),
                "local_port": State.deploy_config.WebuiPort,
            },
            daemon=False,
        )
        self.thread.start()

    def _thread_main(self, **kwargs) -> None:
        """SSH 连接重试守护循环。"""
        logger.info("启动SSH远程访问服务")
        reconnect_delay = SSH_RECONNECT_DELAY
        while not self.stop_event.is_set():
            try:
                new_username = self._run(**kwargs)
                if isinstance(new_username, str) and new_username:
                    # 只响应服务明确要求的改名；保留调用方指定的服务器和端口。
                    host = kwargs.get("server", "app.pywebio.online").rsplit("@", 1)[-1]
                    kwargs["server"] = f"{new_username}@{host}"
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.info.error = str(e)
                logger.warning(f"SSH远程访问服务错误: {e}")

            if self.stop_event.is_set() or self.notfound:
                break

            logger.warning(f"[WebUI-远程] SSH远程访问断开，重试间隔 {reconnect_delay} 秒")
            self.info.connection_state = "reconnecting"
            if self.stop_event.wait(reconnect_delay):
                break
            reconnect_delay = min(reconnect_delay * 2, SSH_RECONNECT_MAX_DELAY)

        if self.process and self.process.poll() is None:
            logger.info("停止SSH远程访问进程")
            self.process.kill()
        logger.info("退出SSH远程访问服务线程")

    def stop(self) -> None:
        """停止 SSH 远程访问并终止子进程。"""
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.kill()

    def is_alive(self) -> bool:
        """检查 SSH 服务线程及子进程是否均处于运行状态。

        Returns:
            bool: 正常运行返回 True，否则返回 False。
        """
        return (
            self.thread is not None
            and self.thread.is_alive()
            and self.process is not None
            and self.process.poll() is None
        )

    def get_state(self) -> int:
        """获取状态码。

        Returns:
            int: 0=未启动, 1=已就绪, 2=连接中, 3=未找到 ssh。
        """
        if self.is_alive():
            return 1 if self.info.address else 2
        if self.notfound:
            return 3
        return 0

    def get_entry_point(self) -> Optional[str]:
        """获取对外公开的访问 URL。

        Returns:
            Optional[str]: 访问 URL；未运行或未获取到时返回 None。
        """
        return self.info.address if self.is_alive() else None

    def get_connection_state(self) -> str:
        """获取当前连接状态描述。

        Returns:
            str: 状态字符串。
        """
        if self.is_alive():
            return self.info.connection_state if self.info.address else "starting"
        return "ssh_not_found" if self.notfound else "stopped"

    def get_error(self) -> str:
        """获取错误信息。

        Returns:
            str: 错误信息字符串。
        """
        return self.info.error


class WebRTCTunnel:
    """基于 WebRTC DataChannel 的透明反向代理隧道。

    处理通过数据通道传输的 HTTP 请求、WebSocket 与 SSE 流。

    Attributes:
        local_host: 本地目标主机。
        local_port: 本地目标端口。
        channel: WebRTC DataChannel 通道对象。
        peer_id: 本地节点标识。
        ws_sessions: 活跃的 WebSocket 客户端会话映射。
        sse_tasks: 运行中的 SSE 转发协程任务。
        ws_incoming_chunks: 分片接收的 WebSocket 大消息缓存。
    """

    def __init__(self, local_host: str, local_port: int, channel, peer_id: Optional[str] = None) -> None:
        """初始化 WebRTC 数据通道代理隧道。

        Args:
            local_host: 本地服务 IP。
            local_port: 本地服务端口。
            channel: WebRTC DataChannel 实例。
            peer_id: 本地节点对等 ID。
        """
        self.local_host = local_host.strip("[]")
        self.local_port = int(local_port)
        self.channel = channel
        self.peer_id = str(peer_id or "").strip("/").lower()
        self.ws_sessions = {}
        self.sse_tasks = {}
        self.ws_incoming_chunks = {}

    @property
    def base_http_url(self) -> str:
        """本地 HTTP 基础访问 URL。"""
        host = self.local_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.local_port}"

    @property
    def base_ws_url(self) -> str:
        """本地 WebSocket 基础访问 URL。"""
        host = self.local_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"ws://{host}:{self.local_port}"

    def send_json(self, payload: dict) -> None:
        """向 WebRTC 数据通道发送 JSON 消息。

        Args:
            payload: 消息载荷字典。
        """
        self.channel.send(json.dumps(payload, ensure_ascii=False))

    def _normalize_proxy_path(self, value: str) -> str:
        """规范化代理转发路径，去除 P2P 前缀。

        Args:
            value: 原始请求路径。

        Returns:
            str: 转换后的本地服务相对路径。
        """
        text = str(value or "/")
        if "://" in text:
            parsed = urlsplit(text)
            text = parsed.path or "/"
            if parsed.query:
                text = f"{text}?{parsed.query}"
        if not text.startswith("/"):
            text = f"/{text}"

        if self.peer_id:
            prefix = f"/p2p/{self.peer_id}"
            lower_text = text.lower()
            if lower_text == prefix or lower_text.startswith(f"{prefix}?") or lower_text.startswith(f"{prefix}/"):
                suffix = text[len(prefix):]
                if suffix.startswith("/"):
                    text = suffix or "/"
                elif suffix.startswith("?"):
                    text = f"/{suffix}"
                else:
                    text = "/"
        return text

    @staticmethod
    def _forward_headers(headers: dict, payload: dict) -> dict:
        """拼装转发给本地服务的请求头。

        透明传递浏览器信息，并打上隧道标记：隧道连接同样来自回环地址，
        标记后 WebUI 才不会把它当成免密的本机直连。

        Args:
            headers: 原始请求头字典。
            payload: 数据包字典。

        Returns:
            dict: 注入标记与客户端信息后的请求头。
        """
        headers = dict(headers or {})
        user_agent = payload.get("user_agent")
        accept_language = payload.get("accept_language")
        if user_agent:
            headers["User-Agent"] = user_agent
        if accept_language:
            headers.setdefault("Accept-Language", accept_language)
        headers[REMOTE_ACCESS_HEADER] = "1"
        return headers

    async def handle(self, payload: dict) -> None:
        """分发处理从 WebRTC 通道收到的各类代理消息。

        Args:
            payload: 协议消息字典。
        """
        msg_type = payload.get("type")
        if msg_type == "http.request":
            await self._http_request(payload)
        elif msg_type == "ws.open":
            await self._ws_open(payload)
        elif msg_type == "ws.send":
            await self._ws_send(payload)
        elif msg_type == "ws.send.start":
            self._ws_send_start(payload)
        elif msg_type == "ws.send.chunk":
            self._ws_send_chunk(payload)
        elif msg_type == "ws.send.end":
            await self._ws_send_end(payload)
        elif msg_type == "ws.close":
            await self._ws_close(payload)
        elif msg_type == "sse.open":
            await self._sse_open(payload)
        elif msg_type == "sse.close":
            await self._sse_close(payload)

    async def _http_request(self, payload: dict) -> None:
        """代理执行本地 HTTP 请求并将响应分片送回通道。"""
        req_id = payload.get("id")
        try:
            import aiohttp

            method = payload.get("method") or "GET"
            path = self._normalize_proxy_path(payload.get("path"))
            headers = self._forward_headers(payload.get("headers"), payload)
            body = payload.get("body") or ""
            data = base64.b64decode(body) if body else None
            url = f"{self.base_http_url}{path}"
            async with aiohttp.ClientSession(auto_decompress=False) as session:
                async with session.request(method, url, headers=headers, data=data) as resp:
                    self.send_json({
                        "type": "http.response.start",
                        "id": req_id,
                        "status": resp.status,
                        "status_text": resp.reason,
                        "headers": dict(resp.headers),
                    })
                    async for chunk in resp.content.iter_chunked(HTTP_BODY_CHUNK):
                        self.send_json({
                            "type": "http.response.chunk",
                            "id": req_id,
                            "data": base64.b64encode(chunk).decode("ascii"),
                        })
                    self.send_json({"type": "http.response.end", "id": req_id})
        except Exception as e:
            logger.warning(f"P2P HTTP代理失败: {e}")
            self.send_json({"type": "http.response.error", "id": req_id, "message": str(e)})

    async def _ws_open(self, payload: dict) -> None:
        """建立至本地服务的 WebSocket 代理连接。"""
        ws_id = payload.get("id")
        session = None
        try:
            import aiohttp

            path = self._normalize_proxy_path(payload.get("path"))
            url = f"{self.base_ws_url}{path}"
            session = aiohttp.ClientSession()
            ws = await session.ws_connect(
                url,
                heartbeat=30,
                headers=self._forward_headers({}, payload),
            )
            self.ws_sessions[ws_id] = (session, ws)
            self.send_json({"type": "ws.opened", "id": ws_id})
            asyncio.create_task(self._ws_reader(ws_id, session, ws))
        except Exception as e:
            if session is not None:
                await session.close()
            logger.warning(f"P2P WebSocket打开失败: {e}")
            self.send_json({"type": "ws.error", "id": ws_id, "message": str(e)})

    async def _ws_reader(self, ws_id, session, ws) -> None:
        """读取本地 WebSocket 输出并转发到通道。"""
        try:
            import aiohttp

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self.send_json({"type": "ws.message", "id": ws_id, "binary": False, "data": msg.data})
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await self._ws_send_chunked_message(ws_id, True, msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        finally:
            self.ws_sessions.pop(ws_id, None)
            await session.close()
            self.send_json({"type": "ws.closed", "id": ws_id, "code": 1000, "reason": ""})

    async def _ws_send(self, payload: dict) -> None:
        """将客户端发送的消息转发给本地 WebSocket 服务。"""
        ws_id = payload.get("id")
        item = self.ws_sessions.get(ws_id)
        if not item:
            return
        _session, ws = item
        if payload.get("binary"):
            await ws.send_bytes(base64.b64decode(payload.get("data") or ""))
        else:
            await ws.send_str(payload.get("data") or "")

    def _ws_send_start(self, payload: dict) -> None:
        """开始接收客户端分片上传的大消息。"""
        message_id = payload.get("message_id")
        if not message_id:
            return
        self.ws_incoming_chunks[message_id] = {
            "id": payload.get("id"),
            "binary": bool(payload.get("binary")),
            "chunks": [b""] * int(payload.get("total") or 1),
        }

    def _ws_send_chunk(self, payload: dict) -> None:
        """接收单个数据分片。"""
        message_id = payload.get("message_id")
        item = self.ws_incoming_chunks.get(message_id)
        if not item:
            return
        index = int(payload.get("index") or 0)
        if 0 <= index < len(item["chunks"]):
            item["chunks"][index] = base64.b64decode(payload.get("data") or "")

    async def _ws_send_end(self, payload: dict) -> None:
        """大消息分片全部接收完毕，组装并发送给本地服务。"""
        message_id = payload.get("message_id")
        item = self.ws_incoming_chunks.pop(message_id, None)
        if not item:
            return
        ws_id = item["id"]
        session_item = self.ws_sessions.get(ws_id)
        if not session_item:
            return
        _session, ws = session_item
        data = b"".join(item["chunks"])
        if item["binary"]:
            await ws.send_bytes(data)
        else:
            await ws.send_str(data.decode("utf-8", errors="replace"))

    async def _ws_close(self, payload: dict) -> None:
        """关闭代理的 WebSocket 连接。"""
        ws_id = payload.get("id")
        item = self.ws_sessions.pop(ws_id, None)
        if not item:
            return
        session, ws = item
        await ws.close()
        await session.close()

    async def _sse_open(self, payload: dict) -> None:
        """打开 SSE 事件流转发。"""
        sse_id = payload.get("id")
        task = asyncio.create_task(self._sse_reader(payload))
        self.sse_tasks[sse_id] = task

    async def _sse_reader(self, payload: dict) -> None:
        """读取本地 SSE 流并打包送回客户端。"""
        sse_id = payload.get("id")
        try:
            import aiohttp

            path = self._normalize_proxy_path(payload.get("path"))
            url = f"{self.base_http_url}{path}"
            async with aiohttp.ClientSession() as session:
                headers = self._forward_headers({"Accept": "text/event-stream"}, payload)
                async with session.get(url, headers=headers) as resp:
                    async for chunk in resp.content.iter_chunked(8192):
                        self.send_json({
                            "type": "sse.chunk",
                            "id": sse_id,
                            "data": chunk.decode("utf-8", errors="replace"),
                        })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"P2P SSE代理失败: {e}")
        finally:
            self.sse_tasks.pop(sse_id, None)
            self.send_json({"type": "sse.closed", "id": sse_id})

    async def _sse_close(self, payload: dict) -> None:
        """取消 SSE 转发任务。"""
        sse_id = payload.get("id")
        task = self.sse_tasks.pop(sse_id, None)
        if task:
            task.cancel()

    async def _ws_send_chunked_message(self, ws_id, binary: bool, data) -> None:
        """将大尺寸 WebSocket 消息分片后通过 DataChannel 发送。"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        data = bytes(data)
        total = max(1, (len(data) + HTTP_BODY_CHUNK - 1) // HTTP_BODY_CHUNK)
        message_id = f"{ws_id}-{time.time_ns()}"
        self.send_json({
            "type": "ws.message.start",
            "id": ws_id,
            "message_id": message_id,
            "binary": binary,
            "total": total,
        })
        for index in range(total):
            chunk = data[index * HTTP_BODY_CHUNK:(index + 1) * HTTP_BODY_CHUNK]
            self.send_json({
                "type": "ws.message.chunk",
                "id": ws_id,
                "message_id": message_id,
                "index": index,
                "data": base64.b64encode(chunk).decode("ascii"),
            })
        self.send_json({"type": "ws.message.end", "id": ws_id, "message_id": message_id})


class WebRTCRemoteAccessProvider(RemoteAccessProvider):
    """基于 WebRTC P2P 的远程访问提供者。

    与 localshare 信令服务器协作建立客户端与服务端之间的点对点连接，失败时回退到 SSH 隧道。

    Attributes:
        ssh_provider: 底层的 SSH 回退提供者。
        thread: 守护线程对象。
        stop_event: 停止事件。
        info: 远程访问状态元数据。
    """

    def __init__(self, ssh_provider: SSHRemoteAccessProvider) -> None:
        """初始化 WebRTC 提供者。

        Args:
            ssh_provider: SSH 回退服务实例。
        """
        self.ssh_provider = ssh_provider
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self.info = RemoteAccessInfo(connection_state="stopped")
        self._missing_dependency = ""

    def start(self) -> None:
        """启动 WebRTC 及底层 SSH 回退服务。"""
        with self._lock:
            if self.thread is not None and self.thread.is_alive():
                return

            self.stop_event.clear()
            if not self.ssh_provider.is_alive():
                self.ssh_provider.start()

            self.thread = threading.Thread(target=self._thread_main, daemon=False)
            self.thread.start()

    def _wait_for_ssh_info(self) -> bool:
        """等待 SSH 隧道就绪并返回元数据。"""
        started = time.time()
        while time.time() - started < P2P_SETUP_TIMEOUT:
            if self.stop_event.is_set():
                return False
            if self.ssh_provider.info.address:
                return True
            if not self.ssh_provider.is_alive() and self.ssh_provider.get_state() in (0, 3):
                return False
            time.sleep(0.2)
        return False

    def _thread_main(self) -> None:
        """WebRTC 信令与连接维护主线程。"""
        logger.info("启动WebRTC远程访问服务")
        try:
            if not self._wait_for_ssh_info():
                self.info.error = "SSH fallback is not ready"
                return

            self.info.address = self.ssh_provider.info.address
            self.info.fallback_address = self.ssh_provider.info.fallback_address
            self.info.peer_id = self.ssh_provider.info.peer_id
            self.info.signal_url = self.ssh_provider.info.signal_url or _signal_url_from_ssh_server()
            self.info.ice_servers = self.ssh_provider.info.ice_servers
            if not self.info.peer_id:
                raise ParseError("localshare 服务端未返回 peer_id，无法启用 P2P")
            self.info.connection_state = "signaling"
            asyncio.run(self._run_signal_loop())
        except RemoteDependencyError as e:
            self._missing_dependency = str(e)
            self.info.error = str(e)
            self.info.connection_state = "dependency_missing"
            logger.warning(f"WebRTC远程访问已禁用: {e}")
        except RemoteSignalError as e:
            self.info.error = str(e)
            self.info.connection_state = "ssh_forward"
            logger.warning(str(e))
        except Exception as e:
            self.info.error = str(e)
            self.info.connection_state = "failed"
            logger.exception(e)
        logger.info("退出WebRTC远程访问服务线程")

    async def _run_signal_loop(self) -> None:
        """运行 WebRTC 信令循环处理协商。"""
        try:
            import aiohttp
            from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
            from aiortc.sdp import candidate_from_sdp
        except ImportError as e:
            raise RemoteDependencyError("缺少 aiortc/aiohttp 依赖，已退回 SSH 转发") from e

        signal_url = self.info.signal_url
        if not signal_url:
            raise ParseError("SignalingServer is empty")

        ice_servers = _configured_ice_servers(self.info.ice_servers)
        rtc_servers = []
        for item in ice_servers:
            urls = item.get("urls")
            if isinstance(urls, str):
                urls = [urls]
            rtc_servers.append(
                RTCIceServer(
                    urls=urls or [],
                    username=item.get("username"),
                    credential=item.get("credential"),
                )
            )
        rtc_config = RTCConfiguration(iceServers=rtc_servers)
        peer_connections = set()
        peer_connections_by_viewer = {}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(signal_url, heartbeat=30) as ws:
                    await ws.send_json({
                        "type": "register",
                        "peer_id": self.info.peer_id,
                        "fallback_url": self.info.fallback_address,
                    })
                    keepalive_task = asyncio.create_task(self._signal_keepalive(ws))
                    self.info.connection_state = "waiting_peer"

                    try:
                        async for msg in ws:
                            if self.stop_event.is_set():
                                break
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            data = json.loads(msg.data)
                            msg_type = data.get("type")
                            if msg_type == "registered":
                                self.info.address = data.get("address") or self.info.address
                                self.info.fallback_address = data.get("fallback_url") or self.info.fallback_address
                                self.info.connection_state = "waiting_peer"
                                logger.info(f"P2P远程访问URL: {self.info.address}")
                            elif msg_type == "offer":
                                pc = RTCPeerConnection(configuration=rtc_config)
                                peer_connections.add(pc)
                                viewer_id = data.get("viewer_id")
                                if viewer_id:
                                    old_pc = peer_connections_by_viewer.pop(viewer_id, None)
                                    if old_pc is not None:
                                        peer_connections.discard(old_pc)
                                        await old_pc.close()
                                    peer_connections_by_viewer[viewer_id] = pc

                                @pc.on("datachannel")
                                def on_datachannel(channel):
                                    logger.info(f"P2P数据通道已打开: {channel.label}")
                                    tunnel = WebRTCTunnel(
                                        _local_host(),
                                        State.deploy_config.WebuiPort,
                                        channel,
                                        self.info.peer_id,
                                    )

                                    @channel.on("message")
                                    def on_message(message):
                                        try:
                                            payload = json.loads(message)
                                        except Exception as e:
                                            logger.warning(f"P2P通道消息解析失败: {e}")
                                            return
                                        asyncio.create_task(tunnel.handle(payload))

                                @pc.on("connectionstatechange")
                                async def on_connectionstatechange():
                                    if pc.connectionState == "connected":
                                        self.info.connection_state = "direct_p2p"
                                    elif pc.connectionState in ("failed", "closed", "disconnected"):
                                        peer_connections.discard(pc)
                                        if viewer_id and peer_connections_by_viewer.get(viewer_id) is pc:
                                            peer_connections_by_viewer.pop(viewer_id, None)
                                        await pc.close()

                                offer = RTCSessionDescription(sdp=data.get("sdp"), type=data.get("kind", "offer"))
                                await pc.setRemoteDescription(offer)
                                answer = await pc.createAnswer()
                                await pc.setLocalDescription(answer)
                                await self._wait_ice_complete(pc)
                                await ws.send_json({
                                    "type": "answer",
                                    "viewer_id": viewer_id,
                                    "sdp": pc.localDescription.sdp,
                                    "kind": pc.localDescription.type,
                                    })
                            elif msg_type == "candidate":
                                viewer_id = data.get("viewer_id")
                                pc = peer_connections_by_viewer.get(viewer_id)
                                if pc is None:
                                    continue
                                raw_candidate = data.get("candidate")
                                if not raw_candidate:
                                    await pc.addIceCandidate(None)
                                    continue
                                candidate = candidate_from_sdp(raw_candidate.get("candidate", ""))
                                candidate.sdpMid = raw_candidate.get("sdpMid")
                                candidate.sdpMLineIndex = raw_candidate.get("sdpMLineIndex")
                                await pc.addIceCandidate(candidate)
                            elif msg_type == "viewer_state":
                                state = data.get("state")
                                if state in ("direct_p2p", "turn_relay"):
                                    self.info.connection_state = state
                            elif msg_type == "error":
                                self.info.error = data.get("message", "")
                                logger.warning(f"P2P信令错误: {self.info.error}")
                    finally:
                        keepalive_task.cancel()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            raise RemoteSignalError(_format_signal_error(e, signal_url)) from e
        finally:
            for pc in list(peer_connections):
                await pc.close()

    @staticmethod
    async def _wait_ice_complete(pc, timeout: float = 3.5) -> None:
        """等待 ICE 候选收集完成。"""
        if pc.iceGatheringState == "complete":
            return
        done = asyncio.Event()

        @pc.on("icegatheringstatechange")
        def on_icegatheringstatechange():
            if pc.iceGatheringState == "complete":
                done.set()

        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    async def _signal_keepalive(self, ws) -> None:
        """信令 WebSocket 定期心跳保活。"""
        while not self.stop_event.is_set():
            await asyncio.sleep(25)
            if ws.closed:
                return
            await ws.send_json({"type": "ping", "peer_id": self.info.peer_id})

    def stop(self) -> None:
        """停止 WebRTC 及 SSH 服务。"""
        self.stop_event.set()
        self.ssh_provider.stop()

    def is_alive(self) -> bool:
        """检查 WebRTC 服务是否正常运行。"""
        return self.ssh_provider.is_alive() and self.thread is not None and self.thread.is_alive()

    def get_state(self) -> int:
        """获取当前状态码。"""
        if self.is_alive():
            return 1 if self.info.address else 2
        if self._missing_dependency:
            return 4
        return self.ssh_provider.get_state()

    def get_entry_point(self) -> Optional[str]:
        """获取当前对外访问入口 URL。"""
        if self.is_alive() and self.info.address:
            return self.info.address
        return self.ssh_provider.get_entry_point()

    def get_connection_state(self) -> str:
        """获取连接状态描述。"""
        if self.is_alive():
            return self.info.connection_state
        if self._missing_dependency:
            return "dependency_missing"
        return self.ssh_provider.get_connection_state()

    def get_error(self) -> str:
        """获取错误信息。"""
        return self.info.error or self.ssh_provider.get_error()


class AutoRemoteAccessProvider(RemoteAccessProvider):
    """根据部署配置选择 SSH、WebRTC 或 Cloudflare 的聚合提供者。

    Attributes:
        ssh: SSH 协议提供者。
        webrtc: WebRTC P2P 协议提供者。
    """

    def __init__(self) -> None:
        """初始化自动远程访问聚合服务。"""
        self.ssh = SSHRemoteAccessProvider()
        self.webrtc = WebRTCRemoteAccessProvider(self.ssh)
        from module.runtime.remote_cloudflare import cloudflare
        self.cloudflare = cloudflare

    def active(self) -> RemoteAccessProvider:
        """根据当前配置模式返回活跃的提供者实例。

        Returns:
            RemoteAccessProvider: 选中的提供者对象。
        """
        mode = _remote_mode()
        if mode in ("auto", "cloudflare"):
            return self.cloudflare
        return self.ssh if mode == "ssh" else self.webrtc

    def start(self) -> None:
        """启动远程访问服务。"""
        self.active().start()

    def stop(self) -> None:
        """停止所有远程访问提供者。"""
        self.webrtc.stop()
        self.ssh.stop()
        self.cloudflare.stop()

    def is_alive(self) -> bool:
        """检查当前活跃提供者是否存活。"""
        return self.active().is_alive()

    def get_state(self) -> int:
        """获取当前状态码。"""
        return self.active().get_state()

    def get_entry_point(self) -> Optional[str]:
        """获取对外访问入口 URL。"""
        return self.active().get_entry_point()

    def get_connection_state(self) -> str:
        """获取连接状态描述。"""
        return self.active().get_connection_state()

    def get_error(self) -> str:
        """获取错误描述。"""
        return self.active().get_error()


_provider = AutoRemoteAccessProvider()


def start_remote_access_service(**kwargs) -> bool:
    """启动远程访问服务（兼容历史入参）。

    Args:
        **kwargs: 历史参数。

    Returns:
        bool: 始终返回 True。
    """
    if kwargs:
        logger.debug(f"[WebUI-远程访问] 忽略旧版远程访问参数: {kwargs}")
    _provider.start()
    return True


class RemoteAccess:
    """远程访问对外暴露的全局静态方法接口。"""

    @staticmethod
    def keep_ssh_alive():
        """用于调度器任务的生成器，监控并在异常时自动恢复远程访问。"""
        task_handler: TaskHandler
        task_handler = yield
        consecutive_failures = 0
        max_failures = 5
        while True:
            if _provider.is_alive():
                consecutive_failures = 0
                yield
                continue
            if consecutive_failures >= max_failures:
                logger.warning(
                    f"远程访问服务连续 {max_failures} 次启动后仍不可用，已停止重试。"
                    "请检查 SSHServer / SignalingServer 配置是否可用。"
                )
                task_handler.remove_current_task()
                return
            consecutive_failures += 1
            logger.info(
                f"远程访问服务未运行，正在启动（第 {consecutive_failures}/{max_failures} 次尝试）"
            )
            try:
                start_remote_access_service()
            except ParseError as e:
                logger.exception(e)
                task_handler.remove_current_task()
                return
            yield
            if not _provider.is_alive():
                logger.warning(
                    f"远程访问服务启动后仍不可用（连续第 {consecutive_failures} 次）"
                )
            else:
                consecutive_failures = 0

    @staticmethod
    def kill_ssh_process():
        """停止远程访问服务。"""
        _provider.stop()

    @staticmethod
    def is_alive() -> bool:
        """检查远程访问服务是否存活。"""
        return _provider.is_alive()

    @staticmethod
    def get_state() -> int:
        """获取当前状态码。"""
        return _provider.get_state()

    @staticmethod
    def get_entry_point() -> Optional[str]:
        """获取对外公开的访问 URL。"""
        return _provider.get_entry_point()

    @staticmethod
    def get_connection_state() -> str:
        """获取连接状态。"""
        return _provider.get_connection_state()

    @staticmethod
    def get_error() -> str:
        """获取错误信息。"""
        return _provider.get_error()


def remote_access_status() -> dict:
    """返回界面展示用的远程访问状态。

    地址与连接状态活在 WebUI 服务进程内，设置接口与被访问的 provider 同进程，
    直接读即可。未启用或未就绪时地址为 ``None``，统一成空串交给前端判断。

    Returns:
        dict: ``enabled`` 是否开启、``state`` 状态串、``address`` 访问地址、``error`` 错误信息。
    """
    return {
        'enabled': bool(getattr(State.deploy_config, 'EnableRemoteAccess', False)),
        'state': RemoteAccess.get_connection_state(),
        'address': RemoteAccess.get_entry_point() or '',
        'error': RemoteAccess.get_error(),
    }
