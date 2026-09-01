import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy.update_cleanup import (
    ObsoleteFileCleaner,
    complete_environment_cleanup,
    is_environment_cleanup_pending,
)


class TestObsoleteFileCleaner(unittest.TestCase):
    def test_finish_removes_only_previously_managed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / "old.py").write_text("old", encoding="utf-8")
            (root / "user-note.txt").write_text("keep", encoding="utf-8")

            cleaner = ObsoleteFileCleaner(root, "git", MagicMock())
            cleaner.previous_files = {"old.py"}
            with patch.object(cleaner, "_tracked_files", return_value={"new.py"}):
                cleaner.finish()

            self.assertFalse((root / "old.py").exists())
            self.assertTrue((root / "user-note.txt").exists())
            state = json.loads(cleaner.state_file.read_text(encoding="utf-8"))
            self.assertEqual(["new.py"], state["files"])

    def test_finish_refuses_directory_and_outside_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / "old-dir").mkdir()

            cleaner = ObsoleteFileCleaner(root, "git", MagicMock())
            cleaner.previous_files = {"old-dir", "../outside.txt"}
            with patch.object(cleaner, "_tracked_files", return_value=set()):
                cleaner.finish()

            self.assertTrue((root / "old-dir").is_dir())

    def test_prepare_combines_saved_and_current_managed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            cleaner = ObsoleteFileCleaner(root, "git", MagicMock())
            cleaner.state_file.write_text(
                json.dumps({"version": 1, "files": ["previous.py"]}), encoding="utf-8"
            )
            with patch.object(cleaner, "_tracked_files", return_value={"current.py"}):
                cleaner.prepare()

            self.assertEqual({"previous.py", "current.py"}, cleaner.previous_files)

    def test_changed_revision_marks_environment_cleanup_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            cleaner = ObsoleteFileCleaner(root, "git", MagicMock())
            with (
                patch.object(cleaner, "_tracked_files", side_effect=[{"old.py"}, {"new.py"}]),
                patch.object(cleaner, "_revision", side_effect=["old", "new"]),
            ):
                cleaner.prepare()
                cleaner.finish()

            self.assertTrue(is_environment_cleanup_pending(root))
            complete_environment_cleanup(root)
            self.assertFalse(is_environment_cleanup_pending(root))

    def test_git_commands_use_static_argv_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            cleaner = ObsoleteFileCleaner(root, "/path with space/git", MagicMock())

            revision = MagicMock(stdout="abc123\n")
            tracked = MagicMock(stdout=b"a.py\0")
            with patch(
                "deploy.update_cleanup.subprocess.run",
                side_effect=[revision, tracked],
            ) as run:
                self.assertEqual("abc123", cleaner._revision())
                self.assertEqual({"a.py"}, cleaner._tracked_files())

            self.assertEqual(
                ["/path with space/git", "rev-parse", "--verify", "HEAD"],
                run.call_args_list[0].args[0],
            )
            self.assertFalse(run.call_args_list[0].kwargs["shell"])
            self.assertEqual(
                ["/path with space/git", "ls-files", "-z"],
                run.call_args_list[1].args[0],
            )
            self.assertFalse(run.call_args_list[1].kwargs["shell"])


if __name__ == "__main__":
    unittest.main()
