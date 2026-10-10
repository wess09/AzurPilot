"""按实例使用普通总库保存调度；认证历史由专用存储维护。"""
import copy
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager, closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from module.config.transaction import config_transaction
from module.persistence.database import DEFAULT_DIRECTORY, VERSION, create_schema, get_database, register_instance
from module.persistence import scheduler as native
from module.scheduler.history_store import AuthenticatedHistoryStore, HISTORY_ERRORS
from module.scheduler.templates import default_program


class ConflictError(Exception):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class ProgramStore:
    def __init__(self, directory=None, *, store=None):
        self.database = store or get_database(None if directory is None or Path(directory).absolute() == DEFAULT_DIRECTORY else directory)
        self.directory = self.database.directory / 'scheduler'
        self.history = AuthenticatedHistoryStore(self.database.directory)

    def path(self, instance, kind=None):
        self.history.path(instance)
        return self.database.path

    @contextmanager
    def connection(self, instance, write=False, baseline=None, strict_history=False):
        self.path(instance)
        if strict_history or baseline is not None:
            with self.history.connection(instance, write, baseline, strict_history) as connection:
                yield connection
            return
        if not write and not self.database.path.exists() and not self.database.marker.exists():
            from module.persistence.migration import source_files
            if not source_files(self.database):
                yield None
                return
        with self.database.transaction(write=write) as connection:
            yield connection

    @staticmethod
    def default():
        return {'mode': 'native', 'draft': default_program().model_dump(), 'active': None, 'generation': 0}

    @staticmethod
    def _read_program(connection, instance):
        data = native.read_program(connection, instance) if connection else None
        if data is not None:
            return data
        data = ProgramStore.default()
        return {**data, 'revision': hashlib.sha256(encode(data).encode()).hexdigest()}

    def exists(self, instance):
        with self.connection(instance) as connection:
            return bool(connection and connection.execute('SELECT 1 FROM scheduler_programs WHERE instance=?', (instance,)).fetchone())

    def get(self, instance):
        with self.connection(instance) as connection:
            return self._read_program(connection, instance)

    def update(self, instance, revision, **changes):
        with self.connection(instance, write=True) as connection:
            current = self._read_program(connection, instance)
            if current.pop('revision') != revision:
                raise ConflictError('调度方案已被其他窗口修改，请重新加载')
            current.update(copy.deepcopy(changes))
            native.save_program(connection, instance, current, uuid4().hex)
            result = self._read_program(connection, instance)
        return result

    @staticmethod
    def import_bundle(data):
        """导入只接收调度定义，不接收运行状态和账号信息。"""
        from module.scheduler.models import ProgramDocument
        if not isinstance(data, dict) or set(data) - {'mode', 'draft', 'active'} or data.get('mode') not in ('native', 'enhance', 'takeover'):
            raise ValueError('调度导入格式无效')
        draft = ProgramDocument.model_validate(data['draft'])
        active = ProgramDocument.model_validate(data['active']) if data.get('active') else None
        if data['mode'] != 'native':
            from module.scheduler.validation import validate
            if not active or not validate(active, mode=data['mode'])['valid']:
                raise ValueError('已应用的调度程序未通过校验')
        return {'mode': data['mode'], 'draft': draft.model_dump(), 'active': active.model_dump() if active else None, 'generation': 0}

    def export(self, instance):
        document = self.get(instance)
        return {key: document[key] for key in ('mode', 'draft', 'active')}

    def import_program(self, instance, data):
        with self.connection(instance, write=True) as connection:
            native.save_program(connection, instance, self.import_bundle(data), uuid4().hex)

    def persistent(self, instance):
        with self.connection(instance) as connection:
            return native.read_persistent(connection, instance) if connection else {}

    def save_persistent(self, instance, data):
        with self.connection(instance, write=True) as connection:
            native.save_persistent(connection, instance, data)

    def observations(self, instance):
        with self.connection(instance) as connection:
            return native.read_observations(connection, instance) if connection else {}

    @staticmethod
    def _write_observation(connection, name, value, timestamp, source):
        """兼容历史事务的调用点；普通观察写入必须携带实例。"""
        AuthenticatedHistoryStore._write_observation(connection, name, value, timestamp, source)

    def observe(self, instance, name, value, timestamp, source):
        self.path(instance)
        self.database.ensure_ready()
        total = value.get('Total') if isinstance(value, dict) else None
        if name == 'ActionPoint' and type(total) in (int, float) and 0 <= total <= 1_000_000 and int(total) == total:
            try:
                self.history.observe(instance, name, value, timestamp, source)
            except HISTORY_ERRORS as error:
                from module.logger import logger
                logger.warning(f'[认证历史] 记录失败，交易同步将停止：{type(error).__name__}')
        with self.connection(instance, write=True) as connection:
            native.write_observation(connection, instance, name, value, timestamp, source)

    def copy(self, source, target):
        if self.exists(source):
            self.import_program(target, self.export(source))

    def backup(self, instance, target):
        """只导出一个实例的调度切片，重新分配所有内部引用。"""
        self.path(instance)
        target = Path(target)
        if target.resolve() == self.database.path.resolve() or target.is_symlink():
            raise ValueError('调度切片不能覆盖普通总库或符号链接')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
        try:
            with self.database.transaction(write=False) as source, closing(sqlite3.connect(temporary)) as destination:
                destination.row_factory = sqlite3.Row
                destination.execute('PRAGMA foreign_keys=ON')
                create_schema(destination)
                destination.execute('BEGIN IMMEDIATE')
                register_instance(destination, instance)
                native.copy_scheduler(source, destination, instance)
                destination.execute('INSERT INTO storage_migrations VALUES(?,?,?)', (VERSION, datetime.now().isoformat(), 'scheduler-slice'))
                destination.commit()
                if destination.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('实例调度切片未通过外键检查')
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('实例调度切片未通过完整性检查')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def archive(self, instance, backup):
        self.path(instance)
        self.database.ensure_ready()
        with config_transaction(self.database.path):
            self.backup(instance, Path(backup) / 'business' / (instance + '.sqlite3'))
            self.history.archive(instance, backup)
            with self.database.transaction() as connection:
                native.delete_scheduler(connection, instance)

    def restore(self, instance, source):
        self.path(instance)
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as original:
            original.row_factory = sqlite3.Row
            original.execute('PRAGMA foreign_keys=ON')
            original.execute('BEGIN')
            if original.execute('PRAGMA user_version').fetchone()[0] != VERSION:
                raise ValueError('调度切片版本不受支持')
            if original.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or original.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('调度切片未通过数据库检查')
            if not original.execute('SELECT 1 FROM storage_instances WHERE instance=?', (instance,)).fetchone():
                raise ValueError('调度切片中没有指定实例')
            with self.database.transaction() as connection:
                if self._has_state(connection, instance):
                    raise ConflictError('恢复目标已存在调度数据，请先归档')
                native.copy_scheduler(original, connection, instance)

    @staticmethod
    def _has_state(connection, instance):
        return any(connection.execute(f'SELECT 1 FROM {table} WHERE instance=?', (instance,)).fetchone()
                   for table in ('scheduler_programs', 'scheduler_runtime', 'scheduler_state_variables',
                                 'scheduler_counters', 'scheduler_times', 'scheduler_results',
                                 'scheduler_observations', 'scheduler_record_extensions'))

    def relocate(self, source, target):
        """只由可信安全注册的改名流程调用，统计名称保持原样。"""
        self.path(source)
        self.path(target)
        with config_transaction(self.database.path), self.database.transaction() as connection:
            if not self._has_state(connection, source):
                return
            if self._has_state(connection, target):
                raise ConflictError('改名目标已有调度数据，请先归档')
            native.copy_scheduler(connection, connection, source, target)
            native.delete_scheduler(connection, source)
