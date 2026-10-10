"""离线验证正式心情代码的长期误差；不连接模拟器、不读取真实实例配置。

对照规则核实于客户端 CN/model/proxy/bayproxy.lua、CN/model/vo/ship.lua
及 CN/sharecfg/gameset.lua（Lua 提交 d4f86ec76faf39f83fa3f618a2b1c4d6e9f6850e）。
对照只使用独立常量与逐批次整数恢复，不借用被测模型的相位或恢复公式。
"""

import argparse
import hashlib
import json
import random
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import module.combat.emotion as production
import module.config.config as config_source
from module.combat.emotion_state import EmotionRecoveryState
from module.config.config import AzurLaneConfig
from module.exception import ScriptEnd
from module.retire.fleet_emotion import learn_fleet_emotion


US = 1_000_000
PERIOD = 360_000_000
BASE = datetime(2026, 10, 9)
SOURCE_FILES = ('module/combat/emotion.py', 'module/combat/emotion_state.py', 'module/retire/fleet_emotion.py',
                'module/retire/fleet_management.py', 'module/config/config.py', 'dev_tools/emotion_simulate.py')
# 开始时固定源码指纹；长跑期间文件变化不能把新文件哈希冒充被测版本。
SOURCE_SHA256 = {file: hashlib.sha256(Path(file).read_bytes()).hexdigest() for file in SOURCE_FILES}


class QuietLogger:
    def __getattr__(self, name):
        """通过模拟状态对象读取对应的配置字段。"""
        return lambda *args, **kwargs: None


@dataclass(frozen=True)
class ShipSpec:
    recover: str
    oath: bool

    @property
    def cap(self):
        """返回模拟恢复条件下的心情上限。"""
        return 119 if self.recover == 'not_in_dormitory' else 150

    @property
    def label(self):
        """返回模拟策略的可读标识。"""
        return {'not_in_dormitory': '港区', 'dormitory_floor_1': '后宅一楼',
                'dormitory_floor_2': '后宅二楼'}[self.recover] + ('已婚' if self.oath else '未婚')


class LuaOracle:
    """按独立的确定相位逐批次恢复，包含上限和零值截断。"""

    def __init__(self, spec, initial, origin, phase):
        """初始化模拟器的时间、配置或舰队状态。"""
        self.spec = spec
        self.values = [initial, initial]
        self.last = origin
        self.next_tick = origin + PERIOD - phase
        self.gains = [0, 0]
        self.used = [0, 0]

    def advance(self, now):
        """向前推进模拟时钟及心情恢复批次。"""
        assert now >= self.last
        while self.next_tick <= now:
            for i, old in enumerate(self.values):
                base = 3 if self.spec.oath else 2
                extra = {'not_in_dormitory': 0, 'dormitory_floor_1': 2,
                         'dormitory_floor_2': 3}[self.spec.recover]
                cap = 119 if extra == 0 else 150
                new = min(old + max(min(base, cap - old), 0) + extra, 150)
                self.values[i] = new
                self.gains[i] += new - old
            self.next_tick += PERIOD
        self.last = now

    def consume(self, index, cost):
        """模拟一次战斗产生的心情消耗。"""
        assert self.values[index] >= cost, '对照舰队心情不足，不能伪造完成出击'
        self.values[index] -= cost
        self.used[index] += cost


def json_roundtrip(fields):
    """和实际 JSON 一样保留 datetime 的微秒，恢复读取时的 datetime 类型。"""
    restored = json.loads(json.dumps(fields, default=str))
    for key, value in restored.items():
        if key.endswith('Record') and isinstance(value, str):
            restored[key] = datetime.fromisoformat(value)
    return restored


