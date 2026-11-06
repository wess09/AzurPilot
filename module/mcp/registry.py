"""AzurPilot MCP 工具的单一注册表与兼容名称映射。

默认端点只暴露 ``azurpilot_`` 工具；旧名称仅在显式创建的兼容应用中登记。
"""
from dataclasses import dataclass
from typing import Any

from mcp.types import Tool, ToolAnnotations

from module.mcp.device_contract import KEYCODES, MAX_COORDINATE, MAX_SHELL_ARGUMENTS


INSTANCE = {"type": "string", "minLength": 1, "maxLength": 64}
TASK = {"type": "string", "minLength": 1, "maxLength": 80}
REVISION = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
REQUEST_ID = {"type": "string", "minLength": 1, "maxLength": 128,
              "pattern": r"^[A-Za-z0-9_.:-]+$"}
LEASE_ID = {"type": "string", "pattern": r"^[0-9a-f]{32}$"}
FRAME_ID = {"type": "string", "pattern": r"^[0-9a-f]{32}$"}
COORDINATE = {"type": "integer", "minimum": 0, "maximum": MAX_COORDINATE}
# 坐标操作共用同一套观测帧语义：可携带 frame_id，尺寸或方向变化即拒绝执行。
FRAME_REFERENCE = {"type": "string", "pattern": r"^[0-9a-f]{32}$",
                   "description": "可选，azurpilot_observe_device 返回的 frame_id；"
                                  "用于确认坐标仍属于当前画面"}
VERIFY = {"type": "boolean", "default": True,
          "description": "动作后是否再采集一帧并比对画面变化，默认 true"}
# 配置值可以是任意 JSON 类型。这里不用布尔 Schema（true/false），因为部分 MCP
# 客户端的 tools/list 校验器要求 properties 下的每一项都是对象形式的 Schema。
ANY_JSON = {"type": ["string", "number", "boolean", "object", "array", "null"]}
NEXT_STEP = {
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["tool", "reason"],
    "additionalProperties": False,
}


def object_schema(properties=None, required=()):
    """生成拒绝未知字段的对象 Schema。"""
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": False,
    }


def input_schema(properties=None, required=()):
    return object_schema(properties, required)


ERROR_SCHEMA = object_schema({
    "code": {"type": "string"},
    "message": {"type": "string"},
    "retryable": {"type": "boolean"},
    "outcome_certain": {"type": "boolean"},
    "details": ANY_JSON,
}, ["code", "message", "retryable", "outcome_certain"])

# MCP 只有一份 outputSchema，客户端会用它同时校验成功与 isError=true 的
# structuredContent。失败信封若不含在声明里，客户端会以 -32602 拒绝整个响应，
# AI 反而拿不到错误码和下一步建议。
COMMON_OUTPUT = {
    "error": ERROR_SCHEMA,
    "next_step": NEXT_STEP,
    "operation_id": {"type": "string", "minLength": 32, "maxLength": 32},
    "deduplicated": {"type": "boolean"},
}


def output_schema(properties, pending=False):
    """声明成功、pending 与失败三类返回形状，供客户端校验结构化内容。"""
    pending = pending or "operation_id" in properties
    statuses = ["success", "pending", "failed"] if pending else ["success", "failed"]
    return object_schema({
        "status": {"type": "string", "enum": statuses},
        **COMMON_OUTPUT, **properties,
    }, ["status"])


def write_properties(properties, pending=False):
    return {
        "operation_id": {"type": "string", "minLength": 32, "maxLength": 32},
        "deduplicated": {"type": "boolean"},
        "next_step": NEXT_STEP,
        **properties,
    }


