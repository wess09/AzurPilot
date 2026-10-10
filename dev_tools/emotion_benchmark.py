"""比较相位学习前后的正式计算及离线扫描流程，不连接设备或真实实例。"""

import argparse
import copy
import hashlib
import json
import random
import statistics
import subprocess
import sys
import time
import types
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dev_tools.emotion_simulate import MemoryConfig, QuietLogger, ShipSpec, BASE, US
import module.combat.emotion as production
import module.retire.fleet_management as fleet_source
from module.base.utils import load_image
from module.combat.emotion_state import EmotionRecoveryState
from module.config.deep import deep_set
from module.retire.scanner import FleetEmotionScanner


def load_baseline(ref, path, name):
    """读取作为性能与正确性对照的基线数据。"""
    source = subprocess.check_output(['git', 'show', f'{ref}:{path}']).decode('utf-8')
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, f'{ref}:{path}', 'exec'), module.__dict__)
    return module


def calculate(module, state_class, iterations):
    """计算用于对比的心情恢复预测结果。"""
    cursor = [BASE + timedelta(microseconds=500_000)]
    clock = SimpleNamespace(now=lambda: cursor[0])
    config = MemoryConfig(clock, ShipSpec('dormitory_floor_2', True), 80, 2, 'prevent_green_face')
    for i in (1, 2):
        config.fields[f'Emotion_Fleet{i}RecoveryState'] = state_class.calibrate(
            80, clock.now(), 'dormitory_floor_2', True, False).export()
    tracker = module.Emotion(config)
    begin = time.perf_counter_ns()
    with patch.object(module, 'current_time', clock.now), patch.object(module, 'logger', QuietLogger()):
        for _ in range(iterations):
            cursor[0] += timedelta(microseconds=120 * US)
            tracker.check_reduce(1)
            tracker.reduce(1)
    elapsed = time.perf_counter_ns() - begin
    fields = copy.deepcopy(config.fields)
    for i in (1, 2):
        fields[f'Emotion_Fleet{i}RecoveryState']['version'] = 1
    digest = hashlib.sha256(json.dumps(fields, default=str, sort_keys=True).encode()).hexdigest()
    return elapsed / iterations / 1000, digest, config.saves


def compare_without_observations(old_class):
    """比较禁用观测时各恢复策略的预测误差。"""
    rng = random.Random(1092026)
    checks = 0
    for recover in ('not_in_dormitory', 'dormitory_floor_1', 'dormitory_floor_2'):
        for oath in (False, True):
            old = old_class.calibrate(90, BASE, recover, oath, False)
            new = EmotionRecoveryState.calibrate(90, BASE, recover, oath, False)
            for _ in range(2000):
                now = old.record + timedelta(microseconds=rng.randrange(900 * US))
                for state in (old, new):
                    state.advance(now)
                    state.consume(2)
                assert old.segments == new.segments
                assert (old.lower, old.upper, old.value) == (new.lower, new.upper, new.value)
                assert old.recovered_at(42) == new.recovered_at(42)
                checks += 1
    return checks


def scan_flow(runner_class, real_ocr=False):
    """执行模拟的舰队扫描与心情观测流程。"""
    counts, actions = Counter(), []
    state = EmotionRecoveryState.calibrate(144, BASE, 'dormitory_floor_2', True, False)
    fields = {'Mode': 'calculate'}
    for i in (1, 2):
        fields.update({f'Fleet{i}{key}': value for key, value in
                       {'Value': 144, 'Record': BASE, 'RecoveryState': state.export(), 'Recover': state.recover,
                        'Oath': True, 'Onsen': False}.items()})
    config = SimpleNamespace(modified={}, data={'Main': {'Emotion': fields, 'Campaign': {'Mode': 'normal'},
                                                         'Fleet': {'Fleet1': 1, 'Fleet2': 2,
                                                                   'FleetOrder': 'fleet1_all_fleet2_standby'}}})

    def save():
        """记录基准测试生成的结果与状态。"""
        counts['save'] += 1
        for path, value in config.modified.items():
            deep_set(config.data, keys=path, value=value)
        json.loads(json.dumps(config.data, default=str))

    config.save = save
    image = load_image('tests/fixtures/fleet_emotion.png') if real_ocr else object()
    device = SimpleNamespace(config=SimpleNamespace(Emulator_ScreenshotMethod='ADB', Error_SaveError=True),
                             image=image, screenshot_deque=deque(maxlen=5))
    cursor, category = [BASE + timedelta(seconds=59)], [0]

    def screenshot():
        """构造基准场景的截图输入。"""
        counts['screenshot'] += 1
        cursor[0] += timedelta(milliseconds=100)
        device.screenshot_deque.append({'time': cursor[0], 'image': image})

    device.screenshot = screenshot
    runner = runner_class.__new__(runner_class)
    runner.config, runner.device = config, device
    runner.dock_filter = SimpleNamespace(reset_first=True)
    for name in ('ui_ensure', 'dock_favourite_set', 'dock_sort_method_dsc_set', 'dock_filter_set', 'dock_reset'):
        def action(*args, _name=name, **kwargs):
            """执行模拟场景中的单步操作。"""
            counts['click'] += 1
            actions.append((_name, repr(args), repr(kwargs)))
        setattr(runner, name, action)

    def wait_loaded():
        """等待测试场景完成预定加载。"""
        # 同一替身在两个版本执行相同的已有加载截图，不模拟新增等待。
        screenshot()
        screenshot()

    runner._wait_dock_filter_loaded = wait_loaded
    heart = FleetEmotionScanner() if real_ocr else None

    class Scanner:
        name_scanner = SimpleNamespace(name_matcher=SimpleNamespace(names=[f'ship{i}' for i in range(6)]))

        def scan(self, frame):
            """采集模拟舰队并返回识别数据。"""
            counts['scan'] += 1
            counts['ocr'] += 3
            points = 150
            if heart is not None:
                points = heart.scan(frame, output=False)[0]
                counts['real_heart_ocr'] += 1
            indices = range(3) if category[0] != 1 else range(3, 6)
            category[0] += 1
            return {1: [{'name': f'ship{i}', 'level': 125, 'emotion': points} for i in indices]}

    with patch.object(fleet_source, 'FleetManagementScanner', Scanner), patch.object(fleet_source, 'logger', QuietLogger()):
        # 旧类有自己的模块全局变量，也替换其中相同的扫描器和日志。
        namespace = sys.modules[runner_class.__module__]
        with patch.object(namespace, 'FleetManagementScanner', Scanner), patch.object(namespace, 'logger', QuietLogger()):
            begin = time.perf_counter_ns()
            runner.run()
            elapsed = (time.perf_counter_ns() - begin) / 1_000_000
    assert counts['save'] == 1
    assert config.data['Main']['Emotion']['Fleet1Value'] == (150 if runner_class is fleet_source.FleetManagement else 144)
    return elapsed, dict(counts), actions


