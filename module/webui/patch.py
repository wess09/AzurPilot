"""
模拟器运行时的猴子补丁。

- 限制线程池大小，防止 aiofiles 创建过多线程
- 修正 Python 3.7 下 subprocess._communicate 的 IndexError
- 统一 mimetype 表，避免读取用户环境中的污染数据
"""

import asyncio
from functools import partial, wraps

from module.logger import logger
from module.webui.setting import cached_class_property


class CachedThreadPoolExecutor:
    """缓存的线程池执行器，作为全局单例供 loop.run_in_executor 使用。"""

    @cached_class_property
    def executor(cls):
        from concurrent.futures.thread import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=5)
        logger.info('Patched ThreadPoolExecutor created')
        return pool


def wrap(func):
    """将同步函数包装为异步函数，在 CachedThreadPoolExecutor 中执行。"""
    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()
        if executor is None:
            executor = CachedThreadPoolExecutor.executor
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, pfunc)

    return run


def patch_executor():
    """
    限制 loop.run_in_executor 的线程池大小。

    防止 starlette.staticfiles → aiofiles 在每次请求时创建新线程，
    导致线程数持续增长。
    """
    try:
        import aiofiles
    except ImportError:
        return

    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.set_default_executor(CachedThreadPoolExecutor.executor)


def patch_mimetype():
    """
    修补 mimetype 数据库，使用内置表而非从环境变量读取。

    默认情况下，mimetype 会读取用户环境中配置的 MIME 类型表。
    这对服务器环境是合理的，但 AzurPilot 部署在用户本地机器上，
    环境可能已被污染。为保证所有部署行为一致，仅使用内置 MIME 表。
    """
    import mimetypes
    # 标记为已初始化，阻止后续从环境读取
    mimetypes.inited = True
    # 创建全新的干净实例
    db = mimetypes.MimeTypes(filenames=())
    mimetypes._db = db
    # 用内置数据覆盖全局变量
    mimetypes.encodings_map = db.encodings_map
    mimetypes.suffix_map = db.suffix_map
    mimetypes.types_map = db.types_map[True]
    mimetypes.common_types = db.types_map[False]


def fix_py37_subprocess_communicate():
    """
    为 Windows Python 3.7 的 subprocess.Popen._communicate 打补丁。

    修复 IndexError: list index out of range 错误。
    此 bug 在 Python >= 3.8 中已修复，此处反向移植该修复。

    参考：
        https://github.com/LmeSzinc/AzurLaneAutoScript/issues/5226
        https://bugs.python.org/issue43423
        https://github.com/python/cpython/pull/24777
    """
    import subprocess
    import sys
    import threading

    if sys.platform != 'win32' or sys.version_info[:2] != (3, 7):
        return

    def _communicate_fixed(self, input, endtime, orig_timeout):
        # 启动读取线程，将输出收集到列表中（如果尚未启动）
        if self.stdout and not hasattr(self, "_stdout_buff"):
            self._stdout_buff = []
            self.stdout_thread = \
                threading.Thread(target=self._readerthread,
                                 args=(self.stdout, self._stdout_buff))
            self.stdout_thread.daemon = True
            self.stdout_thread.start()
        if self.stderr and not hasattr(self, "_stderr_buff"):
            self._stderr_buff = []
            self.stderr_thread = \
                threading.Thread(target=self._readerthread,
                                 args=(self.stderr, self._stderr_buff))
            self.stderr_thread.daemon = True
            self.stderr_thread.start()

        if self.stdin:
            self._stdin_write(input)

        # 等待读取线程完成，超时则保留线程以便后续再次调用 communicate
        if self.stdout is not None:
            self.stdout_thread.join(self._remaining_time(endtime))
            if self.stdout_thread.is_alive():
                raise subprocess.TimeoutExpired(self.args, orig_timeout)
        if self.stderr is not None:
            self.stderr_thread.join(self._remaining_time(endtime))
            if self.stderr_thread.is_alive():
                raise subprocess.TimeoutExpired(self.args, orig_timeout)

        # 收集输出并关闭管道
        stdout = None
        stderr = None
        if self.stdout:
            stdout = self._stdout_buff
            self.stdout.close()
        if self.stderr:
            stderr = self._stderr_buff
            self.stderr.close()

        # 将列表转换为字符串（修复点）
        stdout = stdout[0] if stdout else None
        stderr = stderr[0] if stderr else None

        return (stdout, stderr)

    subprocess.Popen._communicate = _communicate_fixed
