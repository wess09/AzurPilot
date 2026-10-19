"""明石按钮重合与重启续查回归；使用虚拟时钟和内存配置，不连接游戏。"""

import copy
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.base.timer import Timer
from module.config.deep import deep_set
from module.config.config import AzurLaneConfig, Function
from module.config.utils import get_os_next_reset
from module.exception import GameStuckError
from module.handler.assets import STORY_SKIP_3
from module.os.event_recovery import MapEventRecovery, PENDING_EVENT_PATH
from module.os.assets import FLEET_CHOOSE
from module.os.map import OSMap
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os_shop.assets import PORT_SUPPLY_CHECK
from module.os_shop.shop import OSShop
from tests.test_opsi_cl1_speed import VirtualClock, WalkStateStub
from tests.test_opsi_fixed_patrol_escalation import FixedPatrolStub
from tests import test_opsi_task_context as task_context_tests


def make_grid(area=(270, 584, 345, 668), location=(1, 7)):
    return SimpleNamespace(button=area, location=location, is_akashi=True)


class ShopHarness(OSShop):
    def __init__(self, clock, *, page='map', opens=True, menu=False):
        self.clock = clock
        self.page = page
        self.opens = opens
        self.menu = menu
        self.clicks = []
        self.device = SimpleNamespace(image=None, screenshot=self.screenshot, click=self.click)
        self.fleet_selector = SimpleNamespace(bar_opened=lambda: self.menu)
        self.handle_story_skip = Mock(return_value=False)
        self.os_shop_buy = Mock(side_effect=lambda **kwargs: setattr(clock, 'now', clock.now + 30))
        self.ui_back = Mock(side_effect=lambda **kwargs: setattr(self, 'page', 'map'))
        self.returns = []

    def screenshot(self):
        self.clock.now += 0.5

    def click(self, button):
        self.clicks.append((button, self.clock.now))
        if button is FLEET_CHOOSE:
            self.menu = False
        elif self.opens:
            self.page = 'shop'

    def appear(self, button, **kwargs):
        return button is PORT_SUPPLY_CHECK and self.page == 'shop'

    def appear_then_click(self, button, **kwargs):
        self.device.click(button)
        return True

    def is_in_map(self):
        return self.page == 'map'

    def is_in_globe(self):
        return self.page == 'globe'

    def is_in_storage(self):
        return self.page == 'storage'

    def is_in_os_mission(self):
        return self.page == 'mission'

    def is_in_map_order(self):
        return self.page == 'order'

    def leave(self):
        self.returns.append(self.page)
        self.page = 'map'

    os_globe_goto_map = leave
    storage_quit = leave
    os_mission_quit = leave
    order_quit = leave


