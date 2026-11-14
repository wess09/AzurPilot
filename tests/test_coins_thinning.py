"""凭证与黄币快照的抽稀边界：近期逐条，更早每小时只留末条。"""
from datetime import datetime, timedelta
import tempfile
import unittest
from pathlib import Path

from module.persistence.database import close_all
from module.statistics.cl1_database import Cl1Database

from module.statistics.cl1_database import (
    COINS_EXACT_DAYS,
    YELLOW_COIN_EXACT_HOURS,
    thin_coins_snapshots,
    thin_yellow_coin_snapshots,
)


def _at(days_ago: int, hour: int, minute: int) -> dict:
    stamp = (datetime.now() - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {'ts': stamp.isoformat(), 'yellow_coins': f'{days_ago}d{hour:02d}:{minute:02d}'}


def test_thin_coins_snapshots_keeps_recent_and_thins_older():
    snapshots = [
        _at(0, 10, 5), _at(0, 10, 55),        # 3 天内：两条都留
        _at(COINS_EXACT_DAYS + 2, 9, 10),     # 超期同小时
        _at(COINS_EXACT_DAYS + 2, 9, 50),     # 超期同小时的末条，应取代上一条
        _at(COINS_EXACT_DAYS + 2, 11, 30),    # 另一个小时，独立保留
    ]

    kept = [item['yellow_coins'] for item in thin_coins_snapshots(snapshots)]

    assert '0d10:05' in kept and '0d10:55' in kept
    assert '5d09:50' in kept and '5d09:10' not in kept
    assert '5d11:30' in kept
    assert len(kept) == 4


def test_thin_coins_snapshots_stays_bounded_for_repeated_hours():
    snapshots = [_at(30, 9, minute) for minute in (5, 15, 25, 35, 45, 55)]

    kept = thin_coins_snapshots(snapshots)

    assert len(kept) == 1
    assert kept[0]['yellow_coins'] == '30d09:55'


def test_thin_yellow_coin_snapshots_keeps_recent_hours():
    now = datetime.now()
    recent = [{'ts': (now - timedelta(minutes=minute)).isoformat(), 'yellow_coin': minute} for minute in (1, 2, 3)]
    older = [
        {'ts': (now - timedelta(hours=YELLOW_COIN_EXACT_HOURS + 1)).replace(minute=5).isoformat(), 'yellow_coin': 5},
        {'ts': (now - timedelta(hours=YELLOW_COIN_EXACT_HOURS + 1)).replace(minute=55).isoformat(), 'yellow_coin': 55},
        {'ts': (now - timedelta(hours=YELLOW_COIN_EXACT_HOURS + 2)).replace(minute=30).isoformat(), 'yellow_coin': 30},
    ]

    kept = thin_yellow_coin_snapshots(recent + older)

    assert [item['yellow_coin'] for item in kept] == [30, 55, 3, 2, 1]


class IncrementalYellowCoinThinningTests(unittest.TestCase):
    def test_incremental_append_thinning_matches_document_path(self):
        """增量追加的 SQL 抽稀结果必须与文档路径的 thin_snapshots 一致。"""
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        db = Cl1Database(Path(directory.name) / 'config' / 'azurpilot.db')
        self.addCleanup(close_all)
        now = datetime.now()
        month = now.strftime('%Y-%m')
        # 乱序插入跨三个历史小时，覆盖「按时间排序取每小时末条」的等价性。
        seeded = [
            {'ts': (now - timedelta(hours=hours, minutes=minute)).isoformat(),
             'yellow_coin': hours * 100 + minute, 'source': 't'}
            for hours in (9, 8, 7) for minute in (40, 10, 25)
        ]
        db.save_stats('t', month, {'yellow_coin_snapshots': seeded})
        db.add_yellow_coin_snapshot('t', 99, source='t', observed_at=now)
        db.add_yellow_coin_snapshot('t', 99, source='t', observed_at=now)
        expected = thin_yellow_coin_snapshots(
            seeded + [{'ts': now.isoformat(), 'yellow_coin': 99, 'source': 't'}])
        # 存活集合必须一致；增量路径保持插入序，不承担文档路径写后的 ts 重排。
        actual = db.get_stats('t', month)['yellow_coin_snapshots']
        by_ts = lambda item: item['ts']
        self.assertEqual(sorted(actual, key=by_ts), sorted(expected, key=by_ts))

    def test_incremental_meow_samples_keep_newest_100(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        db = Cl1Database(Path(directory.name) / 'config' / 'azurpilot.db')
        self.addCleanup(close_all)
        for index in range(105):
            db.add_meow_round_time('t', float(index), 3)
        month = datetime.now().strftime('%Y-%m')
        samples = db.get_stats('t', month)
        self.assertEqual([item['duration'] for item in samples['meow_round_times']],
                         [float(index) for index in range(5, 105)])
        self.assertEqual(samples['meow_hazard_stats']['3']['round_times'],
                         [float(index) for index in range(5, 105)])


class IncrementalCoinsThinningTests(unittest.TestCase):
    def test_incremental_append_thinning_matches_document_path(self):
        """凭证快照的 SQL 抽稀结果必须与文档路径的 thin_coins_snapshots 一致。"""
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        db = Cl1Database(Path(directory.name) / 'config' / 'azurpilot.db')
        self.addCleanup(close_all)
        now = datetime.now()
        month = now.strftime('%Y-%m')
        # 乱序插入跨三个历史小时，覆盖「按时间排序取每小时末条」的等价性。
        seeded = [
            {'ts': (now - timedelta(hours=hours, minutes=minute)).isoformat(),
             'yellow_coins': hours * 100 + minute, 'purple_coins': hours, 'source': 't'}
            for hours in (100, 90, 80) for minute in (40, 10, 25)
        ]
        db.save_stats('t', month, {'coins_snapshots': seeded})
        db.add_coins_snapshot('t', 99, 1, source='t', observed_at=now)
        db.add_coins_snapshot('t', 99, 1, source='t', observed_at=now)
        expected = thin_coins_snapshots(
            seeded + [{'ts': now.isoformat(), 'yellow_coins': 99, 'purple_coins': 1, 'source': 't'}])
        # 存活集合必须一致；增量路径保持插入序，不承担文档路径写后的 ts 重排。
        actual = db.get_stats('t', month)['coins_snapshots']
        by_ts = lambda item: item['ts']
        self.assertEqual(sorted(actual, key=by_ts), sorted(expected, key=by_ts))


