"""统一连接、事务与安装级迁移入口。"""
import atexit
import os
import random
import sqlite3
import sys
import threading
import time
import weakref
from contextlib import contextmanager, closing
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from uuid import uuid4

from module.config.transaction import config_transaction

VERSION = 1
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / 'config'
# 单次取锁等待片段：写锁争用时按片段反复尝试，而不是一次等满整个预算。
BUSY_WAIT_SLICE = 0.05
# 片段上限，避免单次 BEGIN 等待吞掉全部退避机会。
BUSY_WAIT_SLICE_MAX = 0.5
# 片段之间的退避基数，实际睡眠带抖动，减少多进程同时重试的碰撞。
BUSY_WAIT_BACKOFF = 0.03
# 等待超过该阈值输出一条诊断日志，说明谁在等锁、等了多久。
BUSY_WAIT_NOTICE = 1.0
# 每线程可复用的嵌套连接层数：写事务里再开只读事务需要第二层。
MAX_SESSION_DEPTH = 2
# 全进程复用的连接上限，超过后退化为一次性连接，避免线程池放大文件句柄。
MAX_REUSED_CONNECTIONS = 16

_configured_directory = Path(os.environ.get('AZURPILOT_CONFIG_DIR', DEFAULT_DIRECTORY)).absolute()
_directory = ContextVar('business_database_directory', default=None)


def current_directory():
    """返回当前业务调用绑定的配置目录。"""
    return _directory.get() or _configured_directory
_databases = {}
# 直接构造的数据库实例（备份恢复、离线工具、测试）也需要在替换库文件前释放句柄。
# 用强引用登记：连接存放在 threading.local 里，实例被回收后句柄仍会存活。
_instances = set()
_guard = threading.RLock()


def is_busy(error):
    """判断异常是否表示写锁争用，兼容缺少 sqlite_errorcode 的解释器。"""
    code = getattr(error, 'sqlite_errorcode', None)
    if code is None:
        message = str(error).lower()
        return 'locked' in message or 'busy' in message
    return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def caller_label(depth=2):
    """取调用栈中的函数名作为取锁诊断标签，取不到时返回占位名。"""
    try:
        return sys._getframe(depth).f_code.co_name
    except (AttributeError, ValueError):
        return 'unknown'


def acquire_write(connection, budget=10.0, label=None):
    """在总预算内分段重试 `BEGIN IMMEDIATE`，只重试取锁语句本身。

    Args:
        connection: 已建立的 SQLite 连接。
        budget: 总等待预算（秒）；小于等于 0 时只尝试一次，不做重试。
        label: 诊断标签，通常为发起写入的函数名。

    Raises:
        sqlite3.OperationalError: 预算耗尽仍未能取得写锁时抛出最后一次原始异常。
    """
    total = max(0.0, float(budget))
    started = time.perf_counter()
    attempts = 0
    last_error = None
    while True:
        remaining = total - (time.perf_counter() - started)
        if last_error is not None and remaining <= 0:
            raise last_error
        slice_seconds = 0.0 if total <= 0 else min(
            BUSY_WAIT_SLICE_MAX, max(BUSY_WAIT_SLICE, remaining))
        connection.execute(f'PRAGMA busy_timeout={int(slice_seconds * 1000)}')
        try:
            connection.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as error:
            if not is_busy(error):
                raise
            attempts += 1
            last_error = error
            remaining = total - (time.perf_counter() - started)
            if total <= 0 or remaining <= 0:
                raise
            delay = min(BUSY_WAIT_BACKOFF * attempts, remaining)
            time.sleep(delay * (0.5 + random.random()))
            continue
        waited = time.perf_counter() - started
        if waited >= BUSY_WAIT_NOTICE:
            from module.logger import logger
            database = getattr(connection, 'database_path', None)
            logger.warning('[存储] 写锁等待 %.2f 秒后取得：%s（%s）',
                           waited, label or caller_label(2), database or 'unknown')
        return


class ReusableConnection(sqlite3.Connection):
    """可复用连接：允许附加诊断属性，并支持弱引用登记。"""


class ClosingConnection(sqlite3.Connection):
    """进入上下文即取得写锁，提交和回滚之后都释放文件句柄。"""

    def __enter__(self):
        """进入连接上下文并取得业务事务。"""
        try:
            if not self.in_transaction:
                acquire_write(self, getattr(self, 'write_budget', 10.0), caller_label(2))
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *args):
        """结束连接上下文并释放事务相关资源。"""
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def register_instance(connection, instance):
    """在总库中登记实例身份与关联范围。"""
    if instance is not None:
        if not isinstance(instance, str):
            raise TypeError('实例名必须是字符串')
        connection.execute('INSERT OR IGNORE INTO storage_instances(instance) VALUES(?)', (instance,))


def create_schema(connection):
    """执行版本化模式定义以初始化数据库。"""
    connection.executescript(Path(__file__).with_name('schema_v1.sql').read_text(encoding='utf-8'))
    connection.execute(f'PRAGMA user_version={VERSION}')


