"""加密阶段登记与实例重命名中断恢复的回归测试。"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from module.api.protocol import ApiError
from module.api.stock_exchange_identity import load_identity
from module.persistence.scheduler import read_observations, write_observation
from module.runtime.game_data import GameDataProtector
from module.scheduler.store import ProgramStore


class ProfileRelocationTests(unittest.TestCase):
    """验证断电/异常重试不会接管或覆盖不相关的实例历史。"""

    def setUp(self):
        """初始化独立安装目录及同时包含普通和受保护历史的实例。"""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'project'
        self.config_dir = self.root / 'config'
        self.config_dir.mkdir(parents=True)
        self.config = self.config_dir / 'test.json'
        self.config.write_text(json.dumps({'Alas': {}}), encoding='utf-8')
        self.identity, _ = load_identity(self.root, 'test')
        self.protector = GameDataProtector(self.root)
        self.store = ProgramStore(self.config_dir)
        with self.store.database.transaction() as db:
            write_observation(db, 'test', 'Oil', 500, '2026-10-10T00:00:00', 'test')
        self.source = self.config_dir / 'scheduler' / 'test.sqlite3'
        self.source.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('CREATE TABLE preserved (value TEXT)')
            db.execute('INSERT INTO preserved VALUES (?)', ('signed-history-preserved',))
        self.target = self.source.with_name('renamed.sqlite3')
        self.config.rename(self.config_dir / 'renamed.json')
        self.assertEqual(self.identity, self.protector.resolve('renamed'))

    def assert_completed(self):
        """确认历史、调度数据及加密登记均只归属于新实例。"""
        self.assertFalse(self.source.exists())
        with closing(sqlite3.connect(self.target)) as db, db:
            self.assertEqual('signed-history-preserved',
                             db.execute('SELECT value FROM preserved').fetchone()[0])
        with self.store.database.transaction(write=False) as db:
            self.assertEqual({}, read_observations(db, 'test'))
            self.assertIn('Oil', read_observations(db, 'renamed'))
        record = self.protector.record(self.identity)
        self.assertEqual('renamed', record['schedulerName'])
        self.assertNotIn('relocation', record)

    def test_retry_after_ordinary_commit(self):
        """调度数据先完成而历史备份失败时，下一次请求可安全续跑。"""
        with patch('module.runtime.profile_relocation._snapshot', side_effect=OSError('模拟备份失败')):
            with self.assertRaises(OSError):
                self.protector.relocate_scheduler('renamed', self.identity)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())
        self.assertIn('relocation', self.protector.record(self.identity))
        self.protector.relocate_scheduler('renamed', self.identity)
        self.assert_completed()

    def test_retry_after_target_publish(self):
        """发布目标后、清除来源前中断时，通过登记的摘要识别重复副本。"""
        with patch('module.runtime.profile_relocation._discard_source', side_effect=OSError('模拟中断')):
            with self.assertRaises(OSError):
                self.protector.relocate_scheduler('renamed', self.identity)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(64, len(self.protector.record(self.identity)['relocation']['digest']))
        self.protector.relocate_scheduler('renamed', self.identity)
        self.assert_completed()

    def test_tampered_target_is_not_adopted(self):
        """目标副本被修改后拒绝恢复，两个原件和身份登记都保留。"""
        with patch('module.runtime.profile_relocation._discard_source', side_effect=OSError('模拟中断')):
            with self.assertRaises(OSError):
                self.protector.relocate_scheduler('renamed', self.identity)
        self.target.write_bytes(b'an unrelated history')
        with self.assertRaises(ApiError) as failure:
            self.protector.relocate_scheduler('renamed', self.identity)
        self.assertEqual('STOCK_STORAGE_DAMAGED', failure.exception.code)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual('test', self.protector.record(self.identity)['schedulerName'])

    def test_unrelated_existing_target_fails_before_mutation(self):
        """旧来源与其他目标历史同时存在时拒绝登记迁移。"""
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('CREATE TABLE unrelated (id INTEGER)')
        with self.assertRaises(ApiError) as failure:
            self.protector.relocate_scheduler('renamed', self.identity)
        self.assertEqual('STOCK_STORAGE_DAMAGED', failure.exception.code)
        self.assertEqual('test', self.protector.record(self.identity)['schedulerName'])
        self.assertNotIn('relocation', self.protector.record(self.identity))
        self.assertTrue(self.source.exists())


if __name__ == '__main__':
    unittest.main()
