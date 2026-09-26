"""更新 API 的真实 Git 历史与后台互斥回归，不触发线上更新。"""
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.protocol import ApiError, CommitsParams
from module.api.router import Router
from module.api.update_service import UpdateService
from module.runtime.setting import State


class UpdateServiceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.updater = SimpleNamespace(git='git', Branch='dev', state=0, _update_lock=threading.Lock())
        self.service = UpdateService(self.root, self.updater)
        self.git('init', '-b', 'dev')
        self.git('config', 'user.name', '测试作者')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('commit', '--allow-empty', '-m', '初始提交')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('commit', '--allow-empty', '-m', '新增主页\n\n保留完整正文与 --- 分隔符。')
        self.remote = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/dev', self.remote)
        self.git('reset', '--hard', self.base)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True,
                              text=True, encoding='utf-8').stdout.strip()

    def test_heads_and_complete_paginated_history(self):
        with patch.object(State, 'restart_event', threading.Event()), patch.object(State, 'dependency_sync_event', threading.Event()):
            status = self.service.status()
        self.assertEqual((status['localHead'], status['upstreamHead']), (self.base, self.remote))
        self.assertEqual((status['ahead'], status['behind']), (0, 1))
        self.assertTrue(status['canApply'])
        first = self.service.commits(0, 1)
        second = self.service.commits(1, 1)
        self.assertEqual(first['total'], 2)
        self.assertTrue(first['hasMore'])
        self.assertFalse(second['hasMore'])
        self.assertIn('保留完整正文与 --- 分隔符。', first['entries'][0]['message'])
        self.assertEqual(second['entries'][0]['sha'], self.base)

    def test_diverged_history_reports_mismatch_and_allows_confirmed_apply(self):
        """本地与上游历史互不包含时报告 SHA 不匹配；更新改由前端弹窗确认放行。"""
        self.git('commit', '--allow-empty', '-m', '本地修改')
        with patch.object(State, 'restart_event', threading.Event()), patch.object(State, 'dependency_sync_event', threading.Event()):
            status = self.service.status()
        self.assertEqual((status['ahead'], status['behind']), (1, 1))
        self.assertTrue(status['shaMismatch'])
        self.assertTrue(status['canApply'])
        self.assertEqual(self.service.commits()['total'], 3)
        self.updater.run_update = Mock(return_value=True)
        with patch.object(State, 'restart_event', threading.Event()), patch.object(State, 'dependency_sync_event', threading.Event()):
            self.assertTrue(self.service.start('apply')['accepted'])
            for _ in range(100):
                if self.service.operation is None:
                    break
                threading.Event().wait(0.05)
        self.updater.run_update.assert_called_once()

    def test_stale_upstream_head_from_rewritten_history_can_apply(self):
        """上游重写历史后，停在旧版上游历史的本地分支不应被当成"有独有提交"。"""
        stale = self.remote
        self.git('checkout', '-q', '--orphan', 'rewritten')
        self.git('commit', '--allow-empty', '-m', '重写后的提交')
        rewritten = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/dev', rewritten)
        self.git('checkout', '-q', 'dev')
        self.git('reset', '--hard', self.base)
        with patch.object(State, 'restart_event', threading.Event()), patch.object(State, 'dependency_sync_event', threading.Event()):
            diverged = self.service.status()
            with patch('module.runtime.upstream_history.REWRITE_BASES', (stale,)):
                migrated = self.service.status()
        self.assertGreater(diverged['ahead'], 0)
        self.assertTrue(diverged['canApply'])
        self.assertTrue(diverged['shaMismatch'])
        self.assertEqual(migrated['ahead'], 0)
        self.assertTrue(migrated['canApply'])
        self.assertFalse(migrated['shaMismatch'])

    def test_missing_upstream_and_no_supervisor_are_readable(self):
        with patch.object(State, 'restart_event', None):
            self.assertFalse(self.service.status()['canApply'])
        self.git('update-ref', '-d', 'refs/remotes/origin/dev')
        self.assertIsNone(self.service.status()['upstreamHead'])
        self.assertEqual(self.service.commits()['total'], 1)

    def test_fetch_reserves_operation_and_keeps_local_head(self):
        self.updater._fetch_with_retry = Mock()
        with patch('module.api.update_service.Thread') as thread:
            self.assertTrue(self.service.start('fetch')['accepted'])
            with self.assertRaises(ApiError):
                self.service.start('fetch')
            thread.assert_called_once()
        self.service._run('fetch')
        self.assertIsNone(self.service.operation)
        self.assertEqual(self.updater.state, 1)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_fetch_failure_is_reported_and_can_retry(self):
        self.updater._fetch_with_retry = Mock(side_effect=RuntimeError('凭据不可回显'))
        self.service._run('fetch')
        self.assertEqual(self.updater.state, 'failed')
        self.assertNotIn('凭据', self.service.status()['error'])
        self.assertFalse(self.service.status()['busy'])

    def test_busy_update_is_not_overwritten_by_late_fetch(self):
        self.updater.state = 'run update'
        self.service._run('fetch')
        self.assertEqual(self.updater.state, 'run update')

    def test_apply_keeps_wait_phase_visible_and_reuses_updater(self):
        self.updater.state = 'wait'
        self.service.operation = 'apply'
        status = self.service.status()
        self.assertEqual(status['state'], 'wait')
        self.assertTrue(status['canCancel'])
        self.updater.cancel = Mock()
        self.service.cancel()
        self.updater.cancel.assert_called_once()
        self.updater.state = 1
        self.updater.run_update = Mock(return_value=True)
        self.service._run('apply')
        self.updater.run_update.assert_called_once()
        self.assertIsNone(self.service.operation)

    def test_protocol_and_readonly_gate(self):
        with self.assertRaises(ValueError):
            CommitsParams(offset=-1)
        with self.assertRaises(ValueError):
            CommitsParams(limit=101)
        with patch.dict(os.environ, {'DEMO': '1'}):
            for method in ('updater.fetch', 'updater.apply', 'updater.cancel'):
                with self.assertRaises(ApiError) as error:
                    Router(None, None).dispatch(method, {})
                self.assertEqual(error.exception.code, 'READ_ONLY')

    def test_android_runtime_uses_manifest_and_rejects_git_actions(self):
        (self.root / 'BUILD_MANIFEST').write_text(
            '{"azurpilot_commit": "android-commit"}', encoding='utf-8')
        with patch.dict(os.environ, {'AZURPILOT_ANDROID': '1'}):
            status = self.service.status()
            self.assertTrue(status['managedByAndroid'])
            self.assertEqual(status['state'], 'android')
            self.assertEqual(status['localHead'], 'android-commit')
            self.assertFalse(status['canApply'])
            self.assertEqual(self.service.commits()['entries'], [])
            with self.assertRaises(ApiError) as error:
                self.service.start('fetch')
            self.assertEqual(error.exception.code, 'UPDATE_MANAGED_BY_ANDROID')


if __name__ == '__main__':
    unittest.main()
