"""将统一 MCP 工具契约适配到配置、运行、设备与更新服务。"""
import copy
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import jsonschema
from mcp.types import CallToolResult, ImageContent, TextContent

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.api.runtime_service import RuntimeService
from module.api.update_service import update_service
from module.config.time_source import now as current_time
from module.mcp.device_contract import CONTROL_OPERATIONS, load_frame
from module.mcp.execution import BoundedCalls, DEVICE_TIMEOUTS, DeviceCleanupError, cleanup_device, run_device
from module.mcp.registry import resolve, tool_definitions
from module.runtime.setting import State


RETRYABLE_ERRORS = {'TOOL_BUSY', 'TOOL_TIMEOUT', 'DEVICE_TIMEOUT', 'UPDATE_BUSY',
                    'STATISTICS_LOADING'}
UNCERTAIN_ERRORS = {'TOOL_TIMEOUT', 'DEVICE_TIMEOUT'}
READ_ONLY_FIELDS = {'storage', 'stored', 'state', 'lock'}
READ_ONLY_DISPLAY = {'hide', 'disabled', 'readonly'}
LEASE_TTL_SECONDS = 1800
DEDUPLICATED_NOTE = '请求去重：复用同一 request_id 的既有操作，未重复执行'
# 口语说法到配置文案的映射，避免 AI 用「日常」这类常用词时搜不到任务。
TASK_SEARCH_ALIASES = {
    '日常': ('每日', 'daily'),
    '日课': ('每日', 'daily'),
    '清日常': ('每日', 'daily'),
    'daily': ('每日',),
    '委托': ('commission', '后勤'),
    '后勤': ('委托', 'commission'),
    'commission': ('委托',),
    '科研': ('research', '研发'),
    '研发': ('科研', 'research'),
    '大世界': ('opsi', '海域'),
    '海域': ('opsi', '大世界'),
    '活动': ('event',),
    '主线': ('main', '战役'),
    '战役': ('main', '主线'),
    '演习': ('exercise',),
    '竞技': ('exercise', '演习'),
    '后宅': ('dorm', '宿舍'),
    '宿舍': ('dorm', '后宅'),
    '大舰队': ('guild',),
    '舰队': ('guild', '大舰队'),
    '指挥喵': ('meowfficer', '猫'),
    '商店': ('shop', '补给'),
    '补给': ('shop', '商店'),
    '倒油': ('低耗',),
    '低耗': ('倒油',),
}


def brief(items, limit=12):
    """把后续调用必需的标识符列进文本摘要，兼容只展示文本的 MCP 客户端。"""
    items = list(items)
    shown = ', '.join(items[:limit])
    if len(items) > limit:
        shown += f' …共 {len(items)} 项'
    return shown


def describe(value, limit=40):
    """把配置值压成单行文本，便于在摘要里展示修改前后对比。"""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace('\n', ' ')
    return text if len(text) <= limit else f'{text[:limit - 1]}…'


@dataclass
class ToolResult:
    payload: dict
    summary: str
    images: list[ImageContent] = field(default_factory=list)

    def content(self):
        return [TextContent(type='text', text=self.summary), *self.images]


@dataclass
class Operation:
    id: str
    tool: str
    instance: str | None
    request_key: tuple | None
    fingerprint: str
    status: str = 'pending'
    result: ToolResult | None = None
    error: dict | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None

    def view(self):
        return {
            'operation_id': self.id,
            'tool': self.tool,
            'instance': self.instance,
            'status': self.status,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'result': copy.deepcopy(self.result.payload) if self.result else None,
            'error': copy.deepcopy(self.error),
        }


@dataclass
class DeviceLease:
    """设备独占租约：调度器停止后，输入类工具凭此接管设备。"""
    id: str
    instance: str
    created_at: str
    expires_at: float
    ttl_seconds: int

    def view(self):
        return {
            'lease_id': self.id,
            'instance': self.instance,
            'created_at': self.created_at,
            'expires_at': datetime.fromtimestamp(self.expires_at, timezone.utc).isoformat(),
            'ttl_seconds': self.ttl_seconds,
        }


class OperationStore:
    """进程内操作台账；request_id 与参数指纹共同防止重试重复执行。"""

    def __init__(self, limit=256):
        self.limit = limit
        self.lock = threading.Lock()
        self.items = {}
        self.requests = {}

    def begin(self, spec, arguments):
        request_id = arguments.get('request_id')
        fingerprint = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        instance = arguments.get('instance')
        request_key = (spec.name, instance, request_id) if request_id else None
        with self.lock:
            if request_key in self.requests:
                operation = self.items[self.requests[request_key]]
                if operation.fingerprint != fingerprint:
                    raise ApiError('REQUEST_ID_CONFLICT', 'request_id 已用于不同参数，请使用新的 request_id')
                return operation, True
            operation = Operation(uuid.uuid4().hex, spec.name, instance, request_key, fingerprint)
            self.items[operation.id] = operation
            if request_key is not None:
                self.requests[request_key] = operation.id
            while len(self.items) > self.limit:
                oldest = next(iter(self.items))
                removed = self.items.pop(oldest)
                if removed.request_key is not None:
                    self.requests.pop(removed.request_key, None)
            return operation, False

    def succeed(self, operation, result):
        with self.lock:
            operation.status = 'success'
            operation.result = copy.deepcopy(result)
            operation.completed_at = datetime.now(timezone.utc).isoformat()

    def fail(self, operation, error):
        # 超时只表示调用方等待结束，真实工作可能仍在运行，保留 pending。
        if error['error']['code'] in UNCERTAIN_ERRORS:
            return
        with self.lock:
            operation.status = 'failed'
            operation.error = copy.deepcopy(error['error'])
            operation.completed_at = datetime.now(timezone.utc).isoformat()

    def get(self, operation_id):
        with self.lock:
            operation = self.items.get(operation_id)
            if operation is None:
                raise ApiError('NOT_FOUND', '操作不存在或已从内存台账淘汰')
            return copy.deepcopy(operation)


