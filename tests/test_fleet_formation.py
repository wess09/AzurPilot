"""舰位互换的无OCR操作链、图像定位和参考扫描回归；不连接模拟器。"""

from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.base.base import ModuleBase
from module.equipment.assets import FLEET_DETAIL, FLEET_DETAIL_CHECK, FLEET_NEXT, FLEET_PREV
from module.exception import FleetManagementError, GameStuckError, GameTooManyClickError, RequestHumanTakeover
from module.retire.assets import DOCK_CHECK, DOCK_EMPTY
from module.retire.fleet_management import FleetManagement, PICKER_CONFIRM
from module.runtime.fleet_formation import (SLOT_CENTERS, SUBMARINE_SLOT_CENTERS, FormationCardMerger,
    FormationDetailScanner, FormationDockScanner, PortraitMatcher, VisualDockScanner, choose_portrait,
    combine_references, detail_occupied, detail_portraits, menu_area, selected_count_changed,
    bottom_fleet_index, fleet_type_selected, selected_menu_fleet, selector_closed, slot_swap_plan, preserve_emotions,
    validate_position, validate_swap)
from module.ui.assets import BACK_ARROW, FLEET_CHECK
from module.ui.page import page_fleet, page_main, page_main_white


FIXTURES = Path(__file__).parent / 'fixtures/fleet_formation'


def frame(name):
    return np.array(Image.open(FIXTURES / f'{name}.png').convert('RGB'))


def runner():
    tool = FleetManagement.__new__(FleetManagement)
    tool.config = SimpleNamespace(cross_get=Mock(return_value={}), cross_set=Mock(), modified={}, save=Mock())
    tool.device = SimpleNamespace(image=frame('vanguard_top'), has_cached_image=True,
                                  click=Mock(), screenshot=Mock(), swipe=Mock())
    tool.dock_filter = SimpleNamespace(reset_first=True)
    for method in ('fleet_enter', '_open_slot', '_close_picker', '_prepare_dock', 'dock_reset',
                   'ui_ensure', '_save_result', '_confirm_replacement', '_commit_formation',
                   '_enter_scan_submarine', '_scan_fleet_enter'):
        setattr(tool, method, Mock())
    tool.appear = Mock(return_value=False)
    tool._scan_window = None
    return tool


def positions(main=(), front=()):
    return dict(zip(range(1, 7), list(main) + [False] * (3 - len(main)) +
                    list(front) + [False] * (3 - len(front))))


class GeometryTests(unittest.TestCase):
    def test_surface_and_submarine_positions_have_distinct_business_limits(self):
        self.assertEqual(sorted((1, 2, 3), key=lambda n: SLOT_CENTERS[n][0]), [3, 1, 2])
        self.assertEqual(sorted((4, 5, 6), key=lambda n: SLOT_CENTERS[n][0]), [4, 5, 6])
        self.assertEqual(sorted(SUBMARINE_SLOT_CENTERS, key=lambda n: SUBMARINE_SLOT_CENTERS[n][0]), [3, 1, 2])
        self.assertEqual(FleetManagement.slot_button(5).button, (748, 380, 766, 398))
        for fleet, slot, kind in ((0, 1, 'surface'), (7, 1, 'surface'), (True, 1, 'surface'),
                                 (1, False, 'surface'), (3, 1, 'submarine'), (1, 4, 'submarine')):
            with self.subTest(fleet=fleet, slot=slot, kind=kind), self.assertRaises(ValueError):
                validate_position(fleet, slot, kind)

    def test_native_menu_highlights_select_surface_and_submarine_without_number_ocr(self):
        self.assertEqual(selected_menu_fleet(frame('menu_surface')), 3)
        self.assertEqual(selected_menu_fleet(frame('menu_submarine'), 'submarine'), 2)
        for kind in ('surface', 'submarine'):
            self.assertIsNone(selected_menu_fleet(frame(f'closed_{kind}'), kind))
            self.assertTrue(selector_closed(frame(f'closed_{kind}'), kind))
            self.assertFalse(selector_closed(frame(f'menu_{kind}'), kind))
        self.assertEqual(menu_area(1), (152, 586, 353, 628))
        self.assertEqual(menu_area(6), (152, 316, 353, 358))

    def test_reported_fifth_fleet_menu_keeps_native_highlight_and_bottom_number(self):
        image = frame('menu_surface5_native')
        self.assertEqual(5, selected_menu_fleet(image))
        self.assertEqual(5, bottom_fleet_index(image))
        self.assertTrue(fleet_type_selected(image))
        self.assertFalse(selector_closed(image))

    def test_detail_columns_are_surface_one_to_six_and_submarine_one_to_three(self):
        surface = frame('detail_surface')
        submarine = frame('detail_submarine')
        self.assertEqual(set(detail_portraits(surface)), set(range(1, 7)))
        self.assertEqual(set(detail_portraits(submarine, 'submarine')), {1, 2, 3})
        self.assertTrue(all(detail_occupied(surface, slot) for slot in range(1, 7)))
        self.assertTrue(all(detail_occupied(submarine, slot) for slot in range(1, 4)))

    def test_native_type_buttons_select_only_the_brown_gold_category(self):
        for selected in ('surface', 'submarine'):
            for stage in ('menu', 'closed'):
                image = frame(f'{stage}_{selected}')
                for kind in ('surface', 'submarine'):
                    self.assertEqual(fleet_type_selected(image, kind), kind == selected)

    def test_latest_closed_selector_ignores_the_changing_diagonal_background(self):
        image = frame('swap_surface6')
        self.assertTrue(fleet_type_selected(image))
        self.assertEqual(bottom_fleet_index(image), 6)
        self.assertTrue(selector_closed(image))
        self.assertIsNone(selected_menu_fleet(image))
        self.assertFalse(selector_closed(frame('menu_surface')))

    def test_slot_plans_change_only_two_positions_and_support_submarines(self):
        occupied = {1: positions([True] * 3, [True] * 3), 4: positions([True] * 3, [True] * 3)}
        expected = slot_swap_plan(occupied, 1, 4, 4, 5)
        self.assertEqual(expected[1][4], '4:5')
        self.assertEqual(expected[4][5], '1:4')
        self.assertEqual(expected[1][5], '1:5')
        self.assertEqual(expected[4][4], '4:4')
        sub = slot_swap_plan({1: {1: True, 2: True, 3: True}, 2: {1: True, 2: True, 3: True}},
                             1, 3, 2, 1, 'submarine')
        self.assertEqual(sub[1][3], '2:1')
        self.assertEqual(sub[2][1], '1:3')
        with self.assertRaises(ValueError):
            validate_swap(1, 3, 4, 5)

    def test_empty_destination_is_append_only_and_source_positions_compact(self):
        occupied = {1: positions([True], [True, True, True]), 4: positions([True], [True])}
        expected = slot_swap_plan(occupied, 1, 4, 4, 5)
        self.assertEqual([expected[1][s] for s in (4, 5, 6)], ['1:5', '1:6', None])
        self.assertEqual(expected[4][5], '1:4')
        with self.assertRaises(ValueError):
            slot_swap_plan(occupied, 1, 4, 4, 6)

    def test_counter_image_response_works_without_reading_its_digits(self):
        before = np.zeros((720, 1280, 3), np.uint8)
        after = before.copy()
        after[665:682, 589:605] = 255
        self.assertTrue(selected_count_changed(before, after))
        self.assertFalse(selected_count_changed(before, before))
        after[662:686, 615:647] = 120
        self.assertFalse(selected_count_changed(before, after))


