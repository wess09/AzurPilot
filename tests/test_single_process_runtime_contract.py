"""单进程多实例运行时的跨层契约测试。

底层线程宿主的生命周期测试在 ``test_runtime_host.py``；这里验证部署开关、
实例规格、可变资源状态以及宿主与运行态上下文之间的边界。测试不会启动真实
Alas、ADB、OCR 或 WebUI。
"""

import queue
import threading
import time
import unittest
from unittest import mock

import numpy as np

# 某些 WebUI 导入路径会先注入轻量 fake PIL；资源隔离测试需要真实 Pillow，
# 因此在导入 Button 前显式撤销该测试替身，避免 unittest 顺序影响结果。
from module.webui.fake_pil_module import remove_fake_pil_module

remove_fake_pil_module()

from deploy.config import ConfigModel
from deploy.Windows.config import ConfigModel as WindowsConfigModel
from module.base.button import Button
from module.base.filter import Filter
from module.base.runtime_context import (
    RuntimeContext,
    clear_runtime_context,
    clear_runtime_state,
    current_runtime_id,
    get_runtime_context,
    runtime_scope,
    runtime_state,
)
from module.base.timer import Timer
from module.ui.page import Page
from module.ocr.ocr import Digit
from module.statistics.item import ItemGrid
from module.webui.runtime_host import (
    RuntimeHost,
    WorkerSpec,
    WorkerSpecValidationError,
    WorkerStatus,
    validate_worker_specs,
)
from module.webui.single_process_runtime import SingleProcessRuntime
from module.webui.single_process_runtime import RuntimeWorkerState


class TestSingleProcessDeploymentContract(unittest.TestCase):
    def test_deployment_switch_is_explicitly_disabled_by_default(self):
        """升级后不得在未经用户确认时改变原有进程隔离模型。"""
        self.assertIs(ConfigModel.SingleProcessInstances, False)
        self.assertIs(WindowsConfigModel.SingleProcessInstances, False)


class TestRuntimeWorkerSpecContract(unittest.TestCase):
    @staticmethod
    def make_spec(
        config_name="alas",
        emulator_server_name="127.0.0.1:5555",
        server="cn",
        package="com.bilibili.azurlane",
        use_ocr_server=True,
        ocr_address="127.0.0.1:22268",
        control_method=None,
        screenshot_method=None,
    ):
        return WorkerSpec(
            config_name=config_name,
            server=server,
            package=package,
            emulator_server_name=emulator_server_name,
            use_ocr_server=use_ocr_server,
            ocr_address=ocr_address,
            control_method=control_method,
            screenshot_method=screenshot_method,
        )

    def test_same_host_rejects_mixed_ocr_modes_before_any_worker_starts(self):
        remote = self.make_spec(config_name="alpha")
        local = self.make_spec(
            config_name="beta",
            emulator_server_name="127.0.0.1:5556",
            use_ocr_server=False,
            ocr_address=None,
        )

        with self.assertRaises(WorkerSpecValidationError):
            validate_worker_specs((remote, local))

    def test_same_host_rejects_duplicate_normalized_configuration_name(self):
        first = self.make_spec(config_name=" alpha ")
        duplicate = self.make_spec(
            config_name="alpha",
            emulator_server_name="127.0.0.1:5556",
        )

        with self.assertRaises(WorkerSpecValidationError):
            validate_worker_specs((first, duplicate))

    def test_same_host_rejects_auto_device_methods(self):
        auto_method = self.make_spec(control_method='auto')

        with self.assertRaises(WorkerSpecValidationError):
            validate_worker_specs((auto_method,))


