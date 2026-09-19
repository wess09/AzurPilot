"""与界面会话无关的运行服务生命周期。"""
from module.logger import logger
from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State
from module.runtime.task_handler import TaskHandler
from module.ocr.rpc import stop_ocr_server_process
from module.runtime.remote_access import RemoteAccess

task_handler = TaskHandler()


def startup(runs=None):
    """初始化共享进程登记与可选后台服务。"""
    from module.runtime.updater import updater
    State.init()
    updater.event = State.manager.Event()
    if updater.delay > 0:
        task_handler.add(updater.check_update_loop(), 1)
    task_handler.add(updater.schedule_update(), 86400)
    task_handler.start()
    if State.deploy_config.StartOcrServer:
        from module.ocr.rpc import start_ocr_server_process
        start_ocr_server_process(State.deploy_config.OcrServerPort)
    if State.deploy_config.EnableRemoteAccess:
        task_handler.add(RemoteAccess.keep_ssh_alive(), 60)
    ProcessManager.restart_processes(instances=runs, ev=updater.event)


def clearup():
    """逐项停止服务，即使某项失败也继续回收其他工作进程。"""
    with State.cleanup_lock:
        if State._clearup:
            return True
        actions = [task_handler.stop, stop_ocr_server_process, RemoteAccess.kill_ssh_process]
        success = True
        try:
            actions.extend(instance.stop for instance in ProcessManager.running_instances())
        except Exception:
            logger.exception('无法枚举运行进程，保留共享状态供父监督器回收')
            success = False
        for action in actions:
            try:
                success = (action() is not False) and success
            except Exception:
                logger.exception('运行服务资源回收失败')
                success = False
        if success:
            State.clearup()
        return success