class VisualTargetTests(unittest.TestCase):
    def test_unknown_morale_retries_its_category_once_and_preserves_confirmed_values(self):
        image = frame('detail_surface')
        faces = detail_portraits(image)
        for value in (150, None):
            with self.subTest(second_read=value):
                tool = runner()
                result = {'main': {'1': [dict(slot=1, emotion=150)]}, 'submarine': {},
                          'vanguard': {'1': [dict(slot=4, name='已确认', emotion=150),
                                             dict(slot=5, name='花月', emotion=None)]}}
                positions = {slot: dict(slot=slot, name='', level=105, emotion=None,
                                       occupied=slot in (4, 5)) for slot in range(1, 7)}
                tool._scan_category = Mock(return_value={'1': [dict(name='', level=105, emotion=2),
                                                               dict(name='花月', level=105, emotion=value)]})
                tool._reference_portraits = {'1': [faces[4], faces[5]]}
                tool._scan_window = (20, 30)
                windows = {'vanguard': (10, 15)}
                scanner = object()
                tool._retry_unknown_morale(scanner, result, {}, {'surface': {1: positions}}, {},
                                           {'surface': {1: image}}, windows)
                self.assertEqual(result['vanguard']['1'][0]['emotion'], 150)
                self.assertEqual(result['vanguard']['1'][1]['emotion'], value)
                self.assertEqual(windows['vanguard'], (10, 30))
                tool.fleet_enter.assert_called_once_with(1, 'surface')
                tool._open_slot.assert_called_once_with(4, 'surface')
                tool._scan_category.assert_called_once_with(scanner, max_rows=3)
                tool.dock_reset.assert_not_called()
                tool._close_picker.assert_called_once()

    def test_game_morale_sort_selects_first_eligible_source_without_name_or_level_ocr(self):
        tool = runner()
        native = frame('vanguard_top')
        tool._capture_formation = Mock(return_value=(None, detail_portraits(frame('detail_surface')),
                                                     dict.fromkeys(range(1, 7), True)))

        def pages(scanner, **kwargs):
            tool.device.image = native
            yield scanner.scan(native), []

        tool._dock_pages = pages
        with (patch('module.runtime.fleet_formation.FleetNameScanner', side_effect=AssertionError('禁止舰名OCR')),
              patch('module.runtime.fleet_formation.LevelScanner', side_effect=AssertionError('禁止等级OCR'))):
            self.assertEqual(tool.highest_morale_slot(1, 4, 5), 5)
        tool._prepare_dock.assert_called_once_with(sort='mood')
        tool._open_slot.assert_called_once_with(5)

    def test_refresh_reuses_dock_names_by_portrait_and_updates_every_actual_slot(self):
        expected_names = ['拉斐尔', '瑞凤', '独角兽.改', '阿尔弗雷多·奥里亚尼', '花月', '文琴佐·焦贝蒂']
        layouts = {'main': [(0, 2, 1), (0, 6, 2), (0, 5, 3)],
                   'vanguard': [(1, 1, 4), (0, 6, 5), (1, 0, 6)]}
        pools, portraits = {}, {}
        scanner = VisualDockScanner()
        for category, slots in layouts.items():
            image = frame(f'{category}_top')
            cards = scanner.scan(image)
            rows = sorted({card.y for card in cards})
            pools[category], portraits[category] = [], []
            for row, col, slot in slots:
                card = next(card for card in cards if card.y == rows[row] and card.col == col)
                pools[category].append(dict(name=expected_names[slot - 1], level=125 if slot <= 3 else 105,
                                           emotion=2 if slot == 4 else 150, review=False))
                portraits[category].append(scanner.portrait(image, card))
        for first, retry in ((4, False), (1, False), (4, True)):
            with self.subTest(first_slot=first, retry=retry):
                tool = runner()
                tool.config.cross_get.return_value = '旧版未结构化参考记录'
                detail = frame('detail_surface')
                tool._capture_formation = Mock(return_value=(detail, detail_portraits(detail), {}))

                seen = {}

                def scan_category(scanner, **kwargs):
                    category = 'main' if tool._open_slot.call_args.args[0] == 1 else 'vanguard'
                    tool._reference_portraits = {'1': portraits[category]}
                    seen[category] = seen.get(category, 0) + 1
                    ships = [dict(ship) for ship in pools[category]]
                    if retry and category == 'vanguard' and seen[category] == 1:
                        ships[0]['emotion'] = None
                    return {'1': ships}

                tool._scan_category = scan_category
                positions = {slot: dict(name='详情误读', slot=slot, occupied=True,
                                       level=0, emotion=None, review=True) for slot in range(1, 7)}
                with (patch('module.retire.fleet_management.FormationDockScanner'),
                      patch('module.retire.fleet_management.FormationDetailScanner') as details):
                    details.return_value.scan.return_value = positions
                    readings = tool.read_fleet_morale(1, first_slot=first)
                self.assertEqual(readings, {1: 150, 2: 150, 3: 150, 4: 2, 5: 150, 6: 150})
                saved = tool._save_result.call_args.args[0]
                ships = saved['main']['1'] + saved['vanguard']['1']
                self.assertEqual([ship['name'] for ship in ships], expected_names)
                self.assertEqual([ship['slot'] for ship in ships], [1, 2, 3, 4, 5, 6])
                self.assertEqual([call.args[0] for call in tool._open_slot.call_args_list],
                                 [first, 5 - first] + ([4] if retry else []))
                tool._capture_formation.assert_called_once_with(1, navigate=False)
                import json
                json.dumps(saved, ensure_ascii=False)

    def test_native_cross_fleet_popup_is_confirmed_after_selection_submit(self):
        from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM
        from module.handler.info_handler import InfoHandler
        from module.retire.assets import DOCK_CHECK
        tool = runner()
        baseline = frame('vanguard_top')
        selected = baseline.copy()
        selected[665:682, 589:605] = 255
        index = -1

        def images(**kwargs):
            nonlocal index
            for image in (selected, frame('exchange_popup'), baseline):
                index += 1
                tool.device.image = image
                yield image

        tool.loop = images
        tool._formation_visible = lambda: index == 2
        tool.appear = lambda button, **kwargs: (index == 0 if button is DOCK_CHECK else
            button.match(tool.device.image, offset=kwargs.get('offset', (0, 0))))
        tool.handle_popup_confirm = InfoHandler.handle_popup_confirm.__get__(tool)
        self.assertTrue(POPUP_CANCEL.match(frame('exchange_popup'), offset=(3, 30)))
        with patch('module.retire.fleet_management.Timer') as timer:
            timer.return_value.reached.return_value = True
            FleetManagement._confirm_replacement(tool, baseline)
        self.assertEqual([call.args[0] for call in tool.device.click.call_args_list],
                         [PICKER_CONFIRM, POPUP_CONFIRM])

    def test_real_device_without_first_image_screenshots_before_any_appearance_check(self):
        from module.device.device import Device
        tool = runner()
        device = Device.__new__(Device)
        device.click = Mock()
        device.screenshot = Mock(side_effect=lambda: setattr(device, 'image', frame('closed_surface')))
        tool.device = device
        tool.ui_ensure = Mock()
        tool.appear = lambda *args, **kwargs: bool(device.image is None)
        tool._formation_visible = Mock(return_value=True)

        def images(**kwargs):
            for name in ('closed_surface', 'closed_surface', 'menu_surface', 'closed_surface'):
                device.image = frame(name)
                yield device.image

        tool.loop = images
        self.assertFalse(device.has_cached_image)
        with patch('module.retire.fleet_management.Timer') as timer:
            timer.return_value.reached.return_value = True
            FleetManagement.fleet_enter(tool, 3)
        device.screenshot.assert_called_once()
        self.assertTrue(device.has_cached_image)

    def test_each_native_detail_card_finds_its_dock_card_without_any_ocr(self):
        expected = {1: ('main_top', 2, 0), 2: ('main_top', 6, 0), 3: ('main_top', 5, 0),
                    4: ('vanguard_top', 1, 1), 5: ('vanguard_top', 6, 0), 6: ('vanguard_top', 0, 1)}
        portraits = detail_portraits(frame('detail_surface'))
        with (
            patch('module.runtime.fleet_formation.FleetNameScanner', side_effect=AssertionError('禁止舰名OCR')),
            patch('module.runtime.fleet_formation.LevelScanner', side_effect=AssertionError('禁止等级OCR')),
            patch('module.runtime.fleet_formation.FleetEmotionScanner', side_effect=AssertionError('禁止心情OCR')),
        ):
            scanner = VisualDockScanner()
            for slot, (name, column, row) in expected.items():
                image = frame(name)
                cards = scanner.scan(image)
                ys = sorted({card.y for card in cards})
                matcher = PortraitMatcher(portraits[slot])
                candidates = [(card, card.y, matcher.score(scanner.portrait(image, card))) for card in cards]
                picked, _ = choose_portrait(candidates, source_fleet=1)
                self.assertEqual((picked.col, picked.y), (column, ys[row]))
                self.assertGreaterEqual(max(item[2] for item in candidates), 30)

    def test_identical_portraits_use_badge_hint_and_unresolved_visual_twins_stop_before_click(self):
        cards = VisualDockScanner().scan(frame('vanguard_top'))
        one, two = cards[0], cards[1]
        one.fleet, two.fleet = 1, 2
        self.assertIs(choose_portrait([(one, 75, 50), (two, 75, 49)], 2)[0], two)
        one.fleet = two.fleet = -1
        with self.assertRaises(ValueError):
            choose_portrait([(one, 75, 50), (two, 75, 49)], 2)
        with self.assertRaises(ValueError):
            choose_portrait([(one, 75, 4)], 1)

    def test_slot_swap_uses_fresh_geometry_and_succeeds_when_all_ocr_constructors_are_broken(self):
        tool = runner()
        portraits = detail_portraits(frame('detail_surface'))
        occupied = dict.fromkeys(range(1, 7), True)
        source = (None, portraits, occupied)
        target_portraits = {slot: np.flipud(image).copy() for slot, image in portraits.items()}
        target = (None, target_portraits, occupied)
        expected = slot_swap_plan({1: occupied, 4: occupied}, 1, 4, 4, 5)
        originals = {f'{number}:{slot}': image for number, capture in ((1, source), (4, target))
                     for slot, image in capture[1].items()}
        after = {number: (None, {slot: originals[token] for slot, token in values.items()}, occupied)
                 for number, values in expected.items()}
        tool._capture_formation = Mock(side_effect=[source, target, after[1], after[4], after[1], after[4]])
        calls = 0

        def pages(scanner, **kwargs):
            nonlocal calls
            calls += 1
            image = frame('vanguard_top' if calls == 1 else 'vanguard_mid')
            tool.device.image = image
            tool._dock_offset = 0 if calls == 1 else 119
            cards = scanner.scan(image)
            yield cards, [(card, card.y + tool._dock_offset) for card in cards]

        tool._dock_pages = pages
        tool._save_swap_reference = Mock()
        tool._save_swap_reference.side_effect = lambda *args: setattr(tool.device, 'image', frame('scan_surface'))
        tool.device.stuck_record_add = Mock()
        tool.appear = ModuleBase.appear.__get__(tool)
        tool._commit_formation = Mock(wraps=FleetManagement._commit_formation.__get__(tool))
        tool.is_in_main = Mock(return_value=True)
        tool.run = Mock(side_effect=GameStuckError('模拟交换后参考刷新未完成'))
        with patch('module.runtime.fleet_formation.FleetNameScanner', side_effect=AssertionError('舰名不可用')), \
                patch('module.runtime.fleet_formation.LevelScanner', side_effect=AssertionError('等级不可用')), \
                patch('module.runtime.fleet_formation.FleetEmotionScanner', side_effect=AssertionError('心情不可用')):
            result = tool.swap_slots(1, 4, 4, 5, update_emotion=True)
        self.assertTrue(result['changed'])
        self.assertFalse(result['reference_updated'])
        clicked = tool.device.click.call_args.args[0]
        self.assertEqual(clicked.button[1], 223)
        tool._open_slot.assert_called_once_with(5, 'surface')
        tool._confirm_replacement.assert_called_once()
        tool._commit_formation.assert_called_once()
        tool.is_in_main.assert_called_once()
        tool._save_swap_reference.assert_called_once_with(expected, 'surface')
        tool.dock_reset.assert_not_called()
        tool._close_picker.assert_not_called()
        self.assertTrue(tool.dock_filter.reset_first)

    def test_reference_move_preserves_unrelated_fleets_and_does_not_guess_names(self):
        tool = runner()
        stored = {'vanguard': {'1': [{'name': '源参考', 'level': 105, 'slot': 4, 'emotion': None}],
                               '4': [{'name': '目标参考', 'level': 99, 'slot': 5, 'emotion': 0}],
                               '6': [{'name': '无关', 'slot': 4}]}}
        tool.config.cross_get.return_value = stored
        expected = {1: {1: None, 2: None, 3: None, 4: '4:5', 5: None, 6: None},
                    4: {1: None, 2: None, 3: None, 4: None, 5: '1:4', 6: None}}
        tool._save_swap_reference(expected, 'surface')
        saved = tool._save_result.call_args.args[0]
        self.assertEqual(saved['vanguard']['1'][0]['name'], '目标参考')
        self.assertEqual(saved['vanguard']['4'][0]['name'], '源参考')
        self.assertEqual(saved['vanguard']['6'], stored['vanguard']['6'])
        self.assertEqual(stored['vanguard']['1'][0]['name'], '源参考')

    def test_uncertain_click_invalidates_only_affected_records_even_if_cleanup_fails(self):
        tool = runner()
        portraits = detail_portraits(frame('detail_surface'))
        occupied = dict.fromkeys(range(1, 7), True)
        tool._capture_formation = Mock(return_value=(None, portraits, occupied))
        tool.config.cross_get.return_value = {'vanguard': {'1': [], '4': [], '6': [{'name': '保留'}]}}
        scanner = VisualDockScanner()
        cards = scanner.scan(tool.device.image)
        source = next(card for card in cards if card.col == 1 and card.y > 200)
        tool._visual_candidates = Mock(return_value=[(source, source.y, 50)])
        tool._dock_pages = Mock(return_value=iter([(cards, [])]))
        tool._dock_offset = 0
        tool._confirm_replacement.side_effect = GameStuckError('模拟点击后画面卡住')
        tool.appear.return_value = True
        tool.dock_reset.side_effect = GameTooManyClickError('模拟清理失败')
        with self.assertRaises(FleetManagementError):
            tool.swap_slots(1, 4, 4, 5)
        tool.device.click.assert_called_once()
        saved = tool._save_result.call_args.args[0]
        self.assertEqual(saved['vanguard'], {'6': [{'name': '保留'}]})
        self.assertTrue(tool.dock_filter.reset_first)

    def test_confirmation_never_uses_digit_ocr_or_submits_an_unchanged_counter(self):
        tool = runner()
        tool.loop = Mock(return_value=iter([None, None, None]))
        tool._formation_visible = Mock(return_value=False)
        tool.appear = Mock(return_value=True)
        tool.handle_popup_confirm = Mock(return_value=False)
        with patch('module.retire.dock.OCR_DOCK_SELECTED.ocr', side_effect=AssertionError('禁止数字OCR')):
            with self.assertRaises(FleetManagementError):
                FleetManagement._confirm_replacement(tool, tool.device.image.copy())
        self.assertNotIn(PICKER_CONFIRM, [call.args[0] for call in tool.device.click.call_args_list])

    def test_navigation_menu_does_not_need_ocr_or_current_fleet_number(self):
        tool = runner()
        tool.ui_ensure = Mock()
        tool._formation_visible = Mock(return_value=True)

        def images(**kwargs):
            for name in ('closed_surface', 'closed_surface', 'menu_surface', 'closed_surface'):
                tool.device.image = frame(name)
                yield tool.device.image

        tool.loop = images
        with patch('module.retire.fleet_management.Timer') as timer:
            timer.return_value.reached.return_value = True
            FleetManagement.fleet_enter(tool, 3)
        self.assertEqual(tool.device.click.call_count, 2)

    def test_native_scroll_geometry_covers_three_rows_without_reading_names(self):
        tool = runner()
        stage = 0

        def images(**kwargs):
            for _ in range(20):
                tool.device.image = frame('vanguard_top' if stage == 0 else 'vanguard_bottom')
                yield tool.device.image

        def drag(*args):
            nonlocal stage
            stage = 1

        from module.retire.assets import DOCK_CHECK
        tool.appear = lambda button, **kwargs: button is DOCK_CHECK
        tool.loop = images
        with patch('module.retire.dock_scan.DockScan._drag_rows', side_effect=drag) as move:
            pages = list(tool._dock_pages(VisualDockScanner(), max_rows=3))
        self.assertEqual(len(pages), 2)
        self.assertEqual(tool._dock_offset, 231)
        self.assertEqual(len(pages[-1][1]), 21)
        move.assert_called_once()
        tool.device.swipe.assert_called_once()

    def test_direct_menu_and_arrow_navigation_keep_positive_confirmation(self):
        for method in ('menu', 'arrows'):
            with self.subTest(method=method):
                tool = runner()
                tool._formation_visible = Mock(return_value=True)
                sequence = ['closed_surface', 'closed_surface', 'menu_surface', 'closed_surface']
                if method == 'arrows':
                    sequence.append('closed_surface')
                sequence += ['menu_surface4', 'closed_surface']

                def images(**kwargs):
                    for name in sequence:
                        tool.device.image = frame(name)
                        yield tool.device.image

                tool.loop = images
                with patch('module.retire.fleet_management.Timer') as timer:
                    timer.return_value.reached.return_value = True
                    FleetManagement.fleet_enter(tool, 4, method=method)
                if method == 'arrows':
                    from module.equipment.assets import FLEET_NEXT
                    self.assertIn(FLEET_NEXT, [call.args[0] for call in tool.device.click.call_args_list])
                else:
                    self.assertIn(menu_area(4), [call.args[0].button for call in tool.device.click.call_args_list])
                    self.assertEqual(2, tool.device.click.call_count)


