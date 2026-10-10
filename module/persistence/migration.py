"""首次启动先备份，再只读转换旧存储；成功切换后不再导入原件。"""
import csv
import math
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from module.config.transaction import config_transaction
from module.persistence.database import VERSION, create_schema, register_instance
from module.persistence.scheduler import save_persistent, save_program, write_observation
from module.persistence.snapshots import insert, read_month, read_ship, save_month, save_ship

DATABASE_KINDS = {'azurstats_local.db': 'statistics', 'cl1_data.db': 'cl1',
                  'storage_statistics.db': 'storage', 'daily_summary.db': 'daily'}
COPY_TABLES = ('resource_snapshots', 'resource_flows', 'resource_balances', 'opsi_items',
               'storage_scans', 'storage_items', 'daily_summary_task_runs', 'daily_summary_cl1_events',
               'daily_summary_periods', 'daily_summary_collection_state', 'daily_summary_collection_gaps')


class MigrationError(RuntimeError):
    """源数据仍保留，用户恢复环境后可重试。"""


class UnreadableCiphertext(MigrationError):
    """旧密文不可读时仅跳过所属记录，原件及迁移备份继续保留。"""


class UnreadableSnapshotFile(MigrationError):
    """旧快照文件为空或无法解析时保留整份文件并记录跳过原因。"""


def _log_progress(message, *args):
    """只记录阶段、来源和数量，不输出快照、密文或密钥内容。"""
    from module.logger import logger
    logger.info('[存储迁移] ' + message, *args)


def source_files(database):
    """清点当前配置目录与历史日志中的旧数据来源。"""
    directory, root = database.directory, database.directory.parent
    result = {directory / name: kind for name, kind in DATABASE_KINDS.items()}
    old_cl1 = root / 'log' / 'cl1' / 'cl1_data.db'
    if not (directory / 'cl1_data.db').is_file():
        result[old_cl1] = 'cl1'
    for path in (directory / 'scheduler').glob('*.sqlite3'):
        result[path] = 'scheduler'
    for kind in ('programs', 'variables', 'observations'):
        for path in (directory / 'scheduler' / kind).glob('*.json'):
            result[path] = 'scheduler_' + kind
    for path in (root / 'log' / 'cl1').glob('*/ship_exp_data.json'):
        result[path] = 'ships'
    for path in (root / 'log' / 'cl1').glob('*/cl1_monthly.json'):
        result[path] = 'archives'
    for path in (root / 'log').glob('azurstat_meowofficer_farming*.csv'):
        result[path] = 'farming'
    for path in (root / 'log' / 'device_id.json', root / 'log' / 'device_id.json.bak',
                 root / 'log' / 'cl1' / 'cl1_monthly.json', root / 'log' / 'cl1' / 'cl1_monthly.json.bak'):
        result[path] = 'preserved'
    for kind, paths in database.legacy_sources.items():
        for path in paths:
            result[path] = kind
    for path in list(result):
        if result[path] in ('ships', 'archives', 'farming'):
            result[path.with_name(path.name + '.bak')] = 'preserved'
    return {path.absolute(): kind for path, kind in result.items() if path.is_file()}


def _startup_process_ids():
    """识别当前入口的启动转发进程，不豁免可能写数据的 Python 祖先进程。"""
    import psutil

    current = psutil.Process()
    result = {current.pid}
    try:
        command = current.cmdline()
        executable = os.path.normcase(str(Path(current.exe()).resolve()))
        interpreter = os.path.normcase(str(Path(sys.executable).resolve()))
        for parent in current.parents():
            parent_path = Path(parent.exe()).resolve()
            parent_executable = os.path.normcase(str(parent_path))
            parent_command = parent.cmdline()
            uv_launcher = parent_path.name.lower() in ('uv', 'uv.exe') and 'run' in parent_command[1:]
            # Windows 虚拟环境的 python.exe 只转发同一命令，实际解释器是其子进程。
            python_redirector = (
                sys.platform == 'win32'
                and parent_executable == interpreter
                and parent_executable != executable
                and parent_command[1:] == command[1:]
            )
            if not (uv_launcher or python_redirector):
                break
            result.add(parent.pid)
            command, executable = parent_command, parent_executable
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # 无法确认身份时不豁免；后续扫描仍按原规则检查该进程。
        pass
    return result


