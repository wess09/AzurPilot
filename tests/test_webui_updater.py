import os
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

from deploy.git import GitManager
from module.runtime.setting import State
from module.runtime.updater import Updater


class TestGitInstall(unittest.TestCase):
    def test_source_update_uses_cdn_and_git_without_cloud_control(self):
        for use_cdn, cdn_success in ((False, False), (True, True), (True, False)):
            with self.subTest(use_cdn=use_cdn, cdn_success=cdn_success):
                manager = Mock(spec=GitManager)
                manager.GitOverCdn = use_cdn
                manager.goc_client.update.return_value = cdn_success
                with patch('deploy.git.requests.get') as request:
                    GitManager.git_install(manager)

                request.assert_not_called()
                if use_cdn:
                    manager.goc_client.update.assert_called_once_with()
                else:
                    manager.goc_client.update.assert_not_called()
                if use_cdn and cdn_success:
                    manager.git_repository_init.assert_not_called()
                else:
                    manager.git_repository_init.assert_called_once_with(
                        repo=manager.Repository,
                        source='origin',
                        branch=manager.Branch,
                        proxy=manager.GitProxy,
                        ssl_verify=manager.SSLVerify,
                    )


class TestUpdaterReload(unittest.TestCase):
    def setUp(self):
        self.original_restart_event = State.restart_event
        self.original_dependency_sync_event = State.dependency_sync_event
        self.original_restart_requested = State._restart_requested
        State.restart_event = Mock()
        State.dependency_sync_event = Mock()
        State._restart_requested = False

    def tearDown(self):
        State.restart_event = self.original_restart_event
        State.dependency_sync_event = self.original_dependency_sync_event
        State._restart_requested = self.original_restart_requested

    @staticmethod
    def _updater():
        updater = object.__new__(Updater)
        updater.state = None
        updater.update = Mock(return_value=True)
        updater._update_lock = threading.Lock()
        return updater

    def test_update_cleans_before_triggering_webui_reload(self):
        order = []
        app_module = types.ModuleType("module.api.lifecycle")
        app_module.clearup = lambda: order.append("clearup")
        updater = self._updater()
        updater._trigger_reload = Mock(side_effect=lambda: order.append("trigger"))

        with (
            patch("module.runtime.updater.atomic_write") as atomic_write,
            patch("module.runtime.updater.mark_dependency_sync_pending") as mark_pending,
            patch.dict(sys.modules, {"module.api.lifecycle": app_module}),
        ):
            result = updater._run_update([], ["alas\n"])

        self.assertTrue(result)
        self.assertEqual(["clearup", "trigger"], order)
        atomic_write.assert_called_once_with("./config/reloadalas", "alas\n")
        mark_pending.assert_called_once_with()
        State.dependency_sync_event.set.assert_called_once_with()

    def test_update_still_triggers_reload_when_cleanup_fails(self):
        order = []
        app_module = types.ModuleType("module.api.lifecycle")

        def clearup():
            order.append("clearup")
            raise RuntimeError("cleanup failed")

        app_module.clearup = clearup
        updater = self._updater()
        updater._trigger_reload = Mock(side_effect=lambda: order.append("trigger"))

        with (
            patch("module.runtime.updater.atomic_write"),
            patch("module.runtime.updater.mark_dependency_sync_pending"),
            patch("module.runtime.updater.logger.exception_context") as log_error,
            patch.dict(sys.modules, {"module.api.lifecycle": app_module}),
        ):
            updater._run_update([], [])

        self.assertEqual(["clearup", "trigger"], order)
        log_error.assert_called_once()

    def test_update_still_triggers_reload_when_cleanup_import_fails(self):
        updater = self._updater()
        updater._trigger_reload = Mock()
        original_import = __import__

        def fail_webui_app_import(name, *args, **kwargs):
            if name == "module.api.lifecycle":
                raise ImportError("updated WebUI module is unavailable")
            return original_import(name, *args, **kwargs)

        with (
            patch("module.runtime.updater.atomic_write"),
            patch("module.runtime.updater.mark_dependency_sync_pending"),
            patch("module.runtime.updater.logger.exception_context") as log_error,
            patch("builtins.__import__", side_effect=fail_webui_app_import),
        ):
            self.assertTrue(updater._run_update([], []))

        updater._trigger_reload.assert_called_once_with()
        log_error.assert_called_once()

    def test_update_does_not_run_git_when_reload_marker_cannot_be_written(self):
        updater = self._updater()
        updater.event = Mock()
        updater._trigger_reload = Mock()

        with (
            patch("module.runtime.updater.atomic_write", side_effect=OSError("read-only")),
            patch("module.runtime.updater.mark_dependency_sync_pending") as mark_pending,
            patch("module.runtime.updater.ProcessManager.restart_processes") as restart,
            patch("module.runtime.updater.logger.exception_context") as log_error,
        ):
            result = updater._run_update([], ["alas\n"])

        self.assertFalse(result)
        self.assertEqual("failed", updater.state)
        updater.event.clear.assert_called_once_with()
        restart.assert_called_once_with([], updater.event)
        log_error.assert_called_once()
        mark_pending.assert_called_once_with()
        updater.update.assert_not_called()
        updater._trigger_reload.assert_not_called()

    def test_update_does_not_run_git_when_sync_marker_cannot_be_written(self):
        updater = self._updater()
        updater.event = Mock()
        updater._trigger_reload = Mock()

        with (
            patch(
                "module.runtime.updater.mark_dependency_sync_pending",
                side_effect=OSError("read-only"),
            ),
            patch("module.runtime.updater.atomic_write") as write_marker,
            patch("module.runtime.updater.ProcessManager.restart_processes") as restart,
            patch("module.runtime.updater.logger.exception_context") as log_error,
        ):
            result = updater._run_update([], ["alas\n"])

        self.assertFalse(result)
        self.assertEqual("failed", updater.state)
        updater.event.clear.assert_called_once_with()
        restart.assert_called_once_with([], updater.event)
        write_marker.assert_not_called()
        updater.update.assert_not_called()
        updater._trigger_reload.assert_not_called()
        log_error.assert_called_once()

    def test_existing_restart_request_does_not_overwrite_reload_marker(self):
        updater = self._updater()
        State._restart_requested = True

        with (
            patch("module.runtime.updater.atomic_write") as write_marker,
            patch("module.runtime.updater.mark_dependency_sync_pending") as mark_pending,
        ):
            self.assertTrue(updater._run_update([], ["alas\n"]))

        write_marker.assert_not_called()
        mark_pending.assert_not_called()

    def test_cancel_before_wait_does_not_stop_or_update_instances(self):
        updater = self._updater()
        updater.state = "cancel"
        updater.event = Mock()
        updater._run_update = Mock()

        self.assertTrue(updater._wait_update([], []))

        self.assertEqual(1, updater.state)
        updater.event.set.assert_not_called()
        updater._run_update.assert_not_called()

    def test_update_converts_unexpected_error_to_recoverable_failure(self):
        updater = object.__new__(Updater)
        updater.git_install = Mock(side_effect=RuntimeError("network broken"))

        with patch("module.runtime.updater.logger.exception_context") as log_error:
            self.assertFalse(updater.update())

        log_error.assert_called_once()

    def test_trigger_reload_sets_parent_event_immediately(self):
        Updater._trigger_reload()

        State.restart_event.set.assert_called_once_with()

    def test_run_update_serializes_concurrent_requests(self):
        updater = self._updater()
        updater.state = 1
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def start_update():
            calls.append(True)
            updater.state = "start"
            entered.set()
            release.wait(timeout=2)
            return True

        updater._start_update = Mock(side_effect=start_update)
        results = []
        first = threading.Thread(target=lambda: results.append(updater.run_update()))
        second = threading.Thread(target=lambda: results.append(updater.run_update()))

        first.start()
        self.assertTrue(entered.wait(timeout=2))
        second.start()
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertCountEqual([True, False], results)
        updater._start_update.assert_called_once_with()
        self.assertEqual([True], calls)

    def test_run_update_holds_restart_transaction_until_update_finishes(self):
        updater = self._updater()
        updater.state = 1
        entered = threading.Event()
        release = threading.Event()

        def start_update():
            entered.set()
            release.wait(timeout=2)
            return True

        updater._start_update = Mock(side_effect=start_update)
        thread = threading.Thread(target=updater.run_update)
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        try:
            self.assertFalse(State.restart_lock.acquire(blocking=False))
        finally:
            release.set()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())

    def test_run_update_skips_when_manual_restart_is_pending(self):
        updater = self._updater()
        updater.state = 1
        updater._start_update = Mock()
        State._restart_requested = True

        self.assertTrue(updater.run_update())

        updater._start_update.assert_not_called()

    def test_update_marks_pending_sync_before_notifying_parent(self):
        order = []
        app_module = types.ModuleType("module.api.lifecycle")
        app_module.clearup = lambda: order.append("clearup")
        updater = self._updater()
        updater.update.side_effect = lambda: order.append("git") or True
        updater._trigger_reload = Mock(side_effect=lambda: order.append("reload"))

        with (
            patch(
                "module.runtime.updater.atomic_write",
                side_effect=lambda *args: order.append("marker"),
            ),
            patch(
                "module.runtime.updater.mark_dependency_sync_pending",
                side_effect=lambda: order.append("pending"),
            ),
            patch.dict(sys.modules, {"module.api.lifecycle": app_module}),
        ):
            State.dependency_sync_event.set.side_effect = lambda: order.append("sync")
            self.assertTrue(updater._run_update([], []))

        self.assertEqual(["pending", "marker", "git", "sync", "clearup", "reload"], order)

    def test_update_failure_restarts_through_parent_without_local_worker_recovery(self):
        app_module = types.ModuleType("module.api.lifecycle")
        app_module.clearup = Mock(return_value=True)
        updater = self._updater()
        updater.event = Mock()
        updater.update.return_value = False
        updater._trigger_reload = Mock()

        with (
            patch("module.runtime.updater.atomic_write"),
            patch("module.runtime.updater.mark_dependency_sync_pending"),
            patch("module.runtime.updater.ProcessManager.restart_processes") as restart,
            patch.dict(sys.modules, {"module.api.lifecycle": app_module}),
        ):
            result = updater._run_update([], ["alas\n"])

        self.assertFalse(result)
        self.assertEqual("failed", updater.state)
        restart.assert_not_called()
        updater.event.clear.assert_not_called()
        State.dependency_sync_event.set.assert_called_once_with()
        updater._trigger_reload.assert_called_once_with()
        self.assertTrue(State._restart_requested)

    def test_update_keeps_persistent_sync_marker_when_event_notification_fails(self):
        app_module = types.ModuleType("module.api.lifecycle")
        app_module.clearup = Mock(return_value=True)
        updater = self._updater()
        updater._trigger_reload = Mock()
        State.dependency_sync_event.set.side_effect = OSError("event closed")

        with (
            patch("module.runtime.updater.atomic_write"),
            patch("module.runtime.updater.mark_dependency_sync_pending") as mark_pending,
            patch("module.runtime.updater.logger.exception_context") as log_error,
            patch.dict(sys.modules, {"module.api.lifecycle": app_module}),
        ):
            self.assertTrue(updater._run_update([], []))

        mark_pending.assert_called_once_with()
        updater._trigger_reload.assert_called_once_with()
        log_error.assert_called_once()
        self.assertTrue(State._restart_requested)

    def test_update_without_hot_reload_is_rejected_before_git_update(self):
        updater = self._updater()
        updater.state = 1
        State.restart_event = None

        self.assertFalse(updater.run_update())

        self.assertEqual("failed", updater.state)
        updater.update.assert_not_called()

    def test_direct_update_without_hot_reload_is_rejected_before_git_update(self):
        updater = self._updater()
        State.restart_event = None

        self.assertFalse(updater._run_update([], []))

        self.assertEqual("failed", updater.state)
        updater.update.assert_not_called()

    def test_wait_update_cancels_when_forced_worker_stop_fails(self):
        updater = self._updater()
        updater.state = 1
        updater.event = Mock()
        updater._run_update = Mock()
        worker = Mock(config_name="alas")
        worker.alive = True
        worker.stop.return_value = False

        with (
            patch("module.runtime.updater.time.time", side_effect=[0, 601]),
            patch("module.runtime.updater.time.sleep"),
            patch("module.runtime.updater.logger.warning"),
            patch("module.runtime.updater.logger.critical"),
            patch("module.runtime.updater.ProcessManager.restart_processes") as restart,
        ):
            self.assertFalse(updater._wait_update([worker], ["alas\n"]))

        worker.stop.assert_called_once_with()
        updater._run_update.assert_not_called()
        updater.event.clear.assert_called_once_with()
        restart.assert_called_once_with([worker], updater.event)


