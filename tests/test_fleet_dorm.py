"""换船后宅联动的截图识别、逐次选中、失败跳过和出击顺序；不连接账号。"""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.campaign.fleet_rotation import preflight_rotation
from module.device.connection import Connection
from module.device.control import control_interval, wait_control_interval
from module.device.device import Device
from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.dorm.assets import (DORM_FLEET_CANCEL, DORM_FLEET_CHECK, DORM_FLEET_CONFIRM,
                               DORM_FLEET_REST, DORM_FLEET_TRAIN, OCR_DORM_FLEET_AMOUNT)
from module.dorm.fleet_rotation import (DORM_PATH, DormArrangeError, DormCounter, DormFleetScanner,
                                       DORM_SLOTS, FleetRotationDorm, rest_after_rotation, rest_fleet)
from module.exception import GameStuckError
from module.ocr.al_ocr import AlOcr, OcrSettings
from module.retire.assets import DOCK_CHECK, DOCK_SELECTED
from module.ui.assets import DORM_CHECK, DORM_INFO
from module.ui.page import page_main
import tests.test_fleet_rotation as rotation_cases
import tests.test_fleet_training as training_cases
from tests.test_api import fixture


FIXTURES = Path(__file__).parent / 'fixtures/fleet_dorm'


def frame(name):
    return np.array(Image.open(FIXTURES / f'{name}.png').convert('RGB'))


def config(values=None, order='fleet1_mob_fleet2_boss'):
    values = values or {}
    return SimpleNamespace(cross_get=lambda path, default=None: deepcopy(values.get(path, default)),
                           Fleet_FleetOrder=order, Fleet_Fleet1=4, Fleet_Fleet2=5)


class DormRuleTests(unittest.TestCase):
    def test_generated_defaults_and_real_config_save_validate_only_the_new_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            before = service.get('testpilot')
            self.assertEqual({'Enabled': False, 'Floor': 'floor_1'}, before['values']['FleetInfo']['FleetDorm'])
            after = service.patch('testpilot', before['revision'],
                                  [ConfigChange(path=DORM_PATH + '.Enabled', value=True),
                                   ConfigChange(path=DORM_PATH + '.Floor', value='floor_2')])
            self.assertEqual({'Enabled': True, 'Floor': 'floor_2'}, after['values']['FleetInfo']['FleetDorm'])
            self.assertEqual(before['values']['FleetInfo']['FleetRotation'], after['values']['FleetInfo']['FleetRotation'])
            with self.assertRaises(ApiError):
                service.patch('testpilot', after['revision'],
                              [ConfigChange(path=DORM_PATH + '.Floor', value='floor_3')])

    def test_disabled_and_no_actual_swap_do_not_enter_dorm(self):
        manager = Mock(config=config())
        with patch('module.dorm.fleet_rotation.FleetRotationDorm') as factory:
            rest_after_rotation(manager, {4, 5})
            manager.config = config({DORM_PATH + '.Enabled': True})
            rest_after_rotation(manager, set())
        factory.assert_not_called()
        manager._commit_formation.assert_not_called()

    def test_priority_uses_actual_fleet_and_all_battle_mob_boss_roles(self):
        for order, expected in [('fleet1_all_fleet2_standby', 4), ('fleet1_standby_fleet2_all', 5),
                                ('fleet1_mob_fleet2_boss', 4), ('fleet1_boss_fleet2_mob', 5)]:
            cfg = config({DORM_PATH + '.Enabled': True}, order)
            self.assertEqual(expected, rest_fleet(cfg, {4, 5}))
        self.assertEqual(4, rest_fleet(config({DORM_PATH + '.Enabled': True}, 'fleet1_boss_fleet2_mob'), {4}))

    def test_partial_training_swap_does_not_arrange_an_incomplete_round(self):
        manager = Mock(config=config({DORM_PATH + '.Enabled': True,
                                      'FleetInfo.FleetTraining.State': {'pending': {'1:4': {}}}}))
        with patch('module.dorm.fleet_rotation.FleetRotationDorm') as factory:
            rest_after_rotation(manager, {4})
        factory.assert_not_called()
        manager._commit_formation.assert_not_called()

    def test_counter_rejects_unknown_truncated_and_over_capacity_values(self):
        counter = DormCounter(DOCK_SELECTED)
        for text in ('', '66', '7/6', '6/0', '0/0', '16/6', '6/6x', '6//6'):
            self.assertIsNone(counter.after_process(text))
        self.assertEqual((0, 6), counter.after_process('0/6'))
        self.assertEqual((4, 6), counter.after_process('4/6'))


