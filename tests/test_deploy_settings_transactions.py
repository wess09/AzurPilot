"""临时部署文件的事务、并发与独立 Windows 部署兼容性回归。"""

import multiprocessing
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from deploy import config as deploy_config
from deploy.Windows import config as windows_config
from deploy.utils import poor_yaml_read
from module.runtime.config import DeployConfig as RuntimeDeployConfig
from module.runtime import deploy_settings
from module.runtime.setting import State


TEMPLATE = '''Repository: https://example.invalid/custom
Branch: master
PypiMirror: null
Theme: default
WebuiPort: 25548
Run: null
AllowedRedirectHosts: null
MaxRedirects: 2
'''


def increment_port(file, template, count):
    with patch.object(deploy_config, 'get_deploy_template', return_value=template), \
            patch.object(deploy_config.DeployConfig, 'show_config'):
        config = deploy_config.DeployConfig(file)
    for _ in range(count):
        with config.transaction() as values:
            values['WebuiPort'] += 1


class DeploySettingsTransactionsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.file = self.root / 'deploy.yaml'
        self.template = self.root / 'template.yaml'
        self.file.write_text(TEMPLATE)
        self.template.write_text(TEMPLATE)
        for context in (
            patch.object(deploy_config, 'get_deploy_template', return_value=str(self.template)),
            patch.object(windows_config, 'DEPLOY_TEMPLATE', str(self.template)),
            patch.object(deploy_config.DeployConfig, 'show_config'),
            patch.object(windows_config.DeployConfig, 'show_config'),
            patch.object(deploy_settings, 'is_demo_mode', return_value=False),
            patch.object(deploy_settings, 'alas_instance', return_value=['account_a', 'account_b']),
        ):
            context.start()
            self.addCleanup(context.stop)
        self.config = RuntimeDeployConfig(str(self.file))
        state_patch = patch.object(State, '_deploy_config_', self.config, create=True)
        state_patch.start()
        self.addCleanup(state_patch.stop)

    def assert_saved(self, **expected):
        saved = poor_yaml_read(str(self.file))
        for key, value in expected.items():
            self.assertEqual(saved[key], value)
            self.assertEqual(self.config.config[key], value)
            self.assertEqual(getattr(self.config, key), value)

    def race(self, first, second, config=None):
        """在首个写者落盘前暂停，让第二个写者实际尝试进入事务。"""
        config = config or self.config
        ready, release, attempted, finished = (threading.Event() for _ in range(4))
        write = config._write_config

        def paused_write():
            if not ready.is_set():
                ready.set()
                if not release.wait(5):
                    raise AssertionError('未释放首个写者')
            write()

        def run_second():
            attempted.set()
            try:
                return second()
            finally:
                finished.set()

        with patch.object(config, '_write_config', side_effect=paused_write), \
                ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(first)
            try:
                self.assertTrue(ready.wait(5))
                second_future = executor.submit(run_second)
                self.assertTrue(attempted.wait(5))
                self.assertFalse(finished.wait(0.1), '第二个写者不应越过尚未完成的事务')
            finally:
                release.set()
            return first_future.result(timeout=5), second_future.result(timeout=5)

    def test_concurrent_api_saves_preserve_both_settings(self):
        first, second = self.race(
            lambda: deploy_settings.save_deploy_settings({'Theme': 'dark'}),
            lambda: deploy_settings.save_deploy_settings({'WebuiPort': 30001}),
        )
        self.assertEqual(first, {'updated': ['Theme']})
        self.assertEqual(second, {'updated': ['WebuiPort']})
        self.assert_saved(Theme='dark', WebuiPort=30001)

    def test_concurrent_startup_additions_preserve_both_instances(self):
        self.race(lambda: deploy_settings.set_startup_run('account_a', True),
                  lambda: deploy_settings.set_startup_run('account_b', True))
        self.assert_saved(Run='["account_a","account_b"]')
        self.assertTrue(deploy_settings.get_startup_run('account_a')['enabled'])

    def test_startup_and_runtime_assignment_share_api_transaction(self):
        self.race(lambda: deploy_settings.set_startup_run('account_a', True),
                  lambda: setattr(self.config, 'Theme', 'dark'))
        self.assert_saved(Run='["account_a"]', Theme='dark')

    def test_separate_objects_merge_stale_write_with_new_values(self):
        other = deploy_config.DeployConfig(str(self.file))
        other.config['Theme'] = 'dark'
        self.config.WebuiPort = 30001
        other.write()
        self.config.read()
        self.assert_saved(Theme='dark', WebuiPort=30001)
        self.assertEqual(other.WebuiPort, 30001)

    def test_separate_objects_and_windows_writer_share_lock(self):
        other = windows_config.DeployConfig(str(self.file))
        self.race(lambda: self.config.update_config({'Theme': 'dark'}),
                  lambda: other.update_config({'WebuiPort': 30001}))
        self.config.read()
        self.assert_saved(Theme='dark', WebuiPort=30001)

    def test_read_migration_cannot_overwrite_concurrent_edit(self):
        self.file.write_text(TEMPLATE.replace('Theme: default\n', ''))
        self.race(self.config.read, lambda: setattr(self.config, 'WebuiPort', 30001))
        self.assert_saved(Theme='default', WebuiPort=30001)

    def test_failed_save_restores_disk_and_memory(self):
        for writer in (
            lambda: setattr(self.config, 'Theme', 'dark'),
            lambda: deploy_settings.save_deploy_settings({'Theme': 'dark', 'WebuiPort': 30001}),
            lambda: deploy_settings.set_startup_run('account_a', True),
        ):
            with self.subTest(writer=writer), patch.object(
                    self.config, '_write_config', side_effect=OSError('模拟落盘失败')):
                with self.assertRaises(OSError):
                    writer()
            self.assert_saved(Theme='default', WebuiPort=25548, Run=None)
        self.config.Theme = 'dark'
        self.assert_saved(Theme='dark')

    def test_failed_read_migration_restores_previous_memory(self):
        self.file.write_text(TEMPLATE.replace('Theme: default\n', '').replace('WebuiPort: 25548',
                                                                            'WebuiPort: 30001'))
        with patch.object(self.config, '_write_config', side_effect=OSError('模拟迁移失败')):
            with self.assertRaises(OSError):
                self.config.read()
        self.assertEqual(self.config.WebuiPort, 25548)
        self.assertEqual(self.config.config['WebuiPort'], 25548)
        self.assertNotIn('Theme', poor_yaml_read(str(self.file)))
        self.config.read()
        self.assert_saved(Theme='default', WebuiPort=30001)

    def test_failed_legacy_write_discards_dirty_memory_and_keeps_latest_disk(self):
        other = deploy_config.DeployConfig(str(self.file))
        other.config['Theme'] = 'dark'
        self.config.WebuiPort = 30001
        with patch.object(other, '_write_config', side_effect=OSError('模拟落盘失败')):
            with self.assertRaises(OSError):
                other.write()
        self.assertEqual(other.Theme, 'default')
        self.assertEqual(other.config['Theme'], 'default')
        self.assertEqual(other.WebuiPort, 30001)
        self.assert_saved(Theme='default', WebuiPort=30001)

    def test_runtime_repository_migration_does_not_reenter_auto_save(self):
        self.file.write_text(TEMPLATE.replace('https://example.invalid/custom',
                                             'https://gitee.com/LmeSzinc/AzurLaneAutoScript'))
        config = RuntimeDeployConfig(str(self.file))
        config.Theme = 'dark'
        self.assertEqual(poor_yaml_read(str(self.file))['Repository'],
                         deploy_config.GIT_OVER_CDN_REPOSITORY)
        self.assertIn(config.Repository, deploy_config.GIT_OVER_CDN_FALLBACK_REPOSITORIES)
        self.assertTrue(config.GitOverCdn)
        self.assertEqual(config.Theme, 'dark')

    def test_nested_transaction_and_attribute_assignment_commit_together(self):
        with patch.object(self.config, '_write_config', wraps=self.config._write_config) as write:
            with self.config.transaction() as values:
                values['WebuiPort'] = 30001
                with self.config.transaction() as nested:
                    self.assertIs(nested, values)
                    self.config.Theme = 'dark'
                self.assertEqual(poor_yaml_read(str(self.file))['Theme'], 'default')
            write.assert_called_once()
        self.assert_saved(Theme='dark', WebuiPort=30001)

    def test_nested_failure_rolls_back_outer_pending_values(self):
        with self.assertRaises(ValueError):
            with self.config.transaction() as values:
                values['WebuiPort'] = 30001
                with self.config.transaction():
                    self.config.Theme = 'dark'
                    raise ValueError('取消修改')
        self.assert_saved(Theme='default', WebuiPort=25548)

    def test_invalid_api_input_does_not_commit_valid_subset(self):
        with self.assertRaises(ValueError):
            deploy_settings.save_deploy_settings({'Theme': 'dark', 'WebuiPort': -1})
        self.assert_saved(Theme='default', WebuiPort=25548)

    def test_processes_serialize_read_modify_write(self):
        context = multiprocessing.get_context('spawn')
        processes = [context.Process(target=increment_port,
                                     args=(str(self.file), str(self.template), 5)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=15)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)
        self.config.read()
        self.assert_saved(WebuiPort=25558)

    def test_windows_deploy_tree_runs_without_module_package(self):
        # 仅复制部署层；隔离解释器不继承仓库或 site-packages 搜索路径。
        package = self.root / 'standalone'
        shutil.copytree('deploy', package / 'deploy', ignore=shutil.ignore_patterns('__pycache__'))
        script = '''
import importlib.abc
import sys
import types
sys.path.insert(0, sys.argv[1])
class NoModule(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'module' or fullname.startswith('module.'):
            raise AssertionError('独立部署器不得依赖 module 包')
sys.meta_path.insert(0, NoModule())
sys.modules['requests'] = types.ModuleType('requests')
from deploy.Windows.config import DeployConfig
config = DeployConfig(sys.argv[2])
with config.transaction() as values:
    values['Theme'] = 'dark'
    values['MaxRedirects'] = 0
    values['AllowedRedirectHosts'] = 'custom.example'
config.read()
assert config.Theme == 'dark'
assert config.MaxRedirects == 0
assert config.AllowedRedirectHosts == 'custom.example'
assert config.StunServers == '["stun:stun.l.google.com:19302"]'
'''
        result = subprocess.run([sys.executable, '-I', '-S', '-c', script,
                                 str(package), str(self.root / 'windows.yaml')],
                                cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
