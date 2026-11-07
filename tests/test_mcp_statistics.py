"""MCP 统计数据工具：覆盖 WebUI 分类、字段语义与异常状态。"""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema

from module.api.config_service import ConfigService
from module.api.runtime_service import RuntimeService
from module.api.statistics_service import report
from module.mcp.registry import TOOL_BY_NAME
from module.mcp.tools import Tools
from module.persistence.database import get_database, use_database
from module.statistics import resource_flow, resource_stats


def fixture(directory):
    root = Path(directory)
    template = {'Alas': {},
                'Main': {'Scheduler': {'Enable': False, 'NextRun': '2026-01-01 00:00:00'},
                         'Option': {'Count': 2}}}
    data = {
        'Alas': {},
        'Dashboard': {'Oil': {'Value': 123, 'Limit': 500, 'Total': None, 'Record': '2026-11-07 10:00:00'}},
        'Main': {'Scheduler': {'Enable': False, 'NextRun': '2026-01-01 00:00:00'},
                 'Option': {'Count': 2}},
    }
    args = {'Main': {'Scheduler': {'Enable': {'type': 'checkbox', 'value': False},
                                  'NextRun': {'type': 'datetime', 'value': '2026-01-01 00:00:00'}}}}
    for name, value in [('config/template.json', template), ('config/demo.json', data),
                        ('module/config/argument/args.json', args),
                        ('module/config/argument/menu.json', {}),
                        ('module/config/i18n/zh-CN.json', {})]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    return root


class McpStatisticsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = fixture(self.directory.name)
        self.configs = ConfigService(self.root)
        self.runtime = RuntimeService(self.configs)
        self.tools = Tools(self.configs, self.runtime)
        self.addAsyncCleanup(self.tools.close)

    async def invoke(self, name, **arguments):
        return await self.tools.call(name, arguments)

    async def data(self, name, **arguments):
        result = await self.invoke(name, **arguments)
        self.assertFalse(result.isError, result.content[0].text)
        jsonschema.validate(result.structuredContent, TOOL_BY_NAME[name].output)
        return result.structuredContent

    async def error(self, name, **arguments):
        result = await self.invoke(name, **arguments)
        self.assertTrue(result.isError)
        jsonschema.validate(result.structuredContent, TOOL_BY_NAME[name].output)
        self.assertEqual('failed', result.structuredContent['status'])
        return result.structuredContent

    def database(self):
        return use_database(get_database(self.configs.directory))

    async def test_catalog_covers_every_webui_category_and_explains_fields(self):
        catalog = await self.data('azurpilot_get_statistics_schema')
        categories = {item['category']: item for item in catalog['categories']}
        self.assertEqual({'overview', 'resources', 'action', 'opsi', 'commission',
                          'ships', 'loot', 'research', 'storage', 'flows'}, set(categories))
        for item in categories.values():
            with self.subTest(category=item['category']):
                self.assertTrue(item['label'])
                self.assertTrue(item['description'])
                for metric in item['metrics']:
                    self.assertTrue(metric['meaning'])
                for series in item['series']:
                    self.assertTrue(series['unit'])
                    self.assertTrue(series['meaning'])
                for table in item['tables']:
                    self.assertTrue(table['meaning'])
                    self.assertTrue(table['columns'])
        opsi = categories['opsi']
        self.assertIn('battles', {item['key'] for item in opsi['metrics']})
        meow = next(item for item in opsi['tables'] if item['key'] == 'meow_runs')
        self.assertEqual(['hazard', 'battles', 'effective_rounds', 'avg_battle_seconds',
                          'avg_round_seconds', 'research_devices', 'research_rate', 'source'],
                         [column['key'] for column in meow['columns']])
        filtered = await self.data('azurpilot_get_statistics_schema', category='research')
        self.assertEqual(['research'], [item['category'] for item in filtered['categories']])
        self.assertIn('series', {item['name'] for item in filtered['categories'][0]['filters']})

    async def test_tools_are_registered_read_only(self):
        for name in ('azurpilot_get_statistics', 'azurpilot_get_statistics_schema'):
            with self.subTest(tool=name):
                spec = TOOL_BY_NAME[name]
                self.assertTrue(spec.readonly)
                self.assertTrue(spec.idempotent)
                self.assertFalse(spec.mutating)
                self.assertIsNone(spec.device_operation)

    async def test_report_values_match_the_webui_service(self):
        for category in ('opsi', 'commission', 'ships'):
            with self.subTest(category=category):
                raw = report(self.configs, 'demo', category, None, 7, 'month', 0, 'series', None, False)
                payload = await self.data('azurpilot_get_statistics', instance='demo',
                                          category=category, month='2026-11')
                self.assertEqual({item['key']: item['value'] for item in raw['metrics']},
                                 {item['key']: item['value'] for item in payload['metrics']})
                self.assertEqual({item['key']: item['label'] for item in raw['metrics']},
                                 {item['key']: item['label'] for item in payload['metrics']})
                self.assertEqual([table['title'] for table in raw['tables']],
                                 [table['title'] for table in payload['tables']])
                self.assertEqual([table['columns'] for table in raw['tables']],
                                 [table['columns'] for table in payload['tables']])
                for metric in payload['metrics']:
                    self.assertTrue(metric['meaning'], metric)

    async def test_resources_series_keep_real_points_and_limit_them(self):
        with self.database():
            for day in range(1, 31):
                self.assertTrue(resource_stats.record_resource_snapshot(
                    'demo', {'Oil': day * 100},
                    observed_at=datetime(2026, 11, day, 12, 0, 0)))
        payload = await self.data('azurpilot_get_statistics', instance='demo',
                                  category='resources', month='2026-11',
                                  period='month', max_points=10)
        oil = next(item for item in payload['series'] if item['key'] == 'oil')
        self.assertEqual(30, oil['point_count'])
        self.assertLessEqual(len(oil['points']), 10)
        self.assertTrue(oil['truncated'])
        self.assertTrue(payload['truncated'])
        self.assertEqual(100.0, oil['points'][0]['value'])
        self.assertEqual(3000.0, oil['points'][-1]['value'])
        self.assertEqual('2026-11-01 12:00:00', oil['points'][0]['time'])
        self.assertEqual('石油', oil['label'])
        self.assertTrue(oil['meaning'])
        full = await self.data('azurpilot_get_statistics', instance='demo',
                               category='resources', month='2026-11',
                               period='month', max_points=0)
        full_oil = next(item for item in full['series'] if item['key'] == 'oil')
        self.assertEqual(30, len(full_oil['points']))
        self.assertFalse(full_oil['truncated'])

    async def test_empty_categories_return_hint_and_stable_keys(self):
        cases = {
            'opsi': 'battles',
            'commission': 'commissions',
            'ships': 'target_level',
            'storage': 'storage_items',
        }
        for category, marker in cases.items():
            with self.subTest(category=category):
                payload = await self.data('azurpilot_get_statistics', instance='demo',
                                          category=category, month='2026-11')
                self.assertEqual('empty', payload['state'])
                self.assertTrue(payload['hint'])
                if category == 'storage':
                    table = payload['tables'][0]
                    self.assertEqual(marker, table['key'])
                    self.assertEqual(len(table['columns']), len(table['column_keys']))
                    self.assertTrue(table['meaning'])
                else:
                    metric = next(item for item in payload['metrics'] if item['key'] == marker)
                    self.assertTrue(metric['meaning'])
        storage = await self.data('azurpilot_get_statistics', instance='demo', category='storage')
        self.assertIn('仓库统计任务', storage['hint'])

    async def test_overview_matches_dashboard_resource_cards(self):
        payload = await self.data('azurpilot_get_statistics', instance='demo', category='overview')
        oil = next(item for item in payload['resources'] if item['key'] == 'Oil')
        self.assertEqual(123, oil['value'])
        self.assertEqual(500, oil['limit'])
        self.assertTrue(oil['observed'])
        self.assertEqual('2026-11-07 10:00:00', oil['record'])
        self.assertTrue(oil['meaning'])
        self.assertEqual('ready', payload['state'])
        data = json.loads((self.root / 'config/demo.json').read_text(encoding='utf-8'))
        data['Dashboard'] = {}
        (self.root / 'config/demo.json').write_text(json.dumps(data), encoding='utf-8')
        empty = await self.data('azurpilot_get_statistics', instance='demo', category='overview')
        self.assertEqual('empty', empty['state'])
        self.assertTrue(empty['hint'])

    async def test_flows_returns_inventory_and_paged_entries(self):
        config = SimpleNamespace(config_name='demo')
        now = datetime.now()
        with self.database():
            self.assertTrue(resource_flow.record(config, {'Oil': 50}, '测试收入', task='Main'))
            self.assertTrue(resource_flow.record(config, {'Oil': -20}, '测试支出', task='Main'))
            resource_flow.observe(config, 'Oil', 500, observed_at=now)
        start = (now - timedelta(days=1)).isoformat(sep=' ')
        end = (now + timedelta(minutes=5)).isoformat(sep=' ')
        payload = await self.data('azurpilot_get_statistics', instance='demo', category='flows',
                                  start=start, end=end, resource='Oil', limit=1)
        oil = next(item for item in payload['resources'] if item['key'] == 'Oil')
        self.assertEqual(500, oil['value'])
        self.assertEqual(50, oil['income'])
        self.assertEqual(20, oil['expense'])
        self.assertEqual('ready', payload['state'])
        self.assertEqual(1, payload['page']['limit'])
        self.assertEqual(2, payload['page']['total'])
        self.assertTrue(payload['page']['has_more'])
        entries = next(item for item in payload['tables'] if item['key'] == 'flows_entries')
        self.assertEqual(1, len(entries['rows']))
        self.assertEqual(len(entries['columns']), len(entries['column_keys']))

    async def test_empty_flows_explain_how_data_is_recorded(self):
        data = json.loads((self.root / 'config/demo.json').read_text(encoding='utf-8'))
        data['Dashboard'] = {}
        (self.root / 'config/demo.json').write_text(json.dumps(data), encoding='utf-8')
        payload = await self.data('azurpilot_get_statistics', instance='demo', category='flows',
                                  days=7)
        self.assertEqual('empty', payload['state'])
        self.assertIn('资源流水', payload['hint'])
        self.assertEqual(3, len(payload['tables']))

    async def test_loading_state_when_storage_scan_is_running(self):
        with patch('module.mcp.statistics.running_task', return_value='StorageStatistics'):
            payload = await self.data('azurpilot_get_statistics', instance='demo',
                                      category='storage', month='2026-11')
        self.assertEqual('loading', payload['state'])
        self.assertIn('StorageStatistics', payload['hint'])
        self.assertTrue(payload['tables'])

    async def test_permission_and_database_errors_are_clear(self):
        permission = await self.error_with_patch(PermissionError(13, 'Permission denied', 'azurpilot.db'),
                                                 'azurpilot_get_statistics', instance='demo',
                                                 category='opsi')
        self.assertEqual('PERMISSION_DENIED', permission['error']['code'])
        self.assertFalse(permission['error']['retryable'])
        self.assertNotIn('next_step', permission)

        locked = await self.error_with_patch(sqlite3.OperationalError('database is locked'),
                                             'azurpilot_get_statistics', instance='demo',
                                             category='opsi')
        self.assertEqual('STATISTICS_LOADING', locked['error']['code'])
        self.assertTrue(locked['error']['retryable'])
        self.assertEqual('azurpilot_get_statistics', locked['next_step']['tool'])

        unavailable = await self.error_with_patch(OSError('disk unavailable'),
                                                  'azurpilot_get_statistics', instance='demo',
                                                  category='opsi')
        self.assertEqual('STATISTICS_UNAVAILABLE', unavailable['error']['code'])
        self.assertFalse(unavailable['error']['retryable'])

    async def error_with_patch(self, error, name, **arguments):
        with patch('module.mcp.statistics.report', side_effect=error):
            return await self.error(name, **arguments)

    async def test_parameter_errors_are_correctable_without_writes(self):
        path = self.root / 'config/demo.json'
        before = path.read_bytes()
        invalid_month = await self.error('azurpilot_get_statistics', instance='demo',
                                         category='opsi', month='2026-13')
        self.assertEqual('INVALID_PARAMS', invalid_month['error']['code'])
        self.assertEqual('month', invalid_month['error']['details']['field'])

        wrong_filter = await self.error('azurpilot_get_statistics', instance='demo',
                                        category='opsi', resource='Oil')
        self.assertEqual('INVALID_PARAMS', wrong_filter['error']['code'])
        self.assertEqual('resource', wrong_filter['error']['details']['field'])
        self.assertEqual('azurpilot_get_statistics', wrong_filter['next_step']['tool'])

        wrong_task = await self.error('azurpilot_get_statistics', instance='demo',
                                      category='loot', task='OpsiAbyssal')
        self.assertEqual('INVALID_PARAMS', wrong_task['error']['code'])
        self.assertEqual('task', wrong_task['error']['details']['field'])

        unknown = await self.error('azurpilot_get_statistics', instance='missing', category='opsi')
        self.assertEqual('NOT_FOUND', unknown['error']['code'])
        self.assertEqual(before, path.read_bytes())

    async def test_include_series_false_returns_metrics_without_timeline(self):
        payload = await self.data('azurpilot_get_statistics', instance='demo',
                                  category='resources', month='2026-11', include_series=False)
        self.assertEqual([], payload['series'])
        self.assertFalse(payload['truncated'])


if __name__ == '__main__':
    unittest.main()
