import functools
import random
import time
from functools import partial

from module.logger import logger as logging_logger

"""
从 `retry` 库复制并修改。
"""

try:
    from decorator import decorator
except ImportError:
    def decorator(caller):
        """将 caller 转换为装饰器。

        与 decorator 模块不同，不会保留函数签名。

        Args:
            caller: 调用函数，签名如 caller(f, *args, **kwargs)。
        """

        def decor(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return caller(f, *args, **kwargs)

            return wrapper

        return decor


def __retry_internal(f, exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1, jitter=0,
                     logger=logging_logger):
    """执行函数并在失败时重试。

    Args:
        f: 要执行的函数。
        exceptions: 需要捕获的异常或异常元组。默认为 Exception。
        tries: 最大尝试次数。默认为 -1（无限次）。
        delay: 重试之间的初始延迟秒数。默认为 0。
        max_delay: 延迟的最大值。默认为 None（无限制）。
        backoff: 重试延迟的乘数因子。默认为 1（无退避）。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        jitter: 重试延迟的额外秒数。默认为 0。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        logger: 失败时调用 logger.warning(fmt, error, delay)。
            默认为 retry.logging_logger。如果为 None 则禁用日志。

    Returns:
        f 函数的返回值。
    """
    _tries, _delay = tries, delay
    while _tries:
        try:
            return f()
        except exceptions as e:
            _tries -= 1
            if not _tries:
                # 与原版不同，抛出原始异常
                raise e

            if logger is not None:
                # 与原版不同，显示异常详情
                logger.exception(e)
                logger.warning(f'{type(e).__name__}({e}), retrying in {_delay} seconds...')

            time.sleep(_delay)
            _delay *= backoff

            if isinstance(jitter, tuple):
                _delay += random.uniform(*jitter)
            else:
                _delay += jitter

            if max_delay is not None:
                _delay = min(_delay, max_delay)


def retry(exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1, jitter=0, logger=logging_logger):
    """返回一个重试装饰器。

    Args:
        exceptions: 需要捕获的异常或异常元组。默认为 Exception。
        tries: 最大尝试次数。默认为 -1（无限次）。
        delay: 重试之间的初始延迟秒数。默认为 0。
        max_delay: 延迟的最大值。默认为 None（无限制）。
        backoff: 重试延迟的乘数因子。默认为 1（无退避）。
        jitter: 重试延迟的额外秒数。默认为 0。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        logger: 失败时调用 logger.warning(fmt, error, delay)。
            默认为 retry.logging_logger。如果为 None 则禁用日志。

    Returns:
        重试装饰器。
    """

    @decorator
    def retry_decorator(f, *fargs, **fkwargs):
        args = fargs if fargs else list()
        kwargs = fkwargs if fkwargs else dict()
        return __retry_internal(partial(f, *args, **kwargs), exceptions, tries, delay, max_delay, backoff, jitter,
                                logger)

    return retry_decorator


def retry_call(f, fargs=None, fkwargs=None, exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1,
               jitter=0,
               logger=logging_logger):
    """调用函数并在失败时重新执行。

    Args:
        f: 要执行的函数。
        fargs: 函数的位置参数。
        fkwargs: 函数的关键字参数。
        exceptions: 需要捕获的异常或异常元组。默认为 Exception。
        tries: 最大尝试次数。默认为 -1（无限次）。
        delay: 重试之间的初始延迟秒数。默认为 0。
        max_delay: 延迟的最大值。默认为 None（无限制）。
        backoff: 重试延迟的乘数因子。默认为 1（无退避）。
        jitter: 重试延迟的额外秒数。默认为 0。
            如果是数字则为固定值，如果是元组 (min, max) 则为随机范围。
        logger: 失败时调用 logger.warning(fmt, error, delay)。
            默认为 retry.logging_logger。如果为 None 则禁用日志。

    Returns:
        f 函数的返回值。
    """
    args = fargs if fargs else list()
    kwargs = fkwargs if fkwargs else dict()
    return __retry_internal(partial(f, *args, **kwargs), exceptions, tries, delay, max_delay, backoff, jitter, logger)
