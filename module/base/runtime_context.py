"""单进程多实例的运行态上下文。

资源定义在模块导入时创建，通常可在同一解释器内安全共享；但其中少量字段会在
运行期间写入。这个模块为这类字段提供按 worker 隔离的存储，避免为了隔离状态而
复制 Button、模板图像等大对象。

未进入 :func:`runtime_scope` 时，调用方应继续使用对象自身的原有字段，从而保持
传统单进程单实例和多进程运行模式的行为不变。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from typing import Callable, Generator, TypeVar


T = TypeVar('T')


@dataclass
class _OwnerStates:
    """同一对象在一个运行态上下文中的命名空间状态。"""

    owner: object
    namespaces: dict[str, object] = field(default_factory=dict)


class RuntimeContext:
    """一个 worker 的可变运行态容器。

    ``states`` 以对象身份而非 ``__hash__`` 索引，避免 Button 以名称实现的哈希规则
    将不同资源误合并。对象仅在上下文生命周期内被强引用，worker 退出时会统一清理。
    """

    def __init__(self, worker_id: str | None = None):
        self.worker_id = worker_id
        self._states: dict[int, _OwnerStates] = {}
        self._options: dict[str, object] = {}
        self._lock = RLock()

    def state(self, owner: object, namespace: str, factory: Callable[[], T]) -> T:
        """返回 ``owner`` 在指定命名空间中的隔离状态。"""
        key = id(owner)
        with self._lock:
            entry = self._states.get(key)
            if entry is None or entry.owner is not owner:
                entry = _OwnerStates(owner=owner)
                self._states[key] = entry

            try:
                return entry.namespaces[namespace]  # type: ignore[return-value]
            except KeyError:
                value = factory()
                entry.namespaces[namespace] = value
                return value

    def clear(self, owner: object | None = None, namespace: str | None = None) -> int:
        """清理指定对象/命名空间的运行态，返回移除的状态数量。"""
        with self._lock:
            if owner is not None:
                key = id(owner)
                entry = self._states.get(key)
                if entry is None or entry.owner is not owner:
                    return 0
                return self._clear_entry(key, entry, namespace)

            removed = 0
            for key, entry in list(self._states.items()):
                removed += self._clear_entry(key, entry, namespace)
            if owner is None and namespace is None:
                self._options.clear()
            return removed

    def get_option(self, name: str, default: T = None) -> T:
        """读取当前 worker 的轻量运行时选项。"""
        with self._lock:
            return self._options.get(name, default)  # type: ignore[return-value]

    def set_option(self, name: str, value: object) -> None:
        """设置当前 worker 的轻量运行时选项。"""
        with self._lock:
            self._options[name] = value

    def _clear_entry(self, key: int, entry: _OwnerStates, namespace: str | None) -> int:
        if namespace is None:
            removed = len(entry.namespaces)
            del self._states[key]
            return removed

        if namespace not in entry.namespaces:
            return 0
        del entry.namespaces[namespace]
        if not entry.namespaces:
            del self._states[key]
        return 1


_runtime_context: ContextVar[RuntimeContext | None] = ContextVar(
    'alas_runtime_context', default=None
)
_contexts: dict[str, RuntimeContext] = {}
_contexts_lock = RLock()


def get_runtime_context() -> RuntimeContext | None:
    """返回当前 worker 的上下文；传统进程模式下返回 ``None``。"""
    return _runtime_context.get()


def current_runtime_id() -> str | None:
    """返回当前 worker 标识，未进入运行态上下文时返回 ``None``。"""
    context = get_runtime_context()
    return context.worker_id if context is not None else None


@contextmanager
def runtime_scope(
        worker_id: str | None = None,
        *,
        context: RuntimeContext | None = None,
) -> Generator[RuntimeContext, None, None]:
    """进入一个 worker 运行态作用域。

    同一非空 ``worker_id`` 会复用其已注册上下文，因此受控的重入或恢复执行不会
    丢失该 worker 的运行态。worker 彻底退出后必须调用
    :func:`clear_runtime_context` 释放其状态。传入已有 ``context`` 可用于将同一
    worker 状态显式传播到受控的后台执行单元；调用方负责其生命周期。
    """
    if context is None:
        if worker_id is None:
            # 无标识作用域不具备跨调用复用的语义，避免创建不可回收的匿名上下文。
            context = RuntimeContext(worker_id=None)
        else:
            with _contexts_lock:
                context = _contexts.get(worker_id)
                if context is None:
                    context = RuntimeContext(worker_id=worker_id)
                    _contexts[worker_id] = context

    token = _runtime_context.set(context)
    try:
        yield context
    finally:
        _runtime_context.reset(token)


def runtime_state(owner: object, namespace: str, factory: Callable[[], T]) -> T | None:
    """获取当前上下文中对象的状态；没有上下文时返回 ``None``。

    调用方应在返回 ``None`` 时访问原有实例字段。这一约定使现有多进程模式无需
    感知运行态上下文。
    """
    context = get_runtime_context()
    if context is None:
        return None
    return context.state(owner, namespace, factory)


def clear_runtime_state(owner: object | None = None, namespace: str | None = None) -> int:
    """清理当前上下文中的隔离状态，未进入上下文时不执行操作。"""
    context = get_runtime_context()
    if context is None:
        return 0
    return context.clear(owner=owner, namespace=namespace)


def clear_runtime_context(worker_id: str) -> int:
    """移除已结束 worker 的整个运行态上下文。

    该函数只能在 worker 线程已停止、或调用方确认不会再并发访问该上下文时调用。
    返回被清理的命名空间状态数量；未知 worker 标识返回 ``0``。
    """
    with _contexts_lock:
        context = _contexts.pop(worker_id, None)
    if context is None:
        return 0
    return context.clear()


def active_runtime_count() -> int:
    """返回仍由单进程宿主管理的 worker 上下文数量。"""
    with _contexts_lock:
        return len(_contexts)


def get_runtime_option(name: str, default: T = None) -> T:
    """读取当前运行态选项；传统进程模式返回默认值。"""
    context = get_runtime_context()
    if context is None:
        return default
    return context.get_option(name, default)


def set_runtime_option(name: str, value: object) -> None:
    """设置当前 worker 的运行态选项。"""
    context = get_runtime_context()
    if context is None:
        raise RuntimeError('运行态选项必须在 runtime_scope 内设置')
    context.set_option(name, value)