class TestRuntimeContextContract(unittest.TestCase):
    def test_scope_restores_outer_context_and_keeps_explicit_contexts_isolated(self):
        owner = object()
        alpha_context = RuntimeContext("alpha")
        beta_context = RuntimeContext("beta")

        self.assertIsNone(get_runtime_context())
        self.assertIsNone(current_runtime_id())
        self.assertIsNone(runtime_state(owner, "value", dict))

        with runtime_scope(context=alpha_context):
            self.assertIs(get_runtime_context(), alpha_context)
            self.assertEqual("alpha", current_runtime_id())
            alpha_value = runtime_state(owner, "value", dict)
            alpha_value["instance"] = "alpha"

            with runtime_scope(context=beta_context):
                self.assertIs(get_runtime_context(), beta_context)
                self.assertEqual("beta", current_runtime_id())
                beta_value = runtime_state(owner, "value", dict)
                self.assertEqual({}, beta_value)
                beta_value["instance"] = "beta"

            self.assertIs(get_runtime_context(), alpha_context)
            self.assertEqual(
                {"instance": "alpha"}, runtime_state(owner, "value", dict)
            )

        self.assertIsNone(get_runtime_context())
        with runtime_scope(context=beta_context):
            self.assertEqual(
                {"instance": "beta"}, runtime_state(owner, "value", dict)
            )

    def test_worker_context_is_reused_until_explicitly_released(self):
        owner = object()
        with runtime_scope("finished-worker"):
            runtime_state(owner, "value", dict)["completed"] = True

        with runtime_scope("finished-worker"):
            self.assertEqual(
                {"completed": True}, runtime_state(owner, "value", dict)
            )

        self.assertEqual(1, clear_runtime_context("finished-worker"))
        with runtime_scope("finished-worker"):
            self.assertEqual({}, runtime_state(owner, "value", dict))

    def test_child_thread_does_not_implicitly_inherit_parent_scope(self):
        observed = queue.Queue()

        def child():
            observed.put(current_runtime_id())
            with runtime_scope("child"):
                observed.put(current_runtime_id())
            observed.put(current_runtime_id())

        with runtime_scope("parent"):
            thread = threading.Thread(target=child)
            thread.start()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(
            [None, "child", None], [observed.get_nowait() for _ in range(3)]
        )
        clear_runtime_context("parent")
        clear_runtime_context("child")

    def test_clear_runtime_state_only_clears_current_worker_context(self):
        owner = object()
        alpha_context = RuntimeContext("alpha")
        beta_context = RuntimeContext("beta")

        with runtime_scope(context=alpha_context):
            runtime_state(owner, "state", dict)["value"] = "alpha"
        with runtime_scope(context=beta_context):
            runtime_state(owner, "state", dict)["value"] = "beta"

        with runtime_scope(context=alpha_context):
            self.assertEqual(1, clear_runtime_state(owner, "state"))
            self.assertEqual({}, runtime_state(owner, "state", dict))
        with runtime_scope(context=beta_context):
            self.assertEqual(
                {"value": "beta"}, runtime_state(owner, "state", dict)
            )

    def test_timer_button_and_page_runtime_fields_do_not_cross_instances(self):
        timer = Timer(60)
        button = Button(
            area=(0, 0, 10, 10),
            color=(255, 255, 255),
            button=(10, 20, 30, 40),
            name="RUNTIME_CONTEXT_BUTTON",
        )
        reference = Button(
            area=(0, 0, 10, 10),
            color=(255, 255, 255),
            button=(30, 50, 50, 70),
            name="RUNTIME_CONTEXT_REFERENCE",
        )
        # 绕过 Page 的模块级页面注册，单独验证 parent 属性的运行态隔离。
        page = object.__new__(Page)
        page.__dict__["_runtime_parent"] = None
        alpha_context = RuntimeContext("alpha")
        beta_context = RuntimeContext("beta")

        with runtime_scope(context=alpha_context):
            timer.start().add_count()
            button._button_offset = reference.button
            button.area = (1, 2, 11, 12)
            button._button = (2, 3, 12, 13)
            button.name = "alpha-button"
            page.parent = "alpha-parent"
            self.assertEqual(1, timer.current_count())
            self.assertEqual((30, 50, 50, 70), button.button)
            self.assertEqual((1, 2, 11, 12), button.area)
            self.assertEqual((2, 3, 12, 13), button._button)
            self.assertEqual("alpha-button", button.name)
            self.assertEqual("alpha-parent", page.parent)

        with runtime_scope(context=beta_context):
            self.assertFalse(timer.started())
            self.assertEqual(0, timer.current_count())
            self.assertEqual((10, 20, 30, 40), button.button)
            self.assertEqual((0, 0, 10, 10), button.area)
            self.assertEqual((10, 20, 30, 40), button._button)
            self.assertEqual("RUNTIME_CONTEXT_BUTTON", button.name)
            self.assertIsNone(page.parent)
            timer.start().add_count().add_count()
            page.parent = "beta-parent"

        with runtime_scope(context=alpha_context):
            self.assertEqual(1, timer.current_count())
            self.assertEqual((30, 50, 50, 70), button.button)
            self.assertEqual((1, 2, 11, 12), button.area)
            self.assertEqual((2, 3, 12, 13), button._button)
            self.assertEqual("alpha-button", button.name)
            self.assertEqual("alpha-parent", page.parent)

    def test_filter_and_ocr_dynamic_regions_do_not_cross_instances(self):
        filter_ = Filter(r'^(.*)$', attr=('name',))
        ocr = Digit((0, 0, 10, 10), name='RUNTIME_CONTEXT_OCR')
        alpha_context = RuntimeContext('alpha')
        beta_context = RuntimeContext('beta')

        with runtime_scope(context=alpha_context):
            filter_.load('alpha')
            ocr.buttons = (1, 2, 3, 4)
            self.assertEqual(['alpha'], filter_.filter_raw)
            self.assertEqual([(1, 2, 3, 4)], ocr.buttons)

        with runtime_scope(context=beta_context):
            self.assertEqual([], filter_.filter_raw)
            self.assertEqual([(0, 0, 10, 10)], ocr.buttons)
            filter_.load('beta')
            ocr.buttons = (5, 6, 7, 8)

        with runtime_scope(context=alpha_context):
            self.assertEqual(['alpha'], filter_.filter_raw)
            self.assertEqual([(1, 2, 3, 4)], ocr.buttons)

    def test_item_grid_shares_template_arrays_but_isolates_results(self):
        grid = ItemGrid(None, {})
        alpha_context = RuntimeContext('alpha-items')
        beta_context = RuntimeContext('beta-items')
        template = np.zeros((4, 4, 3), dtype=np.uint8)

        with runtime_scope(context=alpha_context):
            grid.templates['shared'] = template
            grid.colors['shared'] = (0, 0, 0)
            grid.items = ['alpha-result']

        with runtime_scope(context=beta_context):
            self.assertIs(grid.templates['shared'], template)
            self.assertEqual([], grid.items)
            grid.items = ['beta-result']

        with runtime_scope(context=alpha_context):
            self.assertEqual(['alpha-result'], grid.items)

        clear_runtime_context('alpha-items')
        clear_runtime_context('beta-items')


