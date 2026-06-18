---
description:
alwaysApply: true
---

# mcp_server_sse.py 入口文件深度分析

## 1. 文件基础信息

| 项目 | 内容 |
|---|---|
| 文件路径 | `mcp_server_sse.py` |
| 总行数 | 517 行 |
| 文件类型 | Python 脚本（MCP SSE 服务器） |
| 许可证 | GPL-3.0 |
| 服务器名称 | `"ALAS-MCP"` |
| 默认端口 | 22268 |
| SSE 端点 | `/sse` |
| 消息端点 | `/mcp/messages` |

### 导入依赖

| 模块来源 | 具体导入 | 用途 |
|---|---|---|
| 标准库 | `os`, `asyncio`, `logging`, `json`, `datetime`, `base64`, `time`, `subprocess`, `threading`, `re` | 系统操作、异步、日志、序列化、时间、编码、进程、线程、正则 |
| 标准库 | `typing.List, Optional, Dict, Any` | 类型注解 |
| 标准库 | `io.BytesIO` | 内存字节流 |
| 第三方 | `starlette.applications.Starlette` | ASGI 框架 |
| 第三方 | `starlette.middleware.Middleware` | 中间件 |
| 第三方 | `starlette.middleware.cors.CORSMiddleware` | CORS 跨域支持 |
| 第三方 | `mcp.server.Server` | MCP 服务器核心 |
| 第三方 | `mcp.server.models.InitializationOptions` | MCP 初始化选项 |
| 第三方 | `mcp.server.sse.SseServerTransport` | SSE 传输层 |
| 第三方 | `mcp.types.TextContent, ImageContent, Tool` | MCP 类型定义 |
| 第三方 | `cv2` | OpenCV（导入但未直接使用） |
| 项目内部 | `module.config.config.AzurLaneConfig` | 配置系统 |
| 项目内部 | `module.config.utils.alas_instance` | 实例列表 |
| 项目内部 | `module.webui.process_manager.ProcessManager` | 进程管理 |
| 项目内部 | `module.config.mcp_helper.McpConfigHelper` | MCP 配置辅助 |
| 项目内部 | `module.webui.setting.State` | WebUI 全局状态 |
| 可选 | `module.webui.fake_pil_module.remove_fake_pil_module` | PIL 模块伪装清理 |

---

## 2. 模块级初始化 (L38-L46)

```python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alas-mcp")

helper = McpConfigHelper()

mcp_server = Server("ALAS-MCP")
```

- **日志**: 使用标准库 `logging`（非项目的 `module.logger`），级别 INFO
- **helper**: `McpConfigHelper` 实例，加载 `args.json` 和 i18n 数据
- **mcp_server**: MCP 服务器实例，名称 `"ALAS-MCP"`

---

## 3. `list_tools()` 工具注册 (L48-L199)

```python
@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
```

注册 18 个 MCP 工具。每个工具定义了 `name`、`description` 和 `inputSchema`。

### 3.1 工具清单

| # | 工具名 | 功能 | 必需参数 | 可选参数 |
|---|---|---|---|---|
| 1 | `list_instances` | 列出所有 AzurPilot 实例 | 无 | 无 |
| 2 | `get_status` | 获取所有实例运行状态 | 无 | 无 |
| 3 | `list_tasks` | 列出所有顶级任务名 | 无 | 无 |
| 4 | `get_task_help` | 获取任务详细参数结构 | `task_name` | 无 |
| 5 | `get_resources` | 获取实例资源状态 | `instance` | 无 |
| 6 | `get_config` | 获取实例当前配置 | `instance` | `task` |
| 7 | `update_config` | 修改配置项 | `instance`, `task`, `group`, `arg`, `value` | 无 |
| 8 | `get_recent_logs` | 读取最近日志 | `instance` | `lines` (默认 50) |
| 9 | `start_instance` | 启动实例 | `instance` | 无 |
| 10 | `stop_instance` | 停止实例 | `instance` | 无 |
| 11 | `get_screenshot` | 获取模拟器截图 | `instance` | 无 |
| 12 | `get_current_running_task` | 获取当前执行的子任务 | `instance` | 无 |
| 13 | `get_scheduler_queue` | 获取任务排队列表 | `instance` | 无 |
| 14 | `trigger_task` | 强制立即执行任务 | `instance`, `task` | 无 |
| 15 | `clear_scheduler_queue` | 清空任务队列 | `instance` | 无 |
| 16 | `restart_emulator` | 重启模拟器 | `instance` | 无 |
| 17 | `restart_adb` | 重启 ADB 服务 | 无 | `instance` |
| 18 | `update_alas` | 触发 Git Pull 更新 | 无 | 无 |

