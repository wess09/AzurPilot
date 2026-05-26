import atexit
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from rapidocr.ch_ppocr_rec.typings import TextRecOutput
from rapidocr.ch_ppocr_rec.utils import CTCLabelDecode
from rapidocr.utils.load_image import LoadImage
from rapidocr.utils.process_img import resize_image_within_bounds

from module.logger import logger


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = REPO_ROOT / "bin/ocr_models/ncnn"
REC_IMAGE_SHAPE = (3, 48, 320)
INPUT_NAME = "x"


@dataclass(frozen=True)
class NcnnRecModelSpec:
    name: str
    param_path: Path
    bin_path: Path
    keys_path: Path
    output_name: str
    disable_fp16: bool = False


MODEL_SPECS = {
    "en": NcnnRecModelSpec(
        name="en",
        param_path=MODEL_ROOT / "en.param",
        bin_path=MODEL_ROOT / "en.bin",
        keys_path=REPO_ROOT / "bin/ocr_models/en-US/en.txt",
        output_name="Add.227",
        disable_fp16=True,
    ),
    "cn": NcnnRecModelSpec(
        name="cn",
        param_path=MODEL_ROOT / "cn.param",
        bin_path=MODEL_ROOT / "cn.bin",
        keys_path=REPO_ROOT / "bin/ocr_models/zh-CN/cn.txt",
        output_name="Add.227",
    ),
    "jp": NcnnRecModelSpec(
        name="jp",
        param_path=MODEL_ROOT / "jp.param",
        bin_path=MODEL_ROOT / "jp.bin",
        keys_path=REPO_ROOT / "bin/ocr_models/JP/ppocrv5_dict.txt",
        output_name="Add.223",
        disable_fp16=True,
    ),
    "tw": NcnnRecModelSpec(
        name="tw",
        param_path=MODEL_ROOT / "tw.param",
        bin_path=MODEL_ROOT / "tw.bin",
        keys_path=REPO_ROOT / "bin/ocr_models/TW/ppocrv5_dict.txt",
        output_name="Add.223",
        disable_fp16=True,
    ),
}


_ncnn = None
_ncnn_lock = threading.Lock()
_gpu_lock = threading.Lock()
_gpu_instance_created = False


def normalize_model_name(name: str) -> str:
    if name in ("cn", "zhcn"):
        return "cn"
    return name


def supports_ncnn_model(name: str) -> bool:
    return normalize_model_name(name) in MODEL_SPECS


def _load_ncnn():
    global _ncnn
    if _ncnn is not None:
        return _ncnn

    with _ncnn_lock:
        if _ncnn is None:
            try:
                import ncnn
            except ImportError as exc:
                raise RuntimeError(
                    "Python package 'ncnn' is required for OCR recognition."
                ) from exc
            _ncnn = ncnn
    return _ncnn


_gpu_instance_registered = False


def _destroy_gpu_instance():
    """atexit handler: destroy the global ncnn GPU instance cleanly."""
    global _gpu_instance_created, _gpu_instance_registered
    try:
        ncnn = _load_ncnn()
        destroy = getattr(ncnn, "destroy_gpu_instance", None)
        if destroy is not None and _gpu_instance_created:
            destroy()
            _gpu_instance_created = False
    except Exception:
        pass


def _ensure_gpu_instance(ncnn) -> None:
    global _gpu_instance_created, _gpu_instance_registered
    if _gpu_instance_created:
        return

    with _gpu_lock:
        if not _gpu_instance_created:
            create_gpu_instance = getattr(ncnn, "create_gpu_instance", None)
            if create_gpu_instance is not None:
                create_gpu_instance()
                if not _gpu_instance_registered:
                    atexit.register(_destroy_gpu_instance)
                    _gpu_instance_registered = True
            _gpu_instance_created = True


def get_ncnn_vulkan_gpu_count() -> int:
    ncnn = _load_ncnn()
    _ensure_gpu_instance(ncnn)

    get_gpu_count = getattr(ncnn, "get_gpu_count", None)
    if get_gpu_count is None:
        return 0
    return int(get_gpu_count())


def has_ncnn_vulkan_gpu() -> bool:
    try:
        return get_ncnn_vulkan_gpu_count() > 0
    except Exception as e:
        logger.warning(f"ncnn Vulkan GPU detection failed: {e}")
        return False


def _resolve_gpu_index(ncnn, requested_index: int) -> int:
    gpu_count = get_ncnn_vulkan_gpu_count()
    if gpu_count <= 0:
        raise RuntimeError("ncnn Vulkan requested, but no Vulkan GPU was detected.")

    if requested_index < 0:
        get_default_gpu_index = getattr(ncnn, "get_default_gpu_index", None)
        requested_index = get_default_gpu_index() if get_default_gpu_index else 0

    if not 0 <= requested_index < gpu_count:
        raise RuntimeError(
            f"ncnn Vulkan GPU index {requested_index} is out of range; "
            f"detected {gpu_count} GPU(s)."
        )
    return requested_index


