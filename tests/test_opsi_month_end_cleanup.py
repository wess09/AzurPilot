"""大世界月末清理的行动力保留、恢复异常和周期状态回归测试。"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, call, patch

from module.config.config import AzurLaneConfig, Function, TaskEnd
from module.config.deep import deep_get, deep_set
from module.exception import GameStuckError, GameTooManyClickError, RequestHumanTakeover, ScriptError
from module.os.operation_siren import OperationSiren
from module.os.tasks.meowfficer_farming import MeowfficerTargetZoneMixin
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow
from module.os.tasks.scheduling import OpsiScheduling


class MonthEndCleanupConfig:
    """仅保存智能调度状态，不读取真实账号配置或连接模拟器。"""

    def __init__(self, state=None):
        self.data = {'OpsiScheduling': {'Storage': {'Storage': dict(state or {})}}}
        self.modified = {}
        self.save_count = 0

    def cross_get(self, keys, default=None):
        return deep_get(self.data, keys=keys, default=default)

    def save(self):
        for keys, value in self.modified.items():
            deep_set(self.data, keys=keys, value=value)
        self.modified.clear()
        self.save_count += 1

    @staticmethod
    def task_stop():
        raise TaskEnd


class TestMonthEndCleanupActionPoint(unittest.TestCase):
    """每个子任务遵守月末保留值，达到保留值后停止后续行动力消耗。"""

    PRESERVE = 200

    def make_scheduling(self, action_points, first_run=True):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = MonthEndCleanupConfig({
            OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN: first_run,
        })
        scheduling._get_scheduling_action_point = Mock(side_effect=action_points)
        scheduling._run_scheduled_coin_task_once = Mock(return_value=True)
        scheduling._run_month_end_shop_purchase = Mock()
        scheduling._delay_smart_scheduling_to_server_update = Mock()
        scheduling.notify_push = Mock()
        return scheduling

    def run_cleanup(self, scheduling):
        with (
            patch('module.os.tasks.scheduling.get_os_reset_remain', return_value=1),
            self.assertRaises(TaskEnd),
        ):
            scheduling._run_month_end_cleanup(self.PRESERVE, 1000, 1000, 100)

    def test_passes_preserve_to_every_coin_task(self):
        scheduling = self.make_scheduling([
            (900, 100), (800, 100), (700, 100), (200, 100), (200, 100),
        ])

        self.run_cleanup(scheduling)

        self.assertEqual(scheduling._run_scheduled_coin_task_once.call_args_list, [
            call('OpsiStronghold', self.PRESERVE),
            call('OpsiObscure', self.PRESERVE),
            call('OpsiAbyssal', self.PRESERVE),
            call('OpsiMeowfficerFarming', self.PRESERVE, meow_target_zone=None),
        ])
        scheduling._run_month_end_shop_purchase.assert_called_once()

    def test_passes_month_end_meow_target_zone_to_meowfficer(self):
        zone = Mock()
        zone.zone_id = 45
        scheduling = self.make_scheduling([
            (900, 100), (800, 100), (700, 100), (200, 100), (200, 100),
        ])
        scheduling._get_month_end_meow_target_zone = Mock(return_value=zone)

        self.run_cleanup(scheduling)

        self.assertIn(
            call('OpsiMeowfficerFarming', self.PRESERVE, meow_target_zone=zone),
            scheduling._run_scheduled_coin_task_once.call_args_list,
        )

    def test_stops_after_stronghold_reaches_preserve(self):
        scheduling = self.make_scheduling([(200, 100), (200, 100)])

        self.run_cleanup(scheduling)

        scheduling._run_scheduled_coin_task_once.assert_called_once_with('OpsiStronghold', self.PRESERVE)
        scheduling._run_month_end_shop_purchase.assert_not_called()

    def test_stops_after_obscure_reaches_preserve(self):
        scheduling = self.make_scheduling([(250, 100), (200, 100), (200, 100)], first_run=False)

        self.run_cleanup(scheduling)

        scheduling._run_scheduled_coin_task_once.assert_called_once_with('OpsiObscure', self.PRESERVE)
        scheduling._run_month_end_shop_purchase.assert_not_called()

    def test_stops_after_abyssal_reaches_preserve(self):
        scheduling = self.make_scheduling([
            (350, 100), (250, 100), (200, 100), (200, 100),
        ], first_run=False)

        self.run_cleanup(scheduling)

        self.assertEqual(scheduling._run_scheduled_coin_task_once.call_args_list, [
            call('OpsiObscure', self.PRESERVE),
            call('OpsiAbyssal', self.PRESERVE),
        ])
        scheduling._run_month_end_shop_purchase.assert_not_called()

    def test_shop_recovery_exceptions_propagate_without_completion_notification(self):
        for exception_type in (TaskEnd, GameStuckError, GameTooManyClickError, RequestHumanTakeover):
            with self.subTest(exception=exception_type.__name__):
                scheduling = self.make_scheduling([
                    (900, 100), (800, 100), (700, 100), (200, 100), (200, 100),
                ], first_run=False)
                error = exception_type('月末商店流程需要退出或恢复')
                scheduling._run_month_end_shop_purchase.side_effect = error

                with self.assertRaises(exception_type) as raised:
                    scheduling._run_month_end_cleanup(self.PRESERVE, 1000, 1000, 100)

                self.assertIs(raised.exception, error)
                scheduling.notify_push.assert_not_called()
                scheduling._delay_smart_scheduling_to_server_update.assert_not_called()


class TestOperationSirenCoinTaskRouting(unittest.TestCase):
    """保留真实方法解析、配置绑定和短猫准备流程，仅替换游戏操作与持久化。"""

    def make_runner(self, *, target_zone='44', stay_in_zone=True):
        runner = OperationSiren.__new__(OperationSiren)
        config = AzurLaneConfig.__new__(AzurLaneConfig)
        config.bound = {}
        config.modified = {}
        config.overridden = {}
        config.auto_update = False
        config.OS_ACTION_POINT_PRESERVE = 350
        config.pending_task = []
        config.waiting_task = []
        config.data = {
            name: {'Scheduler': {'Command': name, 'Enable': name == 'OpsiScheduling'}}
            for name in ('OpsiScheduling', 'OpsiMeowfficerFarming', 'OpsiStronghold',
                         'OpsiObscure', 'OpsiAbyssal', 'OpsiShop')
        }
        config.data['OpsiMeowfficerFarming']['OpsiMeowfficerFarming'] = {
            'TargetZone': target_zone, 'StayInZone': stay_in_zone,
        }
        config.data['OpsiMeowfficerFarming']['OpsiTarget'] = {'TargetFarming': False}
        config.data['OpsiScheduling']['OpsiScheduling'] = {'MonthEndMeowTargetZone': '0'}
        config.data['OpsiScheduling']['Storage'] = {'Storage': {}}
        config.task = Function(config.data['OpsiScheduling'])
        config.bind(config.task)

        def save_config():
            for keys, value in config.modified.items():
                deep_set(config.data, keys=keys, value=value)
            config.modified.clear()

        config.save = save_config
        runner.config = config
        for method in ('_meow_handle_stay_in_zone', '_meow_handle_target_zone_search',
                       '_meow_handle_traditional_zone', '_meow_handle_normal_search'):
            setattr(runner, method, Mock())
        clip_cleanup = patch('module.base.debug_clip.cleanup_clips_if_due')
        clip_cleanup.start()
        self.addCleanup(clip_cleanup.stop)
        return runner

    def assert_restored(self, runner, owner, bound):
        self.assertIs(runner.config.task, owner)
        self.assertEqual(runner.config.bound, bound)
        self.assertEqual(runner.config.OS_ACTION_POINT_PRESERVE, 350)
        self.assertIsNone(runner._meow_target_zone_override)
        self.assertEqual(runner.config.overridden, {})
        self.assertFalse(runner.is_running_smart_scheduling_task())
        self.assertFalse(runner.is_running_prevent_action_point_overflow_task())

    def test_resolves_real_overflow_override(self):
        runner = self.make_runner()
        self.assertIs(runner._run_scheduled_coin_task_once.__func__,
                      OpsiPreventActionPointOverflow._run_scheduled_coin_task_once)
        # 防溢出未启用仍经过这份覆盖方法，关键字为 None 时也必须能接收。
        self.assertFalse(runner.config.is_task_enabled('OpsiPreventActionPointOverflow'))
        self.assertTrue(runner._run_scheduled_coin_task_once(
            'OpsiMeowfficerFarming', 200, meow_target_zone=None,
        ))

    def test_default_arguments_keep_normal_meow_search(self):
        runner = self.make_runner(target_zone='0', stay_in_zone=False)
        owner, bound = runner.config.task, dict(runner.config.bound)

        self.assertTrue(runner._run_scheduled_coin_task_once('OpsiMeowfficerFarming', 200))

        runner._meow_handle_normal_search.assert_called_once_with()
        runner._meow_handle_stay_in_zone.assert_not_called()
        self.assert_restored(runner, owner, bound)

    def test_none_target_keeps_user_zone_list(self):
        runner = self.make_runner(target_zone='44,22')

        self.assertTrue(runner._run_scheduled_coin_task_once(
            'OpsiMeowfficerFarming', 200, meow_target_zone=None,
        ))

        self.assertEqual([zone.zone_id for zone in runner._meow_target_zone_list], [44, 22])
        self.assertEqual(runner._meow_handle_target_zone_search.call_args.args[0].zone_id, 44)
        runner._meow_handle_stay_in_zone.assert_not_called()

    def test_specified_zone_and_fresh_ap_reach_real_meow_task(self):
        for stay_in_zone in (False, True):
            with self.subTest(stay_in_zone=stay_in_zone):
                runner = self.make_runner(stay_in_zone=stay_in_zone)
                owner, bound = runner.config.task, dict(runner.config.bound)
                zone = runner.name_to_zone('22')
                fresh_ap = (816, 166)

                def check_task(*args, **kwargs):
                    self.assertEqual(runner.config.task.command, 'OpsiMeowfficerFarming')
                    self.assertTrue(runner.is_running_smart_scheduling_task())
                    self.assertEqual(runner.config.OS_ACTION_POINT_PRESERVE, 200)
                    self.assertEqual(runner._meow_target_zone_tokens(), [22])

                handler = (runner._meow_handle_stay_in_zone if stay_in_zone
                           else runner._meow_handle_traditional_zone)
                handler.side_effect = check_task
                self.assertTrue(runner._run_scheduled_coin_task_once(
                    'OpsiMeowfficerFarming', 200, fresh_ap=fresh_ap, meow_target_zone=zone,
                ))

                if stay_in_zone:
                    handler.assert_called_once_with(zone, fresh_ap=fresh_ap)
                else:
                    handler.assert_called_once_with(zone)
                self.assertEqual(runner.config.OpsiMeowfficerFarming_TargetZone, '44')
                self.assert_restored(runner, owner, bound)

    def test_legacy_fresh_ap_positional_and_keyword_calls(self):
        for positional in (False, True):
            with self.subTest(positional=positional):
                runner = self.make_runner()
                fresh_ap = (816, 166)
                args, kwargs = ((fresh_ap,), {}) if positional else ((), {'fresh_ap': fresh_ap})

                self.assertTrue(runner._run_scheduled_coin_task_once(
                    'OpsiMeowfficerFarming', 200, *args, **kwargs,
                ))

                runner._meow_handle_stay_in_zone.assert_called_once_with(
                    runner.name_to_zone('44'), fresh_ap=fresh_ap,
                )

    def test_failure_restores_target_preserve_and_task(self):
        runner = self.make_runner()
        owner, bound = runner.config.task, dict(runner.config.bound)
        runner._meow_handle_stay_in_zone.side_effect = GameStuckError('游戏交互失败')

        with self.assertRaisesRegex(GameStuckError, '游戏交互失败'):
            runner._run_scheduled_coin_task_once(
                'OpsiMeowfficerFarming', 200, meow_target_zone=runner.name_to_zone('22'),
            )

        self.assert_restored(runner, owner, bound)

    def test_month_end_cleanup_runs_through_real_dispatch_to_completion(self):
        for target in ('0', '22'):
            with self.subTest(target=target):
                runner = self.make_runner()
                owner, bound = runner.config.task, dict(runner.config.bound)
                deep_set(runner.config.data, keys=runner.CONFIG_PATH_MONTH_END_MEOW_TARGET_ZONE, value=target)
                runner._get_scheduling_action_point = Mock(side_effect=[
                    (900, 166), (800, 166), (700, 166), (200, 100), (200, 100),
                ])
                order = []

                def record_step(name):
                    order.append(name)
                    self.assertEqual(runner.config.task.command, name)
                    if name != 'OpsiShop':
                        self.assertEqual(runner.config.OS_ACTION_POINT_PRESERVE, 200)

                for name, method in (('OpsiStronghold', 'clear_stronghold'),
                                     ('OpsiObscure', 'clear_obscure'),
                                     ('OpsiAbyssal', 'clear_abyssal'),
                                     ('OpsiShop', 'perform_port_shop_purchase')):
                    setattr(runner, method, lambda name=name: record_step(name))
                runner._meow_handle_stay_in_zone.side_effect = (
                    lambda *args, **kwargs: record_step('OpsiMeowfficerFarming')
                )
                runner.notify_push = Mock()
                runner._delay_smart_scheduling_to_server_update = Mock()

                with (patch('module.os.tasks.scheduling.get_os_reset_remain', return_value=1),
                      self.assertRaises(TaskEnd)):
                    runner._run_month_end_cleanup(200, 117226, 1000, 166)

                self.assertEqual(order, ['OpsiStronghold', 'OpsiObscure', 'OpsiAbyssal',
                                         'OpsiMeowfficerFarming', 'OpsiShop'])
                runner._meow_handle_stay_in_zone.assert_called_once_with(
                    runner.name_to_zone('22' if target == '22' else '44'), fresh_ap=None,
                )
                self.assertFalse(runner._is_month_end_cleanup_first_run())
                runner.notify_push.assert_called_once()
                runner._delay_smart_scheduling_to_server_update.assert_called_once_with('月末清理行动力已完成')
                self.assert_restored(runner, owner, bound)

    def test_no_content_result_is_preserved(self):
        runner = self.make_runner()
        owner, bound = runner.config.task, dict(runner.config.bound)

        def no_content(*args, **kwargs):
            runner._smart_scheduling_no_content_task = 'OpsiMeowfficerFarming'

        runner._meow_handle_stay_in_zone.side_effect = no_content

        self.assertFalse(runner._run_scheduled_coin_task_once(
            'OpsiMeowfficerFarming', 200, meow_target_zone=runner.name_to_zone('22'),
        ))

        self.assertIsNone(runner._smart_scheduling_no_content_task)
        self.assert_restored(runner, owner, bound)

    def test_nested_overflow_keeps_resource_limits_and_forwards_zone(self):
        runner = self.make_runner()
        owner, bound = runner.config.task, dict(runner.config.bound)
        zone = runner.name_to_zone('22')
        fresh_ap = (190, 190)
        box_use = runner.config.OS_ACTION_POINT_BOX_USE
        buy_limit = runner.config.OpsiGeneral_BuyActionPointLimit

        def check_limits(*args, **kwargs):
            self.assertTrue(runner.is_running_prevent_action_point_overflow_task())
            self.assertTrue(runner.is_running_smart_scheduling_task())
            self.assertFalse(runner.config.OS_ACTION_POINT_BOX_USE)
            self.assertEqual(runner.config.OpsiGeneral_BuyActionPointLimit, 0)
            self.assertEqual(runner.config.OS_ACTION_POINT_PRESERVE, 0)

        runner._meow_handle_stay_in_zone.side_effect = check_limits
        with runner.config.temporary(OS_ACTION_POINT_BOX_USE=False, OpsiGeneral_BuyActionPointLimit=0):
            result = runner._run_with_prevent_action_point_overflow_context(
                'OpsiScheduling', runner._run_scheduled_coin_task_once,
                'OpsiMeowfficerFarming', 0, fresh_ap=fresh_ap, meow_target_zone=zone,
            )

        self.assertTrue(result)
        runner._meow_handle_stay_in_zone.assert_called_once_with(zone, fresh_ap=fresh_ap)
        self.assertEqual(runner.config.OS_ACTION_POINT_BOX_USE, box_use)
        self.assertEqual(runner.config.OpsiGeneral_BuyActionPointLimit, buy_limit)
        self.assert_restored(runner, owner, bound)


class TestMonthEndMeowTargetZoneParsing(unittest.TestCase):
    """月末清理耄耋相接指定海域的解析：非单个有效海域一律按 0 处理。"""

    def make_scheduling(self, raw):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = MonthEndCleanupConfig()
        scheduling.config.cross_get = Mock(return_value=raw)
        scheduling.name_to_zone = Mock()
        return scheduling

    @staticmethod
    def make_zone(zone_id=45, is_port=False):
        zone = Mock()
        zone.zone_id = zone_id
        zone.is_port = is_port
        return zone

    def test_unset_values_return_none(self):
        for raw in ('0', 0, '', '  ', None):
            with self.subTest(raw=raw):
                scheduling = self.make_scheduling(raw)

                self.assertIsNone(scheduling._get_month_end_meow_target_zone())
                scheduling.name_to_zone.assert_not_called()

    def test_single_zone_id_is_resolved(self):
        zone = self.make_zone(45)
        scheduling = self.make_scheduling('45')
        scheduling.name_to_zone.return_value = zone

        self.assertIs(scheduling._get_month_end_meow_target_zone(), zone)
        scheduling.name_to_zone.assert_called_once_with('45')

    def test_zone_name_is_resolved(self):
        zone = self.make_zone(44)
        scheduling = self.make_scheduling('NA海域东南E')
        scheduling.name_to_zone.return_value = zone

        self.assertIs(scheduling._get_month_end_meow_target_zone(), zone)

    def test_multiple_tokens_return_none(self):
        for raw in ('44,45', '44，45', '44, 45', '44,'):
            with self.subTest(raw=raw):
                scheduling = self.make_scheduling(raw)

                self.assertIsNone(scheduling._get_month_end_meow_target_zone())
                scheduling.name_to_zone.assert_not_called()

    def test_unknown_zone_returns_none(self):
        scheduling = self.make_scheduling('999')
        scheduling.name_to_zone.side_effect = ScriptError('Unable to find OS globe zone: 999')

        self.assertIsNone(scheduling._get_month_end_meow_target_zone())

    def test_port_zone_returns_none(self):
        scheduling = self.make_scheduling('5')
        scheduling.name_to_zone.return_value = self.make_zone(5, is_port=True)

        self.assertIsNone(scheduling._get_month_end_meow_target_zone())


class TestScheduledMeowTargetZoneOverride(unittest.TestCase):
    """指定海域经实例属性传入短猫代跑，代跑结束后清理。"""

    def make_scheduling(self, runner):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = MagicMock()
        scheduling.config.OS_ACTION_POINT_PRESERVE = 0
        scheduling.run_meowfficer_farming_once = Mock()
        scheduling._run_with_opsi_task_context = runner
        return scheduling

    def test_override_visible_during_delegation_and_cleared_after(self):
        zone = Mock()
        seen = []

        def runner(task_name, func, **kwargs):
            seen.append(scheduling._meow_target_zone_override)
            return True

        scheduling = self.make_scheduling(runner)

        scheduling._run_scheduled_meowfficer_farming(100, target_zone=zone)

        self.assertEqual(seen, [zone])
        self.assertIsNone(scheduling._meow_target_zone_override)

    def test_override_cleared_when_delegation_raises(self):
        def runner(task_name, func, **kwargs):
            raise RuntimeError('boom')

        scheduling = self.make_scheduling(runner)

        with self.assertRaises(RuntimeError):
            scheduling._run_scheduled_meowfficer_farming(100, target_zone=Mock())

        self.assertIsNone(scheduling._meow_target_zone_override)


class TestMeowTargetZoneOverrideTokens(unittest.TestCase):
    """月末清理指定海域覆盖短猫自身的指定海域输入。"""

    def make_meow(self, configured, override=None):
        meow = MeowfficerTargetZoneMixin()
        meow.config = Mock()
        meow.config.OpsiMeowfficerFarming_TargetZone = configured
        if override is not None:
            meow._meow_target_zone_override = override
        return meow

    def test_override_replaces_user_input(self):
        zone = Mock()
        zone.zone_id = 45
        meow = self.make_meow('42,55', override=zone)

        self.assertEqual(meow._meow_target_zone_tokens(), [45])

    def test_without_override_user_input_is_used(self):
        meow = self.make_meow('42,55')

        self.assertEqual(meow._meow_target_zone_tokens(), ['42', '55'])

    def test_cleared_override_returns_to_user_input(self):
        zone = Mock()
        zone.zone_id = 45
        meow = self.make_meow('42', override=zone)
        meow._meow_target_zone_override = None

        self.assertEqual(meow._meow_target_zone_tokens(), ['42'])


class TestMonthEndCleanupCycle(unittest.TestCase):
    """首次清理状态按大世界重置周期持久化，与清理开关和运行间隔无关。"""

    def make_scheduling(self, state=None):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = MonthEndCleanupConfig(state)
        return scheduling

    def sync_cycle(self, scheduling, reset):
        with patch('module.os.tasks.scheduling.get_os_reset_cycle', return_value=reset):
            scheduling._reset_month_end_cleanup_first_run_if_new_month()

    def test_legacy_completed_flag_is_preserved_when_adding_cycle(self):
        scheduling = self.make_scheduling({
            OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN: False,
        })
        reset = '2026-11-01T00:00:00+08:00'

        self.sync_cycle(scheduling, reset)

        self.assertFalse(scheduling._is_month_end_cleanup_first_run())
        self.assertEqual(
            scheduling._get_smart_scheduling_state_value(OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_CYCLE),
            reset,
        )

    def test_first_run_defaults_to_true_when_state_is_empty(self):
        scheduling = self.make_scheduling()

        self.sync_cycle(scheduling, '2026-11-01T00:00:00+08:00')

        self.assertTrue(scheduling._is_month_end_cleanup_first_run())

    def test_next_month_resets_flag_without_an_intermediate_run(self):
        scheduling = self.make_scheduling({
            OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN: False,
            OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_CYCLE: '2026-11-01T00:00:00+08:00',
        })

        # 两次运行都处于月末窗口，不能依靠清理模式曾退出判断是否跨月。
        with patch.object(scheduling, '_is_month_end_cleanup_active', return_value=True):
            self.sync_cycle(scheduling, '2026-12-01T00:00:00+08:00')

        self.assertTrue(scheduling._is_month_end_cleanup_first_run())

    def test_same_month_switch_changes_keep_completed_flag(self):
        reset = '2026-11-01T00:00:00+08:00'
        scheduling = self.make_scheduling({
            OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN: False,
            OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_CYCLE: reset,
        })

        for enabled in (False, True):
            with patch.object(scheduling, '_is_month_end_cleanup_active', return_value=enabled):
                self.sync_cycle(scheduling, reset)
            self.assertFalse(scheduling._is_month_end_cleanup_first_run())

        self.assertEqual(scheduling.config.save_count, 0)

    def test_legacy_local_reset_survives_timezone_change_until_server_rollover(self):
        cycle_key = OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_CYCLE
        scheduling = self.make_scheduling({
            OpsiScheduling.STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN: False,
            cycle_key: '2026-11-30T08:00:00',
        })
        now = datetime(2026, 11, 30, 15, 59, 59, tzinfo=timezone.utc)
        local_timezone = timezone(timedelta(hours=9))

        def current_time(tz=None):
            if tz is not None:
                return now.astimezone(tz)
            return now.astimezone(local_timezone).replace(tzinfo=None)

        with (
            patch('module.config.utils.current_time', side_effect=current_time),
            patch('module.config.utils.server_timezone', return_value=timedelta(hours=8)),
        ):
            scheduling._reset_month_end_cleanup_first_run_if_new_month()
            self.assertFalse(scheduling._is_month_end_cleanup_first_run())
            self.assertEqual(scheduling._get_smart_scheduling_state_value(cycle_key),
                             '2026-12-01T00:00:00+08:00')

            local_timezone = timezone(timedelta(hours=-8))
            scheduling._reset_month_end_cleanup_first_run_if_new_month()
            self.assertFalse(scheduling._is_month_end_cleanup_first_run())
            self.assertEqual(scheduling.config.save_count, 1)

            now += timedelta(seconds=1)
            scheduling._reset_month_end_cleanup_first_run_if_new_month()
            self.assertTrue(scheduling._is_month_end_cleanup_first_run())
            self.assertEqual(scheduling._get_smart_scheduling_state_value(cycle_key),
                             '2027-01-01T00:00:00+08:00')


class TestMonthEndCleanupIdleScheduling(unittest.TestCase):
    """月末清理达到保留线后始终延后，不能回到普通侵蚀 1 消耗剩余行动力。"""

    def make_scheduling(self, total_ap):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = MonthEndCleanupConfig()
        scheduling.is_running_prevent_action_point_overflow_task = Mock(return_value=False)
        scheduling.get_yellow_coins = Mock(return_value=60000)
        scheduling.get_routine_yellow_coins = Mock(return_value=60000)
        scheduling._get_scheduling_action_point = Mock(return_value=(total_ap, 100))
        scheduling._reset_month_end_cleanup_first_run_if_new_month = Mock()
        scheduling._is_month_end_cleanup_active = Mock(return_value=True)
        scheduling._get_month_end_action_point_preserve = Mock(return_value=1000)
        scheduling._run_month_end_cleanup = Mock()
        scheduling._get_smart_scheduling_operation_coins_preserve = Mock(return_value=40000)
        scheduling._get_effective_cl1_ap_preserve = Mock(return_value=200)
        scheduling._get_coin_task_action_point_preserve = Mock(return_value=200)
        scheduling._is_coin_target_scheduling_enabled = Mock(return_value=True)
        scheduling._execute_hazard1_leveling = Mock()
        scheduling._delay_smart_scheduling_with_minutes = Mock()
        scheduling._delay_smart_scheduling_to_server_update = Mock()
        return scheduling

    def run_idle_scheduling(self, scheduling, remain):
        with (
            patch('module.os.tasks.scheduling.get_os_reset_remain', return_value=remain),
            self.assertRaises(TaskEnd),
        ):
            scheduling.run_smart_scheduling_once()
        scheduling._run_month_end_cleanup.assert_not_called()
        scheduling._execute_hazard1_leveling.assert_not_called()

    def test_penultimate_day_waits_for_server_update_at_or_below_preserve(self):
        for total_ap in (500, 1000):
            with self.subTest(total_ap=total_ap):
                scheduling = self.make_scheduling(total_ap)

                self.run_idle_scheduling(scheduling, remain=1)

                scheduling._delay_smart_scheduling_to_server_update.assert_called_once_with('月末清理行动力不足')
                scheduling._delay_smart_scheduling_with_minutes.assert_not_called()

    def test_last_day_waits_two_hours_at_or_below_preserve(self):
        for total_ap in (500, 1000):
            with self.subTest(total_ap=total_ap):
                scheduling = self.make_scheduling(total_ap)

                self.run_idle_scheduling(scheduling, remain=0)

                scheduling._delay_smart_scheduling_with_minutes.assert_called_once_with(
                    '月末清理行动力不足（月底最后一天）', 120,
                )
                scheduling._delay_smart_scheduling_to_server_update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
