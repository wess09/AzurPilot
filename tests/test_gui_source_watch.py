"""gui.py 的 -r 源码监听与自动重载契约。"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui import (
    EXIT_WORKER_CLEANUP_FAILURE,
    SourceWatcher,
    _signal_source_change,
    main,
    reload_requested,
    run_webui_supervisor,
)


class ReloadArgumentTest(unittest.TestCase):
    def test_only_exact_reload_flags_are_accepted(self):
        for argv, expected in (
            (["-r"], True),
            (["--reload"], True),
            (["-p", "25548", "-r"], True),
            ([], False),
            (["-ra"], False),          # pytest 常用参数，不能被误判
            (["--run", "demo"], False),
            (["--reload=true"], False),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(expected, reload_requested(argv))

    def test_reload_flag_forces_supervisor_even_when_config_disabled(self):
        with patch('module.logger.logger.set_file_logger'), patch(
            'module.persistence.database.initialize'
        ), patch('gui.set_start_method'), patch(
            'gui.State', deploy_config=SimpleNamespace(EnableReload=False)
        ), patch('gui.run_webui_supervisor', return_value=0) as supervisor, patch(
            'gui.func'
        ) as service, patch.object(sys, 'argv', ['gui.py', '-r']):
            self.assertEqual(main(), 0)
            supervisor.assert_called_once_with(watch_sources=True)
            service.assert_not_called()

    def test_without_flag_direct_mode_is_unchanged(self):
        with patch('module.logger.logger.set_file_logger'), patch(
            'module.persistence.database.initialize'
        ), patch('gui.set_start_method'), patch(
            'gui.State', deploy_config=SimpleNamespace(EnableReload=False)
        ), patch('gui.run_webui_supervisor') as supervisor, patch(
            'gui.func'
        ) as service, patch.object(sys, 'argv', ['gui.py', '-ra']):
            self.assertEqual(main(), 0)
            supervisor.assert_not_called()
            service.assert_called_once_with(None, None)


class SourceWatcherTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, relative, content='value = 1\n'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def test_first_poll_builds_baseline_without_reload(self):
        self.write('module/service.py')
        watcher = SourceWatcher(self.root, debounce=0, interval=0)
        self.assertEqual([], watcher.poll())
        self.assertEqual([], watcher.poll())
        self.assertEqual(1, len(watcher.baseline))

    def test_py_change_triggers_once_after_debounce(self):
        self.write('module/service.py')
        watcher = SourceWatcher(self.root, debounce=0, interval=0)
        watcher.poll()
        self.write('module/service.py', 'value = 123456\n')
        self.assertEqual([], watcher.poll())       # 记录变更，等待稳定
        expected = str(watcher.root / 'module' / 'service.py')
        self.assertEqual([expected], watcher.poll())
        self.assertEqual([], watcher.poll())       # 基线已更新，不重复重启

    def test_new_and_deleted_py_files_are_detected(self):
        watcher = SourceWatcher(self.root, debounce=0, interval=0)
        watcher.poll()
        added = self.write('module/new.py')
        expected = str(watcher.root / 'module' / 'new.py')
        self.assertEqual([], watcher.poll())
        self.assertEqual([expected], watcher.poll())
        added.unlink()
        self.assertEqual([], watcher.poll())
        self.assertEqual([expected], watcher.poll())

    def test_non_py_and_excluded_directories_are_ignored(self):
        self.write('module/service.py')
        self.write('module/data.json')
        for relative in ('.venv/lib/venv.py', '__pycache__/cache.py',
                         'config/conf.py', 'tests/test_demo.py',
                         'log/note.py', 'tmpabc/scratch.py'):
            self.write(relative)
        watcher = SourceWatcher(self.root, debounce=0, interval=0)
        watcher.poll()
        self.write('module/data.json', '{"changed": true}\n')
        self.write('.venv/lib/venv.py', 'changed = True\n')
        self.write('__pycache__/cache.py', 'changed = True\n')
        self.write('config/conf.py', 'changed = True\n')
        self.write('tests/test_demo.py', 'changed = True\n')
        self.write('log/note.py', 'changed = True\n')
        self.write('tmpabc/scratch.py', 'changed = True\n')
        self.assertEqual([], watcher.poll())
        self.assertEqual([], watcher.poll())

    def test_interval_limits_scan_frequency(self):
        self.write('module/service.py')
        watcher = SourceWatcher(self.root, debounce=0, interval=30)
        watcher.poll()
        self.write('module/service.py', 'value = 123456\n')
        self.assertEqual([], watcher.poll())       # 间隔内的轮询不扫描
        self.assertEqual([], watcher.poll())
        expected = str(watcher.root / 'module' / 'service.py')
        watcher.last_scan = 0                       # 模拟到达下一扫描周期
        self.assertEqual([], watcher.poll())        # 记录变更，等待稳定
        watcher.last_scan = 0
        self.assertEqual([expected], watcher.poll())

    def test_continuous_writes_reset_debounce(self):
        self.write('module/service.py')
        watcher = SourceWatcher(self.root, debounce=30, interval=0)
        watcher.poll()
        self.write('module/service.py', 'value = 22\n')
        self.assertEqual([], watcher.poll())
        self.write('module/service.py', 'value = 333\n')
        self.assertEqual([], watcher.poll())
        self.assertEqual([], watcher.poll())

    def test_signal_source_change_sets_restart_event(self):
        watcher = Mock()
        watcher.root = self.root
        watcher.poll.return_value = [str(self.root / 'module' / 'service.py')]
        event = Mock()
        self.assertTrue(_signal_source_change(watcher, event))
        event.set.assert_called_once_with()
        watcher.poll.return_value = []
        event.set.reset_mock()
        self.assertFalse(_signal_source_change(watcher, event))
        event.set.assert_not_called()


class SupervisorWiringTest(unittest.TestCase):
    def test_watch_mode_creates_watcher_and_builds_baseline(self):
        with patch('gui.SourceWatcher') as factory, patch(
            'gui._recover_orphaned_workers', return_value=False
        ):
            factory.return_value.root = Path('/project')
            factory.return_value.debounce = 0.8
            factory.return_value.poll.return_value = []
            self.assertEqual(
                EXIT_WORKER_CLEANUP_FAILURE,
                run_webui_supervisor(watch_sources=True),
            )
            factory.assert_called_once()
            factory.return_value.poll.assert_called_once_with()

    def test_default_supervisor_does_not_create_watcher(self):
        with patch('gui.SourceWatcher') as factory, patch(
            'gui._recover_orphaned_workers', return_value=False
        ):
            self.assertEqual(
                EXIT_WORKER_CLEANUP_FAILURE,
                run_webui_supervisor(),
            )
            factory.assert_not_called()

    def test_source_change_sets_restart_event_in_supervisor_loop(self):
        """变更必须汇入既有的 restart_event 通道，而不是另起一套重启逻辑。"""
        root = Path.cwd()
        restart_event = Mock()
        restart_event.wait.return_value = True
        sync_event = Mock()
        sync_event.is_set.return_value = False
        second_event = Mock()
        second_event.wait.side_effect = KeyboardInterrupt
        events = [restart_event, sync_event, Mock(),
                  second_event, Mock(), Mock()]
        process = Mock()
        process.pid = 4242
        process.is_alive.return_value = True
        watcher = Mock()
        watcher.root = root
        watcher.debounce = 0.8
        watcher.poll.side_effect = [[], [str(root / 'module' / 'service.py')], []]
        with patch('gui.SourceWatcher', return_value=watcher), patch(
            'gui._recover_orphaned_workers', return_value=True
        ), patch('gui._prepare_dependency_sync_before_webui_start',
                 return_value=(True, None, None, None)), patch(
            'deploy.frontend.ensure_frontend'
        ), patch('gui.Event', side_effect=events), patch(
            'gui.Process', return_value=process
        ), patch('gui._wait_for_webui_ready', return_value=True), patch(
            'gui._stop_webui_process_tree', return_value=True
        ) as stop_tree:
            self.assertEqual(0, run_webui_supervisor(watch_sources=True))
        restart_event.set.assert_called_once_with()
        self.assertTrue(stop_tree.called)


if __name__ == '__main__':
    unittest.main()
