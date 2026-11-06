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
from module.config.config import AzurLaneConfig, TaskEnd
from module.combat.combat import Combat as CommonCombat
from module.combat.assets import BATTLE_PREPARATION
from module.exception import GameStuckError
from module.map.map_grids import SelectedGrids
from module.os.abyssal_resume import ABYSSAL_CONTINUE_KEY, ABYSSAL_RESUME_KEY
from module.os.assets import ABYSSAL_MAP_CHECK
from module.os.config import OSConfig
from module.os.fleet import OSFleet
from module.os.map import OSMap
from module.os.tasks.abyssal import OpsiAbyssal
from module.os.operation_siren import OperationSiren
from module.os_combat.assets import ABYSSAL_LOW_RESOLVE
from module.os_combat.combat import Combat
from module.os_handler.assets import LEAVE_OS_POPUP_CLOSE
from module.os.assets import ABYSSAL_STAGE_2, MAP_GOTO_GLOBE
from module.ui.assets import BACK_ARROW


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
    runner.is_in_map = Mock(return_value=True)
    runner.handle_map_event = Mock(return_value='')
    runner.appear = Mock(return_value=False)
    runner.handle_os_map_fleet_lock = Mock()
    runner.fleet_low_resolve_appear = Mock(return_value=False)
    runner.os_order_execute = Mock()
    runner.map_exit = Mock()
    runner.boss_leave = Mock(side_effect=lambda: runner.actions.append(('leave', runner.current_fleet)))
    runner.stat = Mock()
    runner.stat.new.side_effect = lambda **kwargs: nullcontext(SimpleNamespace(count=0))
    return runner


