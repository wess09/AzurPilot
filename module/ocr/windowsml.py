import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from module.logger import logger


CPU_EP = "CPUExecutionProvider"
DML_EP = "DmlExecutionProvider"
COREML_EP = "CoreMLExecutionProvider"
AMD_INTEGRATED_GPU_RE = re.compile(r"\b(?:610m|660m|680m|740m|760m|780m|880m|890m)\b", re.I)
CPU_DEVICE_KEYWORDS = (
    "core(tm)",
    "ryzen",
    "xeon",
    "pentium",
    "celeron",
    "threadripper",
    "athlon",
)
INTEL_DISCRETE_GPU_KEYWORDS = (
    "arc(tm) a",
    "arc(tm) b",
    "arc(tm) pro",
    "arc a",
    "arc b",
    "arc pro",
)
AMD_DISCRETE_GPU_KEYWORDS = (
    "radeon rx",
    "radeon pro",
    "pro w",
    "instinct",
)

_INSTALL_ATTEMPTED = False


@dataclass(frozen=True)
class OrtDeviceInfo:
    ep_name: str
    device_type: str
    vendor: str
    description: str
    video_memory_mb: int
    raw: Any

    @property
    def value(self) -> str:
        return _device_value(self)

    @property
    def label(self) -> str:
        parts = [self.ep_name, self.device_type]
        if self.description:
            parts.append(self.description)
        metadata = _device_metadata(self.raw)
        luid = metadata.get("LUID")
        adapter = metadata.get("DxgiAdapterNumber")
        if luid:
            parts.append(f"LUID {luid}")
        elif adapter:
            parts.append(f"DXGI {adapter}")
        return " / ".join(parts)


def _cfg_get(cfg, name, default=None):
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(name, default)
    return getattr(cfg, name, default)


def _parse_video_memory_mb(metadata):
    value = metadata.get("DxgiVideoMemory", "")
    if isinstance(value, str):
        number = "".join(ch for ch in value if ch.isdigit())
        return int(number) if number else 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _device_metadata(ep_device):
    device = getattr(ep_device, "device", None)
    if device is None:
        return {}
    return dict(getattr(device, "metadata", {}) or {})


def _device_value(device):
    metadata = _device_metadata(device.raw)
    identity = metadata.get("LUID") or metadata.get("DxgiAdapterNumber") or device.description
    return "|".join(
        [
            device.ep_name,
            device.device_type,
            device.vendor,
            str(identity or ""),
        ]
    )


def _device_type_name(device):
    device_type = getattr(device, "type", "")
    return getattr(device_type, "name", str(device_type)).upper()


def _device_search_text(device):
    return f"{device.vendor} {device.description}".lower()


def _is_cpu_like_device(device):
    if device.ep_name == CPU_EP or device.device_type == "CPU":
        return True

    text = _device_search_text(device)
    return any(keyword in text for keyword in CPU_DEVICE_KEYWORDS)


def _is_integrated_gpu(device):
    if device.device_type != "GPU":
        return False

    text = _device_search_text(device)
    if "microsoft basic render" in text:
        return True

    if "intel" in text:
        return not any(keyword in text for keyword in INTEL_DISCRETE_GPU_KEYWORDS)

    if "amd" in text or "advanced micro devices" in text or "radeon" in text:
        if any(keyword in text for keyword in AMD_DISCRETE_GPU_KEYWORDS):
            return False
        if (
            "radeon(tm) graphics" in text
            or "radeon graphics" in text
            or AMD_INTEGRATED_GPU_RE.search(text)
        ):
            return True
        return 0 < device.video_memory_mb < 1024

    return False


def _is_vendor_gpu_ep(device):
    return device.device_type == "GPU" and device.ep_name not in {DML_EP, CPU_EP}


def _is_vendor_gpu_auto_candidate(device):
    if not _is_vendor_gpu_ep(device):
        return False
    return not _is_cpu_like_device(device) and not _is_integrated_gpu(device)