class MemoryConfig:
    """只替换存储介质，调度目标仍调用生产 task_delay。"""

    def __init__(self, clock, spec, initial, cost, control, public=False, shared=None):
        """初始化模拟器的时间、配置或舰队状态。"""
        self.fields = {}
        self.shared = {} if shared is None else shared
        self.saves = 0
        self.task = SimpleNamespace(command='Main')
        self.Emotion_Mode = 'calculate'
        self.Emotion_IgnoreShipwreck = False
        self.Fleet_FleetOrder = 'fleet1_all_fleet2_standby'
        self.Campaign_Use2xBook = cost == 4
        self.PublicEmotion_Enable = public
        self.PublicEmotion_Tasks = 'Main, Event'
        for prefix in ['Emotion_Fleet1', 'Emotion_Fleet2'] + (['PublicEmotion_Fleet'] if public and not self.shared else []):
            values = {'Value': initial, 'Record': clock.now(), 'Recover': spec.recover,
                      'Oath': spec.oath, 'Onsen': False, 'Control': control}
            values['RecoveryState'] = EmotionRecoveryState.calibrate(
                initial, clock.now(), spec.recover, spec.oath, False).export()
            for key, value in values.items():
                setattr(self, prefix + key, value)

    def __getattr__(self, key):
        """通过模拟状态对象读取对应的配置字段。"""
        target = self.shared if key.startswith('PublicEmotion_Fleet') else self.fields
        if key not in target:
            raise AttributeError(key)
        return target[key]

    def __setattr__(self, key, value):
        """将字段更新写入模拟配置存储。"""
        if key.startswith(('Emotion_', 'PublicEmotion_Fleet')):
            target = self.shared if key.startswith('PublicEmotion_Fleet') else self.fields
            target[key] = value
        else:
            object.__setattr__(self, key, value)

    @contextmanager
    def multi_set(self):
        """批量更新模拟配置中的关联字段。"""
        try:
            yield
        finally:
            restored = json_roundtrip(self.fields)
            self.fields.clear()
            self.fields.update(restored)
            restored = json_roundtrip(self.shared)
            self.shared.clear()
            self.shared.update(restored)
            self.saves += 1

    def cross_set(self, key, value):
        """按分组路径更新模拟配置字段。"""
        self.fields[key] = value

    task_delay = AzurLaneConfig.task_delay


class Clock:
    def __init__(self, start, oracle):
        """初始化模拟器的时间、配置或舰队状态。"""
        self.us = self.origin = start
        self.advanced = 0
        self.oracle = oracle
        self.observe = lambda: None

    def now(self):
        """返回模拟测试当前时间。"""
        return BASE + timedelta(microseconds=self.us)

    def _move(self, target):
        """调整模拟事件的时间或恢复条件。"""
        assert target >= self.us
        self.advanced += target - self.us
        self.us = target
        self.oracle.advance(target)
        self.observe()

    def advance(self, delta):
        """向前推进模拟时钟及心情恢复批次。"""
        assert type(delta) is int and delta >= 0
        target = self.us + delta
        while self.oracle.next_tick <= target:
            tick = self.oracle.next_tick
            if tick - 1 > self.us:
                self._move(tick - 1)
            self._move(tick)
            if tick + 1 <= target:
                self._move(tick + 1)
        if self.us < target:
            self._move(target)


