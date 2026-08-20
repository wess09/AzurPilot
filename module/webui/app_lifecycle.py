"""WebUIASGI生命周期管理"""

from module.webui.app_dependencies import (
    ProcessManager,
    RemoteAccess,
    State,
    close_discord_rpc,
    init_discord_rpc,
    lang,
    logger,
    os,
    start_ocr_server_process,
    stop_ocr_server_process,
    task_handler,
    updater,
    wait_for_ocr_server,
)

from module.webui.app_helpers import (
    is_demo_mode,
)


def _clearup_step(name, handler) -> bool:
    """执行单项清理；一项失败不应阻断其余资源回收。"""
    try:
        return handler() is not False
    except Exception as exc:
        logger.exception_context(
            title=f'WebUI 清理失败: {name}',
            exc=exc,
            impact='其余 WebUI 资源仍会继续清理。',
            action='检查对应资源的退出日志，确认是否遗留子进程。',
            level=40,
        )
        return False


def startup() -> None:
    """初始化 WebUI 进程级后台服务。"""
    State.init()
    lang.reload()
    updater.event = State.manager.Event()
    if updater.delay > 0:
        task_handler.add(updater.check_update_loop(), 1)
    task_handler.add(updater.schedule_update(), 86400)
    task_handler.start()
    if State.deploy_config.DiscordRichPresence:
        init_discord_rpc()
    if not is_demo_mode():
        if State.deploy_config.StartOcrServer:
            start_ocr_server_process(State.deploy_config.OcrServerPort)
        if State.deploy_config.UseOcrServer:
            timeout = 30 if State.deploy_config.StartOcrServer else 3
            if not wait_for_ocr_server(
                State.deploy_config.OcrClientAddress,
                timeout=timeout,
            ):
                logger.warning(
                    "[OCR-RPC] 远程 OCR 未就绪；实例首次识别可能回退到本地模型，"
                    "这会增加每实例内存。"
                )
    if State.deploy_config.EnableRemoteAccess and (
        State.deploy_config.Password is not None or os.environ.get("DEMO") == "1"
    ):
        task_handler.add(RemoteAccess.keep_ssh_alive(), 60)


def clearup() -> bool:
    """停止 WebUI 进程级资源，避免热重载遗留子进程。"""
    with State.cleanup_lock:
        if State._clearup:
            return True

        logger.info("[WebUI-生命周期] 开始清理")
        success = _clearup_step("任务处理器", task_handler.stop)

        for name, handler in (
            ("远程访问", RemoteAccess.kill_ssh_process),
            ("Discord RPC", close_discord_rpc),
        ):
            success = _clearup_step(name, handler) and success

        try:
            instances = ProcessManager.running_instances()
        except Exception as exc:
            logger.exception_context(
                title='WebUI 清理失败: 枚举运行实例',
                exc=exc,
                impact='无法确认所有 AzurPilot 工作进程是否已停止。',
                action='检查 WebUI 进程注册表和 Manager 服务状态。',
                level=40,
            )
            instances = []
            success = False

        for alas in instances:
            success = _clearup_step(f"AzurPilot 实例 {alas.config_name}", alas.stop) and success

        success = _clearup_step("OCR 服务", stop_ocr_server_process) and success

        if success:
            try:
                State.clearup()
            except Exception as exc:
                logger.exception_context(
                    title='WebUI 清理失败: 共享状态',
                    exc=exc,
                    impact='Manager 未能完全关闭，父进程将通过进程树终止兜底。',
                    action='检查 Manager 服务和系统进程权限。',
                    level=40,
                )
                success = False
        else:
            logger.error("WebUI 清理未完成，保留 Manager 直到父进程终止进程树")
        logger.info("[WebUI-生命周期] Alas 已关闭")
        return success