class TestAkashiEntry(unittest.TestCase):
    def setUp(self):
        self.clock = VirtualClock()
        timer_patch = patch('module.base.timer.time', self.clock)
        timer_patch.start()
        self.addCleanup(timer_patch.stop)

    def test_partial_overlap_excludes_the_entire_bottom_toolbar(self):
        handler = ShopHarness(self.clock)
        self.assertTrue(handler.handle_akashi_supply_buy(make_grid()))
        area = handler.clicks[0][0].button
        self.assertEqual(area, (270, 584, 345, 628))
        self.assertLess(area[3], FLEET_CHOOSE.button[1])
        handler.os_shop_buy.assert_called_once()

    def test_fully_covered_grid_never_clicks_the_toolbar(self):
        handler = ShopHarness(self.clock)
        self.assertFalse(handler.handle_akashi_supply_buy(make_grid((270, 636, 345, 699))))
        self.assertEqual(handler.clicks, [])
        handler.os_shop_buy.assert_not_called()

    def test_open_menu_is_closed_before_any_map_click(self):
        handler = ShopHarness(self.clock, menu=True)
        self.assertTrue(handler.handle_akashi_supply_buy(make_grid()))
        self.assertIs(handler.clicks[0][0], FLEET_CHOOSE)
        self.assertEqual(len(handler.clicks), 2)

    def test_three_clicks_two_seconds_apart_then_twelve_second_failure(self):
        handler = ShopHarness(self.clock, opens=False)
        self.assertFalse(handler.handle_akashi_supply_buy(make_grid()))
        self.assertEqual(len(handler.clicks), 3)
        times = [time for _, time in handler.clicks]
        self.assertTrue(all(b - a >= 2 for a, b in zip(times, times[1:])))
        self.assertGreaterEqual(self.clock.now, 112)
        self.assertLessEqual(self.clock.now, 112.5)
        handler.os_shop_buy.assert_not_called()
        handler.ui_back.assert_not_called()

    def test_existing_shop_skips_entry_and_purchase_has_no_twelve_second_limit(self):
        handler = ShopHarness(self.clock, page='shop')
        self.assertTrue(handler.handle_akashi_supply_buy(make_grid((1104, 169, 1214, 284))))
        self.assertEqual(handler.clicks, [])
        self.assertEqual(self.clock.now, 130)

    def test_unconfirmed_return_does_not_finish_pending_event(self):
        handler = ShopHarness(self.clock, page='shop')
        handler.ui_back = Mock()
        handler._finish_pending_event = Mock()
        self.assertFalse(handler.handle_akashi_supply_buy(make_grid()))
        handler._finish_pending_event.assert_not_called()

    def test_known_pages_return_before_relocating_and_clicking(self):
        for page in ('globe', 'storage', 'mission', 'order'):
            with self.subTest(page=page):
                handler = ShopHarness(self.clock, page=page)
                handler._event_global_location = Mock(return_value=(1, 7))

                def fresh_button(target, **kwargs):
                    self.assertEqual(handler.page, 'map')
                    self.assertEqual(handler.returns, [page])
                    return OSShop._event_safe_click_button(make_grid((500, 300, 570, 370)))

                handler._prepare_event_click = Mock(side_effect=fresh_button)
                self.assertTrue(handler.handle_akashi_supply_buy(make_grid()))
                self.assertEqual(handler.clicks[0][0].button, (500, 300, 570, 370))
                handler._prepare_event_click.assert_called_once_with((1, 7), camera_budget=[2])

    def test_unknown_page_is_not_clicked(self):
        handler = ShopHarness(self.clock, page='unknown')
        self.assertFalse(handler.handle_akashi_supply_buy(make_grid()))
        self.assertEqual(handler.clicks, [])
        self.assertEqual(handler.returns, [])

    def test_globe_detection_precedes_a_false_positive_fleet_menu(self):
        handler = ShopHarness(self.clock, page='globe', menu=True)

        def close_menu(button, **kwargs):
            self.assertEqual(handler.returns, ['globe'])
            self.assertEqual(handler.page, 'map')
            handler.device.click(button)
            return True

        handler.appear_then_click = Mock(side_effect=close_menu)
        self.assertTrue(handler.handle_akashi_supply_buy(make_grid()))
        handler.appear_then_click.assert_called_once()


class View(dict):
    center_loca = (4, 3)


class CameraHarness(MapEventRecovery, OSShop):
    def __init__(self, *, movable=True):
        self.camera = (4, 3)
        self.target = (1, 7)
        self.view = View({self.target: make_grid((270, 636, 345, 699))})
        self.update = Mock()
        self.appear = Mock(return_value=False)
        self.is_in_map = Mock(return_value=True)
        self.fleet_selector = SimpleNamespace(bar_opened=lambda: False)
        self.swipes = []
        self.movable = movable

    def map_swipe(self, vector):
        self.swipes.append(vector)
        if self.movable:
            self.camera = tuple(c + v for c, v in zip(self.camera, vector))
            local = tuple(g - c + v for g, c, v in
                          zip(self.target, self.camera, self.view.center_loca))
            self.view = View({local: make_grid((500, 300, 570, 370), local)})
        return True