def control_properties(extra=None):
    """设备控制类工具的统一返回：命令已下发、画面已变化、任务已完成分开表达。"""
    return {
        "instance": INSTANCE,
        "lease_id": LEASE_ID,
        "command_dispatched": {
            "type": "boolean",
            "description": "输入命令已被设备接受，不代表界面已响应或任务已完成",
        },
        "frame_changed": {
            "type": ["boolean", "null"],
            "description": "动作前后画面是否变化；null 表示本次未验证",
        },
        "frame_difference": {
            "type": ["number", "null"],
            "description": "动作前后 32×32 灰度平均差，范围 0-255",
        },
        "frame_id": {
            "type": ["string", "null"],
            "description": "动作后采集的观测帧，可作为下一步坐标操作的 frame_id",
        },
        "observation_verified": {
            "type": "boolean",
            "description": "操作前是否用 frame_id 校验过画面尺寸与方向",
        },
        "detail": {"type": "object", "description": "本次动作的实际参数与后端"},
        **(extra or {}),
    }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: str
    description: str
    input: dict[str, Any]
    output: dict[str, Any]
    readonly: bool = False
    destructive: bool = False
    idempotent: bool = False
    mutating: bool = False
    device_operation: str | None = None
    long_running: bool = False

    def as_tool(self, *, name=None, schema=None, description=None) -> Tool:
        return Tool(
            name=name or self.name,
            description=description or self.description,
            inputSchema=schema or self.input,
            outputSchema=self.output,
            annotations=ToolAnnotations(
                readOnlyHint=self.readonly,
                destructiveHint=self.destructive,
                idempotentHint=self.idempotent,
                openWorldHint=False,
            ),
        )


@dataclass(frozen=True)
class LegacySpec:
    name: str
    target: str
    input: dict[str, Any]
    transform: str = "identity"