class SingleMenuSelectionTests(unittest.TestCase):
    @staticmethod
    def closed(fleet, kind='surface'):
        image = frame(f'closed_{kind}')
        row = fleet - 1 if kind == 'surface' else fleet + 5
        left = 298 if kind == 'surface' else 664
        image[647:707, left:left + 50] = frame('fleet_index_regions')[row * 60:(row + 1) * 60, :50]
        return image

    def navigate(self, images, fleet, kind='surface'):
        tool = runner()
        tool._formation_visible = Mock(return_value=True)
        def frames(**kwargs):
            for image in images:
                tool.device.image = image
                yield image
        tool.loop = frames
        with patch('module.retire.fleet_management.Timer') as timer:
            timer.return_value.reached.return_value = True
            FleetManagement.fleet_enter(tool, fleet, kind)
        return tool

    def test_reported_menu_selects_third_fleet_once_without_reopening_it(self):
        menu = frame('menu_surface5_native')
        unknown = self.closed(5)
        unknown[647:707, 298:348] = 0
        tool = self.navigate([menu, menu, self.closed(5), unknown, self.closed(3)], 3)
        self.assertEqual(['第3舰队'], [call.args[0].name for call in tool.device.click.call_args_list])

    def test_submarine_menu_also_returns_after_one_target_click(self):
        menu = frame('menu_submarine')
        tool = self.navigate([menu, menu, self.closed(1, 'submarine')], 1, 'submarine')
        self.assertEqual(['第1舰队'], [call.args[0].name for call in tool.device.click.call_args_list])

    def test_single_target_click_waits_for_animation_without_more_input(self):
        tool = runner()
        tool._formation_visible = Mock(return_value=True)
        state = SimpleNamespace(clock=100., selected_at=None)
        menu, closed = frame('menu_surface5_native'), self.closed(3)
        def frames(**kwargs):
            for _ in range(20):
                state.clock += .1
                tool.device.image = menu if state.selected_at is None else closed
                yield None
        def click(button):
            self.assertEqual('第3舰队', button.name)
            state.selected_at = state.clock
        tool.loop = frames
        tool.device.click.side_effect = click
        with patch('module.base.timer.time', side_effect=lambda: state.clock):
            FleetManagement.fleet_enter(tool, 3)
        tool.device.click.assert_called_once()
        self.assertGreaterEqual(state.clock - state.selected_at, .5)

    def test_unknown_result_does_not_reopen_the_menu_or_claim_the_switch_succeeded(self):
        menu = frame('menu_surface5_native')
        tool = runner()
        tool._formation_visible = Mock(return_value=True)
        def frames(**kwargs):
            for image in (menu, menu, self.closed(5), self.closed(5)):
                tool.device.image = image
                yield image
        tool.loop = frames
        with patch('module.retire.fleet_management.Timer') as timer:
            timer.return_value.reached.return_value = True
            with self.assertRaises(FleetManagementError):
                FleetManagement.fleet_enter(tool, 3)
        self.assertEqual(['第3舰队'], [call.args[0].name for call in tool.device.click.call_args_list])


