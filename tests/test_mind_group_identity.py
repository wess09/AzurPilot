"""群组身份贯穿真实 API、费用、导入导出及科技兼容导入。"""
import copy
import tempfile
import unittest

from pydantic import ValidationError
from starlette.testclient import TestClient

from module.api.app import create_app
from module.api.config_service import ConfigService
from module.api.mind_calculator_service import MindCalculatorService, import_ships, input_ship
from module.api.protocol import MindShip
from module.runtime.fleet_tech import merge_mind
from module.runtime.mind_calculator import calculate, find_ship, find_ships, highest_ships, preserve_exclusions
from module.runtime.mind_identity import MindIdentity
from tests.test_api import fixture
from tests import test_api


def ship(name, gid=None, level=100, **kwargs):
    return input_ship(MindShip(name=name, group_type=gid, level=level, **kwargs).model_dump())


class GroupIdentityTests(unittest.TestCase):
    def test_every_same_name_retains_all_groups_and_requires_explicit_identity(self):
        for name, gids in {'天城': [30405, 30715], '加贺': [30507, 30702], '新月': [20109, 30156],
                           '约克': [20307, 40311], '霞': [30181, 1060003]}.items():
            self.assertEqual(sorted(info['group_type'] for info in find_ships(name)), gids)
            self.assertIsNone(find_ship(name))
            rows = [ship(name, gid) for gid in gids]
            self.assertEqual(len(highest_ships(rows)), 2)
            self.assertEqual({row['group_type'] for row in calculate(rows)['ships']}, set(gids))

    def test_highest_levels_retrofits_and_billing_are_scoped_to_group(self):
        rows = [ship('加贺', 30507, 100), ship('加贺', 30702, 100), ship('加贺', 30507, 120)]
        self.assertEqual(len(highest_ships(rows)), 2)
        result = calculate(rows)
        self.assertEqual((result['included'], result['merged'], result['mind'], result['gold']), (2, 1, 2200, 22000))
        result = calculate([ship('天城', 30405), ship('天城', 30715, 105)])
        self.assertEqual([row['base_rarity'] for row in result['ships']], ['SSR', 'UR'])
        self.assertEqual(result['mind'], 5200)
        rows = [ship('约克', 20307), ship('约克.改', 20307), ship('约克', 40311)]
        self.assertEqual([row['name'] for row in highest_ships(rows)], ['约克.改', '约克'])
        result = calculate([ship('霞', 30181), ship('霞', 1060003)])
        self.assertEqual((result['included'], result['excluded'], result['mind']), (1, 1, 1320))

    def test_legacy_ambiguous_records_are_independent_review_and_manual_exclusion_survives(self):
        rows = [ship('加贺'), ship('加贺', level=120), ship('天城', excluded=True, source='人工排除')]
        self.assertEqual(len(highest_ships(rows)), 3)
        result = calculate(rows)
        self.assertEqual((result['review'], result['excluded'], result['mind']), (2, 1, 0))
        self.assertEqual(result['ships'][2]['source'], '人工排除')
        self.assertTrue(all(row['group_type'] is None for row in result['ships']))
        self.assertTrue(preserve_exclusions([ship('加贺', 30507)], [ship('加贺', 30507, excluded=True)])[0]['excluded'])
        self.assertFalse(preserve_exclusions([ship('加贺', 30702)], [ship('加贺', 30507, excluded=True)])[0]['excluded'])

    def test_ambiguous_legacy_manual_exclusion_is_retained_without_reenabling_charges(self):
        old = ship('加贺', excluded=True, source='用户人工排除')
        scanned = [ship('加贺', 30507), ship('加贺', 30702), ship('拉菲')]
        rows = preserve_exclusions(scanned, [old])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]['source'], old['source'])
        self.assertTrue(rows[-1]['excluded'])
        self.assertTrue(all(row['review'] for row in rows[:2]))
        self.assertEqual(calculate(rows)['mind'], 1320)
        again = preserve_exclusions(scanned, rows)
        self.assertEqual(again, rows)

    def test_invalid_identity_is_rejected_at_api_and_unbillable_in_pure_calculator(self):
        for gid in (True, '30507', -1, 999999, 10117):
            with self.subTest(gid=gid), self.assertRaises(ValidationError):
                ship('加贺', gid)
        result = calculate([dict(name='加贺', group_type=10117, level=100, base_rarity='UR')])
        self.assertEqual((result['review'], result['mind']), (1, 0))
        self.assertIsNone(result['ships'][0]['group_type'])

    def test_preexisting_qualified_names_are_migrated_only_when_the_qualifier_proves_identity(self):
        rows = [ship('加贺（战列）'), ship('加贺（正航）'), ship('约克（皇家）'), ship('约克（铁血）')]
        self.assertEqual([row['group_type'] for row in rows], [30507, 30702, 20307, 40311])
        self.assertEqual([row['name'] for row in rows], ['加贺', '加贺', '约克', '约克'])
        self.assertEqual(calculate(rows)['included'], 4)
        self.assertIsNone(find_ship('加贺（驱逐）'))

    def test_shared_identity_requires_positive_icons_and_rejects_same_type_guess(self):
        identity = MindIdentity()
        for name, surface, aviation in [('加贺', 30507, 30702), ('天城', 30405, 30715)]:
            self.assertIsNone(identity.match([name, name], 'SSR')[0])
            self.assertEqual(identity.match([name, name], 'SSR', surface=True)[0]['group_type'], surface)
            self.assertEqual(identity.match([name, name], 'SSR', aviation=True)[0]['group_type'], aviation)
        for name in ('新月', '约克'):
            self.assertIsNone(identity.match([name] * 3, 'SR', fuzzy=True)[0])
        self.assertEqual(identity.match(['约克.改'] * 2)[0]['group_type'], 20307)

    def test_mind_to_technology_preserves_both_groups_but_rejects_forgery_and_reviews(self):
        rows = [ship('加贺', 30507, 120), ship('加贺', 30702), ship('新月', review=True)]
        record = merge_mind({}, [*rows, dict(name='拉菲', group_type=30715, level=125)])
        self.assertEqual(record['observed'], {'30507': 120, '30702': 100})
        self.assertEqual(merge_mind(record, rows), record)


class GroupRoundtripTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.configs = ConfigService(fixture(directory))
        self.service = MindCalculatorService(self.configs)

    def test_all_file_formats_and_reload_keep_identity_fee_and_independent_review(self):
        rows = [ship('加贺', 30507, 120), ship('加贺', 30702), ship('天城', 30405),
                ship('天城', 30715, 105), ship('约克', review=True, candidates=[20307, 40311]),
                ship('新月', level=0, review=True, excluded=True, candidates=[20109, 30156])]
        saved = self.service.save('testpilot', self.service.report('testpilot')['revision'], rows)
        self.assertEqual(saved['mind'], 7400)
        for format in ('json', 'csv', 'xlsx'):
            file = self.service.export('testpilot', format)
            parsed = import_ships(file['filename'], file['content'])
            self.assertEqual(parsed, rows)
            self.assertEqual(calculate(parsed)['mind'], 7400)
        before = self.configs.path('testpilot').read_bytes()
        self.assertEqual(self.service.report('testpilot')['revision'], saved['revision'])
        self.assertEqual(self.configs.path('testpilot').read_bytes(), before)

    def test_real_websocket_schema_save_export_and_concurrent_revision_protection(self):
        app = create_app(root=self.configs.root, password='test-secret', manage_runtime=False, mount_mcp=False)
        client = TestClient(app)
        caller = test_api.SocketApiTests()
        caller.counter = 0
        with client.websocket_connect('/api/v1/ws') as ws:
            caller.login(ws)
            def call(method, **params):
                return caller.call(ws, method, dict(instance='testpilot', **params))
            report = call('mind.report')['result']
            rows = [ship('加贺', 30507, 120), ship('加贺', 30702)]
            saved = call('mind.save', revision=report['revision'], ships=rows)
            self.assertTrue(saved['ok'], saved)
            self.assertEqual(saved['result']['mind'], 2200)
            self.assertEqual(call('mind.save', revision=report['revision'], ships=[])['error']['code'], 'CONFLICT')
            bad = copy.deepcopy(rows)
            bad[0]['group_type'] = 30715
            self.assertEqual(call('mind.calculate', ships=bad)['error']['code'], 'INVALID_PARAMS')
            file = call('mind.export', format='xlsx')['result']
            parsed = call('mind.import', filename=file['filename'], content=file['content'])
            self.assertEqual(parsed['result']['ships'], rows)
