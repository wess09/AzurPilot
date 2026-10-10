"""统一连接、事务与安装级迁移入口。"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager, closing
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from uuid import uuid4

from module.config.transaction import config_transaction

VERSION = 1
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / 'config'
_configured_directory = Path(os.environ.get('AZURPILOT_CONFIG_DIR', DEFAULT_DIRECTORY)).absolute()
_directory = ContextVar('business_database_directory', default=None)


def current_directory():
    """返回当前业务调用绑定的配置目录。"""
    return _directory.get() or _configured_directory
_databases = {}
_guard = threading.RLock()


class ClosingConnection(sqlite3.Connection):
    """进入上下文即取得写锁，提交和回滚之后都释放文件句柄。"""

    def __enter__(self):
        """进入连接上下文并取得业务事务。"""
        try:
            if not self.in_transaction:
                self.execute('BEGIN IMMEDIATE')
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
                    if not self.marker.exists():
                        logger.info('[存储] 补齐迁移完成标记')
                        self._write_marker(row[0])
                logger.info('[存储] 总库 v%s 已完成迁移，无需再次解密旧数据', VERSION)
            else:
                if self.marker.exists():
                    raise FileNotFoundError('已迁移的普通总库丢失，请从备份恢复，不能重新导入旧数据')
                from module.persistence.migration import migrate
                migrate(self)
            self._ready = True
            logger.info('[存储] 总库已就绪，耗时 %.2f 秒：%s', time.perf_counter() - started, self.path)

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
        connection = sqlite3.connect(path, uri=readonly, timeout=timeout, factory=factory)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute(f'PRAGMA busy_timeout={int(timeout * 1000)}')
            return connection
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def transaction(self, *, write=True, timeout=10.0):
        """为业务操作提供只读或可写的事务上下文。"""
        with closing(self.connect(timeout=timeout, readonly=not write, factory=sqlite3.Connection)) as connection:
            try:
                connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

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
