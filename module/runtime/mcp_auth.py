"""MCP 接口的鉴权：凭据提取、常数时间比对、会话登记与日志脱敏。

MCP 把 15 个 ``azurpilot_`` 工具（含停止实例、改配置、git pull 等破坏性操作）
直接暴露在 HTTP 上，而 WebUI 的密码校验发生在 PyWebIO 会话内部，管不到挂载的
ASGI 子应用，所以这里单独做一层。密钥复用 WebUI 密码（``--key`` /
``deploy.yaml`` 的 ``Password``），不引入第二把密钥；支持
``Authorization: Bearer`` / ``X-API-Key`` 请求头与 ``?key=`` 查询参数两种
传参方式，以兼容只能填 URL 的 MCP 客户端。工具名称由
``module/mcp/registry.py`` 决定，鉴权只按端点放行，不按工具分级。

本模块只依赖标准库：既能独立单元测试，也避免把 WebUI/OCR 的依赖链带进
独立运行的 MCP 进程。所有判定集中在 :func:`authorize`，ASGI 层只做转发。
"""
from module.base.runtime_params import SESSION_DISCONNECT_GRACE_SECONDS, SESSION_MAX_ENTRIES, SESSION_TTL_SECONDS
import logging
import re
import secrets
import threading
import time
from urllib.parse import parse_qsl

from module.runtime.password_utils import is_webui_password_set

#: 允许通过查询参数传递凭据的参数名，按优先级排列
QUERY_KEY_NAMES = ("key", "api_key", "token")
#: MCP 的 SSE 与消息端点及其允许的方法
ROUTE_METHODS = {"/sse": "GET", "/messages": "POST"}

#: 各种凭据在日志中的出现形式及对应的脱敏结果
_SENSITIVE_PATTERNS = (
    (
        re.compile(r"(?i)\b(key|api_key|token|password|session_id)=([^&\s\"']*)"),
        lambda m: f"{m.group(1)}=***",
    ),
    (
        re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/=-]+)"),
        lambda m: f"{m.group(1)} ***",
    ),
)

_lock = threading.Lock()
_key = None            #: 当前有效密码，None 表示未配置
_public_bind = False   #: 监听地址是否对公网开放
_sessions = {}         #: session_id -> 过期时间（time.monotonic()）


def configure(key, public_bind: bool = False):
    """登记 MCP 的有效密码，由 WebUI 工厂或独立模式的入口调用。

    幂等：重复调用会以最后一次为准并清空会话登记表，避免 WebUI 应用工厂
    被多次调用（热重载、测试）时残留旧会话。

    Args:
        key: 复用自 WebUI 的密码，留空表示未配置。
        public_bind: 监听地址是否对公网开放。
    """
    global _key, _public_bind
    with _lock:
        _key = str(key) if is_webui_password_set(key) else None
        _public_bind = bool(public_bind)
        _sessions.clear()


def enabled() -> bool:
    """检查鉴权是否生效。

    Returns:
        bool: True 表示已配置密码，所有请求都必须携带凭据。
    """
    with _lock:
        return bool(_key)


def deny_all() -> bool:
    """检查是否处于"未配置密码却监听公网"的兜底拒绝状态。

    只可能出现在 DEMO=1 或自动生成密码失败时；此时宁可整体拒绝，也不能
    在公网上开放一个自称已鉴权的远程控制端点。

    Returns:
        bool: True 表示应拒绝全部 MCP 请求。
    """
    with _lock:
        return not _key and _public_bind


def check(candidate) -> bool:
    """常数时间比较候选凭据是否与当前密码一致。

    Args:
        candidate: 候选凭据，None 直接判否。

    Returns:
        bool: 凭据正确返回 True，否则返回 False。
    """
    if candidate is None:
        return False
    with _lock:
        key = _key
    if not key:
        return False
    try:
        return secrets.compare_digest(
            str(candidate).encode("utf-8"), key.encode("utf-8")
        )
    except (TypeError, UnicodeError):
        # 含孤立代理对等无法编码的输入一律判否，不要抛出 500。
        return False


