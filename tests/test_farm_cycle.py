"""周期出击限制的单元测试。"""

import contextlib
import unittest
from datetime import datetime, timedelta

from module.campaign.farm_cycle import FarmCycleLimit


class FakeConfig:
    """只实现周期限制需要的最小配置接口。"""

    def __init__(self, hours=0, runs=0, start=None, remain=0,
                 applied_hours=0, applied_runs=0):
        self.FarmCycle_CycleHours = hours
        self.FarmCycle_CycleRuns = runs
        self.FarmCycle_CycleStart = start or datetime(2020, 1, 1)
        self.FarmCycle_CycleRemain = remain
        self.FarmCycle_CycleHoursApplied = applied_hours
        self.FarmCycle_CycleRunsApplied = applied_runs
        self.delayed = None

    def multi_set(self):
        return contextlib.nullcontext()

    def task_delay(self, target=None, **kwargs):
        self.delayed = target


class FarmCycleLimitTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, 10, 0, 0)

    def make(self, **kwargs):
        return FakeConfig(**kwargs)

    def test_initial_cycle_starts_and_consumes(self):
        config = self.make(hours=2, runs=3)
        limit = FarmCycleLimit(config, now_func=lambda: self.now)

        self.assertTrue(limit.refresh())
        self.assertEqual(limit.remaining, 3)
        self.assertEqual(limit.start, self.now)
        self.assertEqual(limit.cycle_end, self.now + timedelta(hours=2))
        self.assertFalse(limit.is_blocked)

        limit.consume()
        self.assertEqual(config.FarmCycle_CycleRemain, 2)
        self.assertEqual(limit.remaining, 2)

    def test_blocked_defer_uses_cycle_end(self):
        start = self.now - timedelta(minutes=30)
        config = self.make(
            hours=2, runs=3, start=start, remain=0,
            applied_hours=2, applied_runs=3,
        )
        limit = FarmCycleLimit(config, now_func=lambda: self.now)

        self.assertTrue(limit.refresh())
        self.assertTrue(limit.is_blocked)
        limit.defer()
        self.assertEqual(config.delayed, start + timedelta(hours=2))

    def test_expired_cycle_restarts_at_now(self):
        start = self.now - timedelta(hours=2, minutes=1)
        config = self.make(
            hours=2, runs=3, start=start, remain=2,
            applied_hours=2, applied_runs=3,
        )
        limit = FarmCycleLimit(config, now_func=lambda: self.now)

        self.assertTrue(limit.refresh())
        self.assertEqual(limit.start, self.now)
        self.assertEqual(limit.remaining, 3)
        self.assertFalse(limit.is_blocked)

    def test_config_change_restarts_cycle(self):
        start = self.now - timedelta(minutes=20)
        config = self.make(
            hours=2, runs=4, start=start, remain=2,
            applied_hours=2, applied_runs=3,
        )
        limit = FarmCycleLimit(config, now_func=lambda: self.now)

        self.assertTrue(limit.refresh())
        self.assertEqual(limit.start, self.now)
        self.assertEqual(limit.remaining, 4)
        self.assertEqual(config.FarmCycle_CycleRunsApplied, 4)

    def test_disable_clears_state(self):
        start = self.now - timedelta(minutes=20)
        config = self.make(
            hours=0, runs=3, start=start, remain=2,
            applied_hours=2, applied_runs=3,
        )
        limit = FarmCycleLimit(config, now_func=lambda: self.now)

        self.assertFalse(limit.refresh())
        self.assertEqual(config.FarmCycle_CycleStart, datetime(2020, 1, 1))
        self.assertEqual(config.FarmCycle_CycleRemain, 0)
        self.assertEqual(config.FarmCycle_CycleHoursApplied, 0)
        self.assertEqual(config.FarmCycle_CycleRunsApplied, 0)

    def test_consume_does_not_go_below_zero(self):
        start = self.now - timedelta(minutes=10)
        config = self.make(
            hours=2, runs=1, start=start, remain=0,
            applied_hours=2, applied_runs=1,
        )
        limit = FarmCycleLimit(config, now_func=lambda: self.now)
        self.assertTrue(limit.refresh())
        limit.consume()
        self.assertEqual(limit.remaining, 0)
        self.assertTrue(limit.is_blocked)


if __name__ == '__main__':
    unittest.main()
