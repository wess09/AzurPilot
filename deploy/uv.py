import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


BOOTSTRAPPED_ENV = "AZURPILOT_UV_BOOTSTRAPPED"
NO_BOOTSTRAP_ENV = "AZURPILOT_NO_UV_BOOTSTRAP"
REQUIREMENTS_ENV = "AZURPILOT_REQUIREMENTS"
SYNC_MARKER = ".azurpilot-requirements.sha256"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_path(root: Path = None) -> Path:
    root = root or project_root()
    return root / ".venv"


def venv_python(root: Path = None) -> Path:
    venv = venv_path(root)
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


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


def _platform_requirements_name() -> str:
    if sys.platform.startswith("linux"):
        return "requirements-linux.txt"
    if sys.platform == "darwin":
        return "requirements-macos.txt"
    return "requirements.txt"


def requirements_path(root: Path = None) -> Path:
    root = root or project_root()
    override = os.environ.get(REQUIREMENTS_ENV)
    configured = _read_deploy_value(root, "RequirementsFile")

    if override:
        candidate = Path(override)
    elif (
        sys.platform.startswith("linux")
        and configured in {"./deploy/headless/requirements.txt", "deploy/headless/requirements.txt"}
    ):
        candidate = Path("requirements-linux.txt")
    elif configured:
        candidate = Path(configured)
    else:
        candidate = Path(_platform_requirements_name())

    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.exists():
        return candidate

    fallback = root / _platform_requirements_name()
    if fallback.exists():
        return fallback
    return root / "requirements.txt"


def _requirements_digest(requirements: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"azurpilot-uv-bootstrap-v1\n")
    digest.update(sys.platform.encode("utf-8"))
    digest.update(b"\n")
    digest.update(str(sys.version_info[:2]).encode("utf-8"))
    digest.update(b"\n")
    digest.update(str(requirements.resolve()).encode("utf-8"))
    digest.update(b"\n")
    digest.update(requirements.read_bytes())
    return digest.hexdigest()


def _sync_marker(root: Path) -> Path:
    return venv_path(root) / SYNC_MARKER


def _needs_sync(root: Path, requirements: Path) -> bool:
    python = venv_python(root)
    if not python.exists():
        return True

    marker = _sync_marker(root)
    try:
        previous = marker.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return True
    return previous != _requirements_digest(requirements)


def _uv_index_args(root: Path):
    args = []
    mirror = _read_deploy_value(root, "PypiMirror")
    ssl_verify = _read_deploy_value(root, "SSLVerify")
    ssl_verify = True if ssl_verify is None else str(ssl_verify).lower() == "true"

    if mirror:
        args += ["--default-index", mirror]
        hostname = urlparse(mirror).hostname
        if hostname and (mirror.startswith("http:") or not ssl_verify):
            args += ["--allow-insecure-host", hostname]
    elif not ssl_verify:
        args += ["--allow-insecure-host", "pypi.org"]
        args += ["--allow-insecure-host", "files.pythonhosted.org"]
    return args


def _run(command, root: Path):
    print("+ " + subprocess.list2cmdline([str(part) for part in command]))
    subprocess.run(command, cwd=str(root), check=True)


def sync_project_venv(root: Path = None, requirements: Path = None):
    root = root or project_root()
    requirements = requirements or requirements_path(root)
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError(
            "uv is required to prepare AzurPilot's Python environment. "
            "Install uv first, then run this command again."
        )

    python = venv_python(root)
    if not python.exists():
        _run([uv, "venv", str(venv_path(root)), "--python", sys.executable], root)

    if _needs_sync(root, requirements):
        _run(
            [
                uv,
                "pip",
                "sync",
                "--python",
                str(python),
                str(requirements),
            ]
            + _uv_index_args(root),
            root,
        )
        _sync_marker(root).write_text(_requirements_digest(requirements), encoding="utf-8")


def ensure_uv_environment():
    if os.environ.get(NO_BOOTSTRAP_ENV):
        return
    if in_project_venv():
        return

    root = project_root()
    if os.name == "nt" and not os.environ.get(BOOTSTRAPPED_ENV):
        # Keep the legacy Windows toolkit path working unless the user opts into uv.
        return

    try:
        sync_project_venv(root=root)
    except Exception as exc:
        print(f"Failed to prepare uv environment: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    os.environ[BOOTSTRAPPED_ENV] = "1"
    os.execv(str(venv_python(root)), [str(venv_python(root)), *sys.argv])