### 3.2 inputSchema 设计

所有工具使用 JSON Schema 定义输入参数：

```python
# 简单示例 - 无参数
inputSchema={"type": "object", "properties": {}}

# 复杂示例 - 多参数
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
```

**注意**: `update_config` 的 `value` 参数使用 `oneOf` 支持多种类型，这是 MCP 工具中较复杂的 schema 设计。

---

## 4. `call_tool(name, arguments)` 工具调用处理 (L201-L454)

```python
@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
```

**这是所有工具调用的统一分发函数。**

- **参数**: `name` (str) - 工具名, `arguments` (Dict) - 工具参数
- **返回**: `List[TextContent]` 或 `List[ImageContent]`
- **错误处理**: 外层 `try/except` 捕获所有异常，返回错误文本

### 4.1 逐工具分析

#### `list_instances` (L204-L206)

```python
instances = alas_instance()
return [TextContent(type="text", text=json.dumps(instances, ensure_ascii=False, indent=2, default=str))]
```

- **数据源**: `alas_instance()` 从 `config/` 目录扫描 JSON 配置文件
- **返回**: JSON 格式的实例名列表

#### `get_status` (L208-L214)

```python
instances = alas_instance()
results = []
for inst in instances:
    manager = ProcessManager.get_manager(inst)
    results.append({"instance": inst, "running": manager.alive, "state": manager.state})
```

- **数据源**: `ProcessManager` 单例管理器
- **返回**: 每个实例的 `{instance, running, state}`
- **性能**: 遍历所有实例，每个实例获取一次进程状态

#### `list_tasks` (L216-L218)

```python
tasks = helper.get_tasks()
```

- **数据源**: `McpConfigHelper.get_tasks()` 从 `args.json` 提取任务名
- **返回**: 任务名列表

#### `get_task_help` (L220-L223)

```python
task_name = arguments["task_name"]
details = helper.get_task_details(task_name)
```

- **数据源**: `McpConfigHelper.get_task_details()` 从 `args.json` + i18n 数据组装
- **返回**: 包含 `task_name`, `display_name`, `help`, `groups` 的详细结构

#### `get_resources` (L225-L229)

```python
config = AzurLaneConfig(inst)
res = helper.get_dashboard_resources(config.data)
```

- **数据源**: 实例配置中的 `Dashboard` 节点
- **返回**: 资源状态（油、金币、红尖尖等）的 Value/Limit/Total

#### `get_config` (L231-L236)

```python
config = AzurLaneConfig(inst)
data = config.data.get(task, {}) if task else config.data
```

- **参数**: `instance` (必需), `task` (可选过滤)
- **返回**: 配置数据（可按任务过滤）

#### `update_config` (L238-L248)

```python
config = AzurLaneConfig(inst)
path = f"{task}.{group}.{arg}"
config.cross_set(path, value)
config.save()
```

- **功能**: 修改指定配置项并保存到磁盘
- **路径格式**: `Task.Group.Arg`（如 `Research.Scheduler.Enable`）
- **副作用**: 写入 `config/{instance}.json`

#### `get_recent_logs` (L250-L274)

```python
date_str = datetime.date.today().strftime("%Y-%m-%d")
log_file = f"./log/{date_str}_{inst}.txt"
```

- **日志路径**: `./log/YYYY-MM-DD_{instance}.txt`，回退到 `./log/YYYY-MM-DD_alas.txt`
- **返回**: 最近 N 行日志（默认 50）
- **实现**: 读取整个文件后截取最后 N 行（对大文件不高效）

#### `start_instance` (L276-L284)

```python
manager = ProcessManager.get_manager(inst)
if manager.alive:
    return [TextContent(type="text", text=f"Error: {inst} is already running.")]
from module.submodule.utils import get_config_mod
func = get_config_mod(inst)
manager.start(func=func)
```

- **前置检查**: 已运行则返回错误
- **功能**: 通过 `ProcessManager` 启动实例子进程
- **模块选择**: `get_config_mod()` 根据配置确定要运行的模块

#### `stop_instance` (L286-L292)

```python
manager = ProcessManager.get_manager(inst)
if not manager.alive:
    return [TextContent(type="text", text=f"Error: {inst} is not running.")]
manager.stop()
```

- **前置检查**: 未运行则返回错误
- **功能**: 通过 `ProcessManager` 停止实例子进程

