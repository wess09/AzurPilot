"""扫描阶段计时与有界 OCR 复用，所有设备与模型操作仍在原单路调用链执行。"""
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from time import perf_counter


class ScanMetrics:
    def __init__(self):
        self.seconds = defaultdict(float)
        self.counts = defaultdict(int)
        self.started = perf_counter()
        for stage in ('screenshot', 'drag', 'stability', 'stable_wait', 'displacement', 'name_ocr',
                      'level_prepare', 'level_template', 'level_ocr', 'reread', 'merge', 'save'):
            self.seconds[stage] = 0.

    def wrap(self, func, stage):
        def call(*args, **kwargs):
            with self.measure(stage):
                return func(*args, **kwargs)
        return call

    @contextmanager
    def measure(self, stage):
        start = perf_counter()
        try:
            yield
        finally:
            self.seconds[stage] += perf_counter() - start
            self.counts[stage] += 1

    def snapshot(self):
        return dict(elapsed=round(perf_counter() - self.started, 6),
                    seconds={key: round(value, 6) for key, value in self.seconds.items()}, counts=dict(self.counts))


class MeasuredOcr:
    """记录真实 OCR 提交与字图数，不并发访问共享模型。"""
    def __init__(self, reader, metrics, stage):
        self.reader, self.metrics, self.stage = reader, metrics, stage

    def __getattr__(self, name):
        return getattr(self.reader, name)

    def ocr_for_single_lines(self, images):
        self.metrics.counts[self.stage + '_images'] += len(images)
        with self.metrics.measure(self.stage):
            return self._infer(images)

    def _infer(self, images):
        values = self._execute(self.reader.ocr_for_single_lines, images, stage=self.stage + '_backend')
        self.metrics.counts[self.stage + '_backend_images'] += len(images)
        return values

    def det(self, image):
        return self._execute(self.reader.det, image, stage=self.stage + '_detection')

    def _execute(self, func, *args, stage):
        from module.config.config import TaskEnd
        from module.exception import MindCalculatorScanError
        with self.metrics.measure(stage):
            try:
                return func(*args)
            except (TaskEnd, MindCalculatorScanError):
                raise
            except Exception as exc:
                raise MindCalculatorScanError(f'OCR 识别引擎失败，保留旧清单：{exc}') from exc


class CachedOcr(MeasuredOcr):
    """同一扫描内仅复用字节完全相等的字图，不复用推测身份或其他实例设置。"""
    def __init__(self, reader, metrics, stage, max_entries=256, max_bytes=4 * 1024 * 1024):
        super().__init__(reader, metrics, stage)
        self.cache = OrderedDict()
        self.max_entries, self.max_bytes, self.bytes = max_entries, max_bytes, 0
        self.settings = None

    def ocr_for_single_lines(self, images):
        import numpy as np
        if getattr(self.reader, 'save_debug_images', False):
            return super().ocr_for_single_lines(images)
        settings = self.reader._get_settings() if hasattr(self.reader, '_get_settings') else None
        if settings != self.settings:
            self.cache.clear()
            self.bytes = 0
            self.settings = settings
        self.metrics.counts[self.stage + '_images'] += len(images)
        with self.metrics.measure(self.stage):
            output, pending, keys = [None] * len(images), [], {}
            for index, image in enumerate(images):
                # 字节串本身参与相等比较，不以感知哈希或摘要碰撞推定相同。
                key = (image.dtype.str, image.shape, image.tobytes()) if isinstance(image, np.ndarray) and image.nbytes <= self.max_bytes else None
                if key is not None and key in self.cache:
                    output[index] = self.cache[key]
                    self.cache.move_to_end(key)
                    self.metrics.counts[self.stage + '_hits'] += 1
                elif key is not None and key in keys:
                    keys[key].append(index)
                    self.metrics.counts[self.stage + '_hits'] += 1
                else:
                    pending.append((index, image, key))
                    if key is not None:
                        keys[key] = [index]
            if pending:
                values = self._infer([image for _, image, _ in pending])
                if len(values) != len(pending):
                    raise RuntimeError('OCR 返回数量与输入字图不一致')
                for (index, _, key), value in zip(pending, values):
                    for position in keys[key] if key is not None else (index,):
                        output[position] = value
                    if key is not None and self.max_entries > 0:
                        self.cache[key] = value
                        self.bytes += len(key[2])
                        while len(self.cache) > self.max_entries or self.bytes > self.max_bytes:
                            old, _ = self.cache.popitem(last=False)
                            self.bytes -= len(old[2])
            return output
