"""设备后端的有界重试骨架；后端只选择恢复动作和耗尽后的异常类型。"""

import time
from functools import partial, wraps

from module.device.method.utils import (
    RETRY_TRIES,
    handle_adb_error,
    handle_image_truncated,
    handle_unknown_host_service,
    retry_sleep,
)
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.logger import logger


def retry_backend(
    func=None, *, recover, label, on_exhausted=RequestHumanTakeover,
    before_attempt=None, passthrough=(),
):
    """保留后端原有时序：等待、执行恢复动作、再次调用原方法。

    recover 返回下一轮执行的恢复函数；返回 None 表示错误不能自动处理。
    显式接管、已分类的离线异常和 passthrough 异常原样抛出，包括恢复动作
    自身抛出的异常。方法名称仅用于日志，不参与恢复策略选择。
    """
    if func is None:
        return partial(
            retry_backend, recover=recover, label=label, on_exhausted=on_exhausted,
            before_attempt=before_attempt, passthrough=passthrough,
        )

    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        init = None
        last_error = None
        for trial in range(RETRY_TRIES):
            if before_attempt is not None:
                before_attempt(trial, args, kwargs)
            try:
                if init is not None:
                    time.sleep(retry_sleep(trial))
                    init()
                return func(self, *args, **kwargs)
            except (RequestHumanTakeover, EmulatorNotRunningError):
                raise
            except passthrough:
                logger.critical(f'[{label}] {func.__name__}() 参数错误，不执行设备恢复')
                raise
            except Exception as error:
                last_error = error
                init = recover(self, error, trial)
                if init is None:
                    logger.critical(f'[{label}] {func.__name__}() 无法自动恢复')
                    raise RequestHumanTakeover(str(error)) from error

        logger.critical(f'[{label}] 重试 {func.__name__}() 失败')
        raise on_exhausted(f'{func.__name__}() 重试失败') from last_error

    return retry_wrapper


def retry_without_recovery():
    """保持退避等待，但不执行额外恢复动作。"""


def recover_unknown(error):
    logger.exception(error)
    return retry_without_recovery


def recover_truncated_image(device, error):
    # 截断计数及阈值恢复仍在异常发生时执行，不延后到下一次尝试。
    handle_image_truncated(device, error)
    return retry_without_recovery


def recover_adb(device, error, *, reconnect=None):
    """选择 ADB 恢复动作，允许触控后端在重连后清理端口和 builder。"""
    reconnect = device.adb_reconnect if reconnect is None else reconnect
    if isinstance(error, (ConnectionResetError, ConnectionAbortedError)):
        logger.error(error)
        return reconnect
    if handle_adb_error(error):
        return reconnect
    if handle_unknown_host_service(error):
        def restart_server():
            device.adb_start_server()
            reconnect()
        return restart_server
    return None
