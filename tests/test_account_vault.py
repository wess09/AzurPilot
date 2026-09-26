"""账号安全边界及设备快照回归；只使用临时文件和合成账号。"""
import base64
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.account_service import AccountService
from module.api.config_service import ConfigService
from module.api.protocol import AccountParams, ApiError, InstanceParams
from module.runtime.account_device import AccountDevice, BASES, DATABASE, FILES, PLAYER_PREFS, SDK_PREFS
from module.runtime.account_vault import AccountVault, SecretKey, sensitive_operation
from tests.test_api import fixture

PASSWORD = 'temporary-Test-Password-59!'
NEW_PASSWORD = 'another-Strong-Passphrase-62!'


def snapshot():
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('CREATE TABLE users(uid TEXT, uname TEXT, access_key TEXT, pwd TEXT)')
        db.execute("INSERT INTO users VALUES ('synthetic-uid', '合成账号', 'synthetic-secret-token', 'synthetic-secret-password')")
        db.commit()
        blob = db.serialize()
    return {DATABASE: base64.b64encode(blob).decode(), SDK_PREFS: base64.b64encode(b'<map/>').decode(),
            PLAYER_PREFS: base64.b64encode(b'<map><string name="user.arg1">synthetic-secret-token</string></map>').decode()}


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = AccountVault(self.root)
        self.vault.create('testpilot', PASSWORD)

    def test_all_project_files_contain_no_plaintext_or_key(self):
        row, key, data = self.vault.authenticate('testpilot', PASSWORD)
        data['profiles'] = [{'id': 'profile', 'label': '私密账号名称', 'files': snapshot()}]
        data['selected'] = 'profile'
        self.vault.save('testpilot', row[0], key, data, True)
        for path in self.root.rglob('*'):
            if path.is_file():
                raw = path.read_bytes()
                for secret in (PASSWORD.encode(), key.value, b'synthetic-secret-token', '私密账号名称'.encode(), b'synthetic-uid'):
                    self.assertNotIn(secret, raw)
        self.assertEqual(256, len(self.vault.record('testpilot')[0]))
        copied = AccountVault(self.root)
        with self.assertRaisesRegex(ApiError, '重新解锁'):
            copied.startup_key('testpilot')
        self.assertEqual(data, copied.authenticate('testpilot', PASSWORD)[2])

    def test_wrong_password_tamper_and_throttling(self):
        with self.assertRaises(ApiError) as error:
            self.vault.authenticate('testpilot', NEW_PASSWORD)
        self.assertEqual('VAULT_AUTH_FAILED', error.exception.code)
        with self.assertRaises(ApiError) as error:
            self.vault.authenticate('testpilot', PASSWORD)
        self.assertEqual('RATE_LIMITED', error.exception.code)
        self.vault.failures.clear()
        with closing(sqlite3.connect(self.vault.path('testpilot'))) as db, db:
            db.execute('UPDATE vault SET enabled=1')
        with self.assertRaises(ApiError):
            self.vault.authenticate('testpilot', PASSWORD)

    def test_disabled_never_touches_device_and_paths_reject_escape(self):
        device = Mock()
        self.vault.restore('testpilot', device)
        device.restore.assert_not_called()
        for name in ('../other', 'test/other', 'CON'):
            with self.assertRaises(ApiError):
                self.vault.path(name)
        self.vault.keys.clear()
        self.assertIsNone(self.vault.startup_key('testpilot'))

    def test_sensitive_traceback_discards_locals_and_key_repr(self):
        from rich.console import Console
        from rich.traceback import Traceback
        import io

        @sensitive_operation
        def fail():
            password = PASSWORD
            token = 'synthetic-secret-token'
            raise RuntimeError(password + token)

        try:
            fail()
        except ApiError as error:
            output = io.StringIO()
            Console(file=output, width=120).print(Traceback.from_exception(type(error), error,
                error.__traceback__.tb_next, show_locals=True))
            text = output.getvalue()
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn('synthetic-secret-token', text)
        self.assertNotIn('unsafe-key-bytes', repr(SecretKey(b'unsafe-key-bytes')))

    def test_tpm_unlock_only_with_original_hardware_and_authenticated_blob(self):
        row, key, data = self.vault.authenticate('testpilot', PASSWORD)
        data.update(profiles=[{'id': 'profile'}], selected='profile')
        self.vault.save('testpilot', row[0], key, data, True, b'wrapped-hardware-key')
        cold = AccountVault(self.root)
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.return_value = key.value
            self.assertEqual(key.value, cold.startup_key('testpilot').value)
        cold.keys.clear()
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.side_effect = ApiError('TPM_UNAVAILABLE', '绑定失效')
            with self.assertRaises(ApiError):
                cold.startup_key('testpilot')
        self.assertFalse(cold.path('testpilot').exists())
        self.assertTrue(cold.status('testpilot')['destroyed'])
        with self.assertRaises(ApiError) as error:
            cold.authenticate('testpilot', PASSWORD)
        self.assertEqual('VAULT_DESTROYED', error.exception.code)

    def bind_fixture(self, enabled=True):
        row, key, data = self.vault.authenticate('testpilot', PASSWORD)
        data.update(profiles=[{'id': 'profile', 'files': snapshot()}], selected='profile')
        self.vault.save('testpilot', row[0], key, data, enabled, b'wrapped-hardware-key')
        return key

    def test_tpm_failure_destroys_salt_sidecars_and_cached_key_before_device_write(self):
        self.bind_fixture()
        cached = self.vault.keys['testpilot']
        path = self.vault.path('testpilot')
        for suffix in ('-journal', '-wal', '-shm'):
            # 空边文件不会被 SQLite 误判为待恢复事务，确保走到 TPM 故障分支。
            path.with_name(path.name + suffix).write_bytes(b'')
        neighbor = path.parent / 'unrelated.txt'
        neighbor.write_bytes(b'keep-neighbor')
        device = Mock()
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.side_effect = ApiError('TPM_UNAVAILABLE', '临时故障')
            with self.assertRaises(ApiError) as error:
                self.vault.restore('testpilot', device)
            self.assertEqual('VAULT_DESTROYED', error.exception.code)
            tpm.return_value.unwrap.assert_called_once()
        device.restore.assert_not_called()
        self.assertEqual(bytes(32), cached.value)
        self.assertNotIn('testpilot', self.vault.keys)
        for suffix in ('', '-journal', '-wal', '-shm'):
            self.assertFalse(path.with_name(path.name + suffix).exists())
        self.assertEqual(b'keep-neighbor', neighbor.read_bytes())
        self.assertTrue(self.vault.marker('testpilot').exists())
        cold = AccountVault(self.root)
        with self.assertRaises(ApiError) as error:
            cold.startup_key('testpilot')
        self.assertEqual('VAULT_DESTROYED', error.exception.code)
        cold.create('testpilot', NEW_PASSWORD)
        self.assertFalse(cold.status('testpilot')['destroyed'])
        self.assertEqual([], cold.authenticate('testpilot', NEW_PASSWORD)[2]['profiles'])

    def test_disabled_tpm_binding_is_still_verified_with_correct_password(self):
        self.bind_fixture(enabled=False)
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.side_effect = ApiError('TPM_DEVICE_CHANGED', '已更换设备')
            with self.assertRaises(ApiError) as error:
                self.vault.authenticate('testpilot', PASSWORD)
        self.assertEqual('VAULT_DESTROYED', error.exception.code)
        self.assertTrue(self.vault.status('testpilot')['destroyed'])

    def test_valid_tpm_wrong_password_does_not_destroy_data(self):
        key = self.bind_fixture()
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.return_value = key.value
            with self.assertRaises(ApiError) as error:
                self.vault.authenticate('testpilot', NEW_PASSWORD)
        self.assertEqual('VAULT_AUTH_FAILED', error.exception.code)
        self.assertTrue(self.vault.path('testpilot').exists())
        self.assertFalse(self.vault.marker('testpilot').exists())

    def test_tpm_decrypt_authentication_failure_also_destroys_data(self):
        self.bind_fixture()
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.return_value = bytes(32)
            self.assertTrue(self.vault.status('testpilot')['destroyed'])
        self.assertFalse(self.vault.path('testpilot').exists())

    def test_failed_wipe_remains_blocked_and_retries_without_password_fallback(self):
        self.bind_fixture()
        path = self.vault.path('testpilot')
        sidecar = path.with_name(path.name + '-wal')
        sidecar.write_bytes(b'synthetic-sensitive-sidecar')
        wipe = self.vault.wipe_file
        def fail_main(target):
            if target == path:
                raise PermissionError('模拟文件占用')
            return wipe(target)
        with patch.object(self.vault, 'wipe_file', side_effect=fail_main), patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.side_effect = ApiError('TPM_UNAVAILABLE', '验证失败')
            with self.assertRaises(ApiError) as error:
                self.vault.startup_key('testpilot')
            self.assertEqual('VAULT_DESTROY_FAILED', error.exception.code)
            self.assertTrue(self.vault.marker('testpilot').exists())
            self.assertFalse(sidecar.exists())
            tpm.reset_mock()
            with self.assertRaises(ApiError):
                self.vault.authenticate('testpilot', PASSWORD)
            tpm.return_value.unwrap.assert_not_called()
        self.assertTrue(self.vault.status('testpilot')['destroyed'])
        self.assertFalse(path.exists())

    def test_wipe_overwrites_and_truncates_before_unlink(self):
        path = self.vault.path('testpilot')
        original_unlink = Path.unlink
        wiped = []
        def inspect_unlink(target, *args, **kwargs):
            if target == path:
                wiped.append(target.read_bytes())
            return original_unlink(target, *args, **kwargs)
        with patch.object(Path, 'unlink', inspect_unlink):
            self.vault.destroy('testpilot')
        self.assertEqual([b''], wiped)

    def test_disk_permission_failure_also_revokes_current_process(self):
        self.bind_fixture()
        cached = self.vault.keys['testpilot']
        original_open = Path.open
        def refuse_marker(target, *args, **kwargs):
            if target == self.vault.marker('testpilot'):
                raise PermissionError('模拟标记写入失败')
            return original_open(target, *args, **kwargs)
        with patch.object(Path, 'open', refuse_marker), patch.object(self.vault, 'wipe_file', side_effect=PermissionError()):
            with self.assertRaises(ApiError) as error:
                self.vault.destroy('testpilot')
            self.assertEqual('VAULT_DESTROY_FAILED', error.exception.code)
            with patch('module.runtime.account_tpm.TpmProtector') as tpm:
                with self.assertRaises(ApiError):
                    self.vault.authenticate('testpilot', PASSWORD)
                tpm.assert_not_called()
        self.assertEqual(bytes(32), cached.value)