class DormImageTests(unittest.TestCase):
    def test_selected_marker_and_identity_survive_the_reported_overlapping_scroll(self):
        scanner = DormFleetScanner()
        old, selected, cleared = frame('picker_partial_last'), frame('picker_overlap_selected'), frame('picker_overlap_cleared')
        first = next(card for card in scanner.scan(old) if card.col == 6 and card.fleet == 1)
        fingerprint = scanner.fingerprint(old, first)
        cards = scanner.scan(selected)
        snake = next(card for card in cards if card.col == 6 and card.fleet == 1)
        self.assertEqual([(6, 98)], [(card.col, card.y) for card in cards if scanner.selected(selected, card)])
        self.assertTrue(scanner.same_ship(selected, snake, fingerprint))
        different = next(card for card in cards if card.col == 6 and card.y != snake.y)
        self.assertFalse(scanner.same_ship(selected, different, fingerprint))
        snake = next(card for card in scanner.scan(cleared) if card.col == 6 and card.fleet == 1)
        self.assertFalse(scanner.selected(cleared, snake))
        self.assertTrue(scanner.same_ship(cleared, snake, fingerprint))

    def test_scrolled_selected_ship_is_recognized_while_the_last_ship_is_still_partial(self):
        scanner = DormFleetScanner()
        image = frame('picker_partial_last')
        cards = scanner.scan(image)
        self.assertEqual([(6, 317)], [(card.col, card.y) for card in cards if scanner.selected(image, card)])
        self.assertEqual([(6, 317)], [(card.col, card.y) for card in cards if card.fleet == 1])
        self.assertTrue(all(card.y + 190 <= 627 for card in cards))

    def test_new_client_target_ships_are_on_the_third_row_not_deep_in_the_dock(self):
        scanner = DormFleetScanner()
        top, next_row = frame('vanguard_top_slow'), frame('vanguard_row_slow')
        self.assertEqual([(1, 75)], [(card.col, card.y) for card in scanner.scan(top) if card.fleet == 1])
        self.assertEqual([(2, 403), (3, 403)],
                         [(card.col, card.y) for card in scanner.scan(next_row) if card.fleet == 1])

    def test_selected_markers_and_fleet_four_after_scrolling(self):
        scanner = DormFleetScanner()
        image = frame('picker_selected')
        cards = scanner.scan(image)
        self.assertEqual([(col, 75) for col in range(1, 7)],
                         [(card.col, card.y) for card in cards if scanner.selected(image, card)])
        image = frame('picker_scrolled')
        cards = scanner.scan(image)
        self.assertEqual([(4, 175), (5, 175), (6, 175)],
                         [(card.col, card.y) for card in cards if card.fleet == 4])
        self.assertFalse(any(scanner.selected(image, card) for card in cards))

    def test_active_floor_and_real_panel_and_dock_counters(self):
        engine = AlOcr(name='azur_lane', settings=OcrSettings('onnx', 'cpu', False, 'standard'),
                       save_debug_images=False)
        with patch('module.ocr.ocr.OCR_MODEL', SimpleNamespace(azur_lane=engine)):
            for name, active, inactive in [('training', DORM_FLEET_TRAIN, DORM_FLEET_REST),
                                            ('rest', DORM_FLEET_REST, DORM_FLEET_TRAIN)]:
                image = frame(name)
                self.assertTrue(active.match_template_color(image, offset=(3, 3)))
                self.assertFalse(inactive.match_template_color(image, offset=(3, 3)))
                self.assertEqual((6, 6), DormCounter(OCR_DORM_FLEET_AMOUNT).ocr(image))
            self.assertEqual((6, 6), DormCounter(DOCK_SELECTED).ocr(frame('picker_selected')))


