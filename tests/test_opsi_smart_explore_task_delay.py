"""智能开荒期间的当天让位，使用真实任务队列及临时配置，不连接设备。"""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.os_run import OSCampaignRun
from module.config.config import AzurLaneConfig, Function, TaskEnd
from module.config.deep import deep_set
from module.os.tasks.shop import OpsiShop
from module.os.tasks.smart_explore import SMART_EXPLORE_DELAY_TASKS


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
            ('module.os.tasks.smart_explore.current_time', NOW),
            ('module.os.tasks.shop.current_time', NOW),
            ('module.os.tasks.smart_explore.get_os_next_reset', RESET),
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

    def test_first_round_completion_still_waits_for_remaining_exploration(self):
        self.config.cross_set('OpsiScheduling.Storage.Storage.SmartExplore.next', [30, 0, 0])
        self.postpone()

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
        self.postpone()
        self.config.cross_set('OpsiShop.OpsiShop.DisableBeforeDate', NOW.day)
        self.assertEqual(self.pending(), ['OpsiShop', 'OpsiScheduling', 'OpsiDaily', 'OpsiPreventActionPointOverflow'])
        self.forbid_smart_progress_read()
        self.campaign.config = self.config
        self.campaign.perform_port_shop_purchase = Mock(side_effect=AssertionError('禁购期间不能购买'))
        self.campaign.os_shop.side_effect = lambda: OpsiShop.os_shop(self.campaign)
        with self.assertRaises(TaskEnd):
            self.run_task('OpsiShop')
        self.assertEqual(self.config.cross_get('OpsiShop.Scheduler.NextRun'), UPDATE)
        self.campaign.perform_port_shop_purchase.assert_not_called()

    def test_date_limit_expiry_allows_shop_to_wait_for_smart_exploration(self):
        self.config.cross_set('OpsiShop.OpsiShop.DisableBeforeDate', NOW.day - 1)
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