class Tools:
    """MCP 工具集适配器，统一校验、分发、操作去重和错误响应。"""

    def __init__(self, configs=None, runtime=None, *, allow_legacy=False):
        self.configs = configs
        self.runtime = runtime
        self.allow_legacy = allow_legacy
        self.calls = BoundedCalls()
        self.devices = BoundedCalls(limit=2)
        self.operations = OperationStore()
        self.initialize_lock = threading.Lock()
        self.lease_lock = threading.Lock()
        self.leases = {}
        self.failed_devices = []

    def definitions(self):
        return tool_definitions(self.allow_legacy)

    def initialize(self):
        """在工作线程中按需惰性初始化配置服务和运行时服务。"""
        with self.initialize_lock:
            if self.configs is None:
                self.configs = ConfigService()
            if self.runtime is None:
                self.runtime = RuntimeService(self.configs)

    @staticmethod
    def error_payload(code, message, *, retryable=False, outcome_certain=True,
                      next_step=None, details=None, operation_id=None):
        error = {
            'code': code,
            'message': message,
            'retryable': retryable,
            'outcome_certain': outcome_certain,
        }
        if details is not None:
            error['details'] = details
        payload = {'status': 'failed', 'error': error}
        if operation_id:
            payload['operation_id'] = operation_id
        if next_step:
            payload['next_step'] = next_step
        return payload

    @staticmethod
    def error_result(payload):
        error = payload['error']
        text = (f"{error['code']}: {error['message']}\n"
                f"可重试：{error['retryable']}，结果确定：{error['outcome_certain']}")
        if payload.get('next_step'):
            text += f"\n下一步：{payload['next_step']['tool']}（{payload['next_step']['reason']}）"
        if payload.get('operation_id'):
            text += f"\noperation_id={payload['operation_id']}（先查询终态，不要直接重试）"
        if payload.get('deduplicated'):
            text += f"\n{DEDUPLICATED_NOTE}"
        if error.get('details'):
            text += f"\n详情：{json.dumps(error['details'], ensure_ascii=False)}"
        return CallToolResult(
            content=[TextContent(type='text', text=text)],
            structuredContent=payload,
            isError=True,
        )

    @staticmethod
    def validate_arguments(arguments, schema):
        if not isinstance(arguments, dict):
            raise ApiError('INVALID_PARAMS', '工具参数必须是 JSON 对象')
        try:
            jsonschema.validate(instance=arguments, schema=schema)
        except jsonschema.ValidationError as exc:
            field = '.'.join(str(part) for part in exc.absolute_path) or None
            details = {'field': field, 'rule': exc.validator}
            raise ApiError('INVALID_PARAMS', f'参数校验失败：{exc.message}', details) from exc

    def transform_legacy(self, legacy, arguments):
        if legacy is None or legacy.transform == 'identity':
            return arguments
        result = dict(arguments)
        if legacy.transform == 'task_help':
            result['task'] = result.pop('task_name')
        elif legacy.transform == 'update_config':
            path = '.'.join(result.pop(key) for key in ('task', 'group', 'arg'))
            result.update(revision=None, changes=[{'path': path, 'value': result.pop('value')}], dry_run=False)
        elif legacy.transform == 'recent_logs':
            result['limit'] = min(result.pop('lines', 50), 500)
        elif legacy.transform == 'trigger_task':
            result.update(enabled=True, next_run=current_time().strftime('%Y-%m-%d %H:%M:%S'))
        return result

    async def call(self, name, arguments):
        """执行工具并始终返回含结构化内容的 MCP CallToolResult。"""
        spec, legacy = resolve(name, self.allow_legacy)
        if spec is None:
            return self.error_result(self.error_payload(
                'UNKNOWN_TOOL', f'未知或当前端点未启用的工具：{name}'))
        operation = None
        try:
            schema = legacy.input if legacy else spec.input
            self.validate_arguments(arguments, schema)
            canonical = self.transform_legacy(legacy, arguments)
            if spec.mutating:
                operation, duplicate = self.operations.begin(spec, canonical)
                if duplicate:
                    return self.duplicate_result(operation)
            if spec.device_operation:
                await self.calls.run(self.validate_device, spec, canonical)
                raw = await self.devices.run(
                    self.device_operation, spec, canonical.get('instance'), canonical,
                    timeout=DEVICE_TIMEOUTS[spec.device_operation] + 30)
                result = self.device_result(spec, canonical, raw)
            else:
                result = await self.calls.run(self.dispatch, spec, canonical)
            if operation:
                result = self.attach_operation(result, operation)
                if result.payload.get('status') == 'pending':
                    operation.result = copy.deepcopy(result)
                else:
                    self.operations.succeed(operation, result)
            return CallToolResult(content=result.content(), structuredContent=result.payload)
        except ApiError as exc:
            payload = self.api_error_payload(spec, exc, canonical if 'canonical' in locals() else arguments,
                                             operation)
            if operation:
                self.operations.fail(operation, payload)
            return self.error_result(payload)
        except Exception as exc:
            certain = not spec.mutating
            payload = self.error_payload(
                'INTERNAL_ERROR', str(exc), outcome_certain=certain,
                next_step=self.next_step(spec, arguments, operation),
                operation_id=operation.id if operation else None)
            if operation:
                self.operations.fail(operation, payload)
            return self.error_result(payload)

    def attach_operation(self, result, operation):
        result.payload['operation_id'] = operation.id
        if result.payload.get('status') == 'pending':
            result.payload['next_step'] = {
                'tool': 'azurpilot_get_operation',
                'reason': f'使用 operation_id={operation.id} 查询最终结果，不要重复提交',
            }
        return result

    def duplicate_result(self, operation):
        if operation.status == 'pending':
            if operation.result is not None:
                result = copy.deepcopy(operation.result)
            else:
                result = ToolResult({'status': 'pending'}, '操作仍在执行，请查询操作状态')
            result = self.attach_operation(result, operation)
            result.payload['deduplicated'] = True
            result.summary = f'{result.summary}\n{DEDUPLICATED_NOTE}'
            return CallToolResult(content=result.content(), structuredContent=result.payload)
        if operation.status == 'failed':
            error = operation.error or {'code': 'OPERATION_FAILED', 'message': '操作失败',
                                        'retryable': False, 'outcome_certain': True}
            return self.error_result({
                'status': 'failed', 'error': error, 'operation_id': operation.id,
                'deduplicated': True,
                'next_step': {'tool': 'azurpilot_get_operation', 'reason': '查看已确定的失败结果'},
            })
        result = copy.deepcopy(operation.result)
        result.payload['deduplicated'] = True
        result.summary = f'{result.summary}\n{DEDUPLICATED_NOTE}'
        return CallToolResult(content=result.content(), structuredContent=result.payload)

    def next_step(self, spec, arguments, operation=None):
        if operation:
            return {'tool': 'azurpilot_get_operation', 'reason': '先确认操作终态，避免重复产生副作用'}
        if spec.name == 'azurpilot_patch_config':
            return {'tool': 'azurpilot_get_config', 'reason': '重新读取配置和 revision 后修正请求'}
        if arguments.get('instance'):
            return {'tool': 'azurpilot_get_context', 'reason': '确认实例与当前任务状态后再决定下一步'}
        if spec.name != 'azurpilot_list_instances':
            return {'tool': 'azurpilot_list_instances', 'reason': '确认可用实例和服务状态'}
        return None

    def api_error_payload(self, spec, error, arguments, operation):
        code = error.code
        next_step = self.next_step(spec, arguments, operation)
        retryable = code in RETRYABLE_ERRORS
        if code == 'CONFLICT':
            next_step = {'tool': 'azurpilot_get_config', 'reason': '配置已变化，重新读取 revision 后再提交'}
        elif code in ('DEVICE_NOT_ACQUIRED', 'LEASE_EXPIRED', 'LEASE_NOT_HELD'):
            next_step = {'tool': 'azurpilot_acquire_device_control',
                         'reason': '先接管设备并取得 lease_id，再执行输入操作'}
        elif code == 'DEVICE_IN_USE':
            next_step = {'tool': 'azurpilot_get_context',
                         'reason': '确认实例状态；接管设备前需由管理端停止实例'}
        elif code == 'STALE_OBSERVATION':
            next_step = {'tool': 'azurpilot_observe_device',
                         'reason': '重新采集画面，用新的 frame_id 重新定位坐标'}
        elif code == 'OUT_OF_RANGE':
            next_step = {'tool': 'azurpilot_observe_device',
                         'reason': '按返回帧的像素尺寸重新指定坐标'}
        elif code in ('UNSUPPORTED_TEXT', 'ADB_SHELL_DENIED'):
            next_step = {'tool': spec.name, 'reason': '按 details 中的允许范围修正参数'}
        elif code == 'INVALID_PARAMS' and error.details:
            next_step = {'tool': spec.name, 'reason': '按 details.field 和 rule 修正参数后重试'}
        elif code == 'STATISTICS_LOADING':
            next_step = {'tool': 'azurpilot_get_statistics',
                         'reason': '统计库正在写入或初始化，稍后重试同一查询'}
        elif code in ('STATISTICS_UNAVAILABLE', 'PERMISSION_DENIED'):
            # 这两类失败无法靠换一个工具解决：前者要检查统计库，后者要检查文件权限。
            next_step = None
        elif code == 'NOT_FOUND' and spec.name == 'azurpilot_get_task_schema':
            next_step = {'tool': 'azurpilot_search_tasks',
                         'reason': '先用关键词确认任务标识，再读取参数定义'}
        elif code in ('NOT_FOUND', 'READ_ONLY') and spec.name in (
                'azurpilot_patch_config', 'azurpilot_set_task_schedule'):
            next_step = {'tool': 'azurpilot_get_task_schema',
                         'reason': '按任务参数定义确认可写路径后重试；本次未写入任何配置'}
        if spec.device_operation in CONTROL_OPERATIONS and code == 'DEVICE_TIMEOUT':
            # 输入命令可能已下发也可能没有，直接重放会重复产生副作用。
            retryable = False
            next_step = {'tool': 'azurpilot_observe_device',
                         'reason': '命令可能已下发，先观测画面确认是否已响应，不要直接重试'}
        return self.error_payload(
            code, error.message, retryable=retryable,
            outcome_certain=code not in UNCERTAIN_ERRORS,
            next_step=next_step, details=error.details,
            operation_id=operation.id if operation else None)

    async def close(self):
        """关闭工具队列并清理残留设备进程。"""
        import asyncio
        await asyncio.gather(self.calls.close(), self.devices.close())
        for process in self.failed_devices[:]:
            await asyncio.to_thread(cleanup_device, process)
            self.failed_devices.remove(process)

    def device_operation(self, spec, instance, params):
        try:
            return run_device(spec.device_operation, instance, params)
        except DeviceCleanupError as exc:
            with self.devices.lock:
                self.devices.closed = True
                self.failed_devices.append(exc.process)
            raise

    def require_lease(self, instance, lease_id):
        """输入类工具的前置条件：持有该实例的未过期租约，且调度器未重新接管。"""
        now = time.time()
        with self.lease_lock:
            lease = self.leases.get(instance)
            if lease is None or lease.id != lease_id:
                raise ApiError('DEVICE_NOT_ACQUIRED',
                               '尚未接管该设备，或 lease_id 与当前租约不一致',
                               {'instance': instance})
            if lease.expires_at <= now:
                self.leases.pop(instance, None)
                raise ApiError('LEASE_EXPIRED', '设备租约已过期，请重新获取后再操作',
                               {'instance': instance})
            lease.expires_at = now + lease.ttl_seconds
        status = self.runtime.overview(instance)['status']
        if status == 'running':
            # 调度器恢复后设备控制权回到实例，旧租约立即作废。
            with self.lease_lock:
                self.leases.pop(instance, None)
            raise ApiError('DEVICE_IN_USE', '该实例的调度器已开始运行，设备接管已失效',
                           {'instance_status': status})

    def validate_device(self, spec, arguments):
        self.initialize()
        if spec.device_operation != 'restart_adb' or arguments.get('instance') is not None:
            self.configs.path(arguments['instance'])
        if spec.device_operation in CONTROL_OPERATIONS:
            self.require_lease(arguments['instance'], arguments.get('lease_id'))
        observed = arguments.get('frame_id')
        if observed and load_frame(arguments['instance'], observed) is None:
            # 先在本进程查观测帧，避免为一个已失效的参照启动设备子进程。
            raise ApiError('STALE_OBSERVATION', '观测帧不存在或已淘汰，请重新观测后再操作',
                           {'frame_id': observed})

    def device_result(self, spec, arguments, raw):
        operation = spec.device_operation
        if operation == 'get_screenshot':
            payload = {'status': 'success', 'instance': arguments['instance'], **{
                key: raw[key] for key in ('frame_id', 'width', 'height', 'orientation',
                                          'captured_at', 'cached', 'backend')
            }, 'mime_type': 'image/jpeg'}
            image = ImageContent(type='image', data=raw['image'], mimeType='image/jpeg')
            return ToolResult(
                payload,
                f"已采集 {arguments['instance']} 的 {payload['width']}×{payload['height']} 截图；"
                f"frame_id={payload['frame_id']}，方向={payload['orientation']}，"
                f"cached={payload['cached']}，backend={payload['backend']}",
                [image])
        if operation == 'restart_emulator':
            return ToolResult({'status': 'success', 'instance': arguments['instance'], 'restart_executed': True},
                              '模拟器重启流程已执行；请重新观测设备确认可用')
        if operation in CONTROL_OPERATIONS:
            payload = {
                'status': 'success', 'instance': arguments['instance'],
                'lease_id': arguments['lease_id'], 'command_dispatched': True,
                'frame_changed': raw.get('frame_changed'),
                'frame_difference': raw.get('frame_difference'),
                'frame_id': raw.get('frame_id'),
                'observation_verified': bool(raw.get('observation_verified')),
                'detail': raw.get('detail') or {},
            }
            if 'output' in raw:
                payload['output'] = raw['output']
            if 'truncated' in raw:
                payload['truncated'] = raw['truncated']
            return ToolResult(payload, self.control_summary(operation, payload))
        payload = {'status': 'success', 'scope': 'global', 'adb_restarted': True,
                   'adb_path': raw.get('adb_path', ''),
                   'reconnected': raw.get('reconnected', []),
                   'devices': raw.get('devices', [])}
        online = '、'.join(payload['devices']) if payload['devices'] else '无'
        return ToolResult(
            payload,
            f"ADB 服务已重启（{payload['adb_path'] or 'adb'}），重连 {len(payload['reconnected'])} 个串口；"
            f"当前在线设备：{online}。请对目标实例调用 azurpilot_observe_device 确认可交互")

    @staticmethod
    def control_summary(operation, payload):
        """把「命令已下发」「画面已变化」「任务已完成」三件事分开陈述。"""
        detail = payload['detail']
        if operation == 'click':
            action = f"点击已发送 ({detail['target'][0]}, {detail['target'][1]})"
        elif operation == 'swipe':
            action = f"滑动已发送 {detail['from']} → {detail['to']}"
        elif operation == 'long_press':
            action = (f"长按已发送 ({detail['target'][0]}, {detail['target'][1]}, "
                      f"{detail['duration_ms']}ms)")
        elif operation == 'input_text':
            action = f"已输入 {detail['text_length']} 个字符，未发送确认键"
        elif operation == 'press_key':
            action = f"已发送按键 {detail['key']}({detail['keycode']})"
        else:
            action = f"已执行只读诊断命令 {' '.join(detail['argv'])}"

        changed = payload['frame_changed']
        if changed is None:
            screen = '画面变化未验证'
        elif changed:
            screen = f"画面已变化（差异 {payload['frame_difference']}）"
        else:
            screen = f"画面未变化（差异 {payload['frame_difference']}）"
        if operation == 'adb_shell':
            text = f"{action}；本操作不改变设备状态"
        else:
            text = (f"{action}；{screen}；任务是否完成未知，"
                    f"请用 azurpilot_observe_device 或 azurpilot_get_context 确认")
        if payload.get('frame_id'):
            text += f"；frame_id={payload['frame_id']}"
        if payload.get('truncated'):
            text += "；输出已截断"
        if operation == 'adb_shell':
            text += f"\n输出：{(payload.get('output') or '')[:400]}"
        return text

    @staticmethod
    def at_path(data, path):
        value = data
        for part in path.split('.'):
            if not isinstance(value, dict) or part not in value:
                raise ApiError('NOT_FOUND', f'配置路径不存在：{path}')
            value = value[part]
        return value

    def dispatch(self, spec, arguments):
        self.initialize()
        handler = getattr(self, f'tool_{spec.handler}', None)
        if handler is None:
            raise ApiError('UNKNOWN_TOOL', f'工具尚未实现：{spec.name}')
        return handler(arguments)

    def tool_list_instances(self, arguments):
        instances = [{'name': item['name'], 'status': item['status'],
                      'current_task': item.get('currentTask')}
                     for item in self.runtime.instances()]
        summary = ('发现 %d 个实例：%s' % (
            len(instances), brief(f"{item['name']}({item['status']})" for item in instances))
            if instances else '未发现实例')
        return ToolResult({'status': 'success', 'instances': instances}, summary)

    def active_lease(self, instance, status=None):
        now = time.time()
        with self.lease_lock:
            lease = self.leases.get(instance)
            if lease is None or lease.expires_at <= now:
                self.leases.pop(instance, None)
                return None
        if (status or self.runtime.overview(instance)['status']) == 'running':
            # 调度器恢复后设备控制权回到实例，租约作废，不能继续报告为可用。
            with self.lease_lock:
                if self.leases.get(instance) is lease:
                    self.leases.pop(instance, None)
            return None
        return lease.view()

    def tool_get_context(self, arguments):
        instance = arguments['instance']
        overview = self.runtime.overview(instance)
        running = next((task['name'] for task in overview['tasks'] if task['state'] == 'running'), None)
        schedule = [{'task': task['name'], 'next_run': task['nextRun'], 'state': task['state']}
                    for task in overview['tasks'][:10]]
        resources = {item['name']: {key: item.get(key) for key in ('label', 'value', 'limit', 'total', 'record')}
                     for item in overview['resources']}
        logs = self.runtime.logs(instance)
        errors = [entry for entry in logs['entries'] if entry['level'] in ('ERROR', 'CRITICAL')]
        recent_error = errors[-1] if errors else None
        lease = self.active_lease(instance, overview['status'])
        payload = {
            'status': 'success', 'instance': instance, 'revision': overview['revision'],
            'instance_status': overview['status'], 'current_task': running,
            'schedule': schedule, 'resources': resources, 'recent_error': recent_error,
            'device': {'observation_supported': True, 'control_supported': True,
                       'control_requires_lease': True, 'lease': lease,
                       'backend': 'spawned_device_worker'},
        }
        summary = f"{instance}：{overview['status']}，当前任务：{running or '无'}"
        if lease:
            summary += f"；已接管设备 lease_id={lease['lease_id']}"
        return ToolResult(payload, summary)

    def task_search_text(self, task):
        """返回任务的三层可检索文本：标识/显示名、参数组、参数与选项说明。"""
        translations = self.configs.translations
        task_i18n = translations.get('Task', {}).get(task, {})
        spec_i18n = translations.get(task, {})
        strong = [task, task_i18n.get('name', '')]
        medium, weak = [], [task_i18n.get('help', '')]
        for group, fields in (self.configs.args.get(task) or {}).items():
            if group == 'Storage' or not isinstance(fields, dict):
                continue
            group_i18n = spec_i18n.get(group, {})
            medium.extend((group, group_i18n.get('_info', {}).get('name', '')))
            for name, metadata in fields.items():
                if not isinstance(metadata, dict):
                    continue
                arg_i18n = group_i18n.get(name, {})
                weak.extend((name, arg_i18n.get('name', ''), arg_i18n.get('help', '')))
                weak.extend(str(arg_i18n.get(option, option)) for option in metadata.get('option') or [])
        return ([text.casefold() for text in strong if text],
                [text.casefold() for text in medium if text],
                [text.casefold() for text in weak if text])

    @staticmethod
    def match_rank(variants, layers):
        """按命中层级打分：显示名精确匹配最高，其次显示名、参数组、参数说明。"""
        strong, medium, weak = layers
        if any(variant == text for variant in variants for text in strong):
            return 4
        if any(variant in text for variant in variants for text in strong):
            return 3
        if any(variant in text for variant in variants for text in medium):
            return 2
        if any(variant in text for variant in variants for text in weak):
            return 1
        return None

    def task_search_rank(self, tokens, task):
        """所有关键词都命中才算匹配，返回最弱一层的权重用于排序。"""
        layers = self.task_search_text(task)
        ranks = []
        for token in tokens:
            variants = [item.casefold() for item in (token, *TASK_SEARCH_ALIASES.get(token, ()))]
            rank = self.match_rank(variants, layers)
            if rank is None:
                return None
            ranks.append(rank)
        return min(ranks)

    def tool_search_tasks(self, arguments):
        query = arguments.get('query', '').strip()
        limit = arguments.get('limit', 10)
        if query:
            tokens = query.casefold().split()
            ranked = sorted(((-rank, index, task)
                             for index, task in enumerate(self.configs.args)
                             if (rank := self.task_search_rank(tokens, task)) is not None))
        else:
            ranked = [(0, index, task) for index, task in enumerate(self.configs.args)]
        total = len(ranked)
        translations = self.configs.translations.get('Task', {})
        matches = []
        for _, _, task in ranked[:limit]:
            task_i18n = translations.get(task, {})
            matches.append({'task': task, 'display_name': task_i18n.get('name', task),
                            'description': task_i18n.get('help', '')})
        truncated = total > limit
        if matches:
            labels = brief((f"{item['task']}({item['display_name']})"
                            if item['display_name'] != item['task'] else item['task'])
                           for item in matches)
            summary = f'找到 {total} 个任务{"（仅列出前 %d 项）" % limit if truncated else ""}：{labels}'
        else:
            summary = f'未找到与「{query}」匹配的任务；可改用任务标识或更短的关键词'
        return ToolResult({'status': 'success', 'query': arguments.get('query', ''),
                           'tasks': matches, 'truncated': truncated}, summary)

    def tool_get_task_schema(self, arguments):
        task = arguments['task']
        task_args = self.configs.args.get(task)
        if not isinstance(task_args, dict):
            raise ApiError('NOT_FOUND', f'任务不存在：{task}')
        translations = self.configs.translations
        task_i18n = translations.get('Task', {}).get(task, {})
        spec_i18n = translations.get(task, {})
        groups = {}
        for group_name, fields in task_args.items():
            if group_name == 'Storage' or not isinstance(fields, dict):
                continue
            group_i18n = spec_i18n.get(group_name, {})
            group_info = group_i18n.get('_info', {})
            output_fields = {}
            for name, metadata in fields.items():
                if not isinstance(metadata, dict):
                    continue
                arg_i18n = group_i18n.get(name, {})
                options = metadata.get('option')
                output_fields[name] = {
                    'path': f'{task}.{group_name}.{name}',
                    'display_name': arg_i18n.get('name', name),
                    'help': arg_i18n.get('help', ''),
                    'type': metadata.get('type', 'input'),
                    'default': metadata.get('value'),
                    'options': options,
                    'option_labels': {str(option): arg_i18n.get(str(option), str(option))
                                      for option in options or []},
                    'writable': metadata.get('display') not in READ_ONLY_DISPLAY
                                and metadata.get('type') not in READ_ONLY_FIELDS,
                    'validation': metadata.get('validate'),
                }
            groups[group_name] = {
                'display_name': group_info.get('name', group_name),
                'help': group_info.get('help', ''), 'arguments': output_fields,
            }
        payload = {'status': 'success', 'task_name': task,
                   'display_name': task_i18n.get('name', task),
                   'help': task_i18n.get('help', ''), 'groups': groups}
        fields = [field for group in groups.values() for field in group['arguments'].values()]
        writable = [field['path'] for field in fields if field['writable']]
        summary = (f'已返回任务 {task} 的参数定义：{len(fields)} 个参数，'
                   f'可写路径：{brief(writable, 20) if writable else "无"}')
        return ToolResult(payload, summary)

    def tool_get_config(self, arguments):
        if arguments.get('task') and arguments.get('path'):
            raise ApiError('INVALID_PARAMS', 'task 与 path 不能同时提供')
        data, revision = self.configs.read(arguments['instance'])
        data.pop('_stockInstance', None)
        path = arguments.get('path') or arguments.get('task')
        values = self.at_path(data, path) if path else data
        return ToolResult({'status': 'success', 'instance': arguments['instance'],
                           'revision': revision, 'path': path, 'values': values},
                          f"已读取 {arguments['instance']} 配置 {path or '全部'}，revision={revision}")

    def tool_patch_config(self, arguments):
        instance = arguments['instance']
        before, current = self.configs.read(instance)
        revision = arguments['revision'] or current  # 仅旧兼容入口允许省略 revision。
        changes = [ConfigChange(path=item['path'], value=item['value']) for item in arguments['changes']]
        dry_run = arguments.get('dry_run', False)
        result = self.configs.patch(instance, revision, changes,
                                    require_revision=True, dry_run=dry_run)
        diff = [{'path': item['path'], 'before': self.at_path(before, item['path']),
                 'after': self.at_path(result['values'], item['path'])}
                for item in arguments['changes']]
        payload = {'status': 'success', 'instance': instance, 'revision': result['revision'],
                   'dry_run': dry_run, 'changes': diff}
        pairs = brief([f"{item['path']}: {describe(item['before'])} → {describe(item['after'])}"
                       for item in diff], 5)
        summary = (f'校验通过，未写入 {len(diff)} 项配置（revision 仍为 {result["revision"]}）：{pairs}'
                   if dry_run else
                   f'已原子提交 {len(diff)} 项配置（新 revision={result["revision"]}）：{pairs}')
        return ToolResult(payload, summary)

    def tool_set_task_schedule(self, arguments):
        instance, task = arguments['instance'], arguments['task']
        _, revision = self.configs.read(instance)
        changes = []
        if 'enabled' in arguments:
            changes.append(ConfigChange(path=f'{task}.Scheduler.Enable', value=arguments['enabled']))
        if 'next_run' in arguments:
            changes.append(ConfigChange(path=f'{task}.Scheduler.NextRun', value=arguments['next_run']))
        result = self.configs.patch(instance, revision, changes, require_revision=True)
        scheduler = result['values'][task]['Scheduler']
        overview = self.runtime.overview(instance)
        running = any(item['name'] == task and item['state'] == 'running' for item in overview['tasks'])
        payload = {'status': 'success', 'instance': instance, 'task': task,
                   'enabled': scheduler['Enable'], 'next_run': str(scheduler['NextRun']),
                   'scheduled': scheduler['Enable'], 'running': running, 'revision': result['revision']}
        return ToolResult(
            payload,
            f"任务 {task} 已更新调度安排：enabled={scheduler['Enable']}, "
            f"next_run={scheduler['NextRun']}, 已排入调度={payload['scheduled']}, "
            f"正在执行={running}；不表示任务已执行完成")

    def tool_get_logs(self, arguments):
        data = self.runtime.logs(arguments['instance'], after=arguments.get('after', 0))
        level, keyword = arguments.get('level'), arguments.get('keyword', '').casefold()
        limit = arguments.get('limit', 50)
        filtered = [entry for entry in data['entries']
                    if (level is None or entry['level'] == level)
                    and (not keyword or keyword in entry['text'].casefold())]
        entries = filtered[:limit]
        has_more = len(filtered) > limit
        next_cursor = entries[-1]['id'] if has_more else data['cursor']
        payload = {'status': 'success', 'instance': arguments['instance'],
                   'next_cursor': next_cursor, 'reset': data['reset'],
                   'has_more': has_more, 'entries': entries}
        return ToolResult(payload, f'返回 {len(entries)} 条日志，next_cursor={next_cursor}')

    def tool_get_statistics(self, arguments):
        from module.mcp import statistics as statistics_tools
        statistics_tools.validate_arguments(arguments)
        category = arguments['category']
        if category == 'overview':
            payload, summary = statistics_tools.build_overview(self.runtime, arguments)
        elif category == 'flows':
            payload, summary = statistics_tools.build_flows(self.configs, arguments)
        else:
            payload, summary = statistics_tools.build_report(self.configs, self.runtime, arguments)
        return ToolResult(payload, summary)

    def tool_get_statistics_schema(self, arguments):
        from module.mcp import statistics as statistics_tools
        payload = statistics_tools.catalog_payload(arguments.get('category'))
        return ToolResult(payload, statistics_tools.catalog_summary(payload))

    def tool_acquire_device_control(self, arguments):
        instance = arguments['instance']
        ttl = arguments.get('ttl_seconds', LEASE_TTL_SECONDS)
        overview = self.runtime.overview(instance)
        if overview['status'] == 'running':
            raise ApiError('DEVICE_IN_USE', '该实例的调度器仍在运行，无法接管设备',
                           {'instance_status': 'running',
                            'hint': '先调用 azurpilot_stop_instance 停止实例，再重新获取接管'})
        now = time.time()
        with self.lease_lock:
            lease = self.leases.get(instance)
            already_held = lease is not None and lease.expires_at > now
            if already_held:
                lease.expires_at = now + ttl
                lease.ttl_seconds = ttl
            else:
                lease = DeviceLease(uuid.uuid4().hex, instance,
                                    datetime.now(timezone.utc).isoformat(), now + ttl, ttl)
                self.leases[instance] = lease
        payload = {'status': 'success', 'instance': instance, 'lease_id': lease.id,
                   'ttl_seconds': ttl,
                   'expires_at': datetime.fromtimestamp(
                       lease.expires_at, timezone.utc).isoformat(),
                   'already_held': already_held,
                   'instance_status': overview['status']}
        summary = (f"已接管 {instance} 设备，lease_id={lease.id}，有效期 {ttl} 秒"
                   + ('（复用已有租约并续期）' if already_held else '')
                   + '；先 observe_device 取 frame_id，再做坐标操作')
        return ToolResult(payload, summary)

    def tool_release_device_control(self, arguments):
        instance, lease_id = arguments['instance'], arguments['lease_id']
        with self.lease_lock:
            lease = self.leases.get(instance)
            if lease is None or lease.id != lease_id:
                raise ApiError('LEASE_NOT_HELD',
                               '没有与该 lease_id 匹配的租约，可能已释放、过期或被调度器收回')
            del self.leases[instance]
        return ToolResult(
            {'status': 'success', 'instance': instance, 'lease_id': lease_id, 'released': True},
            f'已释放 {instance} 的设备租约 {lease_id}；输入类工具不再可用')

    def tool_get_operation(self, arguments):
        operation = self.operations.get(arguments['operation_id'])
        if operation.tool == 'azurpilot_update_application' and operation.status == 'pending':
            status = update_service.status()
            if status.get('error'):
                error = {'code': 'UPDATE_FAILED', 'message': status['error'],
                         'retryable': False, 'outcome_certain': True}
                self.operations.fail(operation, {'error': error})
            elif not status.get('busy'):
                result = operation.result or ToolResult(
                    {'status': 'pending', 'accepted': True, 'update_completed': False}, '更新已接受')
                result.payload.update(status='success', update_completed=True)
                result.summary = '应用更新流程已结束'
                self.operations.succeed(operation, result)
            operation = self.operations.get(arguments['operation_id'])
        view = operation.view()
        return ToolResult({'status': 'success', 'operation': view},
                          f"操作 {operation.id[:8]} 状态：{operation.status}")

    def tool_start_instance(self, arguments):
        overview = self.runtime.start(arguments['instance'])
        running = next((task['name'] for task in overview['tasks'] if task['state'] == 'running'), None)
        return ToolResult({'status': 'success', 'instance': arguments['instance'],
                           'instance_status': overview['status'], 'current_task': running},
                          f"实例 {arguments['instance']} 已启动")

    def tool_stop_instance(self, arguments):
        overview = self.runtime.stop(arguments['instance'])
        return ToolResult({'status': 'success', 'instance': arguments['instance'],
                           'instance_status': overview['status'], 'current_task': None},
                          f"实例 {arguments['instance']} 已确认停止")

    def tool_update_application(self, arguments):
        if State.restart_event is None or State.dependency_sync_event is None:
            raise ApiError('UPDATE_UNAVAILABLE', '独立 MCP 或未启用监督重启的服务不支持安全更新，请通过 WebUI 更新')
        result = update_service.start('apply')
        if not result.get('accepted'):
            raise ApiError('UPDATE_FAILED', '更新请求未被接受')
        return ToolResult({'status': 'pending', 'accepted': True, 'update_completed': False},
                          '应用更新请求已接受，尚未完成；请查询操作状态')

    def tool_clear_scheduler_queue(self, arguments):
        """仅供旧兼容端点使用；新契约要求明确指定任务。"""
        data, _ = self.configs.read(arguments['instance'])
        cleared, retained = [], []
        for task, groups in data.items():
            if not isinstance(groups, dict) or not groups.get('Scheduler', {}).get('Enable', False):
                continue
            try:
                self.configs.validate(f'{task}.Scheduler.Enable', False)
            except ApiError as exc:
                if exc.code not in ('READ_ONLY', 'NOT_FOUND'):
                    raise
                retained.append(task)
            else:
                cleared.append(task)
        if cleared:
            _, revision = self.configs.read(arguments['instance'])
            changes = [ConfigChange(path=f'{task}.Scheduler.Enable', value=False) for task in cleared]
            self.configs.patch(arguments['instance'], revision, changes, require_revision=True)
        return ToolResult({'status': 'success', 'cleared': cleared, 'retained': retained},
                          f'兼容操作已停用 {len(cleared)} 个任务，保留 {len(retained)} 个只读任务')