class TestAkashiCamera(unittest.TestCase):
    def test_story_appearing_during_update_blocks_all_camera_swipes(self):
        handler = CameraHarness()
        handler.appear = lambda button, **kwargs: button is STORY_SKIP_3
        self.assertIsNone(handler._prepare_event_click(handler.target))
        self.assertEqual(handler.swipes, [])

    def test_reframes_and_uses_new_grid_bounds(self):
        handler = CameraHarness()
        button = handler._prepare_event_click(handler.target)
        self.assertEqual(button.button, (500, 300, 570, 370))
        self.assertEqual(len(handler.swipes), 1)
        self.assertEqual(handler._event_global_location(handler._event_local_grid(handler.target)), handler.target)

    def test_immovable_camera_has_at_most_two_attempts(self):
        handler = CameraHarness(movable=False)
        budget = [2]
        self.assertIsNone(handler._prepare_event_click(handler.target, camera_budget=budget))
        self.assertIsNone(handler._prepare_event_click(handler.target, camera_budget=budget))
        self.assertEqual(len(handler.swipes), 2)


class RecoveryHarness(MapEventRecovery):
    def __init__(self, owner='OpsiHazard1Leveling'):
        # 真实配置绑定与代理上下文，只有持久化由内存字典代替。
        self.config = task_context_tests.TestOpsiTaskContext().make_runner(owner).config

        def save(keys, value):
            deep_set(self.config.data, keys=keys, value=copy.deepcopy(value))

        self.config.cross_set = Mock(side_effect=save)
        self.config.OpsiFleet_Fleet = 1
        self.zone = SimpleNamespace(zone_id=22, hazard_level=1, is_port=False)
        self.is_in_special_zone = Mock(return_value=False)
        self.is_in_map = Mock(return_value=True)
        self._solved_map_event = set()
        self._goto_pending_event_with_other_fleets = Mock(return_value=False)
        self._execute_fixed_patrol_scan = Mock()
        self.map_rescan = Mock()
        self.camera = (4, 3)
        self.view = View()

    def save_pending(self):
        self.config.cross_set(PENDING_EVENT_PATH, dict(
            server=self.config.SERVER, reset=get_os_next_reset().isoformat(),
            zone=22, fleet=1, target=[1, 7], kind='is_akashi', phase='interact',
        ))


