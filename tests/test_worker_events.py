"""结构化 worker 结果及退出时队列排空的回归测试。"""

import multiprocessing
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.text import Text

from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State
from module.runtime.worker_events import ExitEvent, TaskEvent, WorkerResult


def emit_final_messages(output):
    """仅发送事件的真实子进程，不导入设备或运行游戏。"""
    output.put(TaskEvent("run", "Commission"))
    output.put(Text("任意收尾日志"))
    output.put(ExitEvent("run", WorkerResult.UPDATE))


class TestWorkerEvents(unittest.TestCase):
    def setUp(self):
        self.manager_patch = patch.object(State, "manager", Mock())
        manager = self.manager_patch.start()
        manager.Queue.side_effect = queue.Queue
        self.addCleanup(self.manager_patch.stop)
        self.registry_patch = patch.object(State, "process_registry", {})
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        self.manager = ProcessManager("event-test")
        self.manager.run_id = "run"
        from module.runtime import worker_events

        self.addCleanup(worker_events.initialize, None, None)

    def test_logs_cannot_change_structured_state(self):
        for result, state in ((WorkerResult.FINISHED, 2), (WorkerResult.UPDATE, 4),
                              (WorkerResult.ERROR, 3), (WorkerResult.MANUAL_STOP, 2)):
            with self.subTest(result=result):
                self.manager.exit_result = result
                self.manager.renderables = [Text("原因: 更新 | Reason: Update"),
                                            Text("原因: 手动停止 | Reason: Manual stop")]
                self.assertEqual(self.manager.state, state)
                self.manager.renderables = [Text("所有日志措辞均已替换")] * 20
                self.assertEqual(self.manager.state, state)

    def test_missing_exit_event_is_error_even_with_finish_log(self):
        self.manager.renderables.append(Text("Reason: Finish"))
        self.assertEqual(self.manager.state, 3)

    def test_unused_manager_is_stopped_regardless_of_logs(self):
        self.manager.run_id = None
        self.manager.renderables.append(Text("任意提示"))
        self.assertEqual(self.manager.state, 2)

    def test_previous_run_events_are_ignored(self):
        self.manager._consume_worker_message(TaskEvent("old", "Main"), "run")
        self.manager._consume_worker_message(ExitEvent("old", WorkerResult.UPDATE), "run")
        self.assertIsNone(self.manager.current_task)
        self.assertIsNone(self.manager.exit_result)
        self.manager._consume_worker_message(TaskEvent("run", "Commission"), "run")
        self.assertEqual(self.manager.current_task, "Commission")
        self.manager._consume_worker_message(ExitEvent("run", WorkerResult.FINISHED), "run")
        self.manager._consume_worker_message(TaskEvent("run", "Main"), "run")
        self.assertIsNone(self.manager.current_task)

    def test_manual_stop_wins_over_delayed_exit_event(self):
        self.manager.exit_result = WorkerResult.MANUAL_STOP
        self.manager._renderable_queue.put(ExitEvent("run", WorkerResult.UPDATE))
        self.manager._process = SimpleNamespace(exitcode=-15, is_alive=lambda: False)
        self.assertEqual(self.manager.state, 2)
        self.assertEqual(self.manager.exit_result, WorkerResult.MANUAL_STOP)

    def test_abnormal_exit_code_wins_over_completed_event(self):
        self.manager._process = SimpleNamespace(exitcode=1, is_alive=lambda: False)
        self.manager._renderable_queue.put(ExitEvent("run", WorkerResult.FINISHED))
        self.assertEqual(self.manager.state, 3)

    def test_startup_failure_cannot_be_replaced_by_delayed_completion(self):
        self.manager.exit_result = WorkerResult.ERROR
        self.manager._renderable_queue.put(ExitEvent("run", WorkerResult.FINISHED))
        self.assertEqual(self.manager.state, 3)

    def test_discarded_local_handle_keeps_abnormal_exit_code(self):
        self.manager._process = SimpleNamespace(exitcode=1)
        self.manager._renderable_queue.put(ExitEvent("run", WorkerResult.FINISHED))

        def detach():
            self.manager._process = None
            return False

        with patch.object(ProcessManager, "alive", property(lambda _: detach())):
            self.assertEqual(self.manager.state, 3)

    def test_unverified_registered_worker_is_not_reported_as_unused(self):
        self.manager.run_id = None
        with patch.object(self.manager, "_registered_pid", return_value=(12345, False)):
            self.assertEqual(self.manager.state, 3)

    def test_state_override_still_takes_priority(self):
        self.manager.exit_result = WorkerResult.ERROR
        self.manager.set_state_override(4, duration=0)
        self.assertEqual(self.manager.state, 4)
        self.manager.clear_state_override()
        self.assertEqual(self.manager.state, 3)

    def test_state_drains_exit_event_before_reader_starts(self):
        self.manager._renderable_queue.put(TaskEvent("run", "Main"))
        self.manager._renderable_queue.put(ExitEvent("run", WorkerResult.UPDATE))
        self.assertEqual(self.manager.state, 4)
        self.assertIsNone(self.manager.current_task)

    def test_reader_drains_messages_from_already_exited_process(self):
        context = multiprocessing.get_context("spawn")
        with context.Manager() as shared:
            output = shared.Queue()
            process = context.Process(target=emit_final_messages, args=(output,))
            process.start()
            process.join(timeout=10)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
            self.manager._thread_log_queue_handler(output, process, "run")
        self.assertEqual(self.manager.exit_result, WorkerResult.UPDATE)
        self.assertIsNone(self.manager.current_task)
        self.assertEqual(len(self.manager.renderables), 1)

    def test_exit_between_queue_timeout_and_alive_check_is_drained(self):
        output = queue.Queue()

        def process_exits(_):
            output.put(ExitEvent("run", WorkerResult.FINISHED))
            return False

        with patch.object(ProcessManager, "_is_process_alive", side_effect=process_exits):
            self.manager._thread_log_queue_handler(output, object(), "run")
        self.assertEqual(self.manager.exit_result, WorkerResult.FINISHED)

    def test_old_reader_does_not_consume_new_queue(self):
        old_output = queue.Queue()
        old_output.put(ExitEvent("old", WorkerResult.UPDATE))
        self.manager._renderable_queue.put(ExitEvent("run", WorkerResult.FINISHED))
        self.manager._thread_log_queue_handler(old_output, None, "old")
        self.assertIsNone(self.manager.exit_result)
        self.assertEqual(self.manager.state, 2)

    def test_reader_does_not_need_lifecycle_lock_to_finish(self):
        output = queue.Queue()
        output.put(ExitEvent("run", WorkerResult.FINISHED))
        with ProcessManager._get_lifecycle_lock(self.manager.config_name):
            reader = threading.Thread(target=self.manager._thread_log_queue_handler,
                                      args=(output, None, "run"), daemon=True)
            reader.start()
            reader.join(timeout=2)
            self.assertFalse(reader.is_alive())

    def test_start_cannot_replace_run_during_stopped_state_read(self):
        self.manager._process = SimpleNamespace(exitcode=1, is_alive=lambda: False)
        state_entered = threading.Event()
        release_state = threading.Event()
        process_started = threading.Event()
        new_process = Mock(pid=23456)
        new_process.start.side_effect = process_started.set
        observed = []

        def drain(*_):
            state_entered.set()
            release_state.wait(timeout=2)

        with (patch.object(self.manager, "_drain_worker_queue", side_effect=drain),
              patch("module.runtime.process_manager.Process", return_value=new_process),
              patch.object(self.manager, "_register_process"),
              patch.object(self.manager, "start_log_queue_handler"),
              patch.object(State, "_clearup", False),
              patch.object(State, "_restart_requested", False)):
            reader = threading.Thread(target=lambda: observed.append(self.manager.state))
            starter = threading.Thread(target=lambda: self.manager.start("alas"))
            reader.start()
            try:
                self.assertTrue(state_entered.wait(timeout=2))
                starter.start()
                self.assertFalse(process_started.wait(timeout=0.1))
            finally:
                release_state.set()
                reader.join(timeout=2)
                if starter.ident is not None:
                    starter.join(timeout=2)
            self.assertFalse(reader.is_alive())
            self.assertFalse(starter.is_alive())
        self.assertEqual(observed, [3])
        self.assertTrue(process_started.is_set())

    def test_old_reader_lock_does_not_block_new_run_state(self):
        old_output = queue.Queue()
        old_lock = threading.Lock()
        old_lock.acquire()
        self.manager._renderable_queue.put(ExitEvent("run", WorkerResult.FINISHED))
        reader = threading.Thread(target=self.manager._thread_log_queue_handler,
                                  args=(old_output, None, "old", old_lock), daemon=True)
        reader.start()
        try:
            self.assertEqual(self.manager.state, 2)
        finally:
            old_lock.release()
            reader.join(timeout=2)
        self.assertFalse(reader.is_alive())

    def test_worker_entry_publishes_errors_and_system_exit_results(self):
        for error, updating, expected in (
            (RuntimeError("失败"), False, WorkerResult.ERROR),
            (SystemExit(0), False, WorkerResult.FINISHED),
            (SystemExit(0), True, WorkerResult.UPDATE),
            (SystemExit(1), True, WorkerResult.ERROR),
            (KeyboardInterrupt(), False, WorkerResult.ERROR),
        ):
            with self.subTest(error=error, updating=updating):
                output = queue.Queue()
                event = threading.Event()
                if updating:
                    event.set()
                with patch.object(ProcessManager, "_run_process", side_effect=error), \
                        patch("module.runtime.process_manager.logger"):
                    if isinstance(error, Exception):
                        ProcessManager.run_process("test", "alas", output, event, run_id="run")
                    else:
                        with self.assertRaises(type(error)):
                            ProcessManager.run_process("test", "alas", output, event, run_id="run")
                self.assertEqual(output.get_nowait(), ExitEvent("run", expected))
                self.assertTrue(output.empty())

    def test_task_events_work_without_preview_channel(self):
        from module.runtime.preview import set_task

        output = queue.Queue()

        def run(*_):
            set_task("Main")
            set_task(None)
            return WorkerResult.FINISHED

        with patch.object(ProcessManager, "_run_process", side_effect=run):
            ProcessManager.run_process("test", "Main", output, run_id="run")
        self.assertEqual(output.get_nowait(), TaskEvent("run", "Main"))
        self.assertEqual(output.get_nowait(), TaskEvent("run", None))
        self.assertEqual(output.get_nowait(), ExitEvent("run", WorkerResult.FINISHED))

    def test_dispatch_distinguishes_task_failure_and_update(self):
        config_module = SimpleNamespace(AzurLaneConfig=type("FakeConfig", (), {}))
        script = Mock()
        alas_module = SimpleNamespace(AzurLaneAutoScript=Mock(return_value=script))
        for task_result, updating, expected in (
            (True, False, WorkerResult.FINISHED),
            (False, False, WorkerResult.ERROR),
            (False, True, WorkerResult.ERROR),
            ("recoverable", False, WorkerResult.ERROR),
            (True, True, WorkerResult.UPDATE),
        ):
            with self.subTest(task_result=task_result, updating=updating):
                script.run.return_value = task_result
                event = threading.Event()
                if updating:
                    event.set()
                output = queue.Queue()
                with (patch.dict("sys.modules", {"module.config.config": config_module,
                                                 "alas": alas_module}),
                      patch.dict("os.environ", {"DEMO": "0"}),
                      patch("module.runtime.process_manager.set_file_logger"),
                      patch("module.runtime.process_manager.set_func_logger"),
                      patch("module.runtime.process_manager.logger"),
                      patch("module.runtime.process_manager.get_available_func", return_value=["Main"])):
                    ProcessManager.run_process("test", "Main", output, event, run_id="run")
                self.assertEqual(output.get_nowait(), ExitEvent("run", expected))
