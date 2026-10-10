"""资源时间线的窗口过滤：下推到 SQL 后窗口内的点一个不少。"""
import calendar
import shutil
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tests.opsi_test_support import install_store
from pathlib import Path

from module.statistics import resource_stats


def test_timeline_since_keeps_every_row_in_window():
    # 清理失败即忽略：库文件可能仍被连接占用。
    directory = tempfile.mkdtemp(prefix='azurpilot-resource-')
    case = unittest.TestCase()
    install_store(case, directory)
    database = Path(directory) / 'config' / 'azurstats_local.db'
    original_db, original_ensured = resource_stats._LOCAL_DB, resource_stats._table_ensured
    resource_stats._LOCAL_DB, resource_stats._table_ensured = str(database), False
    try:
        resource_stats._ensure_table()
        with sqlite3.connect(database) as conn:
            conn.executemany(
                "INSERT INTO resource_snapshots (instance, ts, oil) VALUES ('default', ?, ?)",
                [(f'2026-01-01T{hour:02d}:{minute:02d}:00', hour * 100 + minute)
                 for hour in range(24) for minute in (0, 30)],
            )

        whole = resource_stats.get_resource_timeline('default')
        window = resource_stats.get_resource_timeline('default', since='2026-01-01T20:00:00')

        assert len(whole) == 48
        assert [row['oil'] for row in window] == [2000, 2030, 2100, 2130, 2200, 2230, 2300, 2330]
    finally:
        resource_stats._LOCAL_DB, resource_stats._table_ensured = original_db, original_ensured
        case.doCleanups()
        shutil.rmtree(directory, ignore_errors=True)


def test_timeline_until_drops_every_row_after_window():
    """窗口上界同样下推到 SQL：看向历史月份时不得混入其后的点。"""
    directory = tempfile.mkdtemp(prefix='azurpilot-resource-')
    case = unittest.TestCase()
    install_store(case, directory)
    database = Path(directory) / 'config' / 'azurstats_local.db'
    original_db, original_ensured = resource_stats._LOCAL_DB, resource_stats._table_ensured
    resource_stats._LOCAL_DB, resource_stats._table_ensured = str(database), False
    try:
        resource_stats._ensure_table()
        with sqlite3.connect(database) as conn:
            conn.executemany(
                "INSERT INTO resource_snapshots (instance, ts, oil) VALUES ('default', ?, ?)",
                [(f'2026-01-{day:02d}T00:00:00', day) for day in range(1, 11)]
                + [(f'2026-02-{day:02d}T00:00:00', 100 + day) for day in range(1, 4)],
            )

        window = resource_stats.get_resource_timeline(
            'default', since='2026-01-05T00:00:00', until='2026-01-08T00:00:00')

        assert [row['oil'] for row in window] == [5, 6, 7, 8]
    finally:
        resource_stats._LOCAL_DB, resource_stats._table_ensured = original_db, original_ensured
        case.doCleanups()
        shutil.rmtree(directory, ignore_errors=True)


def test_report_month_window_excludes_snapshots_after_the_month():
    """资源趋势按选定月份取窗口：月内全要，月外一条都不带。"""
    directory = tempfile.mkdtemp(prefix='azurpilot-resource-')
    case = unittest.TestCase()
    install_store(case, directory)
    database = Path(directory) / 'config' / 'azurstats_local.db'
    original_db, original_ensured = resource_stats._LOCAL_DB, resource_stats._table_ensured
    resource_stats._LOCAL_DB, resource_stats._table_ensured = str(database), False
    try:
        resource_stats._ensure_table()
        with sqlite3.connect(database) as conn:
            conn.executemany(
                "INSERT INTO resource_snapshots (instance, ts, oil) VALUES ('default', ?, ?)",
                [(f'2026-01-{day:02d}T00:00:00', day) for day in range(1, 11)]
                + [(f'2026-02-{day:02d}T00:00:00', 100 + day) for day in range(1, 4)],
            )

        from module.api.statistics_service import report
        configs = SimpleNamespace(path=lambda instance: database.parent / f'{instance}.json')
        result = report(configs, 'default', 'resources', '2026-01', 7, 'month')
        oil = next(item for item in result['series'] if item['key'] == 'oil')

        assert [point['v'] for point in oil['points']] == [float(day) for day in range(1, 11)]
    finally:
        resource_stats._LOCAL_DB, resource_stats._table_ensured = original_db, original_ensured
        case.doCleanups()
        shutil.rmtree(directory, ignore_errors=True)


def test_report_skips_series_for_hidden_charts():
    """图表与原始记录都隐藏时，后端不再查询也不再构造序列数据。"""
    directory = tempfile.mkdtemp(prefix='azurpilot-resource-')
    case = unittest.TestCase()
    install_store(case, directory)
    database = Path(directory) / 'config' / 'azurstats_local.db'
    original_db, original_ensured = resource_stats._LOCAL_DB, resource_stats._table_ensured
    resource_stats._LOCAL_DB, resource_stats._table_ensured = str(database), False
    try:
        resource_stats._ensure_table()
        with sqlite3.connect(database) as conn:
            conn.executemany(
                "INSERT INTO resource_snapshots (instance, ts, oil) VALUES ('default', ?, ?)",
                [(f'2026-01-{day:02d}T00:00:00', day) for day in range(1, 6)],
            )

        from module.api.statistics_service import report
        configs = SimpleNamespace(path=lambda instance: database.parent / f'{instance}.json')

        full = report(configs, 'default', 'resources', '2026-01', 7, 'month')
        with patch.object(resource_stats, 'get_resource_timeline', return_value=[]) as spy:
            lean = report(configs, 'default', 'resources', '2026-01', 7, 'month', include_series=False)

        assert full['series']
        assert lean['series'] == []
        assert lean['metrics'] == full['metrics']
        assert spy.call_count == 0
    finally:
        resource_stats._LOCAL_DB, resource_stats._table_ensured = original_db, original_ensured
        case.doCleanups()
        shutil.rmtree(directory, ignore_errors=True)


def test_wallclock_micros_keeps_utc_field_semantics():
    """墙上时钟按 UTC 字段直译成微秒：闰日、微秒与跨世纪边界都与 stdlib 一致。"""
    from datetime import datetime
    from module.api.statistics_service import wallclock_micros

    moments = [
        datetime(1970, 1, 1),
        datetime(1970, 1, 1, 0, 0, 0, 1),
        datetime(2000, 2, 29, 23, 59, 59, 999999),
        datetime(2026, 10, 9, 12, 38, 15, 234939),
        datetime(2100, 3, 1, 6, 0, 0),
    ]
    for moment in moments:
        expected = calendar.timegm(moment.timetuple()) * 1000000 + moment.microsecond
        assert wallclock_micros(moment) == expected, moment