class TestPendingAkashi(unittest.TestCase):
    def test_real_config_save_reload_and_clear_use_only_a_temporary_file(self):
        handler = RecoveryHarness()
        handler.save_pending()
        pending = handler._get_pending_event()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'akashi-test.json'
            path.write_text('{}', encoding='utf-8')
            with patch('module.config.config.filepath_config', return_value=str(path)), patch(
                'module.config.config_updater.filepath_config', return_value=str(path)
            ):
                worker = AzurLaneConfig.__new__(AzurLaneConfig)
                worker.config_name = 'akashi-test'
                worker.data = worker.read_file('akashi-test')
                worker._loaded_data = copy.deepcopy(worker.data)
                worker.modified = {PENDING_EVENT_PATH: pending}
                worker.save()
                handler.config.data = worker.read_file('akashi-test')
                self.assertEqual(handler._get_pending_event(), pending)
                saved = json.loads(path.read_text(encoding='utf-8'))
                group = saved['OpsiHazard1Leveling']['OpsiHazard1Leveling']
                self.assertFalse(group['ExecuteFixedPatrolScan'])
                self.assertEqual(group['PendingEventRecovery'], pending)
                worker.modified[PENDING_EVENT_PATH] = None
                worker.save()
                self.assertIsNone(worker.read_file('akashi-test')['OpsiHazard1Leveling']
                                  ['OpsiHazard1Leveling']['PendingEventRecovery'])

    def test_confirmation_is_saved_before_first_click_and_keeps_global_location(self):
        handler = RecoveryHarness()
        grid = make_grid()
        handler.convert_radar_to_local = Mock(return_value=SimpleNamespace(distance_to=lambda grid: 1))

        def walk(**kwargs):
            state = handler._get_pending_event()
            self.assertEqual(state['target'], [1, 7])
            self.assertEqual(state['zone'], 22)
            self.assertEqual(kwargs['event_target'], (1, 7))
            return ''

        handler.wait_until_walk_stable = Mock(side_effect=walk)
        self.assertFalse(handler._try_akashi_grid(grid))
        self.assertNotIn('is_akashi', handler._solved_map_event)
        self.assertIsNotNone(handler._get_pending_event())

    def test_other_tasks_do_not_create_hazard1_recovery_records(self):
        handler = RecoveryHarness('OpsiMeowfficerFarming')
        handler._remember_pending_event('is_akashi', make_grid())
        handler.config.cross_set.assert_not_called()

    def test_mismatched_server_reset_and_zone_invalidate_without_moving(self):
        for key, value in (('server', 'jp'), ('reset', 'old'), ('zone', 44), ('fleet', 0)):
            with self.subTest(key=key):
                handler = RecoveryHarness()
                handler.save_pending()
                state = handler._get_pending_event()
                state[key] = value
                handler.config.cross_set(PENDING_EVENT_PATH, state)
                self.assertFalse(handler._resume_pending_event())
                self.assertIsNone(handler.config.cross_get(PENDING_EVENT_PATH))
                handler.map_rescan.assert_not_called()
                handler._execute_fixed_patrol_scan.assert_not_called()

    def test_resume_rebinds_direct_scheduling_and_overflow_owners_and_clears_only_on_success(self):
        for owner in ('OpsiHazard1Leveling', 'OpsiScheduling', 'OpsiPreventActionPointOverflow'):
            with self.subTest(owner=owner):
                handler = RecoveryHarness(owner)
                handler.save_pending()
                original_task = handler.config.task

                def rescan(**kwargs):
                    self.assertEqual(handler.config.task.command, 'OpsiHazard1Leveling')
                    self.assertEqual(kwargs, {'rescan_mode': 'full'})
                    handler._solved_map_event.add('is_akashi')
                    handler._finish_pending_event('is_akashi')

                handler.map_rescan.side_effect = rescan
                with patch('module.os.event_recovery.record_cl1_akashi_encounter') as count:
                    self.assertTrue(handler._resume_pending_event())
                    self.assertFalse(handler._resume_pending_event())
                    count.assert_called_once_with(handler.config)
                self.assertIs(handler.config.task, original_task)
                self.assertIsNone(handler.config.cross_get(PENDING_EVENT_PATH))
                handler._execute_fixed_patrol_scan.assert_not_called()

    def test_missing_akashi_after_restart_is_not_assumed_completed(self):
        handler = RecoveryHarness('OpsiScheduling')
        handler.save_pending()
        owner = handler.config.task
        with patch('module.os.event_recovery.record_cl1_akashi_encounter') as count:
            self.assertTrue(handler._resume_pending_event())
            count.assert_not_called()
        self.assertIsNone(handler._get_pending_event())
        self.assertEqual(handler._solved_map_event, set())
        self.assertIs(handler.config.task, owner)
        handler._execute_fixed_patrol_scan.assert_called_once_with(
            ExecuteFixedPatrolScan=True, event_recovery=True)

    def test_another_fleet_success_skips_forced_movement(self):
        handler = RecoveryHarness()
        handler.save_pending()
        handler._goto_pending_event_with_other_fleets.return_value = True
        self.assertTrue(handler._recover_pending_event())
        handler._execute_fixed_patrol_scan.assert_not_called()
        self.assertFalse(handler._event_recovery_active)

    def test_forced_movement_success_is_propagated(self):
        handler = RecoveryHarness()
        handler.save_pending()
        handler._execute_fixed_patrol_scan.side_effect = lambda **kwargs: handler._finish_pending_event('is_akashi')
        self.assertTrue(handler._recover_pending_event())

    def test_recovery_budget_survives_rescan_and_nested_visit_does_not_recurse(self):
        handler = RecoveryHarness()
        handler.save_pending()
        handler._try_akashi_grid = Mock(return_value=False)

        def nested(**kwargs):
            self.assertFalse(handler._visit_akashi(make_grid()))

        handler._execute_fixed_patrol_scan.side_effect = nested
        for _ in range(2):
            self.assertFalse(handler._recover_pending_event())
        handler._execute_fixed_patrol_scan.assert_called_once()
        self.assertFalse(handler._event_recovery_active)

    def test_non_map_failure_never_attempts_fleet_operations(self):
        handler = RecoveryHarness()
        handler.save_pending()
        handler.is_in_map.return_value = False
        with self.assertRaises(GameStuckError):
            handler._recover_pending_event()
        handler._goto_pending_event_with_other_fleets.assert_not_called()