class DirectRotationTests(unittest.TestCase):
    def test_fixed_slot_portrait_skips_another_source_ship_on_the_earlier_page(self):
        scanner = VisualDockScanner()
        native = frame('slot4_dock')
        cards = scanner.scan(native)
        rows = sorted({card.y for card in cards})
        aylwin = next(card for card in cards if card.col == 1 and card.y == rows[0])
        snake = next(card for card in cards if card.col == 1 and card.y == rows[1])
        mercury = next(card for card in cards if card.col == 2 and card.y == rows[1])
        # 错误截图中艾尔温已在1队；仅在虚拟页面还原交换前的3队徽标。
        native[aylwin.y + 117:aylwin.y + 162, aylwin.x:aylwin.x + 35] = (
            native[mercury.y + 117:mercury.y + 162, mercury.x:mercury.x + 35])
        earlier = native.copy()
        earlier[rows[1]:rows[1] + 207, 85:570] = native[rows[0]:rows[0] + 207, 85:570]
        # 与日志一样，艾尔温先出现在完整第二行，水星号还需要翻页。
        earlier[rows[0] + 117:rows[0] + 162, aylwin.x:aylwin.x + 35] = 0
        entries = [('水星号', 4, 88, mercury), ('长蛇号', 5, 98, snake), ('艾尔温', 6, 99, aylwin)]
        source = [dict(name=name, slot=slot, level=level, emotion=150) for name, slot, level, _ in entries]
        pictures = [scanner.portrait(native, card).copy() for *_, card in entries]
        detail = detail_portraits(frame('slot4_detail'))

        class SelectionSubmitted(Exception):
            pass

        for cached, available in ((False, True), (True, True), (True, False)):
            with self.subTest(cached=cached, source_visible=available):
                tool = runner()
                tool._rotation_fleet = 1
                tool._rotation_picker = (1, 4)
                if cached:
                    tool._rotation_scanned_slot = (1, 4)
                tool._rotation_result = {'vanguard': {'1': [dict(name='热心.改', slot=4, level=105, emotion=150)],
                                                       '3': deepcopy(source)}}
                # 候补按等级降序排列，与固定舰位顺序相反。
                tool._rotation_pool = {'vanguard': ({'3': list(reversed(source))},
                                                     {'3': list(reversed(pictures))})}
                tool._slot_portraits = {(3, slot): detail[slot] for slot in (4, 5, 6)}
                tool.device.image = earlier
                pages = []

                def dock_pages(scan, **kwargs):
                    for image in (earlier, native) if available else (earlier,):
                        tool.device.image = image
                        pages.append(image)
                        yield scan.scan(image), []

                tool._dock_pages = dock_pages
                tool._confirm_replacement.side_effect = SelectionSubmitted
                with (patch('module.runtime.fleet_formation.FleetNameScanner', side_effect=AssertionError('禁止舰名OCR')),
                      patch('module.runtime.fleet_formation.LevelScanner', side_effect=AssertionError('禁止等级OCR'))):
                    if available:
                        with self.assertRaises(SelectionSubmitted):
                            tool.rotate_slot(3, 4, 1)
                        self.assertEqual(len(pages), 2)
                        button = tool.device.click.call_args.args[0]
                        self.assertEqual(button.button, (mercury.x + 20, mercury.y + 40,
                                                         mercury.x + 115, mercury.y + 145))
                        tool._confirm_replacement.assert_called_once()
                    else:
                        with self.assertRaisesRegex(FleetManagementError, '未能确认来源舰位卡面'):
                            tool.rotate_slot(3, 4, 1)
                        tool.device.click.assert_not_called()
                        tool._confirm_replacement.assert_not_called()
                tool._save_result.assert_not_called()

    def test_local_check_starts_from_selected_slot_and_preserves_other_fleet_morale(self):
        tool = self.direct_tool()
        tool._rotation_result['main']['1'][0]['emotion'] = 70
        readings = tool.prepare_rotation(6, slots=[1, 4], fleets={6})
        self.assertEqual([call.args[0] for call in tool._open_slot.call_args_list], [1, 4])
        self.assertEqual(70, readings[1][1])
        self.assertEqual({1: 12, 4: 12}, readings[6])

    def test_verified_candidate_pool_is_reused_when_opening_the_actual_swap_slot(self):
        tool = self.direct_tool()
        tool.prepare_rotation(6)
        tool.finish_rotation()
        tool._scan_category.reset_mock()
        tool._open_slot.reset_mock()
        tool.prepare_rotation(6, slots=[4], scan=False)
        tool._open_slot.assert_called_once_with(4)
        tool._scan_category.assert_not_called()
        readings = tool.rotate_slot(1, 4, 6)
        self.assertEqual(150, readings[6][4])
        self.assertEqual(1, tool._scan_category.call_count)

    def direct_tool(self):
        tool = runner()
        tool.device.image = frame('swap_surface6')
        tool.device.stuck_record_add = Mock()
        tool.appear = ModuleBase.appear.__get__(tool)
        pictures = {category: frame(f'direct_{category}') for category in ('main', 'vanguard')}
        layout = {'main': [('拉斐尔', 1, 1, 0, 3, 125, 150), ('突击者', 6, 1, 1, 1, 100, 12)],
                  'vanguard': [('杜威', 1, 4, 1, 5, 100, 150), ('Z20', 6, 4, 1, 6, 100, 12)]}
        owners, references, records = {}, {}, {'main': {}, 'vanguard': {}}
        scanner = VisualDockScanner()
        for category, entries in layout.items():
            cards = scanner.scan(pictures[category])
            rows = sorted({card.y for card in cards})
            for name, fleet, slot, row, column, level, morale in entries:
                card = next(card for card in cards if card.y == rows[row] and card.col == column)
                owners[name] = fleet
                ship = dict(name=name, slot=slot, level=level, emotion=morale, occupied=True)
                records[category].setdefault(str(fleet), []).append(ship)
                references[name] = (ship, scanner.portrait(pictures[category], card))
        tool._rotation_result = deepcopy(records)
        tool.config.cross_get.return_value = records
        state = SimpleNamespace(slot=None)

        def open_slot(slot, *args):
            state.slot = slot
            tool.device.image = pictures['main' if slot <= 3 else 'vanguard'].copy()

        def scan_category(scanner, **kwargs):
            category = 'main' if state.slot <= 3 else 'vanguard'
            pool, portraits = {}, {}
            for name, *_ in layout[category]:
                ship, face = references[name]
                fleet = str(owners[name])
                pool.setdefault(fleet, []).append(dict(ship))
                portraits.setdefault(fleet, []).append(face)
            tool._reference_portraits = portraits
            return pool

        def confirm(*args):
            names = [entry[0] for entry in layout['main' if state.slot <= 3 else 'vanguard']]
            owners[names[0]], owners[names[1]] = owners[names[1]], owners[names[0]]
            tool.device.image = frame('swap_surface6')

        def pages(scanner, **kwargs):
            yield scanner.scan(tool.device.image), []

        tool._open_slot.side_effect = open_slot
        tool._close_picker.side_effect = lambda: setattr(tool.device, 'image', frame('swap_surface6'))
        tool._scan_category = Mock(side_effect=scan_category)
        tool._save_result.side_effect = lambda value: setattr(tool, '_rotation_result', deepcopy(value))
        tool._confirm_replacement.side_effect = confirm
        tool._dock_pages = Mock(side_effect=pages)
        tool._capture_formation = Mock(side_effect=AssertionError('智能换船不重复采集详情'))
        return tool

    def test_fleet_six_scans_four_then_one_and_swaps_one_then_four_without_source_navigation(self):
        tool = self.direct_tool()
        readings = tool.prepare_rotation(6)
        self.assertEqual(readings[6], {1: 12, 4: 12})
        self.assertEqual(tool._rotation_picker, (6, 1))
        first = tool.rotate_slot(1, 1, 6)
        self.assertEqual(first[6], {1: 150, 4: 12})
        final = tool.rotate_slot(1, 4, 6)
        tool.finish_rotation()
        self.assertEqual(final[6], {1: 150, 4: 150})
        self.assertEqual(final[1], {1: 12, 4: 12})
        self.assertEqual([call.args[0] for call in tool._open_slot.call_args_list], [4, 1, 1, 4, 4])
        self.assertEqual(tool._scan_category.call_count, 4)
        self.assertEqual(tool._dock_pages.call_count, 1)
        self.assertEqual([call.args[0].name for call in tool.device.click.call_args_list], ['源舰位卡面'] * 2)
        tool._prepare_dock.assert_called_once()
        tool.dock_reset.assert_not_called()
        tool.fleet_enter.assert_not_called()
        tool._capture_formation.assert_not_called()
        tool._commit_formation.assert_not_called()
        self.assertIsNone(tool._rotation_picker)

    def test_duplicate_source_faces_stop_before_click_and_leave_recovery_to_rescan(self):
        tool = self.direct_tool()
        tool.prepare_rotation(6)
        dock, pictures = tool._rotation_pool['main']
        dock['1'].append(dict(dock['1'][0]))
        pictures['1'].append(pictures['1'][0].copy())
        with self.assertRaisesRegex(FleetManagementError, '唯一候选'):
            tool.rotate_slot(1, 1, 6)
        tool.device.click.assert_not_called()

    def test_empty_destination_keeps_the_existing_append_and_compaction_validation(self):
        tool = self.direct_tool()
        tool.prepare_rotation(6)
        tool._rotation_result['main']['6'] = []

        class ExistingValidation(Exception):
            pass

        tool.swap_slots = Mock(side_effect=ExistingValidation)
        with self.assertRaises(ExistingValidation):
            tool.rotate_slot(1, 1, 6)
        tool.swap_slots.assert_called_once_with(1, 1, 6, 1)
        tool.device.click.assert_not_called()

    def test_unknown_morale_retries_once_without_resetting_sort(self):
        tool = self.direct_tool()
        original = tool._scan_category.side_effect
        calls = []

        def scan(scanner, **kwargs):
            result = original(scanner, **kwargs)
            calls.append(tool._rotation_picker[1])
            if calls == [4]:
                result['6'][0]['emotion'] = None
            return result

        tool._scan_category.side_effect = scan
        readings = tool.prepare_rotation(6)
        self.assertEqual(readings[6], {1: 12, 4: 12})
        self.assertEqual(calls, [4, 4, 1])
        tool._prepare_dock.assert_called_once()
        tool.dock_reset.assert_not_called()


