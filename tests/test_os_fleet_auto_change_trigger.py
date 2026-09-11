"""单舰毕业模式（任意舰船满经验触发自动配队）判定逻辑的单元测试。"""

import unittest

from module.config.config import TaskEnd
from module.os.ship_exp_data import LIST_SHIP_EXP
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling

TARGET_LEVEL = 120
FULL_EXP = LIST_SHIP_EXP[TARGET_LEVEL - 1]


def ship(position, total_exp, level=120):
    """构造一条舰位检测数据。"""
    return {
        "position": position,
        "level": level,
        "current_exp": 0,
        "total_exp": total_exp,
    }


class TriggerConfig:
    """提供满经验触发处理所需的配置接口。"""

    def __init__(self, auto_change_enable=True, any_ship_reached=True, delay_after_full=False):
        self.config_name = 'test'
        self.OpsiFleetAutoChange_Enable = auto_change_enable
        self.OpsiFleetAutoChange_AnyShipReached = any_ship_reached
        self.OpsiCheckLeveling_DelayAfterFull = delay_after_full
        self.task_stop_calls = 0

    def task_stop(self):
        self.task_stop_calls += 1
        raise TaskEnd


class ParseConfig:
    """提供自定义舰位解析所需的配置接口。"""

    def __init__(self, enable_custom_check=True, custom_check_positions='4,5'):
        self.OpsiCheckLeveling_EnableCustomCheck = enable_custom_check
        self.OpsiCheckLeveling_CustomCheckPositions = custom_check_positions


class FullExpHarness:
    """复现满经验触发处理所需的最小环境，避免实例化完整任务类。"""

    # 满经验统一处理委托到被测类的真实实现，仅桩掉自动配队执行与设备交互
    _handle_full_exp_triggered = OpsiHazard1Leveling._handle_full_exp_triggered

    def __init__(self, config):
        self.config = config
        self.notifications = []
        self.auto_change_calls = []
        self.delay_calls = []

    def notify_push(self, title, content):
        self.notifications.append((title, content))

    def _run_fleet_auto_change(self, replace_positions=None):
        self.auto_change_calls.append(replace_positions)
        return True

    def delay_opsi_active_task(self, server_update=True, task=None):
        self.delay_calls.append((server_update, task))


class CheckCustomPositionsFullExpTest(unittest.TestCase):
    """覆盖单舰毕业模式与全部毕业模式的判定分支。"""

    def _check(self, config, ships, custom_positions):
        harness = FullExpHarness(config)
        OpsiHazard1Leveling._check_custom_positions_full_exp(
            harness, ships, TARGET_LEVEL, custom_positions
        )
        return harness

    def test_any_ship_mode_triggers_with_only_full_positions(self):
        """单舰毕业模式：任意舰位满经验即触发，仅更换已满经验的舰位。"""
        harness = self._check(
            TriggerConfig(any_ship_reached=True),
            [ship(4, FULL_EXP), ship(5, 0)],
            [4, 5],
        )
        self.assertEqual(harness.auto_change_calls, [[4]])
        self.assertEqual(len(harness.notifications), 1)
        title, content = harness.notifications[0]
        self.assertEqual(title, "自定义舰位练级检查通过")
        self.assertIn("自定义舰位 4 已达到等级限制 120", content)
        self.assertEqual(harness.delay_calls, [])

    def test_any_ship_mode_blocked_when_position_missing(self):
        """单舰毕业模式：存在未检测到的自定义舰位时不判定为满经验。"""
        harness = self._check(
            TriggerConfig(any_ship_reached=True),
            [ship(4, FULL_EXP)],
            [4, 5],
        )
        self.assertEqual(harness.auto_change_calls, [])
        self.assertEqual(harness.notifications, [])

    def test_any_ship_mode_no_trigger_when_none_full(self):
        """单舰毕业模式：所有舰位均未满经验时不触发。"""
        harness = self._check(
            TriggerConfig(any_ship_reached=True),
            [ship(4, 0), ship(5, 0)],
            [4, 5],
        )
        self.assertEqual(harness.auto_change_calls, [])
        self.assertEqual(harness.notifications, [])

    def test_all_mode_requires_all_positions_full(self):
        """全部毕业模式：任一舰位未满经验则不触发。"""
        harness = self._check(
            TriggerConfig(any_ship_reached=False),
            [ship(4, FULL_EXP), ship(5, 0)],
            [4, 5],
        )
        self.assertEqual(harness.auto_change_calls, [])
        self.assertEqual(harness.notifications, [])

    def test_all_mode_triggers_without_replace_positions(self):
        """全部毕业模式：所有舰位满经验时触发，更换范围交由自动配队按配置解析。"""
        harness = self._check(
            TriggerConfig(any_ship_reached=False),
            [ship(4, FULL_EXP), ship(5, FULL_EXP)],
            [4, 5],
        )
        self.assertEqual(harness.auto_change_calls, [None])
        self.assertEqual(len(harness.notifications), 1)

    def test_auto_change_disabled_skips_execution(self):
        """自动配队未启用时仅推送通知，不执行更换。"""
        harness = self._check(
            TriggerConfig(auto_change_enable=False),
            [ship(4, FULL_EXP), ship(5, 0)],
            [4, 5],
        )
        self.assertEqual(harness.auto_change_calls, [])
        self.assertEqual(len(harness.notifications), 1)