def route_of(path: str) -> str | None:
    """把请求路径归一到 MCP 的两个端点。

    与 ``mcp_asgi_app`` 的路由规则保持一致，用末尾匹配兼容挂载前缀。

    Args:
        path: 请求路径。

    Returns:
        str | None: ``/sse``、``/messages`` 或 None（非 MCP 端点）。
    """
    if path.endswith("/sse"):
        return "/sse"
    if path.endswith("/messages") or path.endswith("/messages/"):
        return "/messages"
    return None


def _decode_query(query_string: bytes) -> list[tuple[str, str]]:
    """解析原始查询串，遇到非法字节不会抛出异常。

    Args:
        query_string: ASGI scope 中的原始查询字节串。

    Returns:
        list[tuple[str, str]]: 解码后的键值对列表，保持原始顺序。
    """
    if not query_string:
        return []
    if isinstance(query_string, bytes):
        try:
            query_string = query_string.decode("utf-8")
        except UnicodeDecodeError:
            # 未经百分号编码的原始字节，退回 latin-1 保证不抛异常。
            query_string = query_string.decode("latin-1")
    return parse_qsl(query_string, keep_blank_values=True)


def extract_credential(headers, query_string: bytes) -> str | None:
    """从请求头和查询参数中提取候选凭据。

    同名参数出现多次时只取第一个，不做"任一匹配"，以免放大试探面。

    Args:
        headers: ASGI scope 的 headers，形如 [(b"name", b"value")]。
        query_string: ASGI scope 的 query_string。

    Returns:
        str | None: 候选凭据；未找到返回 None。
    """
    api_key = None
    bearer = None
    for name, value in headers or ():
        name = bytes(name).decode("latin-1").strip().lower()
        if name == "authorization":
            value = _decode_header_value(value).strip()
            if value[:7].lower() == "bearer ":
                bearer = value[7:].strip()
        elif name == "x-api-key" and api_key is None:
            api_key = _decode_header_value(value)

    query = {}
    for name, value in _decode_query(query_string):
        if name in QUERY_KEY_NAMES and name not in query:
            query[name] = value

    for candidate in (bearer, api_key, *(query.get(name) for name in QUERY_KEY_NAMES)):
        if candidate:
            return candidate
    return None


def _decode_header_value(value: bytes) -> str:
    """解码请求头原始字节串。

    HTTP 头按 ASGI 规范是 latin-1，但客户端往往直接传递 UTF-8 字节，这里优先
    按 UTF-8 解码，失败再退回 latin-1。

    Args:
        value: 请求头原始字节。

    Returns:
        str: 解码后的字符串。
    """
    value = bytes(value)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("latin-1")


def extract_session_id(query_string: bytes) -> str | None:
    """取出 POST 请求携带的 MCP 会话 ID。

    Args:
        query_string: ASGI scope 的 query_string。

    Returns:
        str | None: 形如 32 位十六进制的会话 ID。
    """
    for name, value in _decode_query(query_string):
        if name == "session_id":
            if re.fullmatch(r"[0-9a-fA-F]{32}", value or ""):
                return value.lower()
            return None
    return None


def register_session(session_id: str):
    """登记一个已通过鉴权的 SSE 会话。

    Args:
        session_id: 由 MCP 传输层生成并下发给客户端的会话 ID。
    """
    if not session_id:
        return
    with _lock:
        _purge_locked()
        _sessions[session_id] = time.monotonic() + SESSION_TTL_SECONDS
        while len(_sessions) > SESSION_MAX_ENTRIES:
            _sessions.pop(next(iter(_sessions)), None)


def expire_session(session_id: str, grace: int = SESSION_DISCONNECT_GRACE_SECONDS):
    """SSE 连接结束后把会话置为宽限期内有效。

    Args:
        session_id: 会话 ID。
        grace: 宽限秒数。
    """
    if not session_id:
        return
    with _lock:
        if session_id in _sessions:
            _sessions[session_id] = time.monotonic() + max(int(grace), 0)


