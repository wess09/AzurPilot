"""行动力原始记录的持久补传日志；只做格式处理、身份签名和两端校对。"""
import hashlib
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from module.api.protocol import ApiError
from module.runtime.game_data import GameDataProtector
from module.scheduler.action_history import HistorySeal
from module.scheduler.history_store import AuthenticatedHistoryStore
from module.config.transaction import config_transaction
from module.statistics.cl1_legacy import read_ap_snapshots

SHANGHAI = timezone(timedelta(hours=8))


def history_point(total, recorded):
    if type(total) not in (int, float) or not 0 <= total <= 1_000_000 or int(total) != total or not recorded:
        return None
    try:
        stamp = int(datetime.fromisoformat(recorded).timestamp() * 1000)
        month = datetime.fromtimestamp(stamp / 1000, SHANGHAI).strftime('%Y-%m')
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    return stamp, int(total), month


class ActionHistory:
    """每个实例一个小型 WAL 日志，成功回执后才确认，重启或断网不会丢队列。"""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.protection = GameDataProtector(root)
        self.directory = self.protection.directory / 'history'
        self.connections, self.scanned, self.next_send, self.next_check, self.failures = {}, {}, {}, {}, {}
        self.paths, self.inodes = {}, {}
        self.pending = {}
        self.legacy_warnings = {}
        self.lock = threading.RLock()

    def close(self):
        with self.lock:
            for connection in self.connections.values():
                connection.close()
            self.connections.clear()

    def _connection(self, instance):
        identity = self.protection.resolve(instance)
        path = self.protection.file_path('history/' + identity + '.sqlite3')
        for suffix in ('-wal', '-shm', '-journal'):
            self.protection._safe(path.with_name(path.name + suffix))
        inode = (path.stat().st_dev, path.stat().st_ino) if path.exists() else None
        if identity in self.connections and inode != self.inodes[identity]:
            self.connections.pop(identity).close()
        if identity not in self.connections:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.directory.chmod(0o700)
            legacy = self.directory / (hashlib.sha256(instance.encode()).hexdigest() + '.sqlite3')
            imported = False
            if not path.exists() and legacy.exists() and self.protection.record(identity)['baseline'] and not self.protection.has_anchor(identity + '/upload-history'):
                self.protection._safe(legacy)
                with config_transaction(legacy), closing(sqlite3.connect(legacy.as_uri() + '?mode=ro', uri=True)) as old, closing(sqlite3.connect(path)) as new:
                    old.backup(new)
                imported = True
            if not path.exists() and self.protection.has_anchor(identity + '/upload-history'):
                raise ApiError('STOCK_STORAGE_DAMAGED', '行动力补传日志丢失，已停止同步')
            connection = sqlite3.connect(path, timeout=2, check_same_thread=False)
            try:
                if self.protection.has_anchor(identity + '/upload-history'):
                    seal = HistorySeal(connection, self.protection, identity)
                    try:
                        connection.execute('BEGIN')
                        seal.verify()
                        connection.commit()
                    finally:
                        seal.close()
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('PRAGMA synchronous=FULL')
                connection.executescript('''
                CREATE TABLE IF NOT EXISTS samples (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    time INTEGER NOT NULL UNIQUE,total INTEGER NOT NULL,month TEXT NOT NULL,uploaded INTEGER NOT NULL DEFAULT 0,source INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS samples_pending ON samples(uploaded,seq);
                CREATE INDEX IF NOT EXISTS samples_pending_month ON samples(uploaded,month,seq);
                CREATE INDEX IF NOT EXISTS samples_month ON samples(month,time);
                CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY,value TEXT NOT NULL);
                ''')
                if 'source' not in {row[1] for row in connection.execute('PRAGMA table_info(samples)')}:
                    connection.execute('ALTER TABLE samples ADD COLUMN source INTEGER NOT NULL DEFAULT 0')
                if imported:
                    seal = HistorySeal(connection, self.protection, identity)
                    try:
                        seal.prepare()
                        connection.commit()
                        seal.finish()
                    finally:
                        seal.close()
            except BaseException:
                connection.close()
                raise
            path.chmod(0o600)
            self.connections[identity] = connection
            self.paths[identity] = path
            self.inodes[identity] = (path.stat().st_dev, path.stat().st_ino)
        return self.connections[identity], identity

    @contextmanager
    def _transaction(self, instance):
        connection, identity = self._connection(instance)
        with config_transaction(self.paths[identity]):
            seal = HistorySeal(connection, self.protection, identity)
            try:
                connection.execute('BEGIN IMMEDIATE')
                seal.verify()
                before = seal.digest()
                yield connection
                changed = before != seal.digest() or not self.protection.has_anchor(seal.name)
                if changed:
                    seal.prepare()
                connection.commit()
                if changed:
                    seal.finish()
            except BaseException:
                connection.rollback()
                raise
            finally:
                seal.close()

    def discard_retired(self, active):
        with self.lock:
            for identity in tuple(self.connections):
                if identity not in active:
                    self.connections.pop(identity).close()

    def ready(self, instance):
        now = time.monotonic()
        return now >= self.next_send.get(instance, 0) and (self.pending.get(instance, True) or now >= self.next_check.get(instance, 0))

    @staticmethod
    def _put(connection, points, source=1):
        connection.executemany('''INSERT INTO samples(time,total,month,source) VALUES(?,?,?,?)
            ON CONFLICT(time) DO UPDATE SET seq=excluded.seq,total=excluded.total,uploaded=0,source=excluded.source
            WHERE excluded.source>=samples.source AND (samples.total!=excluded.total OR samples.source!=excluded.source)''',
            [(*point, source) for point in points])

    def _import_legacy_history(self, connection, identity):
        """只迁移原实例当月旧统计；读取失败保留原件和重试资格，不阻断中央记录。"""
        marker = 'legacy_ap_history_v1'
        if connection.execute('SELECT 1 FROM metadata WHERE name=?', (marker,)).fetchone():
            return ''
        record = self.protection.record(identity)
        count = 0
        if record['baseline']:
            path = self.root / 'config' / 'cl1_data.db'
            if not path.exists():
                path = self.root / 'log' / 'cl1' / 'cl1_data.db'
            self.protection._safe(path)
            if path.is_file():
                month = datetime.now(SHANGHAI).strftime('%Y-%m')
                latest_allowed = int((time.time() + 60) * 1000)
                points = []
                try:
                    for row in read_ap_snapshots(path, record.get('legacyStatsName') or record['name'], [month]):
                        # 当前可用行动力 ap 不等于含箱总量，不能用它填造证券价格。
                        point = history_point(row.get('ap_total'), row.get('ts'))
                        if point and point[2] == month and point[0] <= latest_allowed:
                            points.append(point)
                            count += 1
                except (OSError, sqlite3.Error, ValueError, TypeError, UnicodeError) as error:
                    return f'当月旧统计 {month} 无法读取（{error}）；新行动力记录继续同步，后台会重试'
                # 确认整个月可读后才入队；补传日志本身的写入或认证错误仍须向上传递。
                self._put(connection, points, source=1)
        connection.execute('INSERT INTO metadata VALUES(?,?)', (marker, str(count)))
        return ''

    def capture(self, instance, data, database, force=False):
        """导入完整中央历史，并一次性迁移原实例注册前的旧月总行动力。"""
        with self.lock:
            row = data.get('Dashboard', {}).get('ActionPoint', {})
            point = history_point(row.get('Total'), row.get('Record'))
            warning = self.legacy_warnings.get(instance, '')
            with self._transaction(instance) as connection:
                full = force or time.monotonic() >= self.scanned.get(instance, 0)
                saved = connection.execute("SELECT value FROM metadata WHERE name='source_cursor'").fetchone()
                cursor = int(saved[0]) if saved and not full else 0
                store = AuthenticatedHistoryStore(self.root / 'config')
                identity = self.protection.resolve(instance)
                sealed = self.protection.has_anchor(identity + '/action-point-history')
                # 接口传入的数据库路径不参与选择，来源始终由当前稳定实例身份确定。
                with store.connection(instance, write=not sealed, strict_history=True,
                                      baseline=(row.get('Total'), row.get('Record')) if point and not sealed else None) as source:
                    if source.history_guard is None:
                        source.history_guard = source.history_factory()
                    maximum = source.execute('SELECT COALESCE(MAX(seq),0) FROM action_point_history').fetchone()[0]
                    if maximum < cursor:
                        cursor = 0
                    rows = source.execute('SELECT seq,total,observed_at FROM action_point_history WHERE seq>? ORDER BY seq', (cursor,))
                    while values := rows.fetchmany(2048):
                        points = []
                        for seq, total, recorded in values:
                            parsed = history_point(total, recorded)
                            if parsed:
                                points.append(parsed)
                            cursor = seq
                        self._put(connection, points, source=2)
                    connection.execute("INSERT INTO metadata VALUES('source_cursor',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (str(cursor),))
                if full:
                    warning = self._import_legacy_history(connection, identity) or ''
                latest = connection.execute('SELECT time,total,month FROM samples ORDER BY time DESC LIMIT 1').fetchone()
                self.pending[instance] = bool(connection.execute('SELECT 1 FROM samples WHERE uploaded=0 LIMIT 1').fetchone())
            if full:
                self.scanned[instance] = time.monotonic() + 300
            self.legacy_warnings[instance] = warning
            return latest

    def synchronize(self, instance, identity, key, binding, remote, accepted, force=False):
        """常规仅上传未确认的增量；低频月份摘要不一致时补足该月历史。"""
        from module.api.stock_exchange_identity import make_instance_request
        with self.lock, self._transaction(instance) as connection:
            origin = binding['url'] + '\n' + binding['bindingKey']
            saved = connection.execute("SELECT value FROM metadata WHERE name='origin'").fetchone()
            if not saved or saved[0] != origin:
                connection.execute('UPDATE samples SET uploaded=0')
                connection.execute("INSERT INTO metadata VALUES('origin',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (origin,))
            if not force and time.monotonic() < self.next_send.get(instance, 0):
                return
            rows = connection.execute('SELECT seq,time,total FROM samples WHERE uploaded=0 ORDER BY time').fetchall()
            try:
                if rows:
                    report = make_instance_request(identity, key, 'report', points=[(row[1], row[2]) for row in rows])
                    report['backfill'] = any(row[1] < (time.time() - 86400) * 1000 for row in rows)
                    accepted(remote('/v2/instance/report', 'POST', report))
                    connection.executemany('UPDATE samples SET uploaded=1 WHERE seq=? AND time=? AND total=?', rows)
                    self.pending[instance] = False
                    self.next_send[instance] = 0
                    self.next_check.setdefault(instance, time.monotonic() + 300)
                    self.failures[instance] = 0
                    return
                if not force and time.monotonic() < self.next_check.get(instance, 0):
                    return
                # 不用 cursor 证明完整性；摘要可以发现早期缺点、服务器恢复与同毫秒修正。
                manifest = accepted(remote('/v2/instance/manifest', 'POST', make_instance_request(identity, key, 'manifest')))
                remote_months = {row['month']: row for row in manifest.get('months', [])}
                months = [row[0] for row in connection.execute('SELECT DISTINCT month FROM samples ORDER BY month')]
                mismatch = False
                checked_months = []
                for month in months:
                    points = connection.execute('SELECT time,total FROM samples WHERE month=? ORDER BY time', (month,)).fetchall()
                    digest = hashlib.sha256(''.join(f'{t}:{ap}\n' for t, ap in points).encode()).hexdigest()
                    checked_months.append({'month': month, 'count': len(points), 'digest': digest})
                    actual = remote_months.get(month, {})
                    if actual.get('count') != len(points) or actual.get('digest') != digest:
                        connection.execute('UPDATE samples SET uploaded=0 WHERE month=?', (month,))
                        mismatch = True
                if not mismatch and 'reconcile' in binding.get('capabilities', []):
                    accepted(remote('/v2/instance/reconcile', 'POST', make_instance_request(identity, key, 'reconcile', months=checked_months)))
                self.pending[instance] = mismatch
                self.next_check[instance] = time.monotonic() + 300
                self.next_send[instance] = 0
                self.failures[instance] = 0
            except (ApiError, OSError, ValueError, TypeError, KeyError):
                failures = min(self.failures.get(instance, 0) + 1, 6)
                self.failures[instance] = failures
                self.next_send[instance] = time.monotonic() + min(60, 2 ** failures)
                raise
