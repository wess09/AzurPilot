"""AzurPilot MCP SSE 服务入口。

提供基于 SSE（Server-Sent Events）传输通道的 MCP（Model Context Protocol）服务，
供大语言模型（如 Claude / ChatGPT）查询 AzurPilot 状态、任务列表、读取截图与配置等。
"""

import logging
import re
from contextvars import ContextVar
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import CallToolResult, Tool
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from module.mcp.lifecycle import lifespan
from module.mcp.tools import Tools
from module.runtime import mcp_auth
from module.runtime.setting import State


# 初始化日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("azurpilot-mcp")

# 每个挂载应用独享服务适配器，通过请求上下文传递。
active_tools = ContextVar("mcp_tools", default=Tools())

# 初始化 MCP 服务器
mcp_server = Server("AzurPilot-MCP")

ToolResponse = CallToolResult


@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    """按当前端点的固定注册表列出工具；默认不包含旧名称。"""
    return active_tools.get().definitions()


@mcp_server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: Dict[str, Any]) -> ToolResponse:
    """经统一适配层校验并调用工具，保留结构化错误与 isError。"""
    return await active_tools.get().call(name, arguments)


# SSE 传输层初始化 - 固定端点（与 /mcp 挂载点匹配）
transport = SseServerTransport("/mcp/messages")

# 独立运行时的监听地址与端口
STANDALONE_HOST = "0.0.0.0"
STANDALONE_PORT = 22268

# 从 endpoint 事件中提取 session_id
SESSION_ID_PATTERN = re.compile(rb"session_id=([0-9a-fA-F]{32})")
# 嗅探缓冲区上限，避免为体积无关的 SSE 消息长期占用内存
SNIFF_BUFFER_LIMIT = 4096

# 各拒绝状态对应的响应体
DENIED_MESSAGES = {
    401: "Unauthorized: 缺少或无效的凭据。MCP 复用 WebUI 密码，"
         "请携带 Authorization: Bearer <密码>、X-API-Key 或 ?key=<密码>。",
    405: "Method Not Allowed",
    503: "Service Unavailable: 监听公网但未配置访问密码，MCP 已禁用。"
         "请在 config/deploy.yaml 设置 Password 后重启。",
}


def configure_auth(key, public_bind=False):
    """注入 MCP 的访问密码（复用 WebUI 密码）。

    由 `module.api.app` 在挂载 /mcp 之前调用；独立模式的 `__main__`
    也会调用。传入空值即关闭鉴权（仅在监听回环或演示环境下允许）。

    Args:
        key: 复用自 WebUI 的密码。
        public_bind (bool, optional): 监听地址是否对公网开放。默认为 False。
    """
    mcp_auth.install_access_log_filter()
    mcp_auth.configure(key, public_bind=public_bind)
    logger.info(
        "[MCP] 鉴权%s，监听公网=%s"
        % ("已启用" if mcp_auth.enabled() else "未启用", bool(public_bind))
    )


def _sniff_session_id(message, buffer, captured):
    """从 SSE 出站消息中捕获 MCP 下发给客户端的 session_id。

    只用于"客户端只能在 URL 里填 key"的场景：这类客户端拿到的 POST 地址
    由服务端下发，带不上请求头，因此把 session_id 视为该次已鉴权连接的凭据。

    Args:
        message (dict): ASGI 待发送的消息。
        buffer (list[bytes]): 单元素列表，作为跨分块的嗅探缓冲区。
        captured (list[str]): 已捕获的 session_id 列表。
    """
    if captured or message.get("type") != "http.response.body":
        return
    body = message.get("body") or b""
    if not body:
        return
    buffer[0] = (buffer[0] + body)[-SNIFF_BUFFER_LIMIT:]
    match = SESSION_ID_PATTERN.search(buffer[0])
    if not match:
        return
    session_id = match.group(1).decode("ascii").lower()
    captured.append(session_id)
    buffer[0] = b""
    mcp_auth.register_session(session_id)


