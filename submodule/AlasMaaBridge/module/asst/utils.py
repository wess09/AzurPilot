from typing import Union, Dict, List, Any, Type
from enum import Enum, IntEnum, unique, auto

JSON = Union[Dict[str, Any], List[Any], int, str, float, bool, Type[None]]


class InstanceOptionType(IntEnum):
    """实例配置选项类型。"""
    touch_type = 2
    """触控模式设置，可选 "minitouch" | "maatouch" | "adb"。"""
    deployment_with_pause = 3
    """自动战斗、肉鸽、保全是否使用暂停下干员，可选 "0" | "1"。"""
    adblite_enabled = 4
    """是否使用 AdbLite，可选 "0" | "1"。"""
    kill_on_adb_exit = 5
    """ADB 退出时是否终止进程。"""


class StaticOptionType(IntEnum):
    """静态配置选项类型。"""
    invalid = 0
    """无效选项。"""
    cpu_ocr = 1
    """使用 CPU 进行 OCR 识别。"""
    gpu_ocr = 2
    """使用 GPU 进行 OCR 识别。"""


@unique
class Message(Enum):
    """MAA 回调消息类型枚举。

    请参考 docs/回调消息.md 了解各消息的详细含义。
    """
    InternalError = 0
    """内部错误。"""
    InitFailed = auto()
    """初始化失败。"""
    ConnectionInfo = auto()
    """连接信息。"""
    AllTasksCompleted = auto()
    """所有任务已完成。"""
    AsyncCallInfo = auto()
    """异步调用信息。"""
    Destroyed = auto()
    """实例已销毁。"""
    TaskChainError = 10000
    """任务链执行错误。"""
    TaskChainStart = auto()
    """任务链开始执行。"""
    TaskChainCompleted = auto()
    """任务链执行完成。"""
    TaskChainExtraInfo = auto()
    """任务链额外信息。"""
    TaskChainStopped = auto()
    """任务链已停止。"""
    SubTaskError = 20000
    """子任务执行错误。"""
    SubTaskStart = auto()
    """子任务开始执行。"""
    SubTaskCompleted = auto()
    """子任务执行完成。"""
    SubTaskExtraInfo = auto()
    """子任务额外信息。"""
    SubTaskStopped = auto()
    """子任务已停止。"""


@unique
class Version(Enum):
    """目标更新版本类型。"""
    Nightly = auto()
    """每夜构建版本，包含最新但可能不稳定的更改。"""
    Beta = auto()
    """测试版本，功能基本完整但可能存在问题。"""
    Stable = auto()
    """稳定版本，经过充分测试的正式发布版。"""
