import sqlite3
import sys
import tempfile
import types
import unittest
from tests.opsi_test_support import install_store
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alas import AzurLaneAutoScript
import module.statistics.commission_income_stats as commission_income_stats
import module.statistics.daily_summary as daily_summary
import module.statistics.resource_stats as resource_stats
from module.statistics.daily_summary import (
    DAILY_SUMMARY_SYSTEM_PROMPT,
    DAILY_SUMMARY_TITLE,
    DailySummaryService,
    get_daily_summary_window,
    parse_daily_summary_trigger,
    resolve_daily_summary_server,
)
from module.statistics.daily_summary_store import DailySummaryStore


def temporary_directory():
    """建一个容忍清理失败的临时目录。

    Windows 上 SQLite 文件在最后一个连接关闭后仍可能被短暂占用
    （杀毒扫描、句柄回收延迟等），cleanup 会抛 WinError 32/145。
    目录本来就在 %TEMP% 下，清不掉不该判定用例失败。
    """
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def sample_facts():
    return {
        'window': {
            'instance': 'test',
            'server': 'cn',
            'start': '2026-08-20 20:00:00',
            'end': '2026-08-21 20:00:00',
            'duration_hours': 24,
        },
        'automation': {
            'available': True,
            'run_count': 12,
            'success_count': 10,
            'recoverable_count': 2,
            'failed_count': 0,
            'duration_seconds': 240,
            'task_breakdown': [],
        },
        'resources': [
            {'key': 'Oil', 'label': '石油', 'start': 100, 'end': 120, 'delta': 20},
            {'key': 'Coin', 'label': '金币', 'start': 200, 'end': 250, 'delta': 50},
        ],
        'commission': {
            'available': True,
            'settled_count': 3,
            'items': {
                'Gem': {'total': 1},
                'Cube': {'total': 2},
            },
        },
        'cl1': {
            'available': True,
            'battles': 4,
            'estimated_exp': 1248,
            'duration_seconds': 240,
        },
        'data_quality': {'unavailable': [], 'warnings': []},
    }


def valid_report_text():
    return (
        '主人，昨天晚上到今天晚上，脚本跑了12次，10次返回成功，'
        '有2次进入自动恢复流程，没有不可恢复失败。\n\n'
        '石油从100到120，金币从200到250；委托结算3项，拿到钻石1和魔方2。'
        '侵蚀1打了4场，估算经验1248。那两次自动恢复之后，顺手留意一下就好。'
    )


