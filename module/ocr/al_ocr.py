"""AlOcr 文字识别引擎。

基于 RapidOCR 框架的多后端 OCR 系统，支持：
- ONNX Runtime 推理（默认），支持 DirectML (Windows GPU) 和 CoreML (macOS ANE) 加速
- NCNN 推理，推理速度更快但模型覆盖较窄
- Windows ML 设备选择，精确控制 GPU/CPU 推理设备

统一使用通用 PP-OCRv6 识别模型，所有语言共用同一套模型与字典。
不同语言通过配置项映射到同一模型版本。

工作线程模型：
- OCR 推理在专用后台线程 (AlOcrQueue) 中执行，避免阻塞主循环
- 模型使用懒加载策略，首次使用时才初始化
- 模型缓存按 (名称, 后端, 设备, 版本) 组合键管理

检测模型：
- 使用 PP-OCRv6 tiny 检测模型定位文本区域
- 检测+识别流水线在 ncnn 和 ONNX 后端有不同实现
"""

import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

from module.exception import RequestHumanTakeover
from module.logger import logger
from module.config.config import AzurLaneConfig, resolve_ocr_device
from module.config.utils import DEFAULT_CONFIG_NAME
from module.ocr.windows_ml import create_onnx_session


def handle_ocr_error(e):
    """处理 OCR 依赖加载失败的统一错误处理。

    打印详细的故障排除指引，包括：
    - 安装微软 C++ 运行库
    - 关闭 GPU 加速
    - 获取社区支持

    Args:
        e (Exception): 原始异常。

    Raises:
        RequestHumanTakeover: 始终抛出，需要用户手动干预。
    """
    logger.critical(f"加载OCR依赖失败: {e}")
    logger.critical(
        "[OCR] 无法加载 OCR 依赖，请安装微软 C++ 运行库 https://aka.ms/vs/17/release/vc_redist.x64.exe"
    )
    logger.critical("[OCR] 也有可能是 GPU 不支持加速引起，请尝试关闭 GPU 加速")
    logger.critical("[OCR] 如果上述方法都无法解决，请加群获取支持")
    raise RequestHumanTakeover


try:
    from rapidocr import RapidOCR, OCRVersion
    from rapidocr.utils.output import RapidOCROutput
    from rapidocr.ch_ppocr_rec import TextRecognizer
    from rapidocr.cal_rec_boxes import CalRecBoxes
    from rapidocr.ch_ppocr_det import TextDetector, TextDetOutput
    from rapidocr.utils.load_image import LoadImage
    from rapidocr.utils.process_img import get_rotate_crop_image
    from module.ocr.ncnn_ocr import NcnnRecOCR, supports_ncnn_model
except Exception as e:
    handle_ocr_error(e)


DET_DEBUG = False
REPO_ROOT = Path(__file__).resolve().parents[2]
OCR_MODEL_VERSION_AUTO = 'auto'

# PP-OCRv6 三档模型：lite(tiny) / standard(small) / pro(medium)。
# lite 的类别数(6906)与 standard/pro(18710) 不同，字典需分别对齐。
PPOCR_V6_LITE_MODEL = "bin/ocr_models/ppocr-v6/PP-OCRv6_tiny_rec.onnx"
PPOCR_V6_STANDARD_MODEL = "bin/ocr_models/ppocr-v6/PP-OCRv6_small_rec.onnx"
PPOCR_V6_PRO_MODEL = "bin/ocr_models/ppocr-v6/PP-OCRv6_medium_rec.onnx"
PPOCR_V6_FULL_DICT = "bin/ocr_models/ppocr-v6/ppocrv6_dict.txt"
PPOCR_V6_TINY_DICT = "bin/ocr_models/ppocr-v6/ppocrv6_tiny_dict.txt"
# azur_lane 逻辑模型使用受限 en 字典（仅数字/字母/符号，其余类别留空），
# 将非 en 输出静默过滤，避免误识别出中文等无关内容。
PPOCR_V6_EN_RESTRICTED_DICT = "bin/ocr_models/ppocr-v6/ppocrv6_en_restricted_dict.txt"
PPOCR_V6_TINY_EN_RESTRICTED_DICT = "bin/ocr_models/ppocr-v6/ppocrv6_tiny_en_restricted_dict.txt"

