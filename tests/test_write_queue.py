"""排队写入的合并、保序与失败重试。"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from module.persistence.database import close_all, create_schema, get_database
from module.persistence.write_queue import WriteQueue


class WriteQueueTests(unittest.TestCase):
    def setUp(self):
        """准备一个只有单表的最小总库，跳过旧来源迁移。"""
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch('module.persistence.database.BusinessDatabase.ensure_ready', lambda self: None))
        self.database = get_database(self.directory)
        with closing(sqlite3.connect(self.database.path)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            create_schema(connection)
            connection.execute('CREATE TABLE samples (name TEXT, value INTEGER)')
            connection.commit()
        self.queue = WriteQueue()
        self.enterContext(patch.object(self.queue, '_schedule'))

    def tearDown(self):
        close_all()

    @staticmethod
    def insert(name, value):
        def apply(connection):
            connection.execute('INSERT INTO samples (name, value) VALUES (?, ?)', (name, value))
        return apply

    def rows(self):
        with self.database.transaction(write=False) as connection:
            return connection.execute('SELECT name, value FROM samples ORDER BY rowid').fetchall()

    def test_latest_keeps_only_newest_value_per_key(self):
        self.queue.enqueue('latest', 'oil', self.insert('oil', 1), directory=self.directory)
        self.queue.enqueue('latest', 'oil', self.insert('oil', 2), directory=self.directory)
        self.queue.enqueue('latest', 'coin', self.insert('coin', 3), directory=self.directory)
        self.assertTrue(self.queue.flush())
        self.assertEqual([tuple(row) for row in self.rows()], [('oil', 2), ('coin', 3)])

    def test_append_keeps_every_item_in_order(self):
        for value in (1, 2, 3):
            self.queue.enqueue('append', None, self.insert('sample', value), directory=self.directory)
        self.assertTrue(self.queue.flush())
        self.assertEqual([tuple(row) for row in self.rows()], [('sample', 1), ('sample', 2), ('sample', 3)])

    def test_one_transaction_per_flush(self):
        sessions = []
        original = self.database.session

        def counting(*args, **kwargs):
            sessions.append(1)
            return original(*args, **kwargs)

        with patch.object(self.database, 'session', counting):
            for value in range(5):
                self.queue.enqueue('append', None, self.insert('sample', value), directory=self.directory)
            self.assertTrue(self.queue.flush())
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(self.rows()), 5)

    def test_busy_failure_keeps_items_for_next_flush(self):
        attempts = []

        def failing(connection):
            attempts.append(1)
            if len(attempts) == 1:
                raise sqlite3.OperationalError('database is locked')
            self.insert('sample', 1)(connection)

        self.queue.enqueue('append', None, failing, directory=self.directory)
        self.assertFalse(self.queue.flush())
        self.assertEqual(self.queue.pending(), 1)
        self.assertTrue(self.queue.flush())
        self.assertEqual([tuple(row) for row in self.rows()], [('sample', 1)])

    def test_permanent_failure_drops_the_batch(self):
        def broken(connection):
            raise sqlite3.IntegrityError('boom')

        self.queue.enqueue('append', None, broken, directory=self.directory)
        self.assertTrue(self.queue.flush())
        self.assertEqual(self.queue.pending(), 0)

    def test_flush_without_pending_items(self):
        self.assertTrue(self.queue.flush())
        self.assertEqual(self.queue.pending(), 0)


if __name__ == '__main__':
    unittest.main()