async def _run_sse(scope, receive, send):
    """处理 /sse 端点的请求，建立并运行 SSE 流式连接。

    Args:
        scope: ASGI scope 字典。
        receive: ASGI receive 异步可调用对象。
        send: ASGI send 异步可调用对象。
    """
    logger.info("Matched endpoint: /sse. Opening SSE connection...")
    captured = []
    buffer = [b""]

    async def send_wrapper(message):
        _sniff_session_id(message, buffer, captured)
        await send(message)

    try:
        async with transport.connect_sse(scope, receive, send_wrapper) as (read_stream, write_stream):
            logger.info("SSE Stream connected. Running MCP server loop...")
            try:
                options = mcp_server.create_initialization_options()
                await mcp_server.run(read_stream, write_stream, options)
            except Exception as e:
                logger.error(f"MCP Server Loop Error: {e}", exc_info=True)
            logger.info("MCP Server Loop exited.")
    finally:
        # 断开后留一段宽限期，避免客户端最后一帧 POST 被误拒。
        for session_id in captured:
            mcp_auth.expire_session(session_id)


def _is_mcp_client_disconnected(error: Exception) -> bool:
    """判断异常是否属于客户端主动断开连接。

    ClosedResourceError：SSE 已断开但客户端仍在宽限期内投递消息，属正常现象。

    Args:
        error (Exception): 捕获的异常对象。

    Returns:
        bool: 是否属于客户端正常断连。
    """
    return (
        "BrokenResourceError" in str(type(error))
        or "BrokenPipeError" in str(error)
        or "ClosedResourceError" in str(type(error))
    )


async def _handle_mcp_post(scope, receive, send, method):
    """处理客户端通过 POST /messages 发送过来的消息。

    Args:
        scope: ASGI scope 字典。
        receive: ASGI receive 异步可调用对象。
        send: ASGI send 异步可调用对象。
        method (str): HTTP 请求方法。
    """
    logger.info(f"Matched endpoint: /messages. Method: {method}")
    try:
        await transport.handle_post_message(scope, receive, send)
        logger.info("MCP Message POST handled.")
    except Exception as e:
        # 捕获常见的断开连接错误，避免服务器崩溃
        if _is_mcp_client_disconnected(e):
            logger.warning("MCP client disconnected during POST message.")
        else:
            logger.error(f"Error handling MCP message: {e}", exc_info=True)


async def _send_not_found(send):
    """返回 404 Not Found 响应。

    Args:
        send: ASGI send 异步可调用对象。
    """
    await send({
        'type': 'http.response.start',
        'status': 404,
        'headers': [[b'content-type', b'text/plain']]
    })
    await send({
        'type': 'http.response.body',
        'body': b'Not Found'
    })


async def _send_denied(scope, send, status):
    """发送鉴权失败或服务未就绪的拒绝响应。

    刻意不返回 WWW-Authenticate：MCP 客户端会把该响应头判定为
    "本服务要求 OAuth"并转去请求 resource metadata。

    Args:
        scope: ASGI scope 字典。
        send: ASGI send 异步可调用对象。
        status (int): HTTP 状态码。
    """
    body = DENIED_MESSAGES.get(status, "Forbidden").encode("utf-8")
    client = scope.get("client") or ("unknown", 0)
    logger.warning(
        "[MCP] 拒绝请求 %s: %s %s from %s"
        % (
            status,
            scope.get("method", ""),
            mcp_auth.redact(scope.get("path", "")),
            client[0],
        )
    )
    await send({
        'type': 'http.response.start',
        'status': status,
        'headers': [
            [b'content-type', b'text/plain; charset=utf-8'],
            [b'content-length', str(len(body)).encode('ascii')],
        ],
    })
    await send({
        'type': 'http.response.body',
        'body': body,
    })