# 旧版 AlOCR 专用模型（从 git 历史恢复，仅 ONNX 后端可用）。
# alocr_en_v2_6 为英文数字/字母识别模型（PP-OCRv4 结构），
# alocr_cn_v3 为简体中文识别模型（PP-OCRv5 结构）。
ALOCR_EN_V2_6_MODEL = "bin/ocr_models/azur_lane/alocr-en-us-v2.6.nvc.onnx"
ALOCR_EN_DICT = "bin/ocr_models/azur_lane/en_dict.txt"
ALOCR_CN_V3_MODEL = "bin/ocr_models/zh-CN/alocr-zh-cn-v3.dtk.onnx"
ALOCR_CN_DICT = "bin/ocr_models/zh-CN/cn.txt"

# 各逻辑模型的三档参数。azur_lane/azur_lane_jp 使用受限 en 字典，
# 其余使用完整字典。
ONNX_MODEL_PARAMS = {
    "azur_lane": {
        "lite": (PPOCR_V6_LITE_MODEL, PPOCR_V6_TINY_EN_RESTRICTED_DICT, OCRVersion.PPOCRV6),
        "standard": (PPOCR_V6_STANDARD_MODEL, PPOCR_V6_EN_RESTRICTED_DICT, OCRVersion.PPOCRV6),
        "pro": (PPOCR_V6_PRO_MODEL, PPOCR_V6_EN_RESTRICTED_DICT, OCRVersion.PPOCRV6),
        "alocr_en_v2_6": (ALOCR_EN_V2_6_MODEL, ALOCR_EN_DICT, OCRVersion.PPOCRV4),
    },
    "azur_lane_jp": {
        "lite": (PPOCR_V6_LITE_MODEL, PPOCR_V6_TINY_EN_RESTRICTED_DICT, OCRVersion.PPOCRV6),
        "standard": (PPOCR_V6_STANDARD_MODEL, PPOCR_V6_EN_RESTRICTED_DICT, OCRVersion.PPOCRV6),
        "pro": (PPOCR_V6_PRO_MODEL, PPOCR_V6_EN_RESTRICTED_DICT, OCRVersion.PPOCRV6),
    },
    "ppocr_v6": {
        "lite": (PPOCR_V6_LITE_MODEL, PPOCR_V6_TINY_DICT, OCRVersion.PPOCRV6),
        "standard": (PPOCR_V6_STANDARD_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
        "pro": (PPOCR_V6_PRO_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
    },
    "cn": {
        "lite": (PPOCR_V6_LITE_MODEL, PPOCR_V6_TINY_DICT, OCRVersion.PPOCRV6),
        "standard": (PPOCR_V6_STANDARD_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
        "pro": (PPOCR_V6_PRO_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
        "alocr_cn_v3": (ALOCR_CN_V3_MODEL, ALOCR_CN_DICT, OCRVersion.PPOCRV5),
    },
    "jp": {
        "lite": (PPOCR_V6_LITE_MODEL, PPOCR_V6_TINY_DICT, OCRVersion.PPOCRV6),
        "standard": (PPOCR_V6_STANDARD_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
        "pro": (PPOCR_V6_PRO_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
    },
    "tw": {
        "lite": (PPOCR_V6_LITE_MODEL, PPOCR_V6_TINY_DICT, OCRVersion.PPOCRV6),
        "standard": (PPOCR_V6_STANDARD_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
        "pro": (PPOCR_V6_PRO_MODEL, PPOCR_V6_FULL_DICT, OCRVersion.PPOCRV6),
    },
}

DEFAULT_ONNX_MODEL_VERSION = {
    "azur_lane": "alocr_en_v2_6",
    "azur_lane_jp": "standard",
    "ppocr_v6": "standard",
    "cn": "alocr_cn_v3",
    "jp": "standard",
    "tw": "standard",
}


class RecOnlyOCR(RapidOCR):
    """只加载识别模型，跳过 det 和 cls 的 ONNX 模型加载。

    碧蓝航线的 OCR 场景中，文本位置通常固定（已通过 Button 区域裁剪），
    不需要文本检测模型，仅需识别模型即可。跳过检测模型可节省约 10MB 内存
    和加载时间。
    """

    def _initialize(self, cfg):
        self.text_score = cfg.Global.text_score
        self.min_height = cfg.Global.min_height
        self.width_height_ratio = cfg.Global.width_height_ratio

        self.use_det = False
        self.text_det = None

        self.use_cls = False
        self.text_cls = None

        self.use_rec = cfg.Global.use_rec
        cfg.Rec.engine_cfg = cfg.EngineConfig[cfg.Rec.engine_type.value]
        cfg.Rec.font_path = cfg.Global.font_path
        cfg.Rec.model_root_dir = cfg.Global.get("model_root_dir", os.getcwd())
        self.text_rec = TextRecognizer(cfg.Rec)

        self.load_img = LoadImage()
        self.max_side_len = cfg.Global.max_side_len
        self.min_side_len = cfg.Global.min_side_len

        self.cal_rec_boxes = CalRecBoxes()
        self.return_word_box = cfg.Global.return_word_box
        self.return_single_char_box = cfg.Global.return_single_char_box
        self.cfg = cfg


_default_config = None
_default_config_name = None


def _get_default_config():
    """仅在 OCR 工作线程首次使用默认实例时读取配置。"""
    global _default_config, _default_config_name
    config_name = os.environ.get("ALAS_CONFIG_NAME") or DEFAULT_CONFIG_NAME
    if _default_config is None or _default_config_name != config_name:
        _default_config = AzurLaneConfig(config_name)
        _default_config_name = config_name
    return _default_config


class _OcrJob:
    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result = None
        self.exc_info = None

    def run(self):
        try:
            self.result = self.func(*self.args, **self.kwargs)
        except BaseException as e:
            self.exc_info = (e, e.__traceback__)
        finally:
            self.done.set()


_ocr_queue = queue.Queue()
_ocr_worker = None
_ocr_worker_lock = threading.Lock()
_ocr_worker_ident = None


def _ocr_worker_loop():
    global _ocr_worker_ident
    _ocr_worker_ident = threading.get_ident()
    while True:
        job = _ocr_queue.get()
        try:
            job.run()
        finally:
            _ocr_queue.task_done()


def _ensure_ocr_worker():
    global _ocr_worker
    with _ocr_worker_lock:
        if _ocr_worker is None or not _ocr_worker.is_alive():
            _ocr_worker = threading.Thread(
                target=_ocr_worker_loop,
                name='AlOcrQueue',
                daemon=True,
            )
            _ocr_worker.start()


def _run_ocr_queued(func, *args, **kwargs):
    if threading.get_ident() == _ocr_worker_ident:
        return func(*args, **kwargs)

    _ensure_ocr_worker()
    job = _OcrJob(func, args, kwargs)
    _ocr_queue.put(job)
    job.done.wait()

    if job.exc_info is not None:
        exc, traceback = job.exc_info
        raise exc.with_traceback(traceback)
    return job.result


def _resolve_onnx_model_version(name, requested):
    specs = ONNX_MODEL_PARAMS.get(name)
    if specs is None:
        raise ValueError(f"Unsupported OCR model: {name}")

    if requested == OCR_MODEL_VERSION_AUTO:
        return DEFAULT_ONNX_MODEL_VERSION[name]
    if requested in specs:
        return requested

    fallback = DEFAULT_ONNX_MODEL_VERSION[name]
    logger.warning(
        f"OCR model version '{requested}' is not available for '{name}', "
        f"using '{fallback}'"
    )
    return fallback


@dataclass(frozen=True)
class OcrSettings:
    """单个逻辑模型的有效配置，缓存和模型工厂共用同一份不可变快照。"""

    backend: str
    device: str
    allow_vendor_execution_providers: bool
    model_version: str

    @classmethod
    def from_config(cls, config, name, *, device=None):
        backend = config.ocr_backend
        version = _resolve_onnx_model_version(name, config.ocr_model_version(name))
        # NCNN 仅提供三档 PP-OCRv6，旧版 AlOCR 选择按既有行为回退到 standard。
        if backend == 'ncnn' and version not in {'lite', 'standard', 'pro'}:
            version = 'standard'
        return cls(
            backend=backend,
            device=config.ocr_device if device is None else resolve_ocr_device(backend, device),
            allow_vendor_execution_providers=config.Optimization_OcrWindowsMlVendorEp,
            model_version=version,
        )


def _get_onnx_model_params(name, settings):
    """
    按配置选择 ONNX 识别模型版本。

    Args:
        name: 模型名称，如 'azur_lane'、'azur_lane_jp'、'ppocr_v6'、'cn'、'jp'、'tw'。

    Returns:
        (model_path, rec_keys_path, ocr_version) 三元组。
    """
    return ONNX_MODEL_PARAMS[name][settings.model_version]


def _configure_windows_ml_sessions(
    ocr,
    model_paths,
    ocr_device,
    allow_vendor_execution_providers,
):
    """将 RapidOCR 创建的 CPU session 替换为 Windows ML 精确选定的设备。"""
    if os.name != 'nt':
        return ocr

    try:
        import onnxruntime as ort
    except Exception as exc:
        handle_ocr_error(exc)

    for config_name, component_name, model_path in model_paths:
        component = getattr(ocr, component_name)
        ort_session = component.session
        engine_config = getattr(ocr.cfg, config_name).engine_cfg
        session_options_factory = lambda: ort_session._init_sess_opts(engine_config)
        ort_session.session, _ = create_onnx_session(
            ort,
            model_path,
            session_options_factory=session_options_factory,
            allow_acceleration=ocr_device != 'cpu',
            allow_vendor_execution_providers=allow_vendor_execution_providers,
            device_preference=ocr_device,
        )

    return ocr


def _create_ocr(name, settings):
    backend = settings.backend
    if backend == 'ncnn':
        if not supports_ncnn_model(name):
            raise ValueError(f"Unsupported ncnn OCR model: {name}")
        logger.info("[OCR] OCR后端为ncnn，使用ncnn专用识别模型")
        return NcnnRecOCR(name, device=settings.device, version=settings.model_version)
    else:
        ocr_device = settings.device
        allow_vendor_execution_providers = settings.allow_vendor_execution_providers
        # Windows 下由 Windows ML 显式选择设备，不能交给 RapidOCR 默认 DirectML。
        use_dml = False
        use_coreml = ocr_device == 'ane'

        model_path, rec_keys_path, ocr_version = _get_onnx_model_params(name, settings)
        params = {
            # rapidocr 3.9.0 的 _load_config 在 model_root_dir 为 None 时写入 Path
            # 对象，omegaconf 不支持而抛 UnsupportedValueType，显式传字符串规避
            "Global.model_root_dir": os.getcwd(),
            "Global.use_det": False,
            "Global.use_cls": False,
            "Det.model_path": None,
            "Cls.model_path": None,
            "Rec.ocr_version": ocr_version,
            "Rec.model_path": model_path,
            "Rec.rec_keys_path": rec_keys_path,
            "EngineConfig.onnxruntime.use_dml": use_dml,
            "EngineConfig.onnxruntime.use_coreml": use_coreml,
            "EngineConfig.onnxruntime.coreml_ep_cfg.MLComputeUnits": "CPUAndNeuralEngine",
        }
        ocr = RecOnlyOCR(params=params)
        return _configure_windows_ml_sessions(
            ocr,
            [('Rec', 'text_rec', model_path)],
            ocr_device,
            allow_vendor_execution_providers,
        )


# 懒加载：模块级不再创建模型，首次 init() 时才加载
_model_cache = {}


def _model_cache_key(name, settings):
    return name, settings


def _get_model(name, settings):
    key = _model_cache_key(name, settings)
    if key not in _model_cache:
        _model_cache[key] = _create_ocr(name, settings)
    return _model_cache[key]


DET_MODEL_PATH = "bin/ocr_models/det/PP-OCRv6_tiny_det.onnx"

_det_model_cache = {}


class DetOnlyOCR(RapidOCR):
    """仅加载 RapidOCR 检测模型，识别部分由 ncnn 处理。

    在 ncnn 后端模式下，文本检测使用 ONNX 的 PP-OCRv6 tiny 检测模型，
    而文本识别使用 ncnn 的识别模型。此类封装了这种混合模式的检测端。
    """

    def _initialize(self, cfg):
        self.text_score = cfg.Global.text_score
        self.min_height = cfg.Global.min_height
        self.width_height_ratio = cfg.Global.width_height_ratio

        self.use_det = True
        cfg.Det.engine_cfg = cfg.EngineConfig[cfg.Det.engine_type.value]
        cfg.Det.model_root_dir = cfg.Global.get("model_root_dir", os.getcwd())
        self.text_det = TextDetector(cfg.Det)

        self.use_cls = False
        self.text_cls = None

        self.use_rec = False
        self.text_rec = None

        self.load_img = LoadImage()
        self.max_side_len = cfg.Global.max_side_len
        self.min_side_len = cfg.Global.min_side_len
        self.return_word_box = False
        self.return_single_char_box = False
        self.cfg = cfg


def _create_det_ocr_for_onnx(name, settings):
    """为 ONNX 后端创建完整的 RapidOCR 实例（检测 + 识别）。"""
    ocr_device = settings.device
    allow_vendor_execution_providers = settings.allow_vendor_execution_providers
    # Windows 下由 Windows ML 显式选择设备，不能交给 RapidOCR 默认 DirectML。
    use_dml = False
    use_coreml = ocr_device == 'ane'
    model_path, rec_keys_path, ocr_version = _get_onnx_model_params(name, settings)
    params = {
        "Global.model_root_dir": os.getcwd(),
        "Global.use_det": True,
        "Global.use_cls": False,
        "Det.model_path": DET_MODEL_PATH,
        "Cls.model_path": None,
        "Rec.ocr_version": ocr_version,
        "Rec.model_path": model_path,
        "Rec.rec_keys_path": rec_keys_path,
        "EngineConfig.onnxruntime.use_dml": use_dml,
        "EngineConfig.onnxruntime.use_coreml": use_coreml,
        "EngineConfig.onnxruntime.coreml_ep_cfg.MLComputeUnits": "CPUAndNeuralEngine",
    }
    ocr = RapidOCR(params=params)
    return _configure_windows_ml_sessions(
        ocr,
        [
            ('Det', 'text_det', DET_MODEL_PATH),
            ('Rec', 'text_rec', model_path),
        ],
        ocr_device,
        allow_vendor_execution_providers,
    )


def _create_det_ocr_for_ncnn():
    """为 ncnn 后端创建 DetOnlyOCR 实例。"""
    params = {
        "Global.model_root_dir": os.getcwd(),
        "Global.use_det": True,
        "Global.use_cls": False,
        "Global.use_rec": False,
        "Det.model_path": DET_MODEL_PATH,
        "Cls.model_path": None,
        "Rec.model_path": None,
    }
    return DetOnlyOCR(params=params)


def _get_det_model(name, settings):
    """
    获取检测模型。

    Args:
        name: 语言名称。ONNX 后端按语言缓存，ncnn 后端共享单一实例。
    """
    backend = settings.backend
    if backend == 'ncnn':
        # NCNN 混合模式的检测端仍为固定的 ONNX CPU 模型，与识别版本无关。
        key = ('det', settings.backend, settings.device, settings.allow_vendor_execution_providers)
        if key not in _det_model_cache:
            _det_model_cache[key] = _create_det_ocr_for_ncnn()
        return _det_model_cache[key]
    else:
        key = _model_cache_key(name, settings)
        if key not in _det_model_cache:
            _det_model_cache[key] = _create_det_ocr_for_onnx(name, settings)
        return _det_model_cache[key]


def release_ocr_models(names=None):
    """在 OCR 工作线程中释放指定模型的全局缓存。"""
    names = None if names is None else set(names)

    def _release():
        released = 0
        for cache in (_model_cache, _det_model_cache):
            keys = [key for key in cache if names is None or key[0] in names]
            for key in keys:
                model = cache.pop(key)
                close = getattr(model, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception as exc:
                        logger.warning("关闭 OCR 模型缓存失败: %s", exc)
                released += 1

        if released:
            logger.info("已释放 %s 个 OCR 模型缓存", released)
        return released

    return _run_ocr_queued(_release)


def reset_ocr_model():
    logger.info("重置 OCR 模型")

    def _reset():
        global _default_config, _default_config_name
        released = release_ocr_models()
        # 默认实例下次使用时重读已保存的设置，显式传入的配置不受影响。
        _default_config = None
        _default_config_name = None
        return released

    return _run_ocr_queued(_reset)


class AlOcr:
    """统一的 OCR 识别接口。

    封装了 ONNX 和 ncnn 两种后端的识别和检测功能，提供一致的 API。
    所有 OCR 推理操作在专用后台线程中执行，避免阻塞主事件循环。

    支持的操作：
    - ocr(): 单行文本识别（已裁剪的文本图像）
    - det(): 文本检测 + 识别（完整图像，返回带位置坐标的结果）
    - ocr_for_single_lines(): 批量单行文本识别

    Attributes:
        name (str): 模型名称，如 'azur_lane'、'cn'、'jp'、'tw'。
        model: 识别模型实例（懒加载）。
        _det_model: 检测模型实例（懒加载）。
    """
    def __init__(self, *, config=None, settings=None, **kwargs):
        """可传入当前配置或固定设置；省略时在首次使用时读取默认配置。"""
        if config is not None and settings is not None:
            raise ValueError('config 和 settings 不能同时指定')
        self._config = config
        self._settings = settings
        self.model = None
        self.name = kwargs.get("name", "en")
        self.params = {}
        self._det_model = None
        logger.info(
            f"Created AlOcr instance: name='{self.name}', kwargs={kwargs}, PID={os.getpid()}"
        )

    def init(self):
        _run_ocr_queued(self._ensure_loaded)

    def _get_settings(self):
        if self._settings is not None:
            return self._settings
        config = self._config if self._config is not None else _get_default_config()
        return OcrSettings.from_config(config, self.name)

    def _ensure_loaded(self, settings=None):
        settings = self._get_settings() if settings is None else settings
        # 获取、使用和释放都在同一工作线程，重置后不能继续使用实例上的旧引用。
        self.model = _get_model(self.name, settings)

    def _ensure_det_loaded(self, settings=None):
        settings = self._get_settings() if settings is None else settings
        self._det_model = _get_det_model(self.name, settings)

    def _save_debug_image(self, img, result):
        folder = "ocr_debug"
        if not os.path.exists(folder):
            os.makedirs(folder)

        # 获取当前时间用于文件名唯一性和排序
        import time

        now = int(time.time() * 1000)
        # 清理结果文本用于文件名
        res_clean = str(result).replace("\n", " ").replace("\r", " ").strip()
        # 移除无效文件名字符，仅保留安全字符
        res_clean = "".join(
            [c for c in res_clean if c.isalnum() or c in (" ", "_", "-")]
        ).strip()
        if not res_clean:
            res_clean = "empty"

        filename = f"{self.name}_{res_clean}_{now}.png"
        filepath = os.path.join(folder, filename)

        try:
            if isinstance(img, np.ndarray):
                cv2.imwrite(filepath, img)
            elif isinstance(img, Image.Image):
                img.save(filepath)
            elif isinstance(img, str) and os.path.exists(img):
                import shutil

                shutil.copy(img, filepath)

            # 限制文件数量为 100
            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f))
            ]
            if len(files) > 100:
                files.sort(key=os.path.getmtime)
                # 保留最新的 100 个文件
                for f in files[:-100]:
                    try:
                        os.remove(f)
                    except:
                        pass
        except Exception as e:
            # 不应因调试图片保存失败而崩溃主进程
            logger.warning(f"保存OCR调试图像失败: {e}")

    def _ocr_direct(self, img_fp):
        logger.debug(f"[VERBOSE] AlOcr.ocr: Ensure loaded...")
        self._ensure_loaded()

        try:
            res = self.model(img_fp)
            txt = ""
            if hasattr(res, "txts") and res.txts:
                txt = res.txts[0]

            self._save_debug_image(img_fp, txt)
            return txt
        except Exception as e:
            logger.error(f"AlOcr.ocr异常: {e}")
            raise

    def ocr(self, img_fp):
        return _run_ocr_queued(self._ocr_direct, img_fp)

    def _det_direct(self, img_fp):
        settings = self._get_settings()
        self._ensure_loaded(settings)
        self._ensure_det_loaded(settings)

        try:
            if settings.backend == 'ncnn':
                det_res = self._det_model(img_fp, use_det=True, use_cls=False, use_rec=False)
                if not isinstance(det_res, TextDetOutput) or det_res.boxes is None:
                    return []

                img = self.model.load_image(img_fp)
                results = []
                for box in det_res.boxes:
                    crop = get_rotate_crop_image(img, np.asarray(box, dtype=np.float32))
                    rec_res = self.model(crop)
                    if not getattr(rec_res, "txts", None):
                        continue

                    txt = rec_res.txts[0]
                    if not txt.strip():
                        continue

                    score = rec_res.scores[0] if getattr(rec_res, "scores", None) else 1.0
                    results.append((txt, box.tolist(), float(score)))

                if DET_DEBUG:
                    self._save_det_debug(img_fp, results)

                return results
            else:
                # ONNX：完整 RapidOCR 流水线（检测 + 识别一次调用）
                res = self._det_model(img_fp, use_det=True, use_rec=True)
                if isinstance(res, RapidOCROutput) and res.boxes is not None:
                    results = []
                    txts = res.txts if res.txts is not None else ("",) * len(res.boxes)
                    scores = res.scores if res.scores is not None else (0.0,) * len(res.boxes)
                    for box, txt, score in zip(res.boxes, txts, scores):
                        results.append((txt, box.tolist(), float(score)))

                    if DET_DEBUG:
                        self._save_det_debug(img_fp, results)

                    return results
                return []
        except Exception as e:
            logger.error(f"AlOcr.det异常: {e}")
            raise

    def _save_det_debug(self, img, results):
        import cv2 as cv
        import time
        from PIL import Image as PILImage

        # 根据需要转换为 numpy 数组
        if isinstance(img, PILImage.Image):
            img = np.array(img.convert("RGB"))
            img = cv.cvtColor(img, cv.COLOR_RGB2BGR)
        elif isinstance(img, str):
            img = cv.imread(img)
            if img is None:
                return

        if not isinstance(img, np.ndarray):
            return

        draw = img.copy()
        for txt, box, score in results:
            pts = np.array(box, dtype=np.int32).reshape((-1, 1, 2))
            cv.polylines(draw, [pts], True, (0, 255, 0), 2)
            cx, cy = int(sum(p[0] for p in box) / len(box)), int(sum(p[1] for p in box) / len(box))
            label = f"{txt} {score:.2f}"
            cv.putText(draw, label, (cx - 20, cy - 10),
                       cv.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

        folder = "ocr_debug"
        os.makedirs(folder, exist_ok=True)
        now = int(time.time() * 1000)
        filename = f"det_{self.name}_{now}.png"
        filepath = os.path.join(folder, filename)
        cv.imwrite(filepath, draw)

        # 限制文件数量为 100
        files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".png")]
        if len(files) > 100:
            files.sort(key=os.path.getmtime)
            for f in files[:-100]:
                try:
                    os.remove(f)
                except Exception:
                    pass

    def det(self, img_fp):
        """
        运行文本检测 + 识别，返回带位置坐标的结果。

        Args:
            img_fp: 图像输入（numpy 数组、PIL Image 或文件路径字符串）。

        Returns:
            (text, box, score) 元组列表：
                - text (str): 识别文本。
                - box (list): 4 个角点 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]。
                - score (float): 置信度分数 (0.0-1.0)。
            未检测到内容时返回空列表。
        """
        return _run_ocr_queued(self._det_direct, img_fp)

    def ocr_for_single_line(self, img_fp):
        return self.ocr(img_fp)

    def _ocr_for_single_lines_direct(self, img_list):
        self._ensure_loaded()
        results = []
        for i, img in enumerate(img_list):
            try:
                res = self.model(img)
                txt = ""
                if hasattr(res, "txts") and res.txts:
                    txt = res.txts[0]

                results.append(txt)
                self._save_debug_image(img, txt)
            except Exception as e:
                logger.error(f"AlOcr.ocr_for_single_lines exception on image {i}: {e}")
                raise
        return results

    def ocr_for_single_lines(self, img_list):
        return _run_ocr_queued(self._ocr_for_single_lines_direct, img_list)

    def set_cand_alphabet(self, cand_alphabet):
        pass

    def atomic_ocr(self, img_fp, cand_alphabet=None):
        res = self.ocr(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_line(self, img_fp, cand_alphabet=None):
        res = self.ocr_for_single_line(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        results = self.ocr_for_single_lines(img_list)
        if cand_alphabet:
            results = [
                "".join([c for c in res if c in cand_alphabet]) for res in results
            ]
        return results
