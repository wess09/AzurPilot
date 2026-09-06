"""WebUI 设置与状态管理模块，维护界面偏好和持久化状态。
包括主题配置、展开折叠状态、依赖同步标记，
以及预览资源路径定义和缓存管理机制。"""

# 此文件专门用于管理 Web 界面自身的偏好设置及持久化状态类文件。
# 包括界面主题、常用项展开折叠状态以及各类预览占位图、图标资源的路径定义与缓存管理机制。
import multiprocessing
import os
import threading
from multiprocessing.managers import SyncManager
from typing import TYPE_CHECKING, Callable, Generic, TypeVar

from deploy.atomic import atomic_remove, atomic_write

if TYPE_CHECKING:
    from module.config.config_updater import ConfigUpdater
    from module.webui.config import DeployConfig

T = TypeVar("T")


# 代码更新后，父监督器必须先完成独立环境同步，才能创建新的 WebUI 子进程。
DEPENDENCY_SYNC_PENDING_FILE = "./config/webui-dependency-sync-pending"


def mark_dependency_sync_pending() -> None:
    """持久化依赖同步待处理状态，供新父进程在启动前恢复。"""
    atomic_write(DEPENDENCY_SYNC_PENDING_FILE, "pending\n")


def is_dependency_sync_pending() -> bool:
    """返回当前启动前是否必须执行依赖同步。"""
    return os.path.isfile(DEPENDENCY_SYNC_PENDING_FILE)


def clear_dependency_sync_pending() -> None:
    """仅在父监督器确认依赖同步成功后清除待处理状态。"""
    atomic_remove(DEPENDENCY_SYNC_PENDING_FILE)


class cached_class_property(Generic[T]):
    """
    Code from https://github.com/dssg/dickens
    Add typing support

    Descriptor decorator implementing a class-level, read-only
    property, which caches its results on the class(es) on which it
    operates.
    Inheritance is supported, insofar as the descriptor is never hidden
    by its cache; rather, it stores values under its access name with
    added underscores. For example, when wrapping getters named
    "choices", "choices_" or "_choices", each class's result is stored
    on the class at "_choices_"; decoration of a getter named
    "_choices_" would raise an exception.
    """

    class AliasConflict(ValueError):
        pass

    def __init__(self, func: Callable[..., T]):
        self.__func__ = func
        self.__cache_name__ = '_{}_'.format(func.__name__.strip('_'))
        if self.__cache_name__ == func.__name__:
            raise self.AliasConflict(self.__cache_name__)

    def __get__(self, instance, cls=None) -> T:
        if cls is None:
            cls = type(instance)

        try:
            return vars(cls)[self.__cache_name__]
        except KeyError:
            result = self.__func__(cls)
            setattr(cls, self.__cache_name__, result)
            return result


class State:
    """
    Shared settings
    """

    _init = False
    _clearup = False
    cleanup_lock = threading.Lock()
    restart_lock = threading.RLock()
    _restart_requested = False

    restart_event: threading.Event = None
    dependency_sync_event: threading.Event = None
    manager: SyncManager = None
    process_registry = None
    electron: bool = False
    webui_host: str = None
    theme: str = "default"
    placeholder_images: list = [
        "screen1.jpg",
        "screen2.jpg",
        "screen3.jpg",
        "screen4.png",
        "screen5.png",
        "screen6.png",
        "screen7.png",
        "screen8.jpg",
        "screen9.png",
    ]
    placeholder_index: int = 0

    @classmethod
    def get_placeholder_url(cls) -> str:
        try:
            idx = getattr(cls.deploy_config, "PlaceholderIndex", None)
            if idx is not None:
                try:
                    idx = int(idx)
                    cls.placeholder_index = idx % len(cls.placeholder_images)
                except Exception:
                    pass
        except Exception:
            pass

        name = cls.placeholder_images[cls.placeholder_index % len(cls.placeholder_images)]
        return f"static/assets/spa/{name}"

    @classmethod
    def toggle_placeholder(cls) -> str:
        return cls.advance_placeholder()

    @classmethod
    def advance_placeholder(cls) -> str:
        cls.placeholder_index = (cls.placeholder_index + 1) % len(cls.placeholder_images)
        try:
            cls.deploy_config.PlaceholderIndex = cls.placeholder_index
        except Exception:
            pass
        name = cls.placeholder_images[cls.placeholder_index]
        return f"static/assets/spa/{name}"
    
    @classmethod
    def init(cls):
        cls._clearup = False
        cls._restart_requested = False
        manager = multiprocessing.Manager()
        cls.manager = manager
        # Browser sessions may run in separate processes, so workers need a
        # process-wide registry instead of session-local Python objects.
        cls.process_registry = manager.dict()
        from module.webui.worker_registry import claim_owner

        try:
            claim_owner(os.getpid())
        except Exception as e:
            # 认领失败说明旧的登记残留无法在当前进程内自愈（例如旧所有者或其
            # worker 仍存活）。记录具体原因再清场，避免留下无主的 Manager
            # 子进程，随后向上抛出由启动方处理。
            from module.logger import logger

            logger.exception(
                f"[WebUI] 无法认领 worker 登记所有权，后端中止启动: {e}"
            )
            cls.process_registry = None
            cls.manager = None
            cls._init = False
            try:
                manager.shutdown()
            except Exception:
                pass
            raise
        cls._init = True

    @classmethod
    def clearup(cls):
        if cls._clearup:
            return
        from module.webui.worker_registry import clear_owner, filter_live_workers, get_workers

        workers = get_workers(os.getpid())
        live_workers = filter_live_workers(workers)
        if live_workers:
            raise RuntimeError(f"仍有存活的 worker 登记未回收: {sorted(live_workers)}")
        cls._clearup = True
        manager = cls.manager
        try:
            if manager is not None:
                manager.shutdown()
        finally:
            cls.manager = None
            cls.process_registry = None
            clear_owner(os.getpid())

    @cached_class_property
    def deploy_config(self) -> "DeployConfig":
        """
        Returns:
            DeployConfig：
        """
        from module.webui.config import DeployConfig

        return DeployConfig()

    @cached_class_property
    def config_updater(self) -> "ConfigUpdater":
        """
        Returns:
            ConfigUpdater：
        """
        from module.config.config_updater import ConfigUpdater

        return ConfigUpdater()
