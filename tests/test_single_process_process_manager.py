"""单进程宿主接入 ProcessManager 的回归测试。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.webui.process_manager import (
    ProcessManager,
    SINGLE_PROCESS_HOST_REGISTRY_NAME,
    SingleProcessUnsafeError,
)
from module.webui.runtime_host import WorkerSpec, WorkerSpecValidationError
from module.webui.setting import State


class TestSingleProcessProcessManager(unittest.TestCase):
    def setUp(self):
        self.original_manager = State.manager
        self.original_registry = State.process_registry
        self.original_runtime = ProcessManager._single_process_runtime
        self.original_processes = ProcessManager._processes
        self.original_lifecycle_locks = ProcessManager._lifecycle_locks
        State.manager = Mock()
        State.manager.Queue.return_value = Mock()
        State.process_registry = {}
        ProcessManager._single_process_runtime = None
        ProcessManager._processes = {}
        ProcessManager._lifecycle_locks = {}
        self.deploy_config = SimpleNamespace(
            SingleProcessInstances=True,
            UseOcrServer=True,
            OcrClientAddress='127.0.0.1:22268',
        )

    def tearDown(self):
        State.manager = self.original_manager
        State.process_registry = self.original_registry
        ProcessManager._single_process_runtime = self.original_runtime
        ProcessManager._processes = self.original_processes
        ProcessManager._lifecycle_locks = self.original_lifecycle_locks

    @staticmethod
    def make_spec(**overrides):
        values = {
            'config_name': 'alpha',
            'server': 'cn',
            'package': 'com.bilibili.azurlane',
            'emulator_server_name': '127.0.0.1:5555',
            'use_ocr_server': True,
            'ocr_address': '127.0.0.1:22268',
        }
        values.update(overrides)
        return WorkerSpec(**values)

    def test_invalid_spec_is_rejected_before_host_is_created(self):
        manager = ProcessManager('alpha')
        invalid = self.make_spec(use_ocr_server=False, ocr_address=None)

        with (
            patch.object(State, 'deploy_config', self.deploy_config),
            patch.object(manager, '_build_single_process_spec', return_value=invalid),
            patch.object(ProcessManager, '_get_single_process_runtime') as create_host,
        ):
            with self.assertRaises(SingleProcessUnsafeError):
                manager._try_start_single_process_worker('alas', None)

        create_host.assert_not_called()

    def test_auto_config_cannot_fall_back_while_host_has_active_workers(self):
        manager = ProcessManager('alpha')
        active_host = Mock()
        active_host.host_pid.return_value = 12345
        active_host.running_names.return_value = {'beta'}
        ProcessManager._single_process_runtime = active_host

        with (
            patch.object(State, 'deploy_config', self.deploy_config),
            patch.object(
                manager,
                '_build_single_process_spec',
                side_effect=WorkerSpecValidationError('alpha 使用了 auto 设备地址'),
            ),
        ):
            with self.assertRaises(SingleProcessUnsafeError):
                manager._try_start_single_process_worker('alas', None)

        active_host.shutdown.assert_not_called()

    def test_non_alas_task_cannot_fall_back_while_host_has_active_workers(self):
        manager = ProcessManager('alpha')
        active_host = Mock()
        active_host.host_pid.return_value = 12345
        active_host.running_names.return_value = {'beta'}
        ProcessManager._single_process_runtime = active_host

        with patch.object(State, 'deploy_config', self.deploy_config):
            with self.assertRaises(SingleProcessUnsafeError):
                manager._try_start_single_process_worker('FleetScan', None)

        active_host.shutdown.assert_not_called()

    def test_failed_runtime_status_is_visible_as_webui_error(self):
        manager = ProcessManager('alpha')
        runtime = Mock()
        runtime.status.return_value = 'failed'
        ProcessManager._single_process_runtime = runtime
        manager._uses_single_process = True

        self.assertEqual(3, manager.state)

    def test_registry_is_preserved_when_host_unregister_fails(self):
        runtime = Mock()
        runtime.shutdown.return_value = True
        ProcessManager._single_process_runtime = runtime
        State.process_registry[SINGLE_PROCESS_HOST_REGISTRY_NAME] = 12345

        with patch(
            'module.webui.process_manager.unregister_worker', return_value=False
        ):
            self.assertFalse(ProcessManager.shutdown_single_process_runtime())

        self.assertIn(SINGLE_PROCESS_HOST_REGISTRY_NAME, State.process_registry)


if __name__ == '__main__':
    unittest.main()