def summary(pairs):
    """汇总基准测试指标和误差分布。"""
    before, after = zip(*pairs)
    differences = [b - a for a, b in pairs]
    rng = random.Random(20261009)
    boot = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
    return {'baseline_median': statistics.median(before), 'current_median': statistics.median(after),
            'paired_delta_median': statistics.median(differences),
            'paired_mean_delta_95pct_bootstrap': [boot[50], boot[1949]], 'pairs': pairs}


def run(ref, pairs, iterations, ocr_pairs):
    """执行心情恢复与观测的基准评估。"""
    old_state = load_baseline(ref, 'module/combat/emotion_state.py', '_emotion_baseline_state')
    old_emotion = load_baseline(ref, 'module/combat/emotion.py', '_emotion_baseline')
    old_emotion.EmotionRecoveryState = old_state.EmotionRecoveryState
    old_fleet = load_baseline(ref, 'module/retire/fleet_management.py', '_fleet_baseline')
    checks = compare_without_observations(old_state.EmotionRecoveryState)
    samples = []
    for i in range(pairs + 2):
        results = {}
        for current in ((False, True) if i % 2 == 0 else (True, False)):
            results[current] = calculate(production if current else old_emotion,
                                         EmotionRecoveryState if current else old_state.EmotionRecoveryState, iterations)
        assert results[False][1:] == results[True][1:], '无观测的正式流程结果或保存次数变化'
        if i >= 2:
            samples.append((results[False][0], results[True][0]))
    plain_samples = []
    for i in range(pairs + 2):
        plain = {}
        for current in ((False, True) if i % 2 == 0 else (True, False)):
            plain[current] = scan_flow(fleet_source.FleetManagement if current else old_fleet.FleetManagement)
        assert plain[False][1:] == plain[True][1:], '点击、截图、OCR、保存次数或顺序发生变化'
        if i >= 2:
            plain_samples.append((plain[False][0] * 1000, plain[True][0] * 1000))
    ocr_samples = []
    for i in range(ocr_pairs + 2):
        results = {}
        for current in ((False, True) if i % 2 == 0 else (True, False)):
            results[current] = scan_flow(fleet_source.FleetManagement if current else old_fleet.FleetManagement, True)
        assert results[False][1:] == results[True][1:]
        if i >= 2:
            ocr_samples.append((results[False][0], results[True][0]))
    return {'baseline_ref': ref, 'no_observation_checks': checks, 'calculation_us_per_battle': summary(samples),
            'scan_without_ocr_us': summary(plain_samples),
            'scan_with_real_heart_ocr_ms': summary(ocr_samples), 'flow_counts': plain[True][1],
            'limitations': '离线设备替身核对操作序列；真实心情OCR用于配对耗时，名称及等级使用夹具；不代表实机速度或所有后端'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--pairs', type=int, default=30)
    parser.add_argument('--iterations', type=int, default=300)
    parser.add_argument('--ocr-pairs', type=int, default=10)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if min(args.pairs, args.iterations, args.ocr_pairs) <= 0:
        parser.error('测试次数必须为正数')
    report = run(args.baseline_ref, args.pairs, args.iterations, args.ocr_pairs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'limitations'}, ensure_ascii=False))