#### `get_screenshot` (L293-L320)

```python
config = AzurLaneConfig(inst)
device = Device(config)
image = device.screenshot()
image_pil = Image.fromarray(image)
buffered = BytesIO()
image_pil.save(buffered, format="JPEG")
img_data = base64.b64encode(buffered.getvalue()).decode("utf-8")
return [ImageContent(type="image", data=img_data, mimeType="image/jpeg")]
```

- **功能**: 截取模拟器屏幕并返回 Base64 编码的 JPEG 图像
- **流程**: ADB 截图 -> numpy 数组 -> PIL Image -> JPEG Bytes -> Base64
- **环境变量**: 设置 `ALAS_CONFIG_NAME` 用于设备连接
- **特殊处理**: `remove_fake_pil_module()` 清理 PIL 模块伪装
- **错误处理**: 捕获异常返回错误文本（含堆栈跟踪）
- **性能**: 每次调用创建新的 Device 实例（无缓存）

#### `get_current_running_task` (L322-L351)

```python
manager = ProcessManager.get_manager(inst)
if not manager.alive:
    return [TextContent(type="text", text="Error: Instance is not running.")]
# 从日志文件解析当前任务
for line in reversed(lines):
    m = re.search(r"调度器: 开始任务\s*[`'\" ](.*?)[`'\" ]", line)
    if not m:
        m = re.search(r"<<<\s*Run task\s*(.*?)\s*>>>", line)
    if m:
        task = m.group(1)
        break
```

- **功能**: 从日志文件中解析当前正在执行的任务
- **正则匹配**: 支持两种日志格式：
  - 现代格式: `调度器: 开始任务 \`TaskName\``
  - 旧版格式: `<<< Run task TaskName >>>`
- **回退**: 匹配失败返回 `"Unknown"`

#### `get_scheduler_queue` (L353-L365)

```python
config = AzurLaneConfig(inst)
queue_data = []
for task_name in config.data:
    if task_name in ["Alas", "Error", "MUMU", "MumuPlayer12", "EmulatorManagement", "Dashboard"]:
        continue
    scheduler = config.data.get(task_name, {}).get("Scheduler", {})
    if scheduler.get("Enable", False):
        next_run = scheduler.get("NextRun", "2050-01-01 00:00:00")
        queue_data.append({"task": task_name, "next_run": str(next_run)})
queue_data.sort(key=lambda x: str(x["next_run"]))
```

- **功能**: 获取已启用任务的执行队列
- **过滤**: 跳过系统任务（Alas, Error, MUMU 等）
- **排序**: 按 `NextRun` 时间升序
- **返回**: `[{task, next_run}, ...]`

#### `trigger_task` (L367-L375)

```python
config = AzurLaneConfig(inst)
config.cross_set(f"{task}.Scheduler.Enable", True)
now = datetime.datetime.now()
config.cross_set(f"{task}.Scheduler.NextRun", str(now))
config.save()
```

- **功能**: 强制将指定任务加入队列并立即执行
- **实现**: 启用任务调度器 + 设置 NextRun 为当前时间

#### `clear_scheduler_queue` (L377-L388)

```python
config = AzurLaneConfig(inst)
cleared = []
for task_name in config.data:
    scheduler = config.data.get(task_name, {}).get("Scheduler", {})
    if scheduler.get("Enable", False):
        config.cross_set(f"{task_name}.Scheduler.Enable", False)
        cleared.append(task_name)
if cleared:
    config.save()
```

- **功能**: 清空所有已启用任务的队列
- **实现**: 遍历所有任务，禁用 Scheduler.Enable
- **返回**: 被清除的任务列表

#### `restart_emulator` (L390-L409)

```python
config = AzurLaneConfig(inst)
device = Device(config)
device.emulator_stop()
time.sleep(60)
device.emulator_start()
```

- **功能**: 重启模拟器
- **流程**: 停止 -> 等待 60 秒 -> 启动
- **注意**: 使用 `time.sleep(60)` 阻塞当前线程（在 async 函数中调用同步阻塞操作）
- **性能问题**: 60 秒阻塞可能影响 MCP 服务器响应其他请求

#### `restart_adb` (L411-L437)

```python
adb_path = State.deploy_config.AdbExecutable
# ... 搜索 ADB 路径 ...
subprocess.run([adb_path, "kill-server"], check=False)
subprocess.run([adb_path, "start-server"], check=False)
```

