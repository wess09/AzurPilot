#!/usr/bin/env python3
"""Benchmark AzurPilot OCR recognition models with ONNX Runtime and ncnn.

This is an experimental tool. It intentionally keeps ncnn optional so the
normal AzurPilot dependency set remains CPU-only on Linux.

Examples:
    # CPU baseline with the current RapidOCR/ONNX path.
    uv run python test/ncnn_ocr_benchmark.py --backend onnx-cpu

    # Convert bundled ONNX recognition models to ncnn param/bin first.
    uv run python test/ncnn_ocr_benchmark.py --convert --backend ncnn-vulkan

    # Compare CPU baseline, ncnn CPU, and ncnn Vulkan.
    uv run python test/ncnn_ocr_benchmark.py --convert --backend all
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import gc
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cv2
import numpy as np
from rapidocr.ch_ppocr_rec.utils import CTCLabelDecode
from rapidocr.main import resize_image_within_bounds
from rapidocr.utils.load_image import LoadImage


@dataclass(frozen=True)
class ModelSpec:
    name: str
    dataset_prefix: str
    dataset_subdir: str
    onnx_path: Path
    keys_path: Path


@dataclass
class PowerSummary:
    sample_sources: dict[str, float] = field(default_factory=dict)
    energy_sources: dict[str, float] = field(default_factory=dict)

    @property
    def watts(self) -> float | None:
        values = [*self.sample_sources.values(), *self.energy_sources.values()]
        if not values:
            return None
        return sum(values)


@dataclass
class BenchResult:
    backend: str
    model: str
    dataset: str
    accuracy: float | None = None
    correct: int = 0
    total: int = 0
    avg_ms: float | None = None
    p50_ms: float | None = None
    p95_ms: float | None = None
    throughput: float | None = None
    power_w: float | None = None
    energy_mj_per_inference: float | None = None
    status: str = "OK"
    note: str = ""
    power: PowerSummary = field(default_factory=PowerSummary)


MODELS = {
    "en": ModelSpec(
        name="en",
        dataset_prefix="sets_num",
        dataset_subdir="sets_num",
        onnx_path=REPO_ROOT / "bin/ocr_models/en-US/alocr-en-us-v2.6.nvc.onnx",
        keys_path=REPO_ROOT / "bin/ocr_models/en-US/en.txt",
    ),
    "cn": ModelSpec(
        name="cn",
        dataset_prefix="sets_zhcn",
        dataset_subdir="sets_zhcn",
        onnx_path=REPO_ROOT / "bin/ocr_models/zh-CN/alocr-zh-cn-v3.dtk.onnx",
        keys_path=REPO_ROOT / "bin/ocr_models/zh-CN/cn.txt",
    ),
}

INPUT_SHAPE = (1, 3, 48, 320)

ATTENTION_SLICE_STARTS = {
    "Slice.3": 0,
    "Slice.4": 1,
    "Slice.5": 2,
    "Slice.8": 0,
    "Slice.9": 1,
    "Slice.10": 2,
}
ATTENTION_SQUEEZES = {
    "Squeeze.2",
    "Squeeze.3",
    "Squeeze.4",
    "Squeeze.5",
    "Squeeze.6",
    "Squeeze.7",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_float(path: Path, scale: float) -> float | None:
    try:
        return float(read_text(path)) / scale
    except (OSError, ValueError):
        return None


class PowerSampler:
    """Collect lightweight Linux power telemetry when sysfs exposes it."""

    def __init__(self, interval: float = 0.05):
        self.interval = interval
        self.sample_paths = self._find_sample_paths()
        self.energy_paths = self._find_energy_paths()
        self._samples: dict[str, list[float]] = {name: [] for name, _ in self.sample_paths}
        self._start_energy: dict[str, float] = {}
        self._end_energy: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time = 0.0
        self._end_time = 0.0

    @staticmethod
    def _find_sample_paths() -> list[tuple[str, Path]]:
        paths: list[tuple[str, Path]] = []
        for hwmon in Path("/sys/class/drm").glob("card*/device/hwmon/hwmon*"):
            card = hwmon.parents[2].name
            for field_name in ("power1_average", "power1_input"):
                path = hwmon / field_name
                if path.is_file():
                    paths.append((f"{card}:{hwmon.name}:{field_name}", path))
                    break
        return paths

    @staticmethod
    def _find_energy_paths() -> list[tuple[str, Path]]:
        paths: list[tuple[str, Path]] = []
        for path in Path("/sys/class/powercap").glob("**/energy_uj"):
            name_path = path.with_name("name")
            name = read_text(name_path) if name_path.is_file() else str(path.parent)
            paths.append((name, path))
        return paths

    def __enter__(self) -> "PowerSampler":
        self._start_time = time.perf_counter()
        self._start_energy = self._read_energy()
        if self.sample_paths:
            self._thread = threading.Thread(target=self._run, name="PowerSampler", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._end_time = time.perf_counter()
        self._end_energy = self._read_energy()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval * 4)

    def _read_energy(self) -> dict[str, float]:
        values = {}
        for name, path in self.energy_paths:
            value = read_float(path, 1_000_000.0)
            if value is not None:
                values[name] = value
        return values

    def _run(self) -> None:
        while not self._stop.is_set():
            for name, path in self.sample_paths:
                value = read_float(path, 1_000_000.0)
                if value is not None:
                    self._samples[name].append(value)
            self._stop.wait(self.interval)

    def summary(self) -> PowerSummary:
        sample_sources = {
            name: statistics.fmean(values)
            for name, values in self._samples.items()
            if values
        }

        elapsed = self._end_time - self._start_time
        energy_sources = {}
        if elapsed > 0:
            for name, start in self._start_energy.items():
                end = self._end_energy.get(name)
                if end is not None and end >= start:
                    energy_sources[name] = (end - start) / elapsed

        return PowerSummary(sample_sources=sample_sources, energy_sources=energy_sources)


class RecPreprocessor:
    def __init__(self, rec_image_shape: tuple[int, int, int] = (3, 48, 320)):
        self.rec_image_shape = rec_image_shape

    def resize_norm_img(self, img: np.ndarray) -> np.ndarray:
        img_channel, img_height, img_width = self.rec_image_shape
        if img.shape[2] != img_channel:
            raise ValueError(f"Expected {img_channel} channels, got {img.shape[2]}")

        h, w = img.shape[:2]
        ratio = w / float(h)
        resized_w = min(img_width, int(math.ceil(img_height * ratio)))

        resized_image = cv2.resize(img, (resized_w, img_height))
        resized_image = resized_image.astype("float32")
        resized_image = resized_image.transpose((2, 0, 1)) / 255.0
        resized_image -= 0.5
        resized_image /= 0.5

        padding_im = np.zeros((img_channel, img_height, img_width), dtype=np.float32)
        padding_im[:, :, :resized_w] = resized_image
        return padding_im


class NcnnRecognizer:
    def __init__(
        self,
        spec: ModelSpec,
        model_dir: Path,
        *,
        vulkan: bool,
        threads: int,
        input_name: str,
        output_name: str,
        input_layout: str,
        gpu_index: int,
        fp16: str,
        packing: str,
    ):
        try:
            import ncnn
        except ImportError as exc:
            raise RuntimeError(
                "Python package 'ncnn' is not installed. Install it separately "
                "for this experiment, then rerun the benchmark."
            ) from exc

        self.ncnn = ncnn
        self.spec = spec
        self.preprocess = RecPreprocessor()
        self.load_image = LoadImage()
        self.decoder = CTCLabelDecode(character_path=spec.keys_path)
        self.input_name = input_name
        self.output_name = output_name
        self.input_layout = input_layout
        self.class_count = len(self.decoder.character)
        self.gpu_index = gpu_index
        self.vulkan = vulkan
        self.fp16 = self._resolve_fp16_mode(fp16)
        self.packing = packing
        self.net = None

        param_path = model_dir / f"{spec.name}.param"
        bin_path = model_dir / f"{spec.name}.bin"
        if not param_path.is_file() or not bin_path.is_file():
            raise FileNotFoundError(
                f"Missing ncnn model files: {param_path} and {bin_path}. "
                "Run with --convert, or provide --ncnn-model-dir containing them."
            )

        if vulkan:
            if hasattr(ncnn, "create_gpu_instance"):
                ncnn.create_gpu_instance()
            get_gpu_count = getattr(ncnn, "get_gpu_count", None)
            gpu_count = get_gpu_count() if get_gpu_count is not None else 0
            if gpu_count <= 0:
                raise RuntimeError("ncnn Vulkan requested, but no Vulkan GPU was detected.")
            if self.gpu_index < 0:
                get_default_gpu_index = getattr(ncnn, "get_default_gpu_index", None)
                self.gpu_index = get_default_gpu_index() if get_default_gpu_index else 0
            if not 0 <= self.gpu_index < gpu_count:
                raise RuntimeError(
                    f"ncnn Vulkan GPU index {self.gpu_index} is out of range; "
                    f"detected {gpu_count} GPU(s)."
                )

        self.net = ncnn.Net()
        if hasattr(self.net, "opt"):
            self.net.opt.use_vulkan_compute = bool(vulkan)
            if threads > 0:
                self.net.opt.num_threads = threads
            if self.fp16 == "off":
                self.net.opt.use_fp16_packed = False
                self.net.opt.use_fp16_storage = False
                self.net.opt.use_fp16_arithmetic = False
            if self.packing == "off":
                self.net.opt.use_packing_layout = False
        if vulkan and hasattr(self.net, "set_vulkan_device"):
            self.net.set_vulkan_device(self.gpu_index)

        self._check_return(self.net.load_param(str(param_path)), "load_param", param_path)
        self._check_return(self.net.load_model(str(bin_path)), "load_model", bin_path)

    @staticmethod
    def _check_return(value, op: str, path: Path) -> None:
        if isinstance(value, int) and value != 0:
            raise RuntimeError(f"ncnn {op} failed for {path}, return code {value}")

    def _resolve_fp16_mode(self, fp16: str) -> str:
        if fp16 != "model":
            return fp16
        return "auto" if self.spec.name == "cn" else "off"

    def close(self) -> None:
        self.net = None
        gc.collect()
        destroy = getattr(self.ncnn, "destroy_gpu_instance", None)
        if self.vulkan and destroy is not None:
            destroy()

    def __call__(self, image_or_path: str | Path | np.ndarray) -> str:
        img = self.load_image(image_or_path)
        img, _, _ = resize_image_within_bounds(img, 30, 2000)

        norm = self.preprocess.resize_norm_img(img)
        input_arr = norm[np.newaxis, :] if self.input_layout == "nchw" else norm
        preds = self._infer(input_arr)
        line_results, _ = self.decoder(preds)
        return line_results[0][0]

    def _infer(self, input_arr: np.ndarray) -> np.ndarray:
        ex = self.net.create_extractor()
        mat_in = self._to_ncnn_mat(input_arr)
        ret = ex.input(self.input_name, mat_in)
        if isinstance(ret, int) and ret != 0:
            raise RuntimeError(f"ncnn input('{self.input_name}') failed with code {ret}")

        extracted = ex.extract(self.output_name)
        if isinstance(extracted, tuple):
            status, mat_out = extracted
            if isinstance(status, int) and status != 0:
                raise RuntimeError(
                    f"ncnn extract('{self.output_name}') failed with code {status}"
                )
        else:
            mat_out = extracted

        return self._normalize_output(np.array(mat_out))

    def _to_ncnn_mat(self, input_arr: np.ndarray):
        arr = np.ascontiguousarray(input_arr, dtype=np.float32)
        if arr.ndim == 4:
            if arr.shape[0] != 1:
                raise ValueError(f"ncnn benchmark only supports batch=1, got {arr.shape}")
            arr = arr[0]
        if arr.ndim != 3:
            raise ValueError(f"Expected CHW input for ncnn, got shape {arr.shape}")

        c, h, w = arr.shape
        mat = self.ncnn.Mat()
        mat.create(w, h, c)
        mat.numpy("f")[...] = arr
        return mat

    def _normalize_output(self, output: np.ndarray) -> np.ndarray:
        arr = np.asarray(output, dtype=np.float32)

        if arr.ndim == 3 and arr.shape[-1] == self.class_count:
            return arr
        if arr.ndim == 2 and arr.shape[-1] == self.class_count:
            return arr[np.newaxis, :, :]
        if arr.ndim == 2 and arr.shape[0] == self.class_count:
            return arr.T[np.newaxis, :, :]
        if arr.ndim == 3 and arr.shape[0] == self.class_count:
            return np.moveaxis(arr, 0, -1).reshape(1, -1, self.class_count)

        raise RuntimeError(
            "Unable to interpret ncnn output shape "
            f"{arr.shape}; expected class dimension {self.class_count}. "
            "Try --input-name/--output-name/--input-layout if conversion renamed blobs."
        )


class OnnxCpuRecognizer:
    def __init__(self, model_name: str):
        from module.ocr.al_ocr import AlOcr

        self.ocr = AlOcr(name=model_name)
        self.ocr.init()

    def __call__(self, image_or_path: str | Path | np.ndarray) -> str:
        return self.ocr.ocr(image_or_path)


def resolve_tool(tool: str) -> str:
    resolved = shutil.which(tool)
    if resolved is None:
        raise RuntimeError(f"Required tool '{tool}' was not found in PATH.")
    return resolved


def simplify_onnx_model(spec: ModelSpec, output_path: Path) -> None:
    try:
        import onnx
        from onnxsim import simplify
    except ImportError as exc:
        raise RuntimeError(
            "ONNX simplification requires 'onnx' and 'onnxsim'. Install them for "
            "the ncnn conversion experiment, then rerun with --convert."
        ) from exc

    model = onnx.load(spec.onnx_path)
    simplified, ok = simplify(model, overwrite_input_shapes={"x": list(INPUT_SHAPE)})
    if not ok:
        raise RuntimeError(f"onnxsim reported that simplification failed for {spec.onnx_path}")
    onnx.save(simplified, output_path)


def patch_alocr_attention(param_path: Path) -> None:
    lines = param_path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"Invalid ncnn param file: {param_path}")

    layer_count, blob_count = (int(value) for value in lines[1].split())
    body, added_layers, added_blobs = patch_alocr_attention_lines(lines[2:])
    lines = [lines[0], f"{layer_count + added_layers} {blob_count + added_blobs}", *body]
    param_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def patch_alocr_attention_lines(lines: list[str]) -> tuple[list[str], int, int]:
    body: list[str] = []
    added_layers = 0
    added_blobs = 0

    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Crop" and parts[1] in ATTENTION_SLICE_STARTS:
            start = ATTENTION_SLICE_STARTS[parts[1]]
            line += f" -23309=1,{start} -23310=1,{start + 1} -23311=1,1"

        if len(parts) >= 2 and parts[0] == "Squeeze" and parts[1] in ATTENTION_SQUEEZES:
            line = line.replace("-23303=1,0", "-23303=1,1")

        if len(parts) >= 2 and parts[0] == "BinaryOp" and parts[1] == "Mul.148":
            body.append(line)
            body.extend(
                [
                    "Reshape                  HeadReshape.0q          1 1 Mul.149 Mul.149.reshape_heads 0=15 1=8 2=-1",
                    "Permute                  HeadPermute.0q          1 1 Mul.149.reshape_heads Mul.149.heads 0=2",
                ]
            )
            added_layers += 2
            added_blobs += 2
            continue

        if len(parts) >= 2 and parts[0] == "BinaryOp" and parts[1] == "Mul.155":
            body.append(line)
            body.extend(
                [
                    "Reshape                  HeadReshape.1q          1 1 Mul.156 Mul.156.reshape_heads 0=15 1=8 2=-1",
                    "Permute                  HeadPermute.1q          1 1 Mul.156.reshape_heads Mul.156.heads 0=2",
                ]
            )
            added_layers += 2
            added_blobs += 2
            continue

        if len(parts) >= 2 and parts[0] == "Squeeze" and parts[1] == "Squeeze.4":
            body.append(line)
            body.extend(
                [
                    "Reshape                  HeadReshape.0v          1 1 p2o.pd_op.slice.3.0 p2o.pd_op.slice.3.0.reshape_heads 0=15 1=8 2=-1",
                    "Permute                  HeadPermute.0v          1 1 p2o.pd_op.slice.3.0.reshape_heads p2o.pd_op.slice.3.0.heads 0=2",
                ]
            )
            added_layers += 2
            added_blobs += 2
            continue

        if len(parts) >= 2 and parts[0] == "Squeeze" and parts[1] == "Squeeze.7":
            body.append(line)
            body.extend(
                [
                    "Reshape                  HeadReshape.1v          1 1 p2o.pd_op.slice.6.0 p2o.pd_op.slice.6.0.reshape_heads 0=15 1=8 2=-1",
                    "Permute                  HeadPermute.1v          1 1 p2o.pd_op.slice.6.0.reshape_heads p2o.pd_op.slice.6.0.heads 0=2",
                ]
            )
            added_layers += 2
            added_blobs += 2
            continue

        if len(parts) >= 2 and parts[0] == "Permute" and parts[1] == "Transpose.2":
            body.append(
                "Reshape                  HeadReshape.0k          1 1 p2o.pd_op.slice.2.0 p2o.pd_op.slice.2.0.reshape_heads 0=15 1=8 2=-1"
            )
            body.append(
                "Permute                  Transpose.2              1 1 p2o.pd_op.slice.2.0.reshape_heads p2o.pd_op.transpose.2.0 0=2"
            )
            added_layers += 1
            added_blobs += 1
            continue

        if len(parts) >= 2 and parts[0] == "Permute" and parts[1] == "Transpose.5":
            body.append(
                "Reshape                  HeadReshape.1k          1 1 p2o.pd_op.slice.5.0 p2o.pd_op.slice.5.0.reshape_heads 0=15 1=8 2=-1"
            )
            body.append(
                "Permute                  Transpose.5              1 1 p2o.pd_op.slice.5.0.reshape_heads p2o.pd_op.transpose.5.0 0=2"
            )
            added_layers += 1
            added_blobs += 1
            continue

        if len(parts) >= 2 and parts[0] == "Gemm" and parts[1] == "MatMul.1":
            body.append(
                "MatMul                   MatMul.1                 2 1 Mul.149.heads p2o.pd_op.transpose.2.0 p2o.pd_op.matmul.1.0 0=1"
            )
            continue

        if len(parts) >= 2 and parts[0] == "Gemm" and parts[1] == "MatMul.2":
            body.append(
                "MatMul                   MatMul.2                 2 1 p2o.pd_op.softmax.0.0 p2o.pd_op.slice.3.0.heads p2o.pd_op.matmul.2.0 0=0"
            )
            continue

        if len(parts) >= 2 and parts[0] == "Gemm" and parts[1] == "MatMul.7":
            body.append(
                "MatMul                   MatMul.7                 2 1 Mul.156.heads p2o.pd_op.transpose.5.0 p2o.pd_op.matmul.7.0 0=1"
            )
            continue

        if len(parts) >= 2 and parts[0] == "Gemm" and parts[1] == "MatMul.8":
            body.append(
                "MatMul                   MatMul.8                 2 1 p2o.pd_op.softmax.1.0 p2o.pd_op.slice.6.0.heads p2o.pd_op.matmul.8.0 0=0"
            )
            continue

        body.append(line)

    if added_layers != 10 or added_blobs != 10:
        raise RuntimeError(
            "Unexpected ncnn param structure while patching AzurPilot OCR attention "
            f"(added_layers={added_layers}, added_blobs={added_blobs})."
        )

    return body, added_layers, added_blobs


def convert_model(spec: ModelSpec, output_dir: Path, onnx2ncnn: str, ncnnoptimize: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    param_path = output_dir / f"{spec.name}.param"
    bin_path = output_dir / f"{spec.name}.bin"

    onnx2ncnn_path = resolve_tool(onnx2ncnn)
    ncnnoptimize_path = resolve_tool(ncnnoptimize)

    with tempfile.TemporaryDirectory(prefix=f"{spec.name}-ncnn-convert-") as temp:
        temp_dir = Path(temp)
        simplified_path = temp_dir / f"{spec.name}.simplified.onnx"
        raw_param_path = temp_dir / f"{spec.name}.raw.param"
        raw_bin_path = temp_dir / f"{spec.name}.raw.bin"
        opt_param_path = temp_dir / f"{spec.name}.param"
        opt_bin_path = temp_dir / f"{spec.name}.bin"

        simplify_onnx_model(spec, simplified_path)
        subprocess.run(
            [onnx2ncnn_path, str(simplified_path), str(raw_param_path), str(raw_bin_path)],
            cwd=REPO_ROOT,
            check=True,
        )
        subprocess.run(
            [ncnnoptimize_path, str(raw_param_path), str(raw_bin_path), str(opt_param_path), str(opt_bin_path), "0"],
            cwd=REPO_ROOT,
            check=True,
        )
        patch_alocr_attention(opt_param_path)
        shutil.copy2(opt_param_path, param_path)
        shutil.copy2(opt_bin_path, bin_path)


def extract_dataset(spec: ModelSpec, work_dir: Path) -> list[tuple[Path, str]]:
    archive = REPO_ROOT / "module/daemon" / f"{spec.dataset_prefix}.tar"
    if not archive.is_file():
        raise FileNotFoundError(f"Missing benchmark archive: {archive}")

    extract_dir = work_dir / spec.dataset_prefix
    with tarfile.open(archive) as tar:
        tar.extractall(extract_dir)

    root = extract_dir / spec.dataset_subdir
    val_path = root / "val.txt"
    if not val_path.is_file():
        raise FileNotFoundError(f"Missing validation labels: {val_path}")

    cases = []
    for line in val_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        name, expected = line.split(None, 1)
        cases.append((root / "imgs" / name, expected))
    return cases


def run_accuracy(
    recognizer: Callable[[Path], str],
    cases: list[tuple[Path, str]],
    limit: int | None,
) -> tuple[int, int]:
    selected = cases[:limit] if limit else cases
    correct = 0
    for image_path, expected in selected:
        actual = recognizer(image_path)
        if actual.strip().upper() == expected.strip().upper():
            correct += 1
    return correct, len(selected)


def run_speed(
    recognizer: Callable[[np.ndarray], str],
    image_path: Path,
    *,
    warmup: int,
    count: int,
    power_interval: float,
) -> tuple[list[float], PowerSummary]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Unable to read image: {image_path}")

    for _ in range(warmup):
        recognizer(image)

    timings = []
    with PowerSampler(interval=power_interval) as sampler:
        for _ in range(count):
            start = time.perf_counter()
            recognizer(image)
            timings.append((time.perf_counter() - start) * 1000.0)
    return timings, sampler.summary()


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percent / 100.0))
    return ordered[index]


def run_one_backend(
    backend: str,
    spec: ModelSpec,
    cases: list[tuple[Path, str]],
    args: argparse.Namespace,
) -> BenchResult:
    result = BenchResult(backend=backend, model=spec.name, dataset=spec.dataset_prefix)
    recognizer = None
    try:
        if backend == "onnx-cpu":
            recognizer = OnnxCpuRecognizer(spec.name)
        elif backend in {"ncnn-cpu", "ncnn-vulkan"}:
            recognizer = NcnnRecognizer(
                spec,
                args.ncnn_model_dir,
                vulkan=backend == "ncnn-vulkan",
                threads=args.threads,
                input_name=args.input_name,
                output_name=args.output_name,
                input_layout=args.input_layout,
                gpu_index=args.gpu_index,
                fp16=args.ncnn_fp16,
                packing=args.ncnn_packing,
            )
        else:
            raise ValueError(f"Unsupported backend: {backend}")

        correct, total = run_accuracy(recognizer, cases, args.accuracy_limit)
        result.correct = correct
        result.total = total
        result.accuracy = correct / total * 100.0 if total else None

        timings, power = run_speed(
            recognizer,
            cases[0][0],
            warmup=args.warmup,
            count=args.count,
            power_interval=args.power_interval,
        )
        result.avg_ms = statistics.fmean(timings)
        result.p50_ms = percentile(timings, 50)
        result.p95_ms = percentile(timings, 95)
        result.throughput = 1000.0 / result.avg_ms if result.avg_ms else None
        result.power = power
        result.power_w = power.watts
        if result.power_w is not None and result.avg_ms is not None:
            result.energy_mj_per_inference = result.power_w * result.avg_ms

    except Exception as exc:
        result.status = "SKIP" if backend.startswith("ncnn") else "ERROR"
        result.note = str(exc)
    finally:
        close = getattr(recognizer, "close", None)
        if close is not None:
            close()

    return result


def expanded_backends(value: str) -> list[str]:
    if value == "all":
        return ["onnx-cpu", "ncnn-cpu", "ncnn-vulkan"]
    return [value]


def result_to_dict(result: BenchResult) -> dict:
    data = asdict(result)
    data["power"] = asdict(result.power)
    return data


def print_table(results: list[BenchResult]) -> None:
    header = (
        "backend",
        "model",
        "accuracy",
        "avg_ms",
        "p95_ms",
        "ips",
        "watts",
        "mJ/inf",
        "status",
    )
    rows = [header]
    for r in results:
        rows.append(
            (
                r.backend,
                r.model,
                "-" if r.accuracy is None else f"{r.accuracy:.2f}% ({r.correct}/{r.total})",
                "-" if r.avg_ms is None else f"{r.avg_ms:.3f}",
                "-" if r.p95_ms is None else f"{r.p95_ms:.3f}",
                "-" if r.throughput is None else f"{r.throughput:.1f}",
                "-" if r.power_w is None else f"{r.power_w:.2f}",
                "-"
                if r.energy_mj_per_inference is None
                else f"{r.energy_mj_per_inference:.2f}",
                r.status,
            )
        )

    widths = [max(len(str(row[i])) for row in rows) for i in range(len(header))]
    for index, row in enumerate(rows):
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
        if index == 0:
            print("  ".join("-" * width for width in widths))

    notes = [r for r in results if r.note]
    if notes:
        print("\nNotes:")
        for r in notes:
            print(f"- {r.backend}/{r.model}: {r.note}")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark bundled OCR recognition models with ONNX CPU and ncnn.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--backend", choices=["all", "onnx-cpu", "ncnn-cpu", "ncnn-vulkan"], default="all")
    parser.add_argument("--models", nargs="+", choices=sorted(MODELS), default=["en", "cn"])
    parser.add_argument("--ncnn-model-dir", type=Path, default=REPO_ROOT / "test/ncnn_models")
    parser.add_argument("--convert", action="store_true", help="Run onnx2ncnn before benchmarking ncnn backends.")
    parser.add_argument("--onnx2ncnn", default="onnx2ncnn", help="onnx2ncnn executable name or path.")
    parser.add_argument("--ncnnoptimize", default="ncnnoptimize", help="ncnnoptimize executable name or path.")
    parser.add_argument("--input-name", default="x", help="ncnn input blob name.")
    parser.add_argument(
        "--output-name",
        default="Add.227",
        help=(
            "ncnn output blob name. The default extracts pre-softmax logits; "
            "use fetch_name_0 to include the final softmax."
        ),
    )
    parser.add_argument("--input-layout", choices=["nchw", "chw"], default="nchw")
    parser.add_argument("--gpu-index", type=int, default=-1, help="ncnn Vulkan GPU index; -1 uses ncnn's default.")
    parser.add_argument(
        "--ncnn-fp16",
        choices=["model", "auto", "off"],
        default="model",
        help="ncnn fp16 policy; model uses fp16 for cn and fp32 for en.",
    )
    parser.add_argument("--ncnn-packing", choices=["auto", "off"], default="auto")
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--accuracy-limit", type=int, default=0, help="0 means all validation samples.")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--power-interval", type=float, default=0.05)
    parser.add_argument("--output-json", type=Path, default=REPO_ROOT / "test/ncnn_ocr_benchmark.json")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    args.ncnn_model_dir = args.ncnn_model_dir.resolve()
    args.output_json = args.output_json.resolve()

    if args.convert:
        for model_name in args.models:
            convert_model(MODELS[model_name], args.ncnn_model_dir, args.onnx2ncnn, args.ncnnoptimize)

    results: list[BenchResult] = []
    with tempfile.TemporaryDirectory(prefix="azurpilot-ncnn-bench-") as temp:
        work_dir = Path(temp)
        for model_name in args.models:
            spec = MODELS[model_name]
            cases = extract_dataset(spec, work_dir)
            for backend in expanded_backends(args.backend):
                if backend.startswith("ncnn") and not (
                    args.ncnn_model_dir / f"{spec.name}.param"
                ).is_file():
                    results.append(
                        BenchResult(
                            backend=backend,
                            model=spec.name,
                            dataset=spec.dataset_prefix,
                            status="SKIP",
                            note=(
                                f"Missing {args.ncnn_model_dir / f'{spec.name}.param'}; "
                                "run with --convert or provide converted ncnn models."
                            ),
                        )
                    )
                    continue
                results.append(run_one_backend(backend, spec, cases, args))

    print_table(results)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps([result_to_dict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {args.output_json}")
    return 0 if all(r.status != "ERROR" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
