"""离线验证侵蚀一维修策略与代理任务初始化，不连接游戏设备。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.exception import GameStuckError
from module.os.operation_siren import OperationSiren


CL1 = 'OpsiHazard1Leveling'


def make_runner(task=CL1, *, sacrifice=False, use_pack=True, port_threshold=-1):
    runner = OperationSiren.__new__(OperationSiren)
    runner.config = SimpleNamespace(
        task=SimpleNamespace(command=task),
        data={},
        bound={},
        SERVER='cn',
        OpsiHazard1Leveling_SkipHpCheck=sacrifice,
        OpsiGeneral_UseRepairPack=use_pack,
        OpsiGeneral_RepairThreshold=port_threshold,
        OpsiGeneral_RepairPackThreshold=0.9,
        OpsiGeneral_RepairPackThresholdHazard1=0.5,
        override=Mock(),
        cross_get=Mock(side_effect=lambda keys, default=None: default),
        bind=Mock(),
    )
    runner._hp = {1: [0.98, 0.98, 0.98, 0, 0, 0]}
    runner._hp_has_ship = {1: [True] * 6}
    runner.fleet_current_index = 1
    runner.need_repair = [False, False, False, True, True, True]
    runner.hp_get = Mock()
    runner.hp_reset = Mock()
    runner.is_in_special_zone = Mock(return_value=False)
    runner.fleet_selector = Mock()
    runner.fleet_selector.get.return_value = 1
    runner.storage_fleet_selector = SimpleNamespace(SUBMARINE_FLEET=5)
    runner.parse_fleet_filter = Mock(return_value=[])
    runner.storage_get_next_item = Mock(return_value=True)
    # 仓库读取的扳手标记仍留在本轮缓存，复现日志中的维修箱后额外回港。
    runner.handle_storage_one_fleet_repair = Mock(return_value=True)
    runner.storage_repair_cancel = Mock()
    runner.storage_quit = Mock()
    runner.fleet_repair = Mock(return_value=True)
    runner._close_scheduling_action_point = Mock()
    return runner


class TestCl1FleetRepair(unittest.TestCase):
    def test_wrench_uses_boxes_without_forcing_a_port_visit_in_cl1(self):
        for port_threshold in (-1, 0.4):
            with self.subTest(port_threshold=port_threshold):
                runner = make_runner(port_threshold=port_threshold)
                self.assertTrue(runner.handle_fleet_repair(revert=False))
                runner.handle_storage_one_fleet_repair.assert_called_once_with(
                    fleet_index=1, threshold=0.5,
                )
                runner.fleet_repair.assert_not_called()
                runner.storage_repair_cancel.assert_called_once_with()
                runner.storage_quit.assert_called_once_with()

    def test_sacrifice_skips_health_read_boxes_and_port(self):
        for use_pack in (True, False):
            with self.subTest(use_pack=use_pack):
                runner = make_runner(sacrifice=True, use_pack=use_pack, port_threshold=0.4)
                self.assertFalse(runner.handle_fleet_repair())
                runner.hp_get.assert_not_called()
                runner.storage_get_next_item.assert_not_called()
                runner.fleet_repair.assert_not_called()

    def test_sacrifice_also_blocks_direct_repair_entry(self):
        for trigger_threshold in (None, 0.9):
            with self.subTest(trigger_threshold=trigger_threshold):
                runner = make_runner(sacrifice=True)
                self.assertFalse(runner.handle_fleet_repair_by_config(
                    fleet_index=1, trigger_threshold=trigger_threshold,
                ))
                runner.storage_get_next_item.assert_not_called()
                runner.fleet_repair.assert_not_called()

    def test_cl1_boxes_are_not_used_above_the_cl1_threshold(self):
        runner = make_runner()
        runner.hp = [0.7] * 6
        runner.need_repair = [False] * 6
        self.assertFalse(runner.handle_fleet_repair())
        runner.storage_get_next_item.assert_not_called()
        runner.fleet_repair.assert_not_called()

    def test_disabled_boxes_and_port_do_not_repair(self):
        runner = make_runner(use_pack=False)
        self.assertFalse(runner.handle_fleet_repair())
        runner.hp_get.assert_not_called()
        runner.fleet_repair.assert_not_called()

    def test_exhausted_boxes_do_not_force_cl1_back_to_port(self):
        runner = make_runner()
        runner.handle_storage_one_fleet_repair.side_effect = [True, False]
        self.assertTrue(runner.handle_storage_fleet_repair(fleet_index=[1, 2, 3]))
        self.assertEqual(runner.handle_storage_one_fleet_repair.call_count, 2)
        runner.storage_quit.assert_called_once_with()
        runner.fleet_repair.assert_not_called()

    def test_explicit_port_repair_remains_available_without_boxes(self):
        runner = make_runner(use_pack=False, port_threshold=0.4)
        self.assertTrue(runner.handle_fleet_repair(revert=False))
        runner.fleet_repair.assert_called_once_with(revert=False)

    def test_other_tasks_keep_wrench_port_repair_and_general_box_threshold(self):
        for task in ('OpsiMeowfficerFarming', 'OpsiStronghold', 'OpsiAbyssal'):
            with self.subTest(task=task):
                # 其他任务不能误用侵蚀一开关，即使配置对象留有该属性。
                runner = make_runner(task, sacrifice=True)
                self.assertTrue(runner.handle_fleet_repair(revert=False))
                runner.handle_storage_one_fleet_repair.assert_called_once_with(
                    fleet_index=1, threshold=0.9,
                )
                runner.fleet_repair.assert_called_once_with(revert=False)


class TestInitialRepairTaskContext(unittest.TestCase):
    def initialize(self, task='OpsiScheduling', *, overflow_target=None):
        runner = make_runner(task)
        runner.is_in_map = Mock(return_value=True)
        runner.zone = SimpleNamespace(zone_id=22)
        runner.zone_init = Mock()
        runner.handle_fleet_emp_debuff = Mock(return_value=False)
        runner.handle_current_fleet_resolve = Mock()
        runner.is_smart_scheduling_enabled = Mock(return_value=True)
        runner.run_first_auto_search = Mock()
        runner.config.cross_get.side_effect = lambda keys, default=None: (
            overflow_target if keys.endswith('OpsiPreventActionPointOverflow.Task') else default
        )
        runner.os_init()
        return runner

    def bind_child(self, runner, *, sacrifice=True):
        owner = runner.config.task

        def bind(task):
            command = task if isinstance(task, str) else task.command
            runner.config.OpsiHazard1Leveling_SkipHpCheck = command == CL1 and sacrifice

        runner.config.bind.side_effect = bind
        runner._make_opsi_task_function = lambda name: SimpleNamespace(command=name)
        return owner

    def test_scheduling_initialization_keeps_emp_and_resolve_without_early_repair(self):
        runner = self.initialize()
        runner.handle_fleet_emp_debuff.assert_called_once_with()
        runner.handle_current_fleet_resolve.assert_called_once_with(revert=False)
        runner.hp_get.assert_not_called()
        runner.storage_get_next_item.assert_not_called()
        runner.fleet_repair.assert_not_called()

    def test_first_cl1_child_uses_sacrifice_setting_and_preserves_open_ap_panel(self):
        runner = self.initialize()
        owner = self.bind_child(runner)
        child = Mock(return_value='completed')
        self.assertEqual(runner._run_with_opsi_task_context(CL1, child), 'completed')
        child.assert_called_once_with()
        runner.hp_get.assert_not_called()
        runner.storage_get_next_item.assert_not_called()
        runner.fleet_repair.assert_not_called()
        runner._close_scheduling_action_point.assert_not_called()
        self.assertIs(runner.config.task, owner)
        self.assertFalse(runner._initial_fleet_repair_pending)

    def test_first_cl1_child_without_sacrifice_uses_boxes_without_port(self):
        runner = self.initialize()
        self.bind_child(runner, sacrifice=False)
        runner._run_with_opsi_task_context(CL1, Mock())
        runner.handle_storage_one_fleet_repair.assert_called_once_with(
            fleet_index=1, threshold=0.5,
        )
        runner.fleet_repair.assert_not_called()

    def test_coin_child_keeps_repair_before_running_and_only_once(self):
        runner = self.initialize()
        self.bind_child(runner)
        actions = []
        runner.hp_get.side_effect = lambda: actions.append('health')
        child = Mock(side_effect=lambda: actions.append('task'))
        for _ in range(2):
            runner._run_with_opsi_task_context('OpsiMeowfficerFarming', child)
        self.assertEqual(actions, ['health', 'task', 'task'])
        runner.fleet_repair.assert_called_once_with(revert=False)

    def test_required_initial_search_keeps_repair_before_combat(self):
        runner = self.initialize()
        actions = []
        runner.hp_get.side_effect = lambda: actions.append('health')
        runner.run_first_auto_search.side_effect = lambda: actions.append('search')
        runner.handle_first_auto_search(run=True)
        self.assertEqual(actions, ['health', 'search'])
        runner.fleet_repair.assert_called_once_with(revert=False)
        self.assertFalse(runner._initial_fleet_repair_pending)

    def test_nested_overflow_scheduling_waits_for_actual_child(self):
        for target in ('OpsiScheduling', CL1):
            with self.subTest(target=target):
                runner = self.initialize('OpsiPreventActionPointOverflow', overflow_target=target)
                owner = self.bind_child(runner)
                child = Mock()
                if target == 'OpsiScheduling':
                    runner._run_with_opsi_task_context(
                        target, runner._run_with_opsi_task_context, CL1, child,
                    )
                else:
                    runner._run_with_opsi_task_context(target, child)
                child.assert_called_once_with()
                runner.storage_get_next_item.assert_not_called()
                runner.fleet_repair.assert_not_called()
                self.assertIs(runner.config.task, owner)

    def test_independent_cl1_initialization_also_honors_sacrifice(self):
        runner = make_runner(sacrifice=True)
        runner.is_in_map = Mock(return_value=True)
        runner.zone = SimpleNamespace(zone_id=22)
        runner.zone_init = Mock()
        runner.handle_fleet_emp_debuff = Mock(return_value=False)
        runner.handle_current_fleet_resolve = Mock()
        runner.run_first_auto_search = Mock()
        runner.os_init()
        runner.hp_get.assert_not_called()
        runner.fleet_repair.assert_not_called()

    def test_other_independent_tasks_keep_initial_repair(self):
        runner = self.initialize('OpsiMeowfficerFarming')
        runner.hp_get.assert_called_once_with()
        runner.fleet_repair.assert_called_once_with(revert=False)

    def test_initial_repair_errors_still_propagate_and_restore_owner(self):
        runner = self.initialize()
        owner = self.bind_child(runner, sacrifice=False)
        runner.hp_get.side_effect = GameStuckError('测试维修异常')
        child = Mock()
        with self.assertRaisesRegex(GameStuckError, '测试维修异常'):
            runner._run_with_opsi_task_context(CL1, child)
        child.assert_not_called()
        self.assertIs(runner.config.task, owner)


if __name__ == '__main__':
    unittest.main()
