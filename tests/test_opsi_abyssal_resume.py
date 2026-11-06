"""深渊断点续战的离线回归，不连接模拟器或修改真实实例配置。"""

import json
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.base.utils import load_image
from module.config.deep import deep_get, deep_set
from module.config.config import AzurLaneConfig
from module.exception import GameStuckError
from module.map.map_grids import SelectedGrids
from module.os.abyssal_resume import ABYSSAL_CONTINUE_KEY, ABYSSAL_RESUME_KEY
from module.os.assets import ABYSSAL_MAP_CHECK
from module.os.config import OSConfig
from module.os.fleet import OSFleet
from module.os.operation_siren import OperationSiren
from module.os_combat.assets import ABYSSAL_LOW_RESOLVE
from module.os_combat.combat import Combat
from module.os_handler.assets import LEAVE_OS_POPUP_CLOSE


FIXTURES = Path(__file__).parent / 'fixtures' / 'opsi_abyssal_resume'
RESET = datetime(2026, 12, 1)


class ConfigStub:
    SERVER = 'cn'
    OpsiFleetFilter_Filter = 'Fleet-4 > CallSubmarine > Fleet-1 > Fleet-2 > Fleet-3'
    DropRecord_OpsiAbyssal = 'do_not'
    OpsiGeneral_UseLogger = True

    def __init__(self, enabled=True, task='OpsiAbyssal'):
        self.data = {}
        self.cross_set(ABYSSAL_CONTINUE_KEY, enabled)
        self.task = SimpleNamespace(command=task)
        self.bound = {}
        self.override = Mock()
        self.temporary = Mock(side_effect=lambda **kwargs: nullcontext())

    def cross_get(self, keys, default=None):
        return deep_get(self.data, keys, default)

    def cross_set(self, keys, value):
        deep_set(self.data, keys, value)


def make_runner(enabled=True):
    runner = OperationSiren.__new__(OperationSiren)
    runner.config = ConfigStub(enabled)
    runner.device = Mock(image='map')
    runner.zone = SimpleNamespace(zone_id=44)
    runner.fleet_selector = SimpleNamespace(get=lambda: runner.current_fleet)
    runner.current_fleet = 1
    runner.actions = []

    def switch(index):
        runner.current_fleet = index
        runner.actions.append(('fleet', index))
        return True

    runner.fleet_set = Mock(side_effect=switch)
    runner.update_os = Mock()
    runner.predict = Mock()
    runner.predict_radar = Mock()
    runner.radar = SelectedGrids([])
    runner.view = []
    runner.handle_os_map_fleet_lock = Mock()
    runner.fleet_low_resolve_appear = Mock(return_value=False)
    runner.os_order_execute = Mock()
    runner.map_exit = Mock()
    runner.boss_leave = Mock(side_effect=lambda: runner.actions.append(('leave', runner.current_fleet)))
    runner.stat = Mock()
    runner.stat.new.side_effect = lambda **kwargs: nullcontext(SimpleNamespace(count=0))
    return runner


def radar(enemy=None, question=None):
    grids = []
    if enemy is not None:
        grids.append(SimpleNamespace(location=enemy, is_enemy=True, is_question=False))
    if question is not None:
        grids.append(SimpleNamespace(location=question, is_enemy=False, is_question=True))
    return SelectedGrids(grids)


