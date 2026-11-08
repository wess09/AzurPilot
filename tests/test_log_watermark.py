"""来源标记使用临时 Git 仓库与日志，覆盖失败隔离和原有保存流程。"""

import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alas import AzurLaneAutoScript
from module.base import log_watermark
from module.config.config_updater import ConfigUpdater
from module.config.config_generated import GeneratedConfig


class TestSourceWatermark(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'config').mkdir()
        self.git('init', '-q', '-b', 'test-branch')
        (self.root / 'source.py').write_text('original\n', encoding='utf-8')
        self.git('add', 'source.py')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'initial')
        self.git('remote', 'add', 'origin', 'https://example.invalid/team/project.git')
        self.commit = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return subprocess.run(
            ['git', *args], cwd=self.root, check=True, capture_output=True,
            text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        ).stdout.strip()

    def collect(self):
        return log_watermark.collect_source_watermark(self.root)

    def test_actual_repository_branch_and_head_override_configured_values(self):
        (self.root / 'config/deploy.yaml').write_text(
            "Repository: 'https://example.invalid/configured.git'\nBranch: 'configured'\n",
            encoding='utf-8',
        )
        result = self.collect()
        self.assertIn('源: https://example.invalid/team/project.git', result)
        self.assertIn('分支: test-branch', result)
        self.assertIn(f'提交: {self.commit[:12]}', result)
        self.assertIn('本地修改: 无', result)
        self.assertNotIn('configured', result)

    def test_detects_both_unstaged_and_staged_changes(self):
        (self.root / 'source.py').write_text('changed\n', encoding='utf-8')
        self.assertIn('本地修改: 有', self.collect())
        self.git('add', 'source.py')
        self.assertIn('本地修改: 有', self.collect())

    def test_untracked_installer_and_settings_do_not_mark_code_as_modified(self):
        (self.root / 'config/instance.json').write_text('{}', encoding='utf-8')
        (self.root / 'installer.exe').write_bytes(b'installer')
        self.assertIn('本地修改: 无', self.collect())

    def test_detached_head_is_not_reported_as_the_configured_branch(self):
        self.git('checkout', '--detach', '-q', self.commit)
        self.assertIn('分支: 分离 HEAD', self.collect())

    def test_remote_credentials_query_and_fragment_are_removed(self):
        self.git('remote', 'set-url', 'origin',
                 'https://user:private-password@example.invalid/team/project.git?token=private-token#private-fragment')
        result = self.collect()
        self.assertIn('源: https://example.invalid/team/project.git', result)
        self.assertNotIn('private-', result)
        self.assertNotIn('user:', result)

    def test_missing_origin_uses_explicitly_labelled_configuration(self):
        self.git('remote', 'remove', 'origin')
        (self.root / 'config/deploy.yaml').write_text("Repository: 'cn'\n", encoding='utf-8')
        self.assertIn('源: cn（配置）', self.collect())

    def test_configured_git_executable_is_used_without_a_shell(self):
        executable = self.root / 'custom git.exe'
        executable.touch()
        (self.root / 'config/deploy.yaml').write_text(
            f"GitExecutable: '{executable.as_posix()}'\n", encoding='utf-8')
        with patch.object(log_watermark.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            result = self.collect()
        self.assertIn('本地修改: 未知', result)
        self.assertEqual(run.call_args.args[0][0], str(executable))
        self.assertIn('--no-optional-locks', run.call_args.args[0])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertLessEqual(run.call_args.kwargs['timeout'], 3)

    def test_unavailable_git_is_unknown_instead_of_clean(self):
        with patch.object(log_watermark.subprocess, 'run', side_effect=FileNotFoundError):
            result = self.collect()
        self.assertIn('分支: 未知', result)
        self.assertIn('提交: 未知', result)
        self.assertIn('本地修改: 未知', result)

    def test_commands_share_a_timeout_budget(self):
        with (
            patch.object(log_watermark.time, 'monotonic', side_effect=[10, 10, 14, 14, 14]),
            patch.object(log_watermark.subprocess, 'run',
                         side_effect=subprocess.TimeoutExpired('git', 3)) as run,
        ):
            result = self.collect()
        self.assertEqual(run.call_count, 1)
        self.assertIn('本地修改: 未知', result)

    def test_archive_without_git_can_report_manifest_commit_but_not_clean_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'BUILD_MANIFEST').write_text(json.dumps({'azurpilot_commit': self.commit}), encoding='utf-8')
            with patch.object(log_watermark.subprocess, 'run') as run:
                result = log_watermark.collect_source_watermark(root)
        run.assert_not_called()
        self.assertIn(f'提交: {self.commit[:12]}', result)
        self.assertIn('分支: 未知', result)
        self.assertIn('本地修改: 未知', result)

    def test_safe_source_hides_local_paths_and_ssh_credentials(self):
        self.assertEqual(log_watermark._safe_source(r'C:\Users\private\repo'), '本地仓库')
        self.assertEqual(log_watermark._safe_source('file:///home/private/repo'), '本地仓库')
        self.assertEqual(log_watermark._safe_source('git@example.invalid:team/repo.git'),
                         'example.invalid:team/repo.git')
        self.assertEqual(log_watermark._safe_source('https://[invalid'), '未知')


