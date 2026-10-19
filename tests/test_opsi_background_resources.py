"""后台资源识别、主线程中断及延迟观察的隔离回归。"""

import json
import tempfile
import threading
import unittest
from concurrent.futures import Future
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.config.config_updater import ConfigUpdater
from module.base.async_executor import async_executor
from module.os.operation_siren import OperationSiren
from module.os_handler.os_status import OCR_SHOP_YELLOW_COINS
from module.os_handler.resource_read import BackgroundCoinRead, CoinReading, CoinReplenishRequired, read_coins
from module.os_handler.resource_state import ActionPointSnapshot, reset_resource_caches
from module.os_handler.resource_write import record_resources_background
from module.statistics import resource_flow
from tests.test_api import fixture


class BackgroundRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.identity = ('isolated', 'cn', 0)
        self.stamp = datetime(2026, 10, 15, 19)
        self.state = BackgroundCoinRead()

    def finish(self, yellow=50000, *, valid=True, identity=None, sampled_at=0):
        future = self.state.future = Future()
        future.set_result(CoinReading(identity or self.identity, self.stamp, yellow, valid, sampled_at=sampled_at))
        return self.state.poll(self.identity)

    def test_pending_inference_never_waits(self):
        self.state.future = Future()
        self.assertIsNone(self.state.poll(self.identity))
        self.assertFalse(self.state.future.done())

    def test_only_two_valid_matching_frames_are_accepted(self):
        self.assertIsNone(self.finish())
        self.assertIsNone(self.finish(valid=False))
        self.assertIsNone(self.finish())
        self.assertIsNotNone(self.finish())

    def test_verified_zero_is_low_balance_but_failed_zero_is_not_an_observation(self):
        self.assertIsNone(self.finish(yellow=0, valid=False))
        self.assertIsNone(self.finish(yellow=0))
        self.assertEqual(self.finish(yellow=0).yellow, 0)

    def test_changed_yellow_balance_needs_two_matching_frames(self):
        self.assertIsNone(self.finish())
        self.assertIsNone(self.finish(yellow=49000))
        self.assertEqual(self.finish(yellow=49000).yellow, 49000)

    def test_verified_round_stops_sampling_until_next_request(self):
        self.finish()
        self.finish()
        reader = SimpleNamespace(buttons=[(0, 0, 4, 4)])
        with patch('module.os_handler.resource_read._executor.submit', return_value=Future()) as submit:
            self.state.submit(np.zeros((10, 10, 3)), [reader], self.identity)
            submit.assert_not_called()
            self.state.request()
            self.state.submit(np.zeros((10, 10, 3)), [reader], self.identity)
            submit.assert_called_once()

    def test_transaction_revision_or_instance_change_rejects_old_frames(self):
        for identity in (('isolated', 'cn', 1), ('other', 'cn', 0), ('isolated', 'en', 0)):
            self.assertIsNone(self.finish(identity=identity))
            self.assertIsNone(self.state.candidate)

    def test_queue_is_bounded_and_captures_private_image_and_readers(self):
        image = np.ones((10, 10, 3), np.uint8)
        reader = SimpleNamespace(buttons=[(0, 0, 4, 4)])
        pending = Future()
        with patch('module.os_handler.resource_read._executor.submit', return_value=pending) as submit:
            self.state.submit(image, [reader, reader], self.identity)
            image[:] = 0
            reader.buttons[0] = (1, 1, 9, 9)
            self.state.submit(image.copy(), [reader, reader], self.identity)
        submit.assert_called_once()
        self.assertTrue(submit.call_args.args[1].all())
        self.assertEqual(submit.call_args.args[2][0].buttons, (0, 0, 4, 4))

    def test_field_validation_is_independent_and_does_not_mutate_front_reader(self):
        readers = [SimpleNamespace(buttons=[(0, 0, 4, 4)], last_valid=True) for _ in range(2)]
        with patch('module.os_handler.resource_read.ocr_batch', return_value=[51000, 601]):
            result = read_coins(np.zeros((10, 10, 3)), readers, self.identity, self.stamp)
        self.assertTrue(result.valid)
        self.assertIsNone(result.ap)
        self.assertEqual(readers[0].buttons, [(0, 0, 4, 4)])

    def test_map_read_needs_only_the_visible_yellow_field(self):
        reader = SimpleNamespace(buttons=[(0, 0, 4, 4)], last_valid=True)
        with patch('module.os_handler.resource_read.ocr_batch', return_value=[97451]):
            result = read_coins(np.zeros((10, 10, 3)), [reader], self.identity, self.stamp)
        self.assertTrue(result.valid)
        self.assertEqual(result.yellow, 97451)
        self.assertIsNone(result.ap)

    def test_failed_yellow_does_not_discard_a_valid_current_ap(self):
        readers = [SimpleNamespace(buttons=[(0, 0, 4, 4)], last_valid=valid) for valid in (False, True)]
        with patch('module.os_handler.resource_read.ocr_batch', return_value=[0, 123]):
            result = read_coins(np.zeros((10, 10, 3)), readers, self.identity, self.stamp)
        self.assertFalse(result.valid)
        self.assertEqual(result.ap, 123)

    def test_invalidated_pending_result_is_drained_without_enqueuing_another(self):
        self.assertIsNone(self.finish(yellow=91760, sampled_at=1))
        pending = self.state.future = Future()
        with patch('module.os_handler.resource_read.monotonic', return_value=2):
            self.state.invalidate()
        reader = SimpleNamespace(buttons=[(0, 0, 4, 4)])
        with patch('module.os_handler.resource_read._executor.submit') as submit:
            self.state.submit(np.zeros((10, 10, 3)), [reader], self.identity)
            submit.assert_not_called()
        pending.set_result(CoinReading(self.identity, self.stamp, 91760, True, sampled_at=1))
        self.assertIsNone(self.state.poll(self.identity))
        self.assertIsNone(self.state.last_result)
        self.assertIsNone(self.finish(yellow=97451, sampled_at=3))
        self.assertEqual(self.finish(yellow=97451, sampled_at=4).yellow, 97451)


class BackgroundRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runner = OperationSiren.__new__(OperationSiren)
        self.runner.config = SimpleNamespace(
            config_name='isolated', task=SimpleNamespace(command='OpsiHazard1Leveling'),
            OpsiHazard1Leveling_ActionPointCheckInterval=5, OS_ACTION_POINT_BOX_USE=True,
            OpsiHazard1Leveling_OperationCoinsPreserve=50000,
        )
        self.runner.device = Mock(image=np.zeros((720, 1280, 3), np.uint8))
        self.runner.is_in_map = Mock(return_value=True)
        self.runner.handle_map_event = Mock(return_value=False)
        self.runner.is_running_smart_scheduling_task = Mock(return_value=True)
        self.runner._get_smart_scheduling_operation_coins_preserve = Mock(return_value=50000)
        self.runner._coin_background = BackgroundCoinRead()
        self.runner._ap_snapshot = ActionPointSnapshot(self.runner._action_point_identity(), 100, 0,
                                                      (10000, 0, 2, 0), 130)
        self.writer = self.enterContext(patch('module.os_handler.os_status.record_resources_background'))
        self.enterContext(patch('module.os_handler.action_point.record_resources_background'))

    def test_changed_map_balance_is_confirmed_before_next_scheduling_decision(self):
        self.runner.config.task.command = 'OpsiScheduling'
        self.runner._last_yellow_coins = 91760
        self.runner._last_yellow_owner = self.runner._background_coin_identity()[:2]
        previous = self.runner.device.image.copy()
        self.runner._yellow_coin_read = (
            ('isolated', 'cn', 'map', 0),
            previous[27:48, 1038:1128].copy(), 91760,
        )
        fixture = Path(__file__).parent / 'fixtures/opsi_yellow_coin_video/97451.png'
        self.runner.device.image[27:48, 1038:1128] = load_image(str(fixture))
        state = self.runner._coin_background
        state.frame = previous
        state.candidate = CoinReading(self.runner._background_coin_identity(), datetime.now(), 91760, True)
        state.future = Future()
        state.future.set_result(state.candidate)
        self.runner.appear = Mock(return_value=False)
        self.runner.appear_then_click = Mock(return_value=False)
        self.runner.loop = lambda **kwargs: iter(range(2))
        self.runner.is_running_prevent_action_point_overflow_task = Mock(return_value=False)
        self.runner._get_scheduling_action_point = Mock(return_value=(1608, 8))
        self.runner._run_smart_scheduling_decision = Mock()
        self.runner._close_scheduling_action_point = Mock()
        with patch.object(OCR_SHOP_YELLOW_COINS, 'ocr', return_value=97451), \
                patch.object(OCR_SHOP_YELLOW_COINS, 'last_valid', True, create=True), \
                patch('module.os_handler.resource_read._executor.submit', return_value=Future()):
            self.runner.run_smart_scheduling_once()
        self.runner._run_smart_scheduling_decision.assert_called_once_with(97451, 1608, 8)
        self.assertEqual(self.runner._last_yellow_coins, 97451)
        self.writer.assert_called_once_with(self.runner.config, {'YellowCoin': 97451})

    def test_meow_polls_current_yellow_without_reading_or_overwriting_purple(self):
        self.runner.config.task.command = 'OpsiMeowfficerFarming'
        self.runner._shop_purple_coins = 31163
        state = self.runner._coin_background
        state.frame = self.runner.device.image
        state.candidate = CoinReading(self.runner._background_coin_identity(), datetime.now(), 97451, True)
        state.future = Future()
        state.future.set_result(state.candidate)
        self.assertFalse(self.runner.background_coin_replenish_required())
        self.assertEqual(self.runner._last_yellow_coins, 97451)
        self.assertEqual(self.runner._shop_purple_coins, 31163)
        self.writer.assert_called_once_with(
            self.runner.config, {'YellowCoin': 97451}, observed_at=state.accepted.observed_at,
        )
        self.runner.appear = Mock(return_value=False)
        with patch.object(OCR_SHOP_YELLOW_COINS, 'ocr', side_effect=AssertionError('不得同步 OCR')), \
                patch('module.os_handler.resource_read._executor.submit', return_value=Future()):
            self.assertEqual(self.runner.get_routine_yellow_coins(), 97451)

    def test_changed_digits_restart_background_sampling_after_stable_read(self):
        state = self.runner._coin_background
        state.frame = self.runner.device.image.copy()
        state.accepted = CoinReading(self.runner._background_coin_identity(), datetime.now(), 91760, True)
        state.wanted = False
        self.runner.device.image[27:48, 1038:1128] = 255
        self.runner.action_point_check_due = Mock(return_value=False)
        with patch.object(state, 'submit') as submit:
            self.runner.poll_background_resources(sample=True)
        self.assertIsNone(state.accepted)
        self.assertTrue(state.wanted)
        self.assertEqual(submit.call_args.args[1], [OCR_SHOP_YELLOW_COINS])
        self.writer.assert_not_called()

    def test_pending_frame_cannot_overwrite_a_newer_synchronous_confirmation(self):
        state = self.runner._coin_background
        old = CoinReading(self.runner._background_coin_identity(), datetime.now(), 91760, True)
        state.candidate = old
        state.future = Future()
        self.runner.appear = Mock(return_value=False)
        self.runner.appear_then_click = Mock(return_value=False)
        self.runner.loop = lambda **kwargs: iter(range(2))
        with patch.object(OCR_SHOP_YELLOW_COINS, 'ocr', return_value=97451), \
                patch.object(OCR_SHOP_YELLOW_COINS, 'last_valid', True, create=True):
            self.assertEqual(self.runner.get_yellow_coins(), 97451)
        state.future.set_result(old)
        self.runner.poll_background_resources()
        self.assertEqual(self.runner._last_yellow_coins, 97451)
        self.writer.assert_called_once_with(self.runner.config, {'YellowCoin': 97451})

    def test_routine_work_continues_using_verified_value_while_ocr_is_pending(self):
        self.runner._last_yellow_coins = 52000
        self.runner._last_yellow_owner = self.runner._background_coin_identity()[:2]
        self.runner._coin_background.future = Future()
        self.runner._yellow_coin_read = (
            ('isolated', 'cn', 'map', 0), self.runner.device.image[27:48, 1038:1128].copy(), 52000,
        )
        self.runner.appear = Mock(return_value=False)
        with patch.object(OCR_SHOP_YELLOW_COINS, 'ocr', side_effect=AssertionError('不得同步 OCR')):
            self.assertEqual(self.runner.get_routine_yellow_coins(), 52000)
        self.runner.device.screenshot.assert_not_called()
        self.runner.config.config_name = 'other'
        self.runner.get_yellow_coins = Mock(side_effect=AssertionError('不得同步 OCR'))
        with self.assertRaisesRegex(AssertionError, '不得同步'):
            self.runner.get_routine_yellow_coins()

    def test_ap_is_included_only_after_interval_expires(self):
        for now, expected in ((399, 1), (400, 2)):
            with patch('module.os_handler.action_point.monotonic', return_value=now), \
                    patch.object(self.runner._coin_background, 'submit') as submit:
                self.runner.poll_background_resources(sample=True)
                self.assertEqual(len(submit.call_args.args[1]), expected)
        self.runner.config.OpsiHazard1Leveling_ActionPointCheckInterval = 0
        with patch.object(self.runner._coin_background, 'submit') as submit:
            self.runner.poll_background_resources(sample=True)
            self.assertEqual(len(submit.call_args.args[1]), 1)

    def test_ap_accounts_for_consumption_after_capture_without_faking_total_inventory(self):
        reading = CoinReading(self.runner._background_coin_identity(), datetime.now(), 51000, True,
                              ap=125, ap_epoch=0, ap_spent=0, sampled_at=120)
        self.runner.consume_cached_action_point(5)
        self.runner.apply_background_action_point(reading)
        self.assertEqual(self.runner._ap_snapshot.current, 120)
        self.assertEqual(self.runner._ap_snapshot.checked_at, 120)
        self.assertEqual(self.runner._action_point_total, 220)
        self.runner.invalidate_action_point_cache()
        self.runner._ap_snapshot = ActionPointSnapshot(self.runner._action_point_identity(), 140, 0,
                                                      (10000, 0, 1, 0), 170)
        self.runner.apply_background_action_point(reading)
        self.assertEqual(self.runner._ap_snapshot.current, 170)

    def test_low_coins_interrupt_on_main_thread_and_keep_drop_recorder(self):
        self.runner.is_in_map.return_value = False
        state = self.runner._coin_background
        state.accepted = CoinReading(self.runner._background_coin_identity(), datetime.now(), 49000, True)
        self.runner.poll_background_resources = Mock()
        threads = []
        self.runner.interrupt_auto_search = Mock(side_effect=lambda **kwargs: threads.append(threading.get_ident()))
        drop = object()
        with self.assertRaises(CoinReplenishRequired):
            self.runner.handle_background_coin_interrupt(drop)
        self.runner.interrupt_auto_search.assert_called_once_with(goto_main=False, end_task=False, drop=drop)
        self.assertEqual(threads, [threading.get_ident()])
        self.runner.config.task.command = 'OpsiMeowfficerFarming'
        self.runner.handle_background_coin_interrupt(drop)
        self.assertEqual(self.runner.interrupt_auto_search.call_count, 1)

    def test_low_coins_on_map_do_not_toggle_ambiguous_auto_search_button(self):
        self.runner._coin_background.accepted = CoinReading(
            self.runner._background_coin_identity(), datetime.now(), 49000, True,
        )
        self.runner.poll_background_resources = Mock()
        self.runner.interrupt_auto_search = Mock()
        self.runner.handle_background_coin_interrupt()
        self.runner.interrupt_auto_search.assert_not_called()
        self.runner.device.click.assert_not_called()

    def test_low_coin_interrupt_returns_to_smart_decision_and_is_not_swallowed(self):
        self.runner.is_running_prevent_action_point_overflow_task = Mock(return_value=False)
        self.runner.get_routine_yellow_coins = Mock(return_value=49000)
        self.runner._get_scheduling_action_point = Mock(return_value=(9000, 130))
        self.runner._run_smart_scheduling_decision = Mock(side_effect=CoinReplenishRequired)
        self.runner._close_scheduling_action_point = Mock()
        self.runner.run_smart_scheduling_once()
        self.runner._close_scheduling_action_point.assert_called_once()
        self.runner.handle_ash_beacon_attack = Mock()
        self.runner.stat = SimpleNamespace(new=Mock(return_value=nullcontext(Mock())))
        self.runner.config.DropRecord_OpsiRecord = 'do_not'
        self.runner.os_auto_search_run = Mock(side_effect=CoinReplenishRequired)
        self.runner._auto_search_battle_count = 1
        with patch('module.os.map.opsi_drop_record', return_value='do_not'), self.assertRaises(CoinReplenishRequired):
            self.runner.run_strategic_search()

    def test_recovery_drops_inflight_results_and_verified_owner(self):
        self.runner._last_yellow_coins = 52000
        self.runner._last_yellow_owner = ('isolated', 'cn')
        reset_resource_caches(self.runner)
        self.assertNotIn('_coin_background', self.runner.__dict__)
        self.assertNotIn('_last_yellow_owner', self.runner.__dict__)

    def test_completed_event_enters_next_plan_without_repeating_zone_ocr_or_screenshots(self):
        config = self.runner.config
        config.override = Mock()
        config.is_task_enabled = Mock(return_value=False)
        config.OpsiHazard1Leveling_MinimumActionPointReserve = 200
        config.OpsiHazard1Leveling_TargetZone = 22
        config.OpsiHazard1Leveling_RecordSeaMiles = -1
        config.OpsiFleet_Fleet = 1
        self.runner._cl1_next_search_ready = True
        self.runner.zone = SimpleNamespace(zone_id=22, hazard_level=1)
        self.runner.is_zone_name_hidden = True
        self.runner._prepare_scheduling_action_point = Mock(return_value=(9000, 130))
        self.runner.get_current_zone = Mock(side_effect=AssertionError('重复海域 OCR'))
        self.runner.fleet_set = Mock()
        self.runner._record_ap_and_coins = Mock()
        self.runner._cl1_handle_telemetry = Mock()
        self.runner.interval_clear = Mock()
        opened = []
        self.runner.appear = Mock(side_effect=lambda *args, **kwargs: bool(opened))
        self.runner.match_template_color = Mock(return_value=True)
        self.runner.device.click.side_effect = opened.append
        self.runner.device.screenshot.side_effect = lambda: self.assertTrue(opened)
        self.runner._cl1_run_battle = self.runner.strategy_search_enter
        self.runner.run_hazard1_leveling_once()
        self.runner.device.click.assert_called_once()
        self.runner.get_current_zone.assert_not_called()

    def test_combat_loading_and_executing_poll_interrupt_without_waiting_for_battle_end(self):
        self.runner.is_in_map.return_value = False
        self.runner.config.Submarine_Fleet = 0
        self.runner.handle_combat_automation_confirm = Mock(return_value=False)
        self.runner.handle_os_auto_search_map_option = Mock(return_value=False)
        self.runner.is_combat_executing = Mock(return_value=True)
        self.runner.submarine_call_reset = Mock()
        self.runner.interrupt_auto_search = Mock()
        for stages in ((True,), (False, True)):
            self.runner.background_coin_replenish_required = Mock(side_effect=stages)
            self.runner.device.screenshot.reset_mock()
            with patch('module.os_combat.combat.start_battle_timer', return_value='cl1'), \
                    self.assertRaises(CoinReplenishRequired):
                self.runner.auto_search_combat()
            self.assertEqual(self.runner.device.screenshot.call_count, len(stages))


class ResourcePersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = fixture(directory)
        self.path = self.root / 'config/testpilot.json'
        self.enterContext(patch('module.statistics.resource_stats._LOCAL_DB', str(self.root / 'config/azurstats_local.db')))
        self.enterContext(patch('module.os_handler.resource_write.filepath_config', return_value=str(self.path)))
        self.enterContext(patch('module.config.utils.filepath_config', return_value=str(self.path)))
        self.enterContext(patch('module.scheduler.store.ProgramStore'))
        self.enterContext(patch('module.statistics.resource_stats.async_record_resource_snapshot'))
        self.enterContext(patch('module.statistics.cl1_database.db.async_add_yellow_coin_snapshot'))
        self.config = SimpleNamespace(config_name='testpilot', task=SimpleNamespace(command='OpsiHazard1Leveling'),
                                      data=json.loads(self.path.read_text(encoding='utf-8')), modified={})
        self.stamp = datetime(2026, 10, 15, 19)
        # 首次总库迁移包含进程清点，先在主线程完成测试环境准备。
        with resource_flow.connect():
            pass
        self.addCleanup(async_executor.flush, timeout=15)

    def test_background_save_preserves_external_settings_and_newer_observation(self):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['OpsiGeneral']['OpsiGeneral']['OilLimit'] = 1234
        data['Dashboard']['YellowCoin']['Value'] = 60000
        data['Dashboard']['YellowCoin']['Record'] = str(self.stamp + timedelta(seconds=1))
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        record_resources_background(self.config, {'YellowCoin': 50000}, observed_at=self.stamp).result(timeout=15)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['OpsiGeneral']['OpsiGeneral']['OilLimit'], 1234)
        self.assertEqual(saved['Dashboard']['YellowCoin']['Value'], 60000)
        self.assertEqual(self.config.modified, {})

    def test_background_observation_keeps_task_context_and_sample_time(self):
        with resource_flow.task_session('testpilot', 'OpsiHazard1Leveling'):
            future = record_resources_background(self.config, {'YellowCoin': 51000}, observed_at=self.stamp)
        future.result(timeout=15)
        with resource_flow.connect() as connection:
            balance = connection.execute('SELECT * FROM resource_balances WHERE resource=?', ('YellowCoin',)).fetchone()
        self.assertEqual(balance['ts'], str(self.stamp))
        self.assertIsNotNone(balance['run_id'])
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['Dashboard']['YellowCoin']['Value'], 51000)

    def test_background_current_only_read_does_not_write_total_ap_statistics(self):
        with patch('module.statistics.cl1_database.db.async_add_ap_snapshot') as saved:
            record_resources_background(self.config, {'ActionPoint': {'Value': 123}},
                                        observed_at=self.stamp).result(timeout=15)
            saved.assert_not_called()
            record_resources_background(self.config, {'ActionPoint': {'Value': 189, 'Total': 7289}},
                                        observed_at=self.stamp + timedelta(seconds=1)).result(timeout=15)
            saved.assert_called_once_with('testpilot', 189, source='OpsiHazard1Leveling',
                                           distance=None, ap_total=7289,
                                           observed_at=self.stamp + timedelta(seconds=1))

    def test_delayed_observation_does_not_count_later_purchase_twice(self):
        with resource_flow.task_session('testpilot', 'OpsiHazard1Leveling'), \
                patch('module.statistics.resource_flow.now', return_value=self.stamp + timedelta(seconds=2)):
            resource_flow.observe(self.config, 'YellowCoin', 50000, observed_at=self.stamp)
            resource_flow.record(self.config, {'YellowCoin': -4000}, '明石购买')
            # 采样时只有奖励 +1000；购买发生在截图之后、观察落库之前。
            resource_flow.observe(self.config, 'YellowCoin', 51000, observed_at=self.stamp + timedelta(seconds=1))
            resource_flow.observe(self.config, 'YellowCoin', 47000, observed_at=self.stamp + timedelta(seconds=3))
        with resource_flow.connect() as connection:
            changes = connection.execute('SELECT amount FROM resource_flows ORDER BY id').fetchall()
        self.assertEqual([row['amount'] for row in changes], [-4000, 1000])

    def test_stale_observation_cannot_move_balance_backwards(self):
        resource_flow.observe(self.config, 'YellowCoin', 60000, observed_at=self.stamp + timedelta(seconds=1))
        resource_flow.observe(self.config, 'YellowCoin', 50000, observed_at=self.stamp)
        with resource_flow.connect() as connection:
            value = connection.execute('SELECT value FROM resource_balances WHERE resource=?', ('YellowCoin',)).fetchone()[0]
        self.assertEqual(value, 60000)


