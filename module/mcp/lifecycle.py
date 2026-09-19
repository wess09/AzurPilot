"""独立 MCP 只拥有自身创建的共享状态，不启动 WebUI 的可选后台服务。"""
import asyncio
from contextlib import asynccontextmanager

from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State


def cleanup():
    """确认工作进程全部退出后才关闭 Manager，失败时保留登记供恢复。"""
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
    owns_state = State.manager is None
    try:
        if owns_state:
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