def assert_no_workers(root):
    """迁移不终止进程；可写源数据的旧运行进程存在时拒绝切换。"""
    import psutil
    from module.runtime.process_control import process_matches
    for path in (root / 'cache' / 'webui-workers.json', root / 'config' / 'webui-workers.json'):
        if not path.exists():
            continue
        registry = json.loads(path.read_text(encoding='utf-8'))
        for record in registry.get('workers', {}).values():
            if isinstance(record, dict) and record.get('pid') != os.getpid() and process_matches(record):
                raise MigrationError(f'旧业务 worker 仍在运行（PID {record["pid"]}），请停止后重新启动')
    startup_ids = _startup_process_ids()
    root_key = os.path.normcase(str(root.resolve()))
    for process in psutil.process_iter(['pid', 'cmdline']):
        if process.pid in startup_ids:
            continue
        command = process.info.get('cmdline') or []
        if not any(Path(part).name.lower() in ('alas.py', 'gui.py', 'tui.py', 'mcp_server_sse.py') for part in command):
            continue
        try:
            if os.path.normcase(str(Path(process.cwd()).resolve())) == root_key:
                raise MigrationError(f'旧运行入口仍在使用该安装（PID {process.pid}），请停止后重试')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def snapshot_database(source, target):
    """使用 SQLite 在线备份取得一致的旧数据库副本。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    last_log = time.perf_counter()

    def progress(_status, remaining, total):
        """输出迁移阶段的进度消息。"""
        nonlocal last_log
        now = time.perf_counter()
        if total > 0 and now - last_log >= 2:
            _log_progress('数据库备份 %s：%s/%s 页（%.1f%%）', source.name, total - remaining, total,
                          100 * (total - remaining) / total)
            last_log = now

    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)) as original, closing(sqlite3.connect(target)) as copy:
        original.backup(copy, pages=256, progress=progress)



@contextmanager
def freeze_database(path):
    """取得源库写锁但不改数据，阻止转换期间出现新提交。"""
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield
        finally:
            connection.rollback()

def fingerprint(path):
    """计算文件摘要以检测迁移期间的外部修改。"""
    digest = hashlib.sha256()
    for candidate in (path, path.with_name(path.name + '-wal')):
        digest.update(candidate.name.encode('utf-8'))
        if candidate.exists():
            with candidate.open('rb') as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b''):
                    digest.update(chunk)
    return digest.hexdigest()


def backup_sources(database, sources, target):
    """备份全部旧数据源并生成来源摘要清单。"""
    root = database.directory.parent
    copies, manifest = {}, []
    for ordinal, (path, kind) in enumerate(sorted(sources.items(), key=lambda pair: str(pair[0])), 1):
        if path.is_symlink():
            raise MigrationError('迁移源不能是符号链接')
        relative = path.relative_to(root) if path.is_relative_to(root) else Path('external') / hashlib.sha256(str(path).encode()).hexdigest()[:16] / path.name
        copy = target / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        _log_progress('[备份 %s/%s] %s（%s）', ordinal, len(sources), relative, kind)
        before = fingerprint(path)
        if kind in ('statistics', 'cl1', 'storage', 'daily', 'scheduler'):
            snapshot_database(path, copy)
        else:
            shutil.copy2(path, copy)
        if fingerprint(path) != before:
            raise MigrationError('迁移源在备份期间发生变化，请停止旧写入者后重试')
        copies[path] = copy
        manifest.append({'path': str(relative), 'kind': kind, 'digest': before})
        _log_progress('[备份 %s/%s] 完成，耗时 %.2f 秒', ordinal, len(sources), time.perf_counter() - started)
    # 安全恢复材料只原样备份；不读取外部密钥，也不改变认证身份。
    for folder in ('opsi_secure', 'stock-exchange'):
        source = database.directory / folder
        if not source.exists():
            continue
        _log_progress('备份专用安全存储：%s', folder)
        for path in source.rglob('*'):
            if path.is_symlink():
                raise MigrationError('安全恢复材料包含符号链接')
            if not path.is_file() or path.name.endswith(('.lock', '-wal', '-shm', '-journal')):
                continue
            copy = target / 'config' / folder / path.relative_to(source)
            copy.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in ('.db', '.sqlite3'):
                snapshot_database(path, copy)
            else:
                shutil.copy2(path, copy)
    for path in database.directory.glob('*/config.db'):
        _log_progress('备份实例安全数据库：%s', path.relative_to(database.directory))
        snapshot_database(path, target / 'config' / path.relative_to(database.directory))
    _log_progress('备份实例配置与源清单')
    for path in database.directory.glob('*.json'):
        if not path.name.startswith('template'):
            copy = target / 'config' / path.name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
    (target / 'sources.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return copies, manifest


class LegacyDecoder:
    """复用旧解密原语，不调用改写、隔离或退役旧密钥的流程。"""

    def __init__(self, root):
        """初始化旧格式的只读解码器及未迁移记录清单。"""
        from module.statistics import opsi_secure
        self.secure = opsi_secure
        self.root = root
        existing = opsi_secure._STORE
        self.store = existing if existing and existing.root == root.resolve() else opsi_secure.StatsStore(root)
        self._legacy_keys = None
        self._legacy_ids = None
        self.unmigrated = []
        self.unmigrated_months = set()
        self._decoding_kinds = set()

    def legacy_device_ids(self):
        """只读旧设备 ID 并计算当前硬件 ID，不调用覆写文件或启动定时器的初始化。"""
        if self._legacy_ids is None:
            _log_progress('读取已有设备 ID，并只读计算当前硬件指纹')
            from module.base import device_id

            candidates = []
            paths = (self.root / 'log' / 'device_id.json', self.root / 'log' / 'device_id.json.bak',
                     self.root / 'log' / 'cl1' / 'cl1_monthly.json',
                     self.root / 'log' / 'cl1' / 'cl1_monthly.json.bak')
            for path in paths:
                try:
                    data = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict):
                    candidates.append(data.get('device_id'))
            candidates.extend((device_id._device_id, device_id.get_old_device_id(), device_id.generate_device_id()))
            self._legacy_ids = tuple(dict.fromkeys(value for value in candidates if isinstance(value, str) and value))
            _log_progress('设备 ID 读取完成，候选数量：%s', len(self._legacy_ids))
        return self._legacy_ids

    def legacy_keys(self):
        """收集可用于解密历史记录的已有密钥材料。"""
        if self._legacy_keys is None:
            from module.statistics.cl1_legacy import derive_legacy_key
            self._legacy_keys = [derive_legacy_key(value) for value in self.legacy_device_ids()]
        return self._legacy_keys

    def record_unmigrated(self, source, kind, identity, error):
        """记录无法解码的历史数据与跳过原因。"""
        relative = str(source.relative_to(self.root)) if source.is_relative_to(self.root) else str(source)
        self.unmigrated.append(dict(source=relative, kind=kind, identity=identity, reason=str(error)))
        if len(self.unmigrated) <= 10 or len(self.unmigrated) % 1000 == 0:
            from module.logger import logger
            category = '旧密文' if isinstance(error, UnreadableCiphertext) else '旧快照文件'
            logger.warning('[存储迁移] 跳过不可读%s：%s %s %s；%s（累计 %s 条）',
                           category, relative, kind, identity, error, len(self.unmigrated))
        if kind == 'cl1':
            self.unmigrated_months.add((identity['instance'], identity['month']))

    def payload(self, kind, raw, context):
        """解码并返回受保护的历史载荷。"""
        if self.secure.is_ciphertext(raw):
            encoding = 'V2' if raw.startswith(self.secure.BLOB_PREFIX) else 'V1'
            if (kind, encoding) not in self._decoding_kinds:
                _log_progress('开始解密 %s 旧载荷（%s），只读现有密钥', kind, encoding)
                self._decoding_kinds.add((kind, encoding))
            result = self.store.vault_keys().decrypt_record(kind, raw, context)
            if result is None:
                raise UnreadableCiphertext(f'旧 {kind} 密文无法解码')
        else:
            result = json.loads(raw)
        if not isinstance(result, dict):
            raise MigrationError(f'旧 {kind} 载荷无法解码，原件和恢复材料已保留')
        return result

    def cl1(self, row):
        """读取旧版 CL1 数据以准备转换。"""
        data = None
        if row.get('data_json'):
            try:
                data = json.loads(row['data_json'])
            except (ValueError, TypeError):
                pass
        if not isinstance(data, dict) and row.get('encrypted_blob'):
            from module.statistics.cl1_legacy import decrypt_legacy_payload
            _log_progress('开始解密整行 AES 月度快照：%s / %s', row.get('instance'), row.get('month'))
            decoded = False
            for key in self.legacy_keys():
                try:
                    data = decrypt_legacy_payload(row['encrypted_blob'], key)
                except (ValueError, TypeError, UnicodeError):
                    continue
                decoded = True
                break
            if not decoded:
                raise UnreadableCiphertext('旧整行 AES 密文未通过现有设备 ID 的完整性校验')
        if not isinstance(data, dict):
            raise MigrationError(f'旧月度快照无法解码（instance={row.get("instance")!r}, '
                                 f'month={row.get("month")!r}）：快照不是有效对象')
        if row.get('secure_json'):
            data.update(self.payload('cl1', row['secure_json'], self.secure.row_context('cl1', row)))
        return data

    def file(self, kind, original, copy):
        """主快照无法解析时尝试同批冻结的 .bak，不改写或重新读取旧源。"""
        try:
            return self._file(kind, original, copy)
        except UnreadableSnapshotFile as error:
            backup = copy.with_name(copy.name + '.bak')
            if not backup.is_file():
                raise
            original_backup = original.with_name(original.name + '.bak')
            try:
                # 旧 .bak 是主文件的字节拷贝，V2 身份仍绑定主文件路径。
                data = self._file(kind, original, backup)
            except MigrationError as backup_error:
                self.record_unmigrated(original_backup, kind, dict(file=original_backup.name), backup_error)
                raise error from backup_error
            self.record_unmigrated(original, kind, dict(file=original.name), error)
            relative = original_backup.relative_to(self.root) if original_backup.is_relative_to(self.root) else original_backup
            self.unmigrated[-1]['recovered_from'] = str(relative)
            _log_progress('已从旧快照备份恢复：%s（%s）；主文件及备份均保留', relative, kind)
            return data

    def _file(self, kind, original, copy):
        """从冻结副本读取旧快照并尝试可用的备份。"""
        try:
            raw = copy.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError as error:
            raise UnreadableSnapshotFile('旧快照文件不是有效 UTF-8 文本') from error
        text = raw.strip()
        if self.secure.is_ciphertext(text):
            return self.payload(kind, text, self.secure.file_context(self.root, kind, original))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            reason = ('旧快照文件为空' if not text else
                      f'旧快照文件不是有效 JSON（第 {error.lineno} 行，第 {error.colno} 列）')
            raise UnreadableSnapshotFile(reason) from error
        # 某些旧文件只给密文加了 JSON 字符串引号，没有对象包装。
        if isinstance(data, str) and self.secure.is_ciphertext(data):
            return self.payload(kind, data, self.secure.file_context(self.root, kind, original))
        if isinstance(data, dict) and (data.get(self.secure.WRAPPER_KEY) or data.get(self.secure.LEGACY_WRAPPER_KEY)):
            payload = data.get('payload')
            if isinstance(payload, dict):
                data = payload
            elif isinstance(payload, str):
                try:
                    data = self.payload(kind, payload, self.secure.file_context(self.root, kind, original))
                except json.JSONDecodeError as error:
                    raise UnreadableSnapshotFile('旧包装快照的载荷不是有效 JSON 或已知密文') from error
            else:
                raise UnreadableSnapshotFile('旧包装快照缺少有效字典或密文载荷')
        if not isinstance(data, dict):
            raise MigrationError('旧文件快照不是字典')
        return data



def verify_snapshot(expected, actual):
    """包括特殊浮点的逐字段对照；丢失或改变任一兼容值都拒绝切换。"""
    if type(expected) is dict:
        valid = type(actual) is dict and expected.keys() == actual.keys() and all(verify_snapshot(value, actual[key]) for key, value in expected.items())
    elif type(expected) is list:
        valid = type(actual) is list and len(expected) == len(actual) and all(verify_snapshot(a, b) for a, b in zip(expected, actual))
    elif type(expected) is float and math.isnan(expected):
        valid = type(actual) is float and math.isnan(actual)
    else:
        valid = expected == actual
    if not valid:
        raise MigrationError('转换后的快照与原业务结果不一致，未切换总库')
    return True


def _source_rows(source, table, query):
    """按表记录处理进度，较大的表每两秒输出一次，不输出业务内容。"""
    total = source.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    started = last_log = time.perf_counter()
    _log_progress('开始处理表 %s：共 %s 条记录', table, total)
    for ordinal, row in enumerate(source.execute(query), 1):
        yield row
        now = time.perf_counter()
        if now - last_log >= 2:
            _log_progress('表 %s：已处理 %s/%s 条，耗时 %.2f 秒', table, ordinal, total, now - started)
            last_log = now
    _log_progress('表 %s 处理完成：%s 条，耗时 %.2f 秒', table, total, time.perf_counter() - started)


def import_database(connection, path, kind, original, decoder):
    """将旧 SQLite 业务表导入临时统一数据库。"""
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        source.row_factory = sqlite3.Row
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if kind == 'scheduler':
            import_scheduler(connection, source, tables, original.stem)
            return
        expected_tables = {'statistics': {'resource_snapshots', 'resource_flows', 'resource_balances', 'opsi_items'},
                           'cl1': {'cl1_data'}, 'storage': {'storage_scans', 'storage_items'},
                           'daily': {name for name in COPY_TABLES if name.startswith('daily_summary_')}}
        unknown = tables - expected_tables[kind] - {'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4'}
        unknown = {name for name in unknown if not name.startswith('__opsi_')}
        # 旧功能可能从未建表或已移除业务表，只剩 SQLite 内部表的空库也可迁移。
        if unknown:
            raise MigrationError(f'旧 {kind} 数据库的表结构不符合迁移约定')
        if kind == 'cl1' and 'cl1_data' in tables:
            seen = set()
            for row in _source_rows(source, 'cl1_data', 'SELECT * FROM cl1_data ORDER BY rowid'):
                row = dict(row)
                key = (row['instance'], row['month'])
                if key in seen or read_month(connection, *key) is not None:
                    raise MigrationError('旧数据库存在重复月份，请先明确数据来源')
                seen.add(key)
                try:
                    decoded = decoder.cl1(row)
                except UnreadableCiphertext as error:
                    decoder.record_unmigrated(original, kind, dict(instance=row['instance'], month=row['month']), error)
                    continue
                save_month(connection, row['instance'], row['month'], decoded)
                verify_snapshot(decoded, read_month(connection, row['instance'], row['month']))
        for table in COPY_TABLES:
            if table not in tables:
                continue
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            for row in _source_rows(source, table, f'SELECT rowid AS __migration_rowid, * FROM {table} ORDER BY rowid'):
                values = dict(row)
                rowid = values.pop('__migration_rowid')
                try:
                    for column, payload_kind in (('opsi_payload', 'res'), ('secure_payload', 'loot' if table == 'opsi_items' else 'daily')):
                        raw = values.pop(column, None)
                        if raw:
                            values.update(decoder.payload(payload_kind, raw, decoder.secure.row_context(payload_kind, values)))
                    if table == 'daily_summary_periods' and decoder.secure.is_ciphertext(values.get('report_text')):
                        payload = decoder.payload('reports', values['report_text'], decoder.secure.report_context(values['instance'], values['period_key']))
                        if not isinstance(payload.get('text'), str):
                            raise MigrationError('旧日报正文无法解码')
                        values['report_text'] = payload['text']
                except UnreadableCiphertext as error:
                    decoder.record_unmigrated(original, kind, dict(table=table, rowid=rowid), error)
                    continue
                register_instance(connection, values.get('instance'))
                if set(values) - columns:
                    raise MigrationError(f'旧 {table} 含无法投影的业务列，未切换总库')
                projected = {key: value for key, value in values.items() if key in columns}
                target_id = insert(connection, table, projected)
                inserted = dict(connection.execute(f'SELECT * FROM {table} WHERE rowid=?', (target_id,)).fetchone())
                verify_snapshot(projected, {key: inserted[key] for key in projected})
        # 已清理的旧流水可能仍在消费水位之前；新 ID 必须越过旧序列和水位。
        if 'sqlite_sequence' in tables:
            autoincrement = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%AUTOINCREMENT%'")}
            for row in source.execute('SELECT name,seq FROM sqlite_sequence'):
                if row['name'] in COPY_TABLES and row['name'] in autoincrement:
                    if type(row['seq']) is not int or row['seq'] < 0:
                        raise MigrationError('旧数据库的自增序列无效')
                    if connection.execute('SELECT 1 FROM sqlite_sequence WHERE name=?', (row['name'],)).fetchone():
                        connection.execute('UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?', (row['seq'], row['name']))
                    else:
                        connection.execute('INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)', (row['name'], row['seq']))
        cursor = connection.execute('SELECT MAX(cursor) FROM resource_balances').fetchone()[0]
        if cursor is not None:
            if connection.execute("SELECT 1 FROM sqlite_sequence WHERE name='resource_flows'").fetchone():
                connection.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='resource_flows'", (cursor,))
            else:
                connection.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('resource_flows',?)", (cursor,))


def import_scheduler(connection, source, tables, instance):
    """转换旧调度器数据库中的定义和运行状态。"""
    if 'scheduler_programs' in tables:
        if source.execute('PRAGMA user_version').fetchone()[0] != VERSION or source.execute('PRAGMA foreign_key_check').fetchone():
            raise MigrationError('旧调度切片的版本或引用无效')
        from module.persistence.scheduler import copy_scheduler
        copy_scheduler(source, connection, instance)
        return
    if not tables.intersection({'programs', 'variables', 'records', 'runtime', 'observations', 'action_point_history', 'action_point_chain_owner'}):
        raise MigrationError('旧调度库没有已知业务或安全表')
    known = {'programs', 'variables', 'records', 'runtime', 'observations', 'action_point_history',
             'action_point_chain', 'action_point_chain_owner', 'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4'}
    if tables - known:
        raise MigrationError('旧调度库包含未约定的业务表')
    for table in ('programs', 'runtime'):
        if table in tables and source.execute(f'SELECT 1 FROM {table} WHERE id<>1').fetchone():
            raise MigrationError('旧调度库的单例记录发生结构冲突')
    if 'programs' in tables:
        row = source.execute('SELECT * FROM programs WHERE id=1').fetchone()
        if row:
            save_program(connection, instance, dict(mode=row['mode'], draft=json.loads(row['draft']),
                active=json.loads(row['active']) if row['active'] else None, generation=row['generation']), row['revision'])
    from module.persistence.scheduler import read_program, read_persistent
    program = read_program(connection, instance)
    if program:
        from module.scheduler.models import ProgramDocument
        verify_snapshot(ProgramDocument.model_validate(json.loads(row['draft'])).model_dump(), program['draft'])
    persistent = {name: {row['name']: json.loads(row['value']) for row in source.execute(f'SELECT * FROM {name}')}
                  for name in ('variables', 'records') if name in tables}
    if 'runtime' in tables:
        row = source.execute('SELECT * FROM runtime WHERE id=1').fetchone()
        if row and row['in_flight']:
            persistent['inFlight'] = row['in_flight']
    if persistent:
        save_persistent(connection, instance, persistent)
        expected = dict(variables=persistent.get('variables', {}), records=persistent.get('records', {}))
        if persistent.get('inFlight'):
            expected['inFlight'] = persistent['inFlight']
        verify_snapshot(expected if any(expected.values()) else {}, read_persistent(connection, instance))
    if 'observations' in tables:
        for row in source.execute('SELECT * FROM observations'):
            write_observation(connection, instance, row['resource'], dict(Value=row['value'], Limit=row['resource_limit'], Total=row['total']), row['observed_at'], row['source'])


def import_archive(connection, original, copy, decoder):
    """导入历史月份快照而不覆盖已导入的月份。"""
    data = decoder.file('archives', original, copy)
    instance = original.parent.name
    for month in sorted(key for key in data if re.fullmatch(r'\d{4}-\d{2}', key)):
        if (instance, month) in decoder.unmigrated_months or read_month(connection, instance, month) is not None:
            continue
        record = data[month]
        if isinstance(record, dict):
            save_month(connection, instance, month, record)
            verify_snapshot(record, read_month(connection, instance, month))
        else:
            from module.statistics.cl1_database import Cl1Database
            projected = Cl1Database()._empty_data(month)
            projected.update(battle_count=record, akashi_encounters=data.get(month + '-akashi', 0),
                akashi_ap=data.get(month + '-akashi-ap', 0), akashi_ap_entries=data.get(month + '-akashi-ap-entries', []))
            save_month(connection, instance, month, projected)
            verify_snapshot(projected, read_month(connection, instance, month))


def import_farming(connection, original, copy, decoder):
    """导入历史刷取收益记录并保留来源归属。"""
    raw = copy.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        # 历史 CSV 的中文标题可能由平台默认编码写出，数值行统一为 ASCII。
        text = 'legacy header\n' + b'\n'.join(raw.splitlines()[1:]).decode('ascii')
    if decoder.secure.is_ciphertext(text):
        rows = decoder.payload('loot', text, decoder.secure.file_context(decoder.root, 'loot', original))['rows']
    else:
        rows = list(csv.reader(io.StringIO(text)))[1:]
    match = re.search(r'\.instance-([0-9a-f]{64})\.csv$', original.name)
    scope = 'instance-' + match[1] if match else 'global'
    instance = device = None
    if match:
        known = [path.stem for path in (decoder.root / 'config').glob('*.json') if not path.name.startswith('template')]
        for candidate_device in decoder.legacy_device_ids():
            for candidate in known:
                if hashlib.sha256(f'{candidate_device}\0{candidate}'.encode()).hexdigest() == match[1]:
                    instance, device = candidate, candidate_device
    register_instance(connection, instance)
    if len(rows) != 6:
        raise MigrationError('旧收益 CSV 缺少六个侵蚀等级')
    for record in rows:
        if len(record) != 7:
            raise MigrationError('旧收益 CSV 列数不符合约定')
        numbers = list(map(float, record))
        if numbers[0] != int(numbers[0]) or numbers[1] != int(numbers[1]):
            raise MigrationError('旧收益 CSV 等级或时间不是整数')
        insert(connection, 'farming_aggregates', dict(scope_key=scope, hazard_level=int(numbers[0]), instance=instance,
            device_id=device, source_kind='legacy', source_file=str(original.relative_to(decoder.root) if original.is_relative_to(decoder.root) else original), recorded_at=int(numbers[1]),
            effective_rounds=numbers[2], average_yellow_coin=numbers[3], average_plate=numbers[4], average_abyssal=numbers[5], average_obscure=numbers[6]))


def migrate(database):
    """备份并验证旧数据后原子发布统一业务数据库。"""
    started = time.perf_counter()
    directory = database.directory
    temporary = directory / ('azurpilot.' + uuid4().hex + '.tmp')
    backup = directory / 'storage-backups' / ('pre-v1-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])

    def phase(message, *args):
        """更新迁移阶段并输出可诊断的进度日志。"""
        nonlocal stage
        stage = message % args if args else message
        _log_progress('%s', stage)

    stage = '清点旧存储'
    try:
        phase('首次初始化总库 v%s，清点旧存储：%s', VERSION, directory)
        directory.mkdir(parents=True, exist_ok=True)
        sources = source_files(database)
        _log_progress('发现 %s 个旧来源，备份目录：%s', len(sources), backup)
        phase('检查旧运行入口与业务 worker 是否已停止')
        assert_no_workers(directory.parent)
        phase('准备只读旧数据解码器')
        decoder = LegacyDecoder(directory.parent)
        with ExitStack() as locks:
            phase('取得旧来源及安全恢复材料的文件锁')
            for path in sorted(sources, key=str):
                _log_progress('等待旧来源文件锁：%s', path)
                locks.enter_context(config_transaction(path))
            for path in directory.glob('*/config.db'):
                _log_progress('等待实例安全数据库文件锁：%s', path)
                locks.enter_context(config_transaction(path))
            for path in (directory / 'stock-exchange', directory / 'stock-exchange' / 'registry.json'):
                _log_progress('等待安全恢复材料文件锁：%s', path)
                locks.enter_context(config_transaction(path))
            for path in sorted(directory.glob('*.json'), key=str):
                _log_progress('等待实例配置文件锁：%s', path)
                locks.enter_context(config_transaction(path))
            phase('取得旧 SQLite 数据库写锁，冻结源数据')
            for path, kind in sorted(sources.items(), key=lambda pair: str(pair[0])):
                if kind in ('statistics', 'cl1', 'storage', 'daily', 'scheduler'):
                    _log_progress('等待旧数据库写锁：%s', path)
                    locks.enter_context(freeze_database(path))
            phase('备份旧普通存储与安全恢复材料：%s', backup)
            backup.mkdir(parents=True)
            copies, manifest = backup_sources(database, sources, backup)
            digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
            phase('创建临时总库及 v%s 表结构', VERSION)
            with closing(sqlite3.connect(temporary)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('PRAGMA synchronous=FULL')
                create_schema(connection)
                connection.execute('BEGIN IMMEDIATE')
                ordered = sorted(sources.items(), key=lambda pair: (pair[1] not in ('statistics', 'cl1', 'storage', 'daily', 'scheduler'), str(pair[0])))
                for ordinal, (original, kind) in enumerate(ordered, 1):
                    copy = copies[original]
                    relative = original.relative_to(directory.parent) if original.is_relative_to(directory.parent) else original
                    phase('[转换 %s/%s] %s（%s）', ordinal, len(ordered), relative, kind)
                    source_started = time.perf_counter()
                    skipped_before = len(decoder.unmigrated)
                    if kind in ('ships', 'archives', 'farming'):
                        try:
                            if kind == 'ships':
                                instance = original.parent.name
                                if read_ship(connection, instance) is None:
                                    decoded = decoder.file('ships', original, copy)
                                    save_ship(connection, instance, decoded)
                                    verify_snapshot(decoded, read_ship(connection, instance))
                            elif kind == 'archives':
                                import_archive(connection, original, copy, decoder)
                            else:
                                import_farming(connection, original, copy, decoder)
                        except (UnreadableCiphertext, UnreadableSnapshotFile) as error:
                            decoder.record_unmigrated(original, kind, dict(file=original.name), error)
                    elif kind in ('statistics', 'cl1', 'storage', 'daily', 'scheduler'):
                        import_database(connection, copy, kind, original, decoder)
                    elif kind.startswith('scheduler_'):
                        instance, section = original.stem, kind.removeprefix('scheduler_')
                        data = json.loads(copy.read_text(encoding='utf-8'))
                        if section == 'programs':
                            if not connection.execute('SELECT 1 FROM scheduler_programs WHERE instance=?', (instance,)).fetchone():
                                save_program(connection, instance, data, data.get('revision', uuid4().hex))
                        elif section == 'variables':
                            if not connection.execute('SELECT 1 FROM scheduler_runtime WHERE instance=?', (instance,)).fetchone():
                                save_persistent(connection, instance, data)
                        else:
                            for name, value in data.items():
                                if not connection.execute('SELECT 1 FROM scheduler_observations WHERE instance=? AND resource=?', (instance, name)).fetchone():
                                    write_observation(connection, instance, name, value, value['observedAt'], value['source'])
                    else:
                        _log_progress('该来源仅保留备份，无需转换')
                    _log_progress('[转换 %s/%s] 完成，跳过 %s 条不可读旧记录，耗时 %.2f 秒',
                                  ordinal, len(ordered), len(decoder.unmigrated) - skipped_before,
                                  time.perf_counter() - source_started)
                phase('写入迁移记录并检查临时总库的外键与完整性')
                insert(connection, 'storage_migrations', dict(version=VERSION, applied_at=datetime.now().isoformat(), source_digest=digest))
                if connection.execute('PRAGMA foreign_key_check').fetchone() or connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise MigrationError('临时总库未通过完整性检查')
                phase('验证通过，提交临时总库并执行 WAL 检查点')
                connection.commit()
                connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            phase('再次检查源文件摘要与来源清单')
            for row, original in zip(manifest, sorted(sources, key=str)):
                if fingerprint(original) != row['digest']:
                    raise MigrationError('转换期间源数据发生变化，未切换总库')
            if source_files(database) != sources:
                raise MigrationError('转换期间旧来源发生变化，未切换总库')
            if decoder.unmigrated:
                phase('保存 %s 条未迁移记录的清单', len(decoder.unmigrated))
                (backup / 'unmigrated.json').write_text(json.dumps(decoder.unmigrated, ensure_ascii=False, indent=2), encoding='utf-8')
            phase('切换正式总库：%s', database.path)
            os.replace(temporary, database.path)
            phase('保存迁移完成标记')
            database._write_marker(digest)
            if decoder.unmigrated:
                from module.logger import logger
                logger.warning(f'[存储迁移] 已跳过 {len(decoder.unmigrated)} 条不可读旧记录，'
                               f'原件及备份保留，启动继续；未迁移清单：{backup / "unmigrated.json"}')
            _log_progress('迁移完成：旧来源 %s 个，跳过 %s 条不可读旧记录，总耗时 %.2f 秒；备份：%s',
                          len(sources), len(decoder.unmigrated), time.perf_counter() - started, backup)
    except BaseException:
        from module.logger import logger
        logger.error('[存储迁移] 阶段未完成：%s；耗时 %.2f 秒。原件保留，已有备份请查看：%s',
                     stage, time.perf_counter() - started, backup)
        for suffix in ('', '-wal', '-shm'):
            temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
        raise
