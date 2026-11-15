"""部署配置事务及通用文件锁；独立部署器仅需标准库与 deploy 包。"""
import copy
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_guard = threading.Lock()
_locks = {}
_local = threading.local()


@contextmanager
def config_transaction(path, *, timeout=15):
    """对同一个配置文件串行化读改写；进程退出时操作系统自动释放锁。

    Args:
        path (str | Path): 配置文件路径。
        timeout (float): 等待进程间文件锁的秒数。

    Yields:
        None: 获得文件锁后进入上下文。

    Raises:
        TimeoutError: 等待配置事务锁超时。
    """
    key = str(Path(path).resolve())
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_local, 'held', set())
        if key in held:
            yield
            return
        lock_path = Path(key).with_suffix('.json.lock')
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a+b') as file:
            if file.tell() == 0:
                file.write(b'0')
                file.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    file.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('等待配置事务锁超时')
                    time.sleep(0.02)
            _local.held = held | {key}
            try:
                yield
            finally:
                _local.held = held
                file.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)


class DeployConfigTransaction:
    """将读取迁移、增量写入和运行时属性同步纳入同一文件事务。"""

    def _sync_config(self):
        """将字典配置同步到实例属性中并执行重定向。"""
        for key, value in self.config.items():
            if hasattr(type(self), key):
                object.__setattr__(self, key, value)
        self.config_redirect()

    def _load_config(self):
        """加载配置模板和用户配置文件。

        Returns:
            dict: 用户原始配置字典。
        """
        from deploy.utils import poor_yaml_read

        self.config_template = poor_yaml_read(self.template_file)
        origin = poor_yaml_read(self.file)
        self.config = {**self.config_template, **origin}
        self._sync_config()
        return origin

    def _write_config(self):
        """将当前配置写回配置文件。"""
        from deploy.utils import poor_yaml_write

        poor_yaml_write(self.config, self.file, template_file=self.template_file)

    def _remember_config(self):
        """深拷贝并记录当前加载的配置快照。"""
        self._loaded_config = copy.deepcopy(self.config)

    def _restore_config(self, state):
        """恢复实例状态字典。

        Args:
            state (dict): 原有的实例属性字典。
        """
        self.__dict__.clear()
        self.__dict__.update(state)

    def read(self):
        """读取和必要的迁移写入必须互斥，失败时恢复原内存状态。"""
        with config_transaction(self.file):
            before = self.__dict__.copy()
            try:
                origin = self._load_config()
                if self.config != origin:
                    self._write_config()
                self._remember_config()
            except BaseException:
                self._restore_config(before)
                raise

    def write(self):
        """只合并自上次读取以来的变更，保留其他对象已保存的字段。"""
        with config_transaction(self.file):
            baseline = getattr(self, '_loaded_config', {})
            updates = {key: value for key, value in self.config.items()
                       if key not in baseline or baseline[key] != value}
            removed = baseline.keys() - self.config.keys()
            before = self.__dict__.copy()
            try:
                origin = self._load_config()
                self._remember_config()
            except BaseException:
                self._restore_config(before)
                raise
            # 后续写入失败时恢复刚读取的磁盘状态，而非待保存的脏值。
            before = self.__dict__.copy()
            self.config = self.config.copy()
            try:
                self.config.update(updates)
                for key in removed:
                    self.config.pop(key, None)
                self._sync_config()
                if self.config != origin:
                    self._write_config()
                self._remember_config()
            except BaseException:
                self._restore_config(before)
                raise

    @contextmanager
    def transaction(self):
        """在最新配置上执行完整读改写；嵌套修改随最外层一起提交。

        Yields:
            dict: 当前配置字典。
        """
        with config_transaction(self.file):
            if getattr(self, '_config_transaction_active', False):
                yield self.config
                return
            self.read()
            before = self.__dict__.copy()
            self.config = copy.deepcopy(self.config)
            self._config_transaction_active = True
            try:
                yield self.config
                self.write()
            except BaseException:
                self._restore_config(before)
                raise
            finally:
                self._config_transaction_active = False

    def update_config(self, updates):
        """统一保存设置接口与属性赋值产生的增量修改。

        Args:
            updates (dict): 增量修改的键值字典。
        """
        with self.transaction() as values:
            values.update(updates)