class CommitFormationTests(unittest.TestCase):
    def commit_tool(self, theme=page_main, current='fleet'):
        tool = runner()
        tool.config.SERVER = 'cn'
        state = SimpleNamespace(page=current, pending=None, clock=100.)

        def screenshot():
            state.clock += .5
            if state.pending is not None:
                if state.pending:
                    state.pending -= 1
                else:
                    state.page, state.pending = 'main', None

        def appear(button, **kwargs):
            if state.page == 'fleet':
                return button is FLEET_CHECK or button is FLEET_DETAIL
            return state.page == 'main' and button is theme.check_button

        def click(button):
            self.assertIs(button, BACK_ARROW)
            self.assertIsNone(state.pending, '返回主界面的动画期间不应连续点击')
            state.pending = 2

        tool.device.screenshot = Mock(side_effect=screenshot)
        tool.device.click = Mock(side_effect=click)
        tool.appear = appear
        tool.handle_popup_confirm = Mock(side_effect=AssertionError('不得自动确认意外编队弹窗'))
        return tool, state

    def test_real_main_page_detector_commits_both_themes_after_a_fresh_screenshot(self):
        for theme in (page_main, page_main_white):
            with self.subTest(theme=str(theme)):
                tool, state = self.commit_tool(theme)
                with patch('module.base.timer.time', side_effect=lambda: state.clock):
                    FleetManagement._commit_formation(tool)
                tool.device.click.assert_called_once_with(BACK_ARROW)
                self.assertGreater(tool.device.screenshot.call_count, 1)
                self.assertEqual(state.page, 'main')
                tool.handle_popup_confirm.assert_not_called()

    def test_already_in_main_confirms_without_clicking_back(self):
        tool, state = self.commit_tool(current='main')
        with patch('module.base.timer.time', side_effect=lambda: state.clock):
            FleetManagement._commit_formation(tool)
        tool.device.screenshot.assert_called_once()
        tool.device.click.assert_not_called()

    def test_unexpected_popup_remains_unconfirmed_and_stops_with_management_error(self):
        tool, state = self.commit_tool(current='popup')
        with patch('module.base.timer.time', side_effect=lambda: state.clock):
            with self.assertRaisesRegex(FleetManagementError, '尚未确认游戏已提交编队'):
                FleetManagement._commit_formation(tool)
        tool.device.click.assert_not_called()
        tool.handle_popup_confirm.assert_not_called()