def radar(enemy=None, question=None, boss=True):
    grids = []
    if enemy is not None:
        grids.append(SimpleNamespace(location=enemy, is_enemy=True, is_question=False, predict_boss=lambda: boss))
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

    def test_disabled_run_uses_stage_guard_without_accessing_resume_records(self):
        runner = make_runner(False)
        runner._load_abyssal_resume = Mock()
        runner._new_abyssal_resume = Mock()
        runner._save_abyssal_resume = Mock()
        runner._clear_abyssal_resume = Mock()
        runner.config.cross_set = Mock(wraps=runner.config.cross_set)
        runner.question_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(enemy=(0, -2))))
        runner.boss_clear = Mock(return_value=True)
        self.assertTrue(runner.run_abyssal())
        runner._load_abyssal_resume.assert_not_called()
        runner._new_abyssal_resume.assert_not_called()
        runner._save_abyssal_resume.assert_not_called()
        runner._clear_abyssal_resume.assert_not_called()
        runner.config.cross_set.assert_not_called()
        runner.update_os.assert_not_called()
        runner.fleet_set.assert_not_called()
        runner.question_goto.assert_called_once_with(has_fleet_step=True)
        runner.boss_clear.assert_called_once_with(
            has_fleet_step=True, allow_submarine_call=False,
            abyssal_check={'phase': 'boss', 'boss_confirmed': True})
        self.assertIsNone(runner._abyssal_normal_state)

    def test_normal_run_keeps_using_gates_before_boss_confirmation(self):
        runner = make_runner(False)
        runner.radar = radar(enemy=(0, -1), question=(0, -2))
        runner.view = [SimpleNamespace(predict_caught_by_siren=lambda: True, is_current_fleet=False)]

        def goto(**kwargs):
            if runner.question_goto.call_count == 2:
                runner.radar = radar(enemy=(0, -2))
                runner.view = []

        runner.question_goto = Mock(side_effect=goto)
        runner.boss_clear = Mock(return_value=True)
        self.assertTrue(runner.run_abyssal())
        self.assertEqual(runner.question_goto.call_count, 2)
        self.assertEqual(runner.device.screenshot.call_count, 2)

    def test_normal_run_waits_for_map_before_searching(self):
        runner = make_runner(False)
        runner.frame = 0
        runner.device.screenshot.side_effect = lambda: setattr(runner, 'frame', runner.frame + 1)
        runner.is_in_map.side_effect = lambda: runner.frame == 2
        runner.question_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(enemy=(0, -2))))
        runner.boss_clear = Mock(return_value=True)
        self.assertTrue(runner.run_abyssal())
        runner.handle_map_event.assert_called_once_with()
        runner.question_goto.assert_called_once_with(has_fleet_step=True)
        self.assertEqual(runner.device.screenshot.call_count, 2)

    def test_normal_boss_exit_requires_a_confirmed_map_and_rejects_stage2(self):
        for confirmed, in_map, stage2, cleared in (
                (False, True, False, False), (True, False, False, False),
                (True, True, True, False), (True, True, False, True)):
            with self.subTest(confirmed=confirmed, in_map=in_map, stage2=stage2):
                runner = make_runner(False)
                runner.is_in_map.return_value = in_map
                runner.appear.side_effect = lambda button, **kwargs: stage2 and button is ABYSSAL_STAGE_2
                runner.radar = radar(question=(0, -2))
                runner.boss_goto = Mock()
                self.assertEqual(runner.boss_clear(
                    allow_submarine_call=False,
                    abyssal_check={'phase': 'boss', 'boss_confirmed': confirmed}), cleared)
                self.assertEqual(runner.map_exit.call_count, int(cleared))
                self.assertIsNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))

    def test_normal_run_clears_only_its_memory_state_on_error(self):
        runner = make_runner(False)
        old = {'keep': 'existing-resume-record'}
        runner.config.cross_set(ABYSSAL_RESUME_KEY, old)
        runner.question_goto = Mock(side_effect=GameStuckError('offline normal interruption'))
        runner.boss_clear = Mock()
        with self.assertRaises(GameStuckError):
            runner.run_abyssal()
        self.assertIsNone(runner._abyssal_normal_state)
        self.assertEqual(runner.config.cross_get(ABYSSAL_RESUME_KEY), old)
        runner.boss_clear.assert_not_called()

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

    def test_entrance_question_beats_false_caught_and_enemy_predictions(self):
        for stage in ('entry1', 'entry2'):
            with self.subTest(stage=stage):
                runner = make_runner()
                state = runner._new_abyssal_resume()
                state.update(phase='boss', stage='fleet4')
                runner.radar = radar(enemy=(0, -1), question=(0, -2))
                runner.view = [SimpleNamespace(predict_caught_by_siren=lambda: True, is_current_fleet=False)]
                runner.appear.side_effect = lambda button, **kwargs: stage == 'entry2' and button is ABYSSAL_STAGE_2
                runner._refresh_abyssal_stage(state)
                self.assertEqual((state['phase'], state['stage']), ('search', stage))
                self.assertFalse(state['boss_confirmed'])
                self.assertFalse(runner._abyssal_boss_cleared(state))

    def test_stage2_scene_overrides_a_saved_boss_stage(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', stage='fleet4', boss_confirmed=True, active=4, fighting=True, completed=[4])
        runner.radar = radar(question=(0, -2))
        runner.appear.side_effect = lambda button, **kwargs: button is ABYSSAL_STAGE_2
        runner._refresh_abyssal_stage(state)
        self.assertEqual((state['phase'], state['stage'], state['active'], state['completed']),
                         ('search', 'entry2', 0, []))
        self.assertFalse(state['boss_confirmed'])
        self.assertFalse(runner._abyssal_boss_cleared(state))

    def test_legacy_boss_stage_without_a_battle_is_unconfirmed(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', stage='fleet4')
        state.pop('boss_confirmed')
        runner._save_abyssal_resume(state)
        self.assertFalse(runner._load_abyssal_resume()['boss_confirmed'])
        state.update(active=1, fighting=True)
        runner._save_abyssal_resume(state)
        self.assertTrue(runner._load_abyssal_resume()['boss_confirmed'])

    def test_question_is_an_exit_only_in_a_confirmed_boss_map(self):
        for confirmed, in_map, stage2, cleared in (
                (False, True, False, False), (True, False, False, False),
                (True, True, True, False), (True, True, False, True)):
            with self.subTest(confirmed=confirmed, in_map=in_map, stage2=stage2):
                runner = make_runner()
                state = runner._new_abyssal_resume()
                state.update(phase='boss', stage='boss', boss_confirmed=confirmed)
                runner.is_in_map.return_value = in_map
                runner.appear.side_effect = lambda button, **kwargs: stage2 and button is ABYSSAL_STAGE_2
                runner.radar = radar(question=(0, -2))
                self.assertEqual(runner._abyssal_boss_cleared(state), cleared)

    def test_transition_frames_do_not_predict_or_spend_resume(self):
        runner = make_runner()
        runner.frame = 0
        runner.device.screenshot.side_effect = lambda: setattr(runner, 'frame', runner.frame + 1)
        runner.is_in_map.side_effect = lambda: runner.frame == 2
        runner.radar = radar(enemy=(0, -2))
        runner.boss_clear = Mock(return_value=False)
        self.assertFalse(runner.run_abyssal(resume=True))
        self.assertEqual(runner.device.screenshot.call_count, 2)
        runner.handle_map_event.assert_called_once_with()
        runner.update_os.assert_called_once_with()
        runner.predict_radar.assert_called_once_with()
        self.assertTrue(runner._load_abyssal_resume()['resume_used'])

    def test_visible_player_fleet_blocks_false_caught_colour(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        runner.radar = radar(enemy=(0, -1), boss=False)
        runner.view = [SimpleNamespace(predict_caught_by_siren=lambda: True, is_current_fleet=True)]
        runner._refresh_abyssal_stage(state)
        self.assertEqual(state['phase'], 'search')
        self.assertFalse(state['boss_confirmed'])

    def test_restart_during_fleet1_leaves_before_fleet2(self):
        for recorded in (False, True):
            with self.subTest(recorded=recorded):
                runner = make_runner()
                state = runner._new_abyssal_resume()
                state.update(phase='boss', boss_confirmed=True, active=1 if recorded else 0, fighting=recorded,
                             completed=[4] if recorded else [])
                runner.view = [SimpleNamespace(predict_caught_by_siren=lambda: True, is_current_fleet=False)]
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
        state.update(phase='boss', boss_confirmed=True, active=1, completed=[4])
        runner.boss_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(question=(0, 1))))
        self.assertTrue(runner.boss_clear(allow_submarine_call=False, abyssal_state=state))
        runner.boss_leave.assert_not_called()
        runner.fleet_set.assert_called_once_with(1)

    def test_saved_battle_fleet_is_restored_before_withdrawal(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', boss_confirmed=True, active=1, fighting=True, completed=[4])
        runner.current_fleet = 3
        runner.boss_goto = Mock(side_effect=lambda **kwargs: setattr(runner, 'radar', radar(question=(0, 1))))
        self.assertTrue(runner.boss_clear(allow_submarine_call=False, abyssal_state=state))
        self.assertEqual(runner.actions[:2], [('fleet', 1), ('leave', 1)])

    def test_normal_boss_order_and_standby_positions_are_preserved(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state['phase'] = 'boss'
        state['boss_confirmed'] = True
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
        state.update(phase='boss', boss_confirmed=True, active=1, fighting=True)
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
                    state.update(phase='boss', stage='fleet1', resume_used=True, active=1, completed=[4])
                    runner._abyssal_battle_progress = state
                    runner._record_abyssal_combat()
                    runner.config = AzurLaneConfig('abyssal-restart-test', task='OpsiScheduling')
                    saved = runner._load_abyssal_resume()
                    self.assertEqual((saved['active'], saved['completed'], saved['fighting']), (1, [4], True))
                    self.assertEqual((saved['stage'], saved['resume_used']), ('fleet1', True))
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

    def test_each_stage_has_one_non_accumulating_resume(self):
        for used in (False, True):
            with self.subTest(previous_stage_used=used):
                runner = make_runner()
                state = runner._new_abyssal_resume()
                state['resume_used'] = used
                for stage in ('entry2', 'boss', 'fleet4', 'fleet1', 'fleet2', 'fleet3'):
                    runner._set_abyssal_stage(state, stage)
                    self.assertFalse(state['resume_used'])
                    state['resume_used'] = True
                    runner._set_abyssal_stage(state, stage)
                    self.assertTrue(state['resume_used'])

    def test_second_restart_in_same_stage_uses_original_exit(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        runner.question_goto = Mock(side_effect=GameStuckError('first resume interrupted'))
        runner.boss_clear = Mock()
        with self.assertRaises(GameStuckError):
            runner.run_abyssal(resume=True)
        self.assertTrue(runner._load_abyssal_resume()['resume_used'])
        runner.question_goto.reset_mock(side_effect=True)
        self.assertTrue(runner.run_abyssal(resume=True))
        runner.question_goto.assert_not_called()
        runner.boss_clear.assert_not_called()
        runner.map_exit.assert_called_once_with()
        self.assertIsNone(runner._load_abyssal_resume())

    def test_stage2_scene_refreshes_used_stage1_before_resume(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state['resume_used'] = True
        runner._save_abyssal_resume(state)
        runner.appear.side_effect = lambda button, **kwargs: button is ABYSSAL_STAGE_2
        runner.question_goto = Mock(side_effect=GameStuckError('stage2 resumed'))
        with self.assertRaises(GameStuckError):
            runner.run_abyssal(resume=True)
        saved = runner._load_abyssal_resume()
        self.assertEqual(saved['stage'], 'entry2')
        self.assertTrue(saved['resume_used'])
        runner.map_exit.assert_not_called()

    def test_lost_map_clears_all_markers_without_boss_or_exit_actions(self):
        for stage in ('entry1', 'entry2', 'boss', 'fleet1'):
            with self.subTest(stage=stage):
                runner = make_runner()
                state = runner._new_abyssal_resume()
                state.update(stage=stage, resume_used=True, completed=[4], active=1, fighting=True)
                runner._save_abyssal_resume(state)
                runner.is_in_map.return_value = True
                runner.appear.side_effect = lambda button, **kwargs: button is MAP_GOTO_GLOBE
                runner.question_goto = Mock()
                runner.boss_clear = Mock()
                self.assertTrue(runner.run_abyssal(resume=True))
                self.assertIsNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))
                self.assertIsNone(runner._abyssal_progress)
                self.assertIsNone(runner._abyssal_battle_progress)
                runner.question_goto.assert_not_called()
                runner.boss_clear.assert_not_called()
                runner.map_exit.assert_not_called()

    def test_popup_or_transition_does_not_consume_lost_map_cleanup(self):
        runner = make_runner()
        runner.is_in_map.return_value = False
        runner._new_abyssal_resume()
        runner.appear.return_value = True
        self.assertFalse(runner._abyssal_map_finished())
        self.assertIsNotNone(runner._load_abyssal_resume())

    def test_lost_map_during_boss_move_does_not_restore_cleared_state(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', boss_confirmed=True, stage='fleet1', completed=[4])

        def disappear(**kwargs):
            runner.is_in_map.return_value = True
            runner.appear.side_effect = lambda button, **kwargs: button is MAP_GOTO_GLOBE

        runner.boss_goto = Mock(side_effect=disappear)
        self.assertTrue(runner.boss_clear(abyssal_state=state, allow_submarine_call=False))
        self.assertIsNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))
        runner.boss_leave.assert_not_called()
        runner.map_exit.assert_not_called()


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
                runner.resume_abyssal_on_init = Mock(side_effect=lambda: runner.actions.append('resume'))
                runner.os_init()
                self.assertEqual(runner.actions, ['resume', 'maintenance'] if enabled and abyssal else ['maintenance'])
                if enabled and abyssal:
                    runner.map_exit.assert_not_called()
                    runner.resume_abyssal_on_init.assert_called_once_with()
                else:
                    runner.map_exit.assert_called_once_with()
                    runner.resume_abyssal_on_init.assert_not_called()
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

    def test_public_context_works_for_standalone_and_combined_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'abyssal-init-test.json'
            path.write_text(Path('config/template.json').read_text(encoding='utf-8'), encoding='utf-8')
            from module.persistence.database import _directory
            token = _directory.set(Path(directory))
            try:
                with patch('module.config.config.filepath_config', return_value=str(path)), \
                        patch('module.config.config_updater.filepath_config', return_value=str(path)):
                    for cls in (OSMap, OpsiAbyssal, OperationSiren):
                        with self.subTest(entry=cls.__name__):
                            runner = cls.__new__(cls)
                            runner.config = AzurLaneConfig('abyssal-init-test', task='OpsiDaily')
                            owner = runner.config.task
                            runner.device = Mock()
                            runner.zone = SimpleNamespace(zone_id=44)
                            runner.zone_init = Mock()

                            def resume():
                                self.assertEqual(runner.config.task.command, 'OpsiAbyssal')
                                self.assertTrue(runner.config._disable_task_switch)

                            with patch.object(OpsiAbyssal, 'clear_abyssal', side_effect=resume) as clear:
                                runner.resume_abyssal_on_init()
                            clear.assert_called_once()
                            self.assertIs(runner.config.task, owner)
                            self.assertFalse(runner.config._disable_task_switch)
                            runner.zone_init.assert_called_once()
                            runner.device.click.assert_not_called()
            finally:
                _directory.reset(token)

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
        runner.run_abyssal.assert_called_once_with(resume=True)
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


class TestAbyssalExhaustedExit(unittest.TestCase):
    def make_exhausted_runner(self, enabled=True, resuming=True):
        runner = make_runner(enabled)
        runner.is_in_abyssal = Mock(return_value=resuming)
        runner.cl1_ap_preserve = Mock()
        runner.storage_get_next_item = Mock(return_value=True)
        runner.zone_init = Mock()
        runner.run_abyssal = Mock(return_value=False)
        runner.handle_fleet_repair_by_config = Mock(side_effect=lambda **kwargs: runner.actions.append('repair'))
        runner.map_exit.side_effect = lambda: runner.actions.append('exit')
        runner.config.cross_set(ABYSSAL_RESUME_KEY, {'pending': 'exhausted-fleet'})
        return runner

    def test_exhausted_fleets_exit_and_clear_resume_before_maintenance(self):
        for enabled, resuming in ((False, False), (True, False), (True, True)):
            with self.subTest(enabled=enabled, resuming=resuming):
                runner = self.make_exhausted_runner(enabled, resuming)
                self.assertFalse(runner.clear_abyssal())  # 返回值仍表示过滤器是否包含潜艇命令。
                self.assertEqual(runner.actions, ['exit', 'repair'])
                self.assertIsNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))
                runner.map_exit.assert_called_once_with()
                runner.handle_fleet_repair_by_config.assert_called_once_with(revert=False)

    def test_exhausted_exit_allows_the_original_scheduler_check(self):
        runner = self.make_exhausted_runner()
        runner.config.OpsiAbyssal_ForceRun = False

        def check_switch():
            runner.actions.append('switch')
            raise TaskEnd

        runner.config.check_task_switch = Mock(side_effect=check_switch)
        with self.assertRaises(TaskEnd):
            runner.os_abyssal()
        self.assertEqual(runner.actions, ['exit', 'repair', 'switch'])
        self.assertIsNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))

    def test_failed_exit_keeps_resume_and_propagates_the_existing_error(self):
        runner = self.make_exhausted_runner()
        runner.map_exit.side_effect = GameStuckError('offline exit interrupted')
        with self.assertRaises(GameStuckError):
            runner.clear_abyssal()
        self.assertIsNotNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))
        runner.handle_fleet_repair_by_config.assert_not_called()

    def test_other_combat_errors_are_not_treated_as_exhausted_fleets(self):
        runner = self.make_exhausted_runner()
        runner.run_abyssal.side_effect = GameStuckError('offline combat interrupted')
        with self.assertRaises(GameStuckError):
            runner.clear_abyssal()
        runner.map_exit.assert_not_called()
        runner.handle_fleet_repair_by_config.assert_not_called()
        self.assertIsNotNone(runner.config.cross_get(ABYSSAL_RESUME_KEY))


