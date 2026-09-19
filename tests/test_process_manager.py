import threading
import unittest
from unittest.mock import Mock, PropertyMock, patch

from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State
from module.runtime.worker_events import WorkerResult


class TestProcessManagerRegistry(unittest.TestCase):
    def setUp(self):
        self.original_manager = State.manager
        self.original_registry = State.process_registry
        self.original_clearup = State._clearup
        self.original_restart_requested = State._restart_requested
        self.original_processes = ProcessManager._processes
        self.original_lifecycle_locks = ProcessManager._lifecycle_locks
        State.manager = Mock()
        State.manager.Queue.return_value = Mock()
        State.process_registry = {}
        State._clearup = False
        State._restart_requested = False
        ProcessManager._processes = {}
        ProcessManager._lifecycle_locks = {}

    def tearDown(self):
        State.manager = self.original_manager
        State.process_registry = self.original_registry
        State._clearup = self.original_clearup
        State._restart_requested = self.original_restart_requested
        ProcessManager._processes = self.original_processes
        ProcessManager._lifecycle_locks = self.original_lifecycle_locks

    def test_second_session_uses_registered_worker_pid(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")

        with (
            patch(
                "module.runtime.process_manager.is_current_owner", return_value=True
            ),
            patch(
                "module.runtime.process_manager.get_workers",
                return_value={"alas": {"pid": 12345, "created_at": 1}},
            ),
            patch("module.runtime.process_manager.process_matches", return_value=True),
        ):
            self.assertTrue(manager.alive)

    def test_authoritative_record_repairs_missing_or_stale_pid_cache(self):
        for cached in (None, 23456):
            with self.subTest(cached=cached):
                State.process_registry.clear()
                if cached is not None:
                    State.process_registry["alas"] = cached
                manager = ProcessManager.get_manager("alas")
                record = {"pid": 12345, "created_at": 1}
                with (
                    patch("module.runtime.process_manager.is_current_owner", return_value=True),
                    patch("module.runtime.process_manager.get_workers", return_value={"alas": record}),
                    patch("module.runtime.process_manager.process_matches", return_value=True),
                ):
                    self.assertTrue(manager.alive)
                self.assertEqual(State.process_registry["alas"], 12345)

    def test_local_handle_must_match_record_even_if_cache_matches(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")
        manager._process = Mock(pid=12345)
        manager._process.is_alive.return_value = True
        with (
            patch("module.runtime.process_manager.get_workers", return_value={"alas": {"pid": 23456, "created_at": 1}}),
            patch("module.runtime.process_manager.stop_process_tree") as stop_tree,
            patch("module.runtime.process_manager.unregister_worker") as unregister,
        ):
            self.assertFalse(manager.stop())
        stop_tree.assert_not_called()
        unregister.assert_not_called()

    def test_start_rejects_unreadable_registry_without_pid_cache(self):
        manager = ProcessManager.get_manager("alas")
        with (
            patch("module.runtime.process_manager.get_workers", side_effect=RuntimeError("拒绝读取")),
            patch("module.runtime.process_manager.Process") as process,
        ):
            manager.start("alas")
        process.assert_not_called()

    def test_stop_uses_registered_worker_pid_without_local_process(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")

        with (
            patch("module.runtime.process_manager.stop_process_tree", return_value=True) as kill,
            patch(
                "module.runtime.process_manager.is_current_owner", return_value=True
            ),
            patch(
                "module.runtime.process_manager.get_workers",
                return_value={"alas": {"pid": 12345, "created_at": 1}},
            ),
            patch("module.runtime.process_manager.process_matches", return_value=True),
            patch("module.runtime.process_manager.unregister_worker"),
        ):
            self.assertTrue(manager.stop())

        kill.assert_called_once_with(None, record={"pid": 12345, "created_at": 1}, name="worker alas", timeout=0)
        self.assertNotIn("alas", State.process_registry)
        self.assertEqual(manager.exit_result, WorkerResult.MANUAL_STOP)
        self.assertEqual(manager.state, 2)

    def test_stop_passes_local_handle_and_record_to_tree_stop(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")
        process = Mock(pid=12345)
        process.is_alive.return_value = True
        manager._process = process
        record = {"pid": 12345, "created_at": 1}
        with (
            patch("module.runtime.process_manager.stop_process_tree", return_value=True) as stop_tree,
            patch("module.runtime.process_manager.is_current_owner", return_value=True),
            patch("module.runtime.process_manager.get_workers", return_value={"alas": record}),
            patch("module.runtime.process_manager.process_matches", return_value=True),
            patch("module.runtime.process_manager.unregister_worker"),
        ):
            self.assertTrue(manager.stop())
        stop_tree.assert_called_once_with(process, record=record, name="worker alas", timeout=5)
        self.assertNotIn("alas", State.process_registry)

    def test_failed_local_tree_stop_keeps_handle_and_registry(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")
        process = Mock(pid=12345)
        process.is_alive.return_value = True
        manager._process = process
        with (
            patch("module.runtime.process_manager.stop_process_tree", return_value=False),
            patch("module.runtime.process_manager.is_current_owner", return_value=True),
            patch("module.runtime.process_manager.get_workers", return_value={"alas": {"pid": 12345, "created_at": 1}}),
            patch("module.runtime.process_manager.process_matches", return_value=True),
            patch("module.runtime.process_manager.unregister_worker") as unregister,
        ):
            self.assertFalse(manager.stop())
        self.assertIs(manager._process, process)
        self.assertEqual(State.process_registry["alas"], 12345)
        unregister.assert_not_called()

    def test_failed_cross_session_stop_keeps_worker_registered(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")

        with patch("module.runtime.process_manager.stop_process_tree", return_value=False):
            with (
                patch(
                    "module.runtime.process_manager.is_current_owner", return_value=True
                ),
                patch(
                    "module.runtime.process_manager.get_workers",
                    return_value={"alas": {"pid": 12345, "created_at": 1}},
                ),
                patch("module.runtime.process_manager.process_matches", return_value=True),
            ):
                self.assertFalse(manager.stop())

        self.assertEqual(12345, State.process_registry["alas"])

    def test_pid_reuse_clears_stale_registration_without_terminating_unknown_process(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")

        with (
            patch("module.runtime.process_manager.stop_process_tree") as kill,
            patch(
                "module.runtime.process_manager.is_current_owner", return_value=True
            ),
            patch(
                "module.runtime.process_manager.get_workers",
                return_value={"alas": {"pid": 12345, "created_at": 1}},
            ),
            patch("module.runtime.process_manager.process_matches", return_value=False),
            patch("module.runtime.process_manager.unregister_worker"),
        ):
            self.assertTrue(manager.stop())

        kill.assert_not_called()
        self.assertNotIn("alas", State.process_registry)

    def test_unowned_cross_session_worker_is_not_terminated(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")

        with (
            patch("module.runtime.process_manager.stop_process_tree") as kill,
            patch(
                "module.runtime.process_manager.is_current_owner", return_value=False
            ),
        ):
            self.assertFalse(manager.stop())

        kill.assert_not_called()
        self.assertEqual(12345, State.process_registry["alas"])

    def test_local_process_pid_reuse_is_not_terminated(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")
        process = Mock()
        process.pid = 12345
        process.is_alive.return_value = True
        manager._process = process

        with (
            patch("module.runtime.process_manager.stop_process_tree") as kill,
            patch(
                "module.runtime.process_manager.is_current_owner", return_value=True
            ),
            patch(
                "module.runtime.process_manager.get_workers",
                return_value={"alas": {"pid": 12345, "created_at": 1}},
            ),
            patch("module.runtime.process_manager.process_matches", return_value=False),
            patch("module.runtime.process_manager.unregister_worker"),
        ):
            self.assertFalse(manager.stop())

        kill.assert_not_called()
        # join(timeout=0) 是僵尸检测探针（不阻塞），不应与实际 join(timeout>0) 混淆
        join_calls = [c.kwargs.get("timeout") for c in process.join.call_args_list]
        self.assertNotIn(3, join_calls, "不应调用阻塞式 join(timeout=3)")
        self.assertIs(manager._process, process)
        self.assertNotIn("alas", State.process_registry)

    def test_start_waits_for_stop_lifecycle_lock(self):
        State.process_registry["alas"] = 12345
        manager = ProcessManager.get_manager("alas")
        starter_manager = ProcessManager("alas")
        old_process = Mock()
        old_process.pid = 12345
        old_process.is_alive.return_value = True
        manager._process = old_process

        stop_entered = threading.Event()
        release_stop = threading.Event()
        new_process_started = threading.Event()
        new_process = Mock()
        new_process.pid = 23456
        new_process.start.side_effect = new_process_started.set

        def kill_process_tree(*_, **__):
            stop_entered.set()
            release_stop.wait(timeout=2)
            return True

        with (
            patch(
                "module.runtime.process_manager.stop_process_tree", side_effect=kill_process_tree
            ),
            patch(
                "module.runtime.process_manager.is_current_owner", return_value=True
            ),
            patch(
                "module.runtime.process_manager.get_workers",
                return_value={"alas": {"pid": 12345, "created_at": 1}},
            ),
            patch("module.runtime.process_manager.process_matches", return_value=True),
            patch("module.runtime.process_manager.unregister_worker"),
            patch("module.runtime.process_manager.Process", return_value=new_process),
            patch.object(starter_manager, "_register_process"),
            patch.object(starter_manager, "start_log_queue_handler"),
            patch.object(
                ProcessManager,
                "alive",
                new_callable=PropertyMock,
                return_value=False,
            ),
        ):
            stopper = threading.Thread(target=manager.stop)
            starter = threading.Thread(target=lambda: starter_manager.start("alas"))
            stopper.start()
            self.assertTrue(stop_entered.wait(timeout=2))
            starter.start()
            self.assertFalse(new_process_started.wait(timeout=0.2))

            release_stop.set()
            stopper.join(timeout=2)
            starter.join(timeout=2)

        self.assertFalse(stopper.is_alive())
        self.assertFalse(starter.is_alive())
        self.assertTrue(new_process_started.is_set())

    def test_start_rejects_during_update_transaction(self):
        manager = ProcessManager.get_manager("alas")
        process_started = threading.Event()
        process = Mock()
        process.pid = 12345
        process.start.side_effect = process_started.set

        with (
            patch("module.runtime.process_manager.Process", return_value=process),
            patch.object(manager, "_register_process"),
            patch.object(manager, "start_log_queue_handler"),
            patch.object(
                ProcessManager,
                "alive",
                new_callable=PropertyMock,
                return_value=False,
            ),
        ):
            State.restart_lock.acquire()
            try:
                starter = threading.Thread(target=lambda: manager.start("alas"))
                starter.start()
                starter.join(timeout=2)
            finally:
                State.restart_lock.release()

        self.assertFalse(starter.is_alive())
        self.assertFalse(process_started.is_set())

    def test_start_rejects_during_webui_cleanup(self):
        manager = ProcessManager.get_manager("alas")
        process_started = threading.Event()
        process = Mock()
        process.pid = 12345
        process.start.side_effect = process_started.set

        with (
            patch("module.runtime.process_manager.Process", return_value=process),
            patch.object(manager, "_register_process"),
            patch.object(manager, "start_log_queue_handler"),
            patch.object(
                ProcessManager,
                "alive",
                new_callable=PropertyMock,
                return_value=False,
            ),
        ):
            State.cleanup_lock.acquire()
            try:
                starter = threading.Thread(target=lambda: manager.start("alas"))
                starter.start()
                starter.join(timeout=2)
            finally:
                State.cleanup_lock.release()

        self.assertFalse(starter.is_alive())
        self.assertFalse(process_started.is_set())

    def test_start_allows_reentrant_update_recovery(self):
        manager = ProcessManager.get_manager("alas")
        process_started = threading.Event()
        process = Mock()
        process.pid = 12345
        process.start.side_effect = process_started.set

        with (
            patch("module.runtime.process_manager.Process", return_value=process),
            patch.object(manager, "_register_process"),
            patch.object(manager, "start_log_queue_handler"),
            patch.object(
                ProcessManager,
                "alive",
                new_callable=PropertyMock,
                return_value=False,
            ),
        ):
            with State.restart_lock:
                manager.start("alas")

        self.assertTrue(process_started.is_set())

    def test_start_registration_failure_does_not_kill_exited_pid(self):
        manager = ProcessManager.get_manager("alas")
        process = Mock()
        process.pid = 12345
        process.is_alive.return_value = False

        with (
            patch("module.runtime.process_manager.Process", return_value=process),
            patch.object(manager, "_register_process", side_effect=RuntimeError("deny")),
        ):
            with self.assertRaises(RuntimeError):
                manager.start(func="alas")

        process.kill.assert_not_called()
        process.terminate.assert_not_called()
        process.join.assert_called_once_with(timeout=0)
        self.assertIsNone(manager._process)

    def test_failed_start_rollback_keeps_live_handle_and_prevents_duplicate_start(self):
        manager = ProcessManager.get_manager("alas")
        process = Mock(pid=12345)
        process.is_alive.return_value = True
        with (
            patch("module.runtime.process_manager.Process", return_value=process) as factory,
            patch.object(manager, "_register_process", side_effect=RuntimeError("登记失败")),
            patch("module.runtime.process_manager.stop_process_tree", return_value=False),
            patch("module.runtime.process_manager.stop_process", return_value=False) as stop_root,
        ):
            with self.assertRaises(RuntimeError):
                manager.start("alas")
            manager.start("alas")
        self.assertIs(manager._process, process)
        factory.assert_called_once()
        stop_root.assert_called_once_with(process, timeout=3)

    def test_start_rollback_stops_trusted_root_when_tree_enumeration_fails(self):
        manager = ProcessManager.get_manager("alas")
        process = Mock(pid=12345)
        process.is_alive.return_value = True
        process.terminate.side_effect = lambda: setattr(process.is_alive, "return_value", False)
        with (
            patch("module.runtime.process_manager.Process", return_value=process),
            patch.object(manager, "_register_process", side_effect=RuntimeError("登记失败")),
            patch("module.runtime.process_manager.stop_process_tree", return_value=False),
        ):
            with self.assertRaises(RuntimeError):
                manager.start("alas")
        process.terminate.assert_called_once_with()
        process.join.assert_any_call(timeout=3)
        self.assertIsNone(manager._process)

    def test_stop_by_user_stay_there_uses_original_stop_path(self):
        manager = ProcessManager.get_manager("alas")

        with (
            patch.object(manager, "stop", return_value=True) as stop,
            patch.object(manager, "_stop_worker_locked") as stop_worker,
            patch.object(manager, "_run_manual_stop_action_locked") as action,
        ):
            self.assertTrue(manager.stop_by_user("stay_there"))

        stop.assert_called_once_with()
        stop_worker.assert_not_called()
        action.assert_not_called()

    def test_stop_by_user_runs_action_after_confirmed_worker_stop(self):
        manager = ProcessManager.get_manager("alas")

        with (
            patch.object(manager, "_stop_worker_locked", return_value=(True, True)),
            patch.object(manager, "_run_manual_stop_action_locked") as action,
        ):
            self.assertTrue(manager.stop_by_user("goto_main"))

        action.assert_called_once_with()

    def test_stop_by_user_without_action_keeps_legacy_config_resolution(self):
        manager = ProcessManager.get_manager("alas")

        with (
            patch.object(manager, "_stop_worker_locked", return_value=(True, True)),
            patch.object(manager, "_run_manual_stop_action_locked") as action,
        ):
            self.assertTrue(manager.stop_by_user())

        action.assert_called_once_with()

    def test_stop_by_user_skips_action_when_worker_stop_fails(self):
        manager = ProcessManager.get_manager("alas")

        with (
            patch.object(manager, "_stop_worker_locked", return_value=(False, True)),
            patch.object(manager, "_run_manual_stop_action_locked") as action,
        ):
            self.assertFalse(manager.stop_by_user("close_game"))

        action.assert_not_called()

    def test_stop_by_user_skips_action_without_a_confirmed_worker(self):
        manager = ProcessManager.get_manager("alas")

        with (
            patch.object(manager, "_stop_worker_locked", return_value=(True, False)),
            patch.object(manager, "_run_manual_stop_action_locked") as action,
        ):
            self.assertTrue(manager.stop_by_user("close_emulator"))

        action.assert_not_called()

    def test_generic_stop_does_not_run_manual_stop_action(self):
        manager = ProcessManager.get_manager("alas")

        with (
            patch.object(manager, "_stop_worker_locked", return_value=(True, True)),
            patch.object(manager, "_run_manual_stop_action_locked") as action,
        ):
            self.assertTrue(manager.stop())

        action.assert_not_called()

    def test_manual_stop_action_uses_isolated_process_with_timeout(self):
        manager = ProcessManager.get_manager("alas")
        process = Mock()
        process.is_alive.return_value = False
        process.exitcode = 0

        with patch("module.runtime.process_manager.Process", return_value=process) as cls:
            manager._run_manual_stop_action_locked()

        cls.assert_called_once_with(
            target=ProcessManager.run_manual_stop_action,
            args=("alas",),
        )
        process.start.assert_called_once_with()
        process.join.assert_called_once_with(
            timeout=ProcessManager.MANUAL_STOP_ACTION_TIMEOUT
        )

    def test_manual_stop_action_timeout_terminates_helper(self):
        manager = ProcessManager.get_manager("alas")
        process = Mock()
        process.is_alive.return_value = True

        with (
            patch("module.runtime.process_manager.Process", return_value=process),
            patch.object(
                ProcessManager, "_terminate_manual_stop_action"
            ) as terminate,
        ):
            manager._run_manual_stop_action_locked()

        terminate.assert_called_once_with(process)
