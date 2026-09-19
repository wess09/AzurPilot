"""worker 的任务边界和最终结果，通过已有可靠队列传递。"""

from dataclasses import dataclass
from enum import StrEnum


class WorkerResult(StrEnum):
    FINISHED = "finished"
    MANUAL_STOP = "manual_stop"
    UPDATE = "update"
    ERROR = "error"


@dataclass(frozen=True)
class TaskEvent:
    run_id: str | None
    command: str | None


@dataclass(frozen=True)
class ExitEvent:
    run_id: str | None
    result: WorkerResult


_sink = None
_run_id = None


def initialize(sink, run_id):
    """仅在 worker 中安装输出通道，独立脚本保持无操作。"""
    global _sink, _run_id
    _sink = sink
    _run_id = run_id


def set_task(command):
    if _sink is not None:
        _sink(TaskEvent(_run_id, command))