class ScanNavigationTests(unittest.TestCase):
    @staticmethod
    def native_runner():
        tool = runner()
        tool.device.image = frame('scan_surface')
        tool.device.stuck_record_add = Mock()
        tool.appear = ModuleBase.appear.__get__(tool)
        for name in ('_open_slot', '_close_picker', '_enter_scan_submarine'):
            setattr(tool, name, getattr(FleetManagement, name).__get__(tool))

        def images(**kwargs):
            for index in range(12):
                if index or not kwargs.get('skip_first', True):
                    tool.device.screenshot()
                yield tool.device.image

        tool.loop = images
        return tool

    def test_native_formation_titles_match_dock_color_but_not_dock_template(self):
        tool = self.native_runner()
        for name in ('scan_surface', 'scan_surface_menu', 'scan_submarine'):
            with self.subTest(frame=name):
                tool.device.image = frame(name)
                self.assertTrue(tool.appear(DOCK_CHECK))
                self.assertFalse(tool.appear(DOCK_CHECK, offset=(20, 20)))
        tool.device.image = frame('scan_dock')
        self.assertTrue(tool.appear(DOCK_CHECK, offset=(20, 20)))

    def test_general_navigation_opens_selector_from_the_reported_stuck_frame(self):
        tool = self.native_runner()
        tool.device.image = frame('swap_surface6')

        class MenuOpened(Exception):
            pass

        def click(button):
            self.assertEqual(button.name, 'surface舰队选择')
            raise MenuOpened

        tool.device.click.side_effect = click
        with patch('module.retire.fleet_management.Timer') as timer:
            timer.return_value.reached.return_value = True
            with self.assertRaises(MenuOpened):
                FleetManagement.fleet_enter(tool, 3)
        tool.device.click.assert_called_once()

    def test_dock_card_colors_do_not_end_scrolling_as_an_empty_dock(self):
        tool = self.native_runner()
        bottom = frame('vanguard_bottom')
        x1, y1, x2, y2 = DOCK_EMPTY.area
        # 模拟卡面颜色恰好接近“空船坞”提示，字形仍不相同。
        bottom[y1:y2, x1:x2] = DOCK_EMPTY.color
        tool.device.image = bottom
        self.assertTrue(tool.appear(DOCK_EMPTY))
        self.assertFalse(tool.appear(DOCK_EMPTY, offset=(20, 20)))
        appear = tool.appear
        # 卡片夹具遮除了标题；保留真实的空船坞提示识别。
        tool.appear = lambda button, **kwargs: button is DOCK_CHECK or appear(button, **kwargs)
        stage = 0

        def images(**kwargs):
            for _ in range(20):
                tool.device.image = frame('vanguard_top') if stage == 0 else bottom
                yield tool.device.image

        def drag(*args):
            nonlocal stage
            stage = 1

        tool.loop = images
        with patch('module.retire.dock_scan.DockScan._drag_rows', side_effect=drag):
            pages = list(tool._dock_pages(VisualDockScanner()))
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(pages[-1][1]), 21)

    def test_scan_clicks_slots_four_one_then_submarine_once_and_its_slot_one(self):
        from module.device.device import Device

        tool = self.native_runner()
        # 使用尚无首帧的真实 Device 类型，只替换截图和点击，不连接模拟器。
        device = Device.__new__(Device)
        device.stuck_record_add = Mock()
        tool.device = device
        images = {name: frame(name) for name in ('scan_surface', 'scan_submarine', 'scan_dock')}
        current, pending, return_to, delay = 'scan_surface', None, None, 0
        clicks = []

        def screenshot():
            nonlocal current, pending, delay
            if delay:
                delay -= 1
            elif pending:
                current, pending = pending, None
            device.image = images[current]

        def click(button):
            nonlocal pending, return_to, delay
            clicks.append(button.name)
            if button.name in ('surface舰位4', 'surface舰位1', 'submarine舰位1'):
                expected = 'scan_submarine' if button.name.startswith('submarine') else 'scan_surface'
                self.assertEqual(current, expected)
                return_to, pending = current, 'scan_dock'
            elif button is BACK_ARROW:
                self.assertEqual(current, 'scan_dock')
                pending = return_to
            elif button.name == 'submarine舰队选择':
                self.assertEqual(current, 'scan_surface')
                pending, delay = 'scan_submarine', 3
            else:
                self.fail(f'扫描入口出现了多余点击：{button.name}')

        device.screenshot = Mock(side_effect=screenshot)
        device.click = Mock(side_effect=click)
        tool._prepare_dock.side_effect = lambda: self.assertTrue(tool.appear(DOCK_CHECK, offset=(20, 20)))
        tool._scan_category = Mock(return_value={})
        tool._capture_formation = Mock(side_effect=lambda number, kind, **kwargs: (frame(f'detail_{kind}'), {}, {}))
        self.assertFalse(device.has_cached_image)
        with (patch('module.retire.fleet_management.Timer') as timer,
              patch('module.retire.fleet_management.FormationDockScanner'),
              patch('module.retire.fleet_management.FormationDetailScanner') as details):
            timer.return_value.reached.return_value = True
            details.return_value.scan.side_effect = lambda image, kind: {
                slot: dict(name='', level=0, emotion=None, slot=slot, occupied=False)
                for slot in range(1, 7 if kind == 'surface' else 4)}
            tool.run(update_emotion=False)

        self.assertEqual(clicks, ['surface舰位4', 'BACK_ARROW', 'surface舰位1', 'BACK_ARROW',
                                 'submarine舰队选择', 'submarine舰位1', 'BACK_ARROW'])
        tool.ui_ensure.assert_called_once_with(page_fleet)
        tool.fleet_enter.assert_not_called()
        self.assertEqual(tool._scan_category.call_count, 3)
        self.assertEqual(tool._capture_formation.call_count, 8)
        tool.dock_reset.assert_not_called()
        tool._prepare_dock.assert_called_once()
        tool._save_result.assert_called_once()
        self.assertTrue(tool.dock_filter.reset_first)

    def test_failed_slot_entry_does_not_start_dock_cleanup_or_save(self):
        tool = self.native_runner()
        with (patch('module.retire.fleet_management.Timer') as timer,
              patch('module.retire.fleet_management.FormationDockScanner'),
              patch('module.retire.fleet_management.FormationDetailScanner')):
            timer.return_value.reached.return_value = True
            with self.assertRaisesRegex(FleetManagementError, '未能从指定舰位进入选船页'):
                tool.run(update_emotion=False)
        tool._prepare_dock.assert_not_called()
        tool.dock_reset.assert_not_called()
        tool._save_result.assert_not_called()
        self.assertTrue(tool.dock_filter.reset_first)

    def test_submarine_transition_does_not_reopen_selector_when_switch_fails(self):
        tool = self.native_runner()
        with self.assertRaisesRegex(FleetManagementError, '未能从水面编队进入潜艇编队'):
            tool._enter_scan_submarine()
        tool.device.click.assert_called_once()
        self.assertEqual(tool.device.click.call_args.args[0].button, (500, 650, 710, 702))


