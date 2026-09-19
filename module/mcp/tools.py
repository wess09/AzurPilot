"""将 MCP 的 18 个工具适配到配置、运行与更新服务。"""
import datetime
import json
import re
import threading
from collections import deque

from mcp.types import ImageContent, TextContent

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.api.runtime_service import RuntimeService
from module.api.update_service import update_service
from module.config.mcp_helper import McpConfigHelper
from module.config.time_source import now as current_time
from module.mcp.execution import BoundedCalls, DEVICE_TIMEOUTS, DeviceCleanupError, cleanup_device, run_device
from module.runtime.setting import State


def text_response(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return [TextContent(type='text', text=value)]


class Tools:
    def __init__(self, configs=None, runtime=None):
        self.configs = configs
        self.runtime = runtime
        self.calls = BoundedCalls()
        self.devices = BoundedCalls(limit=2)
        self.helper = None
        self.initialize_lock = threading.Lock()
        self.failed_devices = []

    def initialize(self):
        # 在执行线程中惰性初始化，只读模板，不在导入时加载用户配置。
        with self.initialize_lock:
            if self.configs is None:
                self.configs = ConfigService()
            if self.runtime is None:
                self.runtime = RuntimeService(self.configs)
            if self.helper is None:
                self.helper = McpConfigHelper()

    async def call(self, name, arguments):
        try:
            if name in DEVICE_TIMEOUTS:
                # 实例白名单检查也必须经过配置服务，且不在事件循环中读盘。
                await self.calls.run(self.validate_device, name, arguments)
                result = await self.devices.run(self.device_operation, name, arguments.get('instance'),
                                                timeout=DEVICE_TIMEOUTS[name] + 30)
                if 'image' in result:
                    return [ImageContent(type='image', data=result['image'], mimeType='image/jpeg')]
                return text_response(result['text'])
            return await self.calls.run(self.dispatch, name, arguments)
        except ApiError as exc:
            return text_response(f'Error: {exc.code}: {exc.message}')
        except Exception as exc:
            return text_response(f'Error: {exc}')

    async def close(self):
        # 先同时禁入两组调用，再等工作完成；不会在关闭间隙启动新设备进程。
        import asyncio
        await asyncio.gather(self.calls.close(), self.devices.close())
        for process in self.failed_devices[:]:
            await asyncio.to_thread(cleanup_device, process)
            self.failed_devices.remove(process)

    def device_operation(self, name, instance):
        try:
            return run_device(name, instance)
        except DeviceCleanupError as exc:
            with self.devices.lock:
                self.devices.closed = True
                self.failed_devices.append(exc.process)
            raise

    def validate_device(self, name, arguments):
        self.initialize()
        if name != 'restart_adb' or arguments.get('instance') is not None:
            self.configs.path(arguments['instance'])

    def patch(self, instance, changes):
        self.configs.patch(instance, None, [ConfigChange(path=path, value=value)
                                            for path, value in changes])

    def log_path(self, instance):
        self.configs.path(instance)
        date = datetime.date.today().strftime('%Y-%m-%d')
        path = self.configs.root / 'log' / f'{date}_{instance}.txt'
        fallback = self.configs.root / 'log' / f'{date}_alas.txt'
        return fallback if not path.exists() and fallback.exists() else path

    def dispatch(self, name, arguments):
        self.initialize()
        handler = getattr(self, f'tool_{name}', None)
        if handler is None:
            return text_response(f'Unknown tool: {name}')
        return text_response(handler(arguments))

    def tool_list_instances(self, arguments):
        return self.configs.names()

    def tool_get_status(self, arguments):
        states = {'running': 1, 'stopped': 2, 'error': 3, 'updating': 4}
        return [{'instance': item['name'], 'running': item['status'] == 'running',
                 'state': states[item['status']]} for item in self.runtime.instances()]

    def tool_list_tasks(self, arguments):
        return self.helper.get_tasks()

    def tool_get_task_help(self, arguments):
        return self.helper.get_task_details(arguments['task_name'])

    def tool_get_resources(self, arguments):
        data, _ = self.configs.read(arguments['instance'])
        return self.helper.get_dashboard_resources(data)

    def tool_get_config(self, arguments):
        data, _ = self.configs.read(arguments['instance'])
        return data.get(arguments['task'], {}) if arguments.get('task') else data

    def tool_update_config(self, arguments):
        path = '.'.join(arguments[key] for key in ('task', 'group', 'arg'))
        self.patch(arguments['instance'], [(path, arguments['value'])])
        return f"Success: Updated {path} to {arguments['value']}"

    def tool_get_recent_logs(self, arguments):
        count = arguments.get('lines', 50)
        if type(count) is not int or not 1 <= count <= 5000:
            raise ApiError('INVALID_PARAMS', '日志行数须为 1 到 5000 的整数')
        path = self.log_path(arguments['instance'])
        if not path.exists():
            return f'Log file not found: {path}'
        with path.open(encoding='utf-8', errors='ignore') as stream:
            return ''.join(deque(stream, maxlen=count))

    def tool_start_instance(self, arguments):
        instance = arguments['instance']
        self.runtime.start(instance)
        return f'Success: Started {instance} (alas)'

    def tool_stop_instance(self, arguments):
        instance = arguments['instance']
        self.runtime.stop(instance)
        return f'Success: Stopped {instance}'

    def tool_get_current_running_task(self, arguments):
        overview = self.runtime.overview(arguments['instance'])
        if overview['status'] != 'running':
            return 'Error: Instance is not running.'
        for task in overview['tasks']:
            if task['state'] == 'running':
                return task['name']
        # 老 worker 未上报结构化任务事件时继续兼容日志解析。
        path = self.log_path(arguments['instance'])
        task = 'Unknown'
        if path.exists():
            with path.open(encoding='utf-8', errors='ignore') as stream:
                for line in stream:
                    match = re.search(r'调度器: 开始任务\s*[`\'" ](.*?)[`\'" ]', line)
                    match = match or re.search(r'<<<\s*Run task\s*(.*?)\s*>>>', line)
                    if match:
                        task = match[1]
        return task

    def tool_get_scheduler_queue(self, arguments):
        data, _ = self.configs.read(arguments['instance'])
        queue = []
        for name, groups in data.items():
            if name in {'Alas', 'Error', 'MUMU', 'MumuPlayer12', 'EmulatorManagement', 'Dashboard'}:
                continue
            scheduler = groups.get('Scheduler', {})
            if scheduler.get('Enable', False):
                queue.append({'task': name, 'next_run': str(scheduler.get('NextRun', '2050-01-01 00:00:00'))})
        return sorted(queue, key=lambda item: item['next_run'])

    def tool_trigger_task(self, arguments):
        task = arguments['task']
        self.patch(arguments['instance'], [(f'{task}.Scheduler.Enable', True),
                                           (f'{task}.Scheduler.NextRun', current_time().strftime('%Y-%m-%d %H:%M:%S'))])
        return f'Success: Task {task} scheduled for immediately.'

    def tool_clear_scheduler_queue(self, arguments):
        data, _ = self.configs.read(arguments['instance'])
        cleared, retained = [], []
        for task, groups in data.items():
            if not groups.get('Scheduler', {}).get('Enable', False):
                continue
            try:
                self.configs.validate(f'{task}.Scheduler.Enable', False)
            except ApiError as exc:
                if exc.code != 'READ_ONLY':
                    raise
                retained.append(task)
            else:
                cleared.append(task)
        if cleared:
            self.patch(arguments['instance'], [(f'{task}.Scheduler.Enable', False) for task in cleared])
        result = f"Success: Cleared tasks: {', '.join(cleared)}"
        if retained:
            result += f"; 保留不可编辑的任务: {', '.join(retained)}"
        return result

    def tool_update_alas(self, arguments):
        if State.restart_event is None or State.dependency_sync_event is None:
            raise ApiError('UPDATE_UNAVAILABLE', '独立 MCP 或未启用监督重启的服务不支持安全更新，请通过 WebUI 更新')
        result = update_service.start('apply')
        if not result.get('accepted'):
            raise ApiError('UPDATE_FAILED', '更新请求未被接受')
        return 'Success: Triggered AzurPilot update in background.'