def _is_dml_auto_candidate(device):
    if device.device_type != "GPU" or device.ep_name != DML_EP:
        return False
    return not _is_cpu_like_device(device) and not _is_integrated_gpu(device)


def _is_auto_selectable_device(device):
    if _is_cpu_like_device(device):
        return False
    if device.device_type == "NPU":
        return True
    if _is_vendor_gpu_ep(device):
        return _is_vendor_gpu_auto_candidate(device)
    return _is_dml_auto_candidate(device)


def windowsml_device_options(ort=None, install_missing_ep=False):
    if ort is None:
        import onnxruntime as ort

    ensure_windows_ml_execution_providers(ort, install_missing_ep)

    options = [("auto", "自动选择最佳硬件")]
    for device in iter_ort_device_candidates("gpu", ort):
        if device.device_type == "CPU" or device.ep_name == CPU_EP:
            continue
        options.append((device.value, device.label))
    return options


def _build_session_options(ort, engine_cfg=None):
    options = ort.SessionOptions()
    options.log_severity_level = 4
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    enable_cpu_mem_arena = _cfg_get(engine_cfg, "enable_cpu_mem_arena")
    if enable_cpu_mem_arena is not None:
        options.enable_cpu_mem_arena = bool(enable_cpu_mem_arena)

    cpu_nums = os.cpu_count() or 1
    intra_threads = _cfg_get(engine_cfg, "intra_op_num_threads", -1)
    if isinstance(intra_threads, int) and 1 <= intra_threads <= cpu_nums:
        options.intra_op_num_threads = intra_threads

    inter_threads = _cfg_get(engine_cfg, "inter_op_num_threads", -1)
    if isinstance(inter_threads, int) and 1 <= inter_threads <= cpu_nums:
        options.inter_op_num_threads = inter_threads

    return options


def discover_ort_devices(ort=None):
    if ort is None:
        import onnxruntime as ort

    if not hasattr(ort, "get_ep_devices"):
        return []

    devices = []
    for ep_device in ort.get_ep_devices():
        device = getattr(ep_device, "device", None)
        if device is None:
            continue

        metadata = dict(getattr(device, "metadata", {}) or {})
        devices.append(
            OrtDeviceInfo(
                ep_name=getattr(ep_device, "ep_name", ""),
                device_type=_device_type_name(device),
                vendor=str(getattr(device, "vendor", "") or ""),
                description=str(metadata.get("Description", "") or "").strip(),
                video_memory_mb=_parse_video_memory_mb(metadata),
                raw=ep_device,
            )
        )
    return devices


def _sort_key(device):
    if device.device_type == "NPU":
        group = 0
    elif _is_vendor_gpu_auto_candidate(device):
        group = 1
    elif _is_dml_auto_candidate(device):
        group = 2
    elif device.ep_name == CPU_EP or device.device_type == "CPU":
        group = 3
    else:
        group = 4
    return group, -device.video_memory_mb, device.ep_name, device.description


def iter_ort_device_candidates(preference="auto", ort=None):
    devices = sorted(discover_ort_devices(ort), key=_sort_key)
    if preference == "cpu":
        return [device for device in devices if device.ep_name == CPU_EP]
    if preference == "ane":
        return []
    return devices


def select_best_ort_device(preference="auto", ort=None):
    candidates = iter_ort_device_candidates(preference, ort)
    return candidates[0] if candidates else None


def _import_windows_ml_catalog():
    candidates = [
        "windowsml",
    ]
    for name in candidates:
        try:
            module = __import__(name, fromlist=["*"])
            logger.info(f"Using Windows ML Catalog binding: {name}")
            return module
        except Exception:
            continue
    return None


def _ep_ready_state_name(winml, provider):
    ready_state = getattr(provider, "ready_state", "")
    if hasattr(ready_state, "name"):
        return ready_state.name
    return str(ready_state)


