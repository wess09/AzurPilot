"""更新完成后清理已从发布清单移除的文件。"""

import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Optional

from deploy.atomic import atomic_write


class ObsoleteFileCleaner:
    """以 Git 已跟踪文件清单为边界，安全清理旧版本遗留文件。

    不使用 ``git clean``：后者会删除用户自行放入项目目录的文件。清理器只
    处理上一次成功更新时已记录为发布文件、而新版本不再跟踪的普通文件。
    """

    STATE_FILENAME = "azurpilot-managed-files.json"
    REVISION_ARGUMENTS = ("rev-parse", "--verify", "HEAD")
    TRACKED_FILES_ARGUMENTS = ("ls-files", "-z")

    def __init__(self, root, git, logger):
        self.root = Path(root).resolve()
        self.git = str(git)
        self.logger = logger
        self.previous_files = None
        self.previous_state = None
        self.previous_revision = None

    @property
    def state_file(self) -> Path:
        return self.root / ".git" / self.STATE_FILENAME

    @staticmethod
    def _safe_relative_path(value) -> Optional[str]:
        if not isinstance(value, str) or not value:
            return None
        path = PurePosixPath(value)
        if (
            not path.parts
            or path == PurePosixPath(".")
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[0] == ".git"
        ):
            return None
        return path.as_posix()

    def _read_state(self) -> dict:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError) as exc:
            self.logger.warning(f"无法读取旧版文件清单，跳过该清单：{exc}")
            return {}

        return data if isinstance(data, dict) else {}

    def _state_files(self, state: dict) -> set[str]:
        files = state.get("files", [])
        return {path for item in files if (path := self._safe_relative_path(item))}

    def _git_command(self, arguments: tuple[str, ...]) -> list[str]:
        """构造不经过 shell 解析的 Git 命令参数。

        ``self.git`` 仅由本地部署器在创建清理器时传入；子命令及其参数为
        本模块常量。即使 Git 路径包含空格或 shell 元字符，也会作为单个
        argv 元素传递，不能注入额外命令或参数。
        """
        return [self.git, *arguments]

    def _revision(self) -> Optional[str]:
        try:
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            result = subprocess.run(
                self._git_command(self.REVISION_ARGUMENTS),
                cwd=self.root,
                capture_output=True,
                check=True,
                text=True,
                shell=False,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        revision = result.stdout.strip()
        return revision if revision else None

    def _tracked_files(self) -> Optional[set[str]]:
        try:
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            result = subprocess.run(
                self._git_command(self.TRACKED_FILES_ARGUMENTS),
                cwd=self.root,
                capture_output=True,
                check=True,
                shell=False,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            self.logger.warning(f"无法读取 Git 文件清单，跳过废弃文件清理：{exc}")
            return None

        paths = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        return {path for item in paths if (path := self._safe_relative_path(item))}

    def prepare(self):
        """在更新前保存当前受发布管理的文件集合。"""
        tracked = self._tracked_files()
        if tracked is None:
            return
        self.previous_state = self._read_state()
        self.previous_files = self._state_files(self.previous_state) | tracked
        self.previous_revision = self.previous_state.get("revision") or self._revision()

    def _remove_file(self, relative_path: str) -> bool:
        relative_path = self._safe_relative_path(relative_path)
        if relative_path is None:
            self.logger.warning("拒绝清理不安全的废弃路径")
            return False
        path = self.root.joinpath(*PurePosixPath(relative_path).parts)
        try:
            # 父目录若被替换成符号链接，绝不跨出项目目录删除文件。
            if not path.parent.resolve().is_relative_to(self.root):
                self.logger.warning(f"拒绝清理项目目录外的路径：{relative_path}")
                return False
            if path.is_symlink() or path.is_file():
                path.unlink()
                self.logger.info(f"清理废弃文件：{relative_path}")
                return True
            if path.exists():
                self.logger.warning(f"废弃路径是目录，保留以避免误删：{relative_path}")
        except OSError as exc:
            self.logger.warning(f"清理废弃文件失败 {relative_path}: {exc}")
        return False

    def finish(self):
        """在更新成功后删除不再由新版本跟踪的旧发布文件。"""
        if self.previous_files is None:
            return
        current_files = self._tracked_files()
        if current_files is None:
            return

        removed = self.previous_files - current_files
        cleaned = sum(self._remove_file(path) for path in sorted(removed))
        if removed:
            self.logger.info(f"废弃文件清理完成：删除 {cleaned}/{len(removed)} 个文件")

        try:
            current_revision = self._revision()
            environment_cleanup_pending = bool(
                (self.previous_state or {}).get("environment_cleanup_pending", False)
            )
            if current_revision != self.previous_revision:
                environment_cleanup_pending = True
            atomic_write(
                str(self.state_file),
                json.dumps(
                    {
                        "version": 2,
                        "files": sorted(current_files),
                        "revision": current_revision,
                        "environment_cleanup_pending": environment_cleanup_pending,
                    },
                    ensure_ascii=False,
                ),
            )
        except OSError as exc:
            self.logger.warning(f"无法保存发布文件清单，下次更新将重新生成：{exc}")


def _state_file(root) -> Path:
    return Path(root).resolve() / ".git" / ObsoleteFileCleaner.STATE_FILENAME


def is_environment_cleanup_pending(root) -> bool:
    """判断成功更新后的环境维护是否尚未执行。"""
    try:
        data = json.loads(_state_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(data, dict) and bool(data.get("environment_cleanup_pending"))


def complete_environment_cleanup(root):
    """标记更新后的环境维护已完成。"""
    state_file = _state_file(root)
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(data, dict) or not data.get("environment_cleanup_pending"):
        return
    data["environment_cleanup_pending"] = False
    try:
        atomic_write(str(state_file), json.dumps(data, ensure_ascii=False))
    except OSError:
        pass
