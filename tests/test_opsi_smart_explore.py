"""三轮智能开荒、黄币补充与月度行动力专购的离线行为验证。"""
import copy
import json
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config import AzurLaneConfig, TaskEnd
from module.config.deep import deep_get, deep_set
from module.exception import GameStuckError, GameTooManyClickError
from module.os.map_data import DIC_OS_MAP
from module.os.operation_siren import OperationSiren
from module.os.tasks.smart_explore import SMART_EXPLORE_CONFIG, SMART_EXPLORE_ROUTES, SMART_EXPLORE_ZONES
from module.os.tasks.smart_explore import ACTION_POINT_PURCHASE_CONFIG, smart_explore_enabled
from module.os.tasks.scheduling import OpsiScheduling
from module.os.tasks.task_context import prevent_overflow_context
from module.os.tasks.shop import OpsiShop
from module.os_shop.selector import Selector
from module.os_shop.shop import OSShop
from module.os_handler.action_point import ActionPointLimit
from module.campaign.os_run import OSCampaignRun


RESET = datetime(2026, 11, 1)


class Config:
    def __init__(self):
        self.data = {'OpsiScheduling': {
            'Scheduler': {'Enable': True},
            'OpsiScheduling': {'UseSmartSchedulingOperationCoinsPreserve': True,
                               'OperationCoinsPreserve': 40000, 'OperationCoinsReturnThreshold': 20000, 'BuyActionPoint': False},
            'Storage': {'Storage': {'Unrelated': 'keep'}},
        }, 'OpsiExplore': {'Scheduler': {'Enable': True},
                          'OpsiExplore': {'TraditionalEnable': False, 'SmartEnable': True}}}
        self.task = SimpleNamespace(command='OpsiScheduling')
        self.modified = {}
        self.OS_ACTION_POINT_PRESERVE = 200
        self.OpsiExploreCleanup_State = None
        self.OpsiExploreCleanup_Progress = ''
        self.multi_set = nullcontext
        self.temporary = lambda **kwargs: nullcontext()
        self.task_call = Mock()
        self.task_delay = Mock()
        self.task_stop = Mock(side_effect=TaskEnd)

    def cross_get(self, keys, default=None):
        return deep_get(self.data, keys, default)

    def cross_set(self, keys, value):
        deep_set(self.data, keys, copy.deepcopy(value))

    def save(self):
        for keys, value in self.modified.items():
            self.cross_set(keys, value)
        self.modified.clear()

    def is_task_enabled(self, task):
        return self.cross_get(f'{task}.Scheduler.Enable', False)