class DormPanelNavigationTests(unittest.TestCase):
    def controller(self, initial, *, locked=False):
        tool = FleetRotationDorm.__new__(FleetRotationDorm)
        tool.config = SimpleNamespace(BUTTON_OFFSET=(20, 20))
        tool.interval_timer = {}
        tool.device = SimpleNamespace(image=frame(initial), stuck_record_add=Mock(), sleep=Mock())
        self.clock, self.current = 100., initial
        self.enterContext(patch('module.base.timer.time', side_effect=lambda: self.clock))
        def loop(**kwargs):
            for _ in range(12):
                self.clock += .2
                tool.device.image = frame(self.current)
                yield None
        def click(button):
            if button == DORM_INFO:
                self.current = 'training_handoff'
            elif button == DORM_FLEET_REST:
                if not locked:
                    self.current = 'rest'
            elif button == DORM_FLEET_TRAIN:
                self.current = 'training_handoff'
            elif button == DORM_SLOTS.buttons[0]:
                self.current = 'picker_selected'
            else:
                self.fail(f'不应在当前后宅面板点击{button}')
        tool.loop = loop
        tool.device.click = Mock(side_effect=click)
        return tool

    def test_existing_exp_popup_confirmation_precedes_rest_tab_and_first_slot(self):
        tool = self.controller('exp_popup')
        tool._enter_floor('floor_2')
        tool._open_picker('floor_2')
        self.assertEqual([DORM_INFO, DORM_FLEET_REST, DORM_SLOTS.buttons[0]],
                         [call.args[0] for call in tool.device.click.call_args_list])

    def test_exp_popup_at_picker_handoff_is_confirmed_before_opening_training_slot(self):
        tool = self.controller('exp_popup')
        tool._open_picker('floor_1')
        self.assertEqual([DORM_INFO, DORM_SLOTS.buttons[0]],
                         [call.args[0] for call in tool.device.click.call_args_list])

    def test_reported_training_panel_is_recognized_and_switches_to_rest_before_opening_picker(self):
        tool = self.controller('training_handoff')
        self.assertTrue(tool._panel())
        self.assertTrue(tool._floor('floor_1'))
        self.assertFalse(tool._floor('floor_2'))
        tool._open_picker('floor_2')
        self.assertEqual([DORM_FLEET_REST, DORM_SLOTS.buttons[0]],
                         [call.args[0] for call in tool.device.click.call_args_list])

    def test_already_correct_training_panel_opens_the_first_slot_without_switching_tabs(self):
        tool = self.controller('training_handoff')
        tool._open_picker('floor_1')
        tool.device.click.assert_called_once_with(DORM_SLOTS.buttons[0])

    def test_rest_panel_can_recover_back_to_requested_training(self):
        tool = self.controller('rest')
        tool._open_picker('floor_1')
        self.assertEqual([DORM_FLEET_TRAIN, DORM_SLOTS.buttons[0]],
                         [call.args[0] for call in tool.device.click.call_args_list])

    def test_locked_rest_tab_never_opens_a_slot_in_the_wrong_floor(self):
        tool = self.controller('training_handoff', locked=True)
        with self.assertRaisesRegex(DormArrangeError, '未确认进入后宅选船页'):
            tool._open_picker('floor_2')
        tool.device.click.assert_called_once_with(DORM_FLEET_REST)

    def test_floor_handoff_requires_two_new_matching_frames(self):
        tool = self.controller('rest')
        def transition(**kwargs):
            for name in ('rest', 'training_handoff', 'rest', 'rest'):
                self.clock += .2
                tool.device.image = frame(name)
                yield None
        tool.loop = transition
        tool._enter_floor('floor_2')
        tool.device.click.assert_called_once_with(DORM_FLEET_REST)
        self.assertAlmostEqual(100.8, self.clock)


