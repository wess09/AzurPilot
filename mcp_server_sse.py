import os
import asyncio
import logging
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.types import (
    TextContent,
    Tool,
)

from module.config.config import AzurLaneConfig
from module.config.utils import alas_instance
from module.webui.process_manager import ProcessManager
from module.config.mcp_helper import McpConfigHelper

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alas-mcp")

# Initialize Helper
helper = McpConfigHelper()

# Initialize MCP Server
mcp_server = Server("ALAS-MCP")

@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="list_instances",
            description="列出所有已配置的 ALAS 实例名称",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_status",
            description="获取所有 ALAS 实例的运行状态及详细状态 (state)",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="list_tasks",
            description="列出所有顶级任务名称（如 Main, Event）",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_task_help",
            description="获取指定任务的详细参数结构、中文名和帮助文档",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "任务名称"}
                },
                "required": ["task_name"]
            }
        ),
        Tool(
            name="get_resources",
            description="获取指定实例的资源状态（油、金币、红尖尖等）",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance": {"type": "string", "description": "实例名称"}
                },
                "required": ["instance"]
            }
        ),
        Tool(
            name="get_config",
            description="获取指定实例的当前配置值",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance": {"type": "string", "description": "实例名称"},
                    "task": {"type": "string", "description": "可选，过滤特定任务"}
                },
                "required": ["instance"]
            }
        ),
        Tool(
            name="update_config",
            description="修改指定实例的配置项。路径格式：task.group.arg",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance": {"type": "string", "description": "实例名称"},
                    "task": {"type": "string"},
                    "group": {"type": "string"},
                    "arg": {"type": "string"},
                    "value": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "boolean"},
                            {"type": "object"},
                            {"type": "array"},
                            {"type": "null"}
                        ],
                        "description": "新的配置值"
                    }
                },
                "required": ["instance", "task", "group", "arg", "value"]
            }
        ),
        Tool(
            name="get_recent_logs",
            description="读取指定实例最近的日志内容 (默认为 50 行)",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance": {"type": "string"},
                    "lines": {"type": "integer", "default": 50}
                },
                "required": ["instance"]
            }
        ),
        Tool(
            name="start_instance",
            description="启动 ALAS 实例的运行过程",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance": {"type": "string"}
                },
                "required": ["instance"]
            }
        ),
        Tool(
            name="stop_instance",
            description="强制停止运行中的 ALAS 实例",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance": {"type": "string"}
                },
                "required": ["instance"]
            }
        ),
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "list_instances":
            instances = alas_instance()
            return [TextContent(type="text", text=json.dumps(instances, ensure_ascii=False, indent=2, default=str))]
        
        elif name == "get_status":
            instances = alas_instance()
            results = []
            for inst in instances:
                manager = ProcessManager.get_manager(inst)
                results.append({"instance": inst, "running": manager.alive, "state": manager.state})
            return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2, default=str))]

        elif name == "list_tasks":
            tasks = helper.get_tasks()
            return [TextContent(type="text", text=json.dumps(tasks, ensure_ascii=False, indent=2, default=str))]

        elif name == "get_task_help":
            task_name = arguments["task_name"]
            details = helper.get_task_details(task_name)
            return [TextContent(type="text", text=json.dumps(details, ensure_ascii=False, indent=2, default=str))]

        elif name == "get_resources":
            inst = arguments["instance"]
            config = AzurLaneConfig(inst)
            res = helper.get_dashboard_resources(config.data)
            return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False, indent=2, default=str))]

        elif name == "get_config":
            inst = arguments["instance"]
            task = arguments.get("task")
            config = AzurLaneConfig(inst)
            data = config.data.get(task, {}) if task else config.data
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2, default=str))]

        elif name == "update_config":
            inst = arguments["instance"]
            task = arguments["task"]
            group = arguments["group"]
            arg = arguments["arg"]
            value = arguments["value"]
            config = AzurLaneConfig(inst)
            path = f"{task}.{group}.{arg}"
            config.cross_set(path, value)
            config.save()
            return [TextContent(type="text", text=f"Success: Updated {path} to {value}")]

        elif name == "get_recent_logs":
            inst = arguments["instance"]
            lines_count = arguments.get("lines", 50)
            
            # ALAS 日志命名规则通常是 YYYY-MM-DD_实例名.txt
            import datetime
            date_str = datetime.date.today().strftime("%Y-%m-%d")
            log_file = f"./log/{date_str}_{inst}.txt"
            
            if not os.path.exists(log_file):
                # 尝试不带实例名的通用日志
                log_file_alt = f"./log/{date_str}_alas.txt"
                if os.path.exists(log_file_alt):
                    log_file = log_file_alt
            
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        # 对于超大文件，使用 tail 逻辑更安全
                        # 为了简单这里仍使用 readlines，但限制读取范围
                        content = f.readlines()
                        content = content[-lines_count:]
                    return [TextContent(type="text", text="".join(content))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error reading log: {str(e)}")]
            return [TextContent(type="text", text=f"Log file not found: {log_file}")]

        elif name == "start_instance":
            inst = arguments["instance"]
            manager = ProcessManager.get_manager(inst)
            if manager.alive:
                return [TextContent(type="text", text=f"Error: {inst} is already running.")]
            from module.submodule.utils import get_config_mod
            func = get_config_mod(inst)
            manager.start(func=func)
            return [TextContent(type="text", text=f"Success: Started {inst} ({func})")]

        elif name == "stop_instance":
            inst = arguments["instance"]
            manager = ProcessManager.get_manager(inst)
            if not manager.alive:
                return [TextContent(type="text", text=f"Error: {inst} is not running.")]
            manager.stop()
            return [TextContent(type="text", text=f"Success: Stopped {inst}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.exception(f"Tool {name} error")
        return [TextContent(type="text", text=f"Error: {str(e)}")]

# SSE Setup - Fixed Endpoint (Matching the /mcp mount point)
transport = SseServerTransport("/mcp/messages")

async def mcp_asgi_app(scope, receive, send):
    """
    Pure ASGI application for MCP service with enhanced logging.
    """
    path = scope.get("path", "")
    method = scope.get("method", "")
    
    if scope["type"] == "http":
        logger.info(f"Incoming ASGI HTTP: {method} {path}")
        
        # Route logic - Flexible endswith matching to handle various mount/slash combinations
        if path.endswith("/sse"):
            logger.info("Matched endpoint: /sse. Opening SSE connection...")
            async with transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
                logger.info("SSE Stream connected. Running MCP server loop...")
                try:
                    options = mcp_server.create_initialization_options()
                    await mcp_server.run(read_stream, write_stream, options)
                except Exception as e:
                    logger.error(f"MCP Server Loop Error: {e}", exc_info=True)
                logger.info("MCP Server Loop exited.")
        
        elif path.endswith("/messages") or path.endswith("/messages/"):
            logger.info(f"Matched endpoint: /messages. Method: {method}")
            try:
                await transport.handle_post_message(scope, receive, send)
                logger.info("MCP Message POST handled.")
            except Exception as e:
                # 捕获常见的断开连接错误，避免服务器崩溃
                if "BrokenResourceError" in str(type(e)) or "BrokenPipeError" in str(e):
                    logger.warning("MCP client disconnected during POST message.")
                else:
                    logger.error(f"Error handling MCP message: {e}", exc_info=True)
        
        else:
            # Fallback 404
            await send({
                'type': 'http.response.start',
                'status': 404,
                'headers': [[b'content-type', b'text/plain']]
            })
            await send({
                'type': 'http.response.body',
                'body': b'Not Found'
            })

# Starlette Wrapper
app = Starlette(
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    ]
)
app.mount("/", mcp_asgi_app)

if __name__ == "__main__":
    import uvicorn
    logger.info("启动 ALAS MCP 服务 (Port: 22268)")
    uvicorn.run(app, host="0.0.0.0", port=22268)
