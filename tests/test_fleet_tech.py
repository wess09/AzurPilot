"""科技目录与历史记录回归；所有写入均使用临时实例。"""
import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pydantic import ValidationError

from module.api.config_service import ConfigService
from module.api.fleet_tech_service import FleetTechService
from module.api.protocol import ApiError, FleetTechChange, FleetTechPatchParams
from module.runtime import fleet_tech as tech
from module.runtime.fleet_database import FleetDatabase
from module.runtime.mind_recognition import ScanPolicy
from tests.test_api import fixture


def ship(name='杜威', level=125, **kwargs):
    return dict(name=name, level=level, review=False, **kwargs)


class FleetTechTests(unittest.TestCase):
    def test_catalog_integrity_and_known_points(self):
        data = tech.public_catalog()
        self.assertGreaterEqual(len(data['ships']), 897)
        self.assertEqual(len(data['ships']), len({row['group_type'] for row in data['ships']}))
        self.assertEqual(len(data['ships']), len({(row['handbook_type'], row['code']) for row in data['ships']}))
        total = sum(sum(row['technology'][key] for key in ('pt_get', 'pt_upgrage', 'pt_level'))
                    for row in data['ships'] if row['technology'])
        self.assertEqual(data['max_points'], total)
        self.assertEqual(sum(data['nation_points'].values()), total)
        dewey = next(row for row in data['ships'] if row['name'] == '杜威')
        self.assertEqual(dewey['code'], 4)
        self.assertEqual(dewey['technology']['pt_get'], 3)
        for levels in data['nations'].values():
            for effects in levels:
                for types, attr, value in effects:
                    self.assertTrue(types)
                    self.assertIsInstance(attr, int)
                    self.assertIsInstance(value, int)

    def test_missing_evidence_defaults_to_not_obtained(self):
        row = tech.report({'observed': {'10102': 125}, 'manual': {'10102': {'owned': True}}})['ships'][0]
        self.assertFalse(row['owned'])
        self.assertEqual(row['status'], 'unowned')
        self.assertFalse(tech.progress({'observed': {'10102': 125}}, 10102)['owned'])

    def test_multiple_target_subtypes_do_not_triple_bonus(self):
        record = {'progress': {'10102': {'owned': True, 'full_star': True, 'lv120': True}}}
        result = tech.report(record)
        self.assertEqual(result['bonuses']['1']['1'], 2)
        record['nations'] = {'1': 1}
        faction = tech.report(record)
        self.assertEqual(faction['bonuses']['7']['5'], 1)
        record['nations']['1'] = 2
        self.assertEqual(tech.report(record)['bonuses']['7']['5'], 1)

    def test_new_catalog_ships_start_incomplete_without_mutating_records(self):
        record = {'progress': {'10102': {'owned': True, 'full_star': True, 'lv120': True}}}
        original = copy.deepcopy(record)
        data = copy.deepcopy(tech.catalog())
        row = dict(data['ships'][0], group_type=99999999)
        data['ships'].append(row)
        with patch.object(tech, 'catalog', return_value=data):
            self.assertEqual(tech.report(record)['ships'][-1]['status'], 'unowned')
        self.assertEqual(record, original)

    def test_service_transactions_conflicts_restore_and_instance_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            configs = ConfigService(fixture(directory))
            (configs.path('testpilot').parent / 'second.json').write_bytes(configs.path('testpilot').read_bytes())
            service = FleetTechService(configs)
            initial = service.report('testpilot')
            updated = service.patch('testpilot', initial['revision'], [FleetTechChange(group_type=10102, owned=False)], {})
            with self.assertRaises(ApiError) as error:
                service.patch('testpilot', initial['revision'], [FleetTechChange(group_type=10102, owned=True)], {})
            self.assertEqual(error.exception.code, 'CONFLICT')
            updated = service.patch('testpilot', updated['revision'], [FleetTechChange(group_type=10102, owned=True)], {})
            self.assertTrue(next(row for row in updated['ships'] if row['group_type'] == 10102)['owned'])
            self.assertEqual(service.report('second')['completed'], 0)

    def test_invalid_patch_does_not_write_any_partial_change(self):
        schema = FleetTechChange.model_json_schema()
        self.assertTrue(all('default' not in field for field in schema['properties'].values()))
        with tempfile.TemporaryDirectory() as directory:
            configs = ConfigService(fixture(directory))
            service = FleetTechService(configs)
            before = configs.path('testpilot').read_bytes()
            initial = service.report('testpilot')
            with self.assertRaises(ApiError):
                service.patch('testpilot', initial['revision'], [FleetTechChange(group_type=10102, owned=True)], {'1': 100})
            self.assertEqual(before, configs.path('testpilot').read_bytes())
            for change in [{'group_type': 10102, 'level': 0}, {'group_type': True}, {'group_type': 10102, 'level': 126},
                           *({'group_type': 10102, key: None} for key in tech.MILESTONES)]:
                with self.assertRaises(ValidationError):
                    FleetTechChange.model_validate(change)
            with self.assertRaises(ValidationError):
                FleetTechPatchParams.model_validate({'instance': 'testpilot', 'revision': 'a' * 64, 'nations': {'1': True}})

    def test_saved_scan_range_belongs_to_dock_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture(directory)
            path = root / 'config/testpilot.json'
            data = json.loads(path.read_text(encoding='utf-8'))
            data['DockScan']['Dock']['MinLevel'] = 90
            data['DockScan']['Dock']['MaxLevel'] = 120
            path.write_text(json.dumps(data), encoding='utf-8')
            from module.api.dock_service import DockService
            configs = ConfigService(root)
            result = DockService(configs).report('testpilot')
            self.assertEqual((result['min_level'], result['max_level']), (90, 120))
            technology = FleetTechService(configs).report('testpilot')
            self.assertNotIn('min_level', technology)
            self.assertNotIn('max_level', technology)
            self.assertEqual((ScanPolicy().min_level, ScanPolicy().max_level), (95, 125))

    def test_router_contract_and_read_only_guards(self):
        from module.api.router import Router
        from module.api.protocol import ConfigChange
        with tempfile.TemporaryDirectory() as directory:
            configs = ConfigService(fixture(directory))
            router = Router(configs, SimpleNamespace())
            result = router.dispatch('fleetTech.report', {'instance': 'testpilot'})
            updated = router.dispatch('fleetTech.patch', {'instance': 'testpilot', 'revision': result['revision'],
                                      'changes': [{'group_type': 10102, 'full_star': True}]})
            row = next(row for row in updated['ships'] if row['group_type'] == 10102)
            self.assertTrue(row['full_star'])
            self.assertTrue(row['owned'])
            self.assertFalse(row['lv120'])
            with patch.dict('os.environ', {'DEMO': '1'}):
                self.assertTrue(router.dispatch('fleetTech.catalog', {'instance': 'testpilot'})['ships'])
            with self.assertRaises(ApiError) as error:
                configs.patch('testpilot', configs.get('testpilot')['revision'], [ConfigChange(path='FleetTechScan.FleetTech.Record', value={})])
            self.assertEqual(error.exception.code, 'READ_ONLY')

    def test_scan_transaction_preserves_manual_edit_made_during_scan(self):
        """使用真实配置 save，模拟扫描中途另一客户端写入人工校正。"""
        from contextlib import ExitStack
        from module.config.config import AzurLaneConfig
        from module.retire.dock_scan import DockScan
        from module.retire.assets import DOCK_SEARCH_CLOSED
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            configs = ConfigService(fixture(directory))
            path = configs.path('testpilot')
            for module in ('module.config.config', 'module.config.config_updater', 'module.config.utils'):
                stack.enter_context(patch(module + '.filepath_config', side_effect=lambda *args: str(path)))
            stack.enter_context(patch.object(AzurLaneConfig, 'init_task'))
            stack.enter_context(patch('module.ocr.al_ocr.AlOcr'))
            stack.enter_context(patch('module.retire.dock_scan.server.server', 'cn'))
            scroll = SimpleNamespace(set_top=lambda _: None, appear=lambda _: True, at_top=lambda _: True, length=1, total=2)
            stack.enter_context(patch('module.retire.dock_scan.DOCK_SCROLL', scroll))
            config = AzurLaneConfig('testpilot')
            config.data = configs.read('testpilot')[0]
            config._loaded_data = copy.deepcopy(config.data)
            runner = object.__new__(DockScan)
            runner.config = config
            runner.device = SimpleNamespace(image=None)
            runner._close_search = lambda: None
            stack.enter_context(patch('module.retire.enhancement.OCR_DOCK_AMOUNT.ocr', return_value=(1, 0, 1)))
            runner.ui_ensure = runner.dock_reset = runner.dock_sort_method_dsc_set = lambda *args: None
            runner.appear = lambda button, *args, **kwargs: button is DOCK_SEARCH_CLOSED

            def scan(*args):
                service = FleetTechService(configs)
                service.patch('testpilot', service.report('testpilot')['revision'], [FleetTechChange(group_type=10102, owned=False)], {})
                runner._scan_metadata = dict(reached_bottom=False, physical_count=1)
                runner._scan_slots = [dict(ship(), group_type=10102)]
                return [dict(ship(), group_type=10102)]

            runner._scan_pages = scan
            from module.exception import MindCalculatorScanError
            with self.assertRaises(MindCalculatorScanError):
                runner.run()
            saved = FleetDatabase(path).load(include_pending=True)
            self.assertEqual(saved['snapshot']['ships'], [])
            self.assertEqual(saved['pending_changes'], [])
            self.assertFalse(saved['technology']['progress']['10102']['owned'])

    def test_extractor_parses_nested_faction_bonuses_and_rejects_duplicate_groups(self):
        from dev_tools.ship_data_extractor import extract_fleet_tech
        template = copy.deepcopy(next(row['technology'] for row in tech.catalog()['ships'] if row['group_type'] == 10102))
        fixtures = {
            'ship_data_group.lua': {4: dict(group_type=10102, code=4, handbook_type=0, hide=0)},
            'fleet_tech_ship_template.lua': {10102: template},
            'ship_data_blueprint.lua': {},
            'fleet_tech_template.lua': {1001: {'add': ['{ {6, 7}, 5, 1 }']}},
            'fleet_tech_group.lua': {1: dict(id=1, techs=[1001])},
        }
        with patch('dev_tools.ship_data_extractor.parse_lua_ship_blocks', side_effect=lambda path: fixtures[path.replace('\\', '/').split('/')[-1]]), \
                patch('dev_tools.ship_data_extractor.subprocess.run', return_value=SimpleNamespace(stdout='fixture')):
            result = extract_fleet_tech('fixture')
            self.assertEqual(result['nations']['1'][0], [[[6, 7], 5, 1]])
            fixtures['fleet_tech_template.lua'][1001]['add'] = ['{ {6, 7}, 5, "invalid" }']
            with self.assertRaises(ValueError):
                extract_fleet_tech('fixture')
            fixtures['fleet_tech_template.lua'][1001]['add'] = ['{ {6, 7}, 5, 1 }']
            fixtures['ship_data_group.lua'][5] = dict(fixtures['ship_data_group.lua'][4])
            with self.assertRaises(ValueError):
                extract_fleet_tech('fixture')


if __name__ == '__main__':
    unittest.main()
