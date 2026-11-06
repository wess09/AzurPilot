"""隐秘海域的扫描顺序、跨重启单次续接和共用流程兼容性。"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.config.config import AzurLaneConfig, TaskEnd
from module.exception import GameStuckError
from module.os.map import OSMap
from module.os.map_operation import OSMapOperation
from module.os.operation_siren import OperationSiren
from module.os.tasks.obscure import OBSCURE_RESUME_KEY
from module.statistics.azurstats import DropImage


RESET = datetime(2026, 12, 1)


class ObscureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'obscure-test.json'
        self.path.write_text(Path('config/template.json').read_text(encoding='utf-8'), encoding='utf-8')
        for target in ('module.config.config.filepath_config', 'module.config.config_updater.filepath_config'):
            patcher = patch(target, return_value=str(self.path))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('module.os.tasks.obscure.get_os_next_reset', return_value=RESET)
        patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, task='OpsiObscure', full=False, radar=False, keep_state=False):
        runner = OperationSiren.__new__(OperationSiren)
        runner.config = AzurLaneConfig('obscure-test', task=task)
        runner.config.cross_set('OpsiObscure.OpsiObscure.FullScan', full)
        runner.config.cross_set('OpsiObscure.OpsiObscure.RadarScan', radar)
        if not keep_state:
            runner.config.cross_set(OBSCURE_RESUME_KEY, None)
        runner.zone = SimpleNamespace(zone_id=44, is_port=False)
        runner.is_obscure_zone = True
        runner.device = Mock(image='map')
        runner.stat = Mock()
        drop = DropImage(runner.stat, 'opsi_obscure', save=False, local=True)
        runner.stat.new.return_value = drop
        runner.actions = []
        runner._solved_map_event = set()
        runner._auto_search_battle_count = 1
        for name in ('hp_reset', 'hp_get', 'zone_init', 'fleet_set', 'os_order_execute',
                     'handle_ash_beacon_attack', 'handle_current_fleet_resolve',
                     'cl1_ap_preserve', '_close_scheduling_action_point'):
            setattr(runner, name, Mock())
        runner.handle_after_auto_search = Mock(side_effect=lambda: runner.actions.append('after'))
        runner.is_in_map = Mock(return_value=True)
        runner.is_in_special_zone = Mock(return_value=True)
        runner.storage_get_next_item = Mock(return_value=True)
        runner.run_first_auto_search = Mock()

        def search(collector, **kwargs):
            runner.actions.append('battle')
            collector.add('battle-reward')
            return 1

        def scan(rescan_mode='full', drop=None):
            runner.actions.append(rescan_mode)

        def radar_scan(drop=None, **kwargs):
            runner.actions.append('radar')
            drop.add('radar-reward')

        def exit_map(drop=None):
            runner.actions.append('exit')
            if drop is not None:
                drop.add('exit-reward')

        runner.os_auto_search_run = Mock(side_effect=search)
        runner.clear_question = Mock(side_effect=lambda **kwargs: runner.actions.append('question'))
        runner.map_rescan = Mock(side_effect=scan)
        runner.map_rescan_once = Mock(side_effect=scan)
        runner.clear_question_any_fleet = Mock(side_effect=radar_scan)
        runner.map_exit = Mock(side_effect=exit_map)
        return runner

    def test_each_scan_switch_combination_keeps_original_checks_and_order(self):
        for full, radar in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(full=full, radar=radar):
                runner = self.runner(full=full, radar=radar)
                runner.clear_obscure()
                expected = ['battle', 'question', 'current']
                expected += ['full'] if full else []
                expected += ['radar'] if radar else []
                self.assertEqual(runner.actions, expected + ['exit', 'after'])
                self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))
                runner.os_order_execute.assert_called_once_with(
                    recon_scan=True, submarine_call=runner.config.OpsiFleet_Submarine)
                if radar:
                    runner.clear_question_any_fleet.assert_called_once_with(
                        drop=runner.stat.new.return_value, rescan=False)
                    self.assertEqual(runner.fleet_set.call_args, call(runner.config.OpsiFleet_Fleet))

    def test_handled_event_skips_later_optional_scans(self):
        for stage in ('question', 'current', 'full'):
            for event in ('is_akashi', 'is_logging_tower', 'is_scanning_device', 'is_exploration_reward'):
                with self.subTest(stage=stage, event=event):
                    runner = self.runner(full=True, radar=True)
                    method = {'question': 'clear_question', 'current': 'map_rescan',
                              'full': 'map_rescan_once'}[stage]
                    getattr(runner, method).side_effect = lambda **kwargs: runner._solved_map_event.add(event)
                    runner.clear_obscure()
                    runner.clear_question_any_fleet.assert_not_called()
                    if stage != 'full':
                        runner.map_rescan_once.assert_not_called()
                    else:
                        runner.map_rescan_once.assert_called_once_with(
                            rescan_mode='full', drop=runner.stat.new.return_value)
                    runner.map_exit.assert_called_once()

    def test_scan_result_without_handled_event_does_not_skip_radar(self):
        runner = self.runner(full=True, radar=True)
        runner.map_rescan_once.side_effect = None
        runner.map_rescan_once.return_value = True
        runner.clear_obscure()
        runner.clear_question_any_fleet.assert_called_once()

    def test_same_collector_captures_battle_scans_and_exit(self):
        runner = self.runner(full=True, radar=True)
        runner.map_rescan_once.side_effect = lambda **kwargs: kwargs['drop'].add('scan-reward')
        runner.clear_obscure()
        drop = runner.stat.new.return_value
        runner.map_rescan.assert_called_once_with(rescan_mode='current', drop=drop)
        runner.map_exit.assert_called_once_with(drop=drop)
        self.assertEqual(runner.stat.commit.call_args.kwargs['images'],
                         ['battle-reward', 'map', 'scan-reward', 'radar-reward', 'exit-reward'])

    def test_failed_normal_search_resumes_once_after_configuration_reload(self):
        first = self.runner()
        first.os_auto_search_run.side_effect = GameStuckError('第一次卡死')
        with self.assertRaises(GameStuckError):
            first.clear_obscure()
        self.assertFalse(first.config.cross_get(OBSCURE_RESUME_KEY)['resumed'])

        second = self.runner(full=True, radar=True, keep_state=True)

        def fail_again(*args, **kwargs):
            # 操作之前必须已经把“续接过”保存到磁盘。
            state = json.loads(self.path.read_text(encoding='utf-8'))['OpsiObscure']['OpsiObscure']['ResumeState']
            self.assertTrue(state['resumed'])
            raise GameStuckError('第二次卡死')

        second.map_rescan_once.side_effect = fail_again
        with self.assertRaises(GameStuckError):
            second.os_init()
        second.os_order_execute.assert_not_called()
        second.map_exit.assert_not_called()

        third = self.runner(full=True, radar=True, keep_state=True)
        third.os_init()
        third.os_auto_search_run.assert_not_called()
        third.map_rescan.assert_not_called()
        third.map_rescan_once.assert_not_called()
        third.clear_question_any_fleet.assert_not_called()
        third.map_exit.assert_called_once_with()
        self.assertIsNone(third.config.cross_get(OBSCURE_RESUME_KEY))

    def test_successful_resume_runs_followups_and_clears_record(self):
        runner = self.runner(full=True, radar=True)
        runner._save_obscure_resume()
        runner.os_init()
        self.assertEqual(runner.actions, ['after', 'battle', 'question', 'current', 'full', 'radar', 'exit', 'after'])
        runner.os_auto_search_run.assert_called_once()
        runner.storage_get_next_item.assert_not_called()
        runner.os_order_execute.assert_not_called()
        self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))
        reloaded = AzurLaneConfig('obscure-test', task='OpsiObscure')
        self.assertIsNone(reloaded.cross_get(OBSCURE_RESUME_KEY))

    def test_cross_month_hidden_zone_uses_same_optional_scans(self):
        runner = self.runner(task='OpsiCrossMonth', full=True, radar=True)
        runner.os_mission_overview_accept = Mock(return_value=True)
        runner.os_finish_daily_mission = Mock(return_value=1)
        runner.storage_get_next_item.side_effect = [False, True, False]
        # 隐秘海域后即结束测试，不执行跨月任务后面的无限短猫清理。
        runner._meow_target_zone_tokens = Mock(side_effect=TaskEnd('结束测试'))
        with patch('module.os.tasks.cross_month.current_time', return_value=RESET), \
                patch('module.os.tasks.cross_month.get_os_next_reset', return_value=RESET), \
                self.assertRaisesRegex(TaskEnd, '结束测试'):
            runner.os_cross_month()
        self.assertEqual(runner.actions, ['battle', 'question', 'current', 'full', 'radar', 'exit', 'after'])
        runner.os_order_execute.assert_called_once_with(recon_scan=True, submarine_call=False)
        self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))

    def test_old_config_gets_disabled_scan_defaults_and_keeps_existing_settings(self):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        options = data['OpsiObscure']['OpsiObscure']
        for key in ('FullScan', 'RadarScan', 'ResumeState'):
            del options[key]
        options['ForceRun'] = True
        data['OpsiObscure']['OpsiFleet']['Fleet'] = 4
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        config = AzurLaneConfig('obscure-test', task='OpsiObscure')
        self.assertFalse(config.OpsiObscure_FullScan)
        self.assertFalse(config.OpsiObscure_RadarScan)
        self.assertIsNone(config.OpsiObscure_ResumeState)
        self.assertTrue(config.OpsiObscure_ForceRun)
        self.assertEqual(config.OpsiFleet_Fleet, 4)

    def test_failed_second_exit_keeps_resume_spent(self):
        runner = self.runner()
        runner._save_obscure_resume(resumed=True)
        runner.map_exit.side_effect = GameStuckError('退出失败')
        with self.assertRaises(GameStuckError):
            runner.resume_obscure()
        self.assertTrue(runner.config.cross_get(OBSCURE_RESUME_KEY)['resumed'])
        runner.os_auto_search_run.assert_not_called()

    def test_failures_during_orders_scans_or_exit_keep_resume_record(self):
        for method in ('os_order_execute', 'map_rescan_once', 'clear_question_any_fleet', 'map_exit'):
            with self.subTest(method=method):
                runner = self.runner(full=True, radar=True)
                getattr(runner, method).side_effect = GameStuckError(method)
                with self.assertRaises(GameStuckError):
                    runner.clear_obscure()
                state = runner.config.cross_get(OBSCURE_RESUME_KEY)
                self.assertFalse(state['resumed'])
                self.assertEqual(state['zone'], 44)
                runner.handle_after_auto_search.assert_not_called()

    def test_successful_exit_clears_state_before_after_search_failure(self):
        runner = self.runner()
        runner.handle_after_auto_search.side_effect = GameStuckError('来源海域维修异常')
        with self.assertRaises(GameStuckError):
            runner.clear_obscure()
        self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))

    def test_resume_uses_child_settings_and_restores_parent_identity(self):
        for task in ('OpsiScheduling', 'OpsiPreventActionPointOverflow', 'OpsiCrossMonth', 'OpsiDaily'):
            for fail in (False, True):
                with self.subTest(task=task, fail=fail):
                    runner = self.runner(task=task, full=True)
                    runner._save_obscure_resume()
                    owner = runner.config.task
                    original_bound = dict(runner.config.bound)

                    def search(drop, **kwargs):
                        self.assertEqual(runner.config.task.command, 'OpsiObscure')
                        self.assertEqual(runner.config.bound['OpsiFleet_Fleet'], 'OpsiObscure.OpsiFleet.Fleet')
                        if fail:
                            raise GameStuckError('续接异常')
                        return 0

                    runner.os_auto_search_run.side_effect = search
                    if fail:
                        with self.assertRaises(GameStuckError):
                            runner.resume_obscure()
                        self.assertTrue(runner.config.cross_get(OBSCURE_RESUME_KEY)['resumed'])
                    else:
                        runner.resume_obscure()
                        runner.map_rescan_once.assert_called_once()
                        self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))
                    self.assertIs(runner.config.task, owner)
                    self.assertEqual(runner.config.bound, original_bound)

    def test_other_zone_server_or_month_does_not_inherit_spent_resume(self):
        for changes in ({'zone': 22}, {'server': 'jp'}, {'reset': '2026-11-01T00:00:00'}):
            with self.subTest(changes=changes):
                runner = self.runner()
                runner._save_obscure_resume(resumed=True)
                state = dict(runner.config.cross_get(OBSCURE_RESUME_KEY), **changes)
                runner.config.cross_set(OBSCURE_RESUME_KEY, state)
                runner.resume_obscure()
                runner.os_auto_search_run.assert_called_once()

    def test_other_special_zones_still_exit_without_resume(self):
        runner = self.runner()
        runner._save_obscure_resume(resumed=True)
        runner.is_obscure_zone = False
        runner.os_init()
        runner.os_auto_search_run.assert_not_called()
        runner.map_exit.assert_called_once_with()
        self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))

    def test_missing_zone_clears_saved_record_before_continuing_after_reload(self):
        for resumed in (False, True):
            with self.subTest(resumed=resumed):
                first = self.runner()
                first._save_obscure_resume(resumed=resumed)
                runner = self.runner(keep_state=True, full=True, radar=True)
                runner.is_obscure_zone = False
                runner.is_in_special_zone.return_value = False

                def continue_initialization():
                    self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))

                runner.run_first_auto_search.side_effect = continue_initialization
                runner.os_init()
                runner.run_first_auto_search.assert_called_once()
                runner.os_auto_search_run.assert_not_called()
                runner.map_rescan.assert_not_called()
                runner.map_rescan_once.assert_not_called()
                runner.clear_question_any_fleet.assert_not_called()
                runner.map_exit.assert_not_called()
                runner.fleet_set.assert_not_called()
                self.assertIsNone(AzurLaneConfig('obscure-test', task='OpsiObscure').cross_get(OBSCURE_RESUME_KEY))

    def test_missing_exit_button_prevents_resume_even_with_old_obscure_name(self):
        for resumed in (False, True):
            with self.subTest(resumed=resumed):
                runner = self.runner()
                runner._save_obscure_resume(resumed=resumed)
                runner.is_in_special_zone.return_value = False
                self.assertFalse(runner.resume_obscure())
                self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))
                runner.os_auto_search_run.assert_not_called()
                runner.map_exit.assert_not_called()
                runner.fleet_set.assert_not_called()

    def test_missing_zone_keeps_scheduling_in_control(self):
        runner = self.runner(task='OpsiScheduling')
        runner._save_obscure_resume(resumed=True)
        owner = runner.config.task
        bound = dict(runner.config.bound)
        runner.is_obscure_zone = False
        runner.is_in_special_zone.return_value = False
        runner.is_smart_scheduling_enabled = Mock(return_value=True)
        runner.os_init()
        self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))
        self.assertIs(runner.config.task, owner)
        self.assertEqual(runner.config.bound, bound)
        self.assertTrue(runner._smart_scheduling_first_auto_search_pending)
        runner.run_first_auto_search.assert_not_called()
        runner.os_auto_search_run.assert_not_called()
        runner.map_exit.assert_not_called()

    def test_globe_returns_to_normal_map_without_attempting_missing_obscure_zone(self):
        runner = self.runner()
        runner._save_obscure_resume()
        runner.is_in_map.return_value = False
        runner.is_in_globe = Mock(return_value=True)

        def return_to_source():
            runner.is_in_map.return_value = True
            runner.is_obscure_zone = False
            runner.is_in_special_zone.return_value = False

        runner.os_globe_goto_map = Mock(side_effect=return_to_source)
        runner.os_init()
        self.assertIsNone(runner.config.cross_get(OBSCURE_RESUME_KEY))
        runner.os_globe_goto_map.assert_called_once()
        runner.run_first_auto_search.assert_called_once()
        runner.os_auto_search_run.assert_not_called()
        runner.map_exit.assert_not_called()

    def test_normal_map_without_saved_record_does_not_write_resume_state(self):
        runner = self.runner()
        runner.is_obscure_zone = False
        runner.is_in_special_zone.return_value = False
        with patch.object(runner.config, 'cross_set', wraps=runner.config.cross_set) as save:
            runner.os_init()
        save.assert_not_called()
        runner.run_first_auto_search.assert_called_once()

    def test_unrelated_task_without_owned_record_keeps_original_exit(self):
        for task in ('OpsiDaily', 'OpsiArchive', 'OpsiScheduling'):
            with self.subTest(task=task):
                runner = self.runner(task=task)
                runner.os_init()
                runner.os_auto_search_run.assert_not_called()
                runner.map_exit.assert_called_once_with()

    def test_new_obscure_zone_resets_previous_spent_resume(self):
        runner = self.runner()
        runner._save_obscure_resume(resumed=True)
        runner.clear_obscure()
        runner.os_init()
        self.assertEqual(runner.os_auto_search_run.call_count, 2)


class SharedScanTests(unittest.TestCase):
    def test_radar_only_does_not_start_hidden_full_scans_and_keeps_default_behavior(self):
        for rescan in (False, True):
            with self.subTest(rescan=rescan):
                runner = SimpleNamespace(
                    config=SimpleNamespace(OpsiFleet_Fleet=2), zone=SimpleNamespace(is_port=False),
                    fleet_set=Mock(), device=Mock(), radar=Mock(), clear_question=Mock(),
                    map_rescan_once=Mock(), _solved_map_event=set(),
                )
                runner.radar.predict_question.side_effect = [object(), None, None, None]
                self.assertFalse(OSMap.clear_question_any_fleet(runner, rescan=rescan))
                self.assertEqual(runner.fleet_set.call_args_list, [call(2), call(1), call(3), call(4)])
                runner.clear_question.assert_called_once_with(drop=None)
                self.assertEqual(runner.map_rescan_once.call_count, int(rescan))

    def test_radar_without_questions_only_switches_fleets(self):
        runner = SimpleNamespace(
            config=SimpleNamespace(OpsiFleet_Fleet=1), zone=SimpleNamespace(is_port=False),
            fleet_set=Mock(), device=Mock(), radar=Mock(), clear_question=Mock(),
            _solved_map_event=set(),
        )
        runner.radar.predict_question.return_value = None
        self.assertFalse(OSMap.clear_question_any_fleet(runner, rescan=False))
        self.assertEqual(runner.fleet_set.call_args_list, [call(1), call(2), call(3), call(4)])
        runner.clear_question.assert_not_called()
        runner.device.click.assert_not_called()

    def test_zone_name_detection_keeps_name_parsing_and_clears_obscure_flag(self):
        cases = (
            ('cn', '东北航道C-隐秘海域', '东北航道C-深渊海域', '东北航道C'),
            ('tw', '東北航道C-隱秘海域', '東北航道C-深淵海域', '東北航道C'),
            ('jp', '北東航路C-秘密海域', '北東航路C-異常海域', '北東航路C'),
            ('en', 'Northeast Passage C-Hidden Zone', 'Northeast Passage C-Abyssal Zone', 'northeastpassagec'),
        )
        for server, obscure, other, parsed in cases:
            with self.subTest(server=server):
                runner = OSMapOperation.__new__(OSMapOperation)
                runner.config = SimpleNamespace(SERVER=server)
                runner.device = Mock()
                with patch('module.os.map_operation.Ocr') as ocr:
                    ocr.return_value.ocr.side_effect = [obscure, other]
                    self.assertEqual(runner.get_zone_name(), parsed)
                    self.assertTrue(runner.is_obscure_zone)
                    self.assertEqual(runner.get_zone_name(), parsed)
                    self.assertFalse(runner.is_obscure_zone)


if __name__ == '__main__':
    unittest.main()
