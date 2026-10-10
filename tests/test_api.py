"""WebSocket API 的认证、配置事务及订阅回归测试。"""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from module.api.app import create_app
from module.api.config_service import ConfigService, ROOT
from module.api.protocol import ApiError, ConfigChange
from module.api.runtime_service import RuntimeService
from module.api.socket import Gateway, Session


def fixture(directory):
    """测试只操作临时实例，绝不加载用户的任务进程。"""
    root = Path(directory)
    (root / 'config').mkdir()
    (root / 'module/config/argument').mkdir(parents=True)
    (root / 'module/config/i18n').mkdir(parents=True)
    for relative in ['module/config/argument/args.json', 'module/config/argument/menu.json',
                     'module/config/i18n/zh-CN.json', 'module/config/i18n/en-US.json', 'config/template.json']:
        shutil.copyfile(ROOT / relative, root / relative)
    shutil.copyfile(ROOT / 'config/template.json', root / 'config/testpilot.json')
    return root


class ConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.configs = ConfigService(fixture(self.temp.name))

    def test_read_does_not_write_or_expose_unrelated_json(self):
        path = self.configs.path('testpilot')
        before = path.stat().st_mtime_ns
        (path.parent / 'private.json').write_text('{"token": "hidden"}')
        self.assertEqual(['testpilot'], self.configs.names())
        self.configs.get('testpilot')
        self.assertEqual(before, path.stat().st_mtime_ns)

    def test_instance_identity_is_preserved_and_hidden_from_editable_config(self):
        """内部身份随配置读取与保存保留，但不作为可编辑参数返回。"""
        path = self.configs.path('testpilot')
        data = self.configs.read_json(path)
        data['_stockInstance'] = 'test-identity'
        path.write_text(json.dumps(data), encoding='utf-8')
        before = path.read_bytes(), path.stat().st_mtime_ns
        values, revision = self.configs.read('testpilot')
        self.assertEqual('test-identity', values['_stockInstance'])
        self.assertNotIn('_stockInstance', self.configs.get('testpilot')['values'])
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.configs.patch('testpilot', revision, [ConfigChange(path='Main.Scheduler.Enable', value=True)])
        self.assertEqual('test-identity', self.configs.read_json(path)['_stockInstance'])

    def test_importable_lists_configs_in_import_folder(self):
        """可导入列表只来自导入目录；解不开的 JSON、符号链接、以及实例目录里的文件都不算。"""
        imports = self.configs.import_directory
        imports.mkdir()
        shutil.copyfile(self.configs.directory / 'testpilot.json', imports / 'shared.json')
        (imports / 'broken.json').write_text('{ not json', encoding='utf-8')
        (imports / 'link.json').symlink_to(imports / 'shared.json')

        names = [entry['name'] for entry in self.configs.importable()]
        self.assertIn('shared', names)
        self.assertNotIn('broken', names)     # 解不开的 JSON
        self.assertNotIn('link', names)       # 符号链接
        self.assertNotIn('testpilot', names)  # 实例目录里的不会被当作导入源

        # 文件名不合规的不能被列出来：read_import 会拒掉它，列出来就是一个选不了的选项
        shutil.copyfile(self.configs.directory / 'testpilot.json', imports / 'bad#name.json')
        self.assertNotIn('bad#name', [entry['name'] for entry in self.configs.importable()])
        # 导入创建：从导入目录取内容写到实例目录，导入源保持不动
        self.configs.create('imported', import_file='shared')
        self.assertIn('imported', self.configs.names())
        self.assertTrue((imports / 'shared.json').is_file())

    def test_importable_path_traversal_and_bad_json_are_rejected(self):
        imports = self.configs.import_directory
        imports.mkdir()
        (imports / 'broken.json').write_text('{ not json', encoding='utf-8')
        for name in ['../testpilot', 'a/b', 'a\\b', 'c:foo', 'a*b', '']:
            with self.subTest(name=name), self.assertRaises(ApiError):
                self.configs.read_import(name)
        with self.assertRaises(ApiError):
            self.configs.read_import('broken')

    def test_save_import_accepts_config_and_rejects_junk(self):
        """上传只收「有 Alas 段的 JSON」；坏 JSON、缺 Alas 段、非法名都不落盘。"""
        good = (self.configs.directory / 'testpilot.json').read_text(encoding='utf-8')
        self.configs.save_import('uploaded', good)
        self.assertIn('uploaded', [entry['name'] for entry in self.configs.importable()])

        bad = [('nobody', '{"Other": {}}'), ('notjson', '{ not json'), ('../escape', good),
               ('c:foo', good), ('template', good)]
        for name, content in bad:
            with self.subTest(name=name), self.assertRaises(ApiError):
                self.configs.save_import(name, content)
        self.assertFalse((self.configs.import_directory / 'nobody.json').exists())
        self.assertFalse((self.configs.import_directory / 'notjson.json').exists())
        self.assertFalse((self.configs.directory.parent / 'escape.json').exists())

    def test_schema_language_is_request_local(self):
        original = self.configs.schema()
        english = self.configs.schema('en-US')
        self.assertIn('serial', english['translations']['Emulator']['Serial']['name'].lower())
        self.assertEqual(original, self.configs.schema())
        with self.assertRaises(ApiError):
            self.configs.schema('../deploy')

    def test_rejects_path_traversal_and_reserved_names(self):
        for name in ['../template', 'a/b', 'a\\b', 'template', 'template.fpy', 'CON', 'c:foo', '']:
            with self.subTest(name=name), self.assertRaises(ApiError):
                self.configs.path(name, exists=False)

    def test_accepts_names_upstream_treats_as_configs(self):
        """数字开头、点号、空格都要能用 —— 这些名字在上游就是合法的配置文件名。"""
        # 真实落盘一个汉字实例名，确认创建、列举、读取都按原样往返。
        self.configs.create('测试实例')
        self.assertIn('测试实例', self.configs.names())
        self.assertEqual('测试实例', self.configs.get('测试实例')['instance'])
        for name in ['测试', 'alas测试', '测试-2', '测试.1', '1测试', '2ap', 'zz.v2', 'ap 2',
                     'テスト', 'テスト2', 'アズール', 'ひらがな', 'ｱｽﾞｰﾙ']:
            with self.subTest(name=name):
                self.configs.path(name, exists=False)

    def test_create_returns_the_normalized_name(self):
        """首尾空白与尾点会被归一化，返回的实例名要与落盘名一致 —— 客户端拿它做路由。"""
        for given in ['zztrim ', 'zztrim.', ' zztrim ']:
            with self.subTest(given=given):
                (self.configs.directory / 'zztrim.json').unlink(missing_ok=True)
                result = self.configs.create(given)
                self.assertEqual('zztrim', result['instance'])
                self.assertEqual('zztrim', self.configs.get('zztrim')['instance'])
                (self.configs.directory / 'zztrim.json').unlink(missing_ok=True)

    def test_still_rejects_unsafe_names(self):
        for name in ['-测试', '测试#1', '.隐藏', '测试/实例', ' ']:
            with self.subTest(name=name), self.assertRaises(ApiError):
                self.configs.path(name, exists=False)

    def test_patch_merges_fields_from_stale_revision(self):
        original = self.configs.get('testpilot')
        changed = self.configs.patch('testpilot', original['revision'], [ConfigChange(path='Alas.Emulator.Serial', value='127.0.0.1:5555')])
        self.assertEqual('127.0.0.1:5555', changed['values']['Alas']['Emulator']['Serial'])
        updated = self.configs.patch('testpilot', original['revision'], [ConfigChange(path='Main.Scheduler.Enable', value=True)])
        self.assertEqual('127.0.0.1:5555', updated['values']['Alas']['Emulator']['Serial'])
        self.assertTrue(updated['values']['Main']['Scheduler']['Enable'])
        latest = self.configs.patch('testpilot', original['revision'], [ConfigChange(path='Alas.Emulator.Serial', value='auto')])
        self.assertEqual('auto', latest['values']['Alas']['Emulator']['Serial'])

    def test_event_daily_last_stage_saves_text_from_legacy_zero(self):
        """旧数字断点可改成关卡名，刷新后保留大小写，输入 0 仍可重置。"""
        path = self.configs.path('testpilot')
        data = self.configs.read_json(path)
        tasks = ('EventA', 'EventB', 'EventC', 'EventD')
        for task in tasks:
            data[task]['EventDaily']['LastStage'] = 0
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

        for task in tasks:
            with self.subTest(task=task):
                original = self.configs.get('testpilot')
                self.assertEqual(0, original['values'][task]['EventDaily']['LastStage'])
                for stage in ('a3', 'D3', '0'):
                    changed = self.configs.patch('testpilot', '', [
                        ConfigChange(path=f'{task}.EventDaily.LastStage', value=stage)])
                    self.assertEqual(stage, changed['values'][task]['EventDaily']['LastStage'])
                    self.assertEqual(stage, self.configs.get('testpilot')['values'][task]['EventDaily']['LastStage'])
                    self.assertEqual(stage, self.configs.read_json(path)[task]['EventDaily']['LastStage'])

    def test_invalid_batch_does_not_partially_save(self):
        original = self.configs.get('testpilot')
        with self.assertRaises(ApiError):
            self.configs.patch('testpilot', original['revision'], [
                ConfigChange(path='Alas.Emulator.Serial', value='valid'),
                ConfigChange(path='Main.Scheduler.Enable', value='false')])
        self.assertEqual(original, self.configs.get('testpilot'))

    def test_numeric_range_and_multiselect(self):
        for groups in self.configs.args.values():
            for fields in groups.values():
                for field in fields.values():
                    if field.get('type') == 'multiselect':
                        self.assertIsInstance(field['value'], list)
        with self.assertRaises(ApiError):
            self.configs.validate('IslandBusiness.IslandBusiness.Batch1Shops', [999])
        for task, groups in self.configs.args.items():
            for group, fields in groups.items():
                for arg, field in fields.items():
                    if isinstance(field.get('validate'), list) and not field.get('display'):
                        with self.assertRaises(ApiError):
                            self.configs.validate(f'{task}.{group}.{arg}', field['validate'][1] + 1)
                        return
        self.fail('未找到数值范围参数')

    def test_hidden_and_fixed_fields_are_read_only(self):
        for path in ['Main.Scheduler.Command', 'Restart.Scheduler.Enable']:
            with self.subTest(path=path), self.assertRaises(ApiError) as context:
                self.configs.validate(path, True)
            self.assertEqual('READ_ONLY', context.exception.code)

    def test_display_fields_are_editable_within_options(self):
        for path in ['GemsFarming.Fleet.FleetOrder', 'ThreeOilLowCost.Fleet.FleetOrder']:
            with self.subTest(path=path):
                parts = self.configs.validate(path, 'fleet1_standby_fleet2_all')
                self.assertEqual(path.split('.'), parts)
                with self.assertRaises(ApiError) as context:
                    self.configs.validate(path, 'fleet1_mob_fleet2_boss')
                self.assertEqual('INVALID_PARAMS', context.exception.code)

    def test_storage_can_only_be_cleared(self):
        import json
        path = self.configs.path('testpilot')
        data = self.configs.get('testpilot')['values']
        data['Alas']['Storage']['Storage'] = {'retry': {'count': 3, 'enabled': False}}
        path.write_text(json.dumps(data), encoding='utf-8')
        original = self.configs.get('testpilot')
        for value in [{'count': 1}, [], '', None]:
            with self.subTest(value=value), self.assertRaises(ApiError):
                self.configs.patch('testpilot', original['revision'], [ConfigChange(path='Alas.Storage.Storage', value=value)])
        cleared = self.configs.patch('testpilot', original['revision'], [ConfigChange(path='Alas.Storage.Storage', value={})])
        self.assertEqual({}, cleared['values']['Alas']['Storage']['Storage'])
        self.assertEqual(original['values']['Alas']['Emulator'], cleared['values']['Alas']['Emulator'])
        self.assertEqual(cleared, self.configs.patch('testpilot', original['revision'], [ConfigChange(path='Alas.Storage.Storage', value={})]))

    def test_invalid_yaml_and_dates_do_not_replace_saved_config(self):
        original = self.configs.get('testpilot')
        invalid = [('Alas.Error.OnePushConfig', 'provider: ['),
                   ('Alas.Error.OnePushConfig', '- invalid'),
                   ('Main.Scheduler.NextRun', '2026-02-30 12:00:00'),
                   ('Main.Scheduler.NextRun', '2026-1-1 12:00:00'),
                   ('Main.Scheduler.NextRun', '')]
        for path, value in invalid:
            with self.subTest(path=path, value=value), self.assertRaises(ApiError) as context:
                self.configs.patch('testpilot', None, [ConfigChange(path=path, value=value)])
            self.assertEqual('INVALID_PARAMS', context.exception.code)
            self.assertEqual(original, self.configs.get('testpilot'))
        self.configs.patch('testpilot', None, [ConfigChange(path='Alas.Error.OnePushConfig', value='provider: null')])


    def test_retired_shop_options_are_visible_as_paused_and_saved_on_confirmation(self):
        """只读预览不写文件，确认启用时保存已迁移的普通商店配置。"""
        path = self.configs.path('testpilot')
        data = self.configs.read_json(path)
        data['EventShop']['Scheduler']['Enable'] = True
        data['EventShop']['ShopAdvanced'] = {'Mode': 'advanced', 'Script': 'old'}
        data['EventShop']['EventShop']['CustomFilter'] = 'Cube:5 > Oil:2'
        path.write_text(json.dumps(data), encoding='utf-8')
        raw = path.read_bytes()
        preview = self.configs.get('testpilot')['values']['EventShop']
        self.assertFalse(preview['Scheduler']['Enable'])
        self.assertNotIn('ShopAdvanced', preview)
        self.assertEqual('Cube > Oil', preview['EventShop']['CustomFilter'])
        self.assertEqual(raw, path.read_bytes())
        self.configs.patch('testpilot', None, [ConfigChange(path='EventShop.Scheduler.Enable', value=True)])
        saved = self.configs.read_json(path)['EventShop']
        self.assertTrue(saved['Scheduler']['Enable'])
        self.assertNotIn('ShopAdvanced', saved)
        self.assertTrue(self.configs.get('testpilot')['values']['EventShop']['Scheduler']['Enable'])

    def test_duplicate_creation_and_recoverable_deletion(self):
        created = self.configs.create('second', 'testpilot')
        with self.assertRaises(ApiError):
            self.configs.create('second')
        self.configs.delete('second', created['revision'])
        self.assertFalse(self.configs.path('second', exists=False).exists())
        self.assertEqual(1, len(list((self.configs.directory / 'backup').glob('second-*.json'))))


class SocketApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(root=fixture(self.temp.name), password='test-secret', manage_runtime=False, mount_mcp=False)
        self.client = TestClient(self.app)
        self.counter = 0

    def call(self, ws, method, params=None):
        self.counter += 1
        request_id = str(self.counter)
        ws.send_json({'v': 1, 'type': 'request', 'id': request_id, 'method': method, 'params': params or {}})
        while True:
            result = ws.receive_json()
            if result.get('id') == request_id:
                return result

    def login(self, ws):
        self.assertEqual('session', ws.receive_json()['topic'])
        self.assertTrue(self.call(ws, 'auth.login', {'password': 'test-secret'})['ok'])

    def test_authentication_guards_all_business_methods(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.assertTrue(ws.receive_json()['data']['authRequired'])
            response = self.call(ws, 'instances.list')
            self.assertEqual('UNAUTHORIZED', response['error']['code'])
            self.assertTrue(self.call(ws, 'auth.login', {'password': 'test-secret'})['ok'])
            self.assertEqual('testpilot', self.call(ws, 'instances.list')['result'][0]['name'])

    def test_large_calculator_file_keeps_other_message_limits(self):
        """舰船文件可超过 1 MiB，其余方法仍受原限制约束。"""
        import base64
        rows = [{'name': '扩展文件舰船' * 8, 'level': 100, 'source': 'x' * 200}] * 3000
        content = base64.b64encode(json.dumps({'ships': rows}, ensure_ascii=False).encode()).decode()
        self.assertGreater(len(content), 1024 * 1024)
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            result = self.call(ws, 'mind.import', {'instance': 'testpilot', 'filename': 'ships.json', 'content': content})
            self.assertTrue(result['ok'], result)
            self.assertEqual(len(result['result']['ships']), 3000)
            result = self.call(ws, 'config.get', {'instance': 'testpilot', 'padding': content})
            self.assertEqual(result['error']['code'], 'INVALID_REQUEST')
            self.assertIn('1 MiB', result['error']['message'])

    def test_update_methods_require_auth_and_validate_pagination(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            for method in ('updater.status', 'updater.commits', 'updater.fetch', 'updater.apply', 'updater.cancel'):
                self.assertEqual('UNAUTHORIZED', self.call(ws, method)['error']['code'])
            self.assertTrue(self.call(ws, 'auth.login', {'password': 'test-secret'})['ok'])
            self.assertEqual('INVALID_PARAMS', self.call(ws, 'updater.commits', {'limit': 101})['error']['code'])
            with patch('module.api.update_service.update_service') as updates:
                updates.commits.return_value = {'entries': [], 'total': 0, 'hasMore': False,
                                                'localHead': None, 'upstreamHead': None}
                response = self.call(ws, 'updater.commits', {'offset': 50, 'limit': 50})
                self.assertTrue(response['ok'])
                updates.commits.assert_called_once_with(50, 50)

    def test_untrusted_origin_is_rejected_before_upgrade(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/v1/ws', headers={'origin': 'https://evil.example'}):
                pass

    def test_local_connection_skips_password(self):
        """本机浏览器与启动器内嵌窗口直接进入，不再要求输入密码。"""
        client = TestClient(self.app, client=('127.0.0.1', 55555))
        with client.websocket_connect('/api/v1/ws', headers={'host': '127.0.0.1:22267',
                                                             'origin': 'http://127.0.0.1:22267'}) as ws:
            self.assertFalse(ws.receive_json()['data']['authRequired'])
            self.assertEqual('testpilot', self.call(ws, 'instances.list')['result'][0]['name'])

    def test_remote_connection_still_requires_password(self):
        """局域网与远程访问入口仍受密码保护。"""
        client = TestClient(self.app, client=('203.0.113.7', 55555))
        with client.websocket_connect('/api/v1/ws', headers={'host': 'app.hk1.azurlane.cloud'}) as ws:
            self.assertTrue(ws.receive_json()['data']['authRequired'])
            self.assertEqual('UNAUTHORIZED', self.call(ws, 'instances.list')['error']['code'])

    def test_tunnel_forwarded_request_keeps_password(self):
        """远程访问隧道同样来自回环地址，靠标记头避免被当成免密的本机直连。"""
        client = TestClient(self.app, client=('127.0.0.1', 55555))
        with client.websocket_connect('/api/v1/ws', headers={'host': '127.0.0.1:22267',
                                                             'x-azurpilot-remote-access': '1'}) as ws:
            self.assertTrue(ws.receive_json()['data']['authRequired'])
            self.assertEqual('UNAUTHORIZED', self.call(ws, 'instances.list')['error']['code'])

    def test_missing_parameter_returns_correlated_error_and_connection_survives(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            error = self.call(ws, 'config.get')
            self.assertEqual('INVALID_PARAMS', error['error']['code'])
            self.assertTrue(self.call(ws, 'system.ping')['ok'])

    def test_unknown_method_does_not_dispatch_python_attributes(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            self.assertEqual('METHOD_NOT_FOUND', self.call(ws, '__dict__')['error']['code'])

    def test_session_ids_cannot_repeat_mutations(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            payload = {'v': 1, 'type': 'request', 'id': 'unique', 'method': 'instances.create', 'params': {'name': 'newpilot'}}
            ws.send_json(payload)
            self.assertTrue(ws.receive_json()['ok'])
            ws.send_json(payload)
            self.assertEqual('DUPLICATE_REQUEST', ws.receive_json()['error']['code'])

    def test_field_updates_over_real_websocket_accept_stale_or_missing_revision(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            config = self.call(ws, 'config.get', {'instance': 'testpilot'})['result']
            params = {'instance': 'testpilot', 'revision': config['revision'], 'changes': [{'path': 'Alas.Emulator.Serial', 'value': '5555'}]}
            self.assertTrue(self.call(ws, 'config.patch', params)['ok'])
            self.assertTrue(self.call(ws, 'config.patch', params)['ok'])
            del params['revision']
            params['changes'] = [{'path': 'Main.Scheduler.Enable', 'value': True}]
            merged = self.call(ws, 'config.patch', params)
            self.assertTrue(merged['ok'])
            self.assertEqual('5555', merged['result']['values']['Alas']['Emulator']['Serial'])


    def test_overview_and_scheduler_controls_accept_instance_identity(self):
        """启停实际完成后，总览响应不能因内部身份字段而失败。"""
        from module.runtime.process_manager import ProcessManager

        path = Path(self.temp.name) / 'config/testpilot.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['_stockInstance'] = 'test-identity'
        data['Main']['Scheduler']['Enable'] = True
        path.write_text(json.dumps(data), encoding='utf-8')
        before = path.read_bytes()
        manager = SimpleNamespace(alive=False, state=2, current_task=None)

        def start(*args, **kwargs):
            manager.alive, manager.state = True, 1

        def stop():
            manager.alive, manager.state = False, 2
            return True

        manager.start = Mock(side_effect=start)
        manager.stop_by_user = Mock(side_effect=stop)
        stop_event = object()
        with patch.object(ProcessManager, 'get_manager', return_value=manager), \
                patch.dict(ProcessManager._processes, {'testpilot': manager}, clear=True), \
                patch.object(RuntimeService, '_record_running_now'), \
                patch('module.runtime.updater.updater', SimpleNamespace(event=stop_event)), \
                self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            for method, status in [('overview.get', 'stopped'), ('scheduler.start', 'running'),
                                   ('scheduler.stop', 'stopped')]:
                with self.subTest(method=method):
                    response = self.call(ws, method, {'instance': 'testpilot'})
                    self.assertTrue(response['ok'], response)
                    self.assertEqual(status, response['result']['status'])
                    tasks = [task['name'] for task in response['result']['tasks']]
                    self.assertIn('Main', tasks)
                    self.assertNotIn('_stockInstance', tasks)
        manager.start.assert_called_once_with('alas', ev=stop_event)
        manager.stop_by_user.assert_called_once_with()
        self.assertEqual(before, path.read_bytes())

    def test_subscribe_sends_scoped_snapshot_with_instance_identity(self):
        path = Path(self.temp.name) / 'config/testpilot.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['_stockInstance'] = 'test-identity'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            self.assertTrue(self.call(ws, 'events.subscribe', {'instance': 'testpilot', 'topics': ['overview']})['ok'])
            event = ws.receive_json()
            self.assertEqual('overview', event['topic'])
            self.assertEqual('testpilot', event['data']['instance'])
            self.assertNotIn('_stockInstance', [task['name'] for task in event['data']['tasks']])
            self.assertTrue(self.call(ws, 'events.subscribe', {'topics': []})['ok'])

    def test_log_arrival_pushes_websocket_event_without_polling(self):
        from rich.text import Text
        from module.runtime.log_hub import hub
        from module.runtime.process_manager import ProcessManager

        manager = SimpleNamespace(renderables=[])
        with patch.dict(ProcessManager._processes, {'testpilot': manager}, clear=True), \
                self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            self.assertTrue(self.call(ws, 'events.subscribe', {
                'instance': 'testpilot', 'topics': ['logs'],
            })['ok'])
            manager.renderables.append(Text('INFO 到达即推送'))
            hub.publish('testpilot')

            for _ in range(2):
                event = ws.receive_json()
                if event.get('topic') == 'logs' and event['data']['entries']:
                    break
            self.assertEqual(['INFO 到达即推送'], [entry['text'] for entry in event['data']['entries']])

    def test_demo_mode_rejects_mutation(self):
        with patch.dict('os.environ', {'DEMO': '1'}), self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            self.assertEqual('READ_ONLY', self.call(ws, 'instances.create', {'name': 'newpilot'})['error']['code'])

    def test_settings_get_exposes_remote_access_status(self):
        """远程访问地址原本只写进服务端日志，界面要能拿到它。"""
        class Provider:
            @staticmethod
            def get_connection_state():
                return 'direct_p2p'

            @staticmethod
            def get_entry_point():
                return 'https://remurl.example/p2p/abc'

            @staticmethod
            def get_error():
                return ''

        with patch('module.runtime.remote_access._provider', Provider):
            with self.client.websocket_connect('/api/v1/ws') as ws:
                self.login(ws)
                remote = self.call(ws, 'settings.get')['result']['remote']
        self.assertEqual('direct_p2p', remote['state'])
        self.assertEqual('https://remurl.example/p2p/abc', remote['address'])
        self.assertEqual('', remote['error'])
        self.assertIn('enabled', remote)

    def test_remote_access_status_empty_address_is_blank(self):
        """服务未运行时地址是空串，前端据此隐藏复制按钮。"""
        class Provider:
            @staticmethod
            def get_connection_state():
                return 'stopped'

            @staticmethod
            def get_entry_point():
                return None

            @staticmethod
            def get_error():
                return 'ssh_not_found'

        with patch('module.runtime.remote_access._provider', Provider):
            with self.client.websocket_connect('/api/v1/ws') as ws:
                self.login(ws)
                remote = self.call(ws, 'settings.get')['result']['remote']
        self.assertEqual('stopped', remote['state'])
        self.assertEqual('', remote['address'])
        self.assertEqual('ssh_not_found', remote['error'])

    def test_health_and_missing_frontend(self):
        self.assertEqual({'status': 'ok', 'protocolVersion': 1}, self.client.get('/healthz').json())
        self.assertEqual(503, self.client.get('/').status_code)

    def test_slow_client_queue_is_bounded(self):
        from unittest.mock import AsyncMock

        async def check():
            ws = SimpleNamespace(close=AsyncMock())
            session = Session(Gateway(None, ''), ws)
            for _ in range(32):
                await session.enqueue({})
            with self.assertRaises(WebSocketDisconnect):
                await session.enqueue({})
            ws.close.assert_awaited_once()
        asyncio.run(check())


class RuntimeMetadataTests(unittest.TestCase):
    def test_game_region_uses_package_instead_of_server_checker_setting(self):
        """开服检测关闭或选择国服检测区，都不能决定设备实际运行的游戏地区。"""
        emulator = {'ServerName': 'disabled', 'PackageName': 'auto'}
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        configs = SimpleNamespace(directory=Path(temporary.name), names=lambda: ['test'],
                                  read=lambda _: ({'Alas': {'Emulator': emulator}}, ''))
        runtime = RuntimeService(configs)
        cases = [
            ('auto', 'disabled', None), ('', 'disabled', None),
            ('com.bilibili.azurlane', 'disabled', 'cn'),
            ('com.bilibili.blhx.huawei', 'cn_channel-0', 'cn'),
            ('com.YoStarEN.AzurLane', 'disabled', 'en'),
            ('com.YoStarJP.AzurLane', 'cn_android-0', 'jp'),
            ('com.hkmanjuu.azurlane.gp', 'disabled', 'tw'),
            ('com.hkmanjuu.azurlane.gp.mc', 'disabled', 'tw'),
        ]
        with patch('module.api.runtime_service.ProcessManager._processes', {}):
            for package, checker, expected in cases:
                with self.subTest(package=package, checker=checker):
                    emulator.update(PackageName=package, ServerName=checker)
                    instance = runtime.instances()[0]
                    self.assertEqual(expected, instance['region'])
                    self.assertEqual(checker, instance['server'])


class LogCursorTests(unittest.TestCase):
    def test_start_passes_update_stop_event_to_worker(self):
        runtime = RuntimeService(SimpleNamespace(path=lambda _: None))
        manager = SimpleNamespace(alive=False)
        manager.start = Mock(side_effect=lambda *args, **kwargs: setattr(manager, 'alive', True))
        stop_event = object()
        with patch.object(runtime, 'manager', return_value=manager), patch.object(
            runtime, 'overview', return_value={}
        ), patch('module.runtime.updater.updater', SimpleNamespace(event=stop_event)):
            runtime.start('testpilot')
        manager.start.assert_called_once_with('alas', ev=stop_event)

    def test_log_trim_and_clear_do_not_duplicate_entries(self):
        configs = SimpleNamespace(path=lambda _: None)
        runtime = RuntimeService(configs)
        from rich.text import Text
        entries = [Text(f'INFO 日志 {i}') for i in range(5)]
        manager = SimpleNamespace(renderables=entries)
        with patch('module.api.runtime_service.ProcessManager._processes', {'test': manager}):
            first = runtime.logs('test')
            self.assertEqual(5, first['cursor'])
            manager.renderables = entries[2:] + [Text('ERROR 新日志')]
            second = runtime.logs('test', first['cursor'])
            self.assertEqual(1, len(second['entries']))
            self.assertEqual('ERROR', second['entries'][0]['level'])
            self.assertEqual([], runtime.logs('test', second['cursor'])['entries'])


class ProducerCadenceTests(unittest.IsolatedAsyncioTestCase):
    """日志按到达事件即时推送，重主题继续按各自节奏采样。"""

    async def test_stock_events_wake_immediately_and_unsubscribe_when_leaving(self):
        from module.api.protocol import SubscribeParams
        subscribed, delivered, unsubscribed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        callbacks, updates = [], []
        def subscribe(listener):
            callbacks.append(listener)
            subscribed.set()
            return unsubscribed.set
        service = SimpleNamespace(subscribe=subscribe)
        session = Session(SimpleNamespace(router=SimpleNamespace(stock_exchange=service)), ws=None, local=True)
        session.subscription = SubscribeParams(instance='testpilot', topics=['stock'])
        async def event(topic, data):
            self.assertEqual('stock', topic)
            updates.append(data)
            if data.get('revision') == 42:
                delivered.set()
        session.event = event
        task = asyncio.create_task(session.stock_producer())
        try:
            session.stock_changed.set()
            await asyncio.wait_for(subscribed.wait(), 1)
            await asyncio.to_thread(callbacks[0], {'instance': 'another', 'revision': 41})
            await asyncio.to_thread(callbacks[0], {'revision': 42, 'online': True})
            await asyncio.wait_for(delivered.wait(), 1)
            self.assertEqual({'revision': 42, 'online': True, 'instance': 'testpilot'}, updates[-1])
            self.assertFalse(any(value.get('revision') == 41 for value in updates))
            session.subscription = SubscribeParams(topics=[])
            session.stock_changed.set()
            await asyncio.wait_for(unsubscribed.wait(), 1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_heavy_topics_keep_independent_cadence(self):
        counts = {'overview': 0, 'instances': 0}
        runtime = SimpleNamespace(
            overview=lambda instance: counts.__setitem__('overview', counts['overview'] + 1) or {'instance': instance},
            instances=lambda: counts.__setitem__('instances', counts['instances'] + 1) or [],
        )
        session = Session(SimpleNamespace(router=SimpleNamespace(runtime=runtime), workers=asyncio.Semaphore(1)), ws=None, local=True)
        session.subscription = SimpleNamespace(topics=['overview', 'instances'], instance='testpilot')
        session.event = AsyncMock()
        task = asyncio.create_task(session.producer())
        await asyncio.sleep(2.2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertGreater(counts['overview'], counts['instances'])
        self.assertGreater(counts['instances'], 0, '重主题也必须被轮询到')

    async def test_logs_wake_immediately_and_new_entries_are_sent_one_by_one(self):
        from module.api.protocol import SubscribeParams
        from module.runtime.log_hub import LogHub

        calls = 0

        def logs(instance, after):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {'instance': instance, 'cursor': 1, 'reset': False,
                        'entries': [{'id': 1, 'level': 'INFO', 'text': '历史'}]}
            return {'instance': instance, 'cursor': 3, 'reset': False, 'entries': [
                {'id': 2, 'level': 'INFO', 'text': '新增一'},
                {'id': 3, 'level': 'INFO', 'text': '新增二'},
            ]}

        runtime = SimpleNamespace(logs=logs)
        session = Session(SimpleNamespace(router=SimpleNamespace(runtime=runtime), workers=asyncio.Semaphore(1)), ws=None, local=True)
        session.subscription = SubscribeParams(instance='testpilot', topics=['logs'])
        hub = LogHub()
        with patch('module.runtime.log_hub.hub', hub):
            task = asyncio.create_task(session.log_producer())
            session.logs_changed.set()
            first = await asyncio.wait_for(session.queue.get(), timeout=.5)
            self.assertEqual(['历史'], [entry['text'] for entry in first['data']['entries']])

            hub.publish('testpilot')
            second = await asyncio.wait_for(session.queue.get(), timeout=.5)
            third = await asyncio.wait_for(session.queue.get(), timeout=.5)
            self.assertEqual(['新增一'], [entry['text'] for entry in second['data']['entries']])
            self.assertEqual(['新增二'], [entry['text'] for entry in third['data']['entries']])
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(set(), hub.listeners)


if __name__ == '__main__':
    unittest.main()