class ResourceConfigurationTests(unittest.TestCase):
    def test_old_values_migrate_and_new_values_win(self):
        updater = ConfigUpdater()
        old = {'OpsiGeneral': {'OpsiGeneral': {'ActionPointCheckInterval': 5, 'SkipStrategicSearchCheck': True}}}
        new = {'OpsiHazard1Leveling': {'OpsiHazard1Leveling': {}}}
        updater.config_redirect(old, new)
        self.assertEqual(new['OpsiHazard1Leveling']['OpsiHazard1Leveling'],
                         {'ActionPointCheckInterval': 5, 'SkipStrategicSearchCheck': True})
        old['OpsiHazard1Leveling'] = {'OpsiHazard1Leveling': {'ActionPointCheckInterval': 10}}
        new['OpsiHazard1Leveling']['OpsiHazard1Leveling']['ActionPointCheckInterval'] = 10
        updater.config_redirect(old, new)
        self.assertEqual(new['OpsiHazard1Leveling']['OpsiHazard1Leveling']['ActionPointCheckInterval'], 10)

    def test_generated_controls_follow_sacrifice_control_and_have_five_translations(self):
        root = Path(__file__).parents[1]
        args = json.loads((root / 'module/config/argument/args.json').read_text(encoding='utf-8'))
        fields = list(args['OpsiHazard1Leveling']['OpsiHazard1Leveling'])
        index = fields.index('SkipHpCheck')
        self.assertEqual(fields[index + 1:index + 3], ['ActionPointCheckInterval', 'SkipStrategicSearchCheck'])
        self.assertNotIn('ActionPointCheckInterval', args['OpsiGeneral']['OpsiGeneral'])
        for lang in ('zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW'):
            data = json.loads((root / f'module/config/i18n/{lang}.json').read_text(encoding='utf-8'))
            for field in ('ActionPointCheckInterval', 'SkipStrategicSearchCheck'):
                self.assertNotIn(field, data['OpsiGeneral'])
                self.assertNotIn('OpsiHazard1Leveling.', data['OpsiHazard1Leveling'][field]['help'])