TOOL_REGISTRY = (
    ToolSpec(
        "azurpilot_list_instances", "list_instances",
        "管理端只读入口。需要选择实例或确认影响范围时使用；返回各实例的进程状态和当前任务，"
        "不代表具体设备可用。随后可对目标实例调用 azurpilot_get_context。",
        input_schema(),
        output_schema({
            "instances": {"type": "array", "items": object_schema({
                "name": INSTANCE,
                "status": {"type": "string", "enum": ["running", "stopped", "error", "updating"]},
                "current_task": {"type": ["string", "null"]},
            }, ["name", "status", "current_task"])},
        }),
        readonly=True, idempotent=True,
    ),
    ToolSpec(
        "azurpilot_get_context", "get_context",
        "了解单个实例时优先使用。一次返回运行状态、当前任务、计划摘要、资源、最近错误和设备能力；"
        "不含截图与完整日志。排障后再次调用可确认状态变化。",
        input_schema({"instance": INSTANCE}, ["instance"]),
        output_schema({
            "instance": INSTANCE,
            "revision": REVISION,
            "instance_status": {"type": "string", "enum": ["running", "stopped", "error", "updating"]},
            "current_task": {"type": ["string", "null"]},
            "schedule": {"type": "array", "items": {"type": "object"}},
            "resources": {"type": "object"},
            "recent_error": {"type": ["object", "null"]},
            "device": {"type": "object"},
        }),
        readonly=True, idempotent=True,
    ),
    ToolSpec(
        "azurpilot_search_tasks", "search_tasks",
        "不知道任务标识时按关键词搜索，只返回少量任务摘要。匹配任务标识、中文显示名、"
        "参数组与参数/选项文案，常见口语词（如「日常」「委托」「倒油」）会映射到配置用词。"
        "找到任务后再调用 azurpilot_get_task_schema 读取参数，避免一次载入完整配置树。",
        input_schema({
            "query": {"type": "string", "maxLength": 100, "default": ""},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        }),
        output_schema({
            "query": {"type": "string"},
            "tasks": {"type": "array", "items": object_schema({
                "task": TASK, "display_name": {"type": "string"}, "description": {"type": "string"},
            }, ["task", "display_name", "description"])},
            "truncated": {"type": "boolean"},
        }),
        readonly=True, idempotent=True,
    ),
    ToolSpec(
        "azurpilot_get_task_schema", "get_task_schema",
        "修改任务配置前使用，返回参数路径、类型、默认值、可选值、可写性和说明。"
        "不存在的任务返回 NOT_FOUND；随后用 azurpilot_get_config 获取实际值与 revision。",
        input_schema({"task": TASK}, ["task"]),
        output_schema({
            "task_name": TASK,
            "display_name": {"type": "string"},
            "help": {"type": "string"},
            "groups": {"type": "object"},
        }),
        readonly=True, idempotent=True,
    ),
    ToolSpec(
        "azurpilot_get_config", "get_config",
        "读取整个实例、一个任务或 Task.Group.Argument 路径的实际配置，并返回写操作所需的 revision。"
        "task 与 path 不能同时提供；读取不会修改配置。",
        input_schema({
            "instance": INSTANCE,
            "task": TASK,
            "path": {"type": "string", "minLength": 1, "maxLength": 180,
                     "pattern": r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){0,2}$"},
        }, ["instance"]),
        output_schema({
            "instance": INSTANCE, "revision": REVISION,
            "path": {"type": ["string", "null"]}, "values": ANY_JSON,
        }),
        readonly=True, idempotent=True,
    ),
    ToolSpec(
        "azurpilot_patch_config", "patch_config",
        "原子修改一个或多个配置字段。必须先从 get_config 取得 revision；changes 使用完整路径。"
        "dry_run=true 只校验并返回前后值，不写盘。成功仅表示配置已提交，可用返回的 revision 和新值确认。"
        "重试时携带相同 request_id，避免超时后重复写入。",
        input_schema({
            "instance": INSTANCE,
            "revision": REVISION,
            "changes": {"type": "array", "minItems": 1, "maxItems": 200, "items": object_schema({
                "path": {"type": "string", "minLength": 1, "maxLength": 180},
                "value": ANY_JSON,
            }, ["path", "value"])},
            "dry_run": {"type": "boolean", "default": False},
            "request_id": REQUEST_ID,
        }, ["instance", "revision", "changes"]),
        output_schema(write_properties({
            "instance": INSTANCE, "revision": REVISION, "dry_run": {"type": "boolean"},
            "changes": {"type": "array", "items": object_schema({
                "path": {"type": "string"}, "before": ANY_JSON, "after": ANY_JSON,
            }, ["path", "before", "after"])},
        })),
        destructive=True, idempotent=True, mutating=True,
    ),
    ToolSpec(
        "azurpilot_set_task_schedule", "set_task_schedule",
        "设置指定任务的启用状态和下次执行时间（YYYY-MM-DD HH:mm:ss，实例本地时间），至少提供一项。"
        "返回 scheduled 只表示配置已进入计划，running 表示调用时是否正在执行；均不代表任务已完成。"
        "重试时携带相同 request_id。",
        {
            **input_schema({
                "instance": INSTANCE, "task": TASK,
                "enabled": {"type": "boolean"},
                "next_run": {"type": "string",
                             "pattern": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"},
                "request_id": REQUEST_ID,
            }, ["instance", "task"]),
            "anyOf": [
                {"type": "object", "required": ["enabled"]},
                {"type": "object", "required": ["next_run"]},
            ],
        },
        output_schema(write_properties({
            "instance": INSTANCE, "task": TASK, "enabled": {"type": "boolean"},
            "next_run": {"type": "string"}, "scheduled": {"type": "boolean"},
            "running": {"type": "boolean"}, "revision": REVISION,
        })),
        destructive=True, idempotent=True, mutating=True,
    ),
    ToolSpec(
        "azurpilot_get_logs", "get_logs",
        "按游标读取有限数量的运行日志，可用级别和关键词过滤。首次 after=0；续读传上次 next_cursor。"
        "reset=true 表示旧游标已失效，返回的是重置后的日志。完整历史请使用 WebUI 日志。",
        input_schema({
            "instance": INSTANCE,
            "after": {"type": "integer", "minimum": 0, "default": 0},
            "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
            "keyword": {"type": "string", "maxLength": 200},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
        }, ["instance"]),
        output_schema({
            "instance": INSTANCE, "next_cursor": {"type": "integer", "minimum": 0},
            "reset": {"type": "boolean"}, "has_more": {"type": "boolean"},
            "entries": {"type": "array", "items": object_schema({
                "id": {"type": "integer", "minimum": 1},
                "level": {"type": "string"}, "text": {"type": "string"},
            }, ["id", "level", "text"])},
        }),
        readonly=True, idempotent=True,
    ),
    ToolSpec(
        "azurpilot_observe_device", "observe_device",
        "需要查看设备画面时主动采集一张截图，返回帧标识、尺寸、方向、采集时间、缓存标记和后端。"
        "截图只证明采集成功，不证明任何后续操作或任务完成。"
        "返回的 frame_id 是坐标操作的唯一参照：把它传给 click/swipe/long_press，"
        "服务端会在尺寸或方向变化时拒绝继续使用失效观测。",
        input_schema({"instance": INSTANCE}, ["instance"]),
        output_schema({
            "instance": INSTANCE, "frame_id": {"type": "string"},
            "width": {"type": "integer", "minimum": 1}, "height": {"type": "integer", "minimum": 1},
            "orientation": {"type": "string", "enum": ["portrait", "landscape"]},
            "captured_at": {"type": "string"}, "cached": {"type": "boolean"},
            "backend": {"type": "string"}, "mime_type": {"type": "string", "enum": ["image/jpeg"]},
        }),
        readonly=True, idempotent=True, device_operation="get_screenshot",
    ),
    ToolSpec(
        "azurpilot_acquire_device_control", "acquire_device_control",
        "接管设备前必须先调用。要求该实例的调度器已停止，成功返回 lease_id，后续所有输入类工具都要带上它。"
        "重复调用会续期并返回同一个 lease_id（already_held=true），不会产生两个租约。"
        "实例仍在运行时返回 DEVICE_IN_USE，请先用 azurpilot_stop_instance 停止。",
        input_schema({
            "instance": INSTANCE,
            "ttl_seconds": {"type": "integer", "minimum": 60, "maximum": 7200, "default": 1800},
        }, ["instance"]),
        output_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID,
            "ttl_seconds": {"type": "integer"}, "expires_at": {"type": "string"},
            "already_held": {"type": "boolean"},
            "instance_status": {"type": "string",
                                "enum": ["running", "stopped", "error", "updating"]},
        }),
        idempotent=True,
    ),
    ToolSpec(
        "azurpilot_click", "click",
        "在已接管设备上点击一个坐标。前置条件：持有 azurpilot_acquire_device_control 的 lease_id，"
        "并用 azurpilot_observe_device 取得 frame_id；坐标是观测帧的像素坐标（左上角原点）。"
        "返回 command_dispatched 只表示命令已下发，frame_changed 只表示画面有变化，"
        "都不代表目标任务完成——需要确认结果请再调用 observe_device 或 get_context。",
        input_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID,
            "x": COORDINATE, "y": COORDINATE,
            "frame_id": FRAME_REFERENCE, "verify": VERIFY,
        }, ["instance", "lease_id", "x", "y"]),
        output_schema(control_properties()),
        idempotent=False, device_operation="click",
    ),
    ToolSpec(
        "azurpilot_swipe", "swipe",
        "在已接管设备上从 (x1,y1) 滑动到 (x2,y2)，坐标为观测帧像素坐标，距离小于 10px 会被拒绝。"
        "前置条件与返回语义同 azurpilot_click：命令下发、画面变化、任务完成是三件事。",
        input_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID,
            "x1": COORDINATE, "y1": COORDINATE, "x2": COORDINATE, "y2": COORDINATE,
            "duration_ms": {"type": "integer", "minimum": 100, "maximum": 5000, "default": 300},
            "frame_id": FRAME_REFERENCE, "verify": VERIFY,
        }, ["instance", "lease_id", "x1", "y1", "x2", "y2"]),
        output_schema(control_properties()),
        idempotent=False, device_operation="swipe",
    ),
    ToolSpec(
        "azurpilot_long_press", "long_press",
        "在已接管设备上长按一个坐标，默认 1000 毫秒。前置条件与返回语义同 azurpilot_click。",
        input_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID,
            "x": COORDINATE, "y": COORDINATE,
            "duration_ms": {"type": "integer", "minimum": 200, "maximum": 10000, "default": 1000},
            "frame_id": FRAME_REFERENCE, "verify": VERIFY,
        }, ["instance", "lease_id", "x", "y"]),
        output_schema(control_properties()),
        idempotent=False, device_operation="long_press",
    ),
    ToolSpec(
        "azurpilot_input_text", "input_text",
        "向已接管设备的当前输入框输入文本，只支持 ASCII 字母、数字、空格与 ., _ : / @ + - =；"
        "不发送回车或确认键，需要时再用 azurpilot_press_key。中文等输入法文本不受支持。",
        input_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID,
            "text": {"type": "string", "minLength": 1, "maxLength": 200,
                     "pattern": r"^[A-Za-z0-9 .,_:/@+\-=]+$"},
            "frame_id": FRAME_REFERENCE, "verify": VERIFY,
        }, ["instance", "lease_id", "text"]),
        output_schema(control_properties()),
        idempotent=False, device_operation="input_text",
    ),
    ToolSpec(
        "azurpilot_press_key", "press_key",
        "向已接管设备发送一个明确的 Android 按键（HOME、BACK、ENTER、APP_SWITCH 等），"
        "不接受任意数字键码。前置条件与返回语义同 azurpilot_click。",
        input_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID,
            "key": {"type": "string", "enum": sorted(KEYCODES)},
            "frame_id": FRAME_REFERENCE, "verify": VERIFY,
        }, ["instance", "lease_id", "key"]),
        output_schema(control_properties()),
        idempotent=False, device_operation="press_key",
    ),
    ToolSpec(
        "azurpilot_adb_shell", "adb_shell",
        "在已接管设备上执行受限只读诊断命令（dumpsys / getprop / wm size|density / pm list|path），"
        "参数以数组传入而不是整条 shell 字符串，白名单外的命令返回 ADB_SHELL_DENIED。"
        "返回原始输出片段，用于确认为何点击没有生效，不修改设备状态。",
        input_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID,
            "argv": {"type": "array", "minItems": 1, "maxItems": MAX_SHELL_ARGUMENTS,
                     "items": {"type": "string", "minLength": 1, "maxLength": 64,
                               "pattern": r"^[A-Za-z0-9_.:/-]+$"}},
            "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 20000, "default": 10000},
        }, ["instance", "lease_id", "argv"]),
        output_schema(control_properties({
            "output": {"type": "string"},
            "truncated": {"type": "boolean"},
        })),
        readonly=True, idempotent=True, device_operation="adb_shell",
    ),
    ToolSpec(
        "azurpilot_release_device_control", "release_device_control",
        "结束设备接管并释放租约，必须提供 acquire 时返回的 lease_id。释放后输入类工具立即失效；"
        "需要恢复自动挂机时再调用 azurpilot_start_instance。",
        input_schema({"instance": INSTANCE, "lease_id": LEASE_ID}, ["instance", "lease_id"]),
        output_schema({
            "instance": INSTANCE, "lease_id": LEASE_ID, "released": {"type": "boolean"},
        }),
        idempotent=True,
    ),
    ToolSpec(
        "azurpilot_get_operation", "get_operation",
        "查询调度、配置写入、重启或更新操作的当前状态与已确定结果。超时或 pending 后优先调用本工具，"
        "不要直接重放写操作；未知 operation_id 返回 NOT_FOUND。",
        input_schema({"operation_id": {"type": "string", "minLength": 32, "maxLength": 32,
                                       "pattern": r"^[0-9a-f]{32}$"}}, ["operation_id"]),
        output_schema({"operation": {"type": "object"}}),
        readonly=True, idempotent=True,
    ),
    ToolSpec(
        "azurpilot_start_instance", "start_instance",
        "启动指定实例的 alas 调度进程。前置条件是实例存在且未运行；成功表示进程已启动，"
        "不表示游戏任务已完成。可用 get_context 确认运行状态。重试时携带 request_id。",
        input_schema({"instance": INSTANCE, "request_id": REQUEST_ID}, ["instance"]),
        output_schema(write_properties({
            "instance": INSTANCE, "instance_status": {"type": "string"},
            "current_task": {"type": ["string", "null"]},
        })),
        destructive=False, idempotent=True, mutating=True,
    ),
    ToolSpec(
        "azurpilot_stop_instance", "stop_instance",
        "停止指定实例的工作进程，会中断该实例正在执行的任务，不影响其他实例。"
        "成功表示全部相关工作进程已确认停止；可用 get_context 复核。重试时携带 request_id。",
        input_schema({"instance": INSTANCE, "request_id": REQUEST_ID}, ["instance"]),
        output_schema(write_properties({
            "instance": INSTANCE, "instance_status": {"type": "string"},
            "current_task": {"type": ["string", "null"]},
        })),
        destructive=True, idempotent=True, mutating=True,
    ),
    ToolSpec(
        "azurpilot_restart_emulator", "restart_emulator",
        "重启指定实例绑定的模拟器，会中断该设备上的游戏与连接，不重启全局 ADB。"
        "成功仅表示重启流程执行完毕；设备是否可交互须再调用 observe_device。"
        "超时或重试使用同一 request_id，并通过 get_operation 查询。",
        input_schema({"instance": INSTANCE, "request_id": REQUEST_ID}, ["instance"]),
        output_schema(write_properties({
            "instance": INSTANCE, "restart_executed": {"type": "boolean"},
        }, pending=True)),
        destructive=True, idempotent=True, mutating=True,
        device_operation="restart_emulator", long_running=True,
    ),
    ToolSpec(
        "azurpilot_restart_adb", "restart_adb",
        "重启全局 ADB 服务，会影响此服务连接的多个设备，不只影响可选 instance。"
        "kill-server 会让 127.0.0.1:<port> 这类网络设备掉线，本工具会用各实例配置的串口重新 connect，"
        "并返回当前在线设备列表供确认。已在线且仍有替代连接时可重试。",
        input_schema({"instance": INSTANCE, "request_id": REQUEST_ID}),
        output_schema(write_properties({
            "scope": {"type": "string", "enum": ["global"]},
            "adb_restarted": {"type": "boolean"},
            "adb_path": {"type": "string"},
            "reconnected": {"type": "array", "items": {"type": "string"}},
            "devices": {"type": "array", "items": {"type": "string"}},
        }, pending=True)),
        destructive=True, idempotent=True, mutating=True,
        device_operation="restart_adb", long_running=True,
    ),
    ToolSpec(
        "azurpilot_update_application", "update_application",
        "请求后台执行 AzurPilot Git 拉取、依赖同步与监督重启，影响整个应用和所有实例。"
        "返回 pending/accepted 只表示请求已接受，不表示更新完成；必须用 get_operation 查询终态。"
        "需要 WebUI 监督重启能力。重试时携带相同 request_id。",
        input_schema({"request_id": REQUEST_ID}),
        output_schema(write_properties({
            "accepted": {"type": "boolean"}, "update_completed": {"type": "boolean"},
        }, pending=True)),
        destructive=True, idempotent=True, mutating=True, long_running=True,
    ),
)


