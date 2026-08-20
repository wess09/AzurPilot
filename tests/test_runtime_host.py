"""单进程运行时宿主的纯标准库契约测试。"""

import threading
import time
import unittest

from module.base.runtime_context import current_runtime_id
from module.webui.runtime_host import (
    RuntimeHost,
    RuntimeHostClosedError,
    WorkerAlreadyRunningError,
    WorkerSpec,
    WorkerSpecValidationError,
    WorkerStatus,
    validate_worker_specs,
)


class TestRuntimeHost(unittest.TestCase):
    def test_worker_lifecycle_stop_and_log_delivery(self):
        host = RuntimeHost()
        entered = threading.Event()

        def worker(control):
            entered.set()
            control.log("debug", "worker 已进入循环")
            control.wait(1)
            return "stopped"

        handle = host.start_worker("alpha", worker)
        self.assertTrue(entered.wait(1))
        self.assertTrue(host.stop_worker("alpha", timeout=1, reason="测试停止"))

        self.assertEqual(WorkerStatus.STOPPED, handle.status)
        self.assertEqual("stopped", handle.result)
        self.assertEqual("测试停止", handle.control.stop_reason)
        records = host.drain_logs()
        self.assertTrue(
            any(
                record.config_name == "alpha"
                and record.level == "DEBUG"
                and record.message == "worker 已进入循环"
                for record in records
            )
        )

    def test_worker_exception_is_saved_as_text_snapshot(self):
        host = RuntimeHost()

        def worker(_control):
            raise RuntimeError("预期失败")

        handle = host.start_worker("broken", worker)
        self.assertTrue(handle.join(1))

        self.assertEqual(WorkerStatus.FAILED, handle.status)
        self.assertIsNotNone(handle.error)
        self.assertEqual("RuntimeError", handle.error.exception_type)
        self.assertIn("预期失败", handle.traceback)
        records = host.drain_logs()
        self.assertTrue(
            any(
                record.config_name == "broken"
                and record.level == "ERROR"
                and "RuntimeError" in record.message
                for record in records
            )
        )

    def test_duplicate_active_worker_is_rejected_and_terminal_worker_can_restart(self):
        host = RuntimeHost()
        entered = threading.Event()

        def blocking_worker(control):
            entered.set()
            control.wait(1)

        first = host.start_worker("same", blocking_worker)
        self.assertTrue(entered.wait(1))
        with self.assertRaises(WorkerAlreadyRunningError):
            host.start_worker("same", blocking_worker)

        self.assertTrue(host.stop_worker("same", timeout=1))
        self.assertEqual(WorkerStatus.STOPPED, first.status)
        second = host.start_worker("same", lambda _control: "new")
        self.assertTrue(second.join(1))
        self.assertEqual("new", second.result)

    def test_same_name_waits_for_old_thread_runtime_cleanup_before_restart(self):
        host = RuntimeHost()
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()
        original_clear = host._clear_worker_runtime_context

        def slow_cleanup(config_name):
            cleanup_started.set()
            release_cleanup.wait(1)
            original_clear(config_name)

        host._clear_worker_runtime_context = slow_cleanup
        first = host.start_worker("same", lambda _control: None)
        self.assertTrue(cleanup_started.wait(1))
        self.assertEqual(WorkerStatus.STOPPED, first.status)
        with self.assertRaises(WorkerAlreadyRunningError):
            host.start_worker("same", lambda _control: None)

        release_cleanup.set()
        self.assertTrue(first.join(1))
        second = host.start_worker("same", lambda _control: "restarted")
        self.assertTrue(second.join(1))
        self.assertEqual("restarted", second.result)

    def test_stop_timeout_does_not_force_kill_thread(self):
        host = RuntimeHost()
        entered = threading.Event()
        release = threading.Event()

        def uncooperative_worker(_control):
            entered.set()
            release.wait(1)

        handle = host.start_worker("uncooperative", uncooperative_worker)
        self.assertTrue(entered.wait(1))
        try:
            self.assertFalse(host.stop_worker("uncooperative", timeout=0))
            self.assertTrue(handle.is_alive())
            self.assertEqual(WorkerStatus.STOPPING, handle.status)
        finally:
            release.set()
            self.assertTrue(handle.join(1))
        self.assertEqual(WorkerStatus.STOPPED, handle.status)

    def test_shutdown_rejects_new_worker(self):
        host = RuntimeHost()
        self.assertEqual({}, host.shutdown(timeout=0))
        self.assertTrue(host.closed)
        with self.assertRaises(RuntimeHostClosedError):
            host.start_worker("later", lambda _control: None)

    def test_target_runs_in_matching_runtime_scope(self):
        host = RuntimeHost()
        runtime_ids = []

        handle = host.start_worker(
            "scoped",
            lambda _control: runtime_ids.append(current_runtime_id()),
        )
        self.assertTrue(handle.join(1))

        self.assertEqual(["scoped"], runtime_ids)

    def test_drain_logs_honors_limit_without_losing_order(self):
        host = RuntimeHost()
        host._publish_log("alpha", "info", "first")
        host._publish_log("alpha", "info", "second")

        first = host.drain_logs(max_items=1)
        second = host.drain_logs()

        self.assertEqual(["first"], [record.message for record in first])
        self.assertEqual(["second"], [record.message for record in second])
        self.assertEqual([], host.drain_logs(max_items=0))


class TestWorkerSpecValidation(unittest.TestCase):
    @staticmethod
    def make_spec(name, device, **kwargs):
        options = {
            "server": "cn",
            "package": "com.bilibili.blhx",
            "use_ocr_server": True,
            "ocr_address": "127.0.0.1:22268",
        }
        options.update(kwargs)
        return WorkerSpec(
            config_name=name,
            emulator_server_name=device,
            **options,
        )

    def test_compatible_specs_are_normalized(self):
        specs = validate_worker_specs(
            [
                self.make_spec(" alpha ", "127.0.0.1:5555"),
                self.make_spec("beta", "127.0.0.1:5556"),
            ]
        )

        self.assertEqual(("alpha", "beta"), tuple(spec.config_name for spec in specs))

    def test_rejects_shared_global_or_device_state(self):
        cases = (
            [
                self.make_spec("alpha", "127.0.0.1:5555"),
                self.make_spec("beta", "127.0.0.1:5556", server="jp"),
            ],
            [
                self.make_spec("alpha", "127.0.0.1:5555"),
                self.make_spec("beta", "127.0.0.1:5556", package="com.example.other"),
            ],
            [
                self.make_spec("alpha", "127.0.0.1:5555"),
                self.make_spec("beta", "127.0.0.1:5555"),
            ],
            [self.make_spec("alpha", "auto")],
            [self.make_spec("alpha", "127.0.0.1:5555", control_method="nemu_ipc")],
            [self.make_spec("alpha", "127.0.0.1:5555", screenshot_method="NemuIpc")],
        )

        for specs in cases:
            with self.subTest(specs=specs):
                with self.assertRaises(WorkerSpecValidationError):
                    validate_worker_specs(specs)

    def test_ocr_enabled_requires_same_explicit_address(self):
        with self.assertRaises(WorkerSpecValidationError):
            validate_worker_specs(
                [
                    self.make_spec("alpha", "127.0.0.1:5555"),
                    self.make_spec("beta", "127.0.0.1:5556", ocr_address="127.0.0.1:22269"),
                ]
            )
        with self.assertRaises(WorkerSpecValidationError):
            validate_worker_specs(
                [
                    self.make_spec(
                        "alpha",
                        "127.0.0.1:5555",
                        ocr_address=None,
                    )
                ]
            )


if __name__ == "__main__":
    unittest.main()
