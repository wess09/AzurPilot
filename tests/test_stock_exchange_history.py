"""完整采集、持久补传、签名与修正测试；所有资源和网络均为隔离夹具。"""
import base64
import hashlib
import json
import sqlite3
import tempfile
import shutil
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from module.api.protocol import ApiError
from module.api.stock_exchange_history import ActionHistory, SHANGHAI, history_point, make_history_report
from module.api.stock_exchange_identity import binding_key, load_identity
from module.api.stock_exchange_service import StockExchangeService, public_stock_path
from module.scheduler.store import ProgramStore


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'project').resolve()
        (self.root / 'config').mkdir(parents=True)
        (self.root / 'config' / 'test.json').write_text(json.dumps({'Alas': {}}), encoding='utf-8')
        self.store = ProgramStore(self.root / 'config')
        self.store.database.ensure_ready()
        self.journal = ActionHistory(self.root)
        self.addCleanup(self.journal.close)
        self.identity, self.key = load_identity(self.root, 'test')
        self.binding = {'url': 'https://stock.nanoda.work', 'bindingKey': binding_key(self.identity, self.key), 'uploadToken': 'test-upload'}
        self.remote_points = {}
        self.calls = []
        self.now = datetime.now(SHANGHAI)
        self.month = self.now.strftime('%Y-%m')

    def remote(self, path, method, body, token, binding):
        self.assertEqual('test-upload', token)
        self.assertEqual(self.binding['bindingKey'], binding)
        self.calls.append((path, body))
        if path == '/quote-history':
            report = body['report']
            canonical = f"mmex-history-v1\n{self.identity}\n{report['publicKey']}\n{report['month']}\n{report['issuedAt']}\n{report['count']}\n{report['digest']}\n" + ''.join(f"{p['time']}:{p['actionPoints']}\n" for p in report['points'])
            self.key.public_key().verify(base64.b64decode(report['signature']), canonical.encode())
            self.remote_points.update({p['time']: p['actionPoints'] for p in report['points']})
            if report['digest']:
                self.assertEqual(self.manifest(report['month'])['digest'], report['digest'])
        return {'status': 200, 'data': self.manifest(path.rsplit('=', 1)[-1]) if '/manifest?' in path else {'ok': True}}

    def manifest(self, month):
        values = sorted((t, ap) for t, ap in self.remote_points.items() if datetime.fromtimestamp(t / 1000, SHANGHAI).strftime('%Y-%m') == month)
        return {'count': len(values), 'digest': hashlib.sha256(''.join(f'{t}:{ap}\n' for t, ap in values).encode()).hexdigest()}

    def sync(self, journal=None, remote=None):
        (journal or self.journal).synchronize('test', self.identity, self.key, self.binding, remote or self.remote, StockExchangeService._accepted, force=True)

    def legacy_stats(self, snapshots, instance='test', month=None):
        path = self.root / 'config' / 'cl1_data.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS cl1_data(instance TEXT,month TEXT,data_json TEXT,encrypted_blob BLOB,PRIMARY KEY(instance,month))')
            db.execute('INSERT OR REPLACE INTO cl1_data VALUES(?,?,?,NULL)',
                       (instance, month or self.month, json.dumps({'ap_snapshots': snapshots})))
        return path

    def test_legacy_month_import_is_once_and_precise_observation_wins(self):
        earlier = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 6000},
                           {'ts': self.now.isoformat(), 'ap_total': 9999},
                           {'ts': (earlier + timedelta(seconds=1)).isoformat(), 'ap': 100},
                           {'ts': (earlier + timedelta(seconds=2)).isoformat(), 'ap_total': True}])
        self.store.observe('test', 'ActionPoint', {'Total': 8000}, self.now.isoformat(), 'fixture')
        self.journal.capture('test', {}, self.store.history.path('test'))
        self.sync()
        expected = {history_point(6000, earlier.isoformat())[0]: 6000,
                    history_point(8000, self.now.isoformat())[0]: 8000}
        self.assertEqual(expected, self.remote_points)
        # 迁移后修改旧统计库不能重新获得签名；重启仍沿用已认证的迁移状态。
        self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 9999},
                           {'ts': (earlier + timedelta(seconds=3)).isoformat(), 'ap_total': 8888}])
        self.journal.close()
        cold = ActionHistory(self.root)
        self.addCleanup(cold.close)
        cold.capture('test', {}, self.store.history.path('test'), force=True)
        self.sync(cold)
        self.assertEqual(expected, self.remote_points)

    def test_copied_instance_cannot_import_old_statistics(self):
        earlier = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 9999}], instance='copy')
        (self.root / 'config' / 'copy.json').write_bytes((self.root / 'config' / 'test.json').read_bytes())
        self.assertIsNone(self.journal.capture('copy', {}, self.store.history.path('copy')))
        connection, _ = self.journal._connection('copy')
        self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM samples').fetchone()[0])

    def test_legacy_encrypted_month_is_read_only_and_other_instances_stay_isolated(self):
        from Crypto.Cipher import AES
        from module.statistics.cl1_legacy import derive_legacy_key
        earlier = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        raw = json.dumps({'ap_snapshots': [{'ts': earlier.isoformat(), 'ap_total': 6000}]}).encode()
        path = self.legacy_stats([{'ts': (earlier + timedelta(seconds=1)).isoformat(), 'ap_total': 12345}], instance='other')
        cipher = AES.new(derive_legacy_key('test-device'), AES.MODE_GCM)
        payload, tag = cipher.encrypt_and_digest(raw)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('INSERT INTO cl1_data VALUES(?,?,NULL,?)',
                       ('test', self.month, cipher.nonce + tag + payload))
        original = path.read_bytes()
        with patch('module.base.device_id.get_device_id', return_value='test-device'), \
                patch('module.base.device_id.get_old_device_id', return_value=None):
            self.journal.capture('test', {}, self.store.history.path('test'))
        self.sync()
        self.assertEqual({history_point(6000, earlier.isoformat())[0]: 6000}, self.remote_points)
        self.assertEqual(original, path.read_bytes())

    def test_legacy_import_survives_rename_before_first_capture(self):
        earlier = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 6000}])
        (self.root / 'config' / 'test.json').rename(self.root / 'config' / 'renamed.json')
        self.journal.capture('renamed', {}, self.store.history.path('renamed'))
        self.journal.synchronize('renamed', self.identity, self.key, self.binding, self.remote, StockExchangeService._accepted, force=True)
        self.assertEqual({history_point(6000, earlier.isoformat())[0]: 6000}, self.remote_points)

    def test_previous_legacy_month_is_not_read_or_changed(self):
        earlier = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        previous = (earlier - timedelta(days=1)).strftime('%Y-%m')
        path = self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 6000}])
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('INSERT INTO cl1_data VALUES(?,?,NULL,?)', ('test', previous, b'unreadable-old-ciphertext'))
        original = path.read_bytes()
        self.store.observe('test', 'ActionPoint', {'Total': 8000}, self.now.isoformat(), 'fixture')
        with patch('module.base.device_id.get_device_id') as device:
            self.journal.capture('test', {}, self.store.history.path('test'))
        device.assert_not_called()
        self.sync()
        self.assertEqual({history_point(6000, earlier.isoformat())[0]: 6000,
                          history_point(8000, self.now.isoformat())[0]: 8000}, self.remote_points)
        self.assertEqual('', self.journal.legacy_warnings['test'])
        self.assertEqual(original, path.read_bytes())

    def test_unreadable_current_month_keeps_live_history_and_retries_after_repair(self):
        earlier = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        path = self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 6000}])
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('UPDATE cl1_data SET data_json=?', ('broken-json',))
        original = path.read_bytes()
        self.store.observe('test', 'ActionPoint', {'Total': 8000}, self.now.isoformat(), 'fixture')
        self.assertEqual(history_point(8000, self.now.isoformat()), self.journal.capture('test', {}, self.store.history.path('test')))
        self.assertIn(self.month, self.journal.legacy_warnings['test'])
        self.assertEqual(original, path.read_bytes())
        connection, _ = self.journal._connection('test')
        self.assertIsNone(connection.execute("SELECT 1 FROM metadata WHERE name='legacy_ap_history_v1'").fetchone())
        self.sync()
        self.assertEqual({history_point(8000, self.now.isoformat())[0]: 8000}, self.remote_points)
        # 断网或重启不丢中央记录；修复当月旧数据后仍可导入，不需重新开户。
        self.journal.close()
        cold = ActionHistory(self.root)
        self.addCleanup(cold.close)
        self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 6000}])
        cold.capture('test', {}, self.store.history.path('test'), force=True)
        self.sync(cold)
        self.assertEqual({history_point(6000, earlier.isoformat())[0]: 6000,
                          history_point(8000, self.now.isoformat())[0]: 8000}, self.remote_points)
        self.assertEqual('', cold.legacy_warnings['test'])

    def test_unreadable_legacy_database_never_blocks_central_history(self):
        path = self.root / 'config' / 'cl1_data.db'
        path.write_bytes(b'not-a-sqlite-database')
        self.store.observe('test', 'ActionPoint', {'Total': 8000}, self.now.isoformat(), 'fixture')
        self.journal.capture('test', {}, self.store.history.path('test'))
        self.sync()
        self.assertEqual({history_point(8000, self.now.isoformat())[0]: 8000}, self.remote_points)
        self.assertIn('database', self.journal.legacy_warnings['test'])
        self.assertEqual(b'not-a-sqlite-database', path.read_bytes())

    def test_failed_legacy_retry_is_not_postponed_by_new_samples(self):
        path = self.legacy_stats([])
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('UPDATE cl1_data SET data_json=?', ('broken-json',))
        self.store.observe('test', 'ActionPoint', {'Total': 8000}, self.now.isoformat(), 'fixture')
        with patch('module.api.stock_exchange_history.time.monotonic', return_value=0):
            self.journal.capture('test', {}, self.store.history.path('test'))
        self.store.observe('test', 'ActionPoint', {'Total': 8100}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
        with patch('module.api.stock_exchange_history.time.monotonic', return_value=100):
            self.journal.capture('test', {}, self.store.history.path('test'))
        self.assertEqual(300, self.journal.scanned['test'])
        earlier = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        self.legacy_stats([{'ts': earlier.isoformat(), 'ap_total': 6000}])
        with patch('module.api.stock_exchange_history.time.monotonic', return_value=301):
            self.journal.capture('test', {}, self.store.history.path('test'))
        self.sync()
        self.assertEqual(6000, self.remote_points[history_point(6000, earlier.isoformat())[0]])
        self.assertEqual('', self.journal.legacy_warnings['test'])

    def test_central_history_keeps_each_sample_and_correction_without_partial_refresh(self):
        first = self.now.isoformat()
        second = (self.now + timedelta(seconds=1)).isoformat()
        self.store.observe('test', 'ActionPoint', {'Value': 100, 'Total': 9000}, first, 'fixture')
        self.store.observe('test', 'ActionPoint', {'Value': 100, 'Total': 9000}, first, 'fixture')
        with self.store.history.connection('test') as connection:
            seq = connection.execute('SELECT seq FROM action_point_history').fetchone()[0]
        self.store.observe('test', 'ActionPoint', {'Value': 80}, second, 'fixture')
        self.store.observe('test', 'ActionPoint', {'Value': 100, 'Total': 9100}, first, 'fixture')
        with self.store.history.connection('test') as connection:
            rows = connection.execute('SELECT seq,observed_at,total FROM action_point_history').fetchall()
        self.assertEqual(1, len(rows));self.assertGreater(rows[0][0], seq);self.assertEqual(9100, rows[0][2]);self.assertEqual(first, rows[0][1])
        point = self.journal.capture('test', {}, self.store.history.path('test'))
        self.assertEqual(history_point(9100, first), point)
        self.sync()
        # 落后配置不能把中央历史的迟到修正覆盖回去。
        self.journal.capture('test', {'Dashboard': {'ActionPoint': {'Total': 9000, 'Record': first}}}, self.store.history.path('test'))
        self.sync()
        self.assertEqual({point[0]: 9100}, self.remote_points)

    def test_more_than_2000_records_offline_restart_backfill_and_exact_reconciliation(self):
        start = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=123000)
        with self.store.history.connection('test', write=True) as connection:
            for i in range(3001):
                self.store._write_observation(connection, 'ActionPoint', {'Total': 7000 + i % 40}, (start + timedelta(seconds=i)).isoformat(), 'fixture')
        self.journal.capture('test', {}, self.store.history.path('test'))
        failure = ApiError('STOCK_UNAVAILABLE', '隔离断网夹具')
        for _ in range(5):
            with self.assertRaises(ApiError):
                self.sync(remote=lambda *args: (_ for _ in ()).throw(failure))
        self.assertEqual({}, self.remote_points)
        self.journal.close()
        recovered = ActionHistory(self.root)
        self.addCleanup(recovered.close)
        for _ in range(5):
            self.sync(recovered)
        self.assertEqual(3001, len(self.remote_points))
        batches = [body['report']['points'] for path, body in self.calls if path == '/quote-history' and body['report']['points']]
        self.assertTrue(any(len(batch) == 3001 for batch in batches))
        self.assertTrue(all(all(a['time'] < b['time'] for a, b in zip(batch, batch[1:])) for batch in batches))
        original = next(iter(self.remote_points))
        self.remote_points.pop(original)  # 服务器缺行，摘要发现后重新排队修复。
        for _ in range(6):
            self.sync(recovered)
        self.assertEqual(3001, len(self.remote_points))
        self.assertTrue(any(body and body['report']['digest'] for _, body in self.calls))
        # 同一毫秒修正后游标能再导入，重复读不会产生第二条。
        self.store.observe('test', 'ActionPoint', {'Total': 9999}, start.isoformat(), 'fixture')
        recovered.capture('test', {}, self.store.history.path('test'))
        for _ in range(2):self.sync(recovered)
        self.assertEqual(9999, self.remote_points[history_point(9999, start.isoformat())[0]])
        self.assertEqual(3001, len(self.remote_points))

    def test_whitelist_and_transport_formats(self):
        self.assertTrue(public_stock_path('/stocks/1?period=m20&month=2026-10&day=2026-10-01'))
        for path in ['/stocks/1?period=m5&period=day', '/stocks/1?token=secret', '/stocks/1#fragment', '/quote-history/manifest?month=2026-10', '//evil.test/stocks/1']:
            self.assertFalse(public_stock_path(path))
        self.assertIsNone(history_point(True, self.now.isoformat()))
        self.assertIsNone(history_point(float('nan'), self.now.isoformat()))
        self.assertEqual(8000, history_point(8000.0, self.now.isoformat())[1])
        report = make_history_report(self.identity, self.key, self.month, [(1000, 8000)])
        self.assertNotIn('privateKey', report)

    def test_new_current_month_records_do_not_starve_previous_month(self):
        previous = self.now.replace(day=1, hour=0, minute=0, second=0) - timedelta(seconds=1)
        database = self.store.history.path('test')
        self.store.observe('test', 'ActionPoint', {'Total': 6000}, previous.isoformat(), 'fixture')
        self.store.observe('test', 'ActionPoint', {'Total': 7000}, self.now.isoformat(), 'fixture')
        self.journal.capture('test', {}, database)
        self.sync()  # 先传本月最新值。
        updated = self.now + timedelta(seconds=1)
        self.store.observe('test', 'ActionPoint', {'Total': 7100}, updated.isoformat(), 'fixture')
        self.journal.capture('test', {}, database)
        self.sync()  # 本月仍有新记录，也必须轮到上月。
        self.assertIn(history_point(6000, previous.isoformat())[0], self.remote_points)
        self.sync()
        self.assertEqual(7100, self.remote_points[history_point(7100, updated.isoformat())[0]])

    def seed(self):
        for i in range(3):
            self.store.observe('test', 'ActionPoint', {'Total': 7000 + i}, (self.now + timedelta(seconds=i)).isoformat(), 'fixture')
        self.journal.capture('test', {}, self.store.history.path('test'))

    def test_corrections_keep_immutable_events(self):
        self.seed()
        self.store.observe('test', 'ActionPoint', {'Total': 8000}, self.now.isoformat(), 'fixture')
        with self.store.history.connection('test') as db:
            events = db.execute('SELECT total FROM action_point_chain ORDER BY seq').fetchall()
            current = db.execute('SELECT total FROM action_point_history WHERE observed_at=?', (self.now.isoformat(),)).fetchone()
        self.assertEqual([7000, 7001, 7002, 8000], [row[0] for row in events])
        self.assertEqual(8000, current[0])

    def test_edits_and_deletions_of_history_are_rejected(self):
        self.seed()
        path = self.store.history.path('test')
        for sql in ("UPDATE action_point_history SET total=9999 WHERE seq=1", "DELETE FROM action_point_history WHERE seq=2", "UPDATE action_point_chain SET total=9999 WHERE seq=1", "DROP TABLE action_point_chain"):
            backup = self.root / 'original.sqlite3'
            self.store.history.backup('test', backup)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(sql)
            with self.assertRaises(ApiError):
                self.journal.capture('test', {}, path, force=True)
            self.assertEqual([], self.calls)
            for suffix in ('-wal', '-shm'):
                path.with_name(path.name + suffix).unlink(missing_ok=True)
            shutil.copyfile(backup, path)

    def test_consistent_tail_truncation_is_rejected_by_external_checkpoint(self):
        self.seed()
        with closing(sqlite3.connect(self.store.history.path('test'))) as db, db:
            db.execute('DELETE FROM action_point_chain WHERE seq=3')
            db.execute('DELETE FROM action_point_history WHERE seq=3')
        with self.assertRaises(ApiError):
            self.journal.capture('test', {}, self.store.history.path('test'), force=True)

    def test_old_source_database_cannot_be_replayed(self):
        self.seed()
        backup = self.root / 'earlier.sqlite3'
        self.store.history.backup('test', backup)
        self.store.observe('test', 'ActionPoint', {'Total': 8000}, (self.now + timedelta(seconds=4)).isoformat(), 'fixture')
        path = self.store.history.path('test')
        for suffix in ('-wal', '-shm'):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        shutil.copyfile(backup, path)
        with self.assertRaises(ApiError):
            self.journal.capture('test', {}, path, force=True)

    def test_pending_checkpoint_recovers_both_commit_outcomes(self):
        self.seed()
        from module.runtime.game_data import GameDataProtector
        protection = GameDataProtector(self.root)
        name = self.identity + '/action-point-history'
        with protection.transaction() as (data, _):
            head = list(data['anchors'][name]['head'])
        protection.anchor(name, [4, 4, 'f' * 64], prepare=True)
        self.journal.capture('test', {}, self.store.history.path('test'), force=True)
        with protection.transaction() as (data, _):
            self.assertEqual({'head': head}, data['anchors'][name])
        from module.scheduler.action_history import ActionPointChain
        with self.assertRaises(OSError), patch.object(ActionPointChain, 'finish', side_effect=OSError('隔离崩溃夹具')):
            with self.store.history.connection('test', write=True, strict_history=True) as db:
                self.store._write_observation(db, 'ActionPoint', {'Total': 8000}, (self.now + timedelta(seconds=5)).isoformat(), 'fixture')
        with protection.transaction() as (data, _):
            self.assertIn('pending', data['anchors'][name])
        self.journal.capture('test', {}, self.store.history.path('test'), force=True)
        with protection.transaction() as (data, _):
            self.assertNotIn('pending', data['anchors'][name])
            self.assertEqual(4, data['anchors'][name]['head'][0])

    def test_queue_sample_cursor_and_receipt_tampering_never_reaches_remote(self):
        self.seed()
        self.sync()
        connection, identity = self.journal._connection('test')
        for sql in ("UPDATE samples SET total=9999 WHERE seq=1", "UPDATE samples SET uploaded=0", "UPDATE metadata SET value='999999' WHERE name='source_cursor'"):
            backup = self.root / 'queue.sqlite3'
            with closing(sqlite3.connect(backup)) as saved:
                connection.backup(saved)
            with closing(sqlite3.connect(self.journal.paths[identity])) as db, db:
                db.execute(sql)
            before = len(self.calls)
            with self.assertRaises(ApiError):
                self.sync()
            self.assertEqual(before, len(self.calls))
            with closing(sqlite3.connect(backup)) as saved:
                saved.backup(connection)

    def test_missing_source_and_queue_are_not_rebuilt_from_dashboard(self):
        self.seed()
        path = self.store.history.path('test')
        for suffix in ('', '-wal', '-shm'):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        with self.assertRaises(ApiError):
            self.journal.capture('test', {'Dashboard': {'ActionPoint': {'Total': 9999, 'Record': self.now.isoformat()}}}, path, force=True)
        _, identity = self.journal._connection('test')
        self.journal.close()
        path = self.journal.paths[identity]
        for suffix in ('', '-wal', '-shm'):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        with self.assertRaises(ApiError):
            self.sync()


if __name__ == '__main__':
    unittest.main()