class OfflineConfig(OSConfig, AzurLaneConfig):
    pass


class TestAbyssalCombatCancel(unittest.TestCase):
    def test_low_resolve_closes_backs_out_withdraws_and_uses_next_fleet(self):
        runner = make_runner()
        state = runner._new_abyssal_resume()
        state.update(phase='boss', boss_confirmed=True, stage='fleet1', completed=[4])
        runner._abyssal_battle_progress = state
        runner.config.campaign_name = 'abyssal-test'
        runner.config.DropRecord_CombatRecord = 'do_not'
        runner.combat_result_reset = Mock()
        runner.combat_execute = Mock()
        runner.combat_status = Mock()
        runner._clear_battle_status_s_timer = Mock()
        runner.radar = radar(enemy=(0, -1))
        runner.frame = None

        def frames(**kwargs):
            for frame in ('low_resolve', 'preparation', 'map'):
                runner.frame = frame
                yield

        runner.loop = frames
        runner.is_in_map.side_effect = lambda: runner.frame == 'map'
        runner.appear.side_effect = lambda button, **kwargs: (
            (runner.frame == 'low_resolve' and button in (ABYSSAL_LOW_RESOLVE, LEAVE_OS_POPUP_CLOSE))
            or (runner.frame == 'preparation' and button in (BATTLE_PREPARATION, BACK_ARROW))
        )
        attacked = []

        def move(location, **kwargs):
            if location == (0, 0):
                attacked.append(runner.current_fleet)
                if runner.current_fleet == 1:
                    runner._record_abyssal_combat()
                    self.assertFalse(runner.combat(
                        balance_hp=False, emotion_reduce=False, auto_mode='combat_auto',
                        submarine_mode='do_not_use', save_get_items=False))
                else:
                    runner.radar = radar(question=(0, 1))

        runner.boss_goto = Mock(side_effect=move)
        self.assertTrue(runner.boss_clear(abyssal_state=state, allow_submarine_call=False))
        self.assertEqual(attacked, [1, 2])
        self.assertEqual([call.args[0] for call in runner.device.click.call_args_list],
                         [LEAVE_OS_POPUP_CLOSE, BACK_ARROW])
        self.assertIn(('leave', 1), runner.actions)
        runner.combat_execute.assert_not_called()
        runner.combat_status.assert_not_called()

    def test_common_combat_cancel_is_opt_in(self):
        for allow in (False, True):
            with self.subTest(allow=allow):
                runner = make_runner()
                runner.config.campaign_name = 'test'
                runner.config.DropRecord_CombatRecord = 'do_not'
                runner.combat_result_reset = Mock()
                runner.combat_preparation = Mock(return_value=False)
                runner.combat_execute = Mock()
                runner.combat_status = Mock()
                result = CommonCombat.combat(
                    runner, balance_hp=False, emotion_reduce=False, auto_mode='combat_auto',
                    submarine_mode='do_not_use', save_get_items=False, allow_preparation_cancel=allow)
                self.assertEqual(runner.combat_execute.call_count, int(not allow))
                self.assertEqual(runner.combat_status.call_count, int(not allow))
                if allow:
                    self.assertFalse(result)


