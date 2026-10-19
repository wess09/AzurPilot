"""侵蚀1完整流程计时、轮数折算和持久化回归，不连接真实设备。"""

import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import GameStuckError
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os.tasks.task_context import opsi_task_context
from module.os_handler.resource_read import CoinReplenishRequired
from module.statistics import opsi_runtime
from module.statistics.ship_exp_stats import ShipExpStats, get_ship_exp_stats
from tests.opsi_test_support import install_store


class FullRoundTimeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='cl1-round-', ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        install_store(self, directory.name)
        self.now = 1000.0
        self.enterContext(patch('module.statistics.opsi_runtime.time.monotonic', side_effect=lambda: self.now))
        self.enterContext(patch('module.statistics.ship_exp_stats.time.time', side_effect=lambda: self.now))
        self.enterContext(patch('module.os.tasks.hazard_leveling.current_time', return_value=datetime(2026, 10, 18, 12)))
        self.config = SimpleNamespace(
            config_name='leveling', task=SimpleNamespace(command=opsi_runtime.CL1_TASK),
            OpsiHazard1Leveling_RecordSeaMiles=0,
            OpsiHazard1Leveling_DebugClip=False,
            OpsiHazard1Leveling_SeaMilesLastRecord=None,
            OpsiHazard1Leveling_TargetZone=0,
            OpsiFleet_Fleet=1, override=Mock(), is_task_enabled=Mock(return_value=False),
        )
        self.runner = OpsiHazard1Leveling.__new__(OpsiHazard1Leveling)
        self.runner.config = self.config
        self.runner.zone = SimpleNamespace(zone_id=22, hazard_level=1)
        self.runner.is_zone_name_hidden = True
        self.runner._prepare_scheduling_action_point = self.phase(5, (1000, 120))
        self.runner.action_point_reusable = Mock(return_value=True)
        self.runner.get_current_zone = self.phase(2)
        self.runner.fleet_set = self.phase(3)
        self.runner.is_running_smart_scheduling_task = Mock(return_value=True)
        self.runner.detect_and_record_sea_miles = self.phase(10, 123456)
        self.runner._record_ap_and_coins = self.phase(4)
        self.runner._get_pending_event = Mock(return_value=None)
        self.runner.run_strategic_search = Mock(side_effect=self.search)
        self.runner.map_rescan = self.phase(11)
        self.runner._forced_move_enabled = Mock(return_value=True)
        self.runner._execute_fixed_patrol_scan = self.phase(12)
        self.runner.handle_after_auto_search = self.phase(9)
        self.runner._cl1_handle_telemetry = self.phase(1)
        self.runner.consume_cached_action_point = Mock()
        self.enterContext(patch('module.base.debug_clip.cleanup_clips_if_due'))
        self.enterContext(patch('module.base.debug_clip.clip_recording', side_effect=lambda *args: nullcontext()))

    def phase(self, seconds, result=None):
        def run(*args, **kwargs):
            self.now += seconds
            return result
        return Mock(side_effect=run)

    def complete_battle(self, seconds, source=None):
        if source is None:
            source = opsi_runtime.start_battle_timer(self.config)
        else:
            get_ship_exp_stats(self.config.config_name).on_battle_start()
        self.now += seconds
        opsi_runtime.finish_battle_timer(self.config, source)

    def search(self):
        self.complete_battle(13)
        self.now += 7
        self.complete_battle(14)
        return True

    def stats(self):
        return ShipExpStats(instance_name=self.config.config_name)

    def run_once(self):
        started_at = self.now
        self.runner.run_hazard1_leveling_once(ap_preserve=0)
        return self.now - started_at

    def test_preparation_sea_miles_patrol_and_repair_are_all_included(self):
        self.assertEqual(self.run_once(), 91)
        stats = self.stats()
        self.assertEqual(stats.get_average_round_time(), 91)
        self.assertEqual(stats.get_average_battle_time(), 13.5)
        self.assertEqual(stats.get_today_stats()['total_run_time'], 27)
        self.assertEqual(stats.get_today_stats()['battle_count'], 2)
        self.assertEqual(stats.get_exp_per_hour(), round(312 * 2 * 3600 / 91, 2))
        self.runner.detect_and_record_sea_miles.assert_called_once()
        self.runner.map_rescan.assert_called_once()
        self.runner._execute_fixed_patrol_scan.assert_called_once()
        self.runner.handle_after_auto_search.assert_called_once()
        self.assertFalse(hasattr(self.config, '_cl1_round_metrics'))

    def test_search_counter_resets_do_not_lose_rounds_or_write_old_samples(self):
        def search():
            for _ in range(2):
                self.runner.on_auto_search_battle_count_reset()
                for _ in range(2):
                    self.runner.on_auto_search_battle_count_add()
                    self.complete_battle(10)
            return True

        self.runner.run_strategic_search.side_effect = search
        with patch('module.statistics.cl1_database.db.async_increment_battle_count') as monthly:
            duration = self.run_once()
        self.assertEqual(monthly.call_count, 4)
        group = self.stats().data['round_times']
        self.assertEqual(group['round_counts'], [2])
        self.assertEqual(group['samples'], [duration / 2])
        self.assertEqual(self.stats().get_average_round_time(), round(duration / 2, 2))

    def test_no_finished_battle_does_not_create_a_round_sample(self):
        self.runner.run_strategic_search.side_effect = lambda: True
        self.run_once()
        self.assertNotIn('round_times', self.stats().data)

    def test_coin_interrupt_includes_repair_and_preserves_the_exception(self):
        def interrupted_search():
            self.search()
            raise CoinReplenishRequired()

        self.runner.run_strategic_search.side_effect = interrupted_search
        started_at = self.now
        with self.assertRaises(CoinReplenishRequired):
            self.run_once()
        self.assertEqual(self.stats().get_average_round_time(), self.now - started_at)
        self.runner.handle_after_auto_search.assert_called_once()
        self.runner.map_rescan.assert_not_called()
        self.assertFalse(hasattr(self.config, '_cl1_round_metrics'))

    def test_idle_time_and_other_sources_are_excluded_from_following_rounds(self):
        self.run_once()
        self.now += 10000
        with opsi_runtime.cl1_round_timer(self.config):
            self.complete_battle(20, source='meow')
        self.assertEqual(self.run_once(), 91)
        stats = self.stats()
        self.assertEqual(stats.data['round_times']['samples'], [91, 91])
        self.assertEqual(stats.get_today_stats()['battle_count'], 4)

    def test_nested_timer_does_not_record_the_same_battles_twice(self):
        with opsi_runtime.cl1_round_timer(self.config):
            self.run_once()
        self.assertEqual(self.stats().data['round_times']['samples'], [91])

    def test_scheduling_and_overflow_proxies_record_before_restoring_owner(self):
        self.config.bind = Mock()
        for command in ('OpsiScheduling', 'OpsiPreventActionPointOverflow'):
            with self.subTest(command=command):
                owner = self.config.task = SimpleNamespace(command=command)
                with opsi_task_context(
                    self.config, SimpleNamespace(command=opsi_runtime.CL1_TASK),
                    bind_task=opsi_runtime.CL1_TASK, disable_task_switch=False,
                ):
                    self.run_once()
                self.assertIs(self.config.task, owner)
                self.assertFalse(hasattr(self.config, '_cl1_round_metrics'))
        self.assertEqual(self.stats().data['round_times']['samples'], [91, 91])
        self.assertEqual(self.stats().get_today_stats()['battle_count'], 4)

    def test_single_finished_battle_is_normalized_as_half_a_round(self):
        with opsi_runtime.cl1_round_timer(self.config):
            self.complete_battle(15)
            self.now += 5
        group = self.stats().data['round_times']
        self.assertEqual(group['round_counts'], [0.5])
        self.assertEqual(self.stats().get_average_round_time(), 40)

    def test_recording_failure_does_not_mask_game_error_or_leave_active_timer(self):
        stats = Mock()
        stats.record_round_time.side_effect = RuntimeError('统计写入失败')
        with patch('module.statistics.ship_exp_stats.get_ship_exp_stats', return_value=stats), \
                patch.object(opsi_runtime.logger, 'exception') as failure:
            with self.assertRaisesRegex(GameStuckError, '游戏中断'):
                with opsi_runtime.cl1_round_timer(self.config):
                    self.complete_battle(10)
                    raise GameStuckError('游戏中断')
        failure.assert_called_once()
        self.assertFalse(hasattr(self.config, '_cl1_round_metrics'))

    def test_new_scope_preserves_legacy_data_without_mixing_it_into_average(self):
        stats = get_ship_exp_stats('leveling')
        legacy = {'samples': [40, 42], 'average': 41}
        stats.data['round_times'] = legacy
        stats._save()
        self.assertEqual(self.stats().get_average_round_time(), 41)
        self.run_once()
        group = self.stats().data['round_times']
        self.assertEqual(group['legacy'], legacy)
        self.assertEqual(group['scope'], 'full_cycle')
        self.assertEqual(group['average'], 91)

    def test_average_is_weighted_by_round_count_across_different_search_lengths(self):
        stats = self.stats()
        stats.record_round_time(100, round_count=1)
        stats.record_round_time(90, round_count=3)
        self.assertEqual(self.stats().get_average_round_time(), 47.5)

    def test_recent_window_is_limited_by_rounds_including_partial_oldest_batch(self):
        stats = self.stats()
        stats.record_round_time(4000, round_count=100)
        stats.record_round_time(90, round_count=1.5)
        group = self.stats().data['round_times']
        self.assertEqual(group['round_counts'], [98.5, 1.5])
        self.assertEqual(group['average'], 40.3)
        stats.record_round_time(10000, round_count=200)
        group = self.stats().data['round_times']
        self.assertEqual(group['round_counts'], [100])
        self.assertEqual(group['samples'], [50])
        self.assertEqual(group['average'], 50)

    def test_invalid_duration_or_round_count_leaves_existing_statistics_unchanged(self):
        stats = self.stats()
        stats.record_round_time(80)
        for duration, count in ((0, 1), (-1, 1), (float('nan'), 1), (float('inf'), 1), (1, 0), (1, -1)):
            with self.subTest(duration=duration, count=count):
                stats.record_round_time(duration, round_count=count)
        self.assertEqual(self.stats().data['round_times']['samples'], [80])


if __name__ == '__main__':
    unittest.main()
