"""
远程访问服务的实现。

基于 pywebio.platform.remote_access 修改，通过在 PyWebIO 应用中启动 SSH 子进程
使用 https://github.com/wang0618/localshare 服务实现远程访问。

SSH 进程的标准输出包含连接信息。
"""

import json
import shlex
import threading
import time
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING

from module.logger import logger
from module.config.utils import random_id
from module.webui.setting import State

if TYPE_CHECKING:
    from module.webui.utils import TaskHandler

_ssh_process: Popen = None
_ssh_thread: threading.Thread = None
_ssh_notfound: bool = False
address: str = None


def am_i_the_only_thread() -> bool:
    """判断当前线程是否是进程中唯一的非守护线程。"""
    alive_none_daemonic_thread_cnt = sum(
        1
        for t in threading.enumerate()
        if t.is_alive() and not t.isDaemon() or t is threading.current_thread()
    )
    return alive_none_daemonic_thread_cnt == 1


def remote_access_service(
    local_host="127.0.0.1",
    local_port=22267,
    server="app.pywebio.online",
    server_port=1022,
    remote_port="/",
    setup_timeout=60,
):
    """
    启动远程访问服务，等待 SSH 连接建立。

    等待最多 setup_timeout 秒获取 SSH 输出，若收到正常 JSON 输出则连接成功，
    否则报告错误并终止 SSH 进程。

    Args:
        local_host: 本地监听地址，默认 127.0.0.1。
        local_port: 本地监听端口，默认 22267。
        server: SSH 服务器域名。
        server_port: SSH 服务器端口。
        remote_port: 远程端口，默认 '/'（由服务端分配）。
        setup_timeout: 连接建立超时秒数，超时后退出。
    """
    global _ssh_process, _ssh_notfound

    bin = State.deploy_config.SSHExecutable
    cmd = f"{bin} -oStrictHostKeyChecking=no -R {remote_port}:{local_host}:{local_port} -p {server_port} {server} -- --output json"
    args = shlex.split(cmd)
    logger.debug(f"remote access service command: {cmd}")

    if _ssh_process is not None and _ssh_process.poll() is None:
        logger.warning(f"Kill previous ssh process [{_ssh_process.pid}]")
        _ssh_process.kill()
    try:
        _ssh_process = Popen(args, stdout=PIPE, stderr=PIPE)
    except FileNotFoundError as e:
        logger.critical(
            f"无法找到SSH可执行文件{bin}，请安装OpenSSH或在deploy.yaml中指定SSHExecutable"
        )
        _ssh_notfound = True
        return
    logger.info(f"remote access process pid: {_ssh_process.pid}")
    success = False

    def timeout_killer(wait_sec):
        time.sleep(wait_sec)
        if not success and _ssh_process.poll() is None:
            logger.info("Connection timeout, kill ssh process")
            _ssh_process.kill()

    threading.Thread(
        target=timeout_killer, kwargs=dict(wait_sec=setup_timeout), daemon=True
    ).start()

    stdout = _ssh_process.stdout.readline().decode("utf8")
    logger.debug(f"ssh server stdout: {stdout}")
    connection_info = {}
    try:
        connection_info = json.loads(stdout)
        success = True
    except json.decoder.JSONDecodeError:
        if not success and _ssh_process.poll() is None:
            _ssh_process.kill()

    if success:
        if connection_info.get("status", "fail") != "success":
            logger.info(
                f"Failed to establish remote access, this is the error message from service provider: {connection_info.get('message', '')}"
            )
            new_username = connection_info.get("change_username", None)
            if new_username:
                logger.info(f"Server requested to change username, change it to: {new_username}")
                State.deploy_config.SSHUser = new_username
        else:
            global address
            address = connection_info["address"]
            logger.debug(f"Remote access url: {address}")

    # 等待 SSH 进程退出或主线程退出
    while not am_i_the_only_thread() and _ssh_process.poll() is None:
        time.sleep(1)

    if _ssh_process.poll() is None:  # 主线程退出，终止 SSH 进程
        logger.info("App process exit, killing ssh process")
        _ssh_process.kill()
    else:  # SSH 进程自行退出或被超时终止
        stderr = _ssh_process.stderr.read().decode("utf8")
        if stderr:
            logger.error(f"PyWebIO application remote access service error: {stderr}")
        else:
            logger.info("PyWebIO application remote access service exit.")
    address = None


def start_remote_access_service_(**kwargs):
    logger.info("Start remote access service")
    try:
        remote_access_service(**kwargs)
    except KeyboardInterrupt:  # 忽略键盘中断
        pass
    except Exception as e:
        logger.exception(e)
    finally:
        if _ssh_process:
            logger.info("Exception occurred, killing ssh process")
            _ssh_process.kill()
    logger.info("Exit remote access service thread")


class ParseError(Exception):
    pass


def start_remote_access_service(**kwagrs):
    global _ssh_thread

    try:
        server, server_port = State.deploy_config.SSHServer.split(":")
    except (ValueError, AttributeError):
        raise ParseError(
            f"Failed to parse SSH server [{State.deploy_config.SSHServer}]"
        )
    if State.deploy_config.WebuiHost == "0.0.0.0":
        local_host = "127.0.0.1"
    elif State.deploy_config.WebuiHost == "::":
        local_host = "[::1]"
    else:
        local_host = State.deploy_config.WebuiHost

    if State.deploy_config.SSHUser is None:
        logger.info("SSHUser is not set, generate a random one")
        State.deploy_config.SSHUser = random_id(24)

    server = f"{State.deploy_config.SSHUser}@{server}"
    kwagrs.setdefault("server", server)
    kwagrs.setdefault("server_port", server_port)
    kwagrs.setdefault("local_host", local_host)
    kwagrs.setdefault("local_port", State.deploy_config.WebuiPort)

    _ssh_thread = threading.Thread(
        target=start_remote_access_service_,
        kwargs=kwagrs,
        daemon=False,
    )
    _ssh_thread.start()
    return _ssh_thread


class RemoteAccess:
    @staticmethod
    def keep_ssh_alive():
        task_handler: TaskHandler
        task_handler = yield
        while True:
            if _ssh_thread is not None and _ssh_thread.is_alive():
                yield
                continue
            logger.info("Remote access service is not running, starting now")
            try:
                start_remote_access_service()
            except ParseError as e:
                logger.exception(e)
                task_handler.remove_current_task()
            yield

    @staticmethod
    def kill_ssh_process():
        if RemoteAccess.is_alive():
            _ssh_process.kill()

    @staticmethod
    def is_alive():
        return (
            _ssh_thread is not None
            and _ssh_thread.is_alive()
            and _ssh_process is not None
            and _ssh_process.poll() is None
        )

    @staticmethod
    def get_state():
        if RemoteAccess.is_alive():
            if address is not None:
                return 1
            else:
                return 2
        elif _ssh_notfound:
            return 3
        else:
            return 0

    @staticmethod
    def get_entry_point():
        return address if RemoteAccess.is_alive() else None