class TestAbyssalScreenshots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        cls.cv_threads = cv2.getNumThreads()
        cv2.setNumThreads(1)

    @classmethod
    def tearDownClass(cls):
        import cv2
        cv2.setNumThreads(cls.cv_threads)

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

    def test_stage2_with_legacy_fleet4_checkpoint_still_enters_the_gate(self):
        runner = OSFleet.__new__(OSFleet)
        runner.config = OfflineConfig.__new__(OfflineConfig)
        runner.config.HOMO_EDGE_DETECT = False
        stub = ConfigStub()
        runner.config.cross_get, runner.config.cross_set = stub.cross_get, stub.cross_set
        runner.zone = SimpleNamespace(zone_id=44)
        runner.interval_timer = {}
        runner.device = Mock(image=load_image(str(FIXTURES / 'stage2.png')))
        runner.handle_os_map_fleet_lock = Mock()
        runner.boss_clear = Mock(return_value=True)
        runner.map_exit = Mock()
        runner.wait_until_walk_stable = Mock(side_effect=lambda **kwargs: setattr(
            runner.device, 'image', load_image(str(FIXTURES / 'boss.png'))))
        with patch('module.os.abyssal_resume.get_os_next_reset', return_value=RESET):
            state = runner._new_abyssal_resume()
            state.update(phase='boss', stage='fleet4', resume_used=True)
            state.pop('boss_confirmed')
            runner._save_abyssal_resume(state)
            self.assertTrue(runner.run_abyssal(resume=True))
        self.assertEqual([tuple(call.args[0].location) for call in runner.device.click.call_args_list], [(5, 4)])
        runner.map_exit.assert_not_called()
        boss_state = runner.boss_clear.call_args.kwargs['abyssal_state']
        self.assertEqual(boss_state['phase'], 'boss')
        self.assertTrue(boss_state['boss_confirmed'])

    def test_normal_entry_screens_ignore_false_caught_colour_without_saving_progress(self):
        for start, next_images in (('stage1', ('stage2', 'boss')), ('stage2', ('boss',))):
            with self.subTest(start=start):
                runner = OSFleet.__new__(OSFleet)
                runner.config = OfflineConfig.__new__(OfflineConfig)
                runner.config.HOMO_EDGE_DETECT = False
                stub = ConfigStub(False)
                runner.config.cross_get = stub.cross_get
                runner.config.cross_set = Mock(wraps=stub.cross_set)
                runner.zone = SimpleNamespace(zone_id=44)
                runner.interval_timer = {}
                runner.device = Mock(image=load_image(str(FIXTURES / (start + '.png'))))
                runner.handle_os_map_fleet_lock = Mock()
                runner.boss_clear = Mock(return_value=True)
                runner.map_exit = Mock()
                images = iter([load_image(str(FIXTURES / (name + '.png'))) for name in next_images])
                runner.wait_until_walk_stable = Mock(side_effect=lambda **kwargs: setattr(
                    runner.device, 'image', next(images)))
                with patch('module.map_detection.os_grid.OSGrid.predict_caught_by_siren', return_value=True):
                    self.assertTrue(runner.run_abyssal())
                self.assertEqual(runner.device.click.call_count, len(next_images))
                self.assertTrue(runner.boss_clear.call_args.kwargs['abyssal_check']['boss_confirmed'])
                runner.map_exit.assert_not_called()
                runner.config.cross_set.assert_not_called()

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
                self.assertEqual(ABYSSAL_STAGE_2.match(runner.device.image, offset=(20, 20)), name == 'stage2')
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