def simulate(spec, *, battles=10_000, cost=2, phase=179 * US, pattern='jitter90',
             control='prevent_green_face', public=False, dual=False, alternate=False, initial=None,
             measurement_us=None):
    """按配置运行一次确定性的心情恢复模拟。"""
    start = spec.cap if initial is None else initial
    oracle = LuaOracle(spec, start, 500_000, phase)
    clock = Clock(500_000, oracle)
    shared = {}
    configs = [MemoryConfig(clock, spec, start, cost, control, public, shared)
               for _ in range(2 if alternate else 1)]
    for i, config in enumerate(configs):
        config.task.command = 'Main' if i == 0 else 'Event'
        if dual:
            config.Fleet_FleetOrder = 'fleet1_mob_fleet2_boss'
    emotions = [production.Emotion(config) for config in configs]
    for emotion in emotions:
        emotion.map_is_2x_book = cost == 4
    active = emotions[0]
    completed = maps = delays = checks = max_over = max_under = max_segments = 0
    duration_us = wait_us = idle_us = 0
    scan_us = observed = learned = absolute_error = zero_error = 0
    baseline_error = baseline_zero = baseline_over = baseline_under = 0
    reference = [EmotionRecoveryState.calibrate(start, clock.now(), spec.recover, spec.oath, False) for _ in range(2)]
    ledger = [0, 0]
    worst = None
    rng = random.Random(20261009)
    scan_rng = random.Random(1092026)

    def observe():
        """应用模拟截图获得的可信心情观测。"""
        nonlocal checks, max_over, max_under, max_segments, worst
        nonlocal absolute_error, zero_error, baseline_error, baseline_zero, baseline_over, baseline_under
        active.update()
        fleets = [active.public_fleet] if public else active.fleets
        for i, fleet in enumerate(fleets):
            truth = oracle.values[i]
            error = fleet.current - truth
            if measurement_us is not None:
                reference[i].advance(clock.now())
                other = reference[i].value - truth
                assert reference[i].lower <= truth <= reference[i].upper
                baseline_error += abs(other)
                baseline_zero += other == 0
                baseline_over, baseline_under = max(baseline_over, other), max(baseline_under, -other)
            absolute_error += abs(error)
            zero_error += error == 0
            assert fleet.lower <= truth <= fleet.upper, (completed, clock.us, fleet.lower, truth, fleet.upper)
            assert abs(error) <= 3, (completed, clock.us, error)
            assert fleet.upper - fleet.lower <= fleet.speed
            assert len(fleet.state.segments) <= 64
            max_segments = max(max_segments, len(fleet.state.segments))
            if worst is None or abs(error) > abs(worst['error']):
                worst = {'battle': completed, 'microseconds': clock.us, 'fleet': i + 1,
                         'calculated': fleet.current, 'lua': truth, 'error': error}
            max_over, max_under = max(max_over, error), max(max_under, -error)
            checks += 1

    clock.observe = observe
    with patch.object(production, 'current_time', clock.now), patch.object(config_source, 'current_time', clock.now), \
            patch.object(production, 'logger', QuietLogger()), patch.object(config_source, 'logger', QuietLogger()):
        observe()
        while completed < battles:
            index = maps % len(configs)
            config, active = configs[index], emotions[index]
            count = min(7, battles - completed)
            attempts = 0
            while True:
                try:
                    active.check_reduce(count)
                    observe()
                    break
                except ScriptEnd:
                    delays += 1
                    attempts += 1
                    assert attempts < 5, '任务等待未能前进'
                    target = config.fields[f'{config.task.command}.Scheduler.NextRun']
                    delta = (target - clock.now()) // timedelta(microseconds=1)
                    assert delta > 0, '调度器提前取整导致反复立即唤醒'
                    wait_us += delta
                    clock.advance(delta)
                    active = emotions[index] = production.Emotion(config)
                    active.map_is_2x_book = cost == 4
            order = [1] * count if not dual else [1] * (count - 1) + [2]
            for fleet_index in order:
                observe()
                fleet = active.public_fleet if public else active.fleets[fleet_index - 1]
                before = fleet.current
                active.reduce(fleet_index)
                assert fleet.current == fleet.value == before - cost
                oracle_index = 0 if public else fleet_index - 1
                oracle.consume(oracle_index, cost)
                if measurement_us is not None:
                    reference[oracle_index].advance(clock.now())
                    reference[oracle_index].consume(cost)
                ledger[oracle_index] += cost
                completed += 1
                observe()
                if pattern in ('jitter90', 'full_rest'):
                    duration = rng.randrange(70 * US, 110 * US)
                elif pattern == 'half90':
                    duration = 90 * US + 500_000
                elif pattern == 'fast30':
                    duration = 30 * US + 500_000
                elif pattern == 'slow600':
                    duration = 600 * US
                elif pattern == 'balanced':
                    rate = (3 if spec.oath else 2) + {'not_in_dormitory': 0, 'dormitory_floor_1': 2,
                                                     'dormitory_floor_2': 3}[spec.recover]
                    duration = cost * PERIOD // rate
                else:
                    raise ValueError(pattern)
                duration_us += duration
                clock.advance(duration)
            maps += 1
            if measurement_us is not None and maps % 25 == 0:
                # 每 25 张图提供一次“本来就有”的完整扫描机会，两个窗口与真实相位无关。
                # 独立对照只输出画面整数读数；相位、批次时刻不传入生产学习函数。
                windows, result = {}, {}
                for category, ids in (('vanguard', range(3)), ('main', range(3, 6))):
                    begin = clock.now()
                    offset = scan_rng.randrange(measurement_us + 1)
                    clock.advance(offset)
                    points = oracle.values[0]
                    clock.advance(measurement_us - offset)
                    windows[category] = (begin, clock.now())
                    result[category] = {'1': [{'name': f'ship{i}', 'emotion': points} for i in ids]}
                    scan_us += measurement_us
                fields = {key.removeprefix('Emotion_'): value for key, value in config.fields.items()
                          if key.startswith('Emotion_')}
                view = SimpleNamespace(data={'Main': {'Emotion': fields, 'Campaign': {'Mode': 'normal'},
                                                      'Fleet': {'Fleet1': 1, 'Fleet2': 2,
                                                                'FleetOrder': 'fleet1_all_fleet2_standby'}}}, modified={})
                learned += learn_fleet_emotion(view, result, windows, {f'ship{i}' for i in range(6)})
                observed += 1
                # 对应 FleetInfo 原有一次保存。参考状态也经历相同扫描时间与保存次数。
                with config.multi_set():
                    for path, value in view.modified.items():
                        setattr(config, 'Emotion_' + path.split('.')[-1], value)
                observe()
            if pattern == 'full_rest' and maps % 30 == 0:
                rest = 6 * 3600 * US
                idle_us += rest
                clock.advance(rest)
            if maps % 100 == 0:
                active = emotions[index] = production.Emotion(config)
                active.map_is_2x_book = cost == 4
        observe()
    assert completed == battles
    assert clock.us - clock.origin == clock.advanced == duration_us + wait_us + idle_us + scan_us
    assert oracle.last == clock.us
    assert ledger == oracle.used and sum(ledger) == battles * cost
    assert oracle.values == [start + gain - used for gain, used in zip(oracle.gains, oracle.used)]
    report = {'configuration': spec.label, 'cost': cost, 'phase_us': phase, 'pattern': pattern,
            'control': control, 'public': public, 'dual': dual, 'alternate': alternate,
            'battles': completed, 'checks': checks, 'max_overestimate': max_over,
            'max_underestimate': max_under, 'worst': worst, 'max_segments': max_segments,
            'delays': delays, 'saves': sum(c.saves for c in configs), 'hours': (clock.us - clock.origin) / (3600 * US),
            'mean_absolute_error': absolute_error / checks, 'zero_error_ratio': zero_error / checks,
            'observation_count': observed, 'accepted_count': learned, 'scan_microseconds': scan_us,
            'measurement_us': measurement_us,
            'invariants': '场次、扣减、整数微秒、恢复收支、相位范围和JSON重载一致'}
    if measurement_us is not None:
        report['paired_baseline'] = {'mean_absolute_error': baseline_error / checks,
                                     'zero_error_ratio': baseline_zero / checks,
                                     'max_overestimate': baseline_over, 'max_underestimate': baseline_under}
    return report