class SmartExploreTests(unittest.TestCase):
    def setUp(self):
        for module in ('smart_explore', 'explore_cleanup', 'scheduling'):
            clock = patch(f'module.os.tasks.{module}.get_os_next_reset', return_value=RESET)
            clock.start()
            self.addCleanup(clock.stop)
        self.runner = OperationSiren.__new__(OperationSiren)
        self.runner.config = Config()
        self.runner._execute_hazard1_leveling = Mock()
        self.runner._get_effective_cl1_ap_preserve = Mock(return_value=200)
        self.runner.handle_first_auto_search = Mock()
        self.runner.perform_port_shop_purchase = Mock(return_value=True)
        self.runner._run_with_opsi_task_context = Mock(side_effect=lambda task, func, *a, **kw: func(*a, **kw))
        self.runner._get_scheduling_action_point = Mock(return_value=(2000, 150))
        self.runner.get_yellow_coins = Mock(return_value=70000)
        self.runner.get_routine_yellow_coins = Mock(return_value=70000)
        self.runner._delay_smart_scheduling_for_ap_limit = Mock()
        self.runner._run_smart_explore_node = Mock()

    def state(self, first=True, second=False, third=False, immediate=False, decided=True):
        state = dict(reset=RESET.isoformat(), phase='explore', attempts=0,
                     next=[len(route) if done else 0 for route, done in
                           zip(SMART_EXPLORE_ROUTES, (first, second, third))],
                     second_started=immediate, second_decided=decided)
        self.runner._save_smart_explore_state(state)
        return state

    def decide(self, coins=70000, ap=2000):
        return self.runner._run_smart_explore_once(coins, ap, 150)

    def mark_monthly_complete(self):
        self.runner.config.cross_set('OpsiExplore.OpsiExplore.Progress', '已完成百分之100.00')
        self.runner.config.cross_set('OpsiExplore.OpsiExplore.MeowfficerCleanupState',
                                     {'reset': RESET.isoformat(), 'phase': 'done'})

    def test_current_month_completed_exploration_skips_smart_routes(self):
        self.mark_monthly_complete()
        self.assertFalse(self.decide())
        self.runner._run_smart_explore_node.assert_not_called()
        self.assertIsNone(self.runner._get_smart_scheduling_state_value('SmartExplore'))

    def test_last_month_completed_exploration_does_not_skip_new_month_routes(self):
        self.mark_monthly_complete()
        self.runner.config.cross_set('OpsiExplore.OpsiExplore.MeowfficerCleanupState',
                                     {'reset': datetime(2026, 10, 1).isoformat(), 'phase': 'done'})
        self.assertTrue(self.decide())
        self.assertEqual(self.runner._run_smart_explore_node.call_args.args[1], 0)

    def test_traditional_mode_disables_smart_routes_and_keeps_monthly_gate(self):
        self.runner.config.cross_set(SMART_EXPLORE_CONFIG + 'SmartEnable', False)
        self.runner.config.cross_set(SMART_EXPLORE_CONFIG + 'TraditionalEnable', True)
        self.assertFalse(smart_explore_enabled(self.runner.config))
        self.assertFalse(self.decide())
        self.assertTrue(self.runner.is_in_opsi_explore())

    def test_purchase_still_works_after_smart_first_round_is_disabled(self):
        self.state()
        self.runner.config.cross_set(SMART_EXPLORE_CONFIG + 'SmartEnable', False)
        self.runner.config.cross_set('OpsiScheduling.OpsiScheduling.UseSmartSchedulingOperationCoinsPreserve', False)
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.assertTrue(self.runner._try_scheduling_action_point_purchase())

    def test_missing_month_marker_cannot_authorize_purchase(self):
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.runner.config.cross_set('OpsiExplore.OpsiExplore.Progress', '已完成百分之100.00')
        self.assertFalse(self.runner._try_scheduling_action_point_purchase())

    def test_purchase_setting_migrates_without_overwriting_explicit_new_value(self):
        from module.config.config_updater import ConfigUpdater

        for old_value in (False, True):
            old = {'OpsiScheduling': {'OpsiSmartExplore': {'BuyActionPoint': old_value}}}
            new = ConfigUpdater().config_update(old)
            self.assertEqual(deep_get(new, ACTION_POINT_PURCHASE_CONFIG), old_value)
            self.assertNotIn('OpsiSmartExplore', new['OpsiScheduling'])
        old['OpsiScheduling']['OpsiScheduling'] = {'BuyActionPoint': False}
        self.assertFalse(deep_get(ConfigUpdater().config_update(old), ACTION_POINT_PURCHASE_CONFIG))

    def test_routes_cover_all_72_normal_zones_once_and_keep_ports(self):
        self.assertEqual(len(SMART_EXPLORE_ZONES), 72)
        self.assertEqual(set(SMART_EXPLORE_ZONES), set(DIC_OS_MAP) - set(range(8)) - {154})
        self.assertEqual(SMART_EXPLORE_ROUTES[0][:4], (0, 44, 42, 22))
        self.assertEqual(SMART_EXPLORE_ROUTES[1], (155, 156, 2, 71, 73, 3, 121))

    def test_only_coin_target_mode_and_enabled_scheduler_can_explore(self):
        for keys in (SMART_EXPLORE_CONFIG + 'SmartEnable', 'OpsiExplore.Scheduler.Enable',
                     'OpsiScheduling.Scheduler.Enable',
                     'OpsiScheduling.OpsiScheduling.UseSmartSchedulingOperationCoinsPreserve'):
            with self.subTest(keys=keys):
                self.runner.config.cross_set(keys, False)
                self.assertFalse(self.decide())
                self.runner.config.cross_set(keys, True)
        self.assertTrue(smart_explore_enabled(self.runner.config))

    def test_prevent_overflow_does_not_explore_or_purchase(self):
        self.runner.config.task.command = 'OpsiPreventActionPointOverflow'
        with prevent_overflow_context(self.runner.config):
            self.assertFalse(self.decide())
            self.assertFalse(self.runner._try_scheduling_action_point_purchase())

    def test_first_round_runs_even_with_enough_coins(self):
        self.state(first=False)
        self.assertTrue(self.decide())
        self.assertEqual(self.runner._run_smart_explore_node.call_args.args[1], 0)

    def test_leveling_returns_to_map_before_ship_check_even_when_check_skips(self):
        for in_globe in (False, True):
            with self.subTest(in_globe=in_globe):
                calls = []
                self.runner.is_in_globe = Mock(return_value=in_globe)
                self.runner.os_globe_goto_map = Mock(side_effect=lambda: calls.append('map'))
                self.runner.zone_init = Mock(side_effect=lambda: calls.append('zone'))
                self.runner.os_check_leveling = Mock(side_effect=lambda: calls.append('check'))
                self.runner.run_hazard1_leveling_once = Mock(side_effect=lambda **kw: calls.append('leveling'))
                self.runner._run_scheduled_hazard1_leveling(200, fresh_ap=(2000, 150))
                self.assertEqual(calls, (['map', 'zone'] if in_globe else []) + ['check', 'leveling'])
                self.runner.run_hazard1_leveling_once.assert_called_once_with(ap_preserve=200, fresh_ap=(2000, 150))

    def test_smart_exploration_uses_shared_force_run_for_interval(self):
        config = self.runner.config
        config.OpsiExplore_SpecialRadar = False
        config.OpsiFleet_Fleet = 1
        config.OpsiFleet_Submarine = False
        for method in ('tuning_sample_use', 'fleet_set', 'os_order_execute', 'run_auto_search', 'handle_after_auto_search'):
            setattr(self.runner, method, Mock())
        for force in (False, True):
            with self.subTest(force=force):
                config.cross_set(SMART_EXPLORE_CONFIG + 'ForceRun', force)
                config.task_delay.reset_mock()
                self.runner._clear_smart_explore_zone()
                if force:
                    config.task_delay.assert_not_called()
                else:
                    config.task_delay.assert_called_once_with(minute=27, task='OpsiScheduling')
                self.runner.run_auto_search.assert_called_with(question=False, rescan='full')

    def test_1360_boundary_and_purchase_switch(self):
        for ap, buy, expected in ((1361, False, 1), (1360, False, None),
                                  (1359, False, None), (1360, True, 1), (1359, True, 1)):
            with self.subTest(ap=ap, buy=buy):
                self.state(decided=False)
                self.runner._run_smart_explore_node.reset_mock()
                self.runner._execute_hazard1_leveling.reset_mock()
                self.runner.perform_port_shop_purchase.reset_mock()
                self.runner._clear_smart_scheduling_state_value('ActionPointPurchase')
                self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, buy)
                self.decide(ap=ap)
                if expected is None:
                    self.runner._execute_hazard1_leveling.assert_called_once()
                    self.runner._run_smart_explore_node.assert_not_called()
                else:
                    self.assertEqual(self.runner._run_smart_explore_node.call_args.args[1], expected)
                self.assertEqual(self.runner.perform_port_shop_purchase.call_count, int(buy and ap <= 1360))

    def test_second_round_once_started_runs_to_completion_with_enough_coins(self):
        state = self.state(immediate=True)
        state['next'][1] = 3
        self.runner._save_smart_explore_state(state)
        self.decide(coins=100000)
        self.assertEqual(self.runner._run_smart_explore_node.call_args.args[1], 1)

    def test_replenishment_uses_second_then_third_before_normal_coin_tasks(self):
        for second, expected in ((False, 1), (True, 2)):
            with self.subTest(second=second):
                self.state(second=second)
                self.decide(coins=39999)
                self.assertEqual(self.runner._run_smart_explore_node.call_args.args[1], expected)

    def test_return_threshold_stays_fixed_and_resumes_third_round_after_leveling(self):
        self.state(second=True)
        self.decide(coins=39999)
        self.runner._run_smart_explore_node.reset_mock()
        self.decide(coins=59999)
        self.runner._run_smart_explore_node.assert_called_once()
        self.runner._run_smart_explore_node.reset_mock()
        self.decide(coins=60000)
        self.runner._execute_hazard1_leveling.assert_called_once()
        self.runner._run_smart_explore_node.assert_not_called()
        self.assertFalse(self.runner._is_coin_replenish_active())
        self.decide(coins=39999)
        self.assertEqual(self.runner._run_smart_explore_node.call_args.args[1], 2)

    def test_complete_skips_event_cleanup_and_returns_to_normal_scheduler(self):
        self.state(second=True, third=True)
        self.runner._run_explore_cleanup = Mock(side_effect=AssertionError('不应补扫'))
        self.assertTrue(self.decide())
        self.runner._run_explore_cleanup.assert_not_called()
        self.assertEqual(self.runner.config.cross_get(SMART_EXPLORE_CONFIG + 'Progress'), '已开荒 72/72，阶段：已完成')
        self.assertFalse(self.runner.config.cross_get(SMART_EXPLORE_CONFIG + 'SpecialRadar'))
        self.runner.config.task_delay.assert_called_with(target=RESET, task='OpsiExplore')
        self.assertFalse(self.decide())

    def test_legacy_pending_cleanup_finishes_without_scanning(self):
        state = self.state(second=True, third=True)
        self.runner._save_smart_explore_state(dict(state, phase='cleanup'))
        self.mark_monthly_complete()
        self.runner._run_explore_cleanup = Mock(side_effect=AssertionError('不应补扫'))
        self.assertTrue(self.decide())
        self.runner._run_explore_cleanup.assert_not_called()
        self.assertEqual(self.runner._get_smart_explore_state()['phase'], 'done')

    def test_cleanup_resume_repairs_interrupted_monthly_completion_write(self):
        state = self.state(second=True, third=True)
        self.runner._save_smart_explore_state(dict(state, phase='cleanup'))
        self.assertTrue(self.decide())
        self.assertEqual(self.runner.config.cross_get('OpsiExplore.OpsiExplore.Progress'),
                         '已开荒 72/72，阶段：已完成')
        self.assertEqual(self.runner.config.cross_get('OpsiExplore.OpsiExplore.MeowfficerCleanupState')['reset'],
                         RESET.isoformat())

    def test_partial_exploration_never_marks_monthly_exploration_100_percent(self):
        self.state(second=True)
        self.decide()
        self.assertEqual(self.runner.config.cross_get(SMART_EXPLORE_CONFIG + 'Progress'), '已开荒 34/72，阶段：开荒')
        self.assertIsNone(self.runner.config.cross_get(SMART_EXPLORE_CONFIG + 'MeowfficerCleanupState'))

    def test_month_reset_clears_routes_but_keeps_other_scheduler_state(self):
        self.state(second=True)
        with patch('module.os.tasks.smart_explore.get_os_next_reset', return_value=datetime(2026, 12, 1)):
            self.assertEqual(self.runner._get_smart_explore_state()['next'], [0, 0, 0])
        self.assertEqual(self.runner._get_smart_scheduling_state_value('Unrelated'), 'keep')

    def test_cross_month_does_not_save_old_progress(self):
        state = self.state()
        with patch('module.os.tasks.smart_explore.get_os_next_reset', return_value=datetime(2026, 12, 1)):
            with self.assertRaises(GameStuckError):
                self.runner._save_smart_explore_state(state)

    def test_purchase_requires_completed_first_round_or_full_monthly_exploration(self):
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.state(first=False)
        self.assertFalse(self.runner._try_scheduling_action_point_purchase())
        self.mark_monthly_complete()
        self.runner.config.cross_set(SMART_EXPLORE_CONFIG + 'SmartEnable', False)
        self.assertTrue(self.runner._try_scheduling_action_point_purchase())

    def test_stale_monthly_100_percent_cannot_purchase(self):
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.runner.config.cross_set('OpsiExplore.OpsiExplore.Progress', '已完成百分之100.00')
        self.runner.config.cross_set('OpsiExplore.OpsiExplore.MeowfficerCleanupState',
                                     {'reset': datetime(2026, 10, 1).isoformat()})
        self.assertFalse(self.runner._try_scheduling_action_point_purchase())

    def test_purchase_once_per_month_and_restarts_do_not_repeat(self):
        self.state()
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.assertTrue(self.runner._try_scheduling_action_point_purchase())
        self.assertFalse(self.runner._try_scheduling_action_point_purchase())
        self.runner.perform_port_shop_purchase.assert_called_once_with(action_point_only=True)
        restarted = OperationSiren.__new__(OperationSiren)
        restarted.config = self.runner.config
        self.assertFalse(restarted._try_scheduling_action_point_purchase())

    def test_interrupted_purchase_resumes_and_normal_return_marks_done(self):
        self.state()
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.runner.perform_port_shop_purchase.side_effect = [GameStuckError('购买中断'), True]
        with self.assertRaises(GameStuckError):
            self.runner._try_scheduling_action_point_purchase()
        self.assertEqual(self.runner._get_smart_scheduling_state_value('ActionPointPurchase')['phase'], 'buying')
        self.assertTrue(self.runner._try_scheduling_action_point_purchase())
        self.assertEqual(self.runner._get_smart_scheduling_state_value('ActionPointPurchase')['phase'], 'done')

    def test_legacy_false_stock_check_retry_counter_does_not_block_resume(self):
        self.state()
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.runner._set_smart_scheduling_state_value('ActionPointPurchase',
                                                     dict(reset=RESET.isoformat(), phase='buying', attempts=3))
        self.assertTrue(self.runner._try_scheduling_action_point_purchase())
        self.assertFalse(self.runner._try_scheduling_action_point_purchase())
        self.assertEqual(self.runner.perform_port_shop_purchase.call_count, 1)
        self.assertEqual(self.runner._get_smart_scheduling_state_value('ActionPointPurchase')['phase'], 'done')

    def test_purchase_crossing_month_does_not_mark_old_month_done(self):
        self.state()
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        with patch('module.os.tasks.smart_explore.get_os_next_reset',
                   side_effect=[RESET, RESET, datetime(2026, 12, 1)]):
            with self.assertRaises(GameStuckError):
                self.runner._try_scheduling_action_point_purchase()
        self.assertEqual(self.runner._get_smart_scheduling_state_value('ActionPointPurchase'),
                         dict(reset=RESET.isoformat(), phase='buying'))

    def test_node_confirms_safe_zone_before_advancing_and_retries_same_zone(self):
        state = self.state(first=False)
        state['next'][0] = 1
        self.runner.globe_goto = Mock(return_value=True)
        self.runner.name_to_zone = lambda zone: zone
        for method in ('_clear_smart_explore_zone', 'os_map_goto_globe', 'globe_update',
                       'globe_focus_to', 'ensure_no_zone_pinned'):
            setattr(self.runner, method, Mock())
        self.runner.zone_has_safe = Mock(side_effect=[False, True])
        with self.assertRaises(GameStuckError):
            OpsiScheduling._run_smart_explore_node(self.runner, state, 0)
        saved = self.runner._get_smart_explore_state()
        self.assertEqual(saved['next'][0], 1)
        self.assertEqual(saved['attempts'], 1)
        OpsiScheduling._run_smart_explore_node(self.runner, saved, 0)
        saved = self.runner._get_smart_explore_state()
        self.assertEqual(saved['next'][0], 2)
        self.assertEqual(saved['attempts'], 0)
        self.runner.globe_goto.assert_called_with(44, stop_if_safe=True, force_enter=True)

    def test_ap_exhaustion_does_not_consume_zone_retry_budget(self):
        state = self.state(first=False)
        state['next'][0] = 1
        self.runner.globe_goto = Mock(side_effect=ActionPointLimit(total=0))
        with self.assertRaises(ActionPointLimit):
            OpsiScheduling._run_smart_explore_node(self.runner, state, 0)
        self.assertEqual(self.runner._get_smart_explore_state()['attempts'], 0)

    def test_port_nodes_enter_and_leave_port_before_saving(self):
        state = self.state(first=False)
        self.runner.globe_goto = Mock()
        self.runner.port_enter = Mock()
        self.runner.port_quit = Mock()
        OpsiScheduling._run_smart_explore_node(self.runner, state, 0)
        self.runner.globe_goto.assert_called_once_with(0)
        self.runner.port_enter.assert_called_once()
        self.runner.port_quit.assert_called_once()
        self.assertEqual(self.runner._get_smart_explore_state()['next'][0], 1)

    def test_scheduling_catches_ap_exhaustion_and_buys_after_first_round(self):
        self.state(second=True)
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.runner._execute_hazard1_leveling.side_effect = ActionPointLimit(total=20, preserve=200)
        self.runner.run_smart_scheduling_once()
        self.runner.perform_port_shop_purchase.assert_called_once_with(action_point_only=True)
        self.runner._delay_smart_scheduling_for_ap_limit.assert_not_called()

    def test_normal_monthly_mode_buys_when_ap_reaches_leveling_reserve(self):
        self.runner.config.cross_set(SMART_EXPLORE_CONFIG + 'SmartEnable', False)
        self.runner.config.cross_set(ACTION_POINT_PURCHASE_CONFIG, True)
        self.mark_monthly_complete()
        self.runner._get_scheduling_action_point.return_value = (200, 100)
        self.runner.run_smart_scheduling_once()
        self.runner.perform_port_shop_purchase.assert_called_once_with(action_point_only=True)

    def test_route_failure_reload_and_shared_progress_keep_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'smart-route-restart-test.json'
            data = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
            data['OpsiScheduling']['Scheduler']['Enable'] = True
            data['OpsiExplore']['Scheduler']['Enable'] = True
            data['OpsiExplore']['OpsiExplore'].update(TraditionalEnable=False, SmartEnable=True)
            data['OpsiScheduling']['Storage']['Storage'] = {'Unrelated': 'keep'}
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('module.config.config.filepath_config', return_value=str(path)), \
                    patch('module.config.config_updater.filepath_config', return_value=str(path)):
                self.runner.config = AzurLaneConfig('smart-route-restart-test', task='OpsiScheduling')
                state = self.state(first=False)
                state['next'][0] = 1
                self.runner._save_smart_explore_state(state)
                del self.runner._run_with_opsi_task_context
                del self.runner._run_smart_explore_node
                failures = [GameTooManyClickError('自律寻敌启动失败'), None]
                def clear():
                    self.assertEqual(self.runner.config.task.command, 'OpsiExplore')
                    failure = failures.pop(0)
                    if failure:
                        raise failure
                self.runner._clear_smart_explore_zone = Mock(side_effect=clear)
                self.runner.globe_goto = Mock(return_value=True)
                self.runner.name_to_zone = lambda zone: zone
                self.runner.zone_has_safe = Mock(return_value=True)
                for method in ('os_map_goto_globe', 'globe_update', 'globe_focus_to', 'ensure_no_zone_pinned'):
                    setattr(self.runner, method, Mock())
                with self.assertRaises(GameTooManyClickError):
                    self.decide()
                self.assertEqual(self.runner.config.task.command, 'OpsiScheduling')
                self.runner.config = AzurLaneConfig('smart-route-restart-test', task='OpsiScheduling')
                saved = self.runner._get_smart_explore_state()
                self.assertEqual((saved['next'][0], saved['attempts']), (1, 1))
                self.assertTrue(self.decide())
                saved = self.runner._get_smart_explore_state()
                self.assertEqual((saved['next'][0], saved['attempts']), (2, 0))
                self.assertEqual(self.runner.config.cross_get(SMART_EXPLORE_CONFIG + 'Progress'),
                                 '已开荒 1/72，阶段：开荒')
                self.assertEqual(self.runner.config.cross_get('OpsiScheduling.Storage.Storage.Unrelated'), 'keep')
                self.assertEqual(self.runner.config.task.command, 'OpsiScheduling')

    def test_real_config_and_task_context_restore_owner_and_persist_purchase(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'smart-explore-test.json'
            data = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
            data['OpsiScheduling']['Scheduler']['Enable'] = True
            data['OpsiExplore']['Scheduler']['Enable'] = True
            data['OpsiExplore']['OpsiExplore'].update(TraditionalEnable=False, SmartEnable=True)
            data['OpsiScheduling']['OpsiScheduling']['BuyActionPoint'] = True
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('module.config.config.filepath_config', return_value=str(path)), \
                    patch('module.config.config_updater.filepath_config', return_value=str(path)):
                self.runner.config = AzurLaneConfig('smart-explore-test', task='OpsiScheduling')
                self.state()
                del self.runner._run_with_opsi_task_context
                owner = self.runner.config.task
                def purchase(**kwargs):
                    self.assertEqual(kwargs, {'action_point_only': True})
                    self.assertEqual(self.runner.config.task.command, 'OpsiShop')
                    self.assertTrue(self.runner.is_running_smart_scheduling_task())
                    return True
                self.runner.perform_port_shop_purchase.side_effect = purchase
                self.assertTrue(self.runner._try_scheduling_action_point_purchase())
                self.assertIs(self.runner.config.task, owner)
                self.assertFalse(self.runner.is_running_smart_scheduling_task())
                self.assertTrue(self.runner.config.cross_get(SMART_EXPLORE_CONFIG + 'SmartEnable'))
                restarted = AzurLaneConfig('smart-explore-test', task='OpsiScheduling')
                self.assertEqual(restarted.cross_get('OpsiScheduling.Storage.Storage')['ActionPointPurchase']['phase'], 'done')
                self.assertEqual(restarted.cross_get('OpsiScheduling.Storage.Storage')['SmartExplore']['next'][0], 30)

    def test_monthly_explore_entry_delegates_before_game_initialization(self):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = self.runner.config
        runner.load_campaign = Mock(side_effect=AssertionError('不应初始化游戏'))
        with self.assertRaises(TaskEnd):
            runner.opsi_explore()
        runner.config.task_call.assert_called_once_with('OpsiScheduling', force_call=False)
        self.assertFalse(self.runner.is_in_opsi_explore())

    def test_traditional_entry_keeps_original_exploration(self):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = self.runner.config
        runner.config.cross_set(SMART_EXPLORE_CONFIG + 'SmartEnable', False)
        campaign = Mock()
        runner._run_opsi_task_with_ap_overflow_guard = Mock(side_effect=lambda callback: callback(campaign))
        runner.opsi_explore()
        campaign.os_explore.assert_called_once_with()
        runner.config.task_call.assert_not_called()

    def test_smart_entry_missing_scheduler_does_not_fall_back_to_traditional(self):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = self.runner.config
        runner.config.cross_set('OpsiScheduling.Scheduler.Enable', False)
        runner.load_campaign = Mock(side_effect=AssertionError('不应初始化传统开荒'))
        with self.assertRaises(TaskEnd):
            runner.opsi_explore()
        runner.load_campaign.assert_not_called()
        runner.config.task_call.assert_not_called()
        self.assertFalse(self.runner.is_in_opsi_explore())

    def test_generated_exploration_modes_share_controls_and_translations_are_complete(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / 'module/config/argument/args.json').read_text(encoding='utf-8'))
        self.assertNotIn('OpsiSmartExplore', schema['OpsiScheduling'])
        self.assertEqual(next(iter(schema['OpsiScheduling']['OpsiScheduling'])), 'BuyActionPoint')
        template = json.loads((root / 'config/template.json').read_text(encoding='utf-8'))['OpsiScheduling']
        self.assertIs(template['OpsiScheduling']['BuyActionPoint'], False)
        self.assertNotIn('OpsiSmartExplore', template)
        monthly = json.loads((root / 'config/template.json').read_text(encoding='utf-8'))['OpsiExplore']
        self.assertIs(monthly['OpsiExplore']['TraditionalEnable'], True)
        self.assertIs(monthly['OpsiExplore']['SmartEnable'], False)
        self.assertIs(monthly['OpsiExplore']['ForceRun'], False)
        self.assertIn('Progress', monthly['OpsiExplore'])
        self.assertNotIn('ExploreProgress', monthly['OpsiExplore'])
        self.assertNotIn('EventCleanup', monthly['OpsiExplore'])
        for lang in ('zh-CN', 'zh-TW', 'en-US', 'ja-JP'):
            texts = json.loads((root / f'module/config/i18n/{lang}.json').read_text(encoding='utf-8'))
            for value in texts['OpsiExplore'].values():
                for text in value.values():
                    self.assertFalse(text.startswith('OpsiExplore.'))