- **功能**: 重启 ADB 服务
- **ADB 路径搜索顺序**: deploy.yaml 配置 -> `.venv/Scripts/adb.exe` -> `.venv/bin/adb` -> `./bin/adb/adb.exe` -> `adb` (PATH)
- **实现**: kill-server + start-server

#### `update_alas` (L439-L447)

```python
from module.webui.updater import updater
def do_update():
    updater.update()
threading.Thread(target=do_update).start()
```

- **功能**: 在后台线程中触发 AzurPilot 更新
- **实现**: 启动独立线程执行 `updater.update()`
- **返回**: 立即返回成功消息（不等待更新完成）

### 4.2 错误处理 (L452-L454)

```python
except Exception as e:
    logger.exception(f"Tool {name} error")
    return [TextContent(type="text", text=f"Error: {str(e)}")]
```

所有工具调用的外层错误处理，记录异常日志并返回错误文本。

---

## 5. SSE 传输层 (L456-L503)

### 5.1 SSE 传输初始化 (L457)

```python
transport = SseServerTransport("/mcp/messages")
```

创建 SSE 传输实例，消息端点路径为 `/mcp/messages`。

### 5.2 `mcp_asgi_app` ASGI 应用 (L459-L503)

```python
async def mcp_asgi_app(scope, receive, send):
```

**纯 ASGI 应用，处理 MCP 协议的 HTTP 请求路由。**

- **参数**: 标准 ASGI 接口 (`scope`, `receive`, `send`)
- **路由逻辑**:

| 路径匹配 | 处理 | 说明 |
|---|---|---|
| `path.endswith("/sse")` | `transport.connect_sse()` | 建立 SSE 连接，运行 MCP 服务器循环 |
| `path.endswith("/messages")` 或 `path.endswith("/messages/")` | `transport.handle_post_message()` | 处理客户端 POST 消息 |
| 其他 | 返回 404 | 未匹配的路径 |

**SSE 连接流程** (L472-L479):

```python
async with transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
    options = mcp_server.create_initialization_options()
    await mcp_server.run(read_stream, write_stream, options)
```

1. 建立 SSE 连接，获取读写流
2. 创建 MCP 初始化选项
3. 运行 MCP 服务器循环（阻塞直到连接关闭）

**错误处理** (L487-L491):

```python
if "BrokenResourceError" in str(type(e)) or "BrokenPipeError" in str(e)):
    logger.warning("MCP client disconnected during POST message.")
else:
    logger.error(f"Error handling MCP message: {e}", exc_info=True)
```

区分客户端断开连接（警告）和其他错误（记录完整堆栈）。

**日志**: 记录所有传入的 HTTP 请求（方法 + 路径）。

---

## 6. Starlette 应用包装 (L505-L511)

```python
app = Starlette(
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    ]
)
app.mount("/", mcp_asgi_app)
```

- **CORS 配置**: 完全开放（`allow_origins=["*"]`），允许所有来源、方法和头部
- **路由**: 根路径 `/` 挂载 MCP ASGI 应用
- **用途**: 可被 `gui.py` 中的 uvicorn 通过 `app.mount("/mcp", mcp_app)` 挂载到主 WebUI 应用

---

## 7. `__main__` 入口 (L513-L516)

```python
if __name__ == "__main__":
    import uvicorn
    logger.info("启动 ALAS MCP 服务 (Port: 22268)")
    uvicorn.run(app, host="0.0.0.0", port=22268)
```

- **独立运行模式**: 直接在端口 22268 启动 MCP 服务器
- **与 gui.py 的关系**: 可独立运行，也可被 gui.py 挂载到 `/mcp` 路径下

---

## 8. 数据结构分析

### 8.1 MCP Tool 结构

```python
Tool(
    name="tool_name",           # 工具名称
    description="描述",          # 工具描述
    inputSchema={               # JSON Schema
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "参数描述"}
        },
        "required": ["param"]
    }
)
```

### 8.2 MCP 响应结构

```python
# 文本响应
TextContent(type="text", text="响应内容")

# 图像响应
ImageContent(type="image", data="base64编码数据", mimeType="image/jpeg")
```

### 8.3 工具返回数据结构示例

```python
# list_instances
["alas", "alas2"]

# get_status
[{"instance": "alas", "running": true, "state": 2}]

# get_task_help
{
    "task_name": "Research",
    "display_name": "科研",
    "help": "...",
    "groups": {
        "Scheduler": {
            "display_name": "调度器",
            "help": "...",
            "arguments": {
                "Enable": {
                    "display_name": "启用",
                    "help": "...",
                    "type": "toggle",
                    "default": true,
                    "options": null
                }
            }
        }
    }
}

# get_scheduler_queue
[{"task": "Commission", "next_run": "2025-01-01 00:00:00"}, ...]
```

