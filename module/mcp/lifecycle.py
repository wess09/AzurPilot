"""独立 MCP 只拥有自身创建的共享状态，不启动 WebUI 的可选后台服务。"""
import asyncio
from contextlib import asynccontextmanager

from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State


def cleanup():
    """
    清理 MCP 运行时状态。

    确认所有由 ProcessManager 追踪的工作进程完全退出后才关闭共享 Manager，
    若有进程未能正常退出则保留登记以供故障恢复。

    Raises:
        RuntimeError: 当部分工作进程无法停止时抛出。
    """
    with State.cleanup_lock:
        success = True
        for manager in ProcessManager.running_instances():
            try:
                success = (manager.stop() is not False) and success
            except Exception:
                success = False
        if not success:
            raise RuntimeError('MCP 工作进程尚未完全停止，保留共享状态')
        State.clearup()


@asynccontextmanager
async def lifespan(application):
    """
    MCP Starlette 应用程序生命周期管理器。

    管理共享 State 进程管理器的初始化，并在服务关闭时安全排空工具队列和子进程。

    Args:
        application: Starlette 应用实例。
    """
    owns_state = State.manager is None
    try:
        if owns_state:
            from module.persistence.database import initialize
            await asyncio.to_thread(initialize)
            await asyncio.to_thread(State.init)
            from module.runtime.updater import updater
            updater.event = State.manager.Event()
        yield
    finally:
        try:
            await application.state.tools.close()
        finally:
            if owns_state and State.manager is not None:
                await asyncio.to_thread(cleanup)
