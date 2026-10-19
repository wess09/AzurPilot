"""独立普通海域补扫、日志中的全球地图卡死及断点恢复回归。"""
import json
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.config.config import AzurLaneConfig, TaskEnd
from module.config.redirect_utils.utils import opsi_explore_cleanup_state_redirect
from module.exception import GameStuckError, MapDetectionError, RequestHumanTakeover
from module.os.globe_operation import GlobeOperation
from module.os.map import OSMap
from module.os.map_base import OSCampaignMap
from module.os.tasks.explore import OpsiExplore
from module.os.tasks.explore_cleanup import OpsiExploreCleanup
from module.campaign.os_run import OSCampaignRun

RESET = datetime(2026, 11, 1)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('module.os.tasks.explore_cleanup.get_os_next_reset', return_value=RESET)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def state(self):
        return dict(reset=RESET.isoformat(), phase='cleanup', order=[44, 24, 22], next=0, attempts=0)

    def runner(self, state=None, progress='已完成百分之100.00', month=None):
        runner = OpsiExploreCleanup.__new__(OpsiExploreCleanup)
        values = {'OpsiExplore.OpsiExplore.ExploreProgress': progress,
                  'OpsiExplore.OpsiExplore.MeowfficerCleanupState': month}
        runner.config = SimpleNamespace(
            OpsiExploreCleanup_State=state, OpsiExploreCleanup_Progress='',
            OpsiFleet_Fleet=1, OS_EXPLORE_FILTER='44 > 24 > 22',
            cross_get=lambda keys, default=None: values.get(keys, default),
            multi_set=nullcontext, check_task_switch=Mock(),
            task_delay=Mock(), task_call=Mock(), task_stop=Mock(side_effect=TaskEnd),
        )
        runner.calls = []
        def enter(zone, **kwargs):
            self.assertEqual(kwargs, {'types': 'DANGEROUS', 'force_enter': True})
            runner.calls.append(('enter', zone))
            runner.zone = SimpleNamespace(zone_id=zone)
        runner.globe_goto = enter
        runner.fleet_set = Mock()
        runner.fleet_selector = SimpleNamespace(get=lambda: 1)
        runner.map = SimpleNamespace(camera_data=[1, 2])
        runner.map_init = lambda **kw: runner.calls.append(('init', runner.zone.zone_id))
        runner.full_scan = Mock(side_effect=AssertionError('大世界补扫不能调用普通战役扫描'))
        runner.map_rescan = lambda **kw: runner.calls.append(('rescan', runner.zone.zone_id)) or True
        runner.clear_question_any_fleet = lambda: runner.calls.append(('radar', runner.zone.zone_id))
        runner.os_map_goto_globe = Mock()
        return runner

    def test_full_pipeline_uses_ordinary_zones_and_own_progress(self):
        runner = self.runner()
        with self.assertRaises(TaskEnd):
            runner.os_explore_cleanup()
        self.assertEqual(runner.calls, [(stage, zone) for zone in [44, 24, 22]
                                      for stage in ['enter', 'rescan', 'radar']])
        self.assertEqual(runner.config.OpsiExploreCleanup_State['phase'], 'done')
        self.assertEqual(runner.config.OpsiExploreCleanup_Progress, '已补扫 3/3')
        self.assertEqual(runner.config.cross_get('OpsiExplore.OpsiExplore.ExploreProgress'), '已完成百分之100.00')
        self.assertFalse(runner._opsi_meowfficer_cleanup)
        runner.config.task_delay.assert_called_once_with(target=RESET)

    def test_world_rescan_visits_all_camera_positions_without_spawn_data(self):
        map_ = OSCampaignMap()
        map_.shape = 'H8'
        self.assertEqual(map_.spawn_data_stack, [])
        runner = SimpleNamespace(
            map=map_, camera=(0, 0), zone=SimpleNamespace(is_port=False),
            config=SimpleNamespace(OpsiFleet_Fleet=1), _opsi_meowfficer_cleanup=True,
            _solved_fleet_mechanism=False, _solved_map_event=set(), is_in_task_explore=True,
            fleet_set=Mock(), map_data_init=Mock(), map_init=Mock(), handle_info_bar=Mock(),
            update=Mock(), focus_to=Mock(), focus_to_grid_center=Mock(),
            map_rescan_current=Mock(return_value=False),
        )
        runner.map_rescan_once = lambda **kw: OSMap.map_rescan_once(runner, **kw)
        self.assertTrue(OSMap.map_rescan(runner, rescan_mode='full'))
        expected = map_.camera_data.sort_by_camera_distance(runner.camera)
        self.assertEqual(runner.focus_to.call_args_list,
                         [call(grid, swipe_limit=(6, 5)) for grid in expected])
        self.assertEqual(runner.map_rescan_current.call_count, len(expected) + 1)

    def test_failed_world_scan_preserves_checkpoint_and_skips_radar(self):
        for failure in (False, MapDetectionError('扫描失败')):
            runner = self.runner(self.state())
            runner.map_rescan = Mock(return_value=failure if failure is False else None,
                                     side_effect=failure if isinstance(failure, Exception) else None)
            runner.clear_question_any_fleet = Mock()
            with self.assertRaises((GameStuckError, MapDetectionError)):
                runner.os_explore_cleanup()
            self.assertEqual(runner.config.OpsiExploreCleanup_State['next'], 0)
            self.assertEqual(runner.config.OpsiExploreCleanup_State['attempts'], 1)
            runner.clear_question_any_fleet.assert_not_called()
            runner.os_map_goto_globe.assert_not_called()

    def test_incomplete_exploration_never_enters_any_zone(self):
        for progress in ('已完成百分之99.00', '', None):
            runner = self.runner(progress=progress)
            with self.assertRaises(TaskEnd):
                runner.os_explore_cleanup()
            self.assertEqual(runner.calls, [])
            runner.config.task_delay.assert_called_once_with(server_update=True)

    def test_gate_runs_before_initializing_game(self):
        wrapper = OSCampaignRun.__new__(OSCampaignRun)
        wrapper.config = self.runner(progress='').config
        wrapper._run_opsi_task_with_ap_overflow_guard = Mock()
        with self.assertRaises(TaskEnd):
            wrapper.opsi_explore_cleanup()
        wrapper._run_opsi_task_with_ap_overflow_guard.assert_not_called()

    def test_done_month_does_not_initialize_or_repeat(self):
        state = self.state()
        state['phase'] = 'done'
        wrapper = OSCampaignRun.__new__(OSCampaignRun)
        wrapper.config = self.runner(state).config
        wrapper._run_opsi_task_with_ap_overflow_guard = Mock()
        with self.assertRaises(TaskEnd):
            wrapper.opsi_explore_cleanup()
        wrapper._run_opsi_task_with_ap_overflow_guard.assert_not_called()

    def test_restart_resumes_unfinished_zone(self):
        runner = self.runner(self.state())
        normal_enter = runner.globe_goto
        def fail_second(zone, **kwargs):
            if zone == 24:
                raise MapDetectionError('识别失败')
            normal_enter(zone, **kwargs)
        runner.globe_goto = fail_second
        with self.assertRaises(MapDetectionError):
            runner.os_explore_cleanup()
        stored = json.loads(json.dumps(runner.config.OpsiExploreCleanup_State))
        self.assertEqual((stored['next'], stored['attempts']), (1, 1))
        restarted = self.runner(stored)
        with self.assertRaises(TaskEnd):
            restarted.os_explore_cleanup()
        self.assertEqual([zone for stage, zone in restarted.calls if stage == 'enter'], [24, 22])

    def test_three_unfinished_attempts_stop(self):
        runner = self.runner(self.state())
        runner.globe_goto = Mock(side_effect=GameStuckError('无法进入'))
        for _ in range(3):
            with self.assertRaises(GameStuckError):
                runner.os_explore_cleanup()
        with self.assertRaises(RequestHumanTakeover):
            runner.os_explore_cleanup()
        self.assertEqual(runner.globe_goto.call_count, 3)

    def test_new_month_resets_own_progress_and_rejects_stale_100_percent(self):
        state = self.state()
        state.update(reset='2026-10-01T00:00:00', phase='done')
        runner = self.runner(state, month={'reset': '2026-10-01T00:00:00'})
        runner.config.OpsiExploreCleanup_Progress = '已补扫 3/3'
        with self.assertRaises(TaskEnd):
            runner.os_explore_cleanup()
        self.assertIsNone(runner.config.OpsiExploreCleanup_State)
        self.assertEqual(runner.config.OpsiExploreCleanup_Progress, '')
        self.assertEqual(runner.calls, [])

    def test_exit_failure_does_not_advance_checkpoint(self):
        runner = self.runner(self.state())
        runner.os_map_goto_globe.side_effect = GameStuckError('退出失败')
        with self.assertRaises(GameStuckError):
            runner.os_explore_cleanup()
        self.assertEqual(runner.config.OpsiExploreCleanup_State['next'], 0)

    def test_real_configuration_retains_checkpoint_and_migrates_old_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cleanup-test.json'
            data = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
            del data['OpsiExploreCleanup']
            data['OpsiExplore']['OpsiExplore'].update(MeowfficerCleanup=True, MeowfficerCleanupState=self.state())
            data['OpsiExplore']['OpsiFleet']['Fleet'] = 3
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('module.config.config.filepath_config', return_value=str(path)), \
                    patch('module.config.config_updater.filepath_config', return_value=str(path)):
                config = AzurLaneConfig('cleanup-test', task='OpsiExploreCleanup')
                self.assertTrue(config.Scheduler_Enable)
                self.assertEqual(config.OpsiFleet_Fleet, 3)
                self.assertEqual(config.OpsiExploreCleanup_State, self.state())
                state = self.state()
                state.update(next=2, attempts=1)
                config.OpsiExploreCleanup_State = state
                restarted = AzurLaneConfig('cleanup-test', task='OpsiExploreCleanup')
                self.assertEqual(restarted.OpsiExploreCleanup_State, state)

    def test_exploration_month_marker_is_not_migrated_as_cleanup_state(self):
        self.assertIsNone(opsi_explore_cleanup_state_redirect({'reset': RESET.isoformat(), 'phase': 'explore'}))
        self.assertIsNone(opsi_explore_cleanup_state_redirect({'reset': RESET.isoformat(), 'phase': 'done'}))

    @patch('module.os.tasks.explore.get_os_next_reset', return_value=RESET)
    def test_exploration_only_schedules_independent_cleanup(self, reset):
        runner = OpsiExplore.__new__(OpsiExplore)
        runner.config = SimpleNamespace(
            OpsiExplore_MeowfficerCleanupState=None, multi_set=nullcontext,
            task_delay=Mock(), task_call=Mock(), task_stop=Mock(side_effect=TaskEnd))
        with self.assertRaises(TaskEnd):
            runner._os_explore_end()
        self.assertEqual(runner.config.OpsiExplore_ExploreProgress, '已完成百分之100.00')
        runner.config.task_call.assert_any_call('OpsiExploreCleanup', force_call=False)

    def test_initialization_skips_unnecessary_battles(self):
        runner = self.runner()
        runner.config.task = SimpleNamespace(command='OpsiExploreCleanup')
        runner.config.override = Mock()
        runner.config.cross_get = Mock(side_effect=lambda keys, default=None:
                                       22 if keys.endswith('.TargetZone') else default)
        runner.is_in_map = lambda: True
        runner.is_in_special_zone = lambda: False
        runner.zone = SimpleNamespace(zone_id=44)
        for name in ('zone_init', 'hp_reset', 'handle_after_auto_search', 'handle_current_fleet_resolve', 'run_first_auto_search'):
            setattr(runner, name, Mock())
        runner.os_init()
        runner.run_first_auto_search.assert_not_called()

    def test_already_unpinned_globe_returns_without_stalling(self):
        def loop():
            yield None
            raise GameStuckError('循环未退出')
        runner = SimpleNamespace(loop=loop, is_in_globe=lambda: True, handle_zone_pinned=Mock(return_value=False))
        with patch('module.os.globe_operation.Timer', return_value=SimpleNamespace(start=lambda: SimpleNamespace(reached=lambda: True))):
            GlobeOperation.os_map_goto_globe(runner)
        runner.handle_zone_pinned.assert_called_once()

    def navigation_runner(self, pinned):
        runner = SimpleNamespace(
            zone=44, name_to_zone=lambda zone: zone, is_in_special_zone=lambda: False,
            is_in_map=lambda: False, globe_update=Mock(), globe_focus_to=Mock(),
            zone_type_select=Mock(), get_zone_pinned_name=lambda: pinned, globe_enter=Mock())
        runner.zone_init = lambda: setattr(runner, 'zone', 44)
        return runner

    def test_force_entry_enters_ordinary_zone_even_when_current_zone_matches(self):
        runner = self.navigation_runner('DANGEROUS')
        self.assertTrue(OSMap.globe_goto(runner, 44, types='DANGEROUS', force_enter=True))
        runner.globe_enter.assert_called_once_with(44)
        runner.zone_type_select.assert_called_once_with(types='DANGEROUS')

    def test_ordinary_zone_entry_never_falls_back_to_safe(self):
        runner = self.navigation_runner('SAFE')
        with self.assertRaises(GameStuckError):
            OSMap.globe_goto(runner, 44, types='DANGEROUS', force_enter=True)
        runner.globe_enter.assert_not_called()

    def test_cleanup_scans_all_existing_event_types(self):
        runner = SimpleNamespace(_opsi_meowfficer_cleanup=True, _solved_map_event=set(), is_in_task_explore=True)
        runner.config = SimpleNamespace(task=SimpleNamespace(command='OpsiExploreCleanup'))
        runner.view = SimpleNamespace(select=Mock(return_value=[]))
        self.assertFalse(OSMap.map_rescan_current(runner))
        self.assertEqual(runner.view.select.call_args_list, [call(**{key: True}) for key in (
            'is_exploration_container', 'is_exploration_reward', 'is_akashi',
            'is_scanning_device', 'is_logging_tower', 'is_fleet_mechanism')])

    def test_cleanup_scans_all_fleets_after_first_event(self):
        runner = SimpleNamespace(
            _opsi_meowfficer_cleanup=True, _solved_map_event=set(), config=SimpleNamespace(OpsiFleet_Fleet=1),
            zone=SimpleNamespace(is_port=False), device=SimpleNamespace(image=None, screenshot=Mock()),
            radar=SimpleNamespace(predict_question=Mock(return_value=(0, -1))))
        current = [1]
        runner.fleet_set = Mock(side_effect=lambda fleet: current.__setitem__(0, fleet))
        runner.fleet_selector = SimpleNamespace(get=lambda: current[0])
        runner.clear_question = Mock(side_effect=lambda **kw: runner._solved_map_event.add('is_logging_tower'))
        runner.map_rescan = Mock(return_value=True)
        self.assertTrue(OSMap.clear_question_any_fleet(runner))
        self.assertEqual(runner.fleet_set.call_args_list, [call(fleet) for fleet in (1, 2, 3, 4)])

    def test_cleanup_does_not_use_hazard_one_fixed_patrol_coordinates(self):
        OSMap._execute_fixed_patrol_scan(SimpleNamespace(_opsi_meowfficer_cleanup=True), ExecuteFixedPatrolScan=True)


if __name__ == '__main__':
    unittest.main()