def run_suite(battles=10_000, passive=False):
    """运行多组场景并报告模拟结果。"""
    results = []
    for recover in ('not_in_dormitory', 'dormitory_floor_1', 'dormitory_floor_2'):
        for oath in (False, True):
            spec = ShipSpec(recover, oath)
            for cost in (2, 4):
                for phase in (0, 179 * US, PERIOD - 1):
                    results.append(simulate(spec, battles=battles, cost=cost, phase=phase))
            print(f'{spec.label}: 6 组，每组 {battles} 场通过', flush=True)
    spec = ShipSpec('dormitory_floor_2', True)
    for options in ({'dual': True}, {'public': True, 'alternate': True}, {'pattern': 'half90'},
                    {'pattern': 'balanced', 'initial': 70}, {'pattern': 'full_rest'},
                    {'control': 'keep_exp_bonus'}, {'pattern': 'fast30'}, {'pattern': 'slow600'}):
        results.append(simulate(spec, battles=battles, phase=PERIOD - 1, **options))
    if passive:
        for recover in ('not_in_dormitory', 'dormitory_floor_1', 'dormitory_floor_2'):
            for oath in (False, True):
                spec = ShipSpec(recover, oath)
                for cost in (2, 4):
                    for width in (100_000, US, 30 * US):
                        result = simulate(spec, battles=battles, cost=cost, phase=179 * US, measurement_us=width)
                        if battles >= 10_000:
                            assert result['accepted_count'] > 0
                            assert result['mean_absolute_error'] < result['paired_baseline']['mean_absolute_error']
                            assert result['zero_error_ratio'] > result['paired_baseline']['zero_error_ratio']
                        results.append(result)
                print(f'{spec.label}: 6 组被动观测配对，每组 {battles} 场通过', flush=True)
    if SOURCE_SHA256 != {file: hashlib.sha256(Path(file).read_bytes()).hexdigest() for file in SOURCE_FILES}:
        raise RuntimeError('模拟期间源码发生变化，结果不能作为最终版本验收')
    report = {'case_count': len(results), 'battle_count': sum(r['battles'] for r in results),
              'max_absolute_error': max(max(r['max_overestimate'], r['max_underestimate']) for r in results),
              'checks': sum(r['checks'] for r in results),
              'source_sha256': SOURCE_SHA256,
              'scope': '全S胜、准确起点、固定且一致的恢复条件；观测组每25图提供一次准确读数；不含温泉、饮料或实机验收',
              'results': results}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--battles', type=int, default=10_000)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--passive', action='store_true', help='增加36组被动观测配对验收，总计80组')
    args = parser.parse_args()
    if args.battles <= 0:
        parser.error('--battles 必须大于零')
    report = run_suite(args.battles, passive=args.passive)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, ensure_ascii=False))
