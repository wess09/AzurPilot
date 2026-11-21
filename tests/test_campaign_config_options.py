"""活动候选按实例地区隔离，旧值与运行器一致且读取不写盘。"""

import copy
import hashlib
import json
import tempfile
import unittest

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.config.config_updater import COALITIONS, EVENTS, MIXED_CAMPAIGNS, RAIDS, ConfigUpdater
from tests.test_api import fixture


class CampaignConfigOptionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.configs = ConfigService(fixture(temporary.name))

    def legacy(self, package='com.bilibili.azurlane'):
        path = self.configs.path('testpilot')
        values = self.configs.read_json(path)
        values['Alas']['Emulator'].update(PackageName=package, ServerName='cn_android-0')
        for task in EVENTS + RAIDS + COALITIONS + MIXED_CAMPAIGNS:
            values[task]['Campaign']['Event'] = 'event_20241219_cn'
        path.write_text(json.dumps(values), encoding='utf-8')
        return path, values

    def test_read_matches_runtime_for_each_region_without_writing(self):
        schema = copy.deepcopy(self.configs.args)
        for package, region in (
            ('com.bilibili.azurlane', 'cn'), ('com.bilibili.blhx.huawei', 'cn'),
            ('com.YoStarEN.AzurLane', 'en'), ('com.YoStarJP.AzurLane', 'jp'),
            ('com.hkmanjuu.azurlane.gp', 'tw'), ('com.hkmanjuu.azurlane.gp.mc', 'tw'),
            ('auto', 'cn'),
        ):
            with self.subTest(package=package):
                path, legacy = self.legacy(package)
                before = path.read_bytes(), path.stat().st_mtime_ns
                current = self.configs.get('testpilot')
                runtime = ConfigUpdater().config_update(legacy)
                for task in EVENTS + RAIDS + COALITIONS + MIXED_CAMPAIGNS:
                    candidates = self.configs.args[task]['Campaign']['Event'][f'option_{region}']
                    self.assertEqual(candidates, current['options'][f'{task}.Campaign.Event'])
                    self.assertEqual(runtime[task]['Campaign']['Event'], current['values'][task]['Campaign']['Event'])
                self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
                self.assertEqual(hashlib.sha256(before[0]).hexdigest(), current['revision'])
        self.assertEqual(schema, self.configs.args)

    def test_each_current_event_is_preserved_when_multiple_events_are_open(self):
        path, values = self.legacy()
        self.configs.args['Event']['Campaign']['Event']['option_cn'] = ['first', 'second']
        values['Event']['Campaign']['Event'] = 'second'
        path.write_text(json.dumps(values), encoding='utf-8')
        current = self.configs.get('testpilot')
        self.assertEqual('second', current['values']['Event']['Campaign']['Event'])
        self.assertEqual(['first', 'second'], current['options']['Event.Campaign.Event'])

    def test_cross_region_choice_rejects_entire_transaction(self):
        path, _ = self.legacy()
        before = path.read_bytes()
        taiwan = self.distinct_taiwan_event()
        with self.assertRaises(ApiError) as caught:
            self.configs.patch('testpilot', None, [
                ConfigChange(path='Alas.Emulator.Serial', value='should-not-save'),
                ConfigChange(path='Event.Campaign.Event', value=taiwan),
            ])
        self.assertEqual('INVALID_PARAMS', caught.exception.code)
        self.assertEqual(before, path.read_bytes())

    def test_batch_uses_final_package_regardless_of_field_order(self):
        self.distinct_taiwan_event()
        taiwan_options = self.configs.args['Event']['Campaign']['Event']['option_tw']
        taiwan = taiwan_options[0]
        package = ConfigChange(path='Alas.Emulator.PackageName', value='com.hkmanjuu.azurlane.gp')
        event = ConfigChange(path='Event.Campaign.Event', value=taiwan)
        for changes in ([event, package], [package, event]):
            with self.subTest(changes=changes):
                self.legacy()
                current = self.configs.patch('testpilot', None, changes)
                self.assertEqual(taiwan, current['values']['Event']['Campaign']['Event'])
                self.assertEqual(taiwan_options, current['options']['Event.Campaign.Event'])

    def test_package_change_refreshes_options_and_other_instances_stay_isolated(self):
        self.legacy()
        self.configs.create('other')
        taiwan = self.distinct_taiwan_event()
        current = self.configs.patch('testpilot', None, [
            ConfigChange(path='Alas.Emulator.PackageName', value='com.hkmanjuu.azurlane.gp'),
        ])
        self.assertEqual(taiwan, current['values']['Event']['Campaign']['Event'])
        other = self.configs.get('other')
        self.assertNotIn(taiwan, other['options']['Event.Campaign.Event'])

    def distinct_taiwan_event(self):
        # 当前活动可能全球同步；用独立候选验证地区隔离，不依赖活动档期。
        event = 'event_test_tw'
        field = self.configs.args['Event']['Campaign']['Event']
        field['option'] = [*field['option'], event]
        field['option_tw'] = [event]
        return event

    def test_archives_and_main_campaign_are_preserved(self):
        path, values = self.legacy()
        archive = self.configs.args['WarArchives']['Campaign']['Event']['option_cn'][-1]
        values['WarArchives']['Campaign']['Event'] = archive
        main = copy.deepcopy(values['Main']['Campaign'])
        path.write_text(json.dumps(values), encoding='utf-8')
        current = self.configs.get('testpilot')['values']
        self.assertEqual(archive, current['WarArchives']['Campaign']['Event'])
        self.assertEqual(main, current['Main']['Campaign'])

    def test_handover_event_selection_survives_api_and_runtime_reload(self):
        candidates = self.configs.args['OperationHandover']['Campaign']['Event']['option_cn']
        selections = [candidates[0], candidates[-1], 'war_archives_20230525_cn']
        for event in dict.fromkeys(selections):
            with self.subTest(event=event):
                self.legacy()
                current = self.configs.patch('testpilot', None, [
                    ConfigChange(path='OperationHandover.Campaign.Event', value=event),
                    ConfigChange(path='OperationHandover.Campaign.Name', value='T6'),
                ])
                saved = self.configs.read_json(self.configs.path('testpilot'))
                for values in (current['values'], ConfigUpdater().config_update(saved)):
                    self.assertEqual(event, values['OperationHandover']['Campaign']['Event'])
                    self.assertEqual('T6', values['OperationHandover']['Campaign']['Name'])

    def test_handover_can_select_archives_for_each_region(self):
        handover = self.configs.args['OperationHandover']['Campaign']['Event']
        archives = self.configs.args['WarArchives']['Campaign']['Event']
        for region in ('cn', 'en', 'jp', 'tw'):
            with self.subTest(region=region):
                self.assertTrue(set(archives[f'option_{region}']).issubset(handover[f'option_{region}']))

    def test_old_handover_main_stage_is_preserved_when_event_list_refreshes(self):
        path, values = self.legacy()
        values['OperationHandover']['Campaign'].update(Event='campaign_main', Name='12-4')
        path.write_text(json.dumps(values), encoding='utf-8')
        for current in (self.configs.get('testpilot')['values'], ConfigUpdater().config_update(values)):
            self.assertEqual('12-4', current['OperationHandover']['Campaign']['Name'])
            self.assertIn(current['OperationHandover']['Campaign']['Event'],
                          self.configs.args['OperationHandover']['Campaign']['Event']['option_cn'])


if __name__ == '__main__':
    unittest.main()