LEGACY_REGISTRY = (
    LegacySpec("list_instances", "azurpilot_list_instances", input_schema()),
    LegacySpec("get_status", "azurpilot_list_instances", input_schema()),
    LegacySpec("list_tasks", "azurpilot_search_tasks", input_schema()),
    LegacySpec("get_task_help", "azurpilot_get_task_schema",
               input_schema({"task_name": TASK}, ["task_name"]), "task_help"),
    LegacySpec("get_resources", "azurpilot_get_context", input_schema({"instance": INSTANCE}, ["instance"])),
    LegacySpec("get_current_running_task", "azurpilot_get_context", input_schema({"instance": INSTANCE}, ["instance"])),
    LegacySpec("get_scheduler_queue", "azurpilot_get_context", input_schema({"instance": INSTANCE}, ["instance"])),
    LegacySpec("get_config", "azurpilot_get_config", input_schema({
        "instance": INSTANCE, "task": TASK,
    }, ["instance"])),
    LegacySpec("update_config", "azurpilot_patch_config", input_schema({
        "instance": INSTANCE, "task": TASK, "group": TASK, "arg": TASK, "value": ANY_JSON,
        "request_id": REQUEST_ID,
    }, ["instance", "task", "group", "arg", "value"]), "update_config"),
    LegacySpec("get_recent_logs", "azurpilot_get_logs", input_schema({
        "instance": INSTANCE, "lines": {"type": "integer", "minimum": 1, "maximum": 5000},
    }, ["instance"]), "recent_logs"),
    LegacySpec("trigger_task", "azurpilot_set_task_schedule", input_schema({
        "instance": INSTANCE, "task": TASK, "request_id": REQUEST_ID,
    }, ["instance", "task"]), "trigger_task"),
    LegacySpec("start_instance", "azurpilot_start_instance", input_schema({
        "instance": INSTANCE, "request_id": REQUEST_ID,
    }, ["instance"])),
    LegacySpec("stop_instance", "azurpilot_stop_instance", input_schema({
        "instance": INSTANCE, "request_id": REQUEST_ID,
    }, ["instance"])),
    LegacySpec("get_screenshot", "azurpilot_observe_device", input_schema({
        "instance": INSTANCE,
    }, ["instance"])),
    LegacySpec("restart_emulator", "azurpilot_restart_emulator", input_schema({
        "instance": INSTANCE, "request_id": REQUEST_ID,
    }, ["instance"])),
    LegacySpec("restart_adb", "azurpilot_restart_adb", input_schema({
        "instance": INSTANCE, "request_id": REQUEST_ID,
    })),
    LegacySpec("update_alas", "azurpilot_update_application", input_schema({"request_id": REQUEST_ID})),
    # 批量停用任务仅保留在显式兼容入口，不进入新默认目录。
    LegacySpec("clear_scheduler_queue", "azurpilot_clear_scheduler_queue_legacy", input_schema({
        "instance": INSTANCE,
    }, ["instance"]), "clear_scheduler_queue"),
)