class DormSelectionTests(unittest.TestCase):
    def controller(self, pages, selected=()):
        tool = FleetRotationDorm.__new__(FleetRotationDorm)
        tool.config = SimpleNamespace(Emulator_ControlMethod='MaaTouch')
        self.page, self.selected, self.clicks = 0, set(selected), []
        self.clock = 0.0
        self.enterContext(patch('module.base.timer.time', side_effect=lambda: self.clock))
        tool.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        tool.appear = Mock(return_value=True)
        tool.handle_popup_cancel = Mock(return_value=False)
        def loop(**kwargs):
            for _ in range(200):
                self.clock += .2
                yield tool.device.image
        tool.loop = loop
        def click(button):
            x, y = button.area[0] - 25, button.area[1] - 35
            card = next(card for card in pages[self.page] if (card.x, card.y) == (x, y))
            self.clicks.append(card.key)
            self.selected.symmetric_difference_update({card.key})
        def swipe(*args, **kwargs):
            self.page = min(self.page + 1, len(pages) - 1)
            tool.device.image = np.full((720, 1280, 3), self.page * 10, dtype=np.uint8)
        tool.device.click, tool.device.swipe = Mock(side_effect=click), Mock(side_effect=swipe)
        tool.device.drag = Mock(side_effect=swipe)
        scanner = Mock()
        scanner.scan.side_effect = lambda image: pages[self.page]
        scanner.selected.side_effect = lambda image, card: card.key in self.selected
        scanner.fingerprint.side_effect = DormFleetScanner.fingerprint
        scanner.same_ship.side_effect = DormFleetScanner.same_ship
        scroll = Mock(length=100)
        scroll.cal_position.side_effect = lambda main: self.page / max(1, len(pages) - 1)
        self.scanner, self.scroll = scanner, scroll
        self.enterContext(patch('module.dorm.fleet_rotation.DormFleetScanner', return_value=scanner))
        self.enterContext(patch('module.dorm.fleet_rotation.Scroll', return_value=scroll))
        counter = self.enterContext(patch('module.dorm.fleet_rotation.DormCounter')).return_value
        counter.ocr.side_effect = lambda image: (len(self.selected), 6)
        return tool, counter

    @staticmethod
    def card(key, col, fleet):
        return SimpleNamespace(key=key, x=90 + col * 165, y=75, fleet=fleet)

    def test_clear_every_old_selection_before_choosing_the_target_number(self):
        cards = [self.card('old1', 0, 1), self.card('old2', 1, 5),
                 self.card('target1', 2, 4), self.card('target2', 3, 4)]
        tool, _ = self.controller([cards], selected=('old1', 'old2'))
        tool._selection(4, 0, 6, clear=True)
        self.assertEqual(set(), self.selected)
        tool._selection(4, 2, 6)
        self.assertEqual({'target1', 'target2'}, self.selected)
        self.assertEqual(['old1', 'old2', 'target1', 'target2'], self.clicks)

    def test_portrait_animation_does_not_delay_clearing_the_visible_first_row(self):
        cards = [self.card('old1', 0, 1), self.card('old2', 1, 5)]
        tool, _ = self.controller([cards], selected=('old1', 'old2'))
        def animated_frames(**kwargs):
            for tick in range(200):
                self.clock += .2
                tool.device.image.fill(tick * 10 % 255)
                yield None
        tool.loop = animated_frames
        tool._selection(4, 0, 6, clear=True)
        self.assertEqual(['old1', 'old2'], self.clicks)
        self.assertLessEqual(self.clock, 1.2)
        self.scroll.cal_position.assert_not_called()

    def test_selected_count_ack_waits_for_the_card_marker_without_clicking_it_again(self):
        tool, _ = self.controller([[self.card('target', 0, 4)]])
        self.scanner.selected.side_effect = lambda image, card: card.key in self.selected and self.clock >= 1
        tool._selection(4, 1, 6)
        self.assertEqual(['target'], self.clicks)
        self.assertEqual({'target'}, self.selected)

    def test_count_increase_with_an_unreadable_marker_never_toggles_the_ship_back_off(self):
        tool, _ = self.controller([[self.card('target', 0, 4)]])
        self.scanner.selected.side_effect = lambda image, card: False
        with self.assertRaisesRegex(DormArrangeError, '卡片选中状态'):
            tool._selection(4, 1, 6)
        self.assertEqual(['target'], self.clicks)
        self.assertEqual({'target'}, self.selected)

    def test_confirmed_ship_is_not_reclicked_when_its_marker_flickers_and_row_shifts_one_pixel(self):
        cards = [self.card(name, col, 4) for col, name in enumerate(('one', 'two', 'three'))]
        for card in cards:
            card.y = 113
        tool, _ = self.controller([cards])
        def selected(image, card):
            if self.clock >= .6:
                card.y = 114
                if card.key == 'one':
                    return False
            return card.key in self.selected
        self.scanner.selected.side_effect = selected
        tool._selection(4, 3, 6)
        self.assertEqual(['one', 'two', 'three'], self.clicks)
        self.assertEqual({'one', 'two', 'three'}, self.selected)

    def test_overlap_and_other_fleets_are_not_toggled_or_selected(self):
        first = self.card('target1', 0, 4)
        second = self.card('target2', 1, 4)
        other = self.card('other', 2, 5)
        tool, _ = self.controller([[first, other], [first, second, other]])
        tool._selection(4, 2, 6)
        self.assertEqual(['target1', 'target2'], self.clicks)
        tool.device.drag.assert_called_once()
        self.assertEqual(.4, tool.device.drag.call_args.kwargs['hold_duration'])
        tool.device.swipe.assert_not_called()

    def test_fifth_ship_is_clicked_once_then_scrolls_for_the_remaining_sixth_ship(self):
        fifth, sixth = self.card('fifth', 6, 1), self.card('sixth', 0, 1)
        fifth.y = 317
        tool, _ = self.controller([[fifth], [fifth, sixth]],
                                 selected=('hidden1', 'hidden2', 'hidden3', 'hidden4'))
        tool._selection(1, 6, 6)
        self.assertEqual(['fifth', 'sixth'], self.clicks)
        self.assertEqual(6, len(self.selected))
        tool.device.drag.assert_called_once()
        tool.device.swipe.assert_not_called()

    def test_confirmed_fifth_ship_is_not_reclicked_after_an_overlapping_scroll_and_marker_miss(self):
        native = DormFleetScanner()
        images = [frame('picker_partial_last'), frame('picker_overlap_selected')]
        pages = [native.scan(image) for image in images]
        for page, cards in enumerate(pages):
            for card in cards:
                card.key = ('fifth' if card.fleet == 1 and card.col == 6 else
                            'sixth' if card.fleet == 1 and card.col == 0 else f'other:{page}:{card.x}:{card.y}')
        tool, _ = self.controller(pages, selected=('hidden1', 'hidden2', 'hidden3', 'hidden4'))
        tool.device.image = images[0]
        advance = tool.device.drag.side_effect
        def drag(*args, **kwargs):
            advance(*args, **kwargs)
            tool.device.image = images[self.page]
        tool.device.drag.side_effect = drag
        self.scanner.selected.side_effect = lambda image, card: (
            False if self.page == 1 and card.key == 'fifth' else card.key in self.selected)
        tool._selection(1, 6, 6)
        self.assertEqual(['fifth', 'sixth'], self.clicks)
        self.assertEqual(6, len(self.selected))
        tool.device.drag.assert_called_once()

    def test_only_one_held_drag_is_needed_for_the_two_ships_in_the_new_screenshots(self):
        scanner = DormFleetScanner()
        images = [frame('vanguard_top_slow'), frame('vanguard_row_slow')]
        pages = [scanner.scan(image) for image in images]
        for page, cards in enumerate(pages):
            for card in cards:
                card.key = f'{page}:{card.col}:{card.y}'
        selected = [card.key for card in pages[0] if scanner.selected(images[0], card)]
        tool, _ = self.controller(pages, selected=selected)
        advance = tool.device.drag.side_effect
        def drag(*args, **kwargs):
            advance(*args, **kwargs)
            tool.device.image = images[self.page]
        tool.device.drag.side_effect = drag
        tool.device.image = images[0]
        tool._selection(1, 3, 6)
        self.assertEqual(['1:2:403', '1:3:403'], self.clicks)
        tool.device.drag.assert_called_once()
        tool.device.swipe.assert_not_called()

    def test_stale_frames_after_a_drag_do_not_cause_another_drag(self):
        tool, _ = self.controller([[self.card('other', 0, 5)], [self.card('target', 1, 4)]])
        tool.device.drag.side_effect = None
        with self.assertRaisesRegex(DormArrangeError, '未确认列表移动'):
            tool._selection(4, 1, 6)
        tool.device.drag.assert_called_once()
        tool.device.click.assert_not_called()

    def test_scrollbar_jitter_without_card_movement_does_not_cause_another_drag(self):
        tool, _ = self.controller([[self.card('other', 0, 5)], [self.card('target', 1, 4)]])
        tool.device.drag.side_effect = None
        with patch('module.dorm.fleet_rotation.Scroll') as scroll:
            scroll.return_value.cal_position.side_effect = lambda main: .01 if int(self.clock * 5) % 2 else .02
            with self.assertRaisesRegex(DormArrangeError, '未确认列表移动'):
                tool._selection(4, 1, 6)
        tool.device.drag.assert_called_once()
        tool.device.click.assert_not_called()

    def test_missing_target_stops_after_the_prefix_instead_of_scrolling_the_whole_dock(self):
        tool, _ = self.controller([[self.card(f'other{page}', 0, 5)] for page in range(8)])
        with self.assertRaisesRegex(DormArrangeError, '前七排'):
            tool._selection(4, 1, 6)
        self.assertEqual(5, tool.device.drag.call_count)
        tool.device.click.assert_not_called()

    def test_backend_without_held_drag_uses_a_slow_swipe_without_a_fallback_click(self):
        tool, _ = self.controller([[self.card('other', 0, 5)], [self.card('target', 1, 4)]])
        tool.config.Emulator_ControlMethod = 'azurpilot_android'
        tool._selection(4, 1, 6)
        tool.device.swipe.assert_called_once()
        self.assertEqual(.6, tool.device.swipe.call_args.kwargs['duration'])
        tool.device.drag.assert_not_called()

    def test_click_without_verified_count_change_is_not_repeated(self):
        tool, _ = self.controller([[self.card('target', 0, 4)]])
        tool.device.click.side_effect = None
        with patch('module.dorm.fleet_rotation.Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            with self.assertRaisesRegex(DormArrangeError, '未确认已选数量变化'):
                tool._selection(4, 1, 6)
        tool.device.click.assert_called_once()

    def test_unknown_count_does_not_clear_or_select_any_card(self):
        tool, counter = self.controller([[self.card('target', 0, 4)]])
        counter.ocr.return_value, counter.ocr.side_effect = None, None
        with self.assertRaises(DormArrangeError):
            tool._selection(4, 1, 6)
        tool.device.click.assert_not_called()


class DormFlowTests(unittest.TestCase):
    def tool(self, *, capacity=6, floor='floor_2'):
        tool = FleetRotationDorm.__new__(FleetRotationDorm)
        formation = {category: {'4': [dict(slot=slot, occupied=True) for slot in slots]}
                     for category, slots in [('main', (1, 2, 3)), ('vanguard', (4, 5, 6))]}
        tool.config = config({DORM_PATH + '.Floor': floor, 'FleetInfo.FleetInfo.Result': formation})
        tool.device = SimpleNamespace(image=frame('picker_selected'))
        tool.loop = lambda **kwargs: iter(range(8))
        for name in ('ui_ensure', '_enter_floor', '_open_picker', 'dock_favourite_set',
                     'dock_filter_set', '_top', '_selection', '_confirm', '_leave'):
            setattr(tool, name, Mock())
        self.enterContext(patch('module.dorm.fleet_rotation.server.server', 'cn'))
        counter = self.enterContext(patch('module.dorm.fleet_rotation.DormCounter')).return_value
        counter.ocr.return_value = (capacity, capacity)
        return tool

    def test_both_floors_clear_then_select_vanguard_and_main_including_fixed_slots(self):
        for floor in ('floor_1', 'floor_2'):
            with self.subTest(floor=floor):
                tool = self.tool(floor=floor)
                events = Mock()
                for name in ('_open_picker', 'dock_filter_set', '_selection', '_confirm'):
                    events.attach_mock(getattr(tool, name), name)
                self.assertTrue(tool.run(4))
                tool._enter_floor.assert_called_once_with(floor)
                self.assertEqual([((4, 0, 6), {'clear': True}), ((4, 6, 6), {})],
                                 tool._selection.call_args_list)
                self.assertEqual([['vanguard', 'main']],
                                 [call.kwargs['index'] for call in tool.dock_filter_set.call_args_list])
                self.assertEqual(['_open_picker', 'dock_filter_set', '_selection', '_selection', '_confirm'],
                                 [call[0] for call in events.mock_calls])
                tool._confirm.assert_called_once_with(floor, 6)
                tool._leave.assert_called_once()

    def test_partial_visible_selection_never_reopens_filters_after_the_initial_setup(self):
        tool = self.tool()
        tool.device.image = frame('vanguard_top_slow')
        tool.run(4)
        self.assertEqual([['vanguard', 'main']],
                         [call.kwargs['index'] for call in tool.dock_filter_set.call_args_list])

    def test_capacity_locked_floor_and_unconfirmed_selection_skip_and_continue(self):
        tool = self.tool(capacity=5)
        self.assertFalse(tool.run(4))
        tool._selection.assert_not_called()
        tool._confirm.assert_not_called()
        tool._leave.assert_called_once()
        for method in ('_enter_floor', '_selection', '_confirm'):
            tool = self.tool()
            getattr(tool, method).side_effect = DormArrangeError('无法确认')
            self.assertFalse(tool.run(4))
            tool._leave.assert_called_once()

    def test_real_device_errors_are_not_hidden_as_a_dorm_skip(self):
        tool = self.tool()
        tool._enter_floor.side_effect = GameStuckError('设备交互失败')
        with self.assertRaises(GameStuckError):
            tool.run(4)

    def test_skip_cancels_picker_then_closes_panel_before_returning_home(self):
        tool = FleetRotationDorm.__new__(FleetRotationDorm)
        tool.loop = lambda **kwargs: iter(range(8))
        stages = iter(('picker', 'panel', 'dorm'))
        stage = {'value': ''}
        def next_stage(**kwargs):
            for current in stages:
                stage['value'] = current
                yield None
        tool.loop = next_stage
        tool.is_in_main = Mock(return_value=False)
        tool.handle_popup_cancel = Mock(return_value=False)
        tool.appear = lambda button, **kwargs: ((stage['value'] == 'picker' and button == DOCK_CHECK)
                                                or (stage['value'] == 'dorm' and button == DORM_CHECK))
        tool.appear_then_click, tool.ui_ensure = Mock(return_value=True), Mock()
        tool._leave()
        self.assertEqual([DORM_FLEET_CANCEL, DORM_FLEET_CHECK],
                         [call.args[0] for call in tool.appear_then_click.call_args_list])
        tool.ui_ensure.assert_called_once_with(page_main)


class DormIntegrationTests(unittest.TestCase):
    def fixture(self, training=False):
        case = (training_cases.TrainingIntegrationTests if training else rotation_cases.RotationIntegrationTests)()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.manager.config, case.manager.device = case.config, case.runner.device
        case.config.cross_set(DORM_PATH + '.Enabled', True)
        return case

    def test_morale_swap_finishes_all_slots_and_equipment_before_dorm_and_original_task(self):
        case = self.fixture()
        events = []
        rotate = case.manager.rotate_slot.side_effect
        def swap(*args):
            events.append('swap')
            return rotate(*args)
        case.manager.rotate_slot.side_effect = swap
        case.campaign.ensure_campaign_ui.side_effect = lambda **kwargs: events.append('task')
        case.config.cross_set('FleetInfo.FleetEquipment.Enabled', True)
        with patch('module.campaign.fleet_rotation.FleetRotationEquipment') as equipment, \
                patch('module.dorm.fleet_rotation.FleetRotationDorm') as dorm:
            equipment.return_value.apply_pending.side_effect = lambda: events.append('equipment')
            dorm.return_value.run.side_effect = lambda fleet: events.append(f'dorm:{fleet}')
            self.assertTrue(preflight_rotation(case.runner, 5, 'normal'))
        self.assertEqual(['swap', 'swap', 'swap', 'equipment', 'dorm:1', 'task'], events)
        case.manager._commit_formation.assert_called_once()

    def test_training_without_morale_uses_the_same_dorm_hook_and_no_swap_does_not_enter(self):
        case = self.fixture(training=True)
        case.configure(mood=False, level=True)
        with patch('module.dorm.fleet_rotation.FleetRotationDorm') as dorm:
            self.assertTrue(preflight_rotation(case.runner, 5, 'normal'))
            dorm.assert_not_called()
            case.profile[case.names[1, 4]]['level'] = 120
            case.runner._fleet_rotation_context['training_checked_at'] = None
            from module.runtime.fleet_training import INTERVAL_PATH
            case.config.cross_set(INTERVAL_PATH, 0)
            self.assertTrue(preflight_rotation(case.runner, 5, 'normal'))
            dorm.return_value.run.assert_called_once_with(1)

    def test_skipping_dorm_does_not_repeat_or_undo_swaps_or_block_task(self):
        case = self.fixture()
        with patch('module.dorm.fleet_rotation.FleetRotationDorm') as dorm:
            dorm.return_value.run.return_value = False
            self.assertTrue(preflight_rotation(case.runner, 5, 'normal'))
        self.assertEqual(3, case.manager.rotate_slot.call_count)
        self.assertFalse(case.state()['1'].get('rescan'))
        case.campaign.ensure_campaign_ui.assert_called_once()
        case.campaign.map_get_info.assert_called_once()


class FleetControlIntervalTests(unittest.TestCase):
    def device(self):
        tool = Device.__new__(Device)
        tool.config = SimpleNamespace(Emulator_ControlMethod='MaaTouch')
        tool.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        tool.sleep = Mock()
        tool.stuck_record_clear, tool.click_record_add, tool.click_record_check = Mock(), Mock(), Mock()
        tool.click_methods = {'MaaTouch': Mock()}
        tool.swipe_maatouch, tool.drag_maatouch = Mock(), Mock()
        self.enterContext(patch('module.statistics.resource_flow.reward_frame'))
        return tool

    def test_normal_controls_keep_their_original_timing(self):
        tool = self.device()
        tool.click(DORM_FLEET_CONFIRM)
        tool.swipe((1170, 470), (1170, 243))
        tool.drag((1170, 470), (1170, 243))
        tool.sleep.assert_not_called()
        self.assertEqual(3, tool.click_record_check.call_count)

    def test_click_swipe_and_drag_all_use_the_requested_interval_inside_the_scope(self):
        tool = self.device()
        with control_interval((.1, .3)):
            tool.click(DORM_FLEET_CONFIRM)
            tool.swipe((1170, 470), (1170, 243))
            tool.drag((1170, 470), (1170, 243))
        self.assertEqual([((.1, .3),)] * 3, [call.args for call in tool.sleep.call_args_list])
        self.assertEqual(3, tool.click_record_check.call_count)
        tool.click(DORM_FLEET_CONFIRM)
        self.assertEqual(3, tool.sleep.call_count)

    def test_nested_scopes_and_errors_restore_the_previous_interval(self):
        tool = self.device()
        with control_interval((.1, .3)):
            with self.assertRaisesRegex(ValueError, 'test'):
                with control_interval((.2, .2)):
                    wait_control_interval(tool)
                    raise ValueError('test')
            wait_control_interval(tool)
        wait_control_interval(tool)
        self.assertEqual([((.2, .2),), ((.1, .3),)], [call.args for call in tool.sleep.call_args_list])

    def test_random_sleep_values_stay_between_point_one_and_point_three(self):
        tool = self.device()
        tool.sleep = Connection.sleep
        with patch('module.device.connection.time.sleep') as sleep, control_interval((.1, .3)):
            for _ in range(20):
                wait_control_interval(tool)
        self.assertEqual(20, sleep.call_count)
        self.assertTrue(all(.1 <= call.args[0] <= .3 for call in sleep.call_args_list))

    def test_morale_rotation_is_paced_and_leaves_no_interval_for_the_following_task(self):
        case = rotation_cases.RotationIntegrationTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.runner.device = SimpleNamespace(sleep=Mock())
        rotate = case.manager.rotate_slot.side_effect
        def swap(*args):
            wait_control_interval(case.runner.device)
            return rotate(*args)
        case.manager.rotate_slot.side_effect = swap
        preflight_rotation(case.runner, 5, 'normal')
        self.assertEqual(3, case.runner.device.sleep.call_count)
        wait_control_interval(case.runner.device)
        self.assertEqual(3, case.runner.device.sleep.call_count)
