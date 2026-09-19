import unittest
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.os_run import OSCampaignRun
from module.config.config import Function, TaskEnd
from module.config.deep import deep_get, deep_set
from module.config.time_source import now as current_time
from module.config.utils import (
    get_os_next_reset,
    get_os_next_reset_after,
    get_os_reset_remain_days,
)
from module.os.operation_siren import OperationSiren
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow
from module.os.tasks.scheduling import OpsiScheduling
from module.os.tasks.stronghold import OpsiStronghold
from module.os_handler.action_point import ActionPointLimit
from module.os_handler.os_status import OSStatus


class TestOpsiTaskCooldown(unittest.TestCase):
    """到期任务不能被当成冷却任务，防止代理任务反复写回过去的运行时间。"""

    def setUp(self):
        self.now = datetime(2026, 9, 8, 7, 18, 17)
        self.update = datetime(2026, 9, 9)
        self.status = OSStatus.__new__(OSStatus)
        self.status.config = SimpleNamespace(pending_task=[], waiting_task=[])
        for name, value in (
            ('current_time', self.now),
            ('get_server_next_update', self.update),
        ):
            patcher = patch(f'module.os_handler.os_status.{name}', return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def make_task(next_run, command='OpsiDaily', enabled=True):
        return Function({'Scheduler': {
            'Command': command,
            'Enable': enabled,
            'NextRun': next_run,
        }})

    def test_expired_or_due_tasks_are_not_cooling_down(self):
        for next_run in (datetime(2026, 9, 7), self.now - timedelta(seconds=1), self.now):
            # 队列是较早生成的快照，等待队列里的任务也可能已经到期。
            for queue in ('pending_task', 'waiting_task'):
                with self.subTest(next_run=next_run, queue=queue):
                    self.status.config.pending_task = []
                    self.status.config.waiting_task = []
                    setattr(self.status.config, queue, [self.make_task(next_run)])
                    self.assertIsNone(self.status.nearest_task_cooling_down)

    def test_future_cooldown_keeps_the_sixty_minute_boundary(self):
        for seconds, expected in ((1, True), (3600, True), (3601, False)):
            with self.subTest(seconds=seconds):
                task = self.make_task(self.now + timedelta(seconds=seconds))
                self.status.config.waiting_task = [task]
                result = self.status.nearest_task_cooling_down
                self.assertIs(result, task if expected else None)

    def test_selects_nearest_enabled_cooldown_and_excludes_server_reset(self):
        # 将日更设在一小时内，确认它仍不会被误认为短期冷却。
        update = self.now + timedelta(minutes=10)
        nearest = self.make_task(self.now + timedelta(minutes=20), 'OpsiObscure')
        self.status.config.pending_task = [self.make_task(datetime(2026, 9, 7))]
        self.status.config.waiting_task = [
            self.make_task(self.now + timedelta(minutes=50), 'OpsiAbyssal'),
            self.make_task(update),
            self.make_task(self.now + timedelta(minutes=1), enabled=False),
            self.make_task(self.now + timedelta(minutes=2), 'Research'),
            nearest,
        ]
        with patch('module.os_handler.os_status.get_server_next_update', return_value=update):
            self.assertIs(self.status.nearest_task_cooling_down, nearest)

    def test_prevent_overflow_runs_meow_instead_of_requeueing_in_the_past(self):
        runner = OperationSiren.__new__(OperationSiren)
        owner = self.make_task(datetime(2026, 9, 7), 'OpsiPreventActionPointOverflow')
        runner.config = SimpleNamespace(
            task=owner,
            data={},
            pending_task=[owner, self.make_task(datetime(2026, 9, 7))],
            waiting_task=[],
            OpsiMeowfficerFarming_HazardLevel=5,
            OpsiMeowfficerFarming_TargetZone=0,
            OpsiMeowfficerFarming_StayInZone=False,
            OpsiTarget_TargetFarming=False,
            is_task_enabled=Mock(return_value=True),
            override=Mock(),
            bind=Mock(),
            temporary=lambda **kwargs: nullcontext(),
            task_delay=Mock(),
            task_stop=Mock(side_effect=TaskEnd),
        )
        with (
            patch.object(runner, '_get_prevent_action_point_overflow_thresholds', return_value=(200, 30)),
            patch.object(runner, '_get_prevent_action_point_overflow_task', return_value='OpsiMeowfficerFarming'),
            patch.object(runner, '_get_current_action_point_for_overflow', side_effect=[300, 20]),
            patch.object(runner, 'update_prevent_action_point_overflow_schedule') as reschedule,
            patch.object(runner, 'is_in_opsi_explore', return_value=False),
            patch.object(runner, '_meow_ap_check', return_value=True),
            patch.object(runner, '_meow_handle_normal_search') as search,
            patch('module.os.tasks.meowfficer_farming.get_os_reset_remain', return_value=22),
            patch('module.base.debug_clip.cleanup_clips_if_due'),
        ):
            with self.assertRaises(TaskEnd):
                runner.run_prevent_action_point_overflow()

        # 保留真实的代理上下文和短猫准备逻辑，仅替换设备交互。
        search.assert_called_once_with()
        runner.config.task_delay.assert_not_called()
        reschedule.assert_called_once_with(current_ap=20, enable=True)
        self.assertIs(runner.config.task, owner)
        self.assertFalse(runner.is_running_prevent_action_point_overflow_task())
        self.assertFalse(runner.is_running_smart_scheduling_task())
        self.assertFalse(hasattr(runner.config, '_opsi_task_context'))


class SmartSchedulingConfig:
    """仅提供智能调度与防溢出测试所需的配置接口。"""

    def __init__(self, task_command='OpsiScheduling'):
        self.task = SimpleNamespace(command=task_command)
        self.task_delay_calls = []

    def cross_get(self, keys, default=None):
        if keys == 'OpsiScheduling.Scheduler.ServerUpdate':
            return '00:00'
        return default

    def task_delay(self, *args, **kwargs):
        self.task_delay_calls.append((args, kwargs))

    @staticmethod
    def temporary(**kwargs):
        return nullcontext()

    @staticmethod
    def task_stop():
        raise TaskEnd


class MeowPreserveConfig:
    """提供智能调度代跑短猫时的共享行动力保留状态。"""

    def __init__(self):
        self.OS_ACTION_POINT_PRESERVE = 180

    @contextmanager
    def temporary(self, **kwargs):
        backup = {key: getattr(self, key) for key in kwargs}
        for key, value in kwargs.items():
            setattr(self, key, value)
        try:
            yield
        finally:
            for key, value in backup.items():
                setattr(self, key, value)

    @staticmethod
    def task_stop():
        raise AssertionError('达到短猫保留值不应停止智能调度')


class SchedulingMeowHarness:
    """复现短猫达到自身阈值后异常冒泡的最小调度环境。"""

    TASK_NAME_MEOWFFICER_FARMING = OpsiScheduling.TASK_NAME_MEOWFFICER_FARMING

    def __init__(self):
        self.config = MeowPreserveConfig()
        self.executed_task_name = None

    def run_meowfficer_farming_once(self, ap_preserve):
        self.config.OS_ACTION_POINT_PRESERVE = ap_preserve
        raise ActionPointLimit(total=5985, preserve=ap_preserve)

    def _run_with_opsi_task_context(self, task_name, func, **kwargs):
        self.executed_task_name = task_name
        return func(**kwargs)

    def run_scheduled_meowfficer_farming(self, ap_preserve):
        return OpsiScheduling._run_scheduled_meowfficer_farming(self, ap_preserve)


class SchedulingMeowCostLimitHarness(SchedulingMeowHarness):
    def run_meowfficer_farming_once(self, ap_preserve):
        self.config.OS_ACTION_POINT_PRESERVE = ap_preserve
        raise ActionPointLimit(current=15, total=15, cost=120)


class TestSmartSchedulingMeowPreserve(unittest.TestCase):
    def test_returns_to_scheduling_and_restores_global_preserve_at_meow_limit(self):
        scheduling = SchedulingMeowHarness()

        scheduling.run_scheduled_meowfficer_farming(ap_preserve=6000)

        self.assertEqual(
            scheduling.executed_task_name,
            OpsiScheduling.TASK_NAME_MEOWFFICER_FARMING,
        )
        self.assertEqual(scheduling.config.OS_ACTION_POINT_PRESERVE, 180)

    def test_propagates_real_ap_shortage_and_still_restores_global_preserve(self):
        scheduling = SchedulingMeowCostLimitHarness()

        with self.assertRaises(ActionPointLimit):
            scheduling.run_scheduled_meowfficer_farming(ap_preserve=6000)

        self.assertEqual(scheduling.config.OS_ACTION_POINT_PRESERVE, 180)


class TestSmartSchedulingExploreDelay(unittest.TestCase):
    def test_skips_campaign_initialization_when_opsi_explore_is_in_progress(self):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = SmartSchedulingConfig()

        with (
            patch.object(runner, 'is_in_opsi_explore', return_value=True),
            patch.object(runner, '_run_opsi_task_with_ap_overflow_guard') as run_task,
        ):
            with self.assertRaises(TaskEnd):
                runner.opsi_scheduling()

        self.assertEqual(
            runner.config.task_delay_calls,
            [
                (
                    (),
                    {
                        'server_update': '00:00',
                        'task': 'OpsiScheduling',
                    },
                )
            ],
        )
        run_task.assert_not_called()

    def test_initializes_campaign_when_opsi_explore_is_complete(self):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = SmartSchedulingConfig()

        with (
            patch.object(runner, 'is_in_opsi_explore', return_value=False),
            patch.object(runner, '_run_opsi_task_with_ap_overflow_guard') as run_task,
        ):
            runner.opsi_scheduling()

        self.assertEqual(runner.config.task_delay_calls, [])
        run_task.assert_called_once()

    def test_delays_scheduling_when_opsi_explore_is_in_progress(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = SmartSchedulingConfig()

        with (
            patch.object(scheduling, 'is_in_opsi_explore', return_value=True),
            patch.object(scheduling, 'is_smart_scheduling_enabled') as enabled,
        ):
            with self.assertRaises(TaskEnd):
                scheduling.run_smart_scheduling()

        self.assertEqual(
            scheduling.config.task_delay_calls,
            [
                (
                    (),
                    {
                        'server_update': '00:00',
                        'task': 'OpsiScheduling',
                    },
                )
            ],
        )
        enabled.assert_not_called()

    def test_does_not_delay_when_smart_scheduling_is_normally_disabled(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = SmartSchedulingConfig()

        with (
            patch.object(scheduling, 'is_in_opsi_explore', return_value=False),
            patch.object(scheduling, 'is_smart_scheduling_enabled', return_value=False),
        ):
            scheduling.run_smart_scheduling()

        self.assertEqual(scheduling.config.task_delay_calls, [])

    def test_prevent_overflow_delays_itself_during_opsi_explore(self):
        prevent = OpsiPreventActionPointOverflow.__new__(OpsiPreventActionPointOverflow)
        prevent.config = SmartSchedulingConfig(
            task_command='OpsiPreventActionPointOverflow'
        )

        with (
            patch.object(
                prevent,
                '_get_prevent_action_point_overflow_thresholds',
                return_value=(200, 0),
            ),
            patch.object(
                prevent,
                '_get_prevent_action_point_overflow_task',
                return_value='OpsiScheduling',
            ),
            patch.object(
                prevent,
                '_get_current_action_point_for_overflow',
                return_value=200,
            ),
            patch.object(prevent, 'is_in_opsi_explore', return_value=True),
            patch.object(
                prevent,
                '_run_with_opsi_task_context',
                side_effect=lambda task, func, *args, **kwargs: func(*args, **kwargs),
            ),
            patch.object(
                prevent,
                'get_yellow_coins',
                side_effect=AssertionError('开荒期间不应进入智能调度决策'),
            ),
        ):
            with self.assertRaises(TaskEnd):
                prevent.run_prevent_action_point_overflow()

        self.assertEqual(
            prevent.config.task_delay_calls,
            [
                (
                    (),
                    {
                        'server_update': True,
                        'task': 'OpsiPreventActionPointOverflow',
                    },
                )
            ],
        )


class StrongholdPostponeConfig(SmartSchedulingConfig):
    """仅提供塞壬要塞推迟检查所需的配置读写接口。"""

    def __init__(self, state=None):
        super().__init__()
        self.data = {'OpsiScheduling': {'Storage': {'Storage': dict(state or {})}}}
        self.modified = {}
        self.OpsiStronghold_SubmarineEveryCombat = False

    def cross_get(self, keys, default=None):
        if keys == 'OpsiScheduling.Storage.Storage':
            return dict(deep_get(self.data, keys=keys, default={}) or {})
        return super().cross_get(keys, default=default)

    def save(self):
        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)
        self.modified.clear()

    @staticmethod
    def multi_set():
        return nullcontext()


class TestStrongholdCheckPostpone(unittest.TestCase):
    """塞壬要塞全部清除后推迟检查，避免每轮补黄币都重扫全球地图。"""

    NEXT_CHECK_KEY = OpsiScheduling.STATE_KEY_STRONGHOLD_NEXT_CHECK

    def make_scheduling(self, state=None, cls=OpsiScheduling):
        scheduling = cls.__new__(cls)
        scheduling.config = StrongholdPostponeConfig(state=state)
        return scheduling

    @staticmethod
    def state_of(scheduling):
        return scheduling.config.cross_get('OpsiScheduling.Storage.Storage')

    def dispatch(self, scheduling, coin_tasks=('OpsiStronghold', 'OpsiObscure')):
        """派发一轮补黄币，返回真正被代理执行的任务名。"""
        executed = []

        def run_once(task_name, ap_preserve):
            executed.append(task_name)
            return True

        with (
            patch.object(scheduling, '_get_enabled_coin_tasks', return_value=list(coin_tasks)),
            patch.object(scheduling, '_run_scheduled_coin_task_once', side_effect=run_once),
            patch.object(scheduling, '_notify_coin_task_proxy'),
        ):
            scheduling._dispatch_coin_task(
                yellow_coins=1000,
                total_ap=5000,
                coin_target=2000,
                meow_ap_preserve=1000,
            )
        return executed

    def test_skips_stronghold_while_check_is_postponed(self):
        future = current_time() + timedelta(days=3)
        scheduling = self.make_scheduling({self.NEXT_CHECK_KEY: future.isoformat()})

        executed = self.dispatch(scheduling)

        self.assertEqual(executed, ['OpsiObscure'])
        self.assertEqual(self.state_of(scheduling)[self.NEXT_CHECK_KEY], future.isoformat())

    def test_searches_stronghold_again_when_postpone_time_has_passed(self):
        scheduling = self.make_scheduling({
            self.NEXT_CHECK_KEY: (current_time() - timedelta(hours=1)).isoformat(),
        })

        executed = self.dispatch(scheduling)

        self.assertEqual(executed, ['OpsiStronghold'])
        self.assertNotIn(self.NEXT_CHECK_KEY, self.state_of(scheduling))

    def test_ends_round_without_scanning_when_only_postponed_stronghold_is_enabled(self):
        scheduling = self.make_scheduling({
            self.NEXT_CHECK_KEY: (current_time() + timedelta(days=3)).isoformat(),
        })

        with self.assertRaises(TaskEnd):
            self.dispatch(scheduling, coin_tasks=('OpsiStronghold',))

        self.assertEqual(
            scheduling.config.task_delay_calls,
            [((), {'server_update': '00:00', 'task': 'OpsiScheduling'})],
        )

    def test_ignores_broken_state_and_checks_stronghold_again(self):
        scheduling = self.make_scheduling({self.NEXT_CHECK_KEY: 'not-a-time'})

        executed = self.dispatch(scheduling)

        self.assertEqual(executed, ['OpsiStronghold'])
        self.assertNotIn(self.NEXT_CHECK_KEY, self.state_of(scheduling))

    def test_check_time_uses_earlier_of_weekly_and_monthly_refresh(self):
        # 无论要塞来自每周刷新还是每月重置，都取更早的那个时间点
        earlier = datetime(2026, 9, 21, 0, 0)
        later = datetime(2026, 10, 1, 0, 0)
        scheduling = self.make_scheduling()

        for name, weekly_value, monthly_value in (
            ('每周刷新在前', earlier, later),
            ('每月重置在前', later, earlier),
        ):
            with self.subTest(name):
                with (
                    patch(
                        'module.os.tasks.scheduling.get_nearest_weekday_date',
                        return_value=weekly_value,
                    ),
                    patch(
                        'module.os.tasks.scheduling.get_os_next_reset',
                        return_value=monthly_value,
                    ),
                ):
                    self.assertEqual(
                        scheduling._get_next_stronghold_check_time(),
                        earlier + OpsiScheduling.RESET_CHECK_GRACE,
                    )

    def assert_postponed_by_clear_stronghold(self, zones):
        """运行一次要塞清理，确认写入了下次检查时间。"""
        stronghold = self.make_scheduling(cls=OpsiStronghold)
        weekly = current_time() + timedelta(days=2)
        monthly = current_time() + timedelta(days=20)

        with (
            patch.object(stronghold, 'cl1_ap_preserve'),
            patch.object(stronghold, 'os_map_goto_globe'),
            patch.object(stronghold, 'globe_update'),
            patch.object(stronghold, 'find_siren_stronghold', side_effect=zones),
            patch.object(stronghold, 'os_globe_goto_map'),
            patch.object(stronghold, 'globe_enter'),
            patch.object(stronghold, 'zone_init'),
            patch.object(stronghold, 'os_order_execute'),
            patch.object(stronghold, 'run_stronghold'),
            patch.object(stronghold, 'handle_fleet_repair_by_config'),
            patch.object(stronghold, 'handle_fleet_resolve'),
            patch.object(stronghold, '_handle_coin_task_no_content', return_value=True),
            patch(
                'module.os.tasks.scheduling.get_nearest_weekday_date',
                return_value=weekly,
            ),
            patch('module.os.tasks.scheduling.get_os_next_reset', return_value=monthly),
        ):
            stronghold.clear_stronghold()

        expected = (min(weekly, monthly) + OpsiScheduling.RESET_CHECK_GRACE).isoformat()
        self.assertEqual(self.state_of(stronghold)[self.NEXT_CHECK_KEY], expected)

    def test_records_postpone_when_no_stronghold_is_found(self):
        self.assert_postponed_by_clear_stronghold(zones=[None])

    def test_records_postpone_after_clearing_the_last_stronghold(self):
        self.assert_postponed_by_clear_stronghold(zones=[Mock(), None])


class CoinCheckDelayConfig(StrongholdPostponeConfig):
    """提供隐秘/深渊延迟检查天数所需的配置接口。"""

    def __init__(self, state=None, delay_days=0, task_command='OpsiScheduling'):
        super().__init__(state=state)
        self.delay_days = delay_days
        self.task = SimpleNamespace(command=task_command)

    def cross_get(self, keys, default=None):
        if keys == 'OpsiScheduling.OpsiScheduling.ObscureAbyssalCheckDelayDays':
            return self.delay_days
        return super().cross_get(keys, default=default)


class TestObscureAbyssalCheckDelay(unittest.TestCase):
    """隐秘/深渊打完后延迟指定天数再检查，0 表示每轮都检查。"""

    OBSCURE_KEY = OpsiScheduling.STATE_KEY_OBSCURE_CLEARED_AT
    ABYSSAL_KEY = OpsiScheduling.STATE_KEY_ABYSSAL_CLEARED_AT

    def make_scheduling(self, state=None, delay_days=0, task_command='OpsiScheduling'):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = CoinCheckDelayConfig(
            state=state,
            delay_days=delay_days,
            task_command=task_command,
        )
        return scheduling

    @staticmethod
    def state_of(scheduling):
        return scheduling.config.cross_get('OpsiScheduling.Storage.Storage')

    def dispatch(self, scheduling, coin_tasks=('OpsiObscure', 'OpsiAbyssal')):
        """派发一轮补黄币，返回真正被代理执行的任务名。"""
        executed = []

        def run_once(task_name, ap_preserve):
            executed.append(task_name)
            return True

        with (
            patch.object(scheduling, '_get_enabled_coin_tasks', return_value=list(coin_tasks)),
            patch.object(scheduling, '_run_scheduled_coin_task_once', side_effect=run_once),
            patch.object(scheduling, '_notify_coin_task_proxy'),
        ):
            scheduling._dispatch_coin_task(
                yellow_coins=1000,
                total_ap=5000,
                coin_target=2000,
                meow_ap_preserve=1000,
            )
        return executed

    def handle_no_content(self, scheduling, task_display, log_message):
        """走真实的无内容处理函数，捕获结束任务时抛出的 TaskEnd。"""
        with (
            patch.object(scheduling, 'is_smart_scheduling_enabled', return_value=False),
            self.assertRaises(TaskEnd),
        ):
            scheduling._handle_coin_task_no_content(task_display, log_message)

    def test_zero_delay_checks_every_round_despite_cleared_state(self):
        scheduling = self.make_scheduling(
            state={
                self.OBSCURE_KEY: (current_time() - timedelta(hours=1)).isoformat(),
                self.ABYSSAL_KEY: (current_time() - timedelta(hours=2)).isoformat(),
            },
            delay_days=0,
        )

        # 每轮派发只代理执行一个任务，两个任务分别到期待派发
        self.assertEqual(self.dispatch(scheduling, coin_tasks=('OpsiObscure',)), ['OpsiObscure'])
        self.assertEqual(self.dispatch(scheduling, coin_tasks=('OpsiAbyssal',)), ['OpsiAbyssal'])

    def test_skips_both_obscure_and_abyssal_within_delay_days(self):
        scheduling = self.make_scheduling(
            state={
                self.OBSCURE_KEY: (current_time() - timedelta(hours=1)).isoformat(),
                self.ABYSSAL_KEY: (current_time() - timedelta(hours=2)).isoformat(),
            },
            delay_days=3,
        )

        with self.assertRaises(TaskEnd):
            self.dispatch(scheduling)

        # 推迟期内直接跳过，打完记录保持不变
        state = self.state_of(scheduling)
        self.assertIn(self.OBSCURE_KEY, state)
        self.assertIn(self.ABYSSAL_KEY, state)
        self.assertEqual(
            scheduling.config.task_delay_calls,
            [((), {'server_update': '00:00', 'task': 'OpsiScheduling'})],
        )

    def test_checks_again_after_delay_days_have_passed(self):
        scheduling = self.make_scheduling(
            state={self.OBSCURE_KEY: (current_time() - timedelta(days=4)).isoformat()},
            delay_days=3,
        )

        executed = self.dispatch(scheduling, coin_tasks=('OpsiObscure',))

        self.assertEqual(executed, ['OpsiObscure'])
        self.assertNotIn(self.OBSCURE_KEY, self.state_of(scheduling))

    def test_postpone_is_capped_at_next_monthly_reset(self):
        cleared_at = current_time() - timedelta(hours=1)
        scheduling = self.make_scheduling(
            state={self.OBSCURE_KEY: cleared_at.isoformat()},
            delay_days=30,
        )
        reset = current_time() + timedelta(days=5)

        with patch('module.os.tasks.scheduling.get_os_next_reset_after', return_value=reset):
            postpone = scheduling._get_coin_task_check_postpone_time('OpsiObscure')

        # 30 天太长，被下次大世界重置截断，重置后照常检查
        self.assertEqual(postpone, reset + OpsiScheduling.RESET_CHECK_GRACE)

    def test_postpone_uses_delay_days_before_reset(self):
        cleared_at = current_time() - timedelta(hours=1)
        scheduling = self.make_scheduling(
            state={self.ABYSSAL_KEY: cleared_at.isoformat()},
            delay_days=3,
        )
        reset = current_time() + timedelta(days=10)

        with patch('module.os.tasks.scheduling.get_os_next_reset_after', return_value=reset):
            postpone = scheduling._get_coin_task_check_postpone_time('OpsiAbyssal')

        self.assertEqual(postpone, cleared_at + timedelta(days=3))

    def test_ignores_broken_cleared_state_and_checks_again(self):
        scheduling = self.make_scheduling(
            state={self.ABYSSAL_KEY: 'not-a-time'},
            delay_days=3,
        )

        executed = self.dispatch(scheduling, coin_tasks=('OpsiAbyssal',))

        self.assertEqual(executed, ['OpsiAbyssal'])
        self.assertNotIn(self.ABYSSAL_KEY, self.state_of(scheduling))

    def test_records_cleared_time_when_storage_is_empty(self):
        now = datetime(2026, 9, 16, 12, 0, 0)
        for task_command, display, message, state_key in (
            ('OpsiObscure', '隐秘海域', '隐秘海域没有可执行内容', self.OBSCURE_KEY),
            ('OpsiAbyssal', '深渊坐标', '深渊坐标没有可执行内容', self.ABYSSAL_KEY),
        ):
            with self.subTest(task=task_command):
                scheduling = self.make_scheduling(delay_days=3, task_command=task_command)

                with patch('module.os.tasks.scheduling.current_time', return_value=now):
                    self.handle_no_content(scheduling, display, message)

                self.assertEqual(self.state_of(scheduling)[state_key], now.isoformat())

    def test_zero_delay_never_records_cleared_time(self):
        scheduling = self.make_scheduling(delay_days=0, task_command='OpsiAbyssal')

        with patch(
            'module.os.tasks.scheduling.current_time',
            return_value=datetime(2026, 9, 16, 12, 0, 0),
        ):
            self.handle_no_content(scheduling, '深渊坐标', '深渊坐标没有可执行内容')

        self.assertEqual(self.state_of(scheduling), {})

    def test_does_not_record_for_stronghold_and_meowfficer(self):
        now = datetime(2026, 9, 16, 12, 0, 0)
        for task_command, display, message in (
            ('OpsiStronghold', '塞壬要塞', '塞壬要塞没有可执行内容'),
            ('OpsiMeowfficerFarming', '耄耋相接', '耄耋相接没有可执行内容'),
        ):
            with self.subTest(task=task_command):
                scheduling = self.make_scheduling(delay_days=3, task_command=task_command)

                with patch('module.os.tasks.scheduling.current_time', return_value=now):
                    self.handle_no_content(scheduling, display, message)

                state = self.state_of(scheduling)
                self.assertNotIn(self.OBSCURE_KEY, state)
                self.assertNotIn(self.ABYSSAL_KEY, state)

    @staticmethod
    def next_reset_after(reset, following):
        """模拟真实实现：返回基准时间之后的第一（或第二）次重置。"""
        return lambda moment: reset if moment < reset else following

    def test_does_not_skip_past_the_monthly_reset(self):
        # 10-31 打空、延迟 3 天，11-01 重置会刷新隐秘/深渊，不能再顺延到 11-03
        cleared_at = datetime(2026, 10, 31, 10, 0)
        reset = datetime(2026, 11, 1, 0, 0)
        scheduling = self.make_scheduling(
            state={self.OBSCURE_KEY: cleared_at.isoformat()},
            delay_days=3,
        )
        next_reset_after = self.next_reset_after(reset, datetime(2026, 12, 1))

        with patch('module.os.tasks.scheduling.get_os_next_reset_after',
                   side_effect=next_reset_after):
            # 重置前：截止时间被截断到重置 + 缓冲
            with patch('module.os.tasks.scheduling.current_time',
                       return_value=datetime(2026, 10, 31, 12, 0)):
                self.assertEqual(
                    scheduling._get_coin_task_check_postpone_time('OpsiObscure'),
                    reset + OpsiScheduling.RESET_CHECK_GRACE,
                )
            # 重置后：到点必须恢复检查，而不是继续用到 11-03 的原始截止时间
            with patch('module.os.tasks.scheduling.current_time',
                       return_value=reset + OpsiScheduling.RESET_CHECK_GRACE):
                self.assertIsNone(
                    scheduling._get_coin_task_check_postpone_time('OpsiObscure')
                )

        self.assertNotIn(self.OBSCURE_KEY, self.state_of(scheduling))

    def test_checks_again_right_after_the_monthly_reset(self):
        cleared_at = datetime(2026, 10, 31, 10, 0)
        reset = datetime(2026, 11, 1, 0, 0)
        scheduling = self.make_scheduling(
            state={self.OBSCURE_KEY: cleared_at.isoformat()},
            delay_days=3,
        )

        with (
            patch('module.os.tasks.scheduling.current_time',
                  return_value=reset + OpsiScheduling.RESET_CHECK_GRACE),
            patch('module.os.tasks.scheduling.get_os_next_reset_after',
                  side_effect=self.next_reset_after(reset, datetime(2026, 12, 1))),
        ):
            executed = self.dispatch(scheduling, coin_tasks=('OpsiObscure',))

        self.assertEqual(executed, ['OpsiObscure'])

    def test_long_delay_expires_at_the_monthly_reset(self):
        # 30 天延迟从 10-20 算起本会到 11-19，重置后必须立即恢复检查
        cleared_at = datetime(2026, 10, 20, 10, 0)
        reset = datetime(2026, 11, 1, 0, 0)
        scheduling = self.make_scheduling(
            state={self.OBSCURE_KEY: cleared_at.isoformat()},
            delay_days=30,
        )

        with (
            patch('module.os.tasks.scheduling.current_time',
                  return_value=reset + OpsiScheduling.RESET_CHECK_GRACE),
            patch('module.os.tasks.scheduling.get_os_next_reset_after',
                  side_effect=self.next_reset_after(reset, datetime(2026, 12, 1))),
        ):
            self.assertIsNone(
                scheduling._get_coin_task_check_postpone_time('OpsiObscure')
            )

        self.assertNotIn(self.OBSCURE_KEY, self.state_of(scheduling))


class TestOsResetRemainDays(unittest.TestCase):
    """大世界重置时间的计算基准与剩余天数语义。"""

    def test_next_reset_after_anchors_on_the_given_moment(self):
        now = current_time()

        self.assertEqual(get_os_next_reset_after(now), get_os_next_reset())
        # 40 天前的记录，其「之后第一次重置」必然早于从今天算出的下一次重置
        self.assertLess(
            get_os_next_reset_after(now - timedelta(days=40)),
            get_os_next_reset(),
        )

    def test_remain_days_counts_calendar_days(self):
        # 8-29 距 9-01 还有 3 个自然日，不能用整天数向下取整算成 2
        for moment, expected in (
            (datetime(2026, 8, 29, 0, 0), 3),
            (datetime(2026, 8, 29, 12, 0), 3),
            (datetime(2026, 8, 30, 12, 0), 2),
            (datetime(2026, 8, 31, 23, 0), 1),
        ):
            with self.subTest(moment=moment):
                with (
                    patch('module.config.utils.get_os_next_reset',
                          return_value=datetime(2026, 9, 1)),
                    patch('module.config.utils.current_time', return_value=moment),
                ):
                    self.assertEqual(get_os_reset_remain_days(), expected)


class TestMonthEndCleanupGrace(unittest.TestCase):
    """月底强制消耗行动力：按自然日触发，且不受隐秘/深渊延迟检查影响。"""

    def make_scheduling(self, state=None, delay_days=0, cleanup_days=1):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = CoinCheckDelayConfig(
            state=state,
            delay_days=delay_days,
            task_command='OpsiScheduling',
        )
        scheduling.cleanup_days = cleanup_days
        return scheduling

    def cleanup_active_at(self, scheduling, moment):
        """在指定时间点判断月末清理是否启动，剩余天数走真实实现。"""
        with (
            patch('module.config.utils.get_os_next_reset',
                  return_value=datetime(2026, 9, 1)),
            patch('module.config.utils.current_time', return_value=moment),
            patch.object(scheduling, '_config_enabled', return_value=True),
            patch.object(
                scheduling,
                '_get_month_end_cleanup_days',
                return_value=scheduling.cleanup_days,
            ),
            # 用整天数（不足一天向下取整）会在重置前一天中午就启动，已改为自然日
            patch(
                'module.os.tasks.scheduling.get_os_reset_remain',
                side_effect=AssertionError('月末清理不应再用整天数判断剩余天数'),
            ),
        ):
            return scheduling._is_month_end_cleanup_active()

    def test_cleanup_starts_at_the_configured_calendar_days(self):
        # 用户反馈：设置 2 天却在 8-29 就跑了，按自然日应当 8-30 才启动
        scheduling = self.make_scheduling(cleanup_days=2)

        self.assertFalse(self.cleanup_active_at(scheduling, datetime(2026, 8, 29, 12, 0)))
        self.assertTrue(self.cleanup_active_at(scheduling, datetime(2026, 8, 30, 0, 30)))

    def test_cleanup_starts_on_the_last_day_when_set_to_one(self):
        scheduling = self.make_scheduling(cleanup_days=1)

        self.assertFalse(self.cleanup_active_at(scheduling, datetime(2026, 8, 30, 23, 0)))
        self.assertTrue(self.cleanup_active_at(scheduling, datetime(2026, 8, 31, 0, 30)))

    def test_cleanup_pulls_coin_tasks_despite_the_check_delay(self):
        # 延迟 3 天仍生效（记录是刚写的），月末清理每一轮依旧要拉起隐秘/深渊
        moment = datetime(2026, 10, 31, 12, 0)
        cleared = moment - timedelta(hours=1)
        scheduling = self.make_scheduling(
            state={
                OpsiScheduling.STATE_KEY_OBSCURE_CLEARED_AT: cleared.isoformat(),
                OpsiScheduling.STATE_KEY_ABYSSAL_CLEARED_AT: cleared.isoformat(),
            },
            delay_days=3,
        )
        scheduling.clear_obscure = Mock()
        scheduling.clear_abyssal = Mock()
        scheduling.clear_stronghold = Mock()

        with (
            patch('module.os.tasks.scheduling.current_time', return_value=moment),
            self.assertRaises(TaskEnd),
            patch.object(
                scheduling,
                '_run_with_opsi_task_context',
                side_effect=lambda task, func, *args, **kwargs: func(*args, **kwargs),
            ),
            patch.object(scheduling, '_run_scheduled_meowfficer_farming'),
            patch.object(scheduling, '_run_month_end_shop_purchase'),
            patch.object(scheduling, '_delay_smart_scheduling_to_server_update'),
            patch.object(scheduling, 'notify_push'),
            patch.object(
                scheduling,
                '_get_scheduling_action_point',
                side_effect=[(5000, 1000), (400, 100), (400, 100)],
            ),
        ):
            # 记录仍在推迟期内（正常派发路径会跳过），但月末清理照样拉起隐秘/深渊
            self.assertEqual(
                scheduling._get_coin_task_check_postpone_time('OpsiObscure'),
                datetime(2026, 11, 1, 2, 0),
            )
            scheduling._run_month_end_cleanup(500, 1000, 5000, 1000)

        scheduling.clear_obscure.assert_called_once()
        scheduling.clear_abyssal.assert_called_once()