class TestEmergencyForcedMovement(unittest.TestCase):
    def test_other_fleet_attempts_restore_a_valid_original_or_primary_fleet(self):
        for original, order in ((0, [2, 3, 4, 1]), (2, [1, 3, 4, 2])):
            with self.subTest(original=original):
                handler = RecoveryHarness()
                handler.fleet_selector = SimpleNamespace(get=lambda: original)
                handler.fleet_set = Mock()
                handler.update = Mock()
                handler.view = SimpleNamespace(select=lambda **kwargs: [make_grid()])
                handler._try_akashi_grid = Mock(return_value=False)
                self.assertFalse(OSMap._goto_akashi_with_other_fleets(handler))
                self.assertEqual([call.args[0] for call in handler.fleet_set.call_args_list], order)

    def test_stops_after_the_first_fleet_move_that_reaches_akashi(self):
        handler = RecoveryHarness()
        handler._event_recovery_active = True
        handler.save_pending()
        handler.config.temporary = lambda **kwargs: SimpleNamespace(recover=Mock())
        handler.fleet_set = Mock()
        # 其他事件不能提前结束已知明石的恢复。
        handler.clear_question = Mock(side_effect=lambda **kwargs: handler._solved_map_event.add('is_logging_tower'))
        handler._move_fleet_to_patrol = Mock(return_value=True)
        handler.map_rescan.side_effect = lambda **kwargs: handler._finish_pending_event('is_akashi')
        self.assertTrue(OSMap._move_fleets_and_rescan(handler))
        handler._move_fleet_to_patrol.assert_called_once_with(1, (2, 0))
        handler.fleet_set.assert_called_once_with(1)

    def test_emergency_exception_still_restores_primary_fleet_and_recursion_guard(self):
        stub = FixedPatrolStub(enabled=False)
        stub._get_pending_event = Mock(return_value={'zone': 22})
        stub._move_fleets_and_rescan = Mock(side_effect=GameStuckError('移动中断'))
        with self.assertRaises(GameStuckError):
            OSMap._execute_fixed_patrol_scan(stub, ExecuteFixedPatrolScan=True, event_recovery=True)
        self.assertEqual(stub.fleet_sets, [1])
        self.assertFalse(stub._in_event_recovery)

    def test_known_akashi_bypasses_disabled_switch_and_low_ap_without_persisting_it(self):
        stub = FixedPatrolStub(enabled=False, current_ap=0)
        stub._get_pending_event = Mock(return_value={'zone': 22})
        OSMap._execute_fixed_patrol_scan(stub, ExecuteFixedPatrolScan=True, event_recovery=True)
        self.assertEqual(stub.move_calls, 1)
        self.assertEqual(stub.ap_reads, 0)
        self.assertEqual(stub.scan_calls, 0)
        self.assertFalse(stub.enabled)
        self.assertEqual(stub.fleet_sets, [1])
        self.assertFalse(stub._in_event_recovery)

    def test_no_pending_event_cannot_bypass_the_switch(self):
        stub = FixedPatrolStub(enabled=False)
        stub._get_pending_event = Mock(return_value=None)
        OSMap._execute_fixed_patrol_scan(stub, ExecuteFixedPatrolScan=True, event_recovery=True)
        self.assertEqual(stub.move_calls, 0)

    def test_short_cat_never_uses_hazard1_emergency_coordinates(self):
        stub = FixedPatrolStub(enabled=False, task='OpsiMeowfficerFarming')
        stub._get_pending_event = Mock(return_value={'zone': 22})
        OSMap._execute_fixed_patrol_scan(stub, ExecuteFixedPatrolScan=True, event_recovery=True)
        self.assertEqual(stub.move_calls, 0)


