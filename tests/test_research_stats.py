"""科研掉落汇总：期数视图 / 心智物资视图 / 今日本月计数。

用假记录喂进汇总层，不碰 SQLite 与用户数据；名称表用仓库里的真表，
这样「金装备不再统计」这条口径是拿真数据验证的。
"""

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


def module_stub(name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def load_research_stats():
    """仅导入待测实现，日志模块用替身，避免初始化用户配置与日志目录。"""
    path = Path(__file__).resolve().parents[1] / 'module/statistics/research_stats.py'
    spec = importlib.util.spec_from_file_location('_research_stats_test', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'module.logger': module_stub('module.logger', logger=Mock())}):
        spec.loader.exec_module(module)
    return module


RESEARCH_STATS = load_research_stats()

# 取自真实名称表的几类代表：彩装备、金装备、金船图纸、当期彩装、心智单元、物资
RAINBOW_GEAR = 'Prototype_Quadruple_305mm_SKC39_Main_Gun_Mount_T0'   # r=5 彩装（八期）
RAINBOW_GEAR_NINTH = 'Prototype_Carrier_Based_Ta_152_C_1_R14_T0'     # r=5 彩装（九期）
GOLD_GEAR = 'Prototype_Quadruple_610mm_Cruiser_Torpedo_Mount_T0'     # r=4 金装（已不统计）
GOLD_BLUEPRINT = 'BlueprintTakahashi'                                # r=4 金船图（九期）
CHIPS = 'CognitiveChips'                                             # 心智单元
COINS = 'Coins'                                                      # 物资


def entry(items, series, when):
    return {
        'ts': when.isoformat(),
        'completed_at': when.isoformat(),
        'project': 'G-531-MI',
        'series': series,
        'items': items,
    }


class ResearchStatsScopeTest(unittest.TestCase):
    """展示口径：期数视图按期看彩装/图纸；金装备不统计；心智物资不分期。"""

    def setUp(self):
        self.now = datetime.now()
        entries = [
            # 九期：该期金船图 + 金装 + 心智 + 物资，另外混进一件八期的彩装
            # （金装备各期混着出、科研项目也会「额外赠送」别期的图纸，用户确认过这两个机制）
            entry({GOLD_BLUEPRINT: 1, GOLD_GEAR: 3, RAINBOW_GEAR: 2, CHIPS: 40, COINS: 120}, 9, self.now),
            # 七期：金装与心智物资——这几类各期混着出，所以也能出现在别期的记录里
            entry({GOLD_GEAR: 5, CHIPS: 30, COINS: 80}, 7, self.now - timedelta(days=2)),
        ]
        self.patcher = patch.object(RESEARCH_STATS, '_iter_entries', lambda *a, **k: iter(entries))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def collect(self, **kwargs):
        return RESEARCH_STATS.collect('alas', days=90, **kwargs)

    def names(self, **kwargs):
        return [item['name'] for item in self.collect(**kwargs)['items']]

    def test_series_view_shows_blueprint_of_that_series(self):
        summary = self.collect(series=9)
        self.assertEqual(summary['scope'], 'series')
        names = self.names(series=9)
        self.assertIn(GOLD_BLUEPRINT, names)
        # 该期的彩装也在清单里（本期没掉过就是 0），与委托收益的资源格子一致
        self.assertIn(RAINBOW_GEAR_NINTH, names)
        amounts = {item['name']: item['amount'] for item in summary['items']}
        self.assertEqual(amounts[GOLD_BLUEPRINT], 1)
        self.assertEqual(amounts[RAINBOW_GEAR_NINTH], 0)

    def test_series_view_hides_gear_and_consumables(self):
        names = self.names(series=9)
        self.assertNotIn(GOLD_GEAR, names)
        # 心智与物资有自己的视图，不再出现在每期视图里
        self.assertNotIn(CHIPS, names)
        self.assertNotIn(COINS, names)

    def test_cross_series_gift_appears_as_extra_row(self):
        """项目额外赠送的别期图纸：不进该期固定清单，但掉了就照实列出来。"""
        summary = self.collect(series=9)
        self.assertNotIn(RAINBOW_GEAR, summary['series_items'])
        amounts = {item['name']: item['amount'] for item in summary['items']}
        self.assertEqual(amounts[RAINBOW_GEAR], 2)

    def test_series_items_are_all_from_that_series(self):
        for keyword in self.collect(series=9)['series_items']:
            with self.subTest(item=keyword):
                self.assertEqual(RESEARCH_STATS.item_info(keyword).get('series'), 9)

    def test_gold_gear_is_no_longer_counted(self):
        """金装备已下线：任何视图都不再展示它（用户 2026-09-24 撤掉金装视图）。"""
        for scope in ('series', 'consumable'):
            with self.subTest(scope=scope):
                self.assertNotIn(GOLD_GEAR, self.names(scope=scope, series=9))

    def test_consumable_view_merges_all_series(self):
        summary = self.collect(scope='consumable')
        self.assertEqual(summary['scope'], 'consumable')
        self.assertEqual(summary['series'], 0)
        # 心智单元（r=4）排在物资（r=1）前面
        self.assertEqual(self.names(scope='consumable'), [CHIPS, COINS])
        self.assertEqual([item['amount'] for item in summary['items']], [70, 200])

    def test_consumable_view_excludes_gear(self):
        names = self.names(scope='consumable')
        self.assertNotIn(RAINBOW_GEAR, names)
        self.assertNotIn(GOLD_GEAR, names)
        self.assertNotIn(GOLD_BLUEPRINT, names)

    def test_series_view_keeps_only_selected_series(self):
        summary = self.collect(series=7)
        # 七期那条只有金装与心智物资，都不是期数视图的口径，所以金额全为 0
        self.assertEqual([item['amount'] for item in summary['items']], [0] * len(summary['items']))
        self.assertTrue(summary['series_items'])
        self.assertEqual(summary['records'], 1)
        self.assertEqual(summary['available'], [9, 7])

    def test_average_per_record(self):
        summary = self.collect(scope='consumable')
        # 心智单元：九期 40 + 七期 30 = 70，跨 2 次掉落
        chips = next(item for item in summary['items'] if item['name'] == CHIPS)
        self.assertEqual(chips['avg'], 35.0)

    def test_series_default_picks_latest_available(self):
        self.assertEqual(self.collect(series=0)['series'], 9)


