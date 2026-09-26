"""本机软件密钥回归；Windows DPAPI / Linux 权限均只操作临时合成保险库。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from module.api.protocol import ApiError
from module.runtime.account_local import LocalProtector, dpapi
from module.runtime.account_vault import AccountVault

PASSWORD = 'Local-Test-Passphrase-82!'


class LocalVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / 'project'
        self.root.mkdir()
        self.keys = self.directory / 'private-keys'
        self.key_path = patch.object(LocalProtector, 'key_directory', return_value=self.keys)
        self.key_path.start()
        self.addCleanup(self.key_path.stop)
        self.vault = AccountVault(self.root)
        self.vault.create('localtest', PASSWORD)
        self.protector = LocalProtector(self.root, 'localtest')

    def bind(self):
        row, key, data = self.vault.authenticate('localtest', PASSWORD)
        data.update(profiles=[{'id': 'synthetic', 'label': '合成私密账号'}], selected='synthetic')
        binding = self.protector.wrap(key.value)
        self.vault.save('localtest', row[0], key, data, True, binding)
        return key, binding

    def test_cold_automatic_unlock_and_no_secrets_in_project(self):
        key, binding = self.bind()
        self.assertEqual(key.value, AccountVault(self.root).startup_key('localtest').value)
        state = self.vault.status('localtest')
        self.assertTrue(state['local_bound'])
        self.assertFalse(state['tpm_bound'])
        for path in self.root.rglob('*'):
            if path.is_file():
                for secret in (key.value, PASSWORD.encode(), '合成私密账号'.encode()):
                    self.assertNotIn(secret, path.read_bytes())
        self.assertFalse(self.keys.is_relative_to(self.root))
        self.assertEqual(1, len(list(self.keys.glob('*.key'))))
        self.assertEqual(key.value, self.protector.unwrap(binding))

    def test_separate_process_unlocks_without_instance_password(self):
        self.bind()
        script = '''
import json, sys
from pathlib import Path
from module.runtime.account_local import LocalProtector
from module.runtime.account_vault import AccountVault
paths = json.loads(sys.stdin.read())
LocalProtector.key_directory = staticmethod(lambda: Path(paths['keys']))
key = AccountVault(Path(paths['root'])).startup_key('localtest')
assert key is not None and len(key.value) == 32
key.clear()
print('unlocked')
'''
        result = subprocess.run([sys.executable, '-c', script],
                                input=json.dumps({'keys': str(self.keys), 'root': str(self.root)}).encode(),
                                capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode)
        self.assertTrue(result.stdout.strip().endswith(b'unlocked'))

    def test_missing_key_blocks_even_cached_startup_but_password_can_recover(self):
        key, binding = self.bind()
        cold = AccountVault(self.root)
        cached = cold.startup_key('localtest')
        self.protector.remove(binding)
        with self.assertRaises(ApiError) as error:
            cold.startup_key('localtest')
        self.assertEqual('LOCAL_KEY_UNAVAILABLE', error.exception.code)
        self.assertEqual(bytes(32), cached.value)
        self.assertNotIn('localtest', cold.keys)
        self.assertEqual(key.value, cold.authenticate('localtest', PASSWORD)[1].value)
        self.assertTrue(cold.path('localtest').exists())

    def test_changed_host_destroys_vault_and_external_key(self):
        self.bind()
        with patch.object(LocalProtector, 'host_identity', return_value='different-host'):
            self.assertTrue(self.vault.status('localtest')['destroyed'])
        self.assertFalse(self.vault.path('localtest').exists())
        self.assertFalse(list(self.keys.glob('*.key')))
        with self.assertRaises(ApiError):
            self.vault.authenticate('localtest', PASSWORD)

    def test_project_copy_cannot_use_original_automatic_binding(self):
        self.bind()
        copied = self.directory / 'copied-project'
        shutil.copytree(self.root, copied)
        with self.assertRaises(ApiError):
            AccountVault(copied).startup_key('localtest')
        self.assertTrue((copied / 'config/localtest/config.db').exists())
        self.assertTrue(self.vault.path('localtest').exists())

    def test_rewrap_after_password_change_reuses_external_key(self):
        key, binding = self.bind()
        row, _, data = self.vault.authenticate('localtest', PASSWORD)
        salt = os.urandom(256)
        replacement = self.vault.derive(PASSWORD + '-new', salt)
        new_binding = self.protector.wrap(replacement.value, previous=binding)
        self.assertEqual(json.loads(binding)['id'], json.loads(new_binding)['id'])
        self.vault.save('localtest', salt, replacement, data, True, new_binding)
        self.assertEqual(replacement.value, AccountVault(self.root).startup_key('localtest').value)
        self.assertNotEqual(key.value, replacement.value)
        self.assertEqual(1, len(list(self.keys.glob('*.key'))))

    def test_bad_external_key_or_sealed_payload_blocks_without_destroying_password_vault(self):
        _, binding = self.bind()
        path = self.protector.path(json.loads(binding)['id'])
        path.write_bytes(b'bad-key')
        with self.assertRaises(ApiError):
            AccountVault(self.root).startup_key('localtest')
        self.assertTrue(self.vault.path('localtest').exists())
        self.assertTrue(self.vault.authenticate('localtest', PASSWORD)[2]['profiles'])

    def test_key_location_inside_project_and_invalid_id_are_rejected(self):
        with patch.object(LocalProtector, 'key_directory', return_value=self.root / 'hidden'):
            with self.assertRaises(ApiError):
                self.protector.wrap(os.urandom(32))
        with self.assertRaises(ValueError):
            self.protector.path('../escape')
        self.assertFalse((self.root / 'hidden').exists())

    @unittest.skipIf(os.name == 'nt', 'Linux 用户与权限边界')
    def test_linux_700_600_and_permission_change_blocks_cached_unlock(self):
        _, binding = self.bind()
        self.assertEqual(0o700, self.keys.stat().st_mode & 0o777)
        path = self.protector.path(json.loads(binding)['id'])
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.vault.startup_key('localtest')
        path.chmod(0o644)
        with self.assertRaises(ApiError):
            self.vault.startup_key('localtest')
        self.assertNotIn('localtest', self.vault.keys)

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI 用户保护')
    def test_windows_key_file_is_dpapi_protected(self):
        _, binding = self.bind()
        path = self.protector.path(json.loads(binding)['id'])
        protected = path.read_bytes()
        secret = self.protector.load(json.loads(binding)['id'])
        self.assertNotIn(secret, protected)
        self.assertNotEqual(32, len(protected))
        self.assertEqual(secret, dpapi(protected, decrypt=True))


if __name__ == '__main__':
    unittest.main()