---

## 9. 模块内部调用关系

```
mcp_server_sse.py
  │
  ├── MCP Server (mcp.server.Server)
  │   ├── list_tools() -> List[Tool]          # 工具注册
  │   └── call_tool() -> List[TextContent]    # 工具调用分发
  │
  ├── SseServerTransport
  │   ├── connect_sse() -> (read_stream, write_stream)
  │   └── handle_post_message()
  │
  ├── McpConfigHelper (module.config.mcp_helper)
  │   ├── get_tasks() -> List[str]
  │   ├── get_task_details(task_name) -> Dict
  │   └── get_dashboard_resources(config_data) -> Dict
  │
  ├── AzurLaneConfig (module.config.config)
  │   ├── data: Dict                          # 原始配置数据
  │   ├── cross_set(path, value)              # 设置配置值
  │   └── save()                              # 保存到磁盘
  │
  ├── ProcessManager (module.webui.process_manager)
  │   ├── get_manager(inst) -> ProcessManager
  │   ├── alive: bool
  │   ├── state: int
  │   ├── start(func)
  │   └── stop()
  │
  ├── Device (module.device.device)           # 惰性加载
  │   ├── screenshot() -> numpy.ndarray
  │   ├── emulator_stop()
  │   └── emulator_start()
  │
  ├── State (module.webui.setting)
  │   └── deploy_config.AdbExecutable
  │
  └── Starlette + CORSMiddleware
      └── mcp_asgi_app (ASGI)
```

---

## 10. 设计模式与架构分析

### 10.1 设计模式

| 模式 | 应用位置 | 说明 |
|---|---|---|
| **注册模式** | `@mcp_server.list_tools()` | 装饰器注册工具列表 |
| **分发模式** | `call_tool()` 中的 `if/elif` 链 | 根据工具名分发到处理逻辑 |
| **传输抽象** | `SseServerTransport` | SSE 传输层抽象 |
| **ASGI 组合** | `app.mount("/", mcp_asgi_app)` | Starlette 应用组合 |
| **惰性加载** | `Device` 和 `remove_fake_pil_module` | 按需导入重模块 |

### 10.2 架构风格

- **MCP 协议**: 基于 JSON-RPC 的工具调用协议，通过 SSE 传输
- **双模式运行**: 可独立运行（端口 22268）或被 gui.py 挂载（`/mcp` 路径）
- **无状态设计**: 每次工具调用独立，不维护客户端会话状态（SSE 连接除外）
- **异步优先**: 所有工具处理器都是 `async` 函数

---

## 11. 性能分析

### 11.1 性能瓶颈

| 位置 | 瓶颈 | 原因 | 影响 |
|---|---|---|---|
| `get_screenshot` | ~500ms+ | ADB 截图 + 图像编码 | 每次调用创建新 Device |
| `restart_emulator` | 60 秒 | `time.sleep(60)` 阻塞 | 阻塞事件循环 |
| `get_recent_logs` | 文件 I/O | 读取整个日志文件 | 大文件性能差 |
| `get_current_running_task` | 文件 I/O | 读取整个日志文件 + 正则匹配 | 大文件性能差 |
| `update_alas` | 后台线程 | Git 操作 | 不阻塞但资源竞争 |

### 11.2 优化建议

| 问题 | 建议 |
|---|---|
| `get_screenshot` 每次创建 Device | 缓存 Device 实例或使用连接池 |
| `restart_emulator` 阻塞 60 秒 | 使用 `asyncio.sleep()` 替代 `time.sleep()` |
| `get_recent_logs` 读取整个文件 | 使用文件尾部读取（`tail` 逻辑） |
| `call_tool` 中的 `if/elif` 链 | 使用字典映射分发 |

### 11.3 并发考虑

- **SSE 连接**: 每个客户端一个长连接，`mcp_server.run()` 阻塞直到连接关闭
- **工具调用**: MCP 协议保证同一连接上的请求顺序处理
- **阻塞操作**: `restart_emulator` 的 60 秒 `time.sleep()` 会阻塞当前 SSE 连接的消息处理

---

## 12. 安全性分析

### 12.1 已实现的安全措施

