"""验证每日备份的开关与保留天数清理。

只跑纯文件系统逻辑：备份根目录与 config 目录都指向临时目录，
不依赖模拟器，也不会碰真实的 config 文件与备份目录。
"""

import json
import shutil
import tempfile
import unittest
from tests.opsi_test_support import install_store
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from module.base import backup as backup_module


def make_backup_dir(root, days_ago):
    """
    在备份根目录下建出一个 N 天前的备份目录。

    Args:
        root (Path): 备份根目录。
        days_ago (int): 距今天数，0 表示今天。

    Returns:
        Path: 创建出的备份目录。
    """
    date = datetime.now().date() - timedelta(days=days_ago)
    folder = root / date.strftime('%Y-%m-%d')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class BackupTestCase(unittest.TestCase):
    """把备份根目录与 config 目录隔离到临时目录。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='backup_test_'))
        self.backup_root = self.root / 'AzurPilot_Data_Backup'
        self.backup_root.mkdir()
        self.config_dir = self.root / 'config'
        self.config_dir.mkdir()
        install_store(self, self.root)

        self._patches = [
            patch.object(backup_module, 'BACKUP_ROOT', self.backup_root),
            patch.object(backup_module, 'CONFIG_DIR', self.config_dir),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def existing_dates(self):
        """
        列出备份根目录下现有的备份目录名。

        Returns:
            list[str]: 按名称排序的目录名。
        """
        return sorted(
            folder.name for folder in self.backup_root.iterdir() if folder.is_dir()
        )

    def date_name(self, days_ago):
        """
        返回 N 天前的备份目录名。

        Args:
            days_ago (int): 距今天数。

        Returns:
            str: `YYYY-MM-DD` 格式的目录名。
        """
        date = datetime.now().date() - timedelta(days=days_ago)
        return date.strftime('%Y-%m-%d')


class BackupSwitchTestCase(BackupTestCase):
    """开关关闭时既不新建备份，也不删除已有备份。"""

    def test_disabled_does_not_create_backup(self):
        backup_module.backup(enable=False)
        self.assertEqual(self.existing_dates(), [])

    def test_disabled_does_not_clean_expired(self):
        make_backup_dir(self.backup_root, 30)
        backup_module.backup(enable=False, keep_days=7)
        self.assertEqual(self.existing_dates(), [self.date_name(30)])

    def test_enabled_creates_today_backup(self):
        backup_module.backup(enable=True)
        info = self.backup_root / self.date_name(0) / 'backup_info.json'
        self.assertTrue(info.exists(), msg='未生成今日备份目录或 backup_info.json')

        with open(info, encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('backup_time', data)
        self.assertIn('files', data)

    def test_enabled_backs_up_user_config(self):
        config = self.config_dir / 'alas.json'
        config.write_text('{"General": {}}', encoding='utf-8')
        template = self.config_dir / 'template.json'
        template.write_text('{}', encoding='utf-8')

        backup_module.backup(enable=True)

        folder = self.backup_root / self.date_name(0)
        self.assertTrue((folder / 'alas.json').exists(), msg='用户配置未被备份')
        self.assertFalse((folder / 'template.json').exists(), msg='模板文件不应被备份')

    def test_existing_backup_is_skipped(self):
        folder = self.backup_root / self.date_name(0)
        folder.mkdir()
        sentinel = folder / 'sentinel.txt'
        sentinel.write_text('keep', encoding='utf-8')

        backup_module.backup(enable=True)

        self.assertTrue(sentinel.exists(), msg='已存在的今日备份被覆盖')
        self.assertFalse((folder / 'backup_info.json').exists())

    def test_stats_backup_is_a_plain_readable_database(self):
        from tests.test_opsi_secure import make_cl1_db
        import sqlite3
        from contextlib import closing
        make_cl1_db(self.config_dir / 'cl1_data.db')
        backup_module.backup(enable=True)
        path = self.backup_root / self.date_name(0) / 'azurpilot.db'
        self.assertEqual(path.read_bytes()[:16], b'SQLite format 3\x00')
        with closing(sqlite3.connect(path)) as conn:
            row = conn.execute('SELECT amount FROM akashi_ap_purchases').fetchone()
        self.assertEqual(row[0], 20)

    def test_old_stats_backup_expiry_is_removed(self):
        folder = make_backup_dir(self.backup_root, 30)
        (folder / 'daily_summary.db').write_bytes(b'old preserved snapshot')
        backup_module.clean_backup(keep_days=7)
        self.assertFalse(folder.exists())


class BackupCleanupTestCase(BackupTestCase):
    """保留天数决定哪些历史备份会被删除。"""

    def test_expired_backup_is_removed(self):
        make_backup_dir(self.backup_root, 2)
        make_backup_dir(self.backup_root, 10)

        backup_module.backup(enable=True, keep_days=7)

        dates = self.existing_dates()
        self.assertIn(self.date_name(0), dates)
        self.assertIn(self.date_name(2), dates)
        self.assertNotIn(self.date_name(10), dates)

    def test_keep_days_boundary(self):
        make_backup_dir(self.backup_root, 7)
        make_backup_dir(self.backup_root, 8)

        backup_module.backup(enable=True, keep_days=7)

        dates = self.existing_dates()
        self.assertIn(self.date_name(7), dates, msg='刚好到达保留天数的备份不应被删除')
        self.assertNotIn(self.date_name(8), dates, msg='超出保留天数的备份应被删除')

    def test_keep_days_can_be_extended(self):
        make_backup_dir(self.backup_root, 10)

        backup_module.backup(enable=True, keep_days=30)

        self.assertIn(self.date_name(10), self.existing_dates())

    def test_non_date_folder_is_kept(self):
        manual = self.backup_root / 'manual'
        manual.mkdir()

        backup_module.backup(enable=True, keep_days=1)

        self.assertTrue(manual.exists(), msg='非日期命名的目录不应被删除')

    def test_invalid_keep_days_keeps_today(self):
        make_backup_dir(self.backup_root, 2)

        backup_module.backup(enable=True, keep_days=0)

        self.assertIn(self.date_name(0), self.existing_dates())
        self.assertNotIn(self.date_name(2), self.existing_dates())


class BackupConfigTestCase(unittest.TestCase):
    """备份开关与保留天数必须是 Alas 任务上的配置项，旧配置能补齐默认值。"""

    def make_config(self, **groups):
        """
        在内存中构造一份待绑定的配置。

        Args:
            **groups: 模拟的 Alas 任务已有配置组，缺省为空（等同全新配置）。

        Returns:
            AzurLaneConfig: 尚未绑定任务的配置对象。
        """
        from module.config.config import AzurLaneConfig

        config = AzurLaneConfig('template')
        config.auto_update = False
        config.data = config.config_update({'Alas': groups})
        return config

    def test_defaults_are_bound_to_alas_task(self):
        config = self.make_config()
        config.bind('Alas')

        self.assertEqual(config.bound['Backup_Enable'], 'Alas.Backup.Enable')
        self.assertEqual(config.bound['Backup_KeepDays'], 'Alas.Backup.KeepDays')
        self.assertEqual(config.Backup_Enable, True)
        self.assertEqual(config.Backup_KeepDays, 7)

    def test_old_config_gets_backup_defaults(self):
        # 模拟旧版本的用户配置：只有 Emulator 组，没有 Backup 组
        config = self.make_config(Emulator={'Serial': 'auto'})
        config.bind('Alas')

        self.assertEqual(config.Backup_Enable, True)
        self.assertEqual(config.Backup_KeepDays, 7)

    def test_user_value_is_kept(self):
        config = self.make_config(Backup={'Enable': False, 'KeepDays': 30})
        config.bind('Alas')

        self.assertEqual(config.Backup_Enable, False)
        self.assertEqual(config.Backup_KeepDays, 30)
