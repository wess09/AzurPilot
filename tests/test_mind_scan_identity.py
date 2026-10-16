"""心智重名群组、原生卡片、人工确认及科技导入的离线回归。"""
import copy
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import numpy as np

from module.api.config_service import ConfigService
from module.api.mind_calculator_service import MindCalculatorService, import_ships
from module.runtime import fleet_tech
from module.runtime.mind_calculator import calculate, find_ship, find_ships, highest_ships
from module.runtime.mind_identity import MindIdentity
from module.runtime.fleet_tech_identity import surface_icon, aviation_icon
from module.runtime.mind_recognition import recognize_cards
from tests.test_api import fixture

FIXTURES = Path(__file__).parent / 'fixtures'


def ship(name, level=100, **values):
    return dict(name=name, level=level, rarity='SSR', **values)


class SameNameTests(unittest.TestCase):
    def test_catalog_preserves_every_same_name_group_and_original_rarity(self):
        for name, expected in [('天城', {30405: 'SSR', 30715: 'UR'}),
                               ('加贺', {30507: 'SSR', 30702: 'SSR'}),
                               ('约克', {20307: 'SR', 40311: 'SR'}),
                               ('新月', {20109: 'N', 30156: 'SR'}),
                               ('霞', {30181: 'SR', 1060003: 'SSR'})]:
            with self.subTest(name=name):
                self.assertIsNone(find_ship(name))
                self.assertEqual({row['group_type']: row['base_rarity'] for row in find_ships(name)}, expected)
                for row in find_ships(name):
                    self.assertEqual(find_ship(row['name'], row['group_type']), row)

    def test_aircraft_and_surface_icons_distinguish_same_names_without_rarity_guessing(self):
        for name, aviation, surface in [('天城', 30715, 30405), ('加贺', 30702, 30507)]:
            for matcher in (MindIdentity().match,):
                with self.subTest(name=name, matcher=matcher.__name__):
                    self.assertIsNone(matcher([name] * 3, 'UR')[0])
                    self.assertEqual(matcher([name] * 3, 'SR', aviation=True)[0]['group_type'], aviation)
                    self.assertEqual(matcher([name] * 3, 'UR', surface=True)[0]['group_type'], surface)
                    self.assertIsNone(matcher([name] * 3, '', aviation=True, surface=True)[0])
                    self.assertIsNone(matcher([name], '', aviation=True)[0])

    def test_york_and_crescent_are_ambiguous_even_with_matching_rarity(self):
        for name in ('约克', '新月'):
            for rarity in ('N', 'SR', 'SSR', ''):
                for matcher in (MindIdentity().match,):
                    with self.subTest(name=name, rarity=rarity, matcher=matcher.__name__):
                        info, note = matcher([name] * 3, rarity)
                        self.assertIsNone(info)
                        self.assertIn('同名同舰种', note)
        self.assertEqual(find_ship('新月.改')['group_type'], 20109)
        self.assertEqual(find_ship('约克.改')['group_type'], 20307)

    def test_qualified_original_retrofit_and_meta_merge_only_the_same_identity(self):
        rows = [ship('天城（战巡）'), ship('天城（正航）'), ship('加贺（战列）'), ship('加贺（正航）'),
                ship('新月（皇家）'), ship('新月.改', 106), ship('新月（重樱）'),
                ship('约克（皇家）'), ship('约克.改', 106), ship('约克（铁血）')]
        highest = highest_ships(rows)
        self.assertEqual(len(highest), 8)
        report = calculate(rows)
        self.assertEqual((report['included'], report['merged'], report['review']), (8, 2, 0))
        self.assertEqual(next(row for row in report['ships'] if row['name'] == '新月.改')['base_rarity'], 'N')

    def test_legacy_ambiguous_rows_remain_separate_unbilled_and_read_only(self):
        rows = [ship(name) for name in ('新月', '新月', '约克', '约克', '天城', '加贺')]
        before = copy.deepcopy(rows)
        self.assertEqual(len(highest_ships(rows)), len(rows))
        report = calculate(rows)
        self.assertEqual((report['included'], report['review'], report['mind']), (0, 6, 0))
        self.assertEqual(rows, before)
        with tempfile.TemporaryDirectory() as directory:
            configs = ConfigService(fixture(directory))
            service = MindCalculatorService(configs)
            service.save('testpilot', service.report('testpilot')['revision'], rows)
            saved = configs.path('testpilot').read_bytes()
            self.assertEqual(service.report('testpilot')['review'], 6)
            self.assertEqual(configs.path('testpilot').read_bytes(), saved)

    def test_manual_qualified_names_round_trip_and_import_into_correct_technology_groups(self):
        rows = [ship('新月（皇家）', 106), ship('新月（重樱）', 110), ship('约克（皇家）'), ship('约克（铁血）'),
                ship('加贺（战列）'), ship('加贺（正航）'), ship('约克', review=True)]
        with tempfile.TemporaryDirectory() as directory:
            configs = ConfigService(fixture(directory))
            service = MindCalculatorService(configs)
            saved = service.save('testpilot', service.report('testpilot')['revision'], rows)
            self.assertEqual((saved['included'], saved['review']), (6, 1))
            exported = service.export('testpilot', 'json')
            imported = import_ships('ships.json', exported['content'])
            self.assertEqual([row['name'] for row in imported], [find_ship(row['name'])['name']
                             if find_ship(row['name']) else row['name'] for row in rows])
            observed = fleet_tech.merge_mind({}, imported)['observed']
            self.assertEqual(observed, {'20109': 106, '30156': 110, '20307': 100, '40311': 100,
                                        '30507': 100, '30702': 100})


class NativeSameNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = {}
        for label, rows in [('amagi', [75]), ('kaga', [77]), ('york', None), ('crescent', None)]:
            cls.cards[label] = recognize_cards(Image.open(FIXTURES / f'fleet_tech_{label}.png'), row_origins=rows)

    def test_native_amagi_and_kaga_cards_keep_both_groups_and_correct_costs(self):
        for label, expected in [('amagi', {30715: 'UR', 30405: 'SSR'}), ('kaga', {30507: 'SSR', 30702: 'SSR'})]:
            cards = [card for card in self.cards[label] if card.ship['name'] in ('天城', '加贺')
                     and card.ship.get('group_type') is not None]
            actual = {card.ship['group_type']: card.ship['base_rarity'] for card in cards}
            self.assertEqual(actual, expected)
            self.assertFalse(any(card.ship['review'] for card in cards))
            self.assertEqual(calculate([dict(card.ship, level=100) for card in cards])['included'], 2)

    def test_native_same_type_names_are_separate_reviews_without_candidate_guessing(self):
        for label, name in [('york', '约克'), ('crescent', '新月')]:
            cards = [card for card in self.cards[label] if card.ship['name'] == name]
            self.assertTrue(cards)
            self.assertTrue(all(card.ship['name'] == name and card.ship['review']
                                and card.ship['candidates'] and card.ship['group_type'] is None for card in cards))
            report = calculate(highest_ships([card.ship for card in cards]))
            self.assertEqual((report['included'], report['review'], report['mind']), (0, len(cards), 0))

    def test_native_icon_phase_and_failed_short_name_require_positive_proof(self):
        image = Image.open(FIXTURES / 'mind_identity_native_phase.png').convert('RGB')
        pixels = np.array(image)
        for x in (93, 258):
            self.assertTrue(surface_icon(pixels, x, 76))
            self.assertFalse(aviation_icon(pixels, x, 76))
        self.assertTrue(aviation_icon(pixels, 422, 303))
        self.assertFalse(surface_icon(pixels, 422, 303))
        cards = recognize_cards(image, row_origins=[76, 303, 530])
        self.assertEqual({(row.ship['name'], row.ship.get('group_type')) for row in cards},
                         {('天城', 30405), ('加贺', 30507), ('加贺', 30702), ('大山', 39907)})
        self.assertTrue(all(row.ship['level'] == 120 and not row.ship['review'] for row in cards))
        self.assertTrue(MindIdentity().stroke_shifts(['天山', '天山']))
        self.assertTrue(MindIdentity().stroke_shifts(['天山', '大山']))
        self.assertEqual(MindIdentity().stroke_shifts(['大山', '大胆']), ())

    def test_low_level_native_phase_keeps_names_levels_and_unassigned_fleet(self):
        cards = recognize_cards(Image.open(FIXTURES / 'mind_low_native_phase.png'), row_origins=[76, 303, 530])
        self.assertEqual({(card.ship['name'], card.ship['level'], card.fleet) for card in cards},
                         {('星座', 1, 0), ('长良', 1, 0), ('厌战', 1, 0), ('大凤', 1, 0), ('让·巴尔', 1, 0)})
        self.assertTrue(all(not card.ship['review'] and card.level_reliable for card in cards))

    def test_truncated_meta_prefix_is_ambiguous_until_faction_is_verified(self):
        image = Image.open(FIXTURES / 'mind_meta_truncated_phase.png')
        cards = recognize_cards(image, row_origins=[77, 530])
        ambiguous = [card for card in cards if card.y == 530 or card.col == 1]
        self.assertEqual(len(ambiguous), 2)
        self.assertTrue(all(card.ship['review'] and card.ship.get('group_type') is None
                            and len(card.ship['candidates']) == 2 for card in ambiguous))
        verified = recognize_cards(image, row_origins=[77, 530], identity=MindIdentity({97}))
        actual = {(card.ship['name'], card.ship['level']) for card in verified
                  if card.y == 530 or card.col == 1}
        self.assertEqual(actual, {('拉·加利索尼埃·META', 120), ('朱利奥·凯撒·META', 120)})
        self.assertTrue(all(not card.ship['review'] for card in verified if card.y == 530 or card.col == 1))

    def test_bold_short_name_phase_confirms_both_stroke_reads(self):
        cards = recognize_cards(Image.open(FIXTURES / 'mind_bold_native_phase.png'), row_origins=[74])
        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0].ship['name'], cards[0].ship['group_type'], cards[0].ship['level']),
                         ('大胆', 80105, 105))
        self.assertFalse(cards[0].ship['review'])

    def test_ii_suffix_with_frame_ghost_requires_two_exact_cropped_suffix_reads(self):
        cards = recognize_cards(Image.open(FIXTURES / 'mind_ii_suffix_native_phase.png'), row_origins=[304])
        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0].ship['name'], cards[0].ship['group_type']), ('休斯敦II', 10231))
        self.assertFalse(cards[0].ship['review'])
        self.assertGreaterEqual(sum('ii' == name[-2:].casefold() or name.endswith('Ⅱ') for name in cards[0].name_reads), 2)


if __name__ == '__main__':
    unittest.main()