class TpmCapabilityTests(unittest.TestCase):
    def test_probe_cache_and_failures_do_not_access_account_vault(self):
        from module.runtime.account_tpm import TpmProtector
        import subprocess
        for output, expected in ((SimpleNamespace(returncode=0, stdout=b'ready'), True),
                                 (SimpleNamespace(returncode=1, stdout=b'ready'), False),
                                 (SimpleNamespace(returncode=0, stdout=b'other'), False)):
            TpmProtector.available.cache_clear()
            with patch('module.runtime.account_tpm.os.name', 'nt'), \
                    patch('module.runtime.account_tpm.subprocess.run', return_value=output) as run:
                self.assertEqual(expected, TpmProtector.available())
                self.assertEqual(expected, TpmProtector.available())
                run.assert_called_once()
        TpmProtector.available.cache_clear()
        with patch('module.runtime.account_tpm.os.name', 'nt'), \
                patch('module.runtime.account_tpm.subprocess.run', side_effect=subprocess.TimeoutExpired('probe', 30)):
            self.assertFalse(TpmProtector.available())
        TpmProtector.available.cache_clear()
        with patch('module.runtime.account_tpm.os.name', 'posix'), \
                patch('module.runtime.account_tpm.subprocess.run') as run:
            self.assertFalse(TpmProtector.available())
            run.assert_not_called()
        TpmProtector.available.cache_clear()


class AccountApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.configs = ConfigService(fixture(self.temp.name))
        self.service = AccountService(self.configs)
        capability = patch('module.runtime.account_tpm.TpmProtector.available', return_value=False)
        capability.start()
        self.addCleanup(capability.stop)
        self.local_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.local_temp.cleanup)
        from module.runtime.account_local import LocalProtector
        key_path = patch.object(LocalProtector, 'key_directory', return_value=Path(self.local_temp.name) / 'keys')
        key_path.start()
        self.addCleanup(key_path.stop)
        self.idle = patch('module.api.account_service.ensure_idle')
        self.idle.start()
        self.addCleanup(self.idle.stop)

    def manage(self, action, **kwargs):
        return self.service.manage(AccountParams(instance='testpilot', action=action, password=PASSWORD, **kwargs))

    def test_local_bind_password_change_cold_start_and_explicit_unbind(self):
        self.manage('create')
        device = Mock()
        device.capture.return_value = (snapshot(), [{'uid': 'synthetic-uid', 'name': '合成账号'}])
        with patch('module.api.account_service.device_for', return_value=device):
            self.manage('capture')
        self.manage('enable', enabled=True)
        result = self.manage('bind_local')
        self.assertTrue(result['local_bound'])
        self.assertFalse(result['tpm_bound'])
        self.assertIsNotNone(AccountVault(self.configs.root).startup_key('testpilot'))
        with self.assertRaises(ApiError) as error:
            self.manage('bind_tpm')
        self.assertEqual('AUTOUNLOCK_BOUND', error.exception.code)
        self.manage('password', new_password=NEW_PASSWORD)
        self.assertIsNotNone(AccountVault(self.configs.root).startup_key('testpilot'))
        result = self.service.manage(AccountParams(instance='testpilot', action='unbind_local', password=NEW_PASSWORD))
        self.assertFalse(result['local_bound'])
        self.assertFalse(list(Path(self.local_temp.name).rglob('*.key')))
        with self.assertRaises(ApiError) as error:
            AccountVault(self.configs.root).startup_key('testpilot')
        self.assertEqual('VAULT_LOCKED', error.exception.code)

    def test_local_initial_failure_preserves_password_vault(self):
        self.manage('create')
        with patch('module.api.account_service.LocalProtector.wrap', side_effect=ApiError('LOCAL_KEY_UNAVAILABLE', '合成失败')):
            with self.assertRaises(ApiError) as error:
                self.manage('bind_local')
        self.assertEqual('LOCAL_KEY_UNAVAILABLE', error.exception.code)
        self.assertTrue(self.service.vault.path('testpilot').exists())
        self.assertFalse(self.service.vault.status('testpilot')['local_bound'])
        self.manage('list')

    def test_tpm_failure_during_final_status_never_returns_sensitive_list(self):
        self.manage('create')
        row, key, data = self.service.vault.authenticate('testpilot', PASSWORD)
        data.update(profiles=[{'id': 'profile', 'label': '私密账号', 'users': [{'uid': 'synthetic'}]}])
        self.service.vault.save('testpilot', row[0], key, data, False, b'wrapped-hardware-key')
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.unwrap.side_effect = [bytes(key.value), ApiError('TPM_UNAVAILABLE', '临时故障')]
            with self.assertRaises(ApiError) as error:
                self.manage('list')
        self.assertEqual('VAULT_DESTROYED', error.exception.code)
        self.assertFalse(self.service.vault.path('testpilot').exists())
        self.assertNotIn('testpilot', self.service.vault.keys)

    def test_password_required_before_identity_and_every_sensitive_action(self):
        self.manage('create')
        device = Mock()
        device.capture.return_value = (snapshot(), [{'uid': 'synthetic-uid', 'name': '合成账号'}])
        with patch('module.api.account_service.device_for', return_value=device):
            response = self.manage('capture', label='私密名称')
            self.assertNotIn('profiles', response)
            self.assertNotIn('profiles', self.service.status(InstanceParams(instance='testpilot')))
            listing = self.manage('list')
            profile = listing['profiles'][0]['id']
            self.manage('select', profile=profile)
            device.restore.assert_called_once_with(snapshot())
            device.launch.assert_called_once()
        with self.assertRaises(ApiError):
            self.service.manage(AccountParams(instance='testpilot', action='list'))
        self.service.vault.failures.clear()
        self.manage('enable', enabled=True)
        self.manage('password', new_password=NEW_PASSWORD)
        self.assertEqual(1, len(self.service.vault.authenticate('testpilot', NEW_PASSWORD)[2]['profiles']))
        self.assertNotIn('synthetic-secret-token', json.dumps(listing))

    def test_reused_password_missing_profile_and_running_instance(self):
        with self.assertRaises(ApiError) as error:
            self.service.manage(AccountParams(instance='testpilot', action='create', password=PASSWORD), PASSWORD)
        self.assertEqual('PASSWORD_REUSED', error.exception.code)
        self.manage('create')
        with self.assertRaises(ApiError):
            self.manage('enable', enabled=True)
        with patch('module.api.account_service.ensure_idle', side_effect=ApiError('INSTANCE_RUNNING', '运行中')):
            with self.assertRaises(ApiError):
                self.manage('capture')

    def test_password_fields_never_appear_in_model_repr(self):
        params = AccountParams(instance='testpilot', action='password', password=PASSWORD, new_password=NEW_PASSWORD)
        self.assertNotIn(PASSWORD, repr(params))
        self.assertNotIn(NEW_PASSWORD, repr(params))

    def test_host_change_during_first_binding_destroys_existing_vault(self):
        from module.runtime.account_tpm import TpmProtector
        self.manage('create')
        with patch.object(TpmProtector, 'available', return_value=True), \
                patch.object(TpmProtector, 'host_identity', side_effect=['old-host', 'new-host']), \
                patch.object(TpmProtector, 'execute', return_value=bytes(256)) as execute:
            with self.assertRaises(ApiError) as error:
                self.manage('bind_tpm')
        self.assertEqual('VAULT_DESTROYED', error.exception.code)
        self.assertEqual(1, execute.call_count)
        self.assertTrue(self.service.status(InstanceParams(instance='testpilot'))['destroyed'])

    def test_unavailable_tpm_rejects_binding_without_destroying_vault(self):
        self.manage('create')
        with patch('module.runtime.account_tpm.TpmProtector.wrap') as wrap:
            with self.assertRaises(ApiError) as error:
                self.manage('bind_tpm')
        self.assertEqual('TPM_UNAVAILABLE', error.exception.code)
        wrap.assert_not_called()
        self.assertTrue(self.service.vault.path('testpilot').exists())
        self.assertFalse(self.service.status(InstanceParams(instance='testpilot'))['tpm_available'])
        self.manage('list')

    def test_failed_first_binding_does_not_keep_password_recovery(self):
        self.manage('create')
        with patch('module.runtime.account_tpm.TpmProtector') as tpm:
            tpm.return_value.wrap.side_effect = ApiError('TPM_UNAVAILABLE', '硬件不可用')
            with self.assertRaises(ApiError) as error:
                self.manage('bind_tpm')
        self.assertEqual('VAULT_DESTROYED', error.exception.code)
        self.assertFalse(self.service.vault.path('testpilot').exists())


