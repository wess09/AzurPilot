"""用固定匿名页建立正确实现的阶段基准；耗时不代表真实设备截图和拖动。"""
import argparse
import hashlib
import json
import os
import statistics
import subprocess
from pathlib import Path

import numpy as np
import psutil
from PIL import Image

from module.logger import set_console_logger
from module.ocr.al_ocr import AlOcr, OcrSettings, reset_ocr_model, _get_onnx_model_params
from module.runtime import mind_recognition as recognition
from module.runtime.mind_calculator import calculate, highest_ships
from module.runtime.scan_metrics import MeasuredOcr, ScanMetrics

FIXTURES = ('fleet_tech_amagi', 'fleet_tech_kaga', 'fleet_tech_york', 'fleet_names_vanguard',
            'mind_dock_duplicates', 'mind_dock_stuck')


def sample(repeats, optimized=False):
    settings = OcrSettings('onnx', 'cpu', False, 'standard')
    metrics = ScanMetrics()
    readers = [AlOcr(name=name, settings=settings, save_debug_images=False) for name in ('ppocr_v6', 'azur_lane')]
    if optimized:
        from module.runtime.scan_metrics import CachedOcr
        readers = [CachedOcr(reader, metrics, stage) for reader, stage in zip(readers, ('name_ocr', 'level_ocr'))]
    else:
        readers = [MeasuredOcr(reader, metrics, stage) for reader, stage in zip(readers, ('name_ocr', 'level_ocr'))]
    output = []
    for name in FIXTURES:
        image = Image.open(Path('tests/fixtures') / f'{name}.png').convert('RGB')
        rows = recognition.color_rows(np.array(image))
        for _ in range(repeats):
            with metrics.measure('recognition'):
                cards = recognition.recognize_cards(image, name_ocr=readers[0], level_ocr=readers[1], row_origins=rows, metrics=metrics)
            with metrics.measure('merge'):
                ships = highest_ships([card.ship for card in cards])
                report = calculate(ships)
            metrics.counts['cards'] += len(cards)
            output.append(dict(fixture=name, cards=[dict(ship=card.ship, fleet=card.fleet,
                reliable=card.level_reliable, reads=card.name_reads) for card in cards], report=report))
    result = metrics.snapshot()
    result.update(fingerprint=hashlib.sha256(json.dumps(output, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                  rss=psutil.Process().memory_info().rss, backend='onnx', device='cpu', model='standard',
                  threads=os.environ.get('AZURPILOT_OCR_THREADS', '2'), concurrency=1, repeats=repeats,
                  end_reason='fixed_offline_dataset', device_operations=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--compare', action='store_true')
    args = parser.parse_args()
    set_console_logger(False)
    results = dict(module=recognition.__file__, head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                   source_sha=hashlib.sha256(Path(recognition.__file__).read_bytes()).hexdigest(), fixtures=FIXTURES)
    results['source_files'] = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (
        'module/ocr/al_ocr.py', 'module/runtime/scan_metrics.py', 'module/runtime/mind_identity.py',
        'module/runtime/mind_calculator.py', 'module/runtime/mind_recognition.py', 'module/runtime/mind_level.py',
        'module/runtime/fleet_tech_identity.py', 'assets/ship/dock_battleship_icon.png',
        'assets/ship/dock_battleship_icon_phase.png', 'assets/ship/ship_data.json',
        'assets/ship/dock_level_prefix.png', 'assets/ship/dock_level_digits.png',
        'assets/ship/dock_fleet_label.png', 'assets/ship/dock_fleet_label_gray.png',
        'module/retire/mind_scan.py', 'module/runtime/scan_dock_amount.py',
        'module/device/connection.py', 'module/device/lease.py')}
    variants = ('baseline', 'cached') if args.compare else ('baseline',)
    results['models'] = []
    for name in ('ppocr_v6', 'azur_lane'):
        model_path, keys_path, _ = _get_onnx_model_params(name, OcrSettings('onnx', 'cpu', False, 'standard'))
        results['models'].append(dict(name=name, path=model_path, dictionary=keys_path,
            sha256=hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
            dictionary_sha256=hashlib.sha256(Path(keys_path).read_bytes()).hexdigest()))
    results['cold_kind'] = 'model_cache_cold'
    for variant in variants:
        reset_ocr_model()
        results[variant] = dict(cold=sample(args.repeats, variant == 'cached'), warm=[])
    # 热轮次交错执行，降低后台负载或执行顺序对两种实现的偏置。
    for index in range(args.rounds):
        for variant in variants if index % 2 == 0 else tuple(reversed(variants)):
            results[variant]['warm'].append(sample(args.repeats, variant == 'cached'))
    for variant in variants:
        times = [row['elapsed'] for row in results[variant]['warm']]
        results[variant].update(median=statistics.median(times), spread=max(times) - min(times))
        Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.compare:
        fingerprints = {row['fingerprint'] for variant in ('baseline', 'cached')
                        for row in [results[variant]['cold'], *results[variant]['warm']]}
        if len(fingerprints) != 1:
            raise RuntimeError('优化前后身份、等级、费用或原始读数不同，基准拒绝通过')
    print(json.dumps({key: dict(median=value['median'], spread=value['spread']) for key, value in results.items()
                      if isinstance(value, dict) and 'median' in value}, ensure_ascii=False))


if __name__ == '__main__':
    main()