class DetailNavigationTests(unittest.TestCase):
    def native_tool(self, kind='surface', fleet=1, detail=False):
        tool = runner()
        tool.appear = ModuleBase.appear.__get__(tool)
        tool._scan_fleet_enter = FleetManagement._scan_fleet_enter.__get__(tool)
        tool.device.stuck_record_add = Mock()
        regions, controls = frame('fleet_index_regions'), frame('detail_controls')
        formations = {kind: frame(f'scan_{kind}') for kind in ('surface', 'submarine')}
        details = {kind: frame(f'detail_{kind}') for kind in ('surface', 'submarine')}
        state = SimpleNamespace(kind=kind, fleet=fleet, detail=detail, pending=None,
                                delay=0, clock=100., events=[], event_times=[], step=.25, animation_frames=2)

        def image():
            result = formations[state.kind].copy()
            row = state.fleet - 1 if state.kind == 'surface' else state.fleet + 5
            left = 298 if state.kind == 'surface' else 664
            result[647:707, left:left + 50] = regions[row * 60:(row + 1) * 60, :50]
            if state.detail:
                current = details[state.kind].copy()
                current[640:] = controls[640:]
                current[640:, :720] = result[640:, :720]
                return current
            return result

        def screenshot():
            self.assertLess(tool.device.screenshot.call_count, 250, '页面切换没有推进')
            state.clock += state.step
            if state.delay:
                state.delay -= 1
            elif state.pending:
                state.kind, state.fleet, state.detail = state.pending
                state.pending = None
            tool.device.image = image()

        def click(button):
            self.assertIsNone(state.pending, '动画期间重复点击了切换按钮')
            state.events.append((button.name, state.kind, state.fleet))
            state.event_times.append((button.name, state.clock))
            if button is FLEET_DETAIL and not state.detail:
                state.pending = state.kind, state.fleet, True
            elif button is BACK_ARROW and state.detail:
                state.pending = state.kind, state.fleet, False
            elif button in (FLEET_NEXT, FLEET_PREV) and not state.detail:
                target = state.fleet + (1 if button is FLEET_NEXT else -1)
                self.assertIn(target, range(1, 7 if state.kind == 'surface' else 3))
                state.pending = state.kind, target, False
            elif button.name in ('surface舰队选择', 'submarine舰队选择') and not state.detail:
                target = button.name.split('舰队')[0]
                self.assertNotEqual(state.kind, target, '详情扫描不应展开当前类型的舰队下拉列表')
                state.pending = target, 1, False
            else:
                self.fail(f'页面切换使用了错误按钮：{button.name}')
            state.delay = state.animation_frames

        tool.device.image = image()
        tool.device.screenshot = Mock(side_effect=screenshot)
        tool.device.click = Mock(side_effect=click)
        return tool, state, image

    def test_bottom_numbers_read_all_surface_and_submarine_fleets_without_ocr(self):
        for kind, count in (('surface', 6), ('submarine', 2)):
            tool, state, image = self.native_tool(kind)
            for fleet in range(1, count + 1):
                with self.subTest(kind=kind, fleet=fleet):
                    state.fleet = fleet
                    self.assertEqual(bottom_fleet_index(image(), kind), fleet)
            blank = np.zeros_like(tool.device.image)
            self.assertIsNone(bottom_fleet_index(blank, kind))

    def test_fast_fleet_number_update_still_waits_half_a_second_before_detail(self):
        for kind in ('surface', 'submarine'):
            with self.subTest(kind=kind):
                tool, state, _ = self.native_tool(kind)
                state.step, state.animation_frames = .05, 0
                with patch('module.base.timer.time', side_effect=lambda: state.clock):
                    tool._scan_fleet_enter(2, kind)
                    tool._capture_formation(2, kind, navigate=False)
                times = dict(state.event_times)
                self.assertGreaterEqual(times['FLEET_DETAIL'] - times['FLEET_NEXT'], .5)
                self.assertEqual([(name, fleet) for name, _, fleet in state.events],
                                 [('FLEET_NEXT', 1), ('FLEET_DETAIL', 2), ('BACK_ARROW', 2)])

    def test_capture_uses_back_and_keeps_native_fixed_portraits(self):
        for kind in ('surface', 'submarine'):
            with self.subTest(kind=kind):
                tool, state, image = self.native_tool(kind)
                with patch('module.base.timer.time', side_effect=lambda: state.clock):
                    captured, portraits, occupied = tool._capture_formation(1, kind)
                self.assertEqual([event[0] for event in state.events], ['FLEET_DETAIL', 'BACK_ARROW'])
                self.assertFalse(state.detail)
                self.assertTrue(tool._formation_visible())
                self.assertTrue(FLEET_DETAIL_CHECK.appear_on(captured))
                expected = detail_portraits(frame(f'detail_{kind}'), kind)
                self.assertEqual(set(portraits), set(expected))
                for slot, portrait in portraits.items():
                    np.testing.assert_array_equal(portrait, expected[slot])
                self.assertTrue(all(occupied.values()))
                tool.fleet_enter.assert_called_once_with(1, kind)

    def test_interrupted_detail_returns_before_handing_back_to_general_navigation(self):
        tool, state, image = self.native_tool(detail=True)
        # 只验证恢复到编队视图这一步，通用下拉导航已由既有测试单独覆盖。
        class NavigationReady(Exception):
            pass

        tool.ui_ensure.side_effect = NavigationReady
        with patch('module.base.timer.time', side_effect=lambda: state.clock):
            with self.assertRaises(NavigationReady):
                FleetManagement.fleet_enter(tool, 1)
        self.assertEqual([event[0] for event in state.events], ['BACK_ARROW'])
        self.assertFalse(state.detail)
        self.assertTrue(tool._formation_visible())
        tool.ui_ensure.assert_called_once_with(page_fleet)

    def test_scan_captures_eight_fleets_with_right_arrows_and_no_dropdown(self):
        tool, state, image = self.native_tool('submarine')
        tool._scan_category = Mock(return_value={})
        with (patch('module.base.timer.time', side_effect=lambda: state.clock),
              patch('module.retire.fleet_management.FormationDockScanner'),
              patch('module.retire.fleet_management.FormationDetailScanner') as scanner):
            scanner.return_value.scan.side_effect = lambda pixels, kind: {
                slot: dict(name='', level=0, emotion=None, slot=slot, occupied=True, review=True)
                for slot in range(1, 7 if kind == 'surface' else 4)}
            tool.run(update_emotion=False)
        expected = [('surface', fleet) for fleet in range(1, 7)] + [('submarine', 1), ('submarine', 2)]
        self.assertEqual([(kind, fleet) for name, kind, fleet in state.events if name == 'FLEET_DETAIL'], expected)
        self.assertEqual(sum(name == 'FLEET_NEXT' for name, _, _ in state.events), 6)
        self.assertEqual(sum(name == 'BACK_ARROW' for name, _, _ in state.events), 8)
        self.assertEqual(sum(name.endswith('舰队选择') for name, _, _ in state.events), 2)
        self.assertNotIn('FLEET_DETAIL_CHECK', [event[0] for event in state.events])
        tool.fleet_enter.assert_not_called()
        self.assertEqual(scanner.return_value.scan.call_count, 8)
        saved = tool._save_result.call_args.args[0]
        self.assertEqual([len(saved[key]) for key in ('main', 'vanguard', 'submarine')], [6, 6, 2])

    def test_unknown_bottom_number_does_not_click_or_guess_a_fleet(self):
        tool, state, image = self.native_tool()
        tool.device.image[647:707, 298:348] = 0
        tool.device.screenshot.side_effect = lambda: setattr(state, 'clock', state.clock + 1)
        with patch('module.base.timer.time', side_effect=lambda: state.clock):
            with self.assertRaisesRegex(FleetManagementError, '未能从底部编号确认'):
                tool._scan_fleet_enter(2)
        tool.device.click.assert_not_called()


