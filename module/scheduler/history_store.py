"""行动力认证历史专用存储；保持旧数据库、链和锚点的身份。"""
import os
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path
from uuid import uuid4

from module.config.transaction import config_transaction
from module.scheduler.action_history import ActionPointChain, HistoryConnection
from module.runtime.game_data import GameDataProtector, damaged
from module.api.protocol import ApiError

HISTORY_ERRORS = (ApiError, OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error)


class AuthenticatedHistoryStore:
    def __init__(self, directory='config'):
        """初始化独立的受认证行动力历史存储。"""
        self.directory = Path(directory).absolute() / 'scheduler'


    def path(self, instance, kind=None):
        """返回指定实例的受保护历史数据库路径。"""
        from module.api.config_service import validate_name
        if validate_name(instance) != instance:
            raise ValueError('实例名不是规范形式')
        path = self.directory / f'{instance}.sqlite3'
        # 只解析父目录；Windows 在其他线程首次创建文件时解析文件本身可能返回不同的路径形式。
        if path.is_symlink() or os.path.normcase(str(path.parent.resolve())) != os.path.normcase(str(self.directory.resolve())):
            raise ValueError('调度路径无效')
        return path


    @contextmanager
    def connection(self, instance, write=False, baseline=None, strict_history=False):
        """打开实例专用认证历史库，普通资源事务不因交易所认证失败而中断。

        Args:
            instance: 实例名。
            write: 是否以可写方式打开。
            baseline: 迁移行动力历史时使用的初始值。
            strict_history: 交易所读取时启用历史强校验，损坏时抛出异常。
        """
        path = self.path(instance)
        protection = GameDataProtector(self.directory.parent.parent)
        for suffix in ('', '-wal', '-shm', '-journal'):
            protection._safe(path.with_name(path.name + suffix))
        identity = None
        if strict_history and protection.initialized() and (self.directory.parent / (instance + '.json')).is_file():
            identity = protection.resolve(instance)
            protection.relocate_scheduler(instance, identity)
        if not path.exists() and not write:
            if identity and protection.has_anchor(identity + '/action-point-history'):
                raise damaged('行动力历史数据库丢失，已停止同步')
            yield None
            return
        if write or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        with config_transaction(path):
            connection = sqlite3.connect(path, timeout=10, factory=HistoryConnection) if write else sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=10, factory=HistoryConnection)
            connection.row_factory = sqlite3.Row
            connection.history_strict = strict_history
            try:
                if connection.execute('PRAGMA user_version').fetchone()[0] > 1:
                    raise ValueError('调度数据库版本高于当前程序支持版本')
                anchored = identity and protection.has_anchor(identity + '/action-point-history')
                if anchored:
                    # 先验证再执行建表或写入，损坏的历史不能被升级逻辑覆盖。
                    connection.execute('BEGIN')
                    connection.history_guard = ActionPointChain(connection, protection, identity)
                    connection.commit()
                if write:
                    connection.execute('PRAGMA journal_mode=WAL')
                    connection.execute('PRAGMA synchronous=FULL')
                    connection.executescript('''
                    CREATE TABLE IF NOT EXISTS action_point_history (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        observed_at TEXT NOT NULL UNIQUE, total INTEGER NOT NULL);
                    PRAGMA user_version=1;
                ''')
                connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                def history_factory():
                    """构造具备历史校验上下文的数据库连接。"""
                    nonlocal identity
                    if identity is None:
                        identity = protection.resolve(instance)
                    return ActionPointChain(connection, protection, identity, write, baseline)
                connection.history_factory = history_factory
                chained = connection.execute("SELECT 1 FROM sqlite_master WHERE name='action_point_chain'").fetchone()
                historical = connection.execute("SELECT 1 FROM sqlite_master WHERE name='action_point_history'").fetchone()
                if strict_history and not connection.history_guard and (chained or write and historical and connection.execute('SELECT 1 FROM action_point_history LIMIT 1').fetchone() or baseline):
                    connection.history_guard = history_factory()
                yield connection
                if connection.history_guard:
                    try:
                        connection.history_guard.prepare()
                    except HISTORY_ERRORS:
                        if strict_history:
                            raise
                        # 茗交所认证失败只停止交易同步，不回滚普通调度或资源记录。
                connection.commit()
                if connection.history_guard:
                    try:
                        connection.history_guard.finish()
                    except HISTORY_ERRORS:
                        if strict_history:
                            raise
            except BaseException:
                connection.rollback()
                raise
            finally:
                if connection.history_guard:
                    connection.history_guard.close()
                connection.close()
    @staticmethod
    def _write_observation(connection, name, value, timestamp, source):
        """将受验证的行动力观测写入历史记录。"""
        values = value if isinstance(value, dict) else {'Value': value}
        # 在覆盖最新值之前保留实际采集的总行动力；同一时间的修正产生新游标。
        total = values.get('Total')
        if name == 'ActionPoint' and type(total) in (int, float) and 0 <= total <= 1_000_000 and int(total) == total:
            if not connection.history_disabled:
                connection.execute('SAVEPOINT stock_history')
                try:
                    if connection.history_guard is None:
                        connection.history_guard = connection.history_factory()
                    if connection.history_guard:
                        connection.history_guard.append(timestamp, int(total))
                except HISTORY_ERRORS:
                    connection.execute('ROLLBACK TO stock_history')
                    if connection.history_strict:
                        raise
                    if connection.history_guard:
                        connection.history_guard.close()
                        connection.history_guard = None
                    connection.history_disabled = True
                finally:
                    connection.execute('RELEASE stock_history')
            if connection.history_guard is None:
                try:
                    connection.execute('''INSERT INTO action_point_history(observed_at,total) VALUES(?,?)
                        ON CONFLICT(observed_at) DO UPDATE SET seq=excluded.seq,total=excluded.total
                        WHERE action_point_history.total!=excluded.total''', (timestamp, int(total)))
                except sqlite3.Error:
                    if connection.history_strict:
                        raise
                    # 可选历史表损坏也不能阻断普通资源记录；茗交所读取时仍会报错。

    def observe(self, instance, name, value, timestamp, source):
        """保存本次观察并更新历史校验状态。"""
        with self.connection(instance, write=True) as connection:
            self._write_observation(connection, name, value, timestamp, source)


    def backup(self, instance, target):
        """原生备份包含已提交的 WAL 数据，不直接复制正在使用的数据库。"""
        path, target = self.path(instance), Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f'{target.name}.{uuid4().hex}.tmp')
        try:
            with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


    def archive(self, instance, backup):
        """归档受保护的行动力历史以便安全恢复。"""
        path = self.path(instance)
        if path.exists():
            with config_transaction(path):
                self.backup(instance, Path(backup) / 'scheduler' / path.name)
                for suffix in ('', '-wal', '-shm'):
                    path.with_name(path.name + suffix).unlink(missing_ok=True)