class TestWatermarkIsolation(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.file = self.root / 'log.txt'
        self.file.write_text('original error\n', encoding='utf-8')
        self.logger = self.enterContext(patch.object(log_watermark, 'logger'))
        self.enterContext(patch.object(log_watermark, '_last_watermark', '[来源水印] cached'))

    def test_original_log_is_preserved_with_watermark_at_the_end(self):
        with patch.object(log_watermark, 'collect_source_watermark', return_value='[来源水印] test'):
            log_watermark._write_source_watermark(self.file)
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'original error\n\n[来源水印] test\n')
        self.logger.info.assert_called_once_with('[来源水印] test')

    def test_removed_log_is_not_recreated(self):
        self.file.unlink()
        with patch.object(log_watermark, 'collect_source_watermark', return_value='watermark'):
            log_watermark._write_source_watermark(self.file)
        self.assertFalse(self.file.exists())

    def test_collection_and_append_failures_never_escape(self):
        with patch.object(log_watermark, 'collect_source_watermark', side_effect=RuntimeError('collection failed')):
            log_watermark._write_source_watermark(self.file)
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'original error\n')
        with (
            patch.object(log_watermark, 'collect_source_watermark', return_value='watermark'),
            patch('builtins.open', side_effect=PermissionError),
        ):
            log_watermark._write_source_watermark(self.file)
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'original error\n')

    def test_slow_collection_does_not_block_the_caller(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def collect():
            entered.set()
            release.wait(timeout=5)
            finished.set()
            return 'watermark'

        with patch.object(log_watermark, 'collect_source_watermark', side_effect=collect):
            try:
                log_watermark.start_log_watermark()
                self.assertTrue(entered.wait(timeout=2))
                self.assertFalse(finished.is_set())
            finally:
                release.set()
                self.assertTrue(finished.wait(timeout=2))

    def test_quick_process_exit_still_leaves_an_explicit_snapshot(self):
        with patch.object(log_watermark.threading, 'Thread') as thread:
            log_watermark.start_log_watermark(self.file)
        self.assertIn('[来源水印] cached（最近快照，等待后台刷新）', self.file.read_text(encoding='utf-8'))
        self.assertTrue(thread.call_args.kwargs['daemon'])
        thread.return_value.start.assert_called_once_with()

    def test_snapshot_append_failure_still_allows_background_collection(self):
        with (
            patch.object(log_watermark, '_append_watermark', side_effect=PermissionError),
            patch.object(log_watermark.threading, 'Thread') as thread,
        ):
            log_watermark.start_log_watermark(self.file)
        thread.return_value.start.assert_called_once_with()


class TestErrorLogIntegration(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / 'source.log'
        self.source.write_text('old line\nstart\n' + '═' * 30 + '\nerror\n', encoding='utf-8')
        self.script = AzurLaneAutoScript.__new__(AzurLaneAutoScript)
        self.script.config_name = 'test'
        self.script.__dict__['config'] = SimpleNamespace(Error_SaveError=True, Error_LlmAnalysis=False)
        self.script.cleanup_error_logs = Mock()
        self.logger = self.enterContext(patch('alas.logger'))
        self.logger.log_file = str(self.source)
        self.enterContext(patch('pathlib.Path', return_value=self.root / 'errors'))
        self.start = self.enterContext(patch.object(log_watermark, 'start_log_watermark'))

    def test_save_log_is_complete_before_optional_watermark_starts(self):
        def start(file):
            self.assertEqual(file.read_text(encoding='utf-8'), self.source.read_text(encoding='utf-8'))
            self.script.cleanup_error_logs.assert_called_once()

        self.start.side_effect = start
        self.script.save_error_log()
        self.start.assert_called_once()
        self.assertNotIn('device', self.script.__dict__)

    def test_disabled_watermark_preserves_error_log_and_cleanup(self):
        self.script.config.Error_LogWatermark = False
        self.script.save_error_log()
        self.start.assert_not_called()
        self.assertEqual(len(list((self.root / 'errors').glob('*/log.txt'))), 1)
        self.script.cleanup_error_logs.assert_called_once()

    def test_disabled_error_saving_creates_no_watermark_or_files(self):
        self.script.config.Error_SaveError = False
        self.script.save_error_log()
        self.start.assert_not_called()
        self.assertFalse((self.root / 'errors').exists())

    def test_thread_start_failure_leaves_saved_log_and_cleanup_unchanged(self):
        self.start.side_effect = RuntimeError('cannot create thread')
        self.script.save_error_log()
        self.assertEqual(len(list((self.root / 'errors').glob('*/log.txt'))), 1)
        self.script.cleanup_error_logs.assert_called_once()

    def test_failed_log_copy_does_not_pass_a_missing_file_to_worker(self):
        self.logger.log_file = str(self.root / 'missing.log')
        self.script.save_error_log()
        self.start.assert_called_once_with(None)
        self.script.cleanup_error_logs.assert_called_once()

    def test_default_and_old_configuration_enable_the_watermark(self):
        self.assertIs(GeneratedConfig.Error_LogWatermark, True)
        old = {'Alas': {'Error': {'SaveError': False, 'HandleError': False}}}
        updated = ConfigUpdater().config_update(old)
        self.assertIs(updated['Alas']['Error']['LogWatermark'], True)
        self.assertIs(updated['Alas']['Error']['SaveError'], False)
        self.assertIs(updated['Alas']['Error']['HandleError'], False)
        self.assertNotIn('LogWatermark', old['Alas']['Error'])


class TestStartupWatermark(unittest.TestCase):
    def test_startup_switch_and_watermark_failure_preserve_normal_stop(self):
        for enabled, fail in ((True, False), (False, False), (True, True)):
            with (
                self.subTest(enabled=enabled, worker_start_fails=fail),
                patch('alas.logger'),
                patch('module.config.utils.is_oobe_needed', return_value=False),
                patch('module.base.backup.backup'),
                patch.dict(os.environ, {'ALAS_DEBUG_SERVER': '0'}),
                patch.object(log_watermark, 'start_log_watermark',
                             side_effect=RuntimeError if fail else None) as start,
            ):
                script = AzurLaneAutoScript('test')
                script.__dict__['config'] = SimpleNamespace(
                    Error_LogWatermark=enabled, DailySummary_Enable=False,
                    Backup_Enable=False, Backup_KeepDays=7,
                )
                script._start_watchdog = Mock()
                script._stop_daily_summary_scheduler = Mock()
                script.stop_event = Mock()
                script.stop_event.is_set.return_value = True
                script.loop()
                self.assertEqual(start.call_count, int(enabled))
                script._start_watchdog.assert_called_once()
                script._stop_daily_summary_scheduler.assert_called_once()
                self.assertNotIn('device', script.__dict__)


if __name__ == '__main__':
    unittest.main()
