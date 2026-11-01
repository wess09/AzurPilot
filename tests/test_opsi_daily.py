"""大世界每日锁定海域延期与未开荒海域侦察的离线回归。"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import crop, load_image
from module.config.config import AzurLaneConfig, TaskEnd
from module.config.deep import deep_get, deep_set
from module.exception import GameStuckError, MapDetectionError
from module.os.assets import ZONE_LOCKED
from module.os.globe_operation import OSExploreError, OSZoneLockedError
from module.os.map import OSMap
from module.os.operation_siren import OperationSiren
from module.os_handler.action_point import ActionPointLimit
from module.os_handler.assets import MISSION_CHECKOUT, MISSION_FINISH, MISSION_MONTHLY_BOSS, ORDER_SCAN


RESET = datetime(2026, 11, 1)
OLD_RESET = datetime(2026, 10, 1).isoformat()
NOW = datetime(2026, 10, 3, 9)
UPDATE = datetime(2026, 10, 4)


class TestOpsiDaily(unittest.TestCase):
    def setUp(self):
        for module in ('module.os.tasks.daily', 'module.os.tasks.smart_explore'):
            clock = patch(f'{module}.get_os_next_reset', return_value=RESET)
            clock.start()
            self.addCleanup(clock.stop)
        for name, value in (('current_time', NOW), ('get_server_next_update', UPDATE)):
            clock = patch(f'module.os_handler.mission.{name}', return_value=value)
            clock.start()
            self.addCleanup(clock.stop)
        self.data = {
            'OpsiExplore': {
                'Scheduler': {'Enable': False},
                'OpsiExplore': {'ExploreProgress': '已完成百分之30.00'},
            },
            'OpsiScheduling': {'Storage': {'Storage': {
                'SmartExplore': {'reset': RESET.isoformat(), 'phase': 'explore', 'next': [30, 0, 1]},
                'Unrelated': 'keep',
            }}},
        }
        self.runner = OperationSiren.__new__(OperationSiren)
        self.runner.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiDaily'),
            SERVER='cn',
            OpsiDaily_UseTuningSample=False,
            OpsiGeneral_UseLogger=False,
            OpsiDaily_SkipSirenResearchMission=False,
            OpsiDaily_KeepMissionZone=False,
            OpsiDaily_CollectTargetReward=False,
            OpsiFleet_Fleet=4,
            OpsiFleet_Submarine=True,
            Scheduler_ServerUpdate='00:00',
            cross_get=lambda keys, default=None: deep_get(self.data, keys, default),
            cross_set=lambda keys, value: deep_set(self.data, keys, value),
            task_delay=Mock(),
            task_stop=Mock(side_effect=TaskEnd),
            check_task_switch=Mock(),
        )
        self.runner.zone = self.runner.name_to_zone(44)
        self.runner.is_zone_name_hidden = False
        for name in ('zone_init', 'globe_goto', 'fleet_set', 'os_order_execute', 'handle_after_auto_search',
                     'ensure_no_zone_pinned', 'os_globe_goto_map', 'os_port_mission', 'os_daily_clear_all_mission_zones'):
            setattr(self.runner, name, Mock())
        self.runner.is_in_special_zone = Mock(return_value=False)
        self.runner.is_in_opsi_explore = Mock(return_value=False)
        self.runner.os_mission_overview_accept = Mock(return_value=True)
        self.runner.run_auto_search = Mock(return_value=1)

    def finish_mission(self, result='pinned_at_mission_zone'):
        self.set_next_missions([result, False])
        return self.runner.os_finish_daily_mission()

    def set_next_missions(self, results):
        queue = iter(results)

        def get_next(**kwargs):
            self.runner._os_mission_index = kwargs.get('mission_index', 0)
            return next(queue, False)

        self.runner.os_get_next_mission = Mock(side_effect=get_next)

    def prepare_mission_entry(self, zone=44):
        image = load_image(ZONE_LOCKED.file)
        self.runner.device = SimpleNamespace(image=image, click=Mock())
        self.runner.loop = lambda: iter((None,))
        self.runner.is_in_map = Mock(return_value=False)
        self.runner.is_zone_pinned = Mock(return_value=True)
        self.runner.get_zone_pinned_name = Mock(return_value='DANGEROUS')
        self.runner.appear = lambda button, offset=0: button.match(image, offset=offset)
        self.runner.os_mission_enter = Mock(return_value=(-20, -20, 20, 20))
        self.runner._os_find_checkout_offset_skip_monthly_boss = Mock(return_value=(-20, -20, 20, 20))
        self.runner.globe_update = Mock()
        self.runner.get_globe_pinned_zone = Mock(return_value=self.runner.name_to_zone(zone))

    def assert_recon(self, expected, result='pinned_at_mission_zone'):
        self.runner.os_order_execute.reset_mock()
        self.assertEqual(self.finish_mission(result), 1)
        self.runner.os_order_execute.assert_called_once_with(
            recon_scan=expected, submarine_call=result != 'pinned_at_archive_zone')

    def test_unfinished_daily_recon_precedes_search(self):
        flow = Mock()
        flow.attach_mock(self.runner.os_order_execute, 'order')
        flow.attach_mock(self.runner.run_auto_search, 'search')
        self.assert_recon(True)
        self.assertEqual([call[0] for call in flow.mock_calls], ['order', 'search'])
        self.assertEqual(self.data['OpsiScheduling']['Storage']['Storage']['Unrelated'], 'keep')

    def test_safe_port_special_and_archive_skip_recon(self):
        for kind in ('safe', 'port', 'special', 'archive'):
            with self.subTest(kind=kind):
                self.runner.zone = self.runner.name_to_zone(0 if kind == 'port' else 44)
                self.runner.is_zone_name_hidden = kind == 'safe'
                self.runner.is_in_special_zone.return_value = kind == 'special'
                self.assert_recon(False, 'pinned_at_archive_zone' if kind == 'archive' else 'pinned_at_mission_zone')

    def test_shared_mission_flow_does_not_enable_other_tasks_recon(self):
        for task in ('OpsiArchive', 'OpsiMonthBoss', 'OpsiCrossMonth', 'OpsiExplore', 'OpsiScheduling'):
            with self.subTest(task=task):
                self.runner.config.task.command = task
                self.assert_recon(False)

    def test_current_month_monthly_completion_skips_recon_even_when_disabled(self):
        deep_set(self.data, 'OpsiExplore.OpsiExplore.ExploreProgress', '已完成百分之100.00')
        deep_set(self.data, 'OpsiExplore.OpsiExplore.MeowfficerCleanupState', {'reset': RESET.isoformat()})
        self.assert_recon(False)

    def test_current_month_smart_completion_skips_recon(self):
        for phase in ('cleanup', 'done'):
            with self.subTest(phase=phase):
                deep_set(self.data, 'OpsiScheduling.Storage.Storage.SmartExplore',
                         {'reset': RESET.isoformat(), 'phase': phase, 'next': [30, 7, 38]})
                self.assert_recon(False)

    def test_previous_month_completion_does_not_skip_recon(self):
        deep_set(self.data, 'OpsiExplore.OpsiExplore.ExploreProgress', '已完成百分之100.00')
        deep_set(self.data, 'OpsiExplore.OpsiExplore.MeowfficerCleanupState', {'reset': OLD_RESET})
        deep_set(self.data, 'OpsiScheduling.Storage.Storage.SmartExplore', {'reset': OLD_RESET, 'phase': 'done'})
        self.assert_recon(True)

    def test_monthly_completion_without_month_marker_still_checks_recon(self):
        deep_set(self.data, 'OpsiExplore.OpsiExplore.ExploreProgress', '已完成百分之100.00')
        self.assert_recon(True)

    def test_missing_or_invalid_smart_state_still_checks_recon(self):
        for storage in (None, [], 'invalid', {}, {'SmartExplore': 'invalid'}):
            with self.subTest(storage=storage):
                deep_set(self.data, 'OpsiScheduling.Storage.Storage', storage)
                self.assert_recon(True)

    def test_already_at_mission_zone_checks_recon_after_refresh(self):
        flow = Mock()
        flow.attach_mock(self.runner.globe_goto, 'refresh')
        flow.attach_mock(self.runner.os_order_execute, 'order')
        flow.attach_mock(self.runner.run_auto_search, 'search')
        self.assert_recon(True, 'already_at_mission_zone')
        self.assertEqual([call[0] for call in flow.mock_calls], ['refresh', 'order', 'search'])
        self.runner.globe_goto.assert_called_once_with(self.runner.zone, refresh=True)

    def test_initial_search_also_recons_before_scanning(self):
        flow = Mock()
        flow.attach_mock(self.runner.os_order_execute, 'order')
        with patch.object(OSMap, 'run_first_auto_search') as search:
            flow.attach_mock(search, 'search')
            self.runner.run_first_auto_search()
        self.runner.os_order_execute.assert_called_once_with(recon_scan=True, submarine_call=False)
        self.assertEqual([call[0] for call in flow.mock_calls], ['order', 'search'])

    def test_other_tasks_initial_search_keeps_existing_behavior(self):
        self.runner.config.task.command = 'OpsiExplore'
        with patch.object(OSMap, 'run_first_auto_search') as search:
            self.runner.run_first_auto_search()
        self.runner.os_order_execute.assert_not_called()
        search.assert_called_once_with()

    def test_existing_order_scan_clicks_only_the_lit_button(self):
        active = load_image(ORDER_SCAN.file)
        disabled = np.full_like(active, 101)
        for image, expected in ((active, True), (disabled, False)):
            with self.subTest(active=expected):
                self.runner.order_enter = Mock()
                self.runner.order_quit = Mock()
                self.runner.loop = lambda: iter((None, None))
                self.runner.is_in_map = Mock(side_effect=[False, True])
                self.runner.is_in_map_order = Mock(return_value=True)
                self.runner.appear = lambda button: button.appear_on(image)
                self.runner.appear_then_click = Mock(return_value=True)
                with patch('module.os_handler.map_order.Timer') as timer:
                    timer.return_value.start.return_value = timer.return_value
                    timer.return_value.reached.return_value = True
                    self.assertEqual(self.runner.order_execute(ORDER_SCAN), expected)
                if expected:
                    self.runner.appear_then_click.assert_called_once_with(ORDER_SCAN, interval=3)
                else:
                    self.runner.appear_then_click.assert_not_called()
                    self.runner.order_quit.assert_called_once_with()

    def test_unavailable_mission_continues_other_daily_missions(self):
        for accepted in (False, True):
            for skip_siren in (False, True):
                with self.subTest(accepted=accepted, skip_siren=skip_siren):
                    self.runner.os_mission_overview_accept = Mock(side_effect=[accepted, True])
                    self.runner.config.OpsiDaily_SkipSirenResearchMission = skip_siren
                    self.runner.config.task_delay.reset_mock()
                    self.runner.run_auto_search.reset_mock()
                    self.set_next_missions(['mission_zone_unavailable', 'pinned_at_mission_zone', False])
                    self.runner.os_daily()
                    self.runner.run_auto_search.assert_called_once()
                    self.assertEqual(self.runner.os_get_next_mission.call_args_list[1].kwargs,
                                     dict(skip_siren_mission=skip_siren, skip_unavailable=True, mission_index=1))
                    self.runner.config.task_delay.assert_called_once_with(server_update=True)
                    self.runner.config.task_stop.assert_not_called()

    def test_lock_between_two_available_missions_does_not_abort(self):
        self.set_next_missions(['pinned_at_mission_zone', 'mission_zone_unavailable',
                                'pinned_at_mission_zone', False])
        self.assertEqual(self.runner.os_finish_daily_mission(), 2)
        self.assertEqual(self.runner.run_auto_search.call_count, 2)
        self.runner.config.task_delay.assert_not_called()

    def test_locked_template_reaches_task_entry_for_next_day_deferral(self):
        self.prepare_mission_entry()
        with self.assertRaises(OSZoneLockedError):
            self.runner.os_get_next_mission(skip_unavailable=True)
        self.runner.device.click.assert_not_called()
        self.runner.ensure_no_zone_pinned.assert_not_called()
        self.runner.os_globe_goto_map.assert_not_called()
        self.assertIsNone(deep_get(self.data, 'OpsiDaily.OpsiDaily.DeferredMissions'))
        self.assertIsNone(deep_get(self.data, 'OpsiDaily.Scheduler.NextRun'))
        self.runner.config.task_delay.assert_not_called()

    def test_same_day_retry_skips_entering_only_the_deferred_zone(self):
        self.prepare_mission_entry()
        self.runner._os_defer_mission_zone(self.runner.name_to_zone(44))
        self.runner.globe_enter = Mock()
        self.assertEqual(self.runner.os_get_next_mission(skip_unavailable=True), 'mission_zone_unavailable')
        self.runner.globe_enter.assert_not_called()
        self.runner.get_globe_pinned_zone.return_value = self.runner.name_to_zone(42)
        self.assertEqual(self.runner.os_get_next_mission(skip_unavailable=True), 'pinned_at_mission_zone')
        self.runner.globe_enter.assert_called_once_with(zone=self.runner.name_to_zone(42))

    def test_next_day_retries_and_defers_only_the_still_locked_zone(self):
        self.prepare_mission_entry()
        self.runner._os_defer_mission_zone(self.runner.name_to_zone(44))
        tomorrow = datetime(2026, 10, 5)
        with (patch('module.os_handler.mission.current_time', return_value=UPDATE),
              patch('module.os_handler.mission.get_server_next_update', return_value=tomorrow),
              patch.object(self.runner, 'globe_enter', side_effect=OSExploreError) as enter):
            self.assertEqual(self.runner.os_get_next_mission(skip_unavailable=True), 'mission_zone_unavailable')
            enter.assert_called_once_with(zone=self.runner.name_to_zone(44))
        self.assertEqual(deep_get(self.data, 'OpsiDaily.OpsiDaily.DeferredMissions'),
                         {'until': tomorrow.isoformat(), 'zones': [44]})
        self.assertIsNone(deep_get(self.data, 'OpsiDaily.Scheduler.NextRun'))

    def test_submitting_a_completed_task_resets_the_skipped_row_index(self):
        self.prepare_mission_entry()
        self.runner._os_mission_submitted = True
        self.runner.globe_enter = Mock()
        self.assertEqual(self.runner.os_get_next_mission(skip_unavailable=True, mission_index=2),
                         'pinned_at_mission_zone')
        self.runner._os_find_checkout_offset_skip_monthly_boss.assert_called_once_with(
            (-20, -20, 20, 20), skip=0)
        self.assertEqual(self.runner._os_mission_index, 0)

    def test_full_queue_with_only_deferred_missions_does_not_reaccept_forever(self):
        self.runner.os_mission_overview_accept.return_value = False
        self.set_next_missions(['mission_zone_unavailable', 'mission_zone_unavailable', False])
        self.runner.os_daily()
        self.runner.os_mission_overview_accept.assert_called_once()
        self.runner.run_auto_search.assert_not_called()
        self.runner.config.task_stop.assert_not_called()

    def test_refresh_failure_skips_one_mission_and_continues(self):
        self.set_next_missions(['already_at_mission_zone', 'pinned_at_mission_zone', False])
        self.runner.globe_goto.side_effect = OSExploreError
        self.assertEqual(self.runner.os_finish_daily_mission(), 1)
        self.runner.run_auto_search.assert_called_once()
        self.assertEqual(deep_get(self.data, 'OpsiDaily.OpsiDaily.DeferredMissions')['zones'], [44])

    def test_other_tasks_do_not_defer_unavailable_missions(self):
        self.prepare_mission_entry()
        self.runner.config.task.command = 'OpsiArchive'
        self.runner.globe_enter = Mock(side_effect=OSExploreError)
        with self.assertRaises(OSExploreError):
            self.runner.os_get_next_mission(skip_unavailable=True)
        self.assertIsNone(deep_get(self.data, 'OpsiDaily.OpsiDaily.DeferredMissions'))

    def test_corrupt_or_expired_records_do_not_skip_missions(self):
        for state in (None, [], {}, {'until': 'bad'}, {'until': UPDATE.isoformat(), 'zones': None},
                      {'until': UPDATE.isoformat() + '+08:00', 'zones': [44]},
                      {'until': NOW.isoformat(), 'zones': [44]}):
            with self.subTest(state=state):
                deep_set(self.data, 'OpsiDaily.OpsiDaily.DeferredMissions', state)
                self.assertEqual(self.runner._os_deferred_mission_zones(), set())

    def test_cleanup_skips_the_locked_zone_and_cleans_the_other_zone(self):
        self.runner.zone = self.runner.name_to_zone(0)
        deep_set(self.data, 'OpsiDaily.OpsiDaily.MissionZones', '44 42')

        def enter(zone, **kwargs):
            if zone.zone_id == 44:
                raise OSExploreError

        self.runner.globe_goto.side_effect = enter
        self.runner._os_daily_retrieve_events = Mock()
        with patch('module.os.tasks.daily.get_os_reset_remain', return_value=0):
            # 调用真实清理流程，屏蔽设备交互。
            del self.runner.os_daily_clear_all_mission_zones
            self.runner.os_daily_clear_all_mission_zones()
        self.runner.run_auto_search.assert_called_once_with(question=False, rescan=False)
        self.assertEqual(deep_get(self.data, 'OpsiDaily.OpsiDaily.MissionZones'), '44')
        self.runner.config.task_delay.assert_not_called()

    def test_unexpected_errors_and_action_point_limits_are_not_suppressed(self):
        for error in (GameStuckError(), RuntimeError('识别失败'), ActionPointLimit()):
            with self.subTest(error=type(error).__name__):
                self.runner.os_finish_daily_mission = Mock(side_effect=error)
                with self.assertRaises(type(error)) as raised:
                    self.runner.os_daily()
                self.assertIs(raised.exception, error)
                self.runner.config.task_delay.assert_not_called()
                self.runner.ensure_no_zone_pinned.assert_not_called()

    def test_recovery_failure_does_not_mark_daily_done(self):
        self.prepare_mission_entry()
        self.runner.globe_enter = Mock(side_effect=OSExploreError)
        self.runner.os_globe_goto_map.side_effect = GameStuckError
        with self.assertRaises(GameStuckError):
            self.runner.os_get_next_mission(skip_unavailable=True)
        self.runner.config.task_delay.assert_not_called()
        self.runner.config.task_stop.assert_not_called()

    def test_normal_daily_completion_keeps_existing_delay(self):
        self.runner.os_finish_daily_mission = Mock(return_value=0)
        self.runner.os_daily()
        self.runner.config.task_delay.assert_called_once_with(server_update=True)
        self.runner.ensure_no_zone_pinned.assert_not_called()
        self.runner.config.task_stop.assert_not_called()

    def test_claiming_reward_marks_the_list_as_shifted(self):
        images = [load_image(button.file) for button in (MISSION_FINISH, MISSION_CHECKOUT)]
        self.runner.device = SimpleNamespace(image=images[0])

        def frames():
            for image in images:
                self.runner.device.image = image
                yield image

        self.runner.loop = frames
        self.runner.is_in_os_mission = Mock(return_value=True)
        self.runner.appear = lambda button, offset=0: button.match(self.runner.device.image, offset=offset)
        self.runner.match_template_color = lambda button, **kwargs: button.match_template_color(
            self.runner.device.image, **kwargs)
        self.runner.appear_then_click = Mock(side_effect=lambda button, **kwargs: button is MISSION_FINISH)
        self.assertEqual(self.runner.os_mission_enter(), (-20, -20, 20, 20))
        self.assertTrue(self.runner._os_mission_submitted)
        self.runner.appear_then_click.assert_any_call(MISSION_FINISH, offset=(-20, -20, 20, 20), interval=2)

    def test_deferred_zones_survive_config_reload_without_changing_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'daily-test.json'
            path.write_text(Path('config/template.json').read_text(encoding='utf-8'), encoding='utf-8')
            with (patch('module.config.config.filepath_config', return_value=str(path)),
                  patch('module.config.config_updater.filepath_config', return_value=str(path))):
                self.runner.config = AzurLaneConfig('daily-test', task='OpsiDaily')
                next_run = self.runner.config.cross_get('OpsiDaily.Scheduler.NextRun')
                self.runner._os_defer_mission_zone(self.runner.name_to_zone(44))
                self.runner._os_defer_mission_zone(self.runner.name_to_zone(42))
                self.runner.config = AzurLaneConfig('daily-test', task='OpsiDaily')
                self.assertEqual(self.runner._os_deferred_mission_zones(), {42, 44})
                self.assertEqual(self.runner.config.cross_get('OpsiDaily.Scheduler.NextRun'), next_run)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['OpsiDaily']['OpsiDaily']
                                 ['DeferredMissions'], {'until': UPDATE.isoformat(), 'zones': [42, 44]})


class TestOpsiDailyMissionList(unittest.TestCase):
    """使用原按钮模板和合成列表，离线验证行定位与翻页，不操作游戏。"""

    def setUp(self):
        self.runner = OperationSiren.__new__(OperationSiren)
        self.runner.device = SimpleNamespace(image=None, drag=Mock())
        self.runner.image_crop = lambda area, copy=True: crop(self.runner.device.image, area, copy=copy)
        self.runner.appear = lambda button, offset=0: button.match(self.runner.device.image, offset=offset)
        self.runner.match_template_color = lambda button, **kwargs: button.match_template_color(
            self.runner.device.image, **kwargs)
        self.stable = Mock()
        self.stable.reached.return_value = True
        self.timeout = Mock()
        self.timeout.reached.return_value = False
        timers = patch('module.os_handler.mission.Timer', side_effect=[self.stable, self.timeout])
        timers.start()
        self.addCleanup(timers.stop)

    def prepare_list(self, count, monthly=(), animate=False):
        content = np.full((max(720, count * 110 + 250), 1280, 3), 45, dtype=np.uint8)
        rng = np.random.default_rng(42)
        checkout = crop(load_image(MISSION_CHECKOUT.file), MISSION_CHECKOUT.area)
        boss = crop(load_image(MISSION_MONTHLY_BOSS.file), MISSION_MONTHLY_BOSS.area)
        for index in range(count):
            y = MISSION_CHECKOUT.area[1] + index * 110
            # 各行文字区域使用不同纹理，模拟任务内容以确认滚动位移。
            content[y - 35:y + 45, 600:1000] = rng.integers(60, 180, (80, 400, 3), dtype=np.uint8)
            x = MISSION_CHECKOUT.area[0]
            content[y:y + checkout.shape[0], x:x + checkout.shape[1]] = checkout
            if index in monthly:
                x1, y1, x2, y2 = MISSION_MONTHLY_BOSS.area
                content[y1 + index * 110:y2 + index * 110, x1:x2] = boss
        maximum = max(0, MISSION_CHECKOUT.area[3] + (count - 1) * 110 - 650)
        position = 0
        pending = []

        def screenshot(scroll):
            image = np.full((720, 1280, 3), 45, dtype=np.uint8)
            image[170:650] = content[170 + scroll:650 + scroll]
            return image

        def drag(*args, **kwargs):
            nonlocal position
            target = min(position + 220, maximum)
            if animate and target > position:
                pending.append(screenshot(position + 20))
            position = target

        def frames():
            for _ in range(30):
                self.runner.device.image = pending.pop(0) if pending else screenshot(position)
                yield self.runner.device.image
            self.fail('任务列表未在有限帧内完成选择')

        self.runner.device.drag.side_effect = drag
        self.runner.loop = frames
        self.runner.device.image = screenshot(0)

    def choose(self, skip):
        return self.runner._os_find_checkout_offset_skip_monthly_boss((-20, -20, 20, 20), skip=skip)

    def test_deferred_rows_fill_first_page_but_next_mission_is_selected(self):
        self.prepare_list(8)
        self.assertEqual(self.choose(4), (-20, 200, 20, 240))
        self.runner.device.drag.assert_called_once_with((820, 550), (820, 330), name='MISSION_SCROLL')

    def test_second_scroll_keeps_overlapping_rows_in_the_correct_order(self):
        self.prepare_list(8)
        self.assertEqual(self.choose(6), (-20, 286, 20, 326))
        self.assertEqual(self.runner.device.drag.call_count, 2)

    def test_monthly_boss_is_not_counted_as_a_deferred_mission(self):
        self.prepare_list(8, monthly=(2,))
        self.assertEqual(self.choose(4), (-20, 310, 20, 350))

    def test_original_first_row_selection_still_skips_monthly_boss(self):
        self.prepare_list(2, monthly=(0,))
        self.assertEqual(self.choose(0), (-20, 90, 20, 130))
        self.runner.device.drag.assert_not_called()

    def test_all_rows_deferred_confirms_bottom_instead_of_looping(self):
        self.prepare_list(9)
        self.assertIsNone(self.choose(9))
        self.assertEqual(self.runner.device.drag.call_count, 4)

    def test_partial_scroll_frame_is_not_used_to_advance_the_row_index(self):
        self.prepare_list(8, animate=True)
        self.assertEqual(self.choose(4), (-20, 200, 20, 240))
        self.runner.device.drag.assert_called_once()

    def test_unrecognized_scroll_does_not_silently_complete_remaining_missions(self):
        self.prepare_list(8)
        self.runner.device.drag.side_effect = lambda *args, **kwargs: self.runner.device.image.fill(0)

        def frames():
            for _ in range(3):
                yield self.runner.device.image

        self.runner.loop = frames
        self.timeout.reached.return_value = True
        with self.assertRaises(MapDetectionError):
            self.choose(4)


if __name__ == '__main__':
    unittest.main()