class ReferenceScanTests(unittest.TestCase):
    def test_targeted_scan_only_submits_selected_fleet_columns_to_ocr(self):
        reader = FormationDockScanner(fleets={1})
        submitted = []
        original = reader.names.scan
        def names(image, **kwargs):
            submitted.append(len(reader.names.ocr_model.buttons))
            return original(image, **kwargs)
        reader.names.scan = Mock(side_effect=names)
        cards = reader.scan(frame('vanguard_top'))
        selected = [card for card in cards if card.fleet == 1]
        others = [card for card in cards if card.fleet != 1]
        self.assertEqual(3, len(selected))
        self.assertEqual(3, sum(submitted))
        self.assertEqual({'花月', '文琴佐·焦贝蒂', '阿尔弗雷多·奥里亚尼'},
                         {card.ship['name'] for card in selected})
        self.assertTrue(all(card.ship['name'] == '' and card.ship['level'] == 0
                            and card.ship['emotion'] is None for card in others))

    def test_targeted_scroll_keeps_all_physical_rows_and_finds_later_fleets(self):
        expected = {'vanguard': {5: {'阿瑞托莎', 'Z18', 'Z19'}, 6: {'Z20'}},
                    'main': {5: {'雪不归', '金色暗影', '帕特莉夏·阿贝尔海姆'}, 6: {'博格'}}}
        for category, teams in expected.items():
            for fleet, names in teams.items():
                with self.subTest(category=category, fleet=fleet):
                    reader, merger = FormationDockScanner(fleets={fleet}), FormationCardMerger()
                    for index, stage in enumerate(('top', 'mid', 'bottom')):
                        image = frame(f'{category}_{stage}')
                        merger.add(image, reader.scan(image, has_remove=index == 0))
                    members = [card for card, _ in merger.slots if card.fleet > 0]
                    self.assertEqual(16, len(members))
                    self.assertEqual(names, {card.ship['name'] for card in members if card.fleet == fleet})
                    self.assertTrue(all(type(card.ship['emotion']) is int for card in members if card.fleet == fleet))
                    self.assertTrue(all(card.ship['emotion'] is None for card in members if card.fleet != fleet))

    def test_single_targeted_card_keeps_its_actual_morale(self):
        cards = FormationDockScanner(fleets={6}).scan(frame('main_bottom'), has_remove=False)
        selected = [card for card in cards if card.fleet == 6]
        self.assertEqual([('博格', 119)], [(card.ship['name'], card.ship['emotion']) for card in selected])

    def test_disabling_morale_update_preserves_existing_slot_values_including_zero(self):
        current = {'vanguard': {'1': [{'slot': 4, 'name': '未知', 'emotion': None},
                                      {'slot': 5, 'name': '花月', 'emotion': None}]}}
        previous = {'vanguard': {'1': [{'slot': 4, 'name': '旧参考', 'emotion': 0},
                                       {'name': '缺少舰位的旧记录', 'emotion': 150}]}}
        preserve_emotions(current, previous)
        self.assertEqual(current['vanguard']['1'][0]['emotion'], 0)
        self.assertIsNone(current['vanguard']['1'][1]['emotion'])

    def test_ocr_failures_keep_all_real_detail_positions_and_unknown_reference_values(self):
        reader = FormationDetailScanner()
        reader.names.scan = Mock(side_effect=RequestHumanTakeover('模拟舰名模型不可用'))
        reader.levels.ocr = Mock(side_effect=ValueError('模拟等级失败'))
        ships = reader.scan(frame('detail_surface'))
        self.assertEqual(set(ships), set(range(1, 7)))
        self.assertTrue(all(ship['occupied'] for ship in ships.values()))
        self.assertTrue(all(ship['name'] == '' for ship in ships.values()))
        self.assertTrue(all(ship['slot'] == slot for slot, ship in ships.items()))

    def test_fixed_detail_positions_do_not_change_when_names_are_wrong(self):
        reader = FormationDetailScanner()
        reader.names.scan = Mock(return_value=['未知文本'] * 6)
        reader.levels.ocr = Mock(return_value=[0] * 6)
        surface = reader.scan(frame('detail_surface'))
        result = combine_references({}, {'surface': {1: surface}, 'submarine': {}})
        self.assertEqual([ship['slot'] for ship in result['main']['1']], [1, 2, 3])
        self.assertEqual([ship['slot'] for ship in result['vanguard']['1']], [4, 5, 6])
        self.assertTrue(all(ship['review'] for ship in result['vanguard']['1']))

    def test_six_native_dock_frames_preserve_32_members_without_duplicate_merging(self):
        scanner = FormationDockScanner()
        expected = {
            'vanguard': {1: {'花月', '文琴佐·焦贝蒂', '阿尔弗雷多·奥里亚尼'},
                         2: {'威廉·D·波特', '岛风', '莫斯科'}, 3: {'热心.改', '命运女神.改', '灵敏·META'},
                         4: {'唐斯.改', '杜威', '艾尔温'}, 5: {'阿瑞托莎', 'Z18', 'Z19'}, 6: {'Z20'}},
            'main': {1: {'拉斐尔', '独角兽.改', '瑞凤'}, 2: {'狮', '苏维埃同盟', '阿尔萨斯'},
                     3: {'雫', '穗香', '伊莉丝'}, 4: {'DEAD MASTER', '环', '优米雅·利斯菲尔德'},
                     5: {'雪不归', '金色暗影', '帕特莉夏·阿贝尔海姆'}, 6: {'博格'}},
        }
        for group in ('vanguard', 'main'):
            merger = FormationCardMerger()
            for index, stage in enumerate(('top', 'mid', 'bottom')):
                image = frame(f'{group}_{stage}')
                cards = scanner.scan(image, has_remove=index == 0)
                merger.add(image, cards)
            members = [card for card, _ in merger.slots if card.fleet > 0]
            self.assertEqual(len(members), 16)
            self.assertEqual({number: {card.ship['name'] for card in members if card.fleet == number}
                              for number in range(1, 7)}, expected[group])

    def test_morale_can_be_skipped_without_calling_its_ocr(self):
        reader = FormationDockScanner(update_emotion=False)
        reader.emotions.scan = Mock(side_effect=AssertionError('不应读取心情'))
        cards = reader.scan(frame('vanguard_top'))
        self.assertTrue(all(card.ship['emotion'] is None for card in cards))
        reader.emotions.scan.assert_not_called()

    def test_native_detail_slots_read_names_and_levels_as_reference(self):
        reader = FormationDetailScanner()
        ships = reader.scan(frame('detail_surface'))
        self.assertEqual([ships[slot]['name'] for slot in (1, 2, 3, 5, 6)],
                         ['拉斐尔', '瑞凤', '独角兽.改', '花月', '文琴佐·焦贝蒂'])
        self.assertEqual([ships[slot]['level'] for slot in range(1, 7)], [125, 125, 125, 105, 105, 105])
        sub = reader.scan(frame('detail_submarine'), 'submarine')
        self.assertEqual(list(sub), [1, 2, 3])
        self.assertEqual(sub[1]['name'], '伊404')
        self.assertEqual(sub[2]['name'], 'U-2501')

    def test_latest_frames_confirm_lua_names_and_same_slot_portraits(self):
        dock = frame('rotation_dock')
        cards = FormationDockScanner().scan(dock)
        self.assertEqual({card.ship['name'] for card in cards if card.fleet == 4},
                         {'杜威', '艾尔温', '唐斯.改'})
        self.assertEqual(min(card.ship['emotion'] for card in cards if card.fleet == 3), 138)
        ships = FormationDetailScanner().scan(frame('rotation_detail'))
        self.assertEqual([ships[slot]['name'] for slot in range(1, 7)],
                         ['拉斐尔', '瑞凤', '独角兽.改', '杜威', '艾尔温', '文琴佐·焦贝蒂'])
        self.assertEqual([ships[slot]['level'] for slot in range(1, 7)], [125, 125, 125, 100, 99, 105])
        portraits = detail_portraits(frame('rotation_detail'))
        for slot, column in ((4, 3), (5, 1)):
            matcher = PortraitMatcher(portraits[slot])
            candidates = [(card, card.y, matcher.score(VisualDockScanner.portrait(dock, card))) for card in cards]
            chosen, _ = choose_portrait(candidates, 4)
            self.assertEqual((chosen.fleet, chosen.col), (4, column))

    def test_direct_picker_frames_confirm_raphael_dewey_and_morale_twelve(self):
        for category, names in (('main', {'拉斐尔': (1, 125, 150), '突击者': (6, 100, 12)}),
                                ('vanguard', {'杜威': (1, 100, 150), 'Z20': (6, 100, 12)})):
            with self.subTest(category=category):
                cards = FormationDockScanner().scan(frame(f'direct_{category}'))
                actual = {card.ship['name']: (card.fleet, card.ship['level'], card.ship['emotion']) for card in cards}
                for name, values in names.items():
                    self.assertEqual(actual[name], values)

    def test_ambiguous_portraits_do_not_assign_morale_using_a_matching_name(self):
        image = frame('detail_surface')
        portrait = detail_portraits(image)[5]
        positions = {slot: dict(slot=slot, name='花月', emotion=None, level=105,
                                occupied=slot == 5, review=False) for slot in range(1, 7)}
        dock = {'vanguard': {'1': [dict(name='花月', level=105, emotion=150),
                                   dict(name='', level=105, emotion=2)]}}
        result = combine_references(dock, {'surface': {1: positions}},
                                    {'vanguard': {'1': [portrait, portrait]}}, {'surface': {1: image}})
        self.assertIsNone(result['vanguard']['1'][0]['emotion'])

    def test_scan_starts_fleet_one_slot_four_and_never_requires_name_confirmation(self):
        tool = runner()
        tool.config.cross_get.return_value = False
        tool._scan_category = Mock(return_value={})
        tool._capture_formation = Mock(side_effect=lambda number, kind, **kwargs:
            (frame(f'detail_{kind}'), {}, {}))
        with (patch('module.retire.fleet_management.FormationDockScanner') as dock,
              patch('module.retire.fleet_management.FormationDetailScanner') as details):
            dock.return_value.matcher.names = ()
            details.return_value.scan.side_effect = lambda image, kind: {
                slot: dict(name='读错也保留', level=0, emotion=None, slot=slot, occupied=True, review=True)
                for slot in range(1, 7 if kind == 'surface' else 4)}
            tool.run(update_emotion=False)
        tool.ui_ensure.assert_called_once_with(page_fleet)
        tool.fleet_enter.assert_not_called()
        tool._enter_scan_submarine.assert_called_once_with()
        self.assertEqual([call.args for call in tool._open_slot.call_args_list],
                         [(4, 'surface'), (1, 'surface'), (1, 'submarine')])
        tool._save_result.assert_called_once()
        saved = tool._save_result.call_args.args[0]
        self.assertEqual(len(saved['main']), 6)
        self.assertEqual(len(saved['vanguard']), 6)
        self.assertEqual(len(saved['submarine']), 2)
        self.assertEqual([ship['slot'] for ship in saved['submarine']['2']], [1, 2, 3])
        self.assertTrue(tool.dock_filter.reset_first)
        self.assertEqual(tool.config.cross_set.call_args.args[0], 'FleetInfo.FleetTraining.FullScanRecord')

    def test_interrupted_full_scan_and_partial_saves_do_not_reset_full_scan_time(self):
        tool = runner()
        tool._scan_category = Mock(side_effect=GameStuckError('扫描中断'))
        with self.assertRaises(GameStuckError):
            tool.run(update_emotion=False)
        self.assertTrue(tool.dock_filter.reset_first)
        tool.config.cross_set.assert_not_called()
        FleetManagement._save_result(tool, {'main': {'1': []}})
        tool.config.save.assert_called_once()
        tool.config.cross_set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
