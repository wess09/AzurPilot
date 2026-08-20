"""游戏服务器状态检查器。

通过 server-checker.nanoda.work 查询碧蓝航线服务器状态。在任务调度前
检查所选服务器是否可用，避免在维护或尚未开放期间执行无效操作。
"""

from collections import deque
from json import JSONDecodeError

import requests

from module.base.timer import Timer
from module.config.server import VALID_SERVER_LIST as server_list
from module.config.server import ServerInfo, get_server_info
from module.exception import ScriptError, WorkerStop
from module.logger import logger

SERVER_API_BASE = 'https://server-checker.nanoda.work'
AVAILABLE_SERVER_STATES = {'normal', 'full', 'reg_full'}
UNAVAILABLE_SERVER_STATES = {'maintenance', 'unopened', 'unknown'}


class ServerApiUnavailableError(requests.exceptions.ConnectionError):
    """服务器检查 API 的临时可用性错误。"""


class ServerChecker:
    """游戏服务器状态检查器。"""

    def __init__(self, server: str) -> None:
        self._base = SERVER_API_BASE
        self._server_info: ServerInfo | None = None
        if server == 'disabled':
            self._server = 'disabled'
        else:
            self._server_info = get_server_info(server)
            self._server = self._server_info.name

        self._state: deque[bool] = deque(maxlen=2)
        self._timer = Timer(0)
        self._recover = False
        self._retry = False

        self.check_now()

    def _load_server(self) -> None:
        """
        通过 API 获取当前服务器状态。

        无法取得状态的临时网络或服务端错误会走快速重试；响应结构错误和
        非预期客户端错误则抛出 ``ScriptError``，由顶层临时禁用检测器。
        """
        if self._server == 'disabled':
            self._state.append(True)
            return

        assert self._server_info is not None
        try:
            session = requests.Session()
            session.trust_env = False
            response = session.get(
                url=(
                    f'{self._base}/api/v1/servers/'
                    f'{self._server_info.region}_{self._server_info.server_id}'
                ),
                timeout=15,
            )
            if response.status_code == 200:
                self._load_response(response.json())
            elif response.status_code == 404:
                # 本地元数据可能已更新而 API 尚未收录，保留旧接口的兼容降级。
                if self._server_in_local_list():
                    self._state.append(True)
                    logger.info(
                        f'[服务器检查] 服务器 "{self._server}" 可用（本地已验证，API未知）。'
                    )
                else:
                    self._state.append(False)
                    raise ScriptError(f'Server "{self._server}" does not exist!')
            elif response.status_code == 429 or response.status_code >= 500:
                raise ServerApiUnavailableError(
                    f'Get status_code {response.status_code}. '
                    f'Response is {getattr(response, "text", "")}'
                )
            else:
                raise ScriptError(
                    f'Get status_code {response.status_code}. '
                    f'Response is {getattr(response, "text", "")}'
                )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logger.error(e)
            logger.error('服务器检查 API 暂时不可用。')
            if self._retry:
                self._state.append(False)
            else:
                self._state.append(self.fast_retry())
        except (JSONDecodeError, ValueError) as e:
            self._state.append(False)
            raise ScriptError('服务器检查 API 返回的 JSON 无效。') from e
        except Exception as e:
            logger.error(e)
            self._state.append(False)
            raise

    def _load_response(self, payload: object) -> None:
        """校验单服响应并记录可用状态。"""
        if not isinstance(payload, dict):
            raise ScriptError('服务器检查 API 返回结构无效。')

        server = payload.get('server')
        if not isinstance(server, dict):
            raise ScriptError('服务器检查 API 未返回服务器数据。')

        assert self._server_info is not None
        server_id = server.get('id')
        name = server.get('name')
        status = server.get('status')
        if not isinstance(server_id, int) or not isinstance(name, str) or not isinstance(status, str):
            raise ScriptError('服务器检查 API 返回的服务器字段无效。')
        if server_id != self._server_info.server_id:
            raise ScriptError(
                f'服务器检查 API 返回了错误的 ID：期望 {self._server_info.server_id}，'
                f'实际 {server_id}。'
            )
        if name != self._server:
            raise ScriptError(
                f'服务器检查 API 返回了错误的服务器：期望 "{self._server}"，实际 "{name}"。'
            )

        if status in AVAILABLE_SERVER_STATES:
            self._state.append(True)
            logger.info(f'[服务器检查] 服务器 "{self._server}" 可用（{status}）。')
        elif status in UNAVAILABLE_SERVER_STATES:
            self._state.append(False)
            logger.info(f'[服务器检查] 服务器 "{self._server}" 暂不可用（{status}）。')
        else:
            raise ScriptError(f'服务器检查 API 返回了未知状态：{status}')

    def wait_until_available(self, stop_event=None) -> None:
        """等待服务器恢复，并在 worker 停止时及时中断等待。"""
        while not self.is_available():
            if stop_event is not None and stop_event.is_set():
                raise WorkerStop

            # 维护等待最长可达 600 秒。线程宿主拆成短片段，避免停止按钮
            # 被服务器维护等待吞掉数分钟。
            if stop_event is None:
                self._timer.wait()
            else:
                while True:
                    if stop_event.is_set():
                        raise WorkerStop
                    remaining = self._timer.limit - self._timer.current_time()
                    if remaining <= 0:
                        break
                    if stop_event.wait(min(remaining, 0.5)):
                        raise WorkerStop

            if stop_event is not None and stop_event.is_set():
                raise WorkerStop
            self.check_now()

    def check_now(self) -> None:
        """
        忽略计时器，立即获取服务器状态。

        若服务器不可用，计时器间隔逐步从 2 分钟递增至 10 分钟。若 API
        协议不兼容，检查器会临时禁用，避免阻断任务调度。
        """
        try:
            self._load_server()
            if self._state[-1]:
                self._timer.limit = 0
                if not self._state[0]:
                    self._recover = True
            else:
                if self._timer.limit < 600:
                    self._timer.limit += 120
                logger.info(f'服务器检查器将在 {self._timer.limit}s 后重试。')
            self._timer.reset()
        except ScriptError as e:
            logger.warning(str(e))
            logger.warning('服务器检查可能有问题。')
            logger.warning('请联系开发者修复。')
            self.reset()
            self._server = 'disabled'
            self._server_info = None
            self._recover = True
            self._state.append(True)

    def _server_in_local_list(self) -> bool:
        """检查服务器名称是否存在于本地配置列表。"""
        return any(self._server in servers for servers in server_list.values())

    def reset(self) -> None:
        self._timer.limit = 0
        self._recover = False

    def is_available(self) -> bool:
        """使用缓存返回服务器状态。"""
        if self._timer.limit != 0 and self._timer.reached():
            self.check_now()

        return self._state[-1]

    def is_recovered(self) -> bool:
        """服务器是否刚从不可用状态恢复。"""
        if len(self._state) < 2:
            self._recover = False
            return False

        if self._recover:
            self._recover = False
            return True

        return False

    def fast_retry(self) -> bool:
        """
        快速重试：通过访问百度判断网络是否连通。

        部分国内用户可能无法连接 API，但网络实际可用，因此借助百度进行
        网络可达性判断。快速重试中的中间状态不会污染原有状态队列。
        """
        self._retry = True
        try:
            try:
                session = requests.Session()
                session.trust_env = False
                session.get('https://www.baidu.com', timeout=5)
                network_available = True
            except requests.exceptions.RequestException as e:
                logger.error(e)
                network_available = False

            logger.attr('network_available', network_available)
            if not network_available:
                logger.error('网络不可用，请检查网络状态。')
                return False

            logger.info('触发服务器检查快速重试。')
            last = self._state.copy()
            for attempt in range(3):
                logger.info(f'重试 {attempt + 1} 次 ...')
                self._load_server()
                if self._state[-1]:
                    self._state.clear()
                    self._state.extend(last)
                    return True

            self._state.clear()
            self._state.extend(last)
            logger.error('无法连接服务器检查 API，请检查网络或禁用服务器检测。')
            return False
        finally:
            self._retry = False
