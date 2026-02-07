import os
import sys  # 核心修复：新增sys模块导入
import threading
from multiprocessing import Event, Process, set_start_method
from typing import Optional

from module.logger import logger
from module.webui.setting import State


def func(ev: Optional[Event]):  # 修正：改为multiprocessing.Event（Optional适配None传参）
    import argparse
    import asyncio

    import uvicorn

    # 修复：macOS下asyncio兼容配置（补充）
    if sys.platform == "darwin":
        # 禁用fork安全检查，解决Mach端口冲突
        os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        # macOS下asyncio事件循环兼容
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    elif sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    State.restart_event = ev

    parser = argparse.ArgumentParser(description="Alas web service")
    parser.add_argument(
        "--host",
        type=str,
        help="Host to listen. Default to WebuiHost in deploy setting",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="Port to listen. Default to WebuiPort in deploy setting",
    )
    parser.add_argument(
        "-k", "--key", type=str, help="Password of alas. No password by default"
    )
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="Use jsdelivr cdn for pywebio static files (css, js). Self host cdn by default.",
    )
    parser.add_argument(
        "--electron", action="store_true", help="Runs by electron client."
    )
    parser.add_argument(
        "--ssl-key", dest="ssl_key", type=str, help="SSL key file path for HTTPS support"
    )
    parser.add_argument(
        "--ssl-cert", type=str, help="SSL certificate file path for HTTPS support"
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="Run alas by config names on startup",
    )
    args, _ = parser.parse_known_args()

    host = args.host or State.deploy_config.WebuiHost or "0.0.0.0"
    port = args.port or int(State.deploy_config.WebuiPort) or 22267
    ssl_key = args.ssl_key or State.deploy_config.WebuiSSLKey
    ssl_cert = args.ssl_cert or State.deploy_config.WebuiSSLCert
    ssl = ssl_key is not None and ssl_cert is not None
    State.electron = args.electron

    logger.hr("Launcher config")
    logger.attr("Host", host)
    logger.attr("Port", port)
    logger.attr("SSL", ssl)
    logger.attr("Electron", args.electron)
    logger.attr("Reload", ev is not None)

    if State.electron:
        # https://github.com/LmeSzinc/AzurLaneAutoScript/issues/2051
        logger.info("Electron detected, remove log output to stdout")
        from module.logger import console_hdlr
        logger.removeHandler(console_hdlr)

    if ssl_cert is None and ssl_key is not None:
        logger.error("SSL key provided without certificate. Please provide both SSL key and certificate.")
    elif ssl_key is None and ssl_cert is not None:
        logger.error("SSL certificate provided without key. Please provide both SSL key and certificate.")

    try:  # 新增：捕获uvicorn运行时异常，避免子进程崩溃无日志
        if ssl:
            uvicorn.run(
                "module.webui.app:app",
                host=host,
                port=port,
                factory=True,
                ssl_keyfile=ssl_key,
                ssl_certfile=ssl_cert
            )
        else:
            uvicorn.run("module.webui.app:app", host=host, port=port, factory=True)
    except Exception as e:
        logger.error(f"Uvicorn service crashed: {str(e)}")
        raise  # 抛出异常让父进程感知


def update_deploy_repository():
    """
    自动修改 config/deploy.yaml 中的 Repository 为指定地址，并强制启用 AutoUpdate
    """
    from pathlib import Path
    try:
        from module.config.utils import read_file, write_file
        
        deploy_path = Path(__file__).parent / 'config' / 'deploy.yaml'
        target_repo = 'https://git.nanoda.work/git/AzurLaneAutoScript'
        
        if deploy_path.exists():
            config = read_file(str(deploy_path))
            
            current_repo = config.get('Deploy', {}).get('Git', {}).get('Repository', '')
            current_auto_update = config.get('Deploy', {}).get('Git', {}).get('AutoUpdate', True)
            
            repo_changed = current_repo != target_repo
            auto_update_changed = current_auto_update != True
            
            if repo_changed or auto_update_changed:
                if repo_changed:
                    config['Deploy']['Git']['Repository'] = target_repo
                    logger.info(f'Repository updated: {current_repo} -> {target_repo}')
                if auto_update_changed:
                    config['Deploy']['Git']['AutoUpdate'] = True
                    logger.info(f'AutoUpdate updated: {current_auto_update} -> True')
                write_file(str(deploy_path), config)
            else:
                logger.info('Repository and AutoUpdate already set to target values')
        else:
            logger.warning(f'Deploy config not found: {deploy_path}')
    except Exception as e:
        logger.warning(f'Failed to update repository: {e}')


if __name__ == "__main__":
    # 自动更新 Repository 配置
    update_deploy_repository()
    
    # 核心修复：强制设置multiprocessing启动方式为spawn（解决macOS fork导致的Mach端口崩溃）
    try:
        # 优先设置spawn，兼容多平台
        set_start_method("spawn", force=True)
        # macOS下额外添加环境变量，禁用fork安全检查
        if os.name == "posix" and sys.platform == "darwin":
            os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    except RuntimeError:
        logger.warning("Failed to set spawn start method, may use fork (not recommended on macOS)")

    if State.deploy_config.EnableReload:
        should_exit = False
        while not should_exit:
            event = Event()
            process = Process(target=func, args=(event,))
            process.start()
            logger.info(f"Started Alas web service (PID: {process.pid})")
            
            while not should_exit:
                try:
                    # 等待重启事件（1秒超时，避免阻塞）
                    restart_triggered = event.wait(1)
                except KeyboardInterrupt:
                    logger.info("Received KeyboardInterrupt, exiting...")
                    should_exit = True
                    break
                except Exception as e:
                    logger.error(f"Error waiting for restart event: {str(e)}")
                    should_exit = True
                    break

                if restart_triggered:
                    logger.info("Restart event triggered, killing current service...")
                    process.kill()
                    process.join(timeout=5)  # 新增：等待子进程退出，避免僵尸进程
                    if process.is_alive():
                        logger.warning("Failed to kill service process, force exit")
                    break
                elif not process.is_alive():
                    logger.error("Alas web service exited unexpectedly")
                    should_exit = True
                # 进程仍存活则继续循环

            # 确保子进程完全退出
            if process.is_alive():
                process.terminate()
                process.join(timeout=3)
        
        # 最终清理：确保子进程退出
        if process.is_alive():
            process.kill()
            process.join()
        logger.info("Alas web service exited successfully")
    else:
        # 非重启模式直接运行
        func(None)
