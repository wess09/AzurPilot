import os
import multiprocessing
import queue
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse


BOOTSTRAPPED_ENV = "AZURPILOT_UV_BOOTSTRAPPED"
BOOTSTRAP_UV_ENV = "AZURPILOT_BOOTSTRAP_UV"
NO_BOOTSTRAP_ENV = "AZURPILOT_NO_UV_BOOTSTRAP"
DEPENDENCY_SYNC_TIMEOUT = 30 * 60


_URL_USERINFO_RE = re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)[^/\s@]+@", re.IGNORECASE)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:access[_-]?token|api[_-]?key|token|password|passwd|secret)=)[^&#\s]+"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|access[_-]?token|api[_-]?key|token|password|passwd|secret)\s*([:=])\s*(?:bearer\s+)?[^\s,;]+"
)


@dataclass
class UvCommandResult:
    """一次 uv 命令的可记录执行结果。"""

    command: list[str]
    output: str


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_path(root: Path = None) -> Path:
    root = root or project_root()
    return root / ".venv"


def venv_bin(root: Path = None) -> Path:
    venv = venv_path(root)
    if os.name == "nt":
        return venv / "Scripts"
    return venv / "bin"


def venv_python(root: Path = None) -> Path:
    executable = "python.exe" if os.name == "nt" else "python"
    return venv_bin(root) / executable


def venv_python_install_dir(root: Path = None) -> Path:
    return venv_path(root) / "python"


def venv_uv(root: Path = None) -> Path:
    executable = "uv.exe" if os.name == "nt" else "uv"
    return venv_bin(root) / executable


def venv_adb(root: Path = None) -> Path:
    executable = "adb.exe" if os.name == "nt" else "adb"
    return venv_bin(root) / executable


def venv_git(root: Path = None) -> Path:
    root = root or project_root()
    if os.name == "nt":
        return venv_path(root) / "Scripts" / "git" / "cmd" / "git.exe"
    return venv_bin(root) / "git"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def in_project_venv(root: Path = None) -> bool:
    root = root or project_root()
    executable = Path(sys.executable).resolve()
    python = venv_python(root)
    try:
        if python.exists() and executable.samefile(python):
            return True
    except OSError:
        pass

    prefix = Path(sys.prefix).resolve()
    return _is_relative_to(prefix, venv_path(root).resolve())


def _read_deploy_value(root: Path, key: str):
    deploy_config = root / "config" / "deploy.yaml"
    try:
        text = deploy_config.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        current_key, value = line.split(":", 1)
        if current_key.strip() != key:
            continue
        value = value.strip().strip("'\"")
        if not value or value.lower() == "null":
            return None
        return value
    return None


def _deploy_bool(root: Path, key: str, default: bool = True) -> bool:
    value = _read_deploy_value(root, key)
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _uv_index_args(root: Path):
    args = []
    mirror = _read_deploy_value(root, "PypiMirror")
    ssl_verify = _deploy_bool(root, "SSLVerify", default=True)

    if mirror:
        args += ["--default-index", mirror]
        hostname = urlparse(mirror).hostname
        if hostname and (mirror.startswith("http:") or not ssl_verify):
            args += ["--allow-insecure-host", hostname]
    elif not ssl_verify:
        args += ["--allow-insecure-host", "pypi.org"]
        args += ["--allow-insecure-host", "files.pythonhosted.org"]
    return args


PathLikeArg = Union[str, os.PathLike]


def _resolve_uv(root: Path, bootstrap_uv: Optional[PathLikeArg] = None) -> Path:
    candidates = []
    if bootstrap_uv:
        candidates.append(Path(bootstrap_uv))
    env_bootstrap = os.environ.get(BOOTSTRAP_UV_ENV)
    if env_bootstrap:
        candidates.append(Path(env_bootstrap))
    candidates.append(venv_uv(root))
    path_uv = shutil.which("uv")
    if path_uv:
        candidates.append(Path(path_uv))

    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
        if candidate and shutil.which(str(candidate)):
            return Path(str(candidate))

    raise RuntimeError(
        "uv is required to prepare AzurPilot's Python environment. "
        "Use the launcher package or install uv first."
    )


def _uv_python_env(root: Path):
    env = os.environ.copy()
    env.pop("UV_PYTHON", None)
    env["UV_PYTHON_INSTALL_DIR"] = str(venv_python_install_dir(root))
    env["UV_CACHE_DIR"] = str(root / ".uv-cache")
    env.setdefault("UV_NO_PROGRESS", "1")
    return env


def _managed_python_executables(root: Path) -> list[Path]:
    install_dir = venv_python_install_dir(root)
    result = []
    for python_home in sorted(install_dir.glob("cpython-*-*"), reverse=True):
        candidates = [
            python_home / "python.exe",
            python_home / "bin" / "python3",
            python_home / "bin" / "python",
        ]
        for candidate in candidates:
            if candidate.exists():
                result.append(candidate)
                break
    return result


