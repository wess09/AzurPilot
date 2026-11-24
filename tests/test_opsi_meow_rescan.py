"""普通短猫沿真实自律寻敌调用链只扫描一次，事件与掉落记录保持完整。"""

import unittest
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import GameStuckError, ScriptError
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap
from module.os.map_base import OSCampaignMap
from module.os.map_event_resume import PENDING_MAP_EVENT_KEY
from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming
from module.statistics.azurstats import DropImage


class MeowRescanTests(unittest.TestCase):
    def runner(self, event='is_akashi', random_events=True):
        runner = OpsiMeowfficerFarming.__new__(OpsiMeowfficerFarming)
        runner.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiMeowfficerFarming'),
            OpsiMeowfficerFarming_HazardLevel=5, OpsiFleet_Fleet=1, OpsiFleet_Submarine=False,
            OpsiGeneral_DoRandomMapEvent=random_events, OpsiMeowfficerFarming_ExecuteFixedPatrolScan=True,
            DropRecord_OpsiMeowfficerFarming='upload', check_task_switch=Mock(),
        )
        runner.zone = SimpleNamespace(zone_id=1, location=(0, 0), is_port=False)
        target = SimpleNamespace(zone_id=2, location=(1200, 1012), is_port=False)
        runner.zones = SelectedGrids([runner.zone, target])
        runner.zone_select = Mock(return_value=runner.zones)
        runner.globe_goto = Mock(side_effect=lambda zone, **kwargs: setattr(runner, 'zone', zone))
        runner.device = Mock(image='map')
        runner.fleet_set = Mock()
        runner.os_order_execute = Mock()
        runner.meow_search_metrics_start = Mock()
        runner.meow_search_metrics_end = Mock()
        runner.handle_ash_beacon_attack = Mock()
        runner.hp_reset = Mock()
        runner.hp_get = Mock()
        runner.clear_question = Mock()
        runner.clear_question_any_fleet = Mock()
        runner.handle_after_auto_search = Mock()
        runner._auto_search_battle_count = 1
        runner.stat = Mock()
        drop = DropImage(runner.stat, 'opsi_meowfficer_farming', save=False, local=True)
        runner.stat.new.return_value = drop
        runner.clip_active = False

        @contextmanager
        def clip():
            runner.clip_active = True
            try:
                yield
            finally:
                runner.clip_active = False
        runner._meow_debug_clip = clip

        def search(collector, **kwargs):
            self.assertFalse(runner.clip_active)
            collector.add('combat-reward')
            return 1
        runner.os_auto_search_run = Mock(side_effect=search)

        def scan(rescan_mode='full', drop=None):
            self.assertTrue(runner.clip_active)
            self.assertIs(drop, runner.stat.new.return_value)
            self.assertEqual(rescan_mode, 'full')
            runner._solved_map_event.add(event)
            runner._solved_fleet_mechanism = True
            drop.add('event-reward')
        runner.map_rescan = Mock(side_effect=scan)
        return runner, target

    def test_normal_search_scans_once_and_preserves_each_event_and_reward(self):
        for enabled in (True, False):
            for event in ('is_akashi', 'is_scanning_device', 'is_logging_tower', 'is_fleet_mechanism'):
                with self.subTest(enabled=enabled, event=event):
                    runner, _ = self.runner(event, enabled)
                    with patch('module.statistics.opsi_runtime.record_meow_akashi_encounter') as record:
                        runner._meow_handle_normal_search()
                    runner.map_rescan.assert_called_once_with(rescan_mode='full', drop=runner.stat.new.return_value)
                    self.assertTrue(runner._solved_fleet_mechanism)
                    if event == 'is_akashi':
                        record.assert_called_once_with(runner)
                    else:
                        self.assertIn(event, runner._solved_map_event)
                        record.assert_not_called()
                    if event != 'is_fleet_mechanism':
                        runner.clear_question_any_fleet.assert_not_called()
                    self.assertEqual(runner.stat.commit.call_args.kwargs['images'],
                                     ['combat-reward', 'map', 'event-reward'])
                    self.assertEqual(runner.stat.commit.call_args.kwargs['combat_count'], 1)
                    runner.handle_after_auto_search.assert_called_once()
                    runner.meow_search_metrics_end.assert_called_once()
                    self.assertFalse(runner.clip_active)

    def test_target_zone_auto_search_uses_same_collector_and_single_full_scan(self):
        runner, target = self.runner()
        with patch('module.statistics.opsi_runtime.record_meow_akashi_encounter') as record:
            runner._meow_handle_target_zone_search(target)
        runner.map_rescan.assert_called_once()
        record.assert_called_once_with(runner)

    def test_target_zone_keeps_the_existing_random_event_switch(self):
        runner, target = self.runner(random_events=False)
        runner._meow_handle_target_zone_search(target)
        runner.map_rescan.assert_not_called()
        runner.handle_after_auto_search.assert_called_once()

    def test_scan_error_propagates_and_closes_clip_and_metrics(self):
        runner, _ = self.runner()
        runner.map_rescan.side_effect = GameStuckError('定位失败')
        with self.assertRaises(GameStuckError):
            runner._meow_handle_normal_search()
        self.assertFalse(runner.clip_active)
        runner.meow_search_metrics_end.assert_called_once()
        runner.handle_after_auto_search.assert_not_called()

    def test_strategic_traditional_and_stay_modes_still_scan_once(self):
        for mode in ('_meow_handle_traditional_zone', '_meow_handle_stay_in_zone'):
            with self.subTest(mode=mode):
                runner, target = self.runner()
                runner.run_strategic_search = Mock(return_value=True)
                runner.run_auto_search = Mock(side_effect=AssertionError('战略搜索不走自律扫描'))
                runner.map_rescan = Mock()
                runner._meow_fixed_patrol_scan = Mock()
                runner.get_current_zone = Mock()
                runner.poll_background_resources = Mock()
                runner.invalidate_action_point_cache = Mock()
                runner.action_point_set = Mock()
                runner.action_point_reusable = Mock(return_value=False)
                getattr(runner, mode)(target)
                runner.run_strategic_search.assert_called_once()
                runner.map_rescan.assert_called_once_with()
                runner._meow_fixed_patrol_scan.assert_called_once()
                runner.handle_after_auto_search.assert_called_once()

    def single_zone_runner(self, stay_in_zone, **event):
        runner, zone = self.runner()
        runner.zone = zone
        runner.is_zone_name_hidden = True
        runner.is_in_map = Mock(return_value=True)
        runner.config.SERVER = 'cn'
        runner.config.OpsiMeowfficerFarming_StayInZone = stay_in_zone
        runner.config.OpsiMeowfficerFarming_TargetZone = str(zone.zone_id)
        runner._meow_target_zone_list = [zone] if stay_in_zone else []
        runner._meow_traditional_zone = None if stay_in_zone else zone
        reset = datetime(2026, 12, 1)
        state = dict(version=1, reset=reset.isoformat(), server='cn', zone=zone.zone_id,
                     type='akashi', node='B3', mode=None, submitted=False, remaining=0)
        state.update(event)
        stored = {
            PENDING_MAP_EVENT_KEY: state,
            'OpsiMeowfficerFarming.OpsiMeowfficerFarming.TargetZone': str(zone.zone_id),
        }

        def cross_set(keys, value):
            stored[keys] = value

        runner.config.cross_get = lambda keys, default=None: stored.get(keys, default)
        runner.config.cross_set = cross_set
        runner.name_to_zone = Mock(return_value=zone)
        runner._meow_ap_check = Mock(return_value=True)
        runner._meow_handle_stay_in_zone = Mock()
        runner._meow_handle_traditional_zone = Mock()
        runner.invalidate_action_point_cache = Mock()
        runner._run_siren_followup_search = Mock()
        runner._execute_fixed_patrol_scan = Mock()
        runner.map_rescan = Mock(return_value=False)
        self.enterContext(patch('module.os.map_event_resume.get_os_next_reset', return_value=reset))
        self.enterContext(patch('module.base.debug_clip.cleanup_clips_if_due'))
        return runner, zone, stored

    def test_single_zone_resumes_device_before_battle_once(self):
        for stay_in_zone in (False, True):
            with self.subTest(stay_in_zone=stay_in_zone):
                runner, zone, stored = self.single_zone_runner(
                    stay_in_zone, type='scanning_device', mode='enemy', submitted=True, remaining=2,
                )
                actions = Mock()
                actions.attach_mock(runner._run_siren_followup_search, 'resume')
                actions.attach_mock(runner._meow_handle_stay_in_zone, 'stay')
                actions.attach_mock(runner._meow_handle_traditional_zone, 'traditional')
                saved = stored[PENDING_MAP_EVENT_KEY]
                fresh_ap = (1000, 120)

                runner.run_meowfficer_farming_once(ap_checked=True, prepared=True, fresh_ap=fresh_ap)

                first_battle = call.stay(zone, fresh_ap=None) if stay_in_zone else call.traditional(zone)
                self.assertEqual(actions.mock_calls, [call.resume('enemy', drop=None, remaining=2), first_battle])
                self.assertIsNone(stored[PENDING_MAP_EVENT_KEY])
                runner.invalidate_action_point_cache.assert_called_once_with()
                runner.map_rescan.assert_not_called()
                runner._execute_fixed_patrol_scan.assert_not_called()

                stored[PENDING_MAP_EVENT_KEY] = saved
                runner.run_meowfficer_farming_once(ap_checked=True, prepared=True, fresh_ap=fresh_ap)

                second_battle = call.stay(zone, fresh_ap=fresh_ap) if stay_in_zone else call.traditional(zone)
                self.assertEqual(actions.mock_calls[-1], second_battle)
                runner._run_siren_followup_search.assert_called_once()
                self.assertIs(stored[PENDING_MAP_EVENT_KEY], saved)

    def test_single_zone_scan_miss_clears_record_and_continues_without_moving_fleets(self):
        runner, zone, stored = self.single_zone_runner(stay_in_zone=False)

        runner.run_meowfficer_farming_once(ap_checked=True, prepared=True)

        runner.map_rescan.assert_called_once_with(rescan_mode='full', drop=None)
        runner._execute_fixed_patrol_scan.assert_not_called()
        self.assertIsNone(stored[PENDING_MAP_EVENT_KEY])
        runner._meow_handle_traditional_zone.assert_called_once_with(zone)

    def test_multi_zone_and_other_zone_records_keep_the_normal_search(self):
        runner, zone, stored = self.single_zone_runner(stay_in_zone=True, zone=44)
        pending = stored[PENDING_MAP_EVENT_KEY]
        runner.run_meowfficer_farming_once(ap_checked=True, prepared=True, fresh_ap=(1000, 120))
        runner._meow_handle_stay_in_zone.assert_called_once_with(zone, fresh_ap=(1000, 120))
        runner.map_rescan.assert_not_called()
        self.assertIs(stored[PENDING_MAP_EVENT_KEY], pending)

        runner, zone, stored = self.single_zone_runner(stay_in_zone=True)
        pending = stored[PENDING_MAP_EVENT_KEY]
        runner._meow_target_zone_list.append(SimpleNamespace(zone_id=44))
        runner._meow_handle_target_zone_search = Mock()
        runner.run_meowfficer_farming_once(ap_checked=True, prepared=True)
        runner._meow_handle_target_zone_search.assert_called_once_with(zone)
        runner.map_rescan.assert_not_called()
        self.assertIs(stored[PENDING_MAP_EVENT_KEY], pending)

    def test_initial_search_defers_only_for_current_single_zone_with_pending_event(self):
        runner, zone, stored = self.single_zone_runner(stay_in_zone=True)
        target_path = 'OpsiMeowfficerFarming.OpsiMeowfficerFarming.TargetZone'
        with patch.object(OSMap, 'run_first_auto_search') as first_search:
            runner.run_first_auto_search()
            first_search.assert_not_called()

            stored[target_path] = f'{zone.zone_id},44'
            runner.name_to_zone.side_effect = ScriptError('not a single zone')
            runner.run_first_auto_search()
            first_search.assert_called_once_with()

    def test_sorted_scan_log_matches_actual_focus_target(self):
        map_ = OSCampaignMap()
        map_.shape = 'T20'
        camera = map_.camera_data[-1].location
        runner = SimpleNamespace(
            map=map_, camera=camera, map_data_init=Mock(), handle_info_bar=Mock(), update=Mock(),
            map_init=Mock(), map_rescan_current=Mock(return_value=False),
            focus_to=Mock(), focus_to_grid_center=Mock(),
        )
        with patch('module.os.map.logger') as logger:
            OSMap.map_rescan_once(runner)
        targets = [entry.args[0] for entry in runner.focus_to.call_args_list]
        logged = [entry.args[0] for entry in logger.hr.call_args_list if entry.args[0].startswith('重新扫描 ')]
        self.assertEqual(logged, [f'重新扫描 {target}' for target in targets])
        self.assertEqual(targets[0].location, camera)
        self.assertEqual(logger.attr.call_args_list[:len(targets)],
                         [call('扫描相机/目标', f'{targets[0]} -> {target}') for target in targets])


if __name__ == '__main__':
    unittest.main()