class ResearchStatsTodayMonthTest(unittest.TestCase):
    """今日 / 本月计数：按记录时间戳分桶，时间戳缺失时不计入任何一桶。"""

    def setUp(self):
        now = datetime.now()
        first_this_month = now.replace(day=1, hour=0, minute=0)
        old = now - timedelta(days=200)
        self.now = now
        entries = [
            entry({CHIPS: 2}, 9, now),
            entry({CHIPS: 3}, 9, first_this_month),
            entry({CHIPS: 5}, 9, old),
            {'project': 'G-531-MI', 'series': 9, 'items': {CHIPS: 7}},  # 没有时间戳
        ]
        self.patcher = patch.object(RESEARCH_STATS, '_iter_entries', lambda *a, **k: iter(entries))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_today_and_month_buckets(self):
        summary = RESEARCH_STATS.collect('alas', days=365, series=9, scope='consumable')
        item = summary['items'][0]
        # 今天 2 张 + 本月 1 号 3 张 + 200 天前 5 张；没有时间戳的那条不进窗口
        self.assertEqual(item['amount'], 10)
        self.assertEqual(item['today'], 2)
        # 「本月」= 今天那条 + 本月 1 号那条；即使今天就是 1 号，两条也在同一个月里
        self.assertEqual(item['month'], 5)
        self.assertEqual(summary['today'], 2)
        self.assertEqual(summary['month'], 5)

    def test_missing_timestamp_is_excluded(self):
        """时间戳缺失的记录不进统计窗口，也不算进今天。"""
        summary = RESEARCH_STATS.collect('alas', days=365, series=9, scope='consumable')
        self.assertLess(summary['today'], 7)
        self.assertEqual(summary['records'], 3)


if __name__ == '__main__':
    unittest.main()
