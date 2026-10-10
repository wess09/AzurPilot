"""行动力的不可变认证事件链及补传数据库检查点。"""
import hashlib
import hmac
import sqlite3

from module.runtime.game_data import canonical, damaged

GENESIS = '0' * 64


class HistoryConnection(sqlite3.Connection):
    history_guard = None
    history_factory = None
    history_strict = False
    history_disabled = False


class ActionPointChain:
    """保留修正前的事件，以本机密钥认证整条哈希链和当前值索引。"""

    def __init__(self, connection, protection, identity, write=False, baseline=None):
        self.connection, self.protection, self.identity = connection, protection, identity
        self.name = identity + '/action-point-history'
        self.key = protection.key(identity, 'action-point-history')
        self.changed = False
        try:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='action_point_chain'").fetchone()
            if not exists:
                if protection.has_anchor(self.name) or not write:
                    raise damaged('行动力历史哈希链丢失，已停止同步')
                connection.execute('CREATE TABLE action_point_chain (seq INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, total INTEGER NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL)')
                connection.execute('CREATE TABLE action_point_chain_owner (id INTEGER PRIMARY KEY CHECK(id=1), instance_id TEXT NOT NULL)')
                connection.execute('INSERT INTO action_point_chain_owner VALUES(1,?)', (identity,))
                self.head = [0, 0, GENESIS]
                # 旧版本首次迁移只能认证当时尚存的数据，不能证明升级前未被改动。
                rows = connection.execute('SELECT seq,observed_at,total FROM action_point_history ORDER BY seq').fetchall()
                if rows and not protection.record(identity)['baseline']:
                    raise damaged('新实例不能继承其他实例的行动力历史')
                for seq, recorded, total in rows:
                    self._event(seq, recorded, total)
                if not rows and protection.record(identity)['baseline']:
                    # 仅兼容原安全库内的旧观察行；普通总库不会参与认证链初始化。
                    legacy = connection.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone()
                    previous = connection.execute("SELECT total,observed_at FROM observations WHERE resource='ActionPoint'").fetchone() if legacy else None
                    point = previous if previous and previous[0] is not None else baseline
                    if point and type(point[0]) in (int, float) and 0 <= point[0] <= 1_000_000 and int(point[0]) == point[0]:
                        self.append(point[1], int(point[0]))
                self.changed = True
            else:
                self.verify()
        except BaseException:
            self.key.clear()
            raise

    def _hash(self, seq, recorded, total, previous):
        return hmac.new(self.key.value, canonical(['AzurPilot/action-history/v1', self.identity, seq, recorded, total, previous]), hashlib.sha256).hexdigest()

    def _event(self, seq, recorded, total):
        previous = self.head[2]
        digest = self._hash(seq, recorded, total, previous)
        self.connection.execute('INSERT INTO action_point_chain VALUES(?,?,?,?,?)', (seq, recorded, total, previous, digest))
        self.head = [self.head[0] + 1, seq, digest]
        self.changed = True

    def verify(self):
        owner = self.connection.execute('SELECT instance_id FROM action_point_chain_owner WHERE id=1').fetchone()
        if not owner or owner[0] != self.identity:
            raise damaged('行动力历史所属实例不匹配，不能使用其他实例的玩家数据')
        head, latest = [0, 0, GENESIS], {}
        for seq, recorded, total, previous, digest in self.connection.execute('SELECT seq,observed_at,total,previous_hash,hash FROM action_point_chain ORDER BY seq'):
            if (seq <= head[1] or previous != head[2] or type(total) is not int or not 0 <= total <= 1_000_000
                    or not isinstance(recorded, str) or not isinstance(digest, str)
                    or not hmac.compare_digest(digest, self._hash(seq, recorded, total, previous))):
                raise damaged('行动力历史哈希链校验失败，已停止同步')
            head = [head[0] + 1, seq, digest]
            latest[recorded] = (seq, total)
        current = {recorded: (seq, total) for seq, recorded, total in self.connection.execute('SELECT seq,observed_at,total FROM action_point_history')}
        if latest != current:
            raise damaged('行动力历史索引被修改或删行，已停止同步')
        if not self.protection.anchor(self.name, head):
            raise damaged('行动力历史持久检查点丢失，不能自动接受无认证的历史')
        self.head = head

    def append(self, recorded, total):
        existing = self.connection.execute('SELECT total FROM action_point_history WHERE observed_at=?', (recorded,)).fetchone()
        if existing and existing[0] == total:
            return
        seq = self.head[1] + 1
        self._event(seq, recorded, total)
        self.connection.execute('INSERT INTO action_point_history(seq,observed_at,total) VALUES(?,?,?) ON CONFLICT(observed_at) DO UPDATE SET seq=excluded.seq,total=excluded.total',
                                (seq, recorded, total))

    def prepare(self):
        if self.changed:
            self.protection.anchor(self.name, self.head, prepare=True)

    def finish(self):
        if self.changed:
            self.protection.anchor(self.name, self.head)

    def close(self):
        self.key.clear()


class HistorySeal:
    """补传队列的可变游标、回执和样本全部认证，禁止篡改后重新签名上传。"""

    def __init__(self, connection, protection, identity):
        self.connection, self.protection = connection, protection
        self.name = identity + '/upload-history'
        self.key = protection.key(identity, 'upload-history')
        self.identity = identity

    def digest(self):
        result = hmac.new(self.key.value, canonical(['AzurPilot/upload-history/v1', self.identity]), hashlib.sha256)
        count = 0
        for row in self.connection.execute('SELECT seq,time,total,month,uploaded,source FROM samples ORDER BY seq'):
            result.update(canonical(list(row)) + b'\n')
            count += 1
        for row in self.connection.execute('SELECT name,value FROM metadata ORDER BY name'):
            result.update(canonical(list(row)) + b'\n')
        return [count, result.hexdigest()]

    def verify(self):
        actual = self.digest()
        if not self.protection.anchor(self.name, actual) and actual[0]:
            raise damaged('补传日志缺少认证检查点，不能上传未认证的数据')

    def prepare(self):
        self.head = self.digest()
        self.protection.anchor(self.name, self.head, prepare=True)

    def finish(self):
        self.protection.anchor(self.name, self.head)

    def close(self):
        self.key.clear()