class TestAbyssalProgress(unittest.TestCase):
    def setUp(self):
        reset = patch('module.os.abyssal_resume.get_os_next_reset', return_value=RESET)
        reset.start()
        self.addCleanup(reset.stop)

    def test_default_is_off_in_source_generated_config_and_template(self):
        runner = make_runner(False)
        self.assertFalse(runner.abyssal_continue_enabled())
        self.assertFalse(AzurLaneConfig.OpsiAbyssal_ContinueAfterRestart)
        data = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
        self.assertFalse(deep_get(data, ABYSSAL_CONTINUE_KEY))

    def test_both_entry_stages_keep_original_fleet_across_restart(self):
        runner = make_runner()
        runner.current_fleet = 3
        state = runner._new_abyssal_resume()
        self.assertEqual(state['entry_fleet'], 3)
        for _ in range(2):
            restarted = make_runner()
            restarted.config.data = json.loads(json.dumps(runner.config.data))
            restarted.question_goto = Mock(side_effect=lambda **kwargs: setattr(
                restarted, 'radar', radar(enemy=(0, -2))))
            restarted.boss_clear = Mock(return_value=False)
            self.assertFalse(restarted.run_abyssal())
            restarted.fleet_set.assert_called_once_with(3)
            restarted.question_goto.assert_called_once_with(has_fleet_step=True)
            self.assertEqual(restarted._load_abyssal_resume()['entry_fleet'], 3)

    def test_disabled_run_keeps_question_navigation_and_original_boss_call(self):
        runner = make_runner(False)
        runner._load_abyssal_resume = Mock()
        runner.question_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(enemy=(0, -2))))
        runner.boss_clear = Mock(return_value=True)
        self.assertTrue(runner.run_abyssal())
        runner._load_abyssal_resume.assert_not_called()
        runner.update_os.assert_not_called()
        runner.fleet_set.assert_not_called()
        runner.question_goto.assert_called_once_with(has_fleet_step=True)
        runner.boss_clear.assert_called_once_with(has_fleet_step=True, allow_submarine_call=False)

    def test_visible_boss_front_or_behind_does_not_repeat_questions(self):
        for position in ((0, -2), (0, 1)):
            with self.subTest(position=position):
                runner = make_runner()
                runner.radar = radar(enemy=position)
                runner.question_goto = Mock()
                runner.boss_clear = Mock(return_value=True)
                self.assertTrue(runner.run_abyssal())
                runner.question_goto.assert_not_called()
                self.assertIsNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))

    def test_edge_arrow_does_not_skip_entry_questions(self):
        runner = make_runner()
        runner.radar = radar(enemy=(5, -1), question=(0, -3))
        runner.question_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(enemy=(0, -2))))
        runner.boss_clear = Mock(return_value=True)
        runner.run_abyssal()
        runner.question_goto.assert_called_once_with(has_fleet_step=True)

    def test_restart_during_fleet1_leaves_before_fleet2(self):
        for recorded in (False, True):
            with self.subTest(recorded=recorded):
                runner = make_runner()
                state = runner._new_abyssal_resume()
                state.update(phase='boss', active=1 if recorded else 0, fighting=recorded,
                             completed=[4] if recorded else [])
                runner.view = [SimpleNamespace(predict_caught_by_siren=lambda: True)]
                runner._abyssal_battle_progress = state

                def move(location, **kwargs):
                    runner.actions.append(('move', runner.current_fleet, location))
                    if location == (0, 0):
                        runner.radar = radar(question=(0, 1))

                runner.boss_goto = Mock(side_effect=move)
                self.assertTrue(runner.boss_clear(allow_submarine_call=False, abyssal_state=state))
                self.assertEqual(runner.actions, [('leave', 1), ('move', 1, (0, -1)),
                                                  ('fleet', 2), ('move', 2, (0, 0))])
                self.assertEqual(state['completed'], [4, 1])
                runner.os_order_execute.assert_not_called()

    def test_approaching_fleet_is_not_skipped_before_battle(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', active=1, completed=[4])
        runner.boss_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(question=(0, 1))))
        self.assertTrue(runner.boss_clear(allow_submarine_call=False, abyssal_state=state))
        runner.boss_leave.assert_not_called()
        runner.fleet_set.assert_called_once_with(1)

    def test_saved_battle_fleet_is_restored_before_withdrawal(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', active=1, fighting=True, completed=[4])
        runner.current_fleet = 3
        runner.boss_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(question=(0, 1))))
        self.assertTrue(runner.boss_clear(allow_submarine_call=False, abyssal_state=state))
        self.assertEqual(runner.actions[:2], [('fleet', 1), ('leave', 1)])

    def test_normal_boss_order_and_standby_positions_are_preserved(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state['phase'] = 'boss'
        attacked = []

        def move(location, **kwargs):
            runner.actions.append(('move', runner.current_fleet, location))
            if location == (0, 0):
                attacked.append(runner.current_fleet)
                runner.radar = radar(question=(0, 1)) if runner.current_fleet == 2 else radar(enemy=(0, -1))

        runner.boss_goto = Mock(side_effect=move)
        self.assertTrue(runner.boss_clear(allow_submarine_call=False, abyssal_state=state))
        self.assertEqual(attacked, [4, 1, 2])
        self.assertIn(('move', 4, (-1, -1)), runner.actions)
        self.assertIn(('move', 1, (0, -1)), runner.actions)
        runner.map_exit.assert_called_once()
        runner.os_order_execute.assert_not_called()

    def test_victory_before_restart_exits_without_replaying_boss(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', active=1, fighting=True)
        runner.radar = radar(question=(0, 1))
        runner.boss_goto = Mock()
        self.assertTrue(runner.boss_clear(abyssal_state=state))
        runner.map_exit.assert_called_once()
        runner.boss_leave.assert_not_called()
        runner.fleet_set.assert_not_called()

    def test_stale_or_invalid_state_is_discarded(self):
        for updates in ({'server': 'en'}, {'reset': 'old'}, {'zone': 22}, {'entry_fleet': 8},
                        {'completed': '4,1'}, {'phase': 'unknown'}):
            with self.subTest(updates=updates):
                runner = make_runner()
                state = runner._new_abyssal_resume()
                state.update(updates)
                runner._save_abyssal_resume(state)
                self.assertIsNone(runner._load_abyssal_resume())

    def test_actual_config_save_reload_preserves_other_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'abyssal-restart-test.json'
            data = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
            deep_set(data, ABYSSAL_CONTINUE_KEY, True)
            data['OpsiAbyssal']['Storage']['Storage'] = {'Unrelated': 'keep'}
            path.write_text(json.dumps(data), encoding='utf-8')
            from module.persistence.database import _directory
            token = _directory.set(Path(directory))
            try:
                with patch('module.config.config.filepath_config', return_value=str(path)), \
                        patch('module.config.config_updater.filepath_config', return_value=str(path)):
                    runner = make_runner()
                    runner.config = AzurLaneConfig('abyssal-restart-test', task='OpsiAbyssal')
                    state = runner._new_abyssal_resume()
                    state.update(phase='boss', active=1, completed=[4])
                    runner._abyssal_battle_progress = state
                    runner._record_abyssal_combat()
                    runner.config = AzurLaneConfig('abyssal-restart-test', task='OpsiScheduling')
                    saved = runner._load_abyssal_resume()
                    self.assertEqual((saved['active'], saved['completed'], saved['fighting']), (1, [4], True))
                    self.assertEqual(runner.config.cross_get('OpsiAbyssal.Storage.Storage.Unrelated'), 'keep')
            finally:
                _directory.reset(token)

    def test_exception_retains_progress_for_next_process(self):
        runner = make_runner()
        runner.radar = radar(enemy=(0, -2))

        def interrupt(**kwargs):
            state = kwargs['abyssal_state']
            state.update(active=1, completed=[4])
            runner._record_abyssal_combat()
            raise GameStuckError('offline restart')

        runner.boss_clear = Mock(side_effect=interrupt)
        with self.assertRaises(GameStuckError):
            runner.run_abyssal()
        self.assertTrue(runner._load_abyssal_resume()['fighting'])
        self.assertIsNone(runner._abyssal_battle_progress)


class TestAbyssalInitialization(unittest.TestCase):
    def test_resume_precedes_maintenance_and_preserves_other_initialization(self):
        for enabled, abyssal in ((False, True), (True, False), (True, True)):
            with self.subTest(enabled=enabled, abyssal=abyssal):
                runner = make_runner(enabled)
                runner.is_in_map = Mock(return_value=True)
                runner.zone_init = Mock()
                runner.is_in_abyssal = Mock(return_value=abyssal)
                runner.is_in_special_zone = Mock(return_value=not (enabled and abyssal))
                runner.handle_after_auto_search = Mock(side_effect=lambda: runner.actions.append('maintenance'))
                runner.handle_current_fleet_resolve = Mock()
                runner.hp_reset = Mock()
                runner.run_first_auto_search = Mock()
                runner.clear_abyssal = Mock()
                runner._run_with_opsi_task_context = Mock(side_effect=lambda *args: runner.actions.append('resume'))
                runner.os_init()
                self.assertEqual(runner.actions, ['resume', 'maintenance'] if enabled and abyssal else ['maintenance'])
                if enabled and abyssal:
                    runner.map_exit.assert_not_called()
                    runner._run_with_opsi_task_context.assert_called_once_with('OpsiAbyssal', runner.clear_abyssal)
                else:
                    runner.map_exit.assert_called_once_with()
                    runner._run_with_opsi_task_context.assert_not_called()
                runner.run_first_auto_search.assert_called_once_with()

    def test_new_coordinate_still_checks_ap_cooldown_and_inventory(self):
        runner = make_runner(False)
        runner.cl1_ap_preserve = Mock()
        runner._check_submarine_cooldown = Mock(return_value=(False, None))
        runner.storage_get_next_item = Mock(return_value=True)
        runner.zone_init = Mock()
        runner.run_abyssal = Mock(return_value=True)
        runner.handle_fleet_repair_by_config = Mock()
        runner.is_in_abyssal = Mock()
        runner.config.cross_set('OpsiAbyssal.OpsiFleetFilter.Filter', 'Fleet-4 > CallSubmarine')
        self.assertTrue(runner.clear_abyssal())
        runner.cl1_ap_preserve.assert_called_once()
        runner._check_submarine_cooldown.assert_called_once()
        runner.storage_get_next_item.assert_called_once_with('ABYSSAL', use_logger=True)
        runner.is_in_abyssal.assert_not_called()

    def test_in_progress_map_needs_no_new_coordinate_or_ap(self):
        runner = make_runner()
        runner.is_in_abyssal = Mock(return_value=True)
        runner.cl1_ap_preserve = Mock()
        runner._check_submarine_cooldown = Mock()
        runner.storage_get_next_item = Mock()
        runner.zone_init = Mock()
        runner.run_abyssal = Mock(return_value=True)
        runner.handle_fleet_repair_by_config = Mock()
        runner.clear_abyssal()
        runner.cl1_ap_preserve.assert_not_called()
        runner._check_submarine_cooldown.assert_not_called()
        runner.storage_get_next_item.assert_not_called()
        runner.run_abyssal.assert_called_once()
        runner.handle_fleet_repair_by_config.assert_called_once_with(revert=False)

    def test_new_coordinate_keeps_submarine_cooldown_with_switch_on_or_off(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                runner = make_runner(enabled)
                runner.is_in_abyssal = Mock(return_value=False)
                runner.cl1_ap_preserve = Mock()
                runner._check_submarine_cooldown = Mock(return_value=(True, RESET))
                runner._delay_until_submarine_cooldown_end = Mock()
                runner.storage_get_next_item = Mock()
                runner.config.cross_set('OpsiAbyssal.OpsiFleetFilter.Filter', 'Fleet-4 > CallSubmarine')
                self.assertFalse(runner.clear_abyssal())
                runner.cl1_ap_preserve.assert_called_once()
                runner._delay_until_submarine_cooldown_end.assert_called_once_with(RESET)
                runner.storage_get_next_item.assert_not_called()


class OfflineConfig(OSConfig, AzurLaneConfig):
    pass


class TestAbyssalScreenshots(unittest.TestCase):
    def test_original_two_stage_question_route_is_identical_with_switch_on_or_off(self):
        routes = []
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                runner = OSFleet.__new__(OSFleet)
                runner.config = OfflineConfig.__new__(OfflineConfig)
                runner.config.HOMO_EDGE_DETECT = False
                stub = ConfigStub(enabled)
                runner.config.cross_get = stub.cross_get
                runner.config.cross_set = stub.cross_set
                runner.zone = SimpleNamespace(zone_id=44)
                runner.interval_timer = {}
                runner.device = Mock(image=load_image(str(FIXTURES / 'stage1.png')))
                runner.handle_os_map_fleet_lock = Mock()
                runner.boss_clear = Mock(return_value=True)
                images = iter([load_image(str(FIXTURES / (name + '.png'))) for name in ('stage2', 'boss')])
                runner.wait_until_walk_stable = Mock(side_effect=lambda **kwargs: setattr(
                    runner.device, 'image', next(images)))
                with patch('module.os.abyssal_resume.get_os_next_reset', return_value=RESET):
                    self.assertTrue(runner.run_abyssal())
                routes.append([tuple(call.args[0].location) for call in runner.device.click.call_args_list])
                self.assertEqual(len(routes[-1]), 2)
        self.assertEqual(routes[0], routes[1])

    def test_six_map_states_and_caught_detection(self):
        runner = OSFleet.__new__(OSFleet)
        runner.config = OfflineConfig.__new__(OfflineConfig)
        runner.config.HOMO_EDGE_DETECT = False
        runner.interval_timer = {}
        for name in ('stage1', 'stage2', 'boss', 'engaged', 'withdrawn', 'damaged'):
            with self.subTest(name=name):
                runner.device = Mock(image=load_image(str(FIXTURES / (name + '.png'))))
                runner.update_os()
                runner.predict()
                runner.predict_radar()
                self.assertTrue(runner.is_in_abyssal())
                self.assertEqual(runner.fleet_selector.get(), 1)
                caught = any(grid.predict_caught_by_siren() for grid in runner.view)
                self.assertEqual(caught, name in ('engaged', 'damaged'))
                if name in ('stage1', 'stage2'):
                    self.assertTrue(runner.radar.select(is_question=True))
                elif name in ('boss', 'withdrawn'):
                    self.assertTrue(runner.radar.select(is_enemy=True))

    def test_low_resolve_closes_x_only_with_switch_and_abyssal_context(self):
        for enabled, active, clicks in ((False, True, 0), (True, False, 0), (True, True, 1)):
            with self.subTest(enabled=enabled, active=active):
                runner = Combat.__new__(Combat)
                runner.config = ConfigStub(enabled)
                runner.interval_timer = {}
                runner._abyssal_battle_progress = {} if active else None
                runner.device = Mock(image=load_image(str(FIXTURES / 'low_resolve.png')))
                self.assertEqual(runner.handle_abyssal_low_resolve(), bool(clicks))
                self.assertEqual(runner.device.click.call_count, clicks)
                if clicks:
                    runner.device.click.assert_called_once_with(LEAVE_OS_POPUP_CLOSE)
                    self.assertFalse(runner.handle_abyssal_low_resolve())

    def test_map_and_popup_templates_do_not_match_each_other(self):
        image = load_image(str(FIXTURES / 'low_resolve.png'))
        self.assertFalse(ABYSSAL_MAP_CHECK.match(image, offset=(20, 20)))
        for name in ('stage1', 'stage2', 'boss', 'engaged', 'withdrawn', 'damaged'):
            image = load_image(str(FIXTURES / (name + '.png')))
            self.assertFalse(ABYSSAL_LOW_RESOLVE.match(image, offset=(20, 20)))


if __name__ == '__main__':
    unittest.main()
