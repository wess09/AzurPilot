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

    def test_startup_collection_updates_cache_without_editing_saved_logs(self):
        with patch.object(log_watermark, 'collect_source_watermark', return_value='[来源水印] test'):
            log_watermark._write_source_watermark()
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'original error\n')
        self.assertEqual(log_watermark._last_watermark, '[来源水印] test')
        self.logger.info.assert_called_once_with('[来源水印] test')

    def test_error_refresh_is_silent_and_does_not_touch_saved_logs(self):
        with patch.object(log_watermark, 'collect_source_watermark', return_value='watermark'):
            log_watermark._write_source_watermark(emit=False)
        self.assertEqual(log_watermark._last_watermark, 'watermark')
        self.logger.info.assert_not_called()
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'original error\n')

    def test_collection_failures_never_escape_or_destroy_the_last_snapshot(self):
        with patch.object(log_watermark, 'collect_source_watermark', side_effect=RuntimeError('collection failed')):
            log_watermark._write_source_watermark()
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'original error\n')
        self.assertEqual(log_watermark._last_watermark, '[来源水印] cached')

    def test_slow_collection_does_not_block_the_caller(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        threads = []
        real_thread = threading.Thread

        def thread_factory(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread

        def collect():
            entered.set()
            release.wait(timeout=5)
            finished.set()
            return 'watermark'

        with (
            patch.object(log_watermark, 'collect_source_watermark', side_effect=collect),
            patch.object(log_watermark.threading, 'Thread', side_effect=thread_factory),
        ):
            try:
                log_watermark.start_log_watermark(cached=True)
                self.assertTrue(entered.wait(timeout=2))
                self.assertFalse(finished.is_set())
                self.logger.info.assert_called_once_with('[来源水印] cached（最近采集快照）')
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())

    def test_snapshot_is_logged_before_the_background_thread_starts(self):
        calls = Mock()
        calls.attach_mock(self.logger.info, 'log')
        with patch.object(log_watermark.threading, 'Thread') as thread:
            calls.attach_mock(thread.return_value.start, 'start')
            log_watermark.start_log_watermark(cached=True)
        self.assertEqual([call[0] for call in calls.mock_calls], ['log', 'start'])
        self.assertTrue(thread.call_args.kwargs['daemon'])
        self.assertEqual(thread.call_args.kwargs['kwargs'], {'emit': False})
        thread.return_value.start.assert_called_once_with()

    def test_initial_unknown_snapshot_does_not_wait_for_collection(self):
        with (
            patch.object(log_watermark, '_last_watermark', '[来源水印] 源: 未知'),
            patch.object(log_watermark.threading, 'Thread') as thread,
        ):
            log_watermark.start_log_watermark(cached=True)
        self.logger.info.assert_called_once_with('[来源水印] 源: 未知（最近采集快照）')
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
        self.start_impl = log_watermark.start_log_watermark
        self.start = self.enterContext(patch.object(log_watermark, 'start_log_watermark'))

    def test_watermark_precedes_save_message_in_both_live_and_saved_logs(self):
        def log(message):
            with self.source.open('a', encoding='utf-8') as file:
                file.write(message + '\n')

        self.logger.info.side_effect = log
        self.logger.warning.side_effect = log
        self.start.side_effect = self.start_impl
        with (
            patch.object(log_watermark, 'logger', self.logger),
            patch.object(log_watermark, '_last_watermark', '[来源水印] cached'),
            patch.object(log_watermark.threading, 'Thread') as thread,
        ):
            self.script.save_error_log()
            file = next((self.root / 'errors').glob('*/log.txt'))
            saved = file.read_text(encoding='utf-8')
            self.assertLess(saved.index('[来源水印]'), saved.index('[AzurPilot] 保存错误日志:'))
            self.assertEqual(saved.count('[来源水印]'), 1)
            self.assertIn('[AzurPilot] 保存错误日志:', saved.splitlines()[-1])
            with patch.object(log_watermark, 'collect_source_watermark', return_value='[来源水印] refreshed'):
                thread.call_args.kwargs['target'](**thread.call_args.kwargs['kwargs'])
            self.assertEqual(file.read_text(encoding='utf-8'), saved)
            self.assertEqual(self.source.read_text(encoding='utf-8'), saved)
        self.start.assert_called_once_with(cached=True)
        self.script.cleanup_error_logs.assert_called_once()
        self.assertNotIn('device', self.script.__dict__)

    def test_obsolete_disabled_switch_does_not_disable_the_watermark(self):
        self.script.config.Error_LogWatermark = False
        self.script.save_error_log()
        self.start.assert_called_once_with(cached=True)
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

    def test_failed_log_copy_still_logs_the_watermark_before_the_attempt(self):
        self.logger.log_file = str(self.root / 'missing.log')
        self.script.save_error_log()
        self.start.assert_called_once_with(cached=True)
        self.script.cleanup_error_logs.assert_called_once()

    def test_switch_is_removed_without_changing_other_error_settings(self):
        self.assertFalse(hasattr(GeneratedConfig, 'Error_LogWatermark'))
        old = {'Alas': {'Error': {'SaveError': False, 'HandleError': False, 'LogWatermark': False}}}
        updated = ConfigUpdater().config_update(old)
        self.assertNotIn('LogWatermark', updated['Alas']['Error'])
        self.assertIs(updated['Alas']['Error']['SaveError'], False)
        self.assertIs(updated['Alas']['Error']['HandleError'], False)
        self.assertIs(old['Alas']['Error']['LogWatermark'], False)


class TestStartupWatermark(unittest.TestCase):
    def test_startup_always_emits_and_watermark_failure_preserves_normal_stop(self):
        for fail in (False, True):
            with (
                self.subTest(worker_start_fails=fail),
                patch('alas.logger'),
                patch('module.config.utils.is_oobe_needed', return_value=False),
                patch('module.base.backup.backup'),
                patch.dict(os.environ, {'ALAS_DEBUG_SERVER': '0'}),
                patch.object(log_watermark, 'start_log_watermark',
                             side_effect=RuntimeError if fail else None) as start,
            ):
                script = AzurLaneAutoScript('test')
                script.__dict__['config'] = SimpleNamespace(
                    Error_LogWatermark=False, DailySummary_Enable=False,
                    Backup_Enable=False, Backup_KeepDays=7,
                )
                script._start_watchdog = Mock()
                script._stop_daily_summary_scheduler = Mock()
                script.stop_event = Mock()
                script.stop_event.is_set.return_value = True
                script.loop()
                start.assert_called_once_with(cached=False)
                script._start_watchdog.assert_called_once()
                script._stop_daily_summary_scheduler.assert_called_once()
                self.assertNotIn('device', script.__dict__)


if __name__ == '__main__':
    unittest.main()