def is_authorized_session(session_id: str | None) -> bool:
    """判断会话是否为某个已鉴权 SSE 连接建立的会话。

    session_id 由 uuid4 生成并经已鉴权的 SSE 通道下发，本身即一次性凭据，
    用于支撑"客户端只能在 URL 里填 key"的场景：这类客户端的 POST 地址由
    服务端下发，带不上请求头。

    Args:
        session_id: 会话 ID。

    Returns:
        bool: 该会话仍在有效期内返回 True，否则返回 False。
    """
    if not session_id:
        return False
    with _lock:
        _purge_locked()
        expire = _sessions.get(session_id)
        if expire is None:
            return False
        # 客户端仍在活跃，滑动续期
        _sessions[session_id] = time.monotonic() + SESSION_TTL_SECONDS
        return True


def _purge_locked():
    """清理已过期的会话记录，调用方需预先持有 ``_lock``。"""
    now = time.monotonic()
    for session_id in [k for k, v in _sessions.items() if v < now]:
        _sessions.pop(session_id, None)


def authorize(path: str, method: str, headers, query_string: bytes) -> tuple[bool, int | None]:
    """判定一次 MCP HTTP 请求是否允许放行。

    Args:
        path: 请求路径。
        method: HTTP 方法。
        headers: ASGI scope 的 headers。
        query_string: ASGI scope 的 query_string。

    Returns:
        tuple[bool, int | None]: (是否放行, 不放行时的建议 HTTP 状态码)。
    """
    route = route_of(path)
    if route is None:
        # 非 MCP 端点交给后续路由处理，这里不拦。
        return True, None

    if str(method or "").upper() != ROUTE_METHODS[route]:
        return False, 405

    if deny_all():
        return False, 503

    if not enabled():
        # 未配置密码且只监听回环，与 WebUI 自身的暴露面一致。
        return True, None

    if check(extract_credential(headers, query_string)):
        return True, None

    if route == "/messages" and is_authorized_session(
        extract_session_id(query_string)
    ):
        return True, None

    return False, 401


def redact(text: str) -> str:
    """抹掉文本中的凭据与会话 ID，避免日志输出泄露敏感凭据。

    命中 ``?key=xxx`` 这类查询参数、``Authorization: Bearer xxx`` 以及
    uvicorn access log 中的请求行。

    Args:
        text: 任意待输出的文本。

    Returns:
        str: 脱敏后的文本。
    """
    if not text:
        return text
    text = str(text)
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_arg(value):
    """只对字符串类型的参数做脱敏，保持参数数据结构不变。

    Args:
        value: 待脱敏的参数对象。

    Returns:
        Any: 脱敏后的参数值。
    """
    return redact(value) if isinstance(value, str) else value


class _RedactFilter(logging.Filter):
    """为 uvicorn access log 脱敏的日志过滤器。

    必须保持 ``record.args`` 的结构：uvicorn 的 AccessFormatter 会把访问日志
    的参数解包成 ``(client_addr, method, full_path, http_version, status_code)``
    五元组，清空或替换结构会让日志格式化直接报错。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """过滤并脱敏单条日志记录中的请求路径与消息文本。

        Args:
            record: 日志记录对象。

        Returns:
            bool: 始终返回 True 表示放行该日志。
        """
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _redact_arg(v) for k, v in record.args.items()}
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def install_access_log_filter():
    """为 uvicorn access log 注册脱敏过滤器，重复调用无副作用。"""
    access_logger = logging.getLogger("uvicorn.access")
    if any(isinstance(f, _RedactFilter) for f in access_logger.filters):
        return
    access_logger.addFilter(_RedactFilter())


def _reset():
    """清空全部状态，仅供单元测试使用。"""
    configure(None, False)
