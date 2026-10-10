"""卡片程序的调度宿主：与现有任务执行、恢复和安全检查点连接。"""
import copy
import sqlite3
from datetime import timedelta

from module.config.time_source import now
from module.scheduler.context import snapshot
from module.scheduler.engine import Engine, ProgramError
from module.scheduler.models import ProgramDocument
from module.scheduler.state_channel import publish
from module.scheduler.store import ProgramStore
from module.scheduler.validation import validate


class SchedulerRuntime:
    def __init__(self, script, directory=None):
        self.script, self.store = script, ProgramStore(directory)
        self.mode, self.generation = 'native', None
        self.engine, self.invocation = None, None
        self.requests, self.recovery_requested = [], False
        self.yield_reason = ''
        self.refresh_at = {}
        self.fault = ''
        self.overlay = {}
        self.last_saved = None
        from module.scheduler.oil_control import NativeOilControl
        self.oil_control = NativeOilControl(self)

    def __deepcopy__(self, memo):
        """共享运行时宿主：持有脚本实例与调度存储，深拷贝复用同一实例。"""
        return self

    def attach(self, config):
        object.__setattr__(config, '_scheduler_runtime', self)
        object.__setattr__(config, '_scheduler_overrides', self.overlay)
        for key, value in self.overlay.items():
            object.__setattr__(config, key, value)

    def load_program(self):
        if not self.store.exists(self.script.config_name):
            if self.mode != 'native':
                raise ProgramError('正在使用的调度文档已丢失')
            return False
        current = self.store.get(self.script.config_name)
        if current['generation'] == self.generation:
            return False
        self.mode, self.generation = current['mode'], current['generation']
        self.overlay, self.invocation, self.fault = {}, None, ''
        from module.scheduler.oil_control import NativeOilControl
        self.oil_control = NativeOilControl(self)
        self.engine = None
        if self.mode != 'native':
            document = ProgramDocument.model_validate(current['active'])
            all_tasks = snapshot(self.script.config.data, {}, now())['tasks']
            result = validate(document, {t['name'] for t in all_tasks}, self.mode)
            if not result['valid']:
                raise ProgramError(result['diagnostics'][0]['message'])
            persisted = self.store.persistent(self.script.config_name)
            interrupted = persisted.pop('inFlight', None)
            if interrupted:
                outcome = {'task': interrupted, 'status': 'interrupted', 'reason': '程序重启，重新从入口判断'}
                persisted.setdefault('records', {})['lastResult'] = outcome
                persisted['records'].setdefault('results', {})[interrupted] = outcome
            self.engine = Engine(document, persisted)
        self.attach(self.script.config)
        self.emit()
        return True

    def program_changed(self):
        """原调度的长等待也需要响应旁路方案的应用操作。"""
        try:
            return self.store.exists(self.script.config_name) and self.store.get(self.script.config_name)['generation'] != self.generation
        except (ValueError, TimeoutError, sqlite3.Error) as exc:
            from module.logger import logger
            logger.warning(f'读取调度方案失败，将在下次轮询重试：{exc}')
            return False

    def context(self, config=None):
        config = config or self.script.config
        context = snapshot(config.data, self.store.observations(self.script.config_name), now())
        context['requests'] = copy.deepcopy(self.requests)
        # 复用原队列实现，保留固定优先级与囤积等待的语义。
        config.get_next_task()
        business = {t['name'] for t in context['tasks']}
        # 系统恢复不能占住业务候选的首位；它由独立恢复通道派发。
        candidate = next((t for t in config.pending_task if t.command in business), None)
        context['nativeTask'] = next((t for t in context['tasks'] if candidate and t['name'] == candidate.command), None)
        waiting = next((t for t in config.waiting_task if t.command in business), None)
        future = waiting.next_run + config.hoarding if waiting else now() + timedelta(minutes=5)
        context['nativeDeadline'] = future.isoformat(sep=' ')
        from module.scheduler.context import original_order
        from module.config.config import AzurLaneConfig
        context['nativeOrder'] = [t['name'] for t in original_order(config.data, context['tasks'])]
        context['nativeDueBefore'] = (now() - config.hoarding if AzurLaneConfig.is_hoarding_task else now()).isoformat(sep=' ')
        if self.mode == 'enhance':
            pending = {t.command for t in config.pending_task}
            context['tasks'] = [t for t in context['tasks'] if t['name'] in pending]
        return context

    def emit(self):
        state = self.engine.state.model_dump() if self.engine else {'status': 'idle', 'trace': []}
        if self.fault:
            state.update(status='error', reason=self.fault)
        state.update(mode=self.mode, generation=self.generation)
        publish(state)

    def save(self, in_flight=None):
        if self.engine:
            data = self.engine.persistent()
            if in_flight:
                data['inFlight'] = in_flight
            if data != self.last_saved:
                self.store.save_persistent(self.script.config_name, data)
                self.last_saved = copy.deepcopy(data)
        self.emit()

    def wait(self, deadline):
        # 只在调度等待层轮询，游戏识别循环不使用固定休眠。
        return self.script.wait_until(min(deadline, now() + timedelta(seconds=4)))

    def next_task(self):
        while True:
            try:
                self.load_program()
                self.attach(self.script.config)
                if self.mode == 'native':
                    return self.oil_control.select()
                if self.recovery_requested:
                    self.recovery_requested = False
                    return 'Restart'
                if self.fault:
                    self.emit()
                    self.wait(now() + timedelta(seconds=5))
                    continue
                self.script.config.load()
                context = self.context()
                if self.mode == 'enhance' and self.engine.state.status == 'ended':
                    previous = self.engine
                    self.engine = Engine(previous.document, previous.persistent())
                    self.engine.variables = copy.deepcopy(previous.variables)
                effect = self.engine.advance(context)
                self.emit()
                if effect.kind == 'execute':
                    from module.config.config import AzurLaneConfig
                    AzurLaneConfig.is_hoarding_task = False
                    self.invocation = copy.deepcopy(effect.payload)
                    self.yield_reason = ''
                    self.overlay = copy.deepcopy(effect.payload['overrides'])
                    if self.mode == 'takeover':
                        self.overlay['TaskBalancer_Enable'] = False
                    self.attach(self.script.config)
                    self.requests = [r for r in self.requests if r['task'] != effect.payload['task']]
                    self.save(effect.payload['task'])
                    return effect.payload['task']
                if effect.kind == 'refresh':
                    names = effect.payload['resources']
                    success = self.refresh(names)
                    self.engine.resume(success)
                    continue
                if effect.kind == 'wait':
                    from module.scheduler.engine import parse_time
                    deadline = parse_time(effect.payload['deadline'])
                    if now() >= deadline:
                        self.engine.resume()
                        continue
                    self.save()
                    if self.wait(deadline) is False and effect.payload.get('recheckOnConfigChange'):
                        self.engine.resume()
                elif effect.kind == 'error':
                    raise ProgramError(effect.payload['reason'])
                else:
                    self.save()
                    self.wait(now() + timedelta(seconds=5))
            except (ProgramError, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
                self.fault = f'卡片程序已停止派发：{exc}'
                from module.logger import logger
                logger.error(self.fault)
                self.emit()
                self.wait(now() + timedelta(seconds=5))

    def refresh(self, names):
        groups = ({'Oil', 'Coin'}, {'ActionPoint', 'YellowCoin', 'PurpleCoin'})
        expanded = set(names)
        for group in groups:
            if expanded & group:
                expanded |= group
        names = sorted(expanded)
        fresh = [n for n in names if n not in self.refresh_at or (now() - self.refresh_at[n]).total_seconds() >= 60]
        if not fresh:
            return False
        for n in fresh:
            self.refresh_at[n] = now()
        self.refresh_names, self.refresh_result = fresh, False
        previous = (getattr(self.script, '_watchdog_active', False), getattr(self.script, '_watchdog_task_start', 0),
                    getattr(self.script, '_watchdog_task_name', ''))
        import time
        self.script._watchdog_active = True
        self.script._watchdog_task_start = time.monotonic()
        self.script._watchdog_task_name = 'SchedulerRefresh'
        try:
            success = self.script.run('scheduler_refresh')
            return success is True and self.refresh_result and len(fresh) == len(names)
        finally:
            self.script._watchdog_active, self.script._watchdog_task_start, self.script._watchdog_task_name = previous

    def task_finished(self, task, success):
        if self.mode == 'native':
            self.oil_control.task_finished(task, success)
            return
        if not self.invocation or task != self.invocation['task']:
            return
        status = 'yielded' if self.yield_reason else 'completed' if success is True else 'recoverable' if success == 'recoverable' else 'failed'
        self.engine.resume({'task': task, 'status': status, 'reason': self.yield_reason, 'finishedAt': now().isoformat(sep=' ')})
        self.overlay, self.invocation = {}, None
        self.attach(self.script.config)
        self.script.config.bind(self.script.config.task)
        self.save()

    def should_yield(self, config):
        if not self.invocation:
            return False
        current = self.store.get(self.script.config_name)
        if current['generation'] != self.generation:
            self.yield_reason = '调度方案已更新'
            return True
        guard = self.invocation.get('guard')
        if self.invocation.get('followOriginal'):
            config.load()
            candidate = self.context(config)['nativeTask']
            if candidate and candidate['name'] != self.invocation['task']:
                self.yield_reason = '原计划已有其他优先任务'
                return True
        if guard:
            try:
                config.load()
                if not self.engine.guard(guard, self.context(config)):
                    self.yield_reason = '继续条件不满足或资源需要刷新'
                    return True
            except (ProgramError, ValueError, TypeError, KeyError) as exc:
                self.yield_reason = f'继续条件不可用：{exc}'
                self.fault = self.yield_reason
                return True
        return False

    def request(self, task):
        if task == 'Restart':
            self.recovery_requested = True
        elif not any(r['task'] == task for r in self.requests):
            self.requests.append({'task': task, 'requestedAt': now().isoformat(sep=' ')})
        return True
