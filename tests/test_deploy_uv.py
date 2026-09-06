import queue
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from deploy import uv


class TestUvPythonCompatibility(unittest.TestCase):
    def test_project_python_request_reads_requires_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pyproject.toml").write_text(
                '[project]\nrequires-python = ">=3.14.6,<3.15"\n',
                encoding="utf-8",
            )

            self.assertEqual("3.14.6", uv._project_python_request(root))

    def test_compatible_environment_is_reused(self):
        with (
            patch("deploy.uv._venv_python_works", return_value=True),
            patch("deploy.uv._compatible_managed_python", return_value=Path("managed")),
            patch("deploy.uv._python_executable_matches_project", return_value=True),
            patch("deploy.uv._run_and_collect") as run,
        ):
            uv._ensure_self_contained_python(Path("."), Path("uv"))

        run.assert_not_called()

    def test_incompatible_environment_installs_project_python_before_rebuild(self):
        new_python = Path("managed-3.14.6")
        with (
            patch("deploy.uv._venv_python_works", return_value=True),
            patch("deploy.uv._compatible_managed_python", side_effect=[None, new_python]),
            patch("deploy.uv._project_python_request", return_value="3.14.6"),
            patch("deploy.uv._remove_stale_venv_launcher"),
            patch("deploy.uv._run_and_collect") as run,
        ):
            uv._ensure_self_contained_python(Path("."), Path("uv"))

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][0:4], [Path("uv"), "python", "install", "3.14.6"])
        self.assertEqual(commands[1][0:3], [Path("uv"), "venv", "--allow-existing"])


class TestUvCommandOutput(unittest.TestCase):
    def test_run_captures_merged_output(self):
        completed = subprocess.CompletedProcess(["uv", "sync"], 0, "resolved\ninstalled\n")
        with patch("deploy.uv.subprocess.run", return_value=completed):
            output = uv._run(["uv", "sync"], Path("."), capture_output=True)

        self.assertEqual(output, "resolved\ninstalled\n")

    def test_run_forwards_timeout_to_subprocess(self):
        completed = subprocess.CompletedProcess(["uv", "sync"], 0, "")
        with patch("deploy.uv.subprocess.run", return_value=completed) as run:
            uv._run(["uv", "sync"], Path("."), capture_output=True, timeout=12)

        self.assertEqual(12, run.call_args.kwargs["timeout"])

    def test_run_preserves_error_output(self):
        completed = subprocess.CompletedProcess(["uv", "sync"], 2, "error: access denied\n")
        with patch("deploy.uv.subprocess.run", return_value=completed):
            with self.assertRaises(subprocess.CalledProcessError) as context:
                uv._run(["uv", "sync"], Path("."), capture_output=True)

        self.assertEqual(context.exception.returncode, 2)
        self.assertEqual(uv.command_output(context.exception), "error: access denied\n")

    def test_run_output_does_not_mix_stderr_into_python_path(self):
        completed = Mock(returncode=0, stdout="C:/Python/python.exe\n", stderr="warning\n")
        with patch("deploy.uv.subprocess.run", return_value=completed):
            output = uv._run_output(["uv", "python", "find"], Path("."))

        self.assertEqual(output, "C:/Python/python.exe")

    def test_log_command_output_redacts_url_credentials(self):
        logger = Mock()

        uv.log_command_output(
            logger,
            "Using https://user:password@example.test/simple?token=secret\n"
            "Authorization: Bearer private-token\n",
        )

        logged = "\n".join(call.args[0] for call in logger.info.call_args_list)
        self.assertNotIn("user:password", logged)
        self.assertNotIn("secret", logged)
        self.assertNotIn("private-token", logged)
        self.assertIn("https://***@example.test/simple?token=***", logged)

    def test_dependency_service_reports_sync_result(self):
        requests = queue.Queue()
        responses = queue.Queue()
        requests.put("sync")
        requests.put("shutdown")
        result = uv.UvCommandResult(command=["uv", "sync"], output="audited 1 package\n")

        with patch("deploy.uv.sync_project_venv", return_value=result):
            uv.dependency_sync_service(requests, responses, root=Path("."))

        self.assertEqual(
            responses.get_nowait(),
            {
                "success": True,
                "command": ["uv", "sync"],
                "output": "audited 1 package\n",
                "error": "",
            },
        )

    def test_dependency_service_passes_timeout_to_sync(self):
        requests = queue.Queue()
        responses = queue.Queue()
        requests.put("sync")
        requests.put("shutdown")
        result = uv.UvCommandResult(command=["uv", "sync"], output="")

        with patch("deploy.uv.sync_project_venv", return_value=result) as sync:
            uv.dependency_sync_service(
                requests,
                responses,
                root=Path("."),
                timeout=12,
            )

        sync.assert_called_once_with(root=Path("."), capture_output=True, timeout=12)

    def test_dependency_service_reports_sync_timeout(self):
        requests = queue.Queue()
        responses = queue.Queue()
        requests.put("sync")
        requests.put("shutdown")
        timeout = subprocess.TimeoutExpired(["uv", "sync"], 12, output="timed out")

        with patch("deploy.uv.sync_project_venv", side_effect=timeout):
            uv.dependency_sync_service(requests, responses, root=Path("."), timeout=12)

        response = responses.get_nowait()
        self.assertFalse(response["success"])
        self.assertEqual(["uv", "sync"], response["command"])
        self.assertEqual("timed out", response["output"])

    def test_sync_project_venv_uses_one_total_timeout_budget(self):
        root = Path(".")
        with (
            patch("deploy.uv._deploy_bool", return_value=True),
            patch("deploy.uv._resolve_uv", return_value=Path("uv")),
            patch("deploy.uv._ensure_self_contained_python") as ensure_python,
            patch("deploy.uv._run_and_collect") as run_sync,
            patch("deploy.uv.time.monotonic", side_effect=[100, 105]),
        ):
            uv.sync_project_venv(root=root, timeout=10)

        self.assertEqual(110, ensure_python.call_args.kwargs["deadline"])
        self.assertEqual(5, run_sync.call_args.args[4])

    def test_dependency_service_exits_when_parent_process_is_gone(self):
        requests = Mock()
        requests.get.side_effect = queue.Empty
        parent = Mock()
        parent.is_alive.return_value = False

        with patch("deploy.uv.multiprocessing.parent_process", return_value=parent):
            uv.dependency_sync_service(requests, queue.Queue(), root=Path("."))

        parent.is_alive.assert_called_once_with()