async def mcp_asgi_app(scope, receive, send):
    """MCP 服务的纯 ASGI 应用，带鉴权与增强日志记录。

    Args:
        scope: ASGI scope 字典。
        receive: ASGI receive 异步可调用对象。
        send: ASGI send 异步可调用对象。
    """
    path = scope.get("path", "")
    method = scope.get("method", "")

    if scope["type"] != "http":
        return

    # 日志脱敏：查询串里的 key 与 session_id 本身就是可用凭据
    query_string = scope.get("query_string") or b""
    logger.info(
        "[MCP] %s %s%s"
        % (
            method,
            mcp_auth.redact(path),
            mcp_auth.redact("?" + query_string.decode("latin-1"))
            if query_string
            else "",
        )
    )

    allowed, status = mcp_auth.authorize(
        path, method, scope.get("headers"), query_string
    )
    if not allowed:
        await _send_denied(scope, send, status)
        return

    # 路由逻辑 - 使用末尾匹配以兼容各种挂载路径和斜线组合
    if path.endswith("/sse"):
        await _run_sse(scope, receive, send)

    elif path.endswith("/messages") or path.endswith("/messages/"):
        await _handle_mcp_post(scope, receive, send, method)

    else:
        await _send_not_found(send)


def create_app(configs=None, runtime=None, *, manage_runtime=True, legacy=False):
    """创建 Starlette 应用实例。

    独立模式管理 State；挂载模式复用宿主注入的服务与生命周期。
    默认只登记 ``azurpilot_`` 工具；``legacy=True`` 显式创建旧名称兼容端点。

    Args:
        configs: 配置映射字典。默认为 None。
        runtime: 运行时管理服务。默认为 None。
        manage_runtime (bool, optional): 是否由本应用接管生命周期。默认为 True。
        legacy (bool, optional): 是否追加已弃用工具名称。默认为 False。

    Returns:
        Starlette: 已配置好的 ASGI Starlette 应用。
    """
    tools = Tools(configs, runtime, allow_legacy=legacy)

    async def bound_app(scope, receive, send):
        token = active_tools.set(tools)
        try:
            await mcp_asgi_app(scope, receive, send)
        finally:
            active_tools.reset(token)

    application = Starlette(
        lifespan=lifespan if manage_runtime else None,
        middleware=[Middleware(CORSMiddleware, allow_origins=["*"],
                               allow_methods=["*"], allow_headers=["*"])],
    )
    application.state.tools = tools
    application.mount("/", bound_app)
    return application


def create_legacy_app(configs=None, runtime=None, *, manage_runtime=True):
    """显式创建旧工具名兼容入口；新部署不应默认挂载它。"""
    return create_app(configs, runtime, manage_runtime=manage_runtime, legacy=True)


app = create_app()


def _resolve_standalone_password():
    """独立模式解析访问密码，与 WebUI 共用同一份来源与生成规则。

    顺序：``deploy.yaml`` 的 ``Password`` → 未设置且监听公网时自动生成并
    写入 ``password.txt``（同时回写部署配置，保证 WebUI 与 MCP 始终一致）。

    Returns:
        str | None: 有效密码，None 表示未配置。
    """
    from module.runtime.password_utils import ensure_password_for_host, is_demo_mode

    password = State.deploy_config.Password
    try:
        password = ensure_password_for_host(password, STANDALONE_HOST, demo=is_demo_mode())
    except Exception as e:
        logger.exception(f"[MCP] 自动生成密码失败: {e}")
        return None

    if password and password != State.deploy_config.Password:
        # 触发部署配置落盘，避免每次重启都换一把新密码
        State.deploy_config.Password = password
        logger.warning(
            "[MCP] 已自动生成密码，请在根目录 password.txt 或 config/deploy.yaml 查看。"
        )
    return password


if __name__ == "__main__":
    import uvicorn

    logger.info(f"[MCP] 启动 AzurPilot MCP 服务 (Port: {STANDALONE_PORT})")
    configure_auth(_resolve_standalone_password(), public_bind=True)
    uvicorn.run(app, host=STANDALONE_HOST, port=STANDALONE_PORT)