class HandleFullExpTriggeredTest(unittest.TestCase):
    """覆盖满经验统一处理：通知 → 自动配队 → 可选延迟。"""

    def test_runs_auto_change_with_positions(self):
        """按传入舰位执行自动配队，未开启延迟时不停止任务。"""
        config = TriggerConfig()
        harness = FullExpHarness(config)
        OpsiHazard1Leveling._handle_full_exp_triggered(
            harness,
            notify_title="自定义舰位练级检查通过",
            notify_content="content",
            log_scope="自定义舰位",
            replace_positions=[4],
        )
        self.assertEqual(harness.notifications, [("自定义舰位练级检查通过", "content")])
        self.assertEqual(harness.auto_change_calls, [[4]])
        self.assertEqual(harness.delay_calls, [])
        self.assertEqual(config.task_stop_calls, 0)

    def test_delay_after_full_stops_task(self):
        """开启延迟后任务停止，且仅在延迟之后停止。"""
        config = TriggerConfig(delay_after_full=True)
        harness = FullExpHarness(config)
        with self.assertRaises(TaskEnd):
            OpsiHazard1Leveling._handle_full_exp_triggered(
                harness,
                notify_title="自定义舰位练级检查通过",
                notify_content="content",
                log_scope="自定义舰位",
            )
        self.assertEqual(harness.auto_change_calls, [None])
        self.assertEqual(harness.delay_calls, [(True, 'OpsiHazard1Leveling')])
        self.assertEqual(config.task_stop_calls, 1)


class ParseCustomCheckPositionsTest(unittest.TestCase):
    """覆盖自定义舰位配置解析。"""

    def _parse(self, config):
        return OpsiHazard1Leveling._parse_custom_check_positions(FullExpHarness(config))

    def test_parse_valid_positions(self):
        """正常解析带空格的舰位列表。"""
        self.assertEqual(self._parse(ParseConfig(True, '4, 5')), (True, [4, 5]))

    def test_disabled_returns_empty(self):
        """未启用自定义检测时返回空列表。"""
        self.assertEqual(self._parse(ParseConfig(False, '4,5')), (False, []))

    def test_out_of_range_positions_return_empty(self):
        """超出 1-6 范围的舰位视为无效配置。"""
        self.assertEqual(self._parse(ParseConfig(True, '0,9')), (True, []))

    def test_malformed_positions_return_empty(self):
        """无法解析为整数的舰位视为无效配置。"""
        self.assertEqual(self._parse(ParseConfig(True, '4,x')), (True, []))

    def test_empty_value_returns_empty(self):
        """空字符串配置返回空列表。"""
        self.assertEqual(self._parse(ParseConfig(True, '')), (True, []))

    def test_none_value_returns_empty(self):
        """空配置返回空列表。"""
        self.assertEqual(self._parse(ParseConfig(True, None)), (True, []))


if __name__ == '__main__':
    unittest.main()
