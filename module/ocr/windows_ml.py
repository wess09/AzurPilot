"""Windows ML ONNX Runtime 设备选择模块。

在 Windows 平台上为 ONNX Runtime 推理会话选择最优的执行提供程序 (Execution Provider)。
支持的 EP 优先级（从高到低）：

1. DirectML (DmlExecutionProvider): 通用 GPU 加速，支持所有 Windows GPU
2. QNN (QNNExecutionProvider): 高通 NPU 加速（特定硬件）
3. OpenVINO (OpenVINOExecutionProvider): Intel 硬件加速
4. CUDA (CUDAExecutionProvider): NVIDIA GPU 加速
5. CPU (CPUExecutionProvider): 兜底方案

设备选择逻辑：
- 根据用户配置的设备偏好（'gpu'、'cpu'、'npu'）选择 EP
- 自动检测 AMD 集成显卡并排除不兼容的 EP
- 通过 GPU 显存大小区分独显和集显
- 同型号多设备时优先真实独显（Discrete 标记 + DXGI 高性能索引），
  避免绑定到会热插拔的虚拟显示器适配器
- 使用线程锁确保 EP 初始化的线程安全性

核心函数 create_onnx_session() 被 al_ocr.py 调用，
为 OCR 模型创建优化的推理会话。
"""

import os
import re
import threading

from module.logger import logger


# 执行提供程序常量
QNN_EP = "QNNExecutionProvider"
OPENVINO_EP = "OpenVINOExecutionProvider"
DML_EP = "DmlExecutionProvider"

QNN_NPU_DEVICE = "qnn_npu"
OPENVINO_NPU_DEVICE = "openvino_npu"
OPENVINO_GPU_DEVICE = "openvino_gpu"
OPENVINO_CPU_DEVICE = "openvino_cpu"

_MIN_DISCRETE_VIDEO_MEMORY_MIB = 1024
# 缺少 DxgiHighPerformanceIndex 元数据时的排序占位值，保证这类设备排在已知索引之后
_UNKNOWN_HIGH_PERFORMANCE_INDEX = 1 << 16
_AMD_INTEGRATED_HD_MODELS = {
    "6250",
    "6290",
    "6310",
    "6320",
    "6410d",
    "6530d",
    "6550d",
    "7560d",
    "7660d",
}
_AMD_INTEGRATED_VEGA_MODELS = {"3", "5", "6", "7", "8", "10", "11"}
_AMD_INTEGRATED_RDNA_MODELS = {
    "610m",
    "660m",
    "680m",
    "740m",
    "760m",
    "780m",
    "840m",
    "860m",
    "880m",
    "890m",
}

_provider_lock = threading.Lock()
_prepared_execution_providers = set()


def create_onnx_session(
    ort,
    model_path,
    session_options_factory=None,
    allow_acceleration=True,
    allow_vendor_execution_providers=True,
    device_preference="auto",
):
    """按固定优先级创建 Windows ML 或 CPU ONNX Runtime session。"""
    create_options = session_options_factory or ort.SessionOptions

    if os.name != "nt" or not allow_acceleration:
        return (
            ort.InferenceSession(
                str(model_path),
                sess_options=create_options(),
                providers=["CPUExecutionProvider"],
            ),
            "CPUExecutionProvider",
        )

    vendor_execution_providers = _vendor_execution_provider_names(device_preference)
    if allow_vendor_execution_providers and vendor_execution_providers:
        _prepare_vendor_execution_providers(ort, vendor_execution_providers)
    elif not allow_vendor_execution_providers and vendor_execution_providers:
        logger.info("[OCR] Windows ML 厂商 EP 自动安装和使用已禁用")

    for device in _iter_preferred_devices(
        ort,
        device_preference=device_preference,
        allow_vendor_execution_providers=allow_vendor_execution_providers,
    ):
        options = create_options()
        # OrtEpDevice 已包含目标硬件的标识；重复传入 ep_options 会导致
        # ONNX Runtime 重复设置 DirectML 的 device_id 并输出无意义警告。
        options.add_provider_for_devices([device], {})
        if device.ep_name == DML_EP:
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

        try:
            session = ort.InferenceSession(str(model_path), sess_options=options)
        except Exception as exc:
            logger.warning(
                f"[OCR] Windows ML 无法使用 {device.ep_name}，尝试下一个设备: {exc}"
            )
            continue

        logger.info(f"[OCR] Windows ML 选择 {_describe_device(device)}")
        return session, device.ep_name

    logger.info("[OCR] 未找到符合条件的 Windows ML 加速设备，使用 CPU")
    return (
        ort.InferenceSession(
            str(model_path),
            sess_options=create_options(),
            providers=["CPUExecutionProvider"],
        ),
        "CPUExecutionProvider",
    )