def _managed_python_executable(root: Path) -> Optional[Path]:
    """返回一个 managed Python，兼容性由调用方按项目约束校验。"""
    return next(iter(_managed_python_executables(root)), None)


def _project_python_request(root: Path) -> Optional[str]:
    """从项目声明中提取可交给 uv 的 Python 版本请求。"""
    try:
        with (root / "pyproject.toml").open("rb") as file:
            project = tomllib.load(file).get("project", {})
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None

    requirement = str(project.get("requires-python", ""))
    match = re.search(r"(?:>=|~=|==|>)\s*(\d+(?:\.\d+){1,2})", requirement)
    return match.group(1) if match else None


def _python_executable_matches_project(
    root: Path,
    uv: Path,
    executable: Path,
    env=None,
    outputs: Optional[list[str]] = None,
    timeout: float | None = None,
) -> bool:
    """使用 uv 的项目解析规则检查解释器是否满足 requires-python。"""
    command = [
        uv,
        "python",
        "find",
        "--project",
        str(root),
        str(executable),
        "--show-version",
    ]
    try:
        output = _run(command, root, env=env, capture_output=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

    if outputs is not None and output:
        outputs.append(output)
    return "incompatible with the project's python requirement" not in output.lower()


def _venv_python_works(root: Path) -> bool:
    python = venv_python(root)
    if not python.exists():
        return False
    try:
        subprocess.run(
            [
                str(python),
                "-c",
                "import sys; raise SystemExit(0)",
            ],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
    except Exception:
        return False
    return True


def _compatible_managed_python(
    root: Path,
    uv: Path,
    env=None,
    outputs: Optional[list[str]] = None,
    deadline: float | None = None,
) -> Optional[Path]:
    """从所有 uv managed Python 中选择满足项目约束的解释器。"""
    for executable in _managed_python_executables(root):
        if _python_executable_matches_project(
            root,
            uv,
            executable,
            env=env,
            outputs=outputs,
            timeout=_remaining_timeout(deadline, [uv, "python", "find"]),
        ):
            return executable
    return None


def _remove_stale_venv_launcher(root: Path):
    """
    清理 uv venv 在 Windows 上重建可重定位环境时可能撞到的旧启动器。

    uv 使用 --allow-existing 时会复用 .venv，但 Windows 上已有的
    Scripts/python.exe 可能阻止它创建新的可执行文件链接，报 os error 80。
    """
    if os.name != "nt":
        return
    python = venv_python(root)
    if not python.exists():
        return
    try:
        python.unlink()
    except OSError:
        pass


def _run(
    command,
    root: Path,
    env=None,
    capture_output: bool = False,
    timeout: float | None = None,
):
    command = [str(part) for part in command]
    print("+ " + _join_command(command))
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    if not capture_output:
        subprocess.run(command, cwd=str(root), check=True, env=env, timeout=timeout)
        return None

    result = subprocess.run(
        command,
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = result.stdout or ""
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=output,
        )
    return output


def _run_output(command, root: Path, env=None, timeout: float | None = None) -> str:
    command = [str(part) for part in command]
    print("+ " + _join_command(command))
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    result = subprocess.run(
        command,
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=(result.stderr or "") + (result.stdout or ""),
        )
    return (result.stdout or "").strip()


def _join_command(command):
    if hasattr(shlex, "join"):
        return shlex.join(command)
    return " ".join(shlex.quote(part) for part in command)


def _run_and_collect(
    command,
    root: Path,
    env,
    outputs: Optional[list[str]],
    timeout: float | None = None,
):
    output = _run(
        command,
        root,
        env=env,
        capture_output=outputs is not None,
        timeout=timeout,
    )
    if outputs is not None and output:
        outputs.append(output)
    return output


def _remaining_timeout(deadline: float | None, command) -> float | None:
    """返回同步总预算的剩余时间，并在预算耗尽时阻止新的 uv 命令。"""
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, 0)
    return remaining


def _ensure_self_contained_python(
    root: Path,
    uv: Path,
    outputs: Optional[list[str]] = None,
    deadline: float | None = None,
):
    env = _uv_python_env(root)
    managed_python = _compatible_managed_python(root, uv, env=env, outputs=outputs, deadline=deadline)
    managed_python_is_compatible = managed_python is not None
    if (
        _venv_python_works(root)
        and managed_python_is_compatible
        and _python_executable_matches_project(
            root,
            uv,
            venv_python(root),
            env=env,
            outputs=outputs,
            timeout=_remaining_timeout(deadline, [uv, "python", "find"]),
        )
    ):
        return

    if not managed_python_is_compatible:
        managed_python = None
    if managed_python is None:
        command = [
            uv,
            "python",
            "install",
        ]
        python_request = _project_python_request(root)
        if python_request:
            command.append(python_request)
        command += [
            "--install-dir",
            venv_python_install_dir(root),
            "--no-bin",
            "--managed-python",
        ]
        _run_and_collect(
            command,
            root,
            env,
            outputs,
            _remaining_timeout(deadline, command),
        )
        managed_python = _compatible_managed_python(root, uv, env=env, outputs=outputs, deadline=deadline)
        if managed_python is None:
            raise RuntimeError("uv could not install a Python interpreter satisfying requires-python")
    if managed_python is None:
        command = [
            uv,
            "python",
            "find",
            "--managed-python",
        ]
        output = _run_output(
            command,
            root,
            env=env,
            timeout=_remaining_timeout(deadline, command),
        )
        if outputs is not None and output:
            outputs.append(output)
        managed_python = Path(output.strip())

    _remove_stale_venv_launcher(root)
    command = [
        uv,
        "venv",
        "--allow-existing",
        "--relocatable",
        "--python",
        managed_python,
        venv_path(root),
    ] + _uv_index_args(root)
    _run_and_collect(
        command,
        root,
        env,
        outputs,
        _remaining_timeout(deadline, command),
    )


def command_output(exc: BaseException) -> str:
    """提取由 subprocess 保留的合并输出。"""
    output = getattr(exc, "stdout", None)
    if output is None:
        output = getattr(exc, "output", "")
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output or "")


