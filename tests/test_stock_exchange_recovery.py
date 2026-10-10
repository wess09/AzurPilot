"""交易数据损坏隔离与显式重建回归；不访问游戏或真实交易账户。"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.api.stock_exchange_identity import binding_key
from module.api.stock_exchange_service import StockExchangeService
from module.runtime.game_data import GameDataProtector
from module.scheduler.action_history import ActionPointChain
from module.scheduler.store import ProgramStore
from tests.test_api import fixture


class StockRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture(Path(self.temp.name).resolve())
        self.configs = ConfigService(self.root)
        self.configs.create('other')
        self.service = StockExchangeService(self.configs)
        self.service.start = Mock()
        self.addCleanup(self.service.close)
        self.store = ProgramStore(self.root / 'config')
        self.now = datetime.now()
        self.identities = {}
        for name in ('testpilot', 'other'):
            self.identities[name] = self.service.status(name)['instanceId']
            identity, key = self.service._identity(name)
            self.service.bindings[name] = {'playerId': len(self.identities), 'username': name,
                                          'bindingKey': binding_key(identity, key), 'uploadToken': 'a' * 64,
                                          'url': 'https://stock.nanoda.work'}
            self.service.sessions[name] = name + '-fixture-session'
            self.store.observe(name, 'ActionPoint', {'Total': 8000}, self.now.isoformat(), 'fixture')
        self.service._save()

    def test_unregistered_identity_never_blocks_normal_config_operations(self):
        path = self.configs.path('testpilot')
        data = json.loads(path.read_bytes())
        data['_stockInstance'] = 'unregistered-fixture'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ApiError):
            self.service.status('testpilot')
        self.assertEqual(['other', 'testpilot'], sorted(self.configs.names()))
        self.configs.get('testpilot')
        exported = self.configs.export('testpilot')
        self.assertNotIn('_stockInstance', exported)
        self.configs.create('copied', source='testpilot')
        self.configs.save_import('fixture', json.dumps(exported))
        self.configs.create('imported', import_file='fixture')
        self.configs.patch('testpilot', '', [ConfigChange(path='Alas.Emulator.Serial', value='fixture-emulator')])
        self.store.save_persistent('testpilot', {'variables': {'fixture': 1}})
        self.store.observe('testpilot', 'ActionPoint', {'Total': 8100}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
        self.assertEqual(8100, self.store.observations('testpilot')['ActionPoint']['Total'])
        self.configs.delete('testpilot', self.configs.read('testpilot')[1])
        self.configs.create('testpilot')

    def test_missing_registry_does_not_block_copy_delete_or_resource_updates(self):
        self.service.protection.state_path.unlink()
        self.configs.export('testpilot')
        self.configs.create('copied', source='testpilot')
        self.store.observe('testpilot', 'Oil', {'Value': 5000}, self.now.isoformat(), 'fixture')
        self.store.observe('testpilot', 'ActionPoint', {'Total': 8100}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
        self.assertEqual(8100, self.store.observations('testpilot')['ActionPoint']['Total'])
        self.configs.delete('other', self.configs.read('other')[1])
        self.configs.create('other')
        with self.assertRaises(ApiError):
            self.service.status('testpilot')

    def test_broken_player_data_never_blocks_webui_startup(self):
        from starlette.testclient import TestClient
        from module.api.app import create_app
        self.service.path.write_bytes(b'{broken-bindings')
        with TestClient(create_app(root=self.root, password='', manage_runtime=False, mount_mcp=False)) as client:
            self.assertEqual(200, client.get('/healthz').status_code)

    def test_tampered_history_blocks_stock_but_not_program_or_resource_writes(self):
        with closing(sqlite3.connect(self.store.history.path('testpilot'))) as db, db:
            db.execute('UPDATE action_point_chain SET total=9999')
        document = self.store.get('testpilot')
        self.store.update('testpilot', document['revision'], mode='native')
        self.store.observe('testpilot', 'ActionPoint', {'Total': 8100}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
        self.assertEqual(8100, self.store.observations('testpilot')['ActionPoint']['Total'])
        with self.assertRaises(ApiError):
            self.service.status('testpilot')

    def test_checkpoint_failure_does_not_rollback_regular_observation(self):
        for method in ('prepare', 'finish'):
            with self.subTest(method=method), patch.object(ActionPointChain, method, side_effect=OSError('隔离写入失败')):
                self.store.observe('other', 'ActionPoint', {'Total': 8100}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
            self.assertEqual(8100, self.store.observations('other')['ActionPoint']['Total'])

    def test_damaged_history_table_never_blocks_normal_resource_collection(self):
        with closing(sqlite3.connect(self.store.history.path('testpilot'))) as db, db:
            db.execute('DROP TABLE action_point_history')
            db.execute('CREATE TABLE action_point_history (seq INTEGER PRIMARY KEY)')
        self.store.observe('testpilot', 'ActionPoint', {'Total': 8100}, (self.now + timedelta(seconds=1)).isoformat(), 'fixture')
        self.assertEqual(8100, self.store.observations('testpilot')['ActionPoint']['Total'])
        with self.assertRaises(ApiError):
            self.service.status('testpilot')

    def test_new_instance_observations_remain_usable_on_first_stock_visit(self):
        self.configs.create('new-instance')
        self.store.observe('new-instance', 'ActionPoint', {'Total': 8200}, self.now.isoformat(), 'fixture')
        self.assertEqual(8200, self.service.status('new-instance')['snapshot']['actionPoints'])

    def test_stock_identity_replacement_never_discards_scheduler_runtime(self):
        self.store.save_persistent('testpilot', {'variables': {'fixture': 1}})
        original = self.store.get('testpilot')
        self.configs.path('testpilot').write_bytes(self.configs.path('other').read_bytes())
        status = self.service.status('testpilot')
        self.assertNotEqual(self.identities['testpilot'], status['instanceId'])
        self.assertFalse(status['bound'])
        self.assertIsNone(status['snapshot'])
        self.assertEqual(original, self.store.get('testpilot'))
        self.assertEqual(1, self.store.persistent('testpilot')['variables']['fixture'])
        self.assertEqual(8000, self.store.observations('testpilot')['ActionPoint']['Total'])

    def test_fresh_resource_collection_survives_unavailable_stock_storage(self):
        self.configs.create('new-instance')
        with patch.object(GameDataProtector, 'resolve', side_effect=ApiError('STOCK_STORAGE_DAMAGED', '隔离存储故障')):
            self.store.observe('new-instance', 'ActionPoint', {'Total': 8200}, self.now.isoformat(), 'fixture')
        self.assertEqual(8200, self.store.observations('new-instance')['ActionPoint']['Total'])

    def test_instance_rebuild_keeps_other_account_and_normal_runtime_data(self):
        self.store.save_persistent('testpilot', {'variables': {'fixture': 1}})
        original_program = self.store.get('testpilot')
        original_observations = self.store.observations('testpilot')
        path = self.service.protection.file_path('identities/' + self.identities['testpilot'] + '.json')
        path.write_bytes(b'{broken-identity')
        plan = self.service.rebuild('testpilot')
        self.assertEqual({'instance': 'testpilot', 'scope': 'instance', 'affectedInstances': ['testpilot'], 'rebuilt': False}, plan)
        self.assertEqual(b'{broken-identity', path.read_bytes())
        result = self.service.rebuild('testpilot', confirm=True, scope=plan['scope'])
        self.assertTrue(result['rebuilt'])
        status = self.service.status('testpilot')
        self.assertNotEqual(self.identities['testpilot'], status['instanceId'])
        self.assertFalse(status['bound'])
        self.assertFalse(status['authenticated'])
        self.assertIsNone(status['snapshot'])
        self.assertEqual(self.identities['other'], self.service.status('other')['instanceId'])
        self.assertTrue(self.service.status('other')['bound'])
        self.assertTrue(self.service.status('other')['authenticated'])
        self.assertEqual(original_program, self.store.get('testpilot'))
        self.assertEqual(original_observations, self.store.observations('testpilot'))
        self.assertEqual(1, self.store.persistent('testpilot')['variables']['fixture'])
        backups = list((self.root / 'config' / 'backup').glob('stock-rebuild-*'))
        self.assertEqual(1, len(backups))
        self.assertEqual(b'{broken-identity', (backups[0] / 'stock-exchange' / path.relative_to(self.service.protection.directory)).read_bytes())
        self.store.observe('testpilot', 'ActionPoint', {'Total': 8200}, (self.now + timedelta(seconds=2)).isoformat(), 'fixture')
        self.assertEqual(8200, self.service.status('testpilot')['snapshot']['actionPoints'])

    def test_shared_registry_rebuild_requires_correct_scope_and_resets_all_accounts(self):
        self.service.protection.state_path.write_bytes(b'{broken-registry')
        plan = self.service.rebuild('testpilot')
        self.assertEqual('all', plan['scope'])
        self.assertEqual(['other', 'testpilot'], plan['affectedInstances'])
        with self.assertRaises(ApiError) as failure:
            self.service.rebuild('testpilot', confirm=True, scope='instance')
        self.assertEqual('STOCK_REBUILD_SCOPE_CHANGED', failure.exception.code)
        self.assertEqual(b'{broken-registry', self.service.protection.state_path.read_bytes())
        self.service.rebuild('testpilot', confirm=True, scope='all')
        for name, previous in self.identities.items():
            status = self.service.status(name)
            self.assertNotEqual(previous, status['instanceId'])
            self.assertFalse(status['bound'])
            self.assertFalse(status['authenticated'])
            self.assertEqual(8000, self.store.observations(name)['ActionPoint']['Total'])


if __name__ == '__main__':
    unittest.main()
