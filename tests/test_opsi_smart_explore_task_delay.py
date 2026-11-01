"""智能开荒期间的当天让位，使用真实任务队列及临时配置，不连接设备。"""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.base.utils import load_image
from module.campaign.os_run import OSCampaignRun
from module.config.config import AzurLaneConfig, Function, TaskEnd
from module.config.deep import deep_set
from module.os.assets import ZONE_LOCKED
from module.os.globe_operation import GlobeOperation, OSExploreError, OSZoneLockedError
from module.os.operation_siren import OperationSiren
from module.os.tasks.shop import OpsiShop
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow
from module.os.tasks.smart_explore import SMART_EXPLORE_DELAY_TASKS, SMART_EXPLORE_ROUTES


NOW = datetime(2026, 10, 4, 8)
UPDATE = datetime(2026, 10, 5)
RESET = datetime(2026, 11, 1)
ENTRIES = {'OpsiDaily': 'opsi_daily', 'OpsiShop': 'opsi_shop',
           'OpsiPreventActionPointOverflow': 'opsi_prevent_action_point_overflow'}
ORDER = ['OpsiDaily', 'OpsiShop', 'OpsiPreventActionPointOverflow', 'OpsiScheduling']


class TestSmartExploreTaskDelay(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'opsi-delay-test.json'
        data = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
        for groups in data.values():
            if 'Scheduler' in groups:
                groups['Scheduler']['Enable'] = False
        # 重启任务由配置强制启用；本组测试将它安排在当前测试窗口之后。
        data['Restart']['Scheduler']['NextRun'] = (NOW + timedelta(hours=20)).isoformat()
        for task in ORDER + ['OpsiExplore']:
            data[task]['Scheduler'].update(Enable=True, NextRun=(NOW - timedelta(hours=1)).isoformat())
            data[task]['Storage']['Storage'] = {'Unrelated': 'keep'}
        data['OpsiExplore']['Scheduler']['NextRun'] = (NOW + timedelta(days=2)).isoformat()
        data['OpsiExplore']['Scheduler']['Enable'] = False
        data['OpsiScheduling']['OpsiSmartExplore']['Enable'] = True
        data['OpsiScheduling']['OpsiScheduling']['UseSmartSchedulingOperationCoinsPreserve'] = True
        data['OpsiScheduling']['Storage']['Storage']['SmartExplore'] = {
            'reset': RESET.isoformat(), 'phase': 'explore', 'next': [10, 0, 0],
        }
        data['OpsiShop']['OpsiShop']['DisableBeforeDate'] = 0
        data['General']['YukikazeTaskManager']['TaskPriorityAdjustment'] = (
            'Restart > Commission > OpsiDaily > OpsiShop > OpsiPreventActionPointOverflow'
            ' > Research > OpsiScheduling > Main'
        )
        self.path.write_text(json.dumps(data), encoding='utf-8')
        for target, value in (
            ('module.config.config.filepath_config', str(self.path)),
            ('module.config.config_updater.filepath_config', str(self.path)),
            ('module.config.config.current_time', NOW),
            ('module.config.utils.current_time', NOW),
            ('module.os.tasks.shop.current_time', NOW),
            ('module.os.tasks.smart_explore.get_os_next_reset', RESET),
            ('module.os.globe_operation.get_os_next_reset', RESET),
            ('module.os.tasks.smart_explore.get_server_next_update', UPDATE),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(AzurLaneConfig, 'is_hoarding_task', False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = AzurLaneConfig('opsi-delay-test', task='OpsiDaily')
        self.original_priority = self.config.SCHEDULER_PRIORITY
        self.original_times = {task: self.config.cross_get(f'{task}.Scheduler.NextRun') for task in ORDER}
        self.campaign = SimpleNamespace(**{method: Mock() for method in
                                          ('os_daily', 'os_shop', 'os_prevent_action_point_overflow')})
        self.runner = OSCampaignRun.__new__(OSCampaignRun)
        self.runner.config = self.config
        self.runner.load_campaign = Mock(return_value=self.campaign)
        self.runner._run_opsi_task_with_ap_overflow_guard = Mock(side_effect=lambda run: run(self.campaign))

    def bind(self, task):
        self.config.task = Function(self.config.data[task])
        self.config.bind(self.config.task)

    def run_task(self, task):
        self.bind(task)
        return getattr(self.runner, ENTRIES[task])()

    def postpone(self, tasks=ORDER[:-1]):
        for task in tasks:
            with self.assertRaises(TaskEnd):
                self.run_task(task)

    def pending(self):
        self.config.get_next_task()
        return [task.command for task in self.config.pending_task]

    def complete(self):
        self.config.cross_set('OpsiExplore.OpsiExplore.ExploreProgress', '已完成百分之100.00')
        self.config.cross_set('OpsiExplore.OpsiExplore.MeowfficerCleanupState',
                              {'reset': RESET.isoformat(), 'phase': 'done'})

    def suppressed(self, count=30, reset=RESET):
        self.config.cross_set('OpsiScheduling.Storage.Storage.SuppressedZones',
                              {'reset': reset.isoformat(), 'count': count})

    def route_progress(self, count):
        indexes = []
        for route in SMART_EXPLORE_ROUTES:
            index = 0
            while count and index < len(route):
                count -= route[index] >= 11
                index += 1
            indexes.append(index)
        self.config.cross_set('OpsiScheduling.Storage.Storage.SmartExplore.next', indexes)

    def forbid_smart_progress_read(self):
        get = self.config.cross_get

        def read(keys, default=None):
            if keys == 'OpsiScheduling.Storage.Storage.SmartExplore':
                self.fail('已完成或未让位的任务不应读取智能开荒断点')
            return get(keys, default)

        patcher = patch.object(self.config, 'cross_get', side_effect=read)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_all_three_entries_postpone_before_game_initialization_and_keep_settings(self):
        self.postpone()
        self.runner.load_campaign.assert_not_called()
        self.runner._run_opsi_task_with_ap_overflow_guard.assert_not_called()
        for task in SMART_EXPLORE_DELAY_TASKS:
            self.assertEqual(self.config.cross_get(f'{task}.Storage.Storage'),
                             {'Unrelated': 'keep', 'SmartExploreDelay': UPDATE.isoformat()})
            self.assertEqual(self.config.cross_get(f'{task}.Scheduler.NextRun'), self.original_times[task])
            self.assertTrue(self.config.is_task_enabled(task))
        self.assertEqual(self.config.SCHEDULER_PRIORITY, self.original_priority)

    def test_original_order_is_used_before_the_first_check(self):
        self.forbid_smart_progress_read()
        self.assertEqual(self.pending(), ORDER)

    def test_only_checked_tasks_move_after_scheduling(self):
        self.postpone(['OpsiDaily'])
        self.assertEqual(self.pending(), ['OpsiShop', 'OpsiPreventActionPointOverflow', 'OpsiScheduling', 'OpsiDaily'])
        self.postpone(['OpsiShop', 'OpsiPreventActionPointOverflow'])
        self.assertEqual(self.pending(), ['OpsiScheduling'] + ORDER[:-1])

    def test_other_tasks_and_already_lower_priority_tasks_keep_their_order(self):
        for task in ('Commission', 'Research', 'Main'):
            self.config.cross_set_many({f'{task}.Scheduler.Enable': True,
                                        f'{task}.Scheduler.NextRun': NOW - timedelta(hours=1)})
        self.postpone()
        self.assertEqual(self.pending(), ['Commission', 'Research', 'OpsiScheduling'] + ORDER[:-1] + ['Main'])
        self.config.cross_set('General.YukikazeTaskManager.TaskPriorityAdjustment',
                              'Commission > OpsiDaily > OpsiScheduling > Research > OpsiShop'
                              ' > OpsiPreventActionPointOverflow > Main')
        self.assertEqual(self.pending(), ['Commission', 'OpsiScheduling', 'OpsiDaily', 'Research',
                                         'OpsiShop', 'OpsiPreventActionPointOverflow', 'Main'])

    def test_system_restart_keeps_priority_over_smart_exploration(self):
        self.postpone()
        self.config.cross_set('Restart.Scheduler.NextRun', NOW - timedelta(seconds=1))
        self.assertEqual(self.pending(), ['Restart', 'OpsiScheduling'] + ORDER[:-1])

    def test_waiting_scheduler_holds_tasks_without_changing_saved_times(self):
        self.postpone()
        later = NOW + timedelta(minutes=27)
        self.config.cross_set('OpsiScheduling.Scheduler.NextRun', later)
        self.assertEqual(self.pending(), [])
        waiting = {task.command: task.next_run for task in self.config.waiting_task}
        for task in SMART_EXPLORE_DELAY_TASKS:
            self.assertEqual(waiting[task], later + timedelta(seconds=1))
            self.assertEqual(self.config.cross_get(f'{task}.Scheduler.NextRun'), self.original_times[task])

    def test_wait_never_carries_temporary_priority_into_the_next_day(self):
        self.postpone()
        self.config.cross_set('OpsiScheduling.Scheduler.NextRun', UPDATE + timedelta(minutes=30))
        self.assertEqual(self.pending(), [])
        for task in self.config.waiting_task:
            if task.command in SMART_EXPLORE_DELAY_TASKS:
                self.assertEqual(task.next_run, UPDATE)
        with (patch('module.config.config.current_time', return_value=UPDATE + timedelta(minutes=1)),
              patch('module.os.tasks.smart_explore.get_server_next_update', return_value=UPDATE + timedelta(days=1))):
            self.forbid_smart_progress_read()
            self.assertEqual(self.pending(), ORDER[:-1])

    def test_monthly_completion_releases_waiting_tasks_without_reading_smart_progress(self):
        self.postpone()
        self.config.cross_set('OpsiScheduling.Scheduler.NextRun', NOW + timedelta(minutes=27))
        self.complete()
        self.forbid_smart_progress_read()
        self.assertEqual(self.pending(), ORDER[:-1])
        for task in SMART_EXPLORE_DELAY_TASKS:
            self.run_task(task)
        self.campaign.os_daily.assert_called_once_with()
        self.campaign.os_shop.assert_called_once_with()
        self.campaign.os_prevent_action_point_overflow.assert_called_once_with()

    def test_running_scheduling_yields_only_after_exploration_finishes(self):
        self.postpone()
        self.bind('OpsiScheduling')
        self.assertFalse(self.config.task_switched())
        self.complete()
        self.assertTrue(self.config.task_switched())

    def test_current_completed_checkpoint_allows_tasks_but_old_checkpoint_does_not(self):
        for phase in ('cleanup', 'done'):
            self.config.cross_set('OpsiScheduling.Storage.Storage.SmartExplore',
                                  {'reset': RESET.isoformat(), 'phase': phase})
            for task in SMART_EXPLORE_DELAY_TASKS:
                self.run_task(task)
        self.config.cross_set('OpsiScheduling.Storage.Storage.SmartExplore.reset', '2026-10-01T00:00:00')
        self.postpone()

    def test_stale_monthly_100_percent_does_not_skip_new_month_exploration(self):
        self.config.cross_set('OpsiExplore.OpsiExplore.ExploreProgress', '已完成百分之100.00')
        self.config.cross_set('OpsiExplore.OpsiExplore.MeowfficerCleanupState',
                              {'reset': '2026-10-01T00:00:00', 'phase': 'done'})
        self.postpone()

    def test_29_suppressed_zones_still_waits_for_exploration(self):
        self.route_progress(29)
        self.postpone()

    def test_30_or_more_confirmed_zones_release_all_three_tasks(self):
        self.postpone()
        for count in (30, 31, 34, 72):
            with self.subTest(count=count):
                self.suppressed(count)
                self.assertEqual(self.pending(), ORDER)
                for task in SMART_EXPLORE_DELAY_TASKS:
                    self.run_task(task)
        self.assertIsNone(self.config.cross_get('OpsiExplore.OpsiExplore.MeowfficerCleanupState'))

    def test_route_checkpoints_count_normal_zones_without_ports(self):
        for count in (30, 31):
            with self.subTest(count=count):
                self.route_progress(count)
                for task in SMART_EXPLORE_DELAY_TASKS:
                    self.run_task(task)

    def test_confirmed_count_skips_further_smart_progress_reads_and_survives_reload(self):
        self.suppressed(34)
        self.config = AzurLaneConfig('opsi-delay-test', task='OpsiDaily')
        self.runner.config = self.config
        self.forbid_smart_progress_read()
        for task in SMART_EXPLORE_DELAY_TASKS:
            self.run_task(task)

    def test_stale_or_invalid_suppression_count_cannot_release_tasks(self):
        for state in ({'reset': '2026-10-01T00:00:00', 'count': 34},
                      {'reset': RESET.isoformat(), 'count': 29},
                      {'reset': RESET.isoformat(), 'count': 73},
                      {'reset': RESET.isoformat(), 'count': '34'}, None):
            with self.subTest(state=state):
                self.config.cross_set('OpsiScheduling.Storage.Storage.SuppressedZones', state)
                self.postpone()

    def test_locked_zone_delays_only_the_current_task_until_next_day(self):
        self.suppressed(34)
        for task in SMART_EXPLORE_DELAY_TASKS:
            with self.subTest(task=task):
                before = {name: self.config.cross_get(f'{name}.Scheduler.NextRun') for name in ORDER}
                campaign_method = getattr(self.campaign, ENTRIES[task].replace('opsi_', 'os_', 1))
                campaign_method.side_effect = OSZoneLockedError('周边海域未压制')
                with self.assertRaises(TaskEnd):
                    self.run_task(task)
                self.assertEqual(self.config.cross_get(f'{task}.Scheduler.NextRun'), UPDATE)
                self.assertEqual(self.config.cross_get(f'{task}.Storage.Storage.ZoneLockedUntil'), UPDATE.isoformat())
                for other in ORDER:
                    if other != task:
                        self.assertEqual(self.config.cross_get(f'{other}.Scheduler.NextRun'), before[other])
                campaign_method.side_effect = None
                campaign_method.reset_mock()
                # 即使行动力重排误将任务唤起，当天也不再进入海域。
                with self.assertRaises(TaskEnd):
                    self.run_task(task)
                campaign_method.assert_not_called()

    def test_locked_zone_delay_expires_the_next_day(self):
        self.suppressed()
        self.config.cross_set('OpsiDaily.Storage.Storage.ZoneLockedUntil', UPDATE.isoformat())
        with patch('module.os.tasks.smart_explore.get_server_next_update', return_value=UPDATE + timedelta(days=1)):
            self.run_task('OpsiDaily')
        self.campaign.os_daily.assert_called_once_with()

    def test_supplied_locked_screen_defers_each_task_through_the_real_entry(self):
        self.suppressed(34)
        image = load_image(str(Path(__file__).parent / 'fixtures/opsi_zone_locked_34.png'))
        campaign = OperationSiren.__new__(OperationSiren)
        campaign.config = self.config
        campaign.device = SimpleNamespace(image=image, click=Mock())
        campaign.loop = lambda: iter((image,))
        campaign.is_in_map = Mock(return_value=False)
        campaign.is_zone_pinned = Mock(return_value=True)
        campaign.get_zone_pinned_name = Mock(return_value='DANGEROUS')
        campaign.appear = lambda button, offset=0: button.match(image, offset=offset)
        campaign.update_prevent_action_point_overflow_schedule = Mock(
            side_effect=lambda enable: self.config.cross_set(
                'OpsiPreventActionPointOverflow.Scheduler.Enable', enable))
        for method in ('os_daily', 'os_shop', 'os_prevent_action_point_overflow'):
            setattr(campaign, method, lambda: campaign.globe_enter(campaign.name_to_zone(24)))
        self.runner.load_campaign.return_value = campaign
        del self.runner._run_opsi_task_with_ap_overflow_guard
        for task in SMART_EXPLORE_DELAY_TASKS:
            with self.subTest(task=task), self.assertRaises(TaskEnd):
                self.run_task(task)
            self.assertEqual(self.config.cross_get(f'{task}.Scheduler.NextRun'), UPDATE)
            self.assertTrue(self.config.is_task_enabled('OpsiPreventActionPointOverflow'))
        campaign.device.click.assert_not_called()

    def test_other_navigation_errors_keep_existing_recovery(self):
        self.suppressed()
        for task in SMART_EXPLORE_DELAY_TASKS:
            method = getattr(self.campaign, ENTRIES[task].replace('opsi_', 'os_', 1))
            method.side_effect = OSExploreError('未确认进入，未出现锁定提示')
            with self.assertRaises(OSExploreError):
                self.run_task(task)
            self.assertIsNone(self.config.cross_get(f'{task}.Storage.Storage.ZoneLockedUntil'))

    def test_action_point_rescheduling_keeps_the_locked_zone_deadline(self):
        task = 'OpsiPreventActionPointOverflow'
        self.config.cross_set(f'{task}.Storage.Storage.ZoneLockedUntil', UPDATE.isoformat())
        campaign = OpsiPreventActionPointOverflow.__new__(OpsiPreventActionPointOverflow)
        campaign.config = self.config
        with patch.object(campaign, '_get_prevent_action_point_overflow_thresholds', return_value=(200, 100)):
            campaign.update_prevent_action_point_overflow_schedule(current_ap=200)
        self.assertEqual(self.config.cross_get(f'{task}.Scheduler.NextRun'), UPDATE)

    def test_supplied_lock_and_suppression_count_are_recognized_offline(self):
        campaign = OperationSiren.__new__(OperationSiren)
        campaign.config = self.config
        image = load_image(str(Path(__file__).parent / 'fixtures/opsi_zone_locked_34.png'))
        self.assertTrue(ZONE_LOCKED.match(image, offset=(20, 20)))
        campaign.device = SimpleNamespace(image=image)
        campaign.record_globe_suppressed_zones()
        self.assertIsNone(self.config.cross_get('OpsiScheduling.Storage.Storage.SuppressedZones'))
        campaign.device.image = image.copy()
        campaign.record_globe_suppressed_zones()
        self.assertEqual(self.config.cross_get('OpsiScheduling.Storage.Storage.SuppressedZones'),
                         {'reset': RESET.isoformat(), 'count': 34})
        self.forbid_smart_progress_read()
        for task in SMART_EXPLORE_DELAY_TASKS:
            self.run_task(task)

    def test_count_confirmation_requires_fresh_matching_frames_and_stops_after_30(self):
        campaign = OperationSiren.__new__(OperationSiren)
        campaign.config = self.config
        image = load_image(str(Path(__file__).parent / 'fixtures/opsi_zone_locked_34.png'))
        campaign.device = SimpleNamespace(image=image)
        with patch('module.os.globe_operation.Digit.ocr', side_effect=[30, 31, 31]) as ocr:
            campaign.record_globe_suppressed_zones()
            campaign.record_globe_suppressed_zones()
            self.assertEqual(ocr.call_count, 1)
            campaign.device.image = image.copy()
            campaign.record_globe_suppressed_zones()
            self.assertIsNone(self.config.cross_get('OpsiScheduling.Storage.Storage.SuppressedZones'))
            campaign.device.image = image.copy()
            campaign.record_globe_suppressed_zones()
            campaign.device.image = image.copy()
            campaign.record_globe_suppressed_zones()
            self.assertEqual(ocr.call_count, 3)
        self.assertEqual(self.config.cross_get('OpsiScheduling.Storage.Storage.SuppressedZones.count'), 31)

    def test_globe_navigation_records_count_during_its_existing_screenshot_loop(self):
        campaign = OperationSiren.__new__(OperationSiren)
        campaign.config = self.config
        image = load_image(str(Path(__file__).parent / 'fixtures/opsi_zone_locked_34.png'))
        campaign.device = SimpleNamespace(image=image)

        def frames():
            for _ in range(3):
                campaign.device.image = image.copy()
                yield campaign.device.image

        campaign.loop = frames
        campaign.is_in_globe = Mock(return_value=True)
        campaign.handle_zone_pinned = Mock(return_value=False)
        with (patch('module.os.globe_operation.Digit.ocr', return_value=30),
              patch('module.os.globe_operation.Timer') as timer):
            timer.return_value.start.return_value = timer.return_value
            timer.return_value.reached.return_value = True
            GlobeOperation.os_map_goto_globe(campaign)
        self.assertEqual(self.config.cross_get('OpsiScheduling.Storage.Storage.SuppressedZones.count'), 30)

    def test_disabling_any_smart_explore_prerequisite_restores_normal_tasks(self):
        self.postpone()
        for key, value in (
            ('OpsiExplore.Scheduler.Enable', True),
            ('OpsiScheduling.OpsiSmartExplore.Enable', False),
            ('OpsiScheduling.Scheduler.Enable', False),
            ('OpsiScheduling.OpsiScheduling.UseSmartSchedulingOperationCoinsPreserve', False),
        ):
            with self.subTest(key=key):
                original = self.config.cross_get(key)
                self.config.cross_set(key, value)
                expected = [task for task in ORDER if task != 'OpsiScheduling' or self.config.is_task_enabled(task)]
                self.assertEqual(self.pending(), expected)
                for task in SMART_EXPLORE_DELAY_TASKS:
                    self.run_task(task)
                self.config.cross_set(key, original)

    def test_shop_monthly_date_limit_uses_original_next_day_delay(self):
        self.suppressed()
        self.config.cross_set('OpsiShop.OpsiShop.DisableBeforeDate', NOW.day)
        self.forbid_smart_progress_read()
        self.campaign.config = self.config
        self.campaign.perform_port_shop_purchase = Mock(side_effect=AssertionError('禁购期间不能购买'))
        self.campaign.os_shop.side_effect = lambda: OpsiShop.os_shop(self.campaign)
        with self.assertRaises(TaskEnd):
            self.run_task('OpsiShop')
        self.assertEqual(self.config.cross_get('OpsiShop.Scheduler.NextRun'), UPDATE)
        self.campaign.perform_port_shop_purchase.assert_not_called()

    def test_shop_date_limit_does_not_change_smart_exploration_queue(self):
        self.config.cross_set('OpsiShop.OpsiShop.DisableBeforeDate', NOW.day)
        self.postpone(['OpsiShop'])
        self.assertEqual(self.pending(), ['OpsiDaily', 'OpsiPreventActionPointOverflow', 'OpsiScheduling', 'OpsiShop'])

    def test_deferred_state_survives_reload_without_changing_priority_or_other_storage(self):
        self.postpone()
        self.config = AzurLaneConfig('opsi-delay-test', task='OpsiScheduling')
        self.runner.config = self.config
        before = copy.deepcopy(self.config.data)
        self.assertEqual(self.pending(), ['OpsiScheduling'] + ORDER[:-1])
        self.assertEqual(self.config.data, before)
        self.assertEqual(self.config.SCHEDULER_PRIORITY, self.original_priority)

    def test_invalid_and_expired_delay_records_do_not_change_queue(self):
        for record in (None, [], {}, 'invalid', (UPDATE - timedelta(days=1)).isoformat()):
            with self.subTest(record=record):
                for task in SMART_EXPLORE_DELAY_TASKS:
                    deep_set(self.config.data, f'{task}.Storage.Storage.SmartExploreDelay', record)
                self.assertEqual(self.pending(), ORDER)


if __name__ == '__main__':
    unittest.main()