class BusinessDatabase:
    """一个配置目录对应一个普通总库，所有连接都经过迁移入口。"""

    def __init__(self, config_directory=None):
        """初始化数据库连接配置及安装路径。"""
        self.directory = Path(config_directory or current_directory()).absolute()
        self.path = self.directory / 'azurpilot.db'
        self.marker = self.directory / 'azurpilot.migrated'
        self.legacy_sources = {}
        self._ready = False
        self._lock = threading.RLock()
        # 长连接复用：每线程按嵌套深度持有连接，close_all() 后按代次失效重建。
        self._local = threading.local()
        self._generation = 0
        self._reused = weakref.WeakSet()
        self._reused_guard = threading.Lock()
        with _guard:
            _instances.add(self)

    def add_legacy_source(self, kind, path):
        """登记额外的历史数据迁移来源。"""
        path = Path(path).absolute()
        with self._lock:
            sources = self.legacy_sources.setdefault(kind, set())
            sources.add(path)

    def ensure_ready(self):
        """检查总库与迁移状态，必要时完成首次初始化。"""
        if self._ready and self.path.is_file():
            return
        from module.logger import logger
        started = time.perf_counter()
        logger.info('[存储] 等待总库初始化锁：%s', self.path)
        with self._lock, config_transaction(self.directory / '.azurpilot-install'):
            logger.info('[存储] 已取得安装锁，等待 %.2f 秒', time.perf_counter() - started)
            if self.path.is_symlink():
                raise ValueError('总库路径不能是符号链接')
            if self.path.is_file():
                logger.info('[存储] 检查已有总库的版本与迁移记录：%s', self.path)
                with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as connection:
                    version = connection.execute('PRAGMA user_version').fetchone()[0]
                    if version != VERSION:
                        raise ValueError(f'不支持的总库版本：{version}')
                    row = connection.execute('SELECT source_digest FROM storage_migrations WHERE version=?', (VERSION,)).fetchone()
                    if row is None or connection.execute('SELECT MAX(version) FROM storage_migrations').fetchone()[0] != version:
                        raise ValueError('总库缺少迁移完成记录')
                    journal_mode = connection.execute('PRAGMA journal_mode').fetchone()[0]
                    if not self.marker.exists():
                        logger.info('[存储] 补齐迁移完成标记')
                        self._write_marker(row[0])
                # 历史库可能仍是回滚日志模式：读事务会被写阻塞，这里一次性切换。
                if str(journal_mode).lower() != 'wal':
                    self._enable_wal()
                logger.info('[存储] 总库 v%s 已完成迁移，无需再次解密旧数据', VERSION)
            else:
                if self.marker.exists():
                    raise FileNotFoundError('已迁移的普通总库丢失，请从备份恢复，不能重新导入旧数据')
                from module.persistence.migration import migrate
                migrate(self)
            self._ready = True
            logger.info('[存储] 总库已就绪，耗时 %.2f 秒：%s', time.perf_counter() - started, self.path)

    def _enable_wal(self):
        """把已有总库切换为 WAL，失败只记录警告不阻断启动。"""
        from module.logger import logger
        try:
            with closing(sqlite3.connect(self.path, timeout=10)) as connection:
                mode = connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]
            logger.info('[存储] 总库日志模式已切换为 %s：%s', mode, self.path)
        except sqlite3.Error as error:
            logger.warning('[存储] 总库日志模式切换失败，继续使用当前模式：%s', type(error).__name__)

    def _write_marker(self, digest):
        """原子写入与总库对应的迁移完成标记。"""
        temporary = self.marker.with_suffix('.migrated.tmp')
        with temporary.open('w', encoding='utf-8') as file:
            file.write(f'{VERSION}\n{digest}\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.marker)

    def connect(self, *, timeout=10.0, readonly=False, factory=ClosingConnection):
        """返回带事务生命周期管理的 SQLite 连接。"""
        self.ensure_ready()
        path = self.path.as_uri() + '?mode=ro' if readonly else self.path
        # 复用连接由每线程栈独占使用；close_all() 可能在其它线程关闭句柄，故不限制线程。
        connection = sqlite3.connect(path, uri=readonly, timeout=timeout, factory=factory,
                                     check_same_thread=False)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute(f'PRAGMA busy_timeout={int(timeout * 1000)}')
            try:
                connection.database_path = str(self.path)
                connection.write_budget = timeout
            except AttributeError:
                # 标准库 sqlite3.Connection 没有 __dict__，诊断属性只对子类生效。
                pass
            return connection
        except BaseException:
            connection.close()
            raise

    def _file_identity(self):
        """返回库文件身份，用于识别被替换或删除的库。"""
        try:
            info = self.path.stat()
        except OSError:
            return None
        return info.st_dev, info.st_ino

    def _open_reused(self):
        """建立并登记一个可复用的长连接；超过上限时返回 None 退化为一次性连接。"""
        with self._reused_guard:
            if len(self._reused) >= MAX_REUSED_CONNECTIONS:
                return None
        connection = self.connect(factory=ReusableConnection)
        with self._reused_guard:
            self._reused.add(connection)
        return connection

    def _borrow(self, depth):
        """取当前线程指定嵌套深度的长连接，文件被替换或关闭后自动重建。"""
        slots = getattr(self._local, 'slots', None)
        if slots is None:
            slots = self._local.slots = []
        identity = self._file_identity()
        if depth < len(slots):
            entry = slots[depth]
            if entry[0] == self._generation and entry[1] == identity and entry[2] is not None:
                return entry[2]
            if entry[2] is not None:
                try:
                    entry[2].close()
                except sqlite3.Error:
                    pass
        connection = self._open_reused()
        entry = [self._generation, identity, connection]
        if depth < len(slots):
            slots[depth] = entry
        else:
            slots.append(entry)
        return connection

    @staticmethod
    def _prepare(connection, write, timeout):
        """借用连接后恢复本次事务需要的会话状态。"""
        connection.execute(f'PRAGMA query_only={"OFF" if write else "ON"}')
        connection.execute(f'PRAGMA busy_timeout={int(max(0.0, timeout) * 1000)}')

    @contextmanager
    def session(self, *, write=True, timeout=10.0, label=None):
        """在复用连接上执行一个事务；退出时提交或回滚后归还连接。"""
        self.ensure_ready()
        label = label or caller_label(2)
        depth = getattr(self._local, 'depth', 0)
        self._local.depth = depth + 1
        connection = None
        one_shot = False
        try:
            if depth < MAX_SESSION_DEPTH:
                connection = self._borrow(depth)
            if connection is None:
                one_shot = True
                connection = self.connect(timeout=timeout, factory=ReusableConnection)
            self._prepare(connection, write, timeout)
            if write:
                acquire_write(connection, timeout, label)
            else:
                connection.execute('BEGIN')
            yield connection
            connection.commit()
        except BaseException:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise
        finally:
            self._local.depth = depth
            if connection is not None:
                if one_shot:
                    connection.close()
                elif connection.in_transaction:
                    try:
                        connection.rollback()
                    except sqlite3.Error:
                        pass

    @contextmanager
    def transaction(self, *, write=True, timeout=10.0, label=None):
        """为业务操作提供只读或可写的事务上下文。"""
        with self.session(write=write, timeout=timeout, label=label) as connection:
            yield connection

    def close_all(self):
        """关闭本库所有可复用连接，用于替换或删除库文件前释放句柄。"""
        with self._reused_guard:
            self._generation += 1
            connections = list(self._reused)
            self._reused = weakref.WeakSet()
        for connection in connections:
            try:
                connection.close()
            except sqlite3.Error as error:
                from module.logger import logger
                logger.warning('[存储] 关闭复用连接失败：%s', type(error).__name__)

    def backup(self, target):
        """创建通过完整性校验的业务数据库备份。"""
        target = Path(target)
        if target.resolve() == self.path.resolve() or target.is_symlink():
            raise ValueError('备份目标不能覆盖普通总库或符号链接')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
        try:
            with closing(self.connect(readonly=True, factory=sqlite3.Connection)) as source, closing(sqlite3.connect(temporary)) as destination:
                destination.execute('PRAGMA synchronous=FULL')
                source.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or destination.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('备份未通过数据库检查')
            os.replace(temporary, target)
        finally:
            for suffix in ('', '-wal', '-shm'):
                temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)


