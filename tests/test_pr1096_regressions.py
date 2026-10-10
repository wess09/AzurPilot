"""PR 1096 的存储与时间校验回归，使用替身和临时目录。"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.base import backup
from module.scheduler.models import ProgramDocument
from module.scheduler.runtime import SchedulerRuntime
from module.scheduler.templates import node
from module.scheduler.validation import validate


class ReviewRegressionTests(unittest.TestCase):
    def test_resource_limit_parse_failure_preserves_existing_limit(self):
        from module.campaign.campaign_status import CampaignStatus
        from module.log_res.log_res import LogRes
        for resource in ('Coin', 'Oil'):
            with self.subTest(resource=resource):
                config = SimpleNamespace(data={'Dashboard': {resource: {'Value': 200, 'Limit': 500, 'Record': None}}}, modified={})
                runner = CampaignStatus.__new__(CampaignStatus)
                runner.config = config
                runner.device = Mock()
                runner.appear = Mock(return_value=True)
                runner._get_num = Mock(side_effect=[300, None])
                timer = Mock()
                timer.start.return_value = timer
                timer.reached.return_value = False
                with patch('module.campaign.campaign_status.Timer', return_value=timer), \
                        patch.object(LogRes, '_observe') as observe, \
                        patch.object(LogRes, '_record_all_resource_snapshot'):
                    result = getattr(runner, f'get_{resource.lower()}')()
                self.assertEqual(300, result)
                observe.assert_called_once_with(resource, {'Value': 300})
                self.assertNotIn(f'Dashboard.{resource}.Limit', config.modified)
                self.assertTrue(all(call.kwargs['require_valid'] for call in runner._get_num.call_args_list))

    def test_program_change_storage_failure_retries(self):
        runtime = SchedulerRuntime(SimpleNamespace(config_name='fixture'))
        runtime.store = Mock()
        runtime.generation = 1
        for method in ('exists', 'get'):
            for error in (ValueError('损坏'), TimeoutError('超时'), sqlite3.OperationalError('锁定')):
                with self.subTest(method=method, error=type(error)):
                    runtime.store.exists.side_effect = None
                    runtime.store.exists.return_value = True
                    runtime.store.get.side_effect = None
                    getattr(runtime.store, method).side_effect = error
                    self.assertFalse(runtime.program_changed())
                    getattr(runtime.store, method).side_effect = None
                    runtime.store.get.return_value = {'generation': 2}
                    self.assertTrue(runtime.program_changed())

    def test_time_parameter_formats(self):
        for kind, key, value, valid in (
            ('time_window', 'start', '09:00', True),
            ('time_window', 'start', '9:00', False),
            ('time_window', 'end', '09:00,10:00', False),
            ('time_window', 'start', '2026-09-30T09:00:00', False),
            ('server_day', 'reset', '09:00,18:00', True),
            ('server_day', 'reset', '2026-09-30T09:00:00', False),
            ('wait_until', 'time', '09:00', True),
            ('wait_until', 'time', '2026-09-30T09:00:00', True),
            ('wait_until', 'time', '09:00,18:00', False),
            ('wait_until', 'time', '25:00', False),
        ):
            with self.subTest(kind=kind, value=value):
                doc = ProgramDocument(entry='start', nodes=[node('start', 'entry'), node('time', kind, **{key: value})])
                errors = [d for d in validate(doc)['diagnostics'] if '时间格式无效' in d['message']]
                self.assertEqual(not valid, bool(errors))

    def test_backup_failure_does_not_publish_a_partial_daily_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, target = root / 'config', root / 'backup'
            (config / 'scheduler').mkdir(parents=True)
            target.mkdir()
            for name in ('broken', 'healthy'):
                with closing(sqlite3.connect(config / 'scheduler' / f'{name}.sqlite3')) as connection, connection:
                    connection.execute('CREATE TABLE history(value INTEGER)')
            (config / 'fixture.json').write_text('{}')
            with patch.object(backup, 'CONFIG_DIR', config), patch.object(backup, 'BACKUP_ROOT', target), \
                    patch.object(backup, 'backup_database', return_value=[]), \
                    patch('module.persistence.migration.snapshot_database', side_effect=sqlite3.OperationalError('锁定')):
                with self.assertRaises(sqlite3.OperationalError):
                    backup.backup()
            self.assertEqual(list(target.iterdir()), [])
            self.assertTrue((config / 'scheduler' / 'healthy.sqlite3').exists())