def summary_config(**overrides):
    values = {
        'DailySummary_Enable': True,
        'DailySummary_TriggerTime': '20:00',
        'Emulator_PackageName': 'com.bilibili.azurlane',
        'Emulator_ServerName': 'disabled',
        'SERVER': 'cn',
        'Error_LlmApiKey': 'test-key',
        'Error_LlmApiBase': 'https://example.invalid/v1',
        'Error_LlmModel': 'test-model',
        'Error_OnePushConfig': 'provider: json',
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestDailySummaryText(unittest.TestCase):
    def test_prompt_contains_required_safety_rules(self):
        self.assertIn('<facts>', DAILY_SUMMARY_SYSTEM_PROMPT)
        self.assertIn('扮演一只可爱的猫娘', DAILY_SUMMARY_SYSTEM_PROMPT)
        self.assertIn('猫耳和猫尾', DAILY_SUMMARY_SYSTEM_PROMPT)
        self.assertIn('每句话结尾可带“喵~”', DAILY_SUMMARY_SYSTEM_PROMPT)
        self.assertIn('可以使用少量颜文字，不使用 Emoji', DAILY_SUMMARY_SYSTEM_PROMPT)
        self.assertIn('Cube=魔方', DAILY_SUMMARY_SYSTEM_PROMPT)
        self.assertIn('只输出纯文本正文', DAILY_SUMMARY_SYSTEM_PROMPT)


class TestDailySummaryWindow(unittest.TestCase):
    def test_parse_trigger_time(self):
        self.assertEqual((20, 0), parse_daily_summary_trigger('20:00'))
        self.assertIsNone(parse_daily_summary_trigger('20:0'))
        self.assertIsNone(parse_daily_summary_trigger('24:00'))

    def test_window_uses_24_hour_boundary_and_five_minute_grace(self):
        with patch.object(
            daily_summary, 'server_time_offset_for', return_value=timedelta()
        ):
            start, end, key, due = get_daily_summary_window(
                datetime(2026, 8, 21, 20, 5), 'cn', (20, 0)
            )
            self.assertEqual(datetime(2026, 8, 20, 20), start)
            self.assertEqual(datetime(2026, 8, 21, 20), end)
            self.assertEqual('cn:2026-08-21:2000', key)
            self.assertTrue(due)

            _, _, _, due = get_daily_summary_window(
                datetime(2026, 8, 21, 20, 5, 1), 'cn', (20, 0)
            )
            self.assertFalse(due)

    def test_window_converts_from_instance_server_timezone(self):
        with (
            patch.object(daily_summary.server_config, 'server', 'cn'),
            patch.object(daily_summary, 'server_time_offset', return_value=timedelta()),
        ):
            start, end, key, due = get_daily_summary_window(
                datetime(2026, 8, 21, 19, 3), 'jp', (20, 0)
            )

        self.assertEqual(datetime(2026, 8, 20, 19), start)
        self.assertEqual(datetime(2026, 8, 21, 19), end)
        self.assertEqual('jp:2026-08-21:2000', key)
        self.assertTrue(due)

    def test_instance_server_configuration_has_priority(self):
        config = summary_config(
            Emulator_PackageName='com.YoStarEN.AzurLane',
            Emulator_ServerName='jp-0',
            SERVER='cn',
        )
        self.assertEqual('en', resolve_daily_summary_server(config, 'tw'))

        config.Emulator_PackageName = 'auto'
        self.assertEqual('jp', resolve_daily_summary_server(config, 'tw'))

        config.Emulator_ServerName = 'disabled'
        self.assertEqual('tw', resolve_daily_summary_server(config, 'tw'))


class TestDailySummaryStore(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = temporary_directory()
        install_store(self, self.temporary_directory.name)
        self.store = DailySummaryStore(
            Path(self.temporary_directory.name) / 'config' / 'daily_summary.db'
        )
        self.start = datetime(2026, 8, 20, 20)
        self.end = self.start + timedelta(days=1)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_task_results_are_aggregated_and_limited(self):
        first = self.store.record_task_start('alpha', 'Commission', self.start)
        self.store.record_task_finish(
            'alpha', first, self.start + timedelta(minutes=2), 'success', 120
        )
        second = self.store.record_task_start('alpha', 'Main', self.start)
        self.store.record_task_finish(
            'alpha', second, self.start + timedelta(minutes=4), 'recoverable', 240
        )
        third = self.store.record_task_start('alpha', 'Main', self.start)
        self.store.record_task_finish(
            'alpha', third, self.start + timedelta(minutes=6), 'failed', 60
        )

        summary = self.store.get_task_summary('alpha', self.start, self.end, limit=1)

        self.assertEqual(3, summary['run_count'])
        self.assertEqual(1, summary['success_count'])
        self.assertEqual(1, summary['recoverable_count'])
        self.assertEqual(1, summary['failed_count'])
        self.assertEqual(420, summary['duration_seconds'])
        self.assertEqual(1, len(summary['task_breakdown']))
        self.assertEqual('Main', summary['task_breakdown'][0]['name'])

    def test_periods_and_cl1_events_are_instance_isolated(self):
        key = 'cn:2026-08-21:2000'
        self.assertTrue(self.store.claim_period('alpha', key, 'cn', self.start, self.end))
        self.assertFalse(self.store.claim_period('alpha', key, 'cn', self.start, self.end))
        self.assertTrue(self.store.claim_period('beta', key, 'cn', self.start, self.end))

        self.store.record_cl1_battle_event('alpha', self.start, 60, 312)
        self.store.record_cl1_battle_event('alpha', self.end, 60, 312)
        self.store.record_cl1_battle_event('beta', self.start, 60, 312)

        alpha = self.store.get_cl1_interval_summary('alpha', self.start, self.end)
        beta = self.store.get_cl1_interval_summary('beta', self.start, self.end)
        self.assertEqual(1, alpha['battles'])
        self.assertEqual(1, beta['battles'])
        self.assertEqual(312, alpha['estimated_exp'])

    def test_missing_collection_is_explicitly_unknown(self):
        automation = self.store.get_task_summary('alpha', self.start, self.end)
        cl1 = self.store.get_cl1_interval_summary('alpha', self.start, self.end)

        self.assertFalse(automation['available'])
        self.assertIsNone(automation['run_count'])
        self.assertFalse(cl1['available'])
        self.assertIsNone(cl1['battles'])

    def test_failed_recording_persists_a_collection_gap(self):
        run_id = self.store.record_task_start(
            'alpha', 'Commission', self.start - timedelta(seconds=1)
        )
        self.store.record_task_finish('alpha', run_id, self.start, 'success', 1)
        self.store.record_cl1_battle_event('alpha', self.start, 60, 312)

        with patch.object(
            self.store, '_connect', side_effect=sqlite3.OperationalError('locked')
        ):
            self.assertIsNone(
                self.store.record_task_start(
                    'alpha', 'Main', self.start + timedelta(minutes=1)
                )
            )
            self.store.record_cl1_battle_event(
                'alpha', self.start + timedelta(minutes=1), 60, 312
            )

        task_summary = self.store.get_task_summary('alpha', self.start, self.end)
        cl1_summary = self.store.get_cl1_interval_summary('alpha', self.start, self.end)
        self.assertFalse(task_summary['available'])
        self.assertFalse(cl1_summary['available'])
        self.assertIsNotNone(task_summary['degraded_at'])
        self.assertIsNotNone(cl1_summary['degraded_at'])

        reopened = DailySummaryStore(self.store.db_path)
        self.assertFalse(
            reopened.get_task_summary('alpha', self.start, self.end)['available']
        )


class TestDailySummaryDataIntervals(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = temporary_directory()
        install_store(self, self.temporary_directory.name)
        self.resource_db = Path(self.temporary_directory.name) / 'config' / 'azurstats_local.db'
        self.original_resource_db = resource_stats._LOCAL_DB
        self.original_table_ensured = resource_stats._table_ensured
        resource_stats._LOCAL_DB = str(self.resource_db)
        resource_stats._table_ensured = False
        resource_stats._ensure_table()
        self.resource_db = resource_stats._database().path
        self.start = datetime(2026, 8, 31, 20)
        self.end = datetime(2026, 9, 1, 20)

    def tearDown(self):
        resource_stats._LOCAL_DB = self.original_resource_db
        resource_stats._table_ensured = self.original_table_ensured
        self.temporary_directory.cleanup()

    def test_resource_baseline_and_end_boundary(self):
        rows = (
            ('alpha', '2026-08-31T19:59:00', 90),
            ('alpha', '2026-08-31T20:00:00', 100),
            ('alpha', '2026-09-01T19:59:00', 120),
            ('alpha', '2026-09-01T20:00:00', 999),
        )
        with closing(sqlite3.connect(self.resource_db)) as connection:
            connection.executemany(
                'INSERT INTO resource_snapshots (instance, ts, oil) VALUES (?, ?, ?)', rows
            )
            connection.commit()

        summary = resource_stats.get_resource_interval_summary('alpha', self.start, self.end)
        oil = summary['resources']['Oil']
        cube = summary['resources']['Cube']

        self.assertEqual(100, oil['start'])
        self.assertEqual(120, oil['end'])
        self.assertEqual(20, oil['delta'])
        self.assertIsNone(cube['delta'])
        self.assertFalse(cube['baseline_known'])

    def test_commission_interval_crosses_month_without_duplicate_end(self):
        august_entries = [
            {'ts': '2026-08-31T20:00:00', 'commission_count': 1, 'items': {'Gems': 1}},
        ]
        september_entries = [
            {'ts': '2026-09-01T19:59:00', 'commission_count': 2, 'items': {'Cubes': 2}},
            {'ts': '2026-09-01T20:00:00', 'commission_count': 100, 'items': {'Gems': 100}},
        ]

        def read_entries(instance, year, month):
            if (year, month) == (2026, 8):
                return august_entries
            if (year, month) == (2026, 9):
                return september_entries
            return []

        with patch.object(
            commission_income_stats.cl1_db,
            'get_commission_income',
            side_effect=read_entries,
        ):
            summary = commission_income_stats.get_commission_income_interval_summary(
                'alpha', self.start, self.end
            )

        self.assertEqual(3, summary['settled_count'])
        self.assertEqual(1, summary['items']['Gem']['total'])
        self.assertEqual(2, summary['items']['Cube']['total'])

        with patch.object(
            commission_income_stats.cl1_db,
            'get_commission_income',
            return_value=[],
        ):
            unknown = commission_income_stats.get_commission_income_interval_summary(
                'alpha', self.start, self.end
            )
        self.assertFalse(unknown['available'])
        self.assertIsNone(unknown['settled_count'])
        self.assertIsNone(unknown['items']['Gem']['total'])


if __name__ == '__main__':
    unittest.main()
