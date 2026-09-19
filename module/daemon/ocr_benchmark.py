"""OCR 基准测试工具，用于评估不同 OCR 模型的识别精度和性能。
支持 azur_lane、azur_lane_jp、cn 等模型的批量测试，
通过 Rich 表格输出详细的准确率统计结果。"""

import os
import platform
import shutil
import sys
import time
import cv2
from rich.table import Table
from rich.text import Text

from module.config.config import AzurLaneConfig
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.al_ocr import AlOcr, OcrSettings


class OcrBenchmark:
    # Each entry: (model_name, dataset_prefix, subfolder_name)
    BENCHMARKS = [
        ('azur_lane', 'sets_num', 'sets_num'),
        ('azur_lane_jp', 'sets_azur_lane_jp', 'azur_lane_jp'),
        ('cn', 'sets_zhcn', 'sets_zhcn'),
    ]

    def __init__(self, config, device=None, task=None):
        if isinstance(config, AzurLaneConfig):
            self.config = config
            if task is not None:
                self.config.init_task(task)
        else:
            self.config = AzurLaneConfig(config, task=task)

    def _find_archive(self, prefix):
        for ext in ['.zip', '.tar', '.tar.xz', '.tar.gz']:
            path = f'module/daemon/{prefix}{ext}'
            if os.path.exists(path):
                return path
        return None

    def _load_test_cases(self, extract_dir, subfolder):
        target_val_txt = os.path.join(extract_dir, 'val.txt')
        if not os.path.exists(target_val_txt):
            target_val_txt = os.path.join(extract_dir, subfolder, 'val.txt')
        test_cases = []
        if os.path.exists(target_val_txt):
            val_root = os.path.dirname(target_val_txt)
            with open(target_val_txt, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        img_path = os.path.join(val_root, parts[0])
                        if not os.path.exists(img_path):
                            img_path = os.path.join(val_root, 'imgs', parts[0])
                        test_cases.append((img_path, parts[1]))
        return test_cases

    @staticmethod
    def _rate_speed(avg_ms):
        if avg_ms < 5.0:    return 'Insane Fast', 'bold bright_green'
        if avg_ms < 10.0:   return 'Ultra Fast', 'bright_green'
        if avg_ms < 20.0:   return 'Very Fast', 'green1'
        if avg_ms < 40.0:   return 'Fast', 'yellow'
        if avg_ms < 80.0:   return 'Medium', 'orange1'
        if avg_ms < 150.0:  return 'Slow', 'bright_red'
        if avg_ms < 300.0:  return 'Very Slow', 'red'
        return 'Ultra Slow', 'bold red'

    def _run_single(self, model_name, dataset_prefix, subfolder, use_gpu=None, ocr_device=None):
        logger.hr(f'基准测试: {model_name.upper()} 模型  |  数据集: {dataset_prefix}', level=2)

        # 基准测试只覆盖本次模型快照，不修改调用方配置或重置其他任务的模型。
        if ocr_device is None and use_gpu is not None:
            ocr_device = 'gpu' if use_gpu else 'cpu'
        settings = OcrSettings.from_config(self.config, model_name, device=ocr_device)

        # --- Init model ---
        ocr = AlOcr(name=model_name, settings=settings)
        ocr.init()

        # --- Extract dataset ---
        archive_path = self._find_archive(dataset_prefix)
        extract_dir = f'module/daemon/{dataset_prefix}_temp'

        try:
            if archive_path:
                logger.info(f'[基准测试] 解压 {archive_path} ...')
                if os.path.exists(extract_dir):
                    shutil.rmtree(extract_dir)
                shutil.unpack_archive(archive_path, extract_dir)

            test_cases = self._load_test_cases(extract_dir, subfolder)
            if not test_cases:
                logger.error(f'[{model_name}] 无法加载测试用例，已跳过')
                return None

            logger.info(f'[{model_name}] 已加载 {len(test_cases)} 个测试用例')

            # --- Accuracy ---
            correct = 0
            total = len(test_cases)
            log_step = max(1, total // 20)  # 每 5% 打一次进度

            for idx, (img_input, expected) in enumerate(test_cases, 1):
                try:
                    result = ocr.ocr(img_input)
                    if result.strip().upper() == expected.strip().upper():
                        correct += 1
                    else:
                        name = os.path.basename(img_input)
                        logger.warning(f'失败 [{name}]: 预期 "{expected}", 实际 "{result}"')
                except Exception as e:
                    logger.error(f'[{model_name}] OCR错误 {img_input}: {e}')

                if idx % log_step == 0 or idx == total:
                    pct = idx / total * 100
                    logger.info(f'[{model_name}] 精度进度: {idx}/{total} ({pct:.0f}%)')

            accuracy = (correct / total) * 100 if total > 0 else 0

            if accuracy >= 100.0:
                acc_color = 'bright_green'
            elif accuracy >= 90.0:
                acc_color = 'yellow'
            else:
                acc_color = 'red'

            logger.info(
                f"[{model_name}] Accuracy: [{acc_color}]{accuracy:.2f}% ({correct}/{total})[/{acc_color}]",
                extra={"markup": True}
            )

            # --- Speed ---
            benchmark_img = cv2.imread(test_cases[0][0])
            count = 100

            logger.info(f'[{model_name}] 预热中...')
            for _ in range(3):
                ocr.ocr(benchmark_img)

            logger.info(f'[{model_name}] 运行 {count} 次推理...')
            start = time.time()
            for i in range(1, count + 1):
                try:
                    ocr.ocr(benchmark_img)
                except Exception as e:
                    logger.error(f'[{model_name}] 第 {i} 次迭代错误: {e}')
                    break
                if i % 5 == 0 or i == count:
                    logger.info(f'[{model_name}] 速度进度: {i}/{count}')

            cost = time.time() - start
            avg_ms = cost * 1000 / count if cost > 0 else 0
            rating, rating_color = self._rate_speed(avg_ms)

            logger.info(
                f"[{model_name}] {count} inferences in {cost:.3f}s | avg {avg_ms:.3f} ms | [{rating_color}]{rating}[/{rating_color}]",
                extra={"markup": True}
            )

            return {
                'model': model_name,
                'dataset': dataset_prefix,
                'accuracy': accuracy,
                'correct': correct,
                'total': total,
                'cost': cost,
                'avg_ms': avg_ms,
                'rating': rating,
                'rating_color': rating_color,
                'acc_color': acc_color,
            }

        finally:
            if os.path.exists(extract_dir):
                try:
                    shutil.rmtree(extract_dir)
                except Exception as e:
                    logger.error(f'[基准测试] 清理 {extract_dir} 失败: {e}')

    def run(self):
        logger.hr('OCR基准测试', level=1)

        results = []
        for model_name, dataset_prefix, subfolder in self.BENCHMARKS:
            r = self._run_single(model_name, dataset_prefix, subfolder)
            if r:
                results.append(r)

        # --- Summary ---
        if not results:
            logger.hr('OCR基准测试摘要', level=1)
            logger.error('[基准测试] 未收集到基准测试结果')
            return

        table = Table(show_lines=True)
        table.add_column("Model", header_style="bright_cyan", style="cyan", no_wrap=True)
        table.add_column("Dataset", style="magenta")
        table.add_column("Accuracy", justify="right")
        table.add_column("Avg Time", justify="right")
        table.add_column("Rating")
        table.add_column("Status", justify="center")

        for r in results:
            acc = r['accuracy']
            if acc >= 100.0:
                status = Text("PASS", style="bold bright_green")
            elif acc >= 90.0:
                status = Text("Warning", style="bold yellow")
            else:
                status = Text("Error", style="bold red")

            table.add_row(
                r['model'].upper(),
                r['dataset'],
                Text(f"{acc:.2f}% ({r['correct']}/{r['total']})", style=r['acc_color']),
                f"{r['avg_ms']:.3f} ms",
                Text(r['rating'], style=r['rating_color']),
                status
            )

        logger.hr('OCR基准测试摘要', level=1)
        logger.print(table, justify='center')
        logger.info('[Daemon] 如果您的 Status 显示 Error 或 Warning，请使用 CPU 运行 OCR')

    def run_simple_ocr_benchmark(self):
        """
        Returns:
            str: Best OCR device for this machine.
        """
        logger.hr('简单OCR基准测试', level=1)
        backend = self.config.ocr_backend
        logger.info(f'[基准测试] 后端: {backend}')

        if backend == 'ncnn':
            from module.ocr.ncnn_ocr import has_ncnn_vulkan_gpu
            if not has_ncnn_vulkan_gpu():
                logger.info('[基准测试] 未检测到ncnn Vulkan GPU，使用CPU')
                return 'cpu'
            logger.info('[基准测试] 使用ncnn Vulkan GPU测试OCR...')
            device = 'gpu'
        else:
            # ONNX backend
            if sys.platform == 'darwin' and platform.machine() == 'arm64':
                logger.info('[基准测试] 使用ANE测试OCR...')
                device = 'ane'
            else:
                logger.info('[基准测试] 使用GPU (DirectML) 测试OCR...')
                device = 'gpu'

        res = self._run_single('azur_lane', 'sets_num', 'sets_num', ocr_device=device)

        if res and res['accuracy'] >= 100.0:
            logger.info(f'[基准测试] 使用 {device.upper()} OCR精度为100%，使用 {device.upper()}')
            return device
        else:
            logger.info(f'[基准测试] 使用 {device.upper()} OCR精度不为100%或测试失败，回退到CPU')
            return 'cpu'


def run_ocr_benchmark(config):
    try:
        OcrBenchmark(config, task='OcrBenchmark').run()
        return True
    except RequestHumanTakeover:
        logger.critical('[Daemon] 错误 请求人类接管')
        return False