TOOL_BY_NAME = {spec.name: spec for spec in TOOL_REGISTRY}
LEGACY_BY_NAME = {spec.name: spec for spec in LEGACY_REGISTRY}


def resolve(name: str, allow_legacy: bool = False) -> tuple[ToolSpec | None, LegacySpec | None]:
    """解析规范名称；旧名称只在兼容端点启用时解析。"""
    spec = TOOL_BY_NAME.get(name)
    if spec is not None:
        return spec, None
    if not allow_legacy:
        return None, None
    legacy = LEGACY_BY_NAME.get(name)
    if legacy is None:
        return None, None
    if legacy.target.endswith("_legacy"):
        return ToolSpec(
            legacy.target, "clear_scheduler_queue", "兼容入口：批量停用全部可编辑任务。",
            legacy.input, output_schema({"cleared": {"type": "array"}, "retained": {"type": "array"}}),
            destructive=True, idempotent=True, mutating=True,
        ), legacy
    return TOOL_BY_NAME[legacy.target], legacy


def tool_definitions(allow_legacy: bool = False) -> list[Tool]:
    """按注册表固定顺序生成工具目录，兼容名称追加在末尾。"""
    tools = [spec.as_tool() for spec in TOOL_REGISTRY]
    if allow_legacy:
        for legacy in LEGACY_REGISTRY:
            spec, _ = resolve(legacy.name, allow_legacy=True)
            tools.append(spec.as_tool(
                name=legacy.name,
                schema=legacy.input,
                description=f"[已弃用，请改用 {spec.name}] {spec.description}",
            ))
    return tools
