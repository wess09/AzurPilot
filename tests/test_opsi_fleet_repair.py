"""离线验证侵蚀一维修策略与代理任务初始化，不连接游戏设备。"""

import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config import TaskEnd
from module.exception import GameStuckError
from module.os.operation_siren import OperationSiren
from module.os_handler.assets import (
    AUTO_SEARCH_OS_MAP_OPTION_OFF,
    AUTO_SEARCH_OS_MAP_OPTION_ON,
    AUTO_SEARCH_REWARD,
)
from tests.test_opsi_cl1_speed import VirtualClock


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


class TestCl1RepairTiming(unittest.TestCase):
    """复现战后出现扳手、游戏仍有后续战斗时被脚本提前关闭自律。"""

    def setUp(self):
        self.clock = VirtualClock()
        self.enterContext(patch('module.base.timer.time', self.clock))
        self.enterContext(patch('module.base.debug_clip.cleanup_clips_if_due'))
        self.enterContext(patch('module.base.debug_clip.clip_recording', side_effect=lambda *args: nullcontext()))

    def make_search(self, task=CL1, *, wrench=True, sacrifice=False, result=None):
        runner = make_runner(task, sacrifice=sacrifice)
        runner.config.OpsiGeneral_RepairPackThresholdHazard1 = 0.3
        runner.config.OpsiGeneral_AutoSearchTimeLimit = 5
        runner.config.OpsiHazard1Leveling_DebugClip = False
        runner.config.DropRecord_OpsiHazard1Leveling = 'do_not'
        runner.config.stop_event = None
        runner.config.task_switched = Mock(return_value=False)
        runner.config.is_task_enabled = Mock(return_value=False)
        runner.config.temporary = Mock(return_value=SimpleNamespace(recover=Mock()))
        runner.hp = [0.98, 0.98, 0.98, 0.31, 0.57, 0 if wrench else 0.28]
        runner.need_repair = [False] * 5 + [wrench]
        runner.device = Mock(image=None)
        runner.interval_timer = {}
        runner.screen = 'map'
        runner.search_on = True
        actions = []

        def frames():
            for screen in ('battle', 'map', 'battle', 'map', 'reward'):
                self.clock.now += 1
                runner.screen = screen if runner.search_on else 'map'
                yield

        def matches(button, **kwargs):
            if runner.screen == 'map':
                return button is (AUTO_SEARCH_OS_MAP_OPTION_ON if runner.search_on else AUTO_SEARCH_OS_MAP_OPTION_OFF)
            return runner.screen == 'reward' and button is AUTO_SEARCH_REWARD

        def click(button):
            if button is AUTO_SEARCH_OS_MAP_OPTION_ON:
                runner.search_on = False
                actions.append('stop')

        def combat(**kwargs):
            runner._auto_search_battle_count += 1
            actions.append('battle')
            runner.screen = 'map'
            return result

        def reward(**kwargs):
            actions.append('reward')
            runner.screen = 'map'
            return True

        runner.loop = frames
        runner.appear = Mock(side_effect=matches)
        runner.match_template_color = Mock(side_effect=matches)
        runner.device.click.side_effect = click
        runner.is_in_map = Mock(side_effect=lambda: runner.screen == 'map')
        runner.info_bar_count = Mock(return_value=0)
        runner.combat_appear = Mock(side_effect=lambda: runner.screen == 'battle')
        runner.on_auto_search_battle_count_add = Mock()
        runner.auto_search_combat = Mock(side_effect=combat)
        runner.os_auto_search_quit = Mock(side_effect=reward)
        runner.handle_background_coin_interrupt = Mock(return_value=False)
        runner.handle_retirement = Mock(return_value=False)
        runner.handle_map_event = Mock(return_value=False)
        runner.handle_ash_beacon_attack = Mock(return_value=False)
        runner.strategic_search_start = Mock()
        drop = Mock(count=1)
        runner.stat = SimpleNamespace(new=lambda **kwargs: nullcontext(drop))
        runner.handle_fleet_emp_debuff = Mock(return_value=False)
        runner.map_rescan = Mock(side_effect=lambda: actions.append('events'))
        runner._forced_move_enabled = Mock(return_value=True)
        runner._execute_fixed_patrol_scan = Mock(side_effect=lambda **kwargs: actions.append('patrol'))
        runner.handle_storage_one_fleet_repair.side_effect = lambda **kwargs: actions.append('repair') or True
        return runner, actions

    def test_cl1_finishes_search_and_events_before_repairing_low_hp_or_wrench(self):
        for wrench in (False, True):
            for result in (None, False):
                with self.subTest(wrench=wrench, result=result):
                    runner, actions = self.make_search(wrench=wrench, result=result)
                    runner._cl1_run_battle()
                    self.assertEqual(actions, ['battle', 'battle', 'reward', 'events', 'patrol', 'repair'])
                    runner.device.click.assert_not_called()
                    runner.handle_storage_one_fleet_repair.assert_called_once_with(fleet_index=1, threshold=0.3)
                    runner.fleet_repair.assert_not_called()

    def test_sacrifice_still_finishes_search_and_events_without_repair(self):
        runner, actions = self.make_search(sacrifice=True)
        runner._cl1_run_battle()
        self.assertEqual(actions, ['battle', 'battle', 'reward', 'events', 'patrol'])
        runner.handle_storage_one_fleet_repair.assert_not_called()
        runner.fleet_repair.assert_not_called()

    def test_other_tasks_keep_stopping_auto_search_on_wrench(self):
        for task in ('OpsiExplore', 'OpsiMeowfficerFarming', 'OpsiStronghold'):
            with self.subTest(task=task):
                runner, actions = self.make_search(task)
                runner.os_auto_search_daemon()
                self.assertEqual(actions, ['battle', 'stop'])
                runner.device.click.assert_called_once_with(AUTO_SEARCH_OS_MAP_OPTION_ON)
                runner.handle_storage_one_fleet_repair.assert_not_called()

    def test_cl1_still_honors_explicit_stop_and_task_switch(self):
        for stop_requested in (False, True):
            with self.subTest(stop_requested=stop_requested):
                runner, _ = self.make_search()
                runner.config.stop_event = SimpleNamespace(is_set=lambda: stop_requested)
                runner.config.task_switched.return_value = not stop_requested
                runner.interrupt_auto_search = Mock(side_effect=TaskEnd)
                with self.assertRaises(TaskEnd):
                    runner.os_auto_search_daemon(strategic=True)
                runner.interrupt_auto_search.assert_called_once_with(drop=None)
                runner.auto_search_combat.assert_not_called()


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