class DeviceTests(unittest.TestCase):
    def test_database_only_capture_and_restore_leave_preferences_untouched(self):
        device = AccountDevice.__new__(AccountDevice)
        device.stop = Mock()
        device.resolve_base = Mock(return_value=BASES[1])
        device.command = Mock(return_value=b'0')
        blob = base64.b64decode(snapshot()[DATABASE])
        device.read = Mock(return_value=blob)
        files, users = device.capture()
        self.assertEqual({DATABASE}, set(files))
        self.assertTrue(users)
        staged = {}
        def command(script, data=None):
            if data is not None:
                staged[script.removeprefix('cat > ')] = data
            elif script.startswith('cat '):
                return staged[script.removeprefix('cat ')]
            elif script.startswith('stat '):
                return b'1000:1000'
            return b''
        device.command = Mock(side_effect=command)
        device.restore(files)
        scripts = '\n'.join(call.args[0] for call in device.command.call_args_list)
        self.assertNotIn('shared_prefs', scripts)
        self.assertIn('mv ', scripts)
        self.assertIn(f'{BASES[1]}/{DATABASE}', scripts)
        device.read.assert_called_with(DATABASE)

    def test_capture_only_account_files_and_player_keys(self):
        device = AccountDevice.__new__(AccountDevice)
        device.stop = Mock()
        device.command = Mock(side_effect=lambda script: b'0' if script.startswith('if test -s ') else b'1')
        device.resolve_base = Mock(return_value=BASES[0])
        blobs = {name: base64.b64decode(value) for name, value in snapshot().items()}
        blobs[PLAYER_PREFS] = b'<map><string name="user.arg1">secret</string><int name="fps_limit" value="60"/></map>'
        device.read = Mock(side_effect=lambda name: blobs[name])
        files, users = device.capture()
        self.assertEqual(set(FILES), set(files))
        self.assertNotIn(b'fps_limit', base64.b64decode(files[PLAYER_PREFS]))
        self.assertEqual('synthetic-uid', users[0]['uid'])
        device.stop.assert_called_once()

    def test_common_private_directories_and_missing_files(self):
        device = AccountDevice.__new__(AccountDevice)
        for index, base in enumerate(BASES):
            with self.subTest(base=base):
                device.command = Mock(return_value=b'11111111' if index == 0 else b'10111111')
                device.base = device.resolve_base()
                self.assertEqual(base, device.base)
                probe = device.command.call_args.args[0]
                self.assertLess(probe.index(BASES[0]), probe.index(BASES[1]))
                for candidate in BASES:
                    for name in FILES:
                        self.assertIn(f'test -f {candidate}/{name}', probe)
                device.read(DATABASE)
                device.command.assert_called_with(f'cat {base}/{DATABASE}')
        device.serial = '127.0.0.1:16384'
        device.command = Mock(return_value=b'10111011')
        with self.assertRaises(ApiError) as error:
            device.resolve_base()
        self.assertEqual('ACCOUNT_DATA_NOT_FOUND', error.exception.code)
        self.assertIn(DATABASE, error.exception.message)
        self.assertIn(device.serial, error.exception.message)
        device.command = Mock(return_value=b'11000000')
        self.assertEqual(BASES[0], device.resolve_base())
        device.command = Mock(return_value=b'00000000')
        with self.assertRaisesRegex(ApiError, '目录不存在或不可访问'):
            device.resolve_base()
        device.command = Mock(return_value=b'unexpected-output')
        with self.assertRaises(ApiError) as error:
            device.resolve_base()
        self.assertEqual('ACCOUNT_DEVICE_FAILED', error.exception.code)

    def test_restore_uses_selected_directory_for_entire_transaction(self):
        import xml.etree.ElementTree as ET
        files = snapshot()
        blobs = {name: base64.b64decode(value) for name, value in files.items()}
        expected_player = ET.tostring(ET.fromstring(blobs[PLAYER_PREFS]), encoding='utf-8', xml_declaration=True)
        for base in BASES:
            with self.subTest(base=base):
                device = AccountDevice.__new__(AccountDevice)
                device.stop = Mock()
                device.resolve_base = Mock(return_value=base)
                device.read = Mock(side_effect=[blobs[DATABASE], blobs[SDK_PREFS], expected_player])
                staged = {}
                def command(script, data=None):
                    if data is not None:
                        staged[script.removeprefix('cat > ')] = data
                    elif script.startswith('cat '):
                        return staged[script.removeprefix('cat ')]
                    elif script.startswith('if test -f '):
                        return blobs[PLAYER_PREFS]
                    elif script.startswith('stat '):
                        return b'1000:1000'
                    return b''
                device.command = Mock(side_effect=command)
                device.restore(files)
                scripts = '\n'.join(call.args[0] for call in device.command.call_args_list)
                other_base = next(candidate for candidate in BASES if candidate != base)
                self.assertNotIn(other_base, scripts)
                self.assertIn('mv ', scripts)
                self.assertIn(f'{base}/{DATABASE}', scripts)
                self.assertIn(f'restorecon {base}/databases/users.db', scripts)
                self.assertIn(f'rm -f {base}/{DATABASE}-wal', scripts)
                device.stop.assert_called_once()

    def test_root_and_transport_errors_never_echo_secret(self):
        with patch('module.runtime.account_device.subprocess.run', return_value=SimpleNamespace(returncode=1, stdout=b'', stderr=b'secret-account')):
            with self.assertRaises(ApiError) as error:
                AccountDevice('127.0.0.1:16384', 'adb')
        self.assertNotIn('secret-account', str(error.exception))

    def test_su_command_and_uid_variants_are_negotiated_only_by_readonly_probe(self):
        for successful_mode in ('command', 'uid', 'root'):
            with self.subTest(mode=successful_mode):
                def run(args, **kwargs):
                    command = args[-1]
                    if command.startswith('sh -c '):
                        uid = b'2000'
                    elif ((successful_mode == 'command' and command.startswith('su -c '))
                          or (successful_mode == 'uid' and command.startswith('su 0 sh -c '))
                          or (successful_mode == 'root' and command.startswith('su root sh -c '))):
                        uid = b'0'
                    else:
                        return SimpleNamespace(returncode=1, stdout=b'', stderr=b'synthetic-sensitive-error')
                    return SimpleNamespace(returncode=0, stdout=base64.b64encode(uid), stderr=b'')
                with patch('module.runtime.account_device.subprocess.run', side_effect=run) as execute:
                    device = AccountDevice('127.0.0.1:16384', 'adb')
                    self.assertEqual(successful_mode, device.use_su)
                    self.assertTrue(all(b'id -u' in base64.b64decode(call.kwargs['input']) for call in execute.call_args_list))
                    execute.reset_mock()
                    execute.side_effect = None
                    execute.return_value = SimpleNamespace(returncode=1, stdout=b'', stderr=b'synthetic-sensitive-error')
                    with self.assertRaises(ApiError):
                        device.command('cat > /synthetic/file', b'synthetic-secret')
                    execute.assert_called_once()

    def test_nonempty_account_journal_reports_busy_instead_of_adb_failure(self):
        device = AccountDevice.__new__(AccountDevice)
        device.stop = Mock()
        device.resolve_base = Mock(return_value=BASES[0])
        device.command = Mock(return_value=b'1')
        device.read = Mock()
        with self.assertRaises(ApiError) as error:
            device.capture()
        self.assertEqual('ACCOUNT_DATABASE_BUSY', error.exception.code)
        device.read.assert_not_called()

    def test_transport_preserves_binary_and_remote_exit_code(self):
        blob = bytes(range(256))
        device = AccountDevice.__new__(AccountDevice)
        device.adb, device.serial, device.use_su = 'adb', '127.0.0.1:16384', False
        with patch('module.runtime.account_device.subprocess.run') as run:
            run.return_value = SimpleNamespace(returncode=0, stdout=base64.b64encode(blob), stderr=b'')
            self.assertEqual(blob, device.command('cat > /synthetic/file', blob))
            args, kwargs = run.call_args
            self.assertEqual(['shell', '-T'], args[0][3:5])
            self.assertNotIn(base64.b64encode(blob).decode(), ' '.join(args[0]))
            self.assertEqual(base64.b64encode(blob) + b'\n', kwargs['input'])
            run.return_value = SimpleNamespace(returncode=1, stdout=b'', stderr=b'synthetic-secret-token')
            with self.assertRaises(ApiError) as error:
                device.command('false')
            self.assertEqual('ACCOUNT_DEVICE_FAILED', error.exception.code)
            self.assertNotIn('synthetic-secret-token', str(error.exception))

    def test_long_shell_script_is_sent_via_stdin_instead_of_su_argument(self):
        device = AccountDevice.__new__(AccountDevice)
        device.adb, device.serial, device.use_su = 'adb', '127.0.0.1:16416', 'command'
        script = 'true #' + 'x' * 7000
        with patch('module.runtime.account_device.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'', stderr=b'')) as execute:
            device.command(script)
        args, kwargs = execute.call_args
        self.assertLess(len(args[0][-1]), 200)
        self.assertIn(script.encode(), base64.b64decode(kwargs['input']))


if __name__ == '__main__':
    unittest.main()
