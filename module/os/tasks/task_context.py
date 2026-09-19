"""大世界代理任务的临时身份与延迟请求。"""

from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from datetime import datetime


@dataclass(frozen=True)
class TaskDelayRequest:
    """与 config.task_delay 同名的参数，避免延后提交时才发现参数拼写错误。"""

    success: bool | None = None
    server_update: bool | str | list | None = None
    target: datetime | str | list | None = None
    minute: int | float | tuple | None = None
    task: str | None = None

    def apply(self, config):
        """仅提交已指定的参数，保留多个时间条件取最近值的原有语义。"""
        config.task_delay(**{
            field.name: value
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        })


@dataclass
class OverflowDelay:
    """一轮防溢出任务中共享的延迟请求；退出本轮后不再保留。"""

    request: TaskDelayRequest | None = None


@dataclass(frozen=True)
class OpsiTaskContext:
    """共享配置上的单一代理上下文，嵌套任务沿用防溢出延迟容器。"""

    smart_scheduling: bool = False
    overflow: OverflowDelay | None = None


def current_opsi_context(config):
    """让共享同一配置的任务对象读取同一个上下文。"""
    return getattr(config, '_opsi_task_context', None) or OpsiTaskContext()


_MISSING = object()


@contextmanager
def _temporary_attributes(config, **values):
    """精确恢复属性的缺失、None 和原值，不能把三者混为一谈。"""
    previous = {key: getattr(config, key, _MISSING) for key in values}
    try:
        for key, value in values.items():
            setattr(config, key, value)
        yield
    finally:
        for key, value in previous.items():
            if value is _MISSING:
                if hasattr(config, key):
                    delattr(config, key)
            else:
                setattr(config, key, value)


@contextmanager
def opsi_task_context(config, task, *, bind_task, disable_task_switch):
    """切换子任务身份；正常返回、TaskEnd 和绑定失败都恢复原身份。"""
    previous_task = config.task
    previous_bind = getattr(config, '_bind_task_override', None)
    context = replace(current_opsi_context(config), smart_scheduling=True)
    try:
        with _temporary_attributes(
            config,
            task=task,
            _bind_task_override=bind_task,
            _task_switch_owner=previous_task,
            _disable_task_switch=disable_task_switch,
            _opsi_task_context=context,
        ):
            config.bind(bind_task)
            yield context
    finally:
        config.bind(previous_bind if previous_bind is not None else previous_task)


@contextmanager
def prevent_overflow_context(config):
    """防溢出代理共享本轮延迟，最外层退出后恢复原上下文。"""
    previous = current_opsi_context(config)
    overflow = previous.overflow if previous.overflow is not None else OverflowDelay()
    with _temporary_attributes(config, _opsi_task_context=replace(previous, overflow=overflow)):
        yield overflow