def get_database(config_directory=None):
    """取得配置目录对应的共享数据库实例。"""
    directory = Path(config_directory or current_directory()).absolute()
    key = os.path.normcase(str(directory.resolve()))
    with _guard:
        return _databases.setdefault(key, BusinessDatabase(directory))


def for_legacy_path(path, kind):
    """保留旧路径注入点作为迁移来源，实际写入同目录总库。"""
    path = Path(path).absolute()
    database = get_database() if path.parent == DEFAULT_DIRECTORY else get_database(path.parent)
    if path.parent == DEFAULT_DIRECTORY:
        path = database.directory / path.name
    database.add_legacy_source(kind, path)
    return database


def close_all(config_directory=None):
    """关闭业务总库的可复用连接；传入目录时只处理该目录。"""
    with _guard:
        databases = set(_databases.values()) | set(_instances)
    if config_directory is not None:
        target = os.path.normcase(str(Path(config_directory).resolve()))
        databases = {item for item in databases if os.path.normcase(str(item.directory.resolve())) == target}
    for database in databases:
        database.close_all()


def initialize(config_directory=None):
    """运行入口在创建业务 worker 前调用，失败必须中止启动。"""
    global _configured_directory
    if config_directory is not None:
        _configured_directory = Path(config_directory).absolute()
        _directory.set(_configured_directory)
    database = get_database()
    database.ensure_ready()
    return database


@contextmanager
def use_database(database):
    """业务服务的调用范围显式绑定同一个配置目录。"""
    token = _directory.set(database.directory)
    try:
        yield database
    finally:
        _directory.reset(token)


def configured_database(function):
    """适配保留参数契约的函数入口和服务方法。"""
    @wraps(function)
    def wrapped(owner, *args, **kwargs):
        """在指定配置目录下执行被包装的业务调用。"""
        configs = getattr(owner, 'configs', owner)
        with use_database(get_database(getattr(configs, 'directory', None))):
            return function(owner, *args, **kwargs)
    return wrapped


atexit.register(close_all)
