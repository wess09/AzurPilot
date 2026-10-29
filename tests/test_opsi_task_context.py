"""代理上下文与延迟路由的组合回归，不连接游戏或写入用户配置。"""

import unittest
from concurrent.futures import Future
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import numpy as np

from module.base.utils import load_image
from module.config.config import AzurLaneConfig, Function, TaskEnd
from module.os.operation_siren import OperationSiren
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow
from module.os.tasks.scheduling import OpsiScheduling
from module.os.tasks.task_context import current_opsi_context
from module.os_handler.action_point import ActionPointLimit
from module.os_handler.os_status import OCR_SHOP_YELLOW_COINS
from module.os_handler.resource_read import BackgroundCoinRead, CoinReading


class TestOpsiTaskContext(unittest.TestCase):
    """使用真实 bind/task_delay，屏蔽持久化和游戏交互。"""

    def make_runner(self, task='OpsiScheduling'):
        runner = OpsiPreventActionPointOverflow.__new__(OpsiPreventActionPointOverflow)
        config = AzurLaneConfig.__new__(AzurLaneConfig)
        config.bound = {}
        config.modified = {}
        config.overridden = {}
        config.auto_update = False
        config.data = {
            name: {'Scheduler': {
                'Command': name,
                'ServerUpdate': update,
                'SuccessInterval': 30,
                'FailureInterval': 60,
            }}
            for name, update in (
                ('OpsiScheduling', '01:00'),
                ('OpsiPreventActionPointOverflow', '02:00'),
                ('OpsiMeowfficerFarming', '03:00'),
                ('OpsiHazard1Leveling', '04:00'),
                ('OpsiObscure', '05:00'),
            )
        }
        config.task = Function(config.data[task])
        config.bind(config.task)
        config.update = Mock()
        config.temporary = lambda **kwargs: nullcontext()
        config.task_stop = Mock(side_effect=TaskEnd)
        runner.config = config
        return runner

    def assert_restored(self, runner, owner, bound):
        self.assertIs(runner.config.task, owner)
        self.assertEqual(runner.config.bound, bound)
        for name in ('_opsi_task_context', '_bind_task_override', '_task_switch_owner', '_disable_task_switch'):
            self.assertNotIn(name, runner.config.__dict__)
        self.assertFalse(runner.is_running_smart_scheduling_task())
        self.assertFalse(runner.is_running_prevent_action_point_overflow_task())

    def make_currency_runner(self, task='OpsiScheduling'):
        """子任务返回时仍留着开工前截图，下一次截图才显示已到账黄币。"""
        runner = self.make_runner(task)
        runner.config.config_name = 'isolated'
        previous = np.zeros((720, 1280, 3), np.uint8)
        current = previous.copy()
        fixture = Path(__file__).parent / 'fixtures/opsi_yellow_coin_video/97451.png'
        current[27:48, 1038:1128] = load_image(str(fixture))
        identity = runner._background_coin_identity()
        runner._last_yellow_coins = 91760
        runner._last_yellow_owner = identity[:2]
        runner._yellow_coin_read = (
            (*identity[:2], 'map', identity[2]), previous[27:48, 1038:1128].copy(), 91760,
        )
        runner.device = Mock(image=previous)
        runner.device.screenshot.side_effect = lambda: setattr(runner.device, 'image', current.copy())
        runner.appear = Mock(return_value=False)
        runner.appear_then_click = Mock(return_value=False)
        runner.is_in_map = Mock(return_value=True)
        runner.handle_map_event = Mock(return_value=False)
        runner.action_point_check_due = Mock(return_value=False)
        runner._close_scheduling_action_point = Mock()
        runner._get_scheduling_action_point = Mock(return_value=(1608, 8))
        runner._run_smart_scheduling_decision = Mock()
        runner._delay_smart_scheduling_for_opsi_explore = Mock(return_value=False)
        state = runner._coin_background = BackgroundCoinRead()
        state.frame = previous
        state.candidate = CoinReading(identity, datetime.now(), 91760, True)
        state.future = Future()
        state.future.set_result(state.candidate)
        self.enterContext(patch('module.os_handler.resource_read._executor.submit', side_effect=lambda *args: Future()))
        self.enterContext(patch('module.os_handler.os_status.record_resources_background'))
        self.enterContext(patch.object(OCR_SHOP_YELLOW_COINS, 'last_valid', True, create=True))
        self.enterContext(patch.object(OCR_SHOP_YELLOW_COINS, 'ocr', side_effect=lambda image:
            97451 if np.array_equal(image[27:48, 1038:1128], current[27:48, 1038:1128]) else 91760))
        return runner

    def test_all_scheduled_children_refresh_parent_budget_after_return_or_partial_failure(self):
        children = (
            'OpsiHazard1Leveling', 'OpsiMeowfficerFarming', 'OpsiObscure', 'OpsiAbyssal',
            'OpsiStronghold', 'OpsiExplore', 'OpsiExploreCleanup', 'OpsiShop',
        )
        for child in children:
            for error in (None, TaskEnd, RuntimeError):
                with self.subTest(child=child, error=error):
                    runner = self.make_currency_runner()
                    owner, bound = runner.config.task, dict(runner.config.bound)

                    def finish():
                        self.assertEqual(runner.config.task.command, child)
                        if error:
                            raise error('奖励到账后任务结束')

                    if error:
                        with self.assertRaisesRegex(error, '奖励到账后'):
                            runner._run_with_opsi_task_context(child, finish)
                    else:
                        runner._run_with_opsi_task_context(child, finish)
                    runner.run_smart_scheduling_once()
                    runner._run_smart_scheduling_decision.assert_called_once_with(97451, 1608, 8)
                    self.assertGreaterEqual(runner.device.screenshot.call_count, 2)
                    self.assert_restored(runner, owner, bound)

    def test_overflow_nested_scheduling_refreshes_budget_after_coin_child(self):
        runner = self.make_currency_runner('OpsiPreventActionPointOverflow')
        owner, bound = runner.config.task, dict(runner.config.bound)

        def scheduling():
            runner._run_with_opsi_task_context('OpsiObscure', lambda: None)
            runner.run_smart_scheduling_once()

        runner._run_with_prevent_action_point_overflow_context('OpsiScheduling', scheduling)
        runner._run_smart_scheduling_decision.assert_called_once_with(97451, 1608, 8)
        self.assert_restored(runner, owner, bound)

    def test_nested_context_restores_identity_on_return_and_exceptions(self):
        for error in (None, TaskEnd('结束'), RuntimeError('失败')):
            with self.subTest(error=error):
                runner = self.make_runner('OpsiPreventActionPointOverflow')
                owner, bound = runner.config.task, dict(runner.config.bound)
                observer = OpsiScheduling.__new__(OpsiScheduling)
                observer.config = runner.config

                def child():
                    self.assertEqual(runner.config.task.command, 'OpsiMeowfficerFarming')
                    self.assertIs(runner.config._task_switch_owner, owner)
                    self.assertEqual(current_opsi_context(runner.config).parent_task, 'OpsiScheduling')
                    self.assertEqual(runner.config._bind_task_override, 'OpsiMeowfficerFarming')
                    self.assertEqual(runner.config.Scheduler_ServerUpdate, '03:00')
                    self.assertFalse(runner.config._disable_task_switch)
                    self.assertTrue(observer.is_running_smart_scheduling_task())
                    self.assertTrue(observer.is_running_prevent_action_point_overflow_task())
                    self.assertFalse(runner._is_direct_prevent_overflow_coin_task())
                    if error is not None:
                        raise error
                    return 42

                def scheduling():
                    context = current_opsi_context(runner.config)
                    try:
                        return runner._run_with_opsi_task_context('OpsiMeowfficerFarming', child)
                    finally:
                        self.assertIs(current_opsi_context(runner.config), context)
                        self.assertEqual(runner.config.task.command, 'OpsiScheduling')
                        self.assertIs(runner.config._task_switch_owner, owner)
                        self.assertTrue(runner.config._disable_task_switch)
                        self.assertEqual(runner.config.Scheduler_ServerUpdate, '01:00')

                if error is None:
                    self.assertEqual(runner._run_with_prevent_action_point_overflow_context(
                        'OpsiScheduling', scheduling,
                    ), 42)
                else:
                    with self.assertRaises(type(error)) as caught:
                        runner._run_with_prevent_action_point_overflow_context('OpsiScheduling', scheduling)
                    self.assertIs(caught.exception, error)
                self.assert_restored(runner, owner, bound)

    def test_nested_proxy_checks_switch_against_the_outer_scheduler_task(self):
        for child_task in ('OpsiMeowfficerFarming', 'OpsiHazard1Leveling'):
            with self.subTest(child_task=child_task):
                runner = self.make_runner('OpsiPreventActionPointOverflow')
                config = runner.config
                owner, bound = config.task, dict(config.bound)
                config.stop_event = None
                config.load = Mock()
                config.get_next = Mock(return_value=owner)

                def child():
                    self.assertIs(config._task_switch_owner, owner)
                    self.assertFalse(runner._is_direct_prevent_overflow_coin_task())
                    self.assertFalse(config.task_switched())
                    config.check_task_switch()
                    config.task_stop.assert_not_called()
                    config.get_next.return_value = Function({'Scheduler': {'Command': 'Reward'}})
                    self.assertTrue(config.task_switched())
                    with self.assertRaises(TaskEnd):
                        config.check_task_switch()
                    config.task_stop.assert_called_once()

                def scheduling():
                    runner._run_with_opsi_task_context(child_task, child)

                runner._run_with_prevent_action_point_overflow_context('OpsiScheduling', scheduling)
                self.assert_restored(runner, owner, bound)

    def test_preserves_existing_none_and_override_values(self):
        for previous_bind in (None, 'OpsiHazard1Leveling'):
            with self.subTest(previous_bind=previous_bind):
                runner = self.make_runner()
                config = runner.config
                config._bind_task_override = previous_bind
                config._task_switch_owner = None
                config._disable_task_switch = True
                config._opsi_task_context = None
                config.bind(previous_bind or config.task)
                owner, bound = config.task, dict(config.bound)
                runner._run_with_opsi_task_context('OpsiObscure', lambda: None)
                self.assertIs(config.task, owner)
                self.assertEqual(config.bound, bound)
                self.assertIsNone(config._task_switch_owner)
                self.assertIsNone(config._opsi_task_context)
                self.assertTrue(config._disable_task_switch)
                self.assertEqual(config._bind_task_override, previous_bind)

    def test_meow_overrides_do_not_disable_the_next_obscure_task_submarine(self):
        runner = OperationSiren.__new__(OperationSiren)
        runner.config = self.make_runner().config
        config = runner.config
        config.data['OpsiMeowfficerFarming'].update({
            'OpsiFleet': {'Submarine': True},
            'OpsiMeowfficerFarming': {'HazardLevel': 5, 'TargetZone': 0, 'StayInZone': False},
            'OpsiTarget': {'TargetFarming': False},
        })
        config.data['OpsiObscure']['OpsiFleet'] = {'Submarine': True}
        overrides = config.overridden
        with (
            patch.object(OperationSiren, 'is_cl1_mode_enabled', new_callable=PropertyMock, return_value=True),
            patch.object(OperationSiren, 'nearest_task_cooling_down', new_callable=PropertyMock, return_value=None),
            patch.object(runner, 'is_in_opsi_explore', return_value=False),
            patch('module.os.tasks.meowfficer_farming.get_os_reset_remain', return_value=20),
        ):
            runner._run_with_opsi_task_context(
                'OpsiMeowfficerFarming', runner._prepare_meowfficer_farming, ap_preserve=0,
            )
        self.assertIs(config.overridden, overrides)
        self.assertEqual(config.overridden, {})

        def obscure():
            self.assertTrue(config.OpsiFleet_Submarine)

        runner._run_with_opsi_task_context('OpsiObscure', obscure)

    def test_nested_overrides_restore_manual_attributes_and_existing_overlays(self):
        for error in (None, TaskEnd('结束'), RuntimeError('失败')):
            with self.subTest(error=error):
                runner = self.make_runner('OpsiPreventActionPointOverflow')
                config = runner.config
                owner, bound = config.task, dict(config.bound)
                config.override(STORY_OPTION=-2)
                overrides = config.overridden
                config._scheduler_overrides = {'OpsiFleet_Submarine': True}
                overlay = config._scheduler_overrides
                config.bind(config.task)
                self.assertNotIn('HOMO_EDGE_DETECT', config.__dict__)

                def child():
                    config.override(
                        STORY_OPTION=0, HOMO_EDGE_DETECT=False, OpsiFleet_Submarine=False,
                        PROXY_OVERRIDE_TEST=True,
                    )
                    self.assertFalse(config.OpsiFleet_Submarine)
                    self.assertFalse(config.HOMO_EDGE_DETECT)
                    self.assertEqual(config.STORY_OPTION, 0)
                    config.modified['OpsiObscure.Test.Progress'] = 1
                    if error is not None:
                        raise error

                def scheduling():
                    config.override(STORY_OPTION=1)
                    try:
                        runner._run_with_opsi_task_context('OpsiObscure', child)
                    finally:
                        self.assertEqual(config.STORY_OPTION, 1)
                        self.assertEqual(config.overridden, {'STORY_OPTION': 1})
                        self.assertIs(config.overridden, overrides)
                        self.assertIs(config._scheduler_overrides, overlay)
                        self.assertEqual(overlay, {'OpsiFleet_Submarine': True})
                        self.assertTrue(config.HOMO_EDGE_DETECT)
                        self.assertNotIn('HOMO_EDGE_DETECT', config.__dict__)
                        self.assertNotIn('PROXY_OVERRIDE_TEST', config.__dict__)

                if error is None:
                    runner._run_with_prevent_action_point_overflow_context('OpsiScheduling', scheduling)
                else:
                    with self.assertRaises(type(error)) as caught:
                        runner._run_with_prevent_action_point_overflow_context('OpsiScheduling', scheduling)
                    self.assertIs(caught.exception, error)
                self.assertEqual(config.STORY_OPTION, -2)
                self.assertEqual(config.overridden, {'STORY_OPTION': -2})
                self.assertIs(config.overridden, overrides)
                self.assertIs(config._scheduler_overrides, overlay)
                self.assertEqual(config.modified, {'OpsiObscure.Test.Progress': 1})
                self.assert_restored(runner, owner, bound)

    def test_failed_initial_bind_restores_original_binding(self):
        runner = self.make_runner()
        owner, bound = runner.config.task, dict(runner.config.bound)
        bind = runner.config.bind
        callback = Mock()

        def failing_bind(task):
            bind(task)
            if task == 'OpsiObscure':
                raise RuntimeError('绑定中断')

        with patch.object(runner.config, 'bind', side_effect=failing_bind):
            with self.assertRaisesRegex(RuntimeError, '绑定中断'):
                runner._run_with_opsi_task_context('OpsiObscure', callback)
        callback.assert_not_called()
        self.assert_restored(runner, owner, bound)

    def run_overflow(self, runner, callback, nested=False):
        """保留真实代理和异常处理路径，仅替换一轮游戏任务。"""
        if nested:
            target, method = 'OpsiScheduling', 'run_smart_scheduling_once'

            def body():
                return runner._run_with_opsi_task_context('OpsiMeowfficerFarming', callback)
        else:
            target, method = 'OpsiMeowfficerFarming', 'run_meowfficer_farming_once'

            def body(**kwargs):
                return callback()

        with (
            patch.object(runner, '_get_prevent_action_point_overflow_thresholds', return_value=(200, 0)),
            patch.object(runner, '_get_prevent_action_point_overflow_task', return_value=target),
            patch.object(runner, '_get_current_action_point_for_overflow', return_value=200),
            patch.object(runner, method, side_effect=body, create=True),
        ):
            runner.run_prevent_action_point_overflow()

    def test_minute_delay_reaches_real_task_delay_for_direct_and_nested_proxy(self):
        now = datetime(2026, 9, 19, 12)
        for nested in (False, True):
            with self.subTest(nested=nested):
                runner = self.make_runner('OpsiPreventActionPointOverflow')
                owner, bound = runner.config.task, dict(runner.config.bound)
                end = TaskEnd('分钟延迟')

                def delay():
                    runner._delay_smart_scheduling_with_minutes('回归测试', 120)
                    raise end

                with patch('module.config.config.current_time', return_value=now):
                    with self.assertRaises(TaskEnd) as caught:
                        self.run_overflow(runner, delay, nested=nested)
                self.assertIs(caught.exception, end)
                self.assertEqual(runner.config.modified, {
                    'OpsiPreventActionPointOverflow.Scheduler.NextRun': now + timedelta(minutes=120),
                })
                self.assert_restored(runner, owner, bound)

    def test_server_update_uses_actual_owner_after_binding_restores(self):
        for nested in (False, True):
            for update in (True, '06:00', ['07:00', '08:00']):
                with self.subTest(nested=nested, update=update):
                    runner = self.make_runner('OpsiPreventActionPointOverflow')

                    def delay():
                        runner.delay_opsi_active_task(server_update=update, task='OpsiObscure')
                        raise TaskEnd

                    with patch('module.config.config.get_server_next_update', return_value=datetime(2026, 9, 20)) as next_update:
                        with self.assertRaises(TaskEnd):
                            self.run_overflow(runner, delay, nested=nested)
                    next_update.assert_called_once_with('02:00' if update is True else update)
                    self.assertEqual(list(runner.config.modified), ['OpsiPreventActionPointOverflow.Scheduler.NextRun'])

    def test_positional_delay_preserves_all_time_conditions(self):
        runner = self.make_runner()
        target = datetime(2026, 9, 21)
        with patch.object(runner.config, 'task_delay', autospec=True) as delay:
            runner._run_with_opsi_task_context(
                'OpsiObscure', runner.delay_opsi_active_task, False, True, target, 90, 'OpsiObscure',
            )
        delay.assert_called_once_with(
            success=False, server_update='01:00', target=target, minute=90, task='OpsiScheduling',
        )

    def test_shared_config_delivers_delay_from_another_task_object(self):
        runner = self.make_runner('OpsiPreventActionPointOverflow')
        observer = OpsiScheduling.__new__(OpsiScheduling)
        observer.config = runner.config

        def body():
            observer.delay_opsi_active_task(minute=90)
            raise TaskEnd

        with patch.object(runner.config, 'task_delay', autospec=True) as delay:
            with self.assertRaises(TaskEnd):
                self.run_overflow(runner, body, nested=True)
        delay.assert_called_once_with(minute=90, task='OpsiPreventActionPointOverflow')

    def test_direct_no_content_stops_but_nested_no_content_returns_to_scheduling(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                runner = self.make_runner('OpsiPreventActionPointOverflow')

                def no_content():
                    return runner._handle_coin_task_no_content('耄耋相接', '没有可执行内容')

                with patch.object(runner, '_postpone_coin_task_check'):
                    if nested:
                        def scheduling():
                            return runner._run_with_opsi_task_context('OpsiMeowfficerFarming', no_content)
                        result = runner._run_with_prevent_action_point_overflow_context('OpsiScheduling', scheduling)
                        self.assertTrue(result)
                        runner.config.task_stop.assert_not_called()
                    else:
                        with self.assertRaises(TaskEnd):
                            runner._run_with_prevent_action_point_overflow_context('OpsiMeowfficerFarming', no_content)
                        runner.config.task_stop.assert_called_once()

    def test_normal_return_drops_delay_before_next_round(self):
        runner = self.make_runner('OpsiPreventActionPointOverflow')
        calls = 0

        def body():
            nonlocal calls
            calls += 1
            if calls == 1:
                runner._delay_smart_scheduling_with_minutes('本轮返回', 120)
                return
            raise TaskEnd('下一轮结束')

        with patch.object(runner, 'update_prevent_action_point_overflow_schedule') as update:
            with self.assertRaises(TaskEnd):
                self.run_overflow(runner, body)
        self.assertEqual(calls, 2)
        self.assertEqual(runner.config.modified, {})
        update.assert_called_once_with(current_ap=200, enable=None)
        self.assertFalse(hasattr(runner.config, '_opsi_task_context'))

    def test_unexpected_failure_drops_delay_and_restores_binding(self):
        runner = self.make_runner('OpsiPreventActionPointOverflow')
        owner, bound = runner.config.task, dict(runner.config.bound)

        def body():
            runner._delay_smart_scheduling_with_minutes('中断', 120)
            raise RuntimeError('游戏失败')

        with self.assertRaisesRegex(RuntimeError, '游戏失败'):
            self.run_overflow(runner, body, nested=True)
        self.assertEqual(runner.config.modified, {})
        self.assert_restored(runner, owner, bound)

    def test_action_point_limit_uses_current_ap_and_discards_pending_delay(self):
        runner = self.make_runner('OpsiPreventActionPointOverflow')
        owner, bound = runner.config.task, dict(runner.config.bound)

        def body():
            runner._delay_smart_scheduling_with_minutes('行动力不足前的请求', 120)
            raise ActionPointLimit(current=15, total=15, cost=120)

        with patch.object(runner, 'update_prevent_action_point_overflow_schedule') as update:
            with self.assertRaises(TaskEnd):
                self.run_overflow(runner, body, nested=True)
        update.assert_called_once_with(current_ap=15, enable=None)
        self.assertEqual(runner.config.modified, {})
        self.assert_restored(runner, owner, bound)