def _prepare_vendor_execution_providers(ort, provider_names):
    """通过 Windows Update 获取并注册本项目允许使用的厂商 EP。"""
    marker = id(ort)
    with _provider_lock:
        pending_provider_names = tuple(
            name
            for name in provider_names
            if (marker, name) not in _prepared_execution_providers
        )
        if not pending_provider_names:
            return

        try:
            import windowsml
        except Exception as exc:
            logger.warning(f"[OCR] Windows ML Runtime 不可用，跳过 NPU/OpenVINO: {exc}")
            _prepared_execution_providers.update(
                (marker, name) for name in pending_provider_names
            )
            return

        try:
            # ExecutionProvider 句柄由 EpCatalog 所有，必须在目录关闭前完成注册。
            with windowsml.EpCatalog() as catalog:
                providers = {
                    provider.name: provider
                    for provider in catalog.find_all_providers()
                }
                for name in pending_provider_names:
                    provider = providers.get(name)
                    if provider is None:
                        continue
                    _ensure_and_register_provider(ort, windowsml, provider)
        except Exception as exc:
            logger.warning(f"[OCR] 无法枚举 Windows ML 执行提供程序: {exc}")

        _prepared_execution_providers.update(
            (marker, name) for name in pending_provider_names
        )


def _ensure_and_register_provider(ort, windowsml, provider):
    try:
        ready = windowsml.EpReadyState.Ready
        if provider.ready_state != ready:
            logger.info(f"[OCR] 准备 Windows ML {provider.name}: {provider.ready_state}")
            with provider.ensure_ready_async() as operation:
                operation.wait()

        registered_names = {device.ep_name for device in ort.get_ep_devices()}
        if provider.name not in registered_names:
            ort.register_execution_provider_library(provider.name, provider.library_path)
            logger.info(f"[OCR] 已注册 Windows ML {provider.name}")
    except Exception as exc:
        logger.warning(
            f"[OCR] Windows ML {provider.name} 自动安装或更新失败: {exc}。"
            "已跳过该 EP 并继续尝试后备设备；请检查 Windows Update 服务未被禁用、"
            "Windows 更新策略没有被组织管理器关闭，以及网络可访问 Windows 更新服务。"
        )


def _device_priority(device):
    """设备排序键：真实独显优先，同级再按 DXGI 高性能索引升序。

    Windows 上的虚拟显示器适配器（远程控制虚拟屏、模拟器虚拟屏、
    Virtual Display Driver 等）会镜像独显的名称与显存，且通常不填
    Discrete 元数据，仅靠 _is_discrete_gpu() 无法把它们与真实独显区分。
    这类适配器会随显示配置变化被热插拔，绑定其上的 DirectML 会话会在
    run() 时失效报错（底层消息为本地化编码，最终表现为
    UnicodeDecodeError 崩溃并中断任务）。
    Discrete=1 是 Windows ML 为真实独显写入的标记，
    DxgiHighPerformanceIndex 则把性能最高的适配器排在前面，
    两者结合即可稳定选中真实独显。

    Args:
        device: ONNX Runtime 的 OrtEpDevice。

    Returns:
        tuple: (是否非独显, 高性能索引)，用于升序排序。
    """
    metadata = device.device.metadata
    discrete = metadata.get("Discrete")
    not_discrete = 0 if str(discrete).lower() in ("1", "true") else 1

    index = metadata.get("DxgiHighPerformanceIndex")
    try:
        performance = int(index)
    except (TypeError, ValueError):
        performance = _UNKNOWN_HIGH_PERFORMANCE_INDEX
    return not_discrete, performance