class TestRuntimeHostContextContract(unittest.TestCase):
    def setUp(self):
        self.host = RuntimeHost()

    def tearDown(self):
        self.host.shutdown(timeout=2)

    @staticmethod
    def wait_until(predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_host_enters_matching_runtime_scope_for_each_worker(self):
        observed = queue.Queue()
        started = threading.Event()

        def worker(control):
            observed.put((control.config_name, current_runtime_id()))
            started.set()
            control.wait()

        with runtime_scope("webui-parent"):
            handle = self.host.start_worker("alpha", worker)

        self.assertTrue(started.wait(timeout=2))
        self.assertEqual(("alpha", "alpha"), observed.get_nowait())
        self.assertEqual(WorkerStatus.RUNNING, handle.status)

    def test_stopping_one_worker_keeps_another_workers_context_and_status(self):
        alpha_started = threading.Event()
        beta_started = threading.Event()
        observed = queue.Queue()

        def worker(control, started):
            observed.put(current_runtime_id())
            started.set()
            control.wait()

        alpha = self.host.start_worker("alpha", worker, alpha_started)
        beta = self.host.start_worker("beta", worker, beta_started)

        self.assertTrue(alpha_started.wait(timeout=2))
        self.assertTrue(beta_started.wait(timeout=2))
        self.assertEqual({"alpha", "beta"}, {observed.get_nowait(), observed.get_nowait()})

        self.assertTrue(self.host.stop_worker("alpha", timeout=2, reason="用户停止"))
        self.assertEqual(WorkerStatus.STOPPED, alpha.status)
        self.assertEqual("用户停止", alpha.control.stop_reason)
        self.assertTrue(beta.is_alive())
        self.assertEqual(WorkerStatus.RUNNING, beta.status)

    def test_failed_worker_does_not_stop_peer_and_preserves_failure_snapshot(self):
        peer_started = threading.Event()

        def fail(_control):
            raise LookupError("预期的 worker 异常")

        def wait_for_stop(control):
            peer_started.set()
            control.wait()

        failed = self.host.start_worker("failed", fail)
        peer = self.host.start_worker("peer", wait_for_stop)

        self.assertTrue(peer_started.wait(timeout=2))
        self.assertTrue(self.wait_until(lambda: failed.status is WorkerStatus.FAILED))
        self.assertIsNotNone(failed.failure)
        self.assertEqual("LookupError", failed.failure.exception_type)
        self.assertIn("预期的 worker 异常", failed.failure.traceback_text)
        self.assertTrue(peer.is_alive())
        self.assertEqual(WorkerStatus.RUNNING, peer.status)

        failed_logs = [
            record
            for record in self.host.drain_logs()
            if record.config_name == "failed"
        ]
        self.assertTrue(failed_logs)
        self.assertTrue(any(record.traceback_text for record in failed_logs))


class TestSingleProcessIpcContract(unittest.TestCase):
    def test_unpicklable_thread_event_is_rejected_before_host_start(self):
        with self.assertRaises(TypeError):
            SingleProcessRuntime._validate_transferable(
                threading.Event(), 'update_event'
            )

    def test_terminal_worker_state_is_not_overwritten_by_late_shutdown_event(self):
        runtime = SingleProcessRuntime()
        runtime._states['alpha'] = RuntimeWorkerState(
            status=WorkerStatus.FAILED.value,
            error='原始启动失败',
            generation=3,
            accepted=True,
        )

        with runtime._lock:
            runtime._apply_worker_state_event_locked({
                'config_name': 'alpha',
                'status': WorkerStatus.STOPPED.value,
                'generation': 3,
            })

        self.assertEqual(WorkerStatus.FAILED.value, runtime.status('alpha'))
        self.assertEqual('原始启动失败', runtime.error('alpha'))

    def test_event_channel_failure_marks_active_workers_failed(self):
        class BrokenQueue:
            def get(self, timeout=None):
                raise OSError('模拟 IPC 断链')

        class LiveProcess:
            def is_alive(self):
                return True

        runtime = SingleProcessRuntime()
        runtime._process = LiveProcess()
        runtime._event_queue = BrokenQueue()
        runtime._host_epoch = 1
        runtime._states['alpha'] = RuntimeWorkerState(
            status=WorkerStatus.RUNNING.value,
            generation=1,
            accepted=True,
        )

        with mock.patch.object(
            runtime, '_process_alive', return_value=True
        ), mock.patch.object(
            runtime, '_terminate_host_locked', return_value=True
        ):
            runtime._event_loop(runtime._event_queue, runtime._process, 1)

        self.assertEqual(WorkerStatus.FAILED.value, runtime.status('alpha'))
        self.assertIn('事件通道', runtime.error('alpha'))