def redact_sensitive_text(value: object) -> str:
    """脱敏命令输出中的 URL 凭据和常见认证字段。"""
    text = str(value or "")
    text = _URL_USERINFO_RE.sub(r"\g<scheme>***@", text)
    text = _SENSITIVE_QUERY_RE.sub(r"\1***", text)
    return _SENSITIVE_ASSIGNMENT_RE.sub(r"\1\2***", text)


def log_command_output(logger, output: str, prefix: str = "[uv]"):
    """将已捕获的子进程输出逐行交给调用方的日志器。"""
    for line in output.splitlines():
        logger.info(f"{prefix} {redact_sensitive_text(line)}")


def sync_project_venv(
    root: Path = None,
    bootstrap_uv: Optional[PathLikeArg] = None,
    capture_output: bool = False,
    timeout: float | None = None,
) -> Optional[UvCommandResult]:
    """在单一总时限内准备解释器、虚拟环境并同步项目依赖。"""
    root = root or project_root()
    if not _deploy_bool(root, "InstallDependencies", default=True):
        output = "InstallDependencies is disabled, skip uv sync"
        print(output)
        if capture_output:
            return UvCommandResult(command=[], output=output)
        return None

    uv = _resolve_uv(root, bootstrap_uv=bootstrap_uv)
    outputs = [] if capture_output else None
    deadline = time.monotonic() + timeout if timeout is not None else None

    try:
        _ensure_self_contained_python(root, uv, outputs=outputs, deadline=deadline)
        command = [
            uv,
            "sync",
            "--project",
            str(root),
            "--python",
            venv_python(root),
        ]
        if (root / "uv.lock").exists():
            command.append("--frozen")
        command += ["--no-dev", "--no-install-project"] + _uv_index_args(root)
        _run_and_collect(
            command,
            root,
            _uv_python_env(root),
            outputs,
            _remaining_timeout(deadline, command),
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        if outputs is not None:
            output = command_output(exc)
            if output:
                outputs.append(output)
            exc.output = "\n".join(outputs)
        raise

    if capture_output:
        return UvCommandResult(command=[str(part) for part in command], output="\n".join(outputs))
    return None


def dependency_sync_service(
    request_queue,
    response_queue,
    root: PathLikeArg = None,
    timeout: float | None = DEPENDENCY_SYNC_TIMEOUT,
):
    """空闲等待 WebUI 更新请求的独立依赖同步服务。"""
    root = Path(root) if root is not None else project_root()
    parent = multiprocessing.parent_process()

    while True:
        try:
            request = request_queue.get(timeout=1)
        except queue.Empty:
            # 启动器强制结束 gui.py 时不会执行 finally，此处避免遗留服务。
            if parent is not None and not parent.is_alive():
                return
            continue
        if request == "shutdown":
            return
        if request != "sync":
            response_queue.put(
                {
                    "success": False,
                    "command": [],
                    "output": "",
                    "error": f"Unknown dependency sync request: {request}",
                }
            )
            continue

        try:
            result = sync_project_venv(
                root=root,
                capture_output=True,
                timeout=timeout,
            )
        except Exception as exc:
            response_queue.put(
                {
                    "success": False,
                    "command": [str(part) for part in (getattr(exc, "cmd", None) or [])],
                    "output": command_output(exc),
                    "error": str(exc),
                }
            )
            continue

        response_queue.put(
            {
                "success": True,
                "command": result.command,
                "output": result.output,
                "error": "",
            }
        )


def ensure_uv_environment():
    if os.environ.get(NO_BOOTSTRAP_ENV):
        return
    if in_project_venv():
        return

    root = project_root()
    try:
        sync_project_venv(root=root)
    except Exception as exc:
        print(f"Failed to prepare uv environment: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    os.environ[BOOTSTRAPPED_ENV] = "1"
    os.execv(str(venv_python(root)), [str(venv_python(root)), *sys.argv])
