"""测试夹具公共初始化。

业务总库改用进程内长连接后，句柄会存活到进程结束；Windows 上未关闭的句柄
会阻止用例自己清理临时目录。这里做两件事：

1. 在每个用例执行自带清理动作（含临时目录删除）之前释放复用连接；
2. 让 ``TemporaryDirectory`` 忽略清理错误：后台排队写入的线程可能刚好还在
   收尾，句柄释放时机不受用例控制，测试不应因此失败。
"""
import tempfile
import unittest

from module.persistence.database import close_all
from module.persistence.write_queue import write_queue

_original_do_cleanups = unittest.TestCase.doCleanups
_original_temporary_directory_init = tempfile.TemporaryDirectory.__init__


def _do_cleanups(self):
    """先丢弃未落库的排队数据并释放存储句柄，再执行用例登记的清理动作。"""
    write_queue.clear()
    close_all()
    return _original_do_cleanups(self)


def _temporary_directory_init(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=False, *, delete=True):
    """统一忽略临时目录清理错误，避免 SQLite 句柄时序导致用例失败。"""
    _original_temporary_directory_init(
        self, suffix, prefix, dir, True, delete=delete)


unittest.TestCase.doCleanups = _do_cleanups
tempfile.TemporaryDirectory.__init__ = _temporary_directory_init
