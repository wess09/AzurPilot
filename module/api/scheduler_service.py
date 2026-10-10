"""调度程序的草稿、应用和设备隔离模拟接口。"""
import copy
from datetime import datetime

from module.api.protocol import ApiError
from module.scheduler.catalog import CARDS, OVERRIDES, REFRESHABLE, RESOURCES
from module.scheduler.context import snapshot, simulation_plan
from module.scheduler.engine import simulate
from module.scheduler.models import ProgramDocument, ResourceObservation
from module.scheduler.store import ConflictError, ProgramStore
from module.scheduler.templates import all_cards_program, builtins, default_program, enhance_program
from module.scheduler.validation import validate


class SchedulerService:
    def __init__(self, configs, runtime):
        self.configs, self.runtime = configs, runtime
        self.store = ProgramStore(configs.directory, store=getattr(configs, 'database', None))

    def get(self, instance):
        self.configs.path(instance)
        return self.store.get(instance)

    def catalog(self, instance):
        data, _ = self.configs.read(instance)
        return {'cards': [c.model_dump() for c in CARDS], 'resources': [
            {'name': name, 'label': self.configs.translate(f'{name}._info.name') if not name.startswith('Emotion') else f'舰队 {name[-1]} 心情',
             'refreshable': name in REFRESHABLE} for name in RESOURCES],
            'tasks': snapshot(data, {}, datetime.now())['tasks'], 'overrides': OVERRIDES,
            'builtins': [s.model_dump() for s in builtins()],
            'templates': {'takeover': default_program().model_dump(), 'enhance': enhance_program().model_dump(),
                          'all': all_cards_program().model_dump()}}

    def validation(self, instance, document, mode='takeover'):
        data, _ = self.configs.read(instance)
        from module.config.time_source import now
        tasks = {t['name'] for t in snapshot(data, {}, now())['tasks']}
        return validate(document, tasks, mode)

    def save(self, instance, revision, document):
        self.configs.path(instance)
        try:
            return self.store.update(instance, revision, draft=document.model_dump())
        except ConflictError as exc:
            raise ApiError('CONFLICT', str(exc)) from exc

    def apply(self, instance, revision, mode):
        current = self.get(instance)
        if current['revision'] != revision:
            raise ApiError('CONFLICT', '方案已变化，请重新加载')
        document = ProgramDocument.model_validate(current['draft'])
        if mode != 'native':
            result = self.validation(instance, document, mode)
            if not result['valid']:
                raise ApiError('INVALID_PARAMS', '程序校验失败，请修复标记的卡片', result['diagnostics'])
        try:
            return self.store.update(instance, revision, mode=mode, active=document.model_dump(), generation=current['generation'] + 1)
        except ConflictError as exc:
            raise ApiError('CONFLICT', str(exc)) from exc

    def simulate(self, instance, document, context, outcomes, steps, mode):
        result = self.validation(instance, document, mode)
        if not result['valid']:
            return {**result, 'state': {'status': 'error', 'trace': []}, 'effects': []}
        data, _ = self.configs.read(instance)
        from module.config.time_source import now
        state = snapshot(data, self.store.observations(instance), now())
        # 模拟输入只存在于本次调用，不能修改真实任务目录或持久变量。
        supplied = copy.deepcopy(context)
        if ('tasks' in supplied and not isinstance(supplied['tasks'], list)) or ('resources' in supplied and not isinstance(supplied['resources'], dict)):
            raise ApiError('INVALID_PARAMS', '模拟任务应为列表，资源应为对象')
        if 'tasks' in supplied:
            allowed = {t['name'] for t in state['tasks']}
            supplied['tasks'] = [t for t in supplied['tasks'] if isinstance(t, dict) and t.get('name') in allowed]
        state.update(supplied)
        from module.scheduler.engine import parse_time
        try:
            state['resources'] = {name: ResourceObservation.model_validate(row).model_dump() for name, row in state['resources'].items()}
            instant = parse_time(state['now'])
            plan = simulation_plan(data, state['tasks'], instant)
            due = [task for name in plan['nativeOrder'] for task in state['tasks'] if task['name'] == name and task.get('enabled') and task.get('nextRun') and parse_time(task['nextRun']) < parse_time(plan['nativeDueBefore'])]
        except (ValueError, TypeError, KeyError) as exc:
            raise ApiError('INVALID_PARAMS', '模拟时间或资源记录格式无效') from exc
        for key, value in plan.items():
            state.setdefault(key, value)
        if mode == 'enhance':
            state['tasks'] = due
        return {**result, **simulate(document, state, outcomes, steps)}

    def state(self, instance):
        current = self.get(instance)
        from module.runtime.process_manager import ProcessManager
        manager = ProcessManager._processes.get(instance)
        state = None
        if manager:
            with manager._runtime_lock:
                state = copy.deepcopy(manager.program_state)
        return {'mode': current['mode'], 'generation': current['generation'], 'state': state or {'status': 'idle', 'trace': []}}