def _is_ep_ready(winml, provider):
    ready_state = getattr(provider, "ready_state", None)
    ep_ready_state = getattr(winml, "EpReadyState", None)
    if ep_ready_state is not None and hasattr(ep_ready_state, "Ready"):
        return ready_state == ep_ready_state.Ready
    return _ep_ready_state_name(winml, provider).lower() == "ready"


def _ensure_ep_ready(winml, provider):
    name = str(getattr(provider, "name", "") or "")
    if _is_ep_ready(winml, provider):
        return True

    ready_state = _ep_ready_state_name(winml, provider)
    logger.info(
        f"Prepare Windows ML EP: "
        f"{name}, state={ready_state}"
    )
    provider.ensure_ready()
    if _is_ep_ready(winml, provider):
        logger.info(
            f"Windows ML EP ready: "
            f"{name}, state={_ep_ready_state_name(winml, provider)}"
        )
        return True

    logger.warning(
        f"Windows ML EP is not ready after prepare: "
        f"{name}, state={_ep_ready_state_name(winml, provider)}"
    )
    return False


def _register_windows_ml_ep(ort, provider):
    name = str(getattr(provider, "name", "") or "")
    library_path = str(getattr(provider, "library_path", "") or "")
    if not library_path:
        logger.warning(f"Windows ML EP has no library path: {name}")
        return False

    ort.register_execution_provider_library(name, library_path)
    logger.info(f"Registered Windows ML EP: {name} ({library_path})")
    return True


def ensure_windows_ml_execution_providers(ort, install_missing=False):
    global _INSTALL_ATTEMPTED
    if not install_missing or os.name != "nt" or _INSTALL_ATTEMPTED:
        return

    _INSTALL_ATTEMPTED = True
    winml = _import_windows_ml_catalog()
    if winml is None:
        logger.info(
            "Skip Windows ML EP install: Python package 'windowsml' is unavailable"
        )
        return

    try:
        with winml.EpCatalog() as catalog:
            providers = catalog.find_all_providers()
            if not providers:
                logger.info("Windows ML Catalog found no compatible vendor EP")
                return

            logger.info(f"Windows ML Catalog provider count: {len(providers)}")
            registered = 0
            for provider in providers:
                name = str(getattr(provider, "name", "") or "")

                try:
                    if _ensure_ep_ready(winml, provider) and _register_windows_ml_ep(
                        ort,
                        provider,
                    ):
                        registered += 1
                except Exception as exc:
                    logger.warning(f"Windows ML EP install/register skipped: {name}, {exc}")

            if registered:
                logger.info(f"Registered Windows ML vendor EP count: {registered}")
            else:
                logger.info("No Windows ML vendor EP was registered")
    except Exception as exc:
        logger.warning(f"Windows ML EP install/register skipped: {exc}")


def _create_with_provider_list(ort, model_path, engine_cfg, providers, log_label):
    options = _build_session_options(ort, engine_cfg)
    session = ort.InferenceSession(str(model_path), sess_options=options, providers=providers)
    logger.info(f"Windows ML OCR provider: {log_label}")
    return session


def _create_cpu_session(ort, model_path, engine_cfg):
    return _create_with_provider_list(
        ort,
        model_path,
        engine_cfg,
        [CPU_EP],
        CPU_EP,
    )


def _create_coreml_session(ort, model_path, engine_cfg):
    available = ort.get_available_providers()
    if COREML_EP not in available:
        logger.warning("CoreMLExecutionProvider is unavailable, falling back to CPU")
        return _create_cpu_session(ort, model_path, engine_cfg)

    return _create_with_provider_list(
        ort,
        model_path,
        engine_cfg,
        [(COREML_EP, {"MLComputeUnits": "CPUAndNeuralEngine"}), CPU_EP],
        f"{COREML_EP} / ANE",
    )


