"""公共进程终止实现的身份、权限、升级策略及真实子树回归。"""

import multiprocessing
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

import psutil

from module.runtime import process_control as control


def _spawn_tree(connection):
    """只创建休眠子树，通过管道告知测试进程 PID。"""
    script = (
        "import subprocess, sys, time; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(p.pid, flush=True); time.sleep(60)"
    )
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    grandchild_pid = int(child.stdout.readline())
    connection.send([child.pid, grandchild_pid])
    connection.close()
    time.sleep(60)


class TestProcessControl(unittest.TestCase):
    def setUp(self):
        self.record = {"pid": 12345, "created_at": 1.0}

    def make_tree(self):
        processes = {}
        for pid in (12345, 23456, 34567):
            process = Mock(pid=pid)
            process.create_time.return_value = 1.0
            process.status.return_value = psutil.STATUS_RUNNING
            process.kill.side_effect = lambda target=process: setattr(
                target.status, "return_value", psutil.STATUS_ZOMBIE
            )
            processes[pid] = process
        root, first, second = processes.values()
        root.children.return_value = [first, second]

        def lookup(pid):
            if pid not in processes:
                raise psutil.NoSuchProcess(pid)
            return processes[pid]

        return processes, lookup

    def test_zombie_is_exited_without_reaping(self):
        process = Mock()
        process.create_time.return_value = 1.0
        process.status.return_value = psutil.STATUS_ZOMBIE
        with patch("psutil.Process", return_value=process), patch("psutil.wait_procs") as wait:
            self.assertIsNone(control.process_matches(self.record))
        process.wait.assert_not_called()
        wait.assert_not_called()

    def test_identity_permission_denied_is_not_mistaken_for_missing_proc(self):
        with patch("psutil.Process", side_effect=psutil.AccessDenied(12345)), \
                patch("os.path.exists", return_value=False):
            with self.assertRaises(RuntimeError):
                control.process_matches(self.record)

    def test_missing_psutil_blocks_record_termination(self):
        with patch.dict(sys.modules, {"psutil": None}), \
                patch("module.runtime.process_control.os.kill") as kill:
            with self.assertRaises(RuntimeError):
                control.process_matches(self.record)
            self.assertFalse(control.stop_process_tree(record=self.record))
        kill.assert_not_called()

    def test_permission_denied_blocks_tree_enumeration_without_blind_kill(self):
        processes, lookup = self.make_tree()
        root = processes[12345]
        root.children.side_effect = psutil.AccessDenied(12345)
        with patch("psutil.Process", side_effect=lookup), \
                patch("module.runtime.process_control.os.kill") as kill:
            self.assertFalse(control.stop_process_tree(record=self.record))
        root.kill.assert_not_called()
        kill.assert_not_called()

    def test_disappearing_child_does_not_skip_root_or_other_children(self):
        processes, lookup = self.make_tree()
        root, first, second = processes.values()

        def disappear():
            processes.pop(second.pid)
            raise psutil.NoSuchProcess(second.pid)

        second.kill.side_effect = disappear
        with patch("psutil.Process", side_effect=lookup):
            self.assertTrue(control.stop_process_tree(record=self.record, kill_timeout=0))
        first.kill.assert_called_once_with()
        second.kill.assert_called_once_with()
        root.kill.assert_called_once_with()

    def test_child_kill_denied_keeps_root_for_retry(self):
        processes, lookup = self.make_tree()
        root, first, second = processes.values()
        second.kill.side_effect = psutil.AccessDenied(second.pid)
        with patch("psutil.Process", side_effect=lookup):
            self.assertFalse(control.stop_process_tree(record=self.record, kill_timeout=0))
        first.kill.assert_called_once_with()
        root.kill.assert_not_called()
        self.assertEqual(second.status(), psutil.STATUS_RUNNING)

    def test_child_exit_timeout_keeps_root_and_does_not_claim_tree_stopped(self):
        processes, lookup = self.make_tree()
        root, first, second = processes.values()
        second.kill.side_effect = None
        with patch("psutil.Process", side_effect=lookup):
            self.assertFalse(control.stop_process_tree(record=self.record, kill_timeout=0))
        first.kill.assert_called_once_with()
        root.kill.assert_not_called()

    def test_reused_root_is_rejected_before_any_signal(self):
        processes, lookup = self.make_tree()
        root = processes[12345]
        root.create_time.return_value = 2.0
        with patch("psutil.Process", side_effect=lookup):
            self.assertFalse(control.stop_process_tree(record=self.record))
        for process in processes.values():
            process.kill.assert_not_called()

    def test_root_identity_is_rechecked_after_stopping_children(self):
        processes, lookup = self.make_tree()
        root, first, second = processes.values()

        def reuse_root():
            second.status.return_value = psutil.STATUS_ZOMBIE
            root.create_time.return_value = 2.0

        second.kill.side_effect = reuse_root
        with patch("psutil.Process", side_effect=lookup):
            self.assertFalse(control.stop_process_tree(record=self.record, kill_timeout=0))
        first.kill.assert_called_once_with()
        root.kill.assert_not_called()

    def test_local_stop_escalates_only_after_terminate_timeout(self):
        process = Mock(pid=12345)
        process.is_alive.return_value = True
        process.kill.side_effect = lambda: setattr(process.is_alive, "return_value", False)
        self.assertTrue(control.stop_process(process, timeout=5, kill_timeout=3))
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual([call.kwargs["timeout"] for call in process.join.call_args_list], [5, 3])

    def test_local_stop_uses_join_without_psutil_wait(self):
        process = Mock(pid=12345)
        process.is_alive.return_value = True
        process.terminate.side_effect = lambda: setattr(process.is_alive, "return_value", False)
        with patch("psutil.wait_procs") as wait:
            self.assertTrue(control.stop_process(process))
        process.kill.assert_not_called()
        process.join.assert_any_call(timeout=5)
        wait.assert_not_called()

    def test_local_permission_denied_does_not_report_success(self):
        process = Mock(pid=12345)
        process.is_alive.return_value = True
        process.terminate.side_effect = PermissionError("拒绝终止")
        process.kill.side_effect = PermissionError("拒绝强制终止")
        self.assertFalse(control.stop_process(process, timeout=0, kill_timeout=0))

    def test_unstarted_and_closed_local_handles_are_idempotent(self):
        process = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(0,))
        self.assertTrue(control.stop_process(process))
        self.assertTrue(control.stop_process_tree(process))
        process.start()
        process.join(timeout=10)
        self.assertFalse(process.is_alive())
        process.close()
        self.assertTrue(control.stop_process(process))
        self.assertTrue(control.stop_process_tree(process))

    def test_windows_taskkill_is_verified_and_retains_tree_flags(self):
        processes, lookup = self.make_tree()
        root = processes[12345]

        def taskkill(*_, **__):
            root.status.return_value = psutil.STATUS_ZOMBIE
            return Mock(returncode=0)

        with patch("psutil.Process", side_effect=lookup), \
                patch("module.runtime.process_control.os.name", "nt"), \
                patch("module.runtime.process_control.subprocess.run", side_effect=taskkill) as run:
            self.assertTrue(control.stop_process_tree(record=self.record, kill_timeout=0))
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "12345", "/T", "/F"])
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_windows_taskkill_failure_cannot_hide_surviving_root(self):
        processes, lookup = self.make_tree()
        with patch("psutil.Process", side_effect=lookup), \
                patch("module.runtime.process_control.os.name", "nt"), \
                patch("module.runtime.process_control.subprocess.run", return_value=Mock(returncode=1)):
            self.assertFalse(control.stop_process_tree(record=self.record, kill_timeout=0))

    def test_registered_real_worker_remains_joinable_by_multiprocessing(self):
        process = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(60,))
        process.start()
        record = {"pid": process.pid, "created_at": psutil.Process(process.pid).create_time()}
        try:
            self.assertTrue(control.stop_process_tree(record=record))
            process.join(timeout=3)
            self.assertFalse(process.is_alive())
            self.assertIsNotNone(process.exitcode)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=3)

    def test_local_real_process_tree_stops_children_and_grandchildren(self):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_spawn_tree, args=(sender,))
        process.start()
        records = []
        try:
            self.assertTrue(receiver.poll(10), "休眠子树未就绪")
            records = [{"pid": pid, "created_at": psutil.Process(pid).create_time()}
                       for pid in receiver.recv()]
            self.assertTrue(control.stop_process_tree(process, timeout=1))
            self.assertFalse(process.is_alive())
            self.assertIsNotNone(process.exitcode)
            for record in records:
                self.assertIsNone(control.process_matches(record))
        finally:
            for record in records:
                control.stop_process_tree(record=record, kill_timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=3)
            receiver.close()
            sender.close()