def _iter_preferred_devices(
    ort,
    device_preference="auto",
    allow_vendor_execution_providers=True,
):
    try:
        devices = ort.get_ep_devices()
    except Exception as exc:
        logger.warning(f"[OCR] 无法枚举 ONNX Runtime 设备: {exc}")
        return ()

    device_types = ort.OrtHardwareDeviceType
    candidates = {
        "auto": (
            (QNN_EP, device_types.NPU, False),
            (OPENVINO_EP, device_types.NPU, False),
            (OPENVINO_EP, device_types.GPU, True),
            (DML_EP, device_types.GPU, True),
            (OPENVINO_EP, device_types.CPU, False),
        ),
        QNN_NPU_DEVICE: ((QNN_EP, device_types.NPU, False),),
        OPENVINO_NPU_DEVICE: ((OPENVINO_EP, device_types.NPU, False),),
        OPENVINO_GPU_DEVICE: ((OPENVINO_EP, device_types.GPU, True),),
        "gpu": ((DML_EP, device_types.GPU, True),),
        OPENVINO_CPU_DEVICE: ((OPENVINO_EP, device_types.CPU, False),),
    }.get(device_preference, ())
    if not allow_vendor_execution_providers:
        candidates = tuple(candidate for candidate in candidates if candidate[0] == DML_EP)

    preferred = []
    for ep_name, device_type, require_discrete in candidates:
        matched = [
            device
            for device in devices
            if device.ep_name == ep_name
            and device.device.type == device_type
            and (not require_discrete or _is_discrete_gpu(device))
        ]
        # 同一候选内可能有多个同型号设备（真实独显 + 虚拟显示器适配器），
        # 排序后再交给 create_onnx_session 依次尝试，确保先绑到真实独显。
        preferred.extend(sorted(matched, key=_device_priority))

    for device in preferred:
        metadata = device.device.metadata
        logger.info(
            f"[OCR] 候选设备 {device.ep_name}/{metadata.get('Description', 'unknown')}"
            f" (adapter={metadata.get('DxgiAdapterNumber', '?')},"
            f" discrete={metadata.get('Discrete', '?')})"
        )
    return tuple(preferred)


def _vendor_execution_provider_names(device_preference):
    if device_preference in ("auto", QNN_NPU_DEVICE):
        names = [QNN_EP]
    else:
        names = []
    if device_preference in (
        "auto",
        OPENVINO_NPU_DEVICE,
        OPENVINO_GPU_DEVICE,
        OPENVINO_CPU_DEVICE,
    ):
        names.append(OPENVINO_EP)
    return tuple(names)


def _is_discrete_gpu(device):
    metadata = device.device.metadata
    discrete = metadata.get("Discrete")
    if discrete is not None:
        return str(discrete).lower() in ("1", "true")

    # Windows 10 的部分驱动不会填充 Discrete。先排除已知核显和软件适配器，
    # 再用 DXGI 专用显存确认其余设备；缺少显存元数据时仍放行未知名称，
    # 避免 GTX 1070 之类独显被漏掉。
    name = _normalize_gpu_name(metadata.get("Description", ""))
    if _is_known_integrated_gpu_name(name) or _is_software_gpu_name(name):
        return False

    video_memory_mib = _video_memory_mib(metadata.get("DxgiVideoMemory"))
    if video_memory_mib is None:
        return True
    return video_memory_mib >= _MIN_DISCRETE_VIDEO_MEMORY_MIB


def _normalize_gpu_name(name):
    name = str(name).lower()
    name = name.replace("(r)", "").replace("(tm)", "")
    return " ".join(name.split())


def _is_known_integrated_gpu_name(name):
    """根据 Windows 设备名识别没有 Discrete 元数据的常见核显。"""
    if name.startswith(
        (
            "intel graphics media accelerator",
            "intel gma ",
            "intel hd graphics",
            "intel iris graphics",
            "intel iris plus graphics",
            "intel iris pro graphics",
            "intel iris xe graphics",
            "intel uhd graphics",
            "intel graphics",
            "intel arc graphics",
            "intel arc 130v",
            "intel arc 140v",
        )
    ):
        # Intel Iris Xe MAX 是独显，名称不会落入上述 Iris Xe Graphics 前缀。
        return True

    for prefix in ("amd ", "advanced micro devices, inc. "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    if name in {"radeon graphics", "radeon(tm) graphics"}:
        return True
    if re.fullmatch(r"radeon r[2-7] graphics", name):
        return True
    if re.fullmatch(
        r"radeon hd (?:" + "|".join(_AMD_INTEGRATED_HD_MODELS) + r")(?: graphics)?",
        name,
    ):
        return True
    if re.fullmatch(
        r"radeon vega (?:"
        + "|".join(_AMD_INTEGRATED_VEGA_MODELS)
        + r")(?: graphics)?",
        name,
    ):
        return True
    return bool(
        re.fullmatch(
            r"radeon (?:"
            + "|".join(_AMD_INTEGRATED_RDNA_MODELS)
            + r")(?: graphics)?",
            name,
        )
    )


def _is_software_gpu_name(name):
    return name.startswith(
        (
            "microsoft basic render driver",
            "microsoft remote display adapter",
            "remote display adapter",
        )
    )


def _video_memory_mib(value):
    if value is None:
        return None

    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(MiB|MB|GiB|GB)?\s*", str(value))
    if match is None:
        return None

    amount = float(match.group(1))
    unit = (match.group(2) or "MiB").lower()
    if unit in {"gib", "gb"}:
        amount *= 1024
    return int(amount)


def _describe_device(device):
    metadata = device.device.metadata
    description = metadata.get("Description", device.device.vendor)
    return f"{device.ep_name}/{device.device.type.name}: {description}"