class TestRecoveryInitialization(unittest.TestCase):
    def test_unfinished_akashi_resumes_before_new_search_without_forcing_restart(self):
        calls = []
        handler = SimpleNamespace(
            config=SimpleNamespace(OpsiHazard1Leveling_DebugClip=False),
            run_strategic_search=Mock(side_effect=lambda: calls.append('search')),
            map_rescan=Mock(), _forced_move_enabled=Mock(return_value=False),
            _get_pending_event=Mock(side_effect=[{'zone': 22}, None, None]),
            handle_after_auto_search=Mock(),
            _resume_pending_event=Mock(side_effect=lambda: calls.append('resume')),
            is_in_map=Mock(return_value=True), match_template_color=Mock(return_value=True),
        )
        with patch('module.base.debug_clip.clip_recording', return_value=nullcontext()), patch(
            'module.base.debug_clip.cleanup_clips_if_due'
        ):
            OpsiHazard1Leveling._cl1_run_battle(handler)
        self.assertEqual(calls, ['resume', 'search'])
        handler.map_rescan.assert_called_once()
        handler.handle_after_auto_search.assert_called_once()

    def test_resume_precedes_maintenance_and_new_auto_search_for_all_entrypoints(self):
        for task in ('OpsiHazard1Leveling', 'OpsiScheduling', 'OpsiPreventActionPointOverflow', 'OpsiDaily'):
            with self.subTest(task=task):
                handler = OSMap.__new__(OSMap)
                helper = RecoveryHarness()
                handler.config = helper.config
                handler.config.task = Function({'Scheduler': {'Command': task}})
                handler.zone = helper.zone
                calls = []
                for name in ('zone_init', '_resume_pending_event', 'hp_reset', 'handle_after_auto_search',
                             'handle_current_fleet_resolve', 'run_first_auto_search'):
                    setattr(handler, name, Mock(side_effect=lambda *args, _name=name, **kwargs: calls.append(_name)))
                handler.is_in_map = Mock(return_value=True)
                handler.is_in_special_zone = Mock(return_value=False)
                handler.is_smart_scheduling_enabled = Mock(return_value=True)
                OSMap.os_init(handler)
                self.assertEqual(calls[:3], ['zone_init', '_resume_pending_event', 'hp_reset'])
                if 'run_first_auto_search' in calls:
                    self.assertLess(calls.index('_resume_pending_event'), calls.index('run_first_auto_search'))

    def test_failed_shop_is_not_reported_as_a_completed_walk_event(self):
        clock = VirtualClock()
        handler = WalkStateStub(clock, command='OpsiHazard1Leveling', shop=True)
        handler.handle_akashi_supply_buy.return_value = False
        from module.os.fleet import OSFleet

        with patch('module.base.timer.time', clock):
            result = OSFleet.wait_until_walk_stable(handler, confirm_timer=Timer(1), allow_event_finish=True)
        self.assertNotIn('akashi', result)


if __name__ == '__main__':
    unittest.main()