class TestUpdaterForceUpdate(unittest.TestCase):
    @staticmethod
    def _updater():
        updater = object.__new__(Updater)
        updater.state = 0
        updater.force_update = False
        updater._force_update_checking = False
        return updater

    def test_force_control_failure_does_not_block_version_check(self):
        updater = self._updater()
        updater.force_update = True
        updater._check_cloud_force_update = Mock(return_value=None)
        client = Mock()
        client.get_status.return_value = 'behind'

        with (
            patch.object(State, 'deploy_config', types.SimpleNamespace(GitOverCdn=True)),
            patch.object(Updater, 'goc_client', new=property(lambda self: client)),
        ):
            self.assertTrue(updater._check_update())

        self.assertFalse(updater.force_update)
        updater._check_cloud_force_update.assert_called_once_with()
        client.get_status.assert_called_once_with()

    def test_detected_update_starts_immediately_when_force_update_is_enabled(self):
        updater = self._updater()
        updater.force_update = True
        updater._check_update = Mock(return_value=True)
        updater.run_update = Mock()

        updater._check_update_thread()

        self.assertEqual(1, updater.state)
        updater.run_update.assert_called_once_with()

    def test_detected_update_waits_for_manual_or_scheduled_update_when_force_is_disabled(self):
        updater = self._updater()
        updater._check_update = Mock(return_value=True)
        updater.run_update = Mock()

        updater._check_update_thread()

        self.assertEqual(1, updater.state)
        updater.run_update.assert_not_called()

    def test_existing_update_starts_when_force_update_is_later_enabled(self):
        updater = self._updater()
        updater._check_cloud_force_update = Mock(return_value=True)
        updater.run_update = Mock()

        updater._check_force_update_thread()

        self.assertTrue(updater.force_update)
        self.assertFalse(updater._force_update_checking)
        updater.run_update.assert_called_once_with()

    def test_update_checks_follow_configured_interval_in_both_modes(self):
        for force_update in (False, True):
            for interval in (2, 5):
                with self.subTest(force_update=force_update, interval=interval):
                    updater = self._updater()
                    updater.force_update = force_update
                    object.__setattr__(updater, "CheckUpdateInterval", interval)
                    updater.read = Mock()
                    updater._check_update = Mock(return_value=False)
                    updater.run_update = Mock()
                    updater.check_update = Mock(side_effect=updater._check_update_thread)
                    handler = types.SimpleNamespace(_task=types.SimpleNamespace(delay=None))
                    loop = updater.check_update_loop()
                    self.addCleanup(loop.close)
                    next(loop)

                    seconds = interval * 60
                    times = (0, 1, seconds - 1, seconds, seconds + 1, 2 * seconds)
                    with patch("module.runtime.updater.time.monotonic", side_effect=times):
                        loop.send(handler)
                        self.assertEqual(1, updater._check_update.call_count)
                        for expected in (1, 1, 2, 2, 3):
                            next(loop)
                            self.assertEqual(expected, updater._check_update.call_count)

                    self.assertEqual(0, updater.state)
                    updater.run_update.assert_not_called()

    def test_enabling_force_update_does_not_bypass_scheduled_check(self):
        updater = self._updater()
        object.__setattr__(updater, "CheckUpdateInterval", 5)
        updater.read = Mock()
        updater.check_update = Mock()
        handler = types.SimpleNamespace(_task=types.SimpleNamespace(delay=None))
        loop = updater.check_update_loop()
        self.addCleanup(loop.close)
        next(loop)

        with patch(
            "module.runtime.updater.time.monotonic", side_effect=[0, 1, 299, 300, 301]
        ):
            loop.send(handler)
            updater.force_update = True
            next(loop)
            next(loop)
            self.assertEqual(1, updater.check_update.call_count)
            next(loop)
            next(loop)

        self.assertEqual(2, updater.check_update.call_count)
        self.assertEqual(1, handler._task.delay)

    def test_android_runtime_skips_git_update_check(self):
        updater = self._updater()
        updater.state = 'failed'
        updater._check_update_thread = Mock()

        with patch.dict(os.environ, {'AZURPILOT_ANDROID': '1'}):
            updater.check_update()

        self.assertEqual(0, updater.state)
        updater._check_update_thread.assert_not_called()