def _create_windows_hardware_session(
    ort,
    model_path,
    engine_cfg,
    install_missing_ep,
    windowsml_device,
):
    ensure_windows_ml_execution_providers(ort, install_missing_ep)
    candidates = iter_ort_device_candidates("gpu", ort)
    if windowsml_device and windowsml_device != "auto":
        selected = [device for device in candidates if device.value == windowsml_device]
        if not selected:
            logger.warning(f"Selected Windows ML OCR device is unavailable: {windowsml_device}")
            return _create_cpu_session(ort, model_path, engine_cfg)
        candidates = selected

    for device in candidates:
        if device.device_type == "CPU" or device.ep_name == CPU_EP:
            continue
        if (
            (not windowsml_device or windowsml_device == "auto")
            and not _is_auto_selectable_device(device)
        ):
            logger.info(f"Skip Windows ML OCR provider for auto: {device.label}")
            continue

        options = _build_session_options(ort, engine_cfg)
        try:
            options.add_provider_for_devices([device.raw], {})
            session = ort.InferenceSession(str(model_path), sess_options=options)
            logger.info(f"Windows ML OCR provider: {device.label}")
            return session
        except Exception as exc:
            logger.warning(f"Windows ML OCR provider failed: {device.label}, {exc}")

    if windowsml_device and windowsml_device != "auto":
        logger.warning("Selected Windows ML OCR device failed, falling back to CPU")
        return _create_cpu_session(ort, model_path, engine_cfg)

    available = ort.get_available_providers()
    if DML_EP in available:
        if candidates:
            logger.info("Skip generic DML fallback: explicit Windows ML devices were tested")
        else:
            try:
                return _create_with_provider_list(
                    ort,
                    model_path,
                    engine_cfg,
                    [DML_EP, CPU_EP],
                    f"{DML_EP} / GPU",
                )
            except Exception as exc:
                logger.warning(f"Windows ML DML provider failed: {exc}")

    logger.warning("Windows ML hardware acceleration is unavailable, falling back to CPU")
    return _create_cpu_session(ort, model_path, engine_cfg)


def create_ort_session(
    model_path,
    preference="auto",
    engine_cfg=None,
    install_missing_ep=False,
    windowsml_device="auto",
):
    import onnxruntime as ort

    model_path = Path(model_path)
    if not model_path.is_file():
        raise FileNotFoundError(f"OCR model not found: {model_path}")

    if preference == "cpu":
        return _create_cpu_session(ort, model_path, engine_cfg)

    if preference == "ane":
        if os.name == "nt":
            logger.warning("ANE is only available on macOS, falling back to CPU")
            return _create_cpu_session(ort, model_path, engine_cfg)
        return _create_coreml_session(ort, model_path, engine_cfg)

    if os.name == "nt":
        return _create_windows_hardware_session(
            ort,
            model_path,
            engine_cfg,
            install_missing_ep,
            windowsml_device,
        )

    return _create_cpu_session(ort, model_path, engine_cfg)


class AlOrtInferSession:
    def __init__(
        self,
        cfg,
        device="cpu",
        install_missing_ep=False,
        windowsml_device="auto",
    ):
        self.model_path = Path(_cfg_get(cfg, "model_path"))
        self.session = create_ort_session(
            self.model_path,
            preference=device,
            engine_cfg=_cfg_get(cfg, "engine_cfg"),
            install_missing_ep=install_missing_ep,
            windowsml_device=windowsml_device,
        )

    def __call__(self, input_content: np.ndarray) -> np.ndarray:
        input_dict = dict(zip(self.get_input_names(), [input_content]))
        try:
            return self.session.run(self.get_output_names(), input_dict)[0]
        except Exception as exc:
            raise RuntimeError(f"ONNXRuntime OCR inference failed: {exc}") from exc

    def get_input_names(self):
        return [item.name for item in self.session.get_inputs()]

    def get_output_names(self):
        return [item.name for item in self.session.get_outputs()]

    def have_key(self, key="character"):
        return key in self.session.get_modelmeta().custom_metadata_map

    def get_character_list(self, key="character"):
        return self.session.get_modelmeta().custom_metadata_map[key].splitlines()

    def get_dict_key_url(self, file_info):
        return None