class PortActionPointTests(unittest.TestCase):
    def item(self, name='ActionPoint', count=5):
        return SimpleNamespace(name=name, count=count, total_count=5, price=100,
                               cost='YellowCoins', is_known_item=lambda: name != 'DefaultItem')

    def test_selector_buys_only_action_point(self):
        runner = Selector()
        runner.config = SimpleNamespace()
        runner._opsi_action_point_purchase = True
        ap, material, sold = self.item(), self.item('DevelopmentMaterialT1'), self.item(count=0)
        self.assertEqual(runner.items_filter_in_os_shop([ap, material, sold]), [ap])

    def test_action_point_purchase_can_use_reserved_coins(self):
        runner = OSShop.__new__(OSShop)
        runner._opsi_action_point_purchase = True
        runner._shop_yellow_coins = 12345
        self.assertEqual(runner.get_currency_coins(self.item()), 12345)

    def test_action_point_purchase_sets_entire_stock_instead_of_legacy_batch_size(self):
        runner = OSShop.__new__(OSShop)
        runner.config = SimpleNamespace()
        runner.device = SimpleNamespace(image=None)
        runner._opsi_action_point_purchase = True
        runner._shop_yellow_coins = 100000
        runner.ui_ensure_index = Mock()
        item = self.item(count=25)
        item.total_count = 25
        with patch('module.os_shop.shop.OCR_SHOP_AMOUNT.ocr', return_value=1):
            self.assertTrue(runner.shop_buy_amount_handler(item))
        self.assertEqual(runner.ui_ensure_index.call_args.args[0], 25)

    def test_purchase_does_not_rescan_locked_or_unrecognized_goods(self):
        runner = OperationSiren.__new__(OperationSiren)
        runner.zone = SimpleNamespace(is_azur_port=True)
        runner.appear = Mock(return_value=True)
        for name in ('port_enter', 'port_shop_enter', 'port_shop_quit', 'port_quit'):
            setattr(runner, name, Mock())
        runner.handle_port_supply_buy = Mock(return_value=True)
        runner.scan_all = Mock(return_value=[self.item('DefaultItem')])
        self.assertTrue(runner.perform_port_shop_purchase(action_point_only=True))
        runner.scan_all.assert_not_called()
        self.assertFalse(runner._opsi_action_point_purchase)

    def test_resumed_purchase_with_no_available_action_points_completes(self):
        runner = OperationSiren.__new__(OperationSiren)
        runner.zone = SimpleNamespace(is_azur_port=True)
        runner.appear = Mock(return_value=True)
        runner.port_enter = Mock()
        runner.port_shop_enter = Mock()
        runner.port_shop_quit = Mock()
        runner.port_quit = Mock()
        runner.handle_port_supply_buy = Mock(return_value=False)
        runner.scan_all = Mock(return_value=[])
        self.assertTrue(runner.perform_port_shop_purchase(action_point_only=True))
        runner.scan_all.assert_not_called()
        self.assertFalse(runner._opsi_action_point_purchase)

    def test_normal_shop_result_is_preserved_and_filter_scope_restored(self):
        for action_only, empty in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(action_only=action_only, empty=empty):
                runner = OperationSiren.__new__(OperationSiren)
                runner.zone = SimpleNamespace(is_azur_port=True)
                runner.appear = Mock(return_value=True)
                for name in ('port_enter', 'port_shop_enter', 'port_shop_quit', 'port_quit'):
                    setattr(runner, name, Mock())
                runner.handle_port_supply_buy = Mock(return_value=not empty)
                runner.scan_all = Mock(side_effect=AssertionError('购买后不应全商店复扫'))
                self.assertEqual(OpsiShop.perform_port_shop_purchase(runner, action_point_only=action_only),
                                 action_only or not empty)
                self.assertFalse(runner._opsi_action_point_purchase)

    def test_missing_shop_still_raises_and_restores_filter_scope(self):
        runner = OperationSiren.__new__(OperationSiren)
        runner.zone = SimpleNamespace(is_azur_port=True)
        runner.appear = Mock(return_value=False)
        runner.port_enter = Mock()
        runner.port_shop_enter = Mock()
        with self.assertRaises(GameStuckError):
            runner.perform_port_shop_purchase(action_point_only=True)
        self.assertFalse(runner._opsi_action_point_purchase)


if __name__ == '__main__':
    unittest.main()