class FarmingStatisticsTests(unittest.TestCase):
    def test_short_meow_duration_is_kept_without_any_ap_read_for_statistics(self):
        from module.statistics.opsi_runtime import finish_meow_search_timer
        runner = SimpleNamespace(
            config=SimpleNamespace(config_name='isolated', task=SimpleNamespace(command='OpsiMeowfficerFarming')),
            zone=SimpleNamespace(hazard_level=3), action_point_enter=Mock(), get_current_ap=Mock(),
        )
        with patch('module.statistics.opsi_runtime.time.time', return_value=110), \
                patch('module.statistics.cl1_database.db.async_add_meow_round_time') as saved, \
                patch('module.statistics.opsi_runtime.record_ap_snapshot') as snapshot:
            self.assertEqual(finish_meow_search_timer(runner, 10, 2), 100)
            saved.assert_called_once_with('isolated', 100, 3)
            snapshot.assert_not_called()
        runner.action_point_enter.assert_not_called()
        runner.get_current_ap.assert_not_called()

    def test_sea_miles_keep_estimated_ap_out_of_successful_observations(self):
        runner = OperationSiren.__new__(OperationSiren)
        runner.config = SimpleNamespace(config_name='isolated')
        runner._action_point_current = 125
        runner._action_point_total_with_box = 9125
        runner.get_routine_yellow_coins = Mock(return_value=51000)
        with patch('module.statistics.opsi_runtime.record_ap_snapshot') as ap, \
                patch('module.statistics.cl1_database.db.async_add_coins_snapshot'):
            runner._record_ap_and_coins(sea_miles=120000)
        self.assertEqual(ap.call_args.kwargs['source'], 'sea_miles')
        self.assertIsNone(ap.call_args.kwargs['ap_current'])
        self.assertIsNone(ap.call_args.kwargs.get('ap_total'))
        self.assertEqual(ap.call_args.kwargs['distance'], 120000)


if __name__ == '__main__':
    unittest.main()