def _gpu_info_value(ncnn, gpu_index: int, name: str):
    try:
        info = ncnn.get_gpu_info(gpu_index)
        value = getattr(info, name)
        return value() if callable(value) else value
    except Exception:
        return None


class RecPreprocessor:
    def __init__(self, rec_image_shape: tuple[int, int, int] = REC_IMAGE_SHAPE):
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


class NcnnRecOCR:
    def __init__(self, model_name: str, device: str = "cpu", gpu_index: int = -1):
        normalized_name = normalize_model_name(model_name)
        if normalized_name not in MODEL_SPECS:
            raise ValueError(f"Unsupported ncnn OCR model: {model_name}")

        self.spec = MODEL_SPECS[normalized_name]
        self.device = device
        self.gpu_index = gpu_index
        self.use_vulkan = False
        self.ncnn = _load_ncnn()
        self.preprocess = RecPreprocessor()
        self.load_image = LoadImage()
        self.decoder = CTCLabelDecode(character_path=self.spec.keys_path)
        self.class_count = len(self.decoder.character)
        self.net = None

        self._check_model_files()
        self._create_net()

    def _check_model_files(self) -> None:
        missing = [
            str(path)
            for path in (self.spec.param_path, self.spec.bin_path, self.spec.keys_path)
            if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(
                "Missing ncnn OCR model files: " + ", ".join(missing)
            )

    def _create_net(self) -> None:
        if self.device == "gpu":
            self.gpu_index = _resolve_gpu_index(self.ncnn, self.gpu_index)
            self.use_vulkan = True
        elif self.device == "cpu":
            self.use_vulkan = False
        else:
            raise RuntimeError(f"Unsupported OCR device for ncnn: {self.device}")

        self.net = self.ncnn.Net()
        if hasattr(self.net, "opt"):
            self.net.opt.use_vulkan_compute = self.use_vulkan
            if self.spec.disable_fp16:
                self.net.opt.use_fp16_packed = False
                self.net.opt.use_fp16_storage = False
                self.net.opt.use_fp16_arithmetic = False

        if self.use_vulkan and hasattr(self.net, "set_vulkan_device"):
            self.net.set_vulkan_device(self.gpu_index)

        self._check_return(
            self.net.load_param(str(self.spec.param_path)),
            "load_param",
            self.spec.param_path,
        )
        self._check_return(
            self.net.load_model(str(self.spec.bin_path)),
            "load_model",
            self.spec.bin_path,
        )

        if self.use_vulkan:
            gpu_name = _gpu_info_value(self.ncnn, self.gpu_index, "device_name")
            backend = f"Vulkan GPU {self.gpu_index}"
            if gpu_name:
                backend = f"{backend} ({gpu_name})"
        else:
            backend = "CPU"
        logger.info(f"Loaded ncnn OCR model '{self.spec.name}' on {backend}")

    @staticmethod
    def _check_return(value, op: str, path: Path) -> None:
        if isinstance(value, int) and value != 0:
            raise RuntimeError(f"ncnn {op} failed for {path}, return code {value}")

    def close(self) -> None:
        self.net = None

    def __call__(self, image_or_path) -> TextRecOutput:
        start_time = time.perf_counter()
        img = self.load_image(image_or_path)
        img, _, _ = resize_image_within_bounds(img, 30, 2000)

        norm = self.preprocess.resize_norm_img(img)
        preds = self._infer(norm)
        line_results, _ = self.decoder(preds)
        text = line_results[0][0]

        # The configured output is pre-softmax logits. CTC argmax is identical,
        # but confidence is not calibrated after skipping Softmax for latency.
        score = 1.0 if text else 0.0
        return TextRecOutput(
            imgs=[img],
            txts=(text,),
            scores=(score,),
            word_results=(),
            elapse=time.perf_counter() - start_time,
        )

    def _infer(self, input_arr: np.ndarray) -> np.ndarray:
        if self.net is None:
            raise RuntimeError("ncnn OCR model has been closed")

        ex = self.net.create_extractor()
        mat_in = self._to_ncnn_mat(input_arr)
        ret = ex.input(INPUT_NAME, mat_in)
        if isinstance(ret, int) and ret != 0:
            raise RuntimeError(f"ncnn input('{INPUT_NAME}') failed with code {ret}")

        extracted = ex.extract(self.spec.output_name)
        if isinstance(extracted, tuple):
            status, mat_out = extracted
            if isinstance(status, int) and status != 0:
                raise RuntimeError(
                    f"ncnn extract('{self.spec.output_name}') failed with code {status}"
                )
        else:
            mat_out = extracted

        return self._normalize_output(np.array(mat_out))

    def _to_ncnn_mat(self, input_arr: np.ndarray):
        arr = np.ascontiguousarray(input_arr, dtype=np.float32)
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
            f"{arr.shape}; expected class dimension {self.class_count}."
        )