| 措施 | 位置 | 说明 |
|---|---|---|
| CORS 中间件 | L506-L510 | 配置跨域访问策略 |
| 异常信息截断 | L454 | 返回 `str(e)` 而非完整堆栈 |
| 日志记录 | L453 | `logger.exception()` 记录完整异常 |
| 错误隔离 | L452-L454 | 工具调用异常不影响服务器运行 |

### 12.2 潜在安全风险

| 风险 | 位置 | 严重程度 | 说明 |
|---|---|---|---|
| CORS 完全开放 | L509 | **高** | `allow_origins=["*"]` 允许任何来源访问 |
| 无认证机制 | 全局 | **高** | 无 API 密钥、Token 或密码验证 |
| `update_config` 可修改任意配置 | L238-L248 | **高** | 可修改密码、服务器等敏感配置 |
| `start_instance` / `stop_instance` | L276-L292 | **中** | 可远程启停进程 |
| `restart_emulator` | L390-L409 | **中** | 可远程重启模拟器 |
| `update_alas` | L439-L447 | **中** | 可触发代码更新 |
| `restart_adb` 子进程执行 | L433-L434 | **低** | `subprocess.run()` 但参数受控 |
| 环境变量注入 | L295-L296 | **低** | 设置 `ALAS_CONFIG_NAME` 环境变量 |

### 12.3 安全建议

1. **添加认证**: 实现 API 密钥或 Token 验证
2. **限制 CORS**: 配置具体的允许来源
3. **操作审计**: 记录所有配置修改和敏感操作
4. **权限控制**: 区分只读和读写操作
5. **输入验证**: 验证 `instance` 和 `task` 参数的有效性

---

## 13. 代码质量评估

### 13.1 优点

1. **MCP 协议标准实现**: 遵循 MCP 规范，工具定义清晰
2. **完整的工具集**: 18 个工具覆盖实例管理、配置、监控、截图等
3. **错误隔离**: 工具调用异常不影响服务器运行
4. **双模式运行**: 支持独立运行和挂载模式
5. **类型注解**: 使用 `typing` 模块提供类型信息
6. **日志完善**: 请求和错误都有日志记录

### 13.2 问题与不足

1. **`call_tool()` 函数过长** (250+ 行): 所有工具逻辑集中在一个函数中
2. **`if/elif` 分发链**: 不利于扩展，应使用注册表模式
3. **同步阻塞操作**: `restart_emulator` 中的 `time.sleep(60)` 在 async 函数中
4. **重复的实例化模式**: 多个工具重复 `AzurLaneConfig(inst)` + `Device(config)` 模式
5. **日志系统不一致**: 使用标准库 `logging` 而非项目的 `module.logger`
6. **`cv2` 导入未使用**: L21 导入了 `cv2` 但未直接使用
7. **注释混合语言**: 中英文注释混合

---

## 14. 潜在问题与改进建议

### 14.1 潜在 Bug

1. **`restart_emulator` 阻塞事件循环**: `time.sleep(60)` 会阻塞整个 SSE 连接的消息处理
2. **`get_screenshot` 环境变量泄漏**: 设置 `ALAS_CONFIG_NAME` 环境变量可能影响其他调用
3. **`get_recent_logs` 文件锁定**: 在 Windows 上可能与其他进程的日志写入冲突
4. **`update_config` 无验证**: 不验证配置路径和值的有效性

### 14.2 改进建议

1. **提取工具处理器**:
   ```python
   class ToolHandler:
       async def list_instances(self) -> List[TextContent]: ...
       async def get_status(self) -> List[TextContent]: ...
       # ...
   ```

2. **使用注册表模式**:
   ```python
   tool_handlers: Dict[str, Callable] = {
       "list_instances": handler.list_instances,
       "get_status": handler.get_status,
       # ...
   }
   ```

3. **异步化阻塞操作**:
   ```python
   async def restart_emulator(self, inst):
       # ...
       await asyncio.sleep(60)  # 替代 time.sleep(60)
       # ...
   ```

4. **缓存 Device 实例**:
   ```python
   _device_cache: Dict[str, Device] = {}
   def get_device(inst: str) -> Device:
       if inst not in _device_cache:
           _device_cache[inst] = Device(AzurLaneConfig(inst))
       return _device_cache[inst]
   ```

5. **添加输入验证**:
   ```python
   def validate_instance(inst: str) -> bool:
       return inst in alas_instance()
   ```

6. **统一日志系统**: 使用项目的 `module.logger` 替代标准库 `logging`

7. **移除未使用的导入**: 删除 `import cv2`

8. **添加 API 认证**: 实现基于 Token 的认证机制
