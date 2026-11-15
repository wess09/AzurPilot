"""构建本地 React 静态资源，取代旧桌面应用更新步骤。"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from deploy.atomic import atomic_write
from deploy.config_transaction import config_transaction

_NPM_REGISTRIES = ('https://registry.npmmirror.com', 'https://registry.npmjs.org')
_INSTALL_TIMEOUT = 600
_BUILD_TIMEOUT = 180

# 安卓运行包永不本地编译前端：源码变更后由宿主从其 CI 发布渠道拉取按提交发布的
# 预构建 dist（frontend-<commit>.tar.xz + .sha256）。基址由宿主注入（含镜像前缀）。
ANDROID_DIST_BASE_ENV = 'AZURPILOT_ANDROID_DIST_BASE'
_ANDROID_UA = 'Mozilla/5.0 (X11; Linux x86_64) AzurPilot-Android-Frontend'


def android_dist_base():
    """读取宿主注入的预构建 dist 下载基址。

    Returns:
        str: 去尾斜杠的基址；未注入返回空串。
    """
    return os.environ.get(ANDROID_DIST_BASE_ENV, '').rstrip('/')


def android_manifest(root=None):
    """读取根目录 BUILD_MANIFEST（构建期由宿主生成、热更后由更新服务改写）。

    Args:
        root (str | Path, optional): 项目根目录。

    Returns:
        dict: 清单元数据；读取失败返回空字典。
    """
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    try:
        return json.loads((root / 'BUILD_MANIFEST').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def android_dist_ready(commit, root=None):
    """探测宿主渠道是否已发布该提交的预构建 dist（更新前置条件）。

    只做 HEAD 探测不下载；探测失败（断网/未发布/未注入基址）一律返回 False，
    让更新检查把该提交视作"暂不可更新"，从源头规避源码与 dist 失配启动崩溃。

    Args:
        commit (str): 目标上游提交完整哈希。
        root (str | Path, optional): 项目根目录，仅用于缺参时回退读当前提交。

    Returns:
        bool: dist 资产存在返回 True。
    """
    if not commit:
        commit = android_manifest(root).get('azurpilot_commit')
    base = android_dist_base()
    if not base or not commit:
        return False
    url = f'{base}/frontend-{commit}.tar.xz.sha256'
    try:
        request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': _ANDROID_UA})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except OSError:
        return False


def _android_download(url, target, timeout=300):
    """下载文件到 target 并返回字节数；网络错误统一转 RuntimeError。"""
    request = urllib.request.Request(url, headers={'User-Agent': _ANDROID_UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(target, 'wb') as f:
            shutil.copyfileobj(response, f)
    except OSError as exc:
        raise RuntimeError(f'下载失败: {url} ({exc})') from exc
    return target.stat().st_size


def _android_fetch_dist(directory, root):
    """拉取与当前源码提交匹配的预构建 dist 并校验指纹。

    Args:
        directory (Path): 前端工程目录（frontend/）。
        root (Path): 项目根目录（读 BUILD_MANIFEST 定提交）。

    Raises:
        RuntimeError: 未注入基址、清单元数据缺失、下载/校验失败或指纹失配。
    """
    from module.logger import logger

    commit = android_manifest(root).get('azurpilot_commit')
    base = android_dist_base()
    if not base:
        raise RuntimeError(f'安卓环境缺少 {ANDROID_DIST_BASE_ENV}，无法获取预构建前端')
    if not commit:
        raise RuntimeError('安卓环境缺少 BUILD_MANIFEST 提交信息，无法获取预构建前端')

    stem = f'frontend-{commit}'
    tar_path = directory / f'.{stem}.tar.xz.tmp'
    try:
        size = _android_download(f'{base}/{stem}.tar.xz', tar_path)
        logger.info(f'预构建前端下载完成: {size} bytes')
        request = urllib.request.Request(
            f'{base}/{stem}.tar.xz.sha256', headers={'User-Agent': _ANDROID_UA})
        with urllib.request.urlopen(request, timeout=30) as response:
            expected = response.read().decode('ascii', 'replace').strip().split()[0]
        digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
        if not expected or digest != expected.lower():
            raise RuntimeError(f'预构建前端校验失败: 期望 {expected[:12]}…, 实际 {digest[:12]}…')

        dist = directory / 'dist'
        if dist.exists():
            shutil.rmtree(dist)
        with tarfile.open(tar_path, 'r:xz') as tar:
            tar.extractall(directory, filter='data')
        marker = dist / '.source-fingerprint'
        if not (dist / 'index.html').is_file() or not marker.is_file():
            raise RuntimeError('预构建前端包缺少 dist/index.html 或指纹标记')
        if marker.read_text().strip() != source_fingerprint(directory):
            raise RuntimeError('预构建前端与当前源码指纹不匹配，包可能与该提交不符')
        logger.info(f'预构建前端就绪: {commit[:12]}')
    finally:
        if tar_path.exists():
            tar_path.unlink()


def npm_command():
    """Windows 直接使用 Node 执行 npm，避免将批处理当作可执行文件。

    Returns:
        list[str]: 用于执行 npm 命令的可执行文件与参数列表。

    Raises:
        RuntimeError: 当缺少 Node.js 或未找到 npm-cli.js 时抛出。
    """
    npm = shutil.which('npm')
    if not npm:
        raise RuntimeError('前端需要构建，请安装 Node.js 22.12+，在 frontend 中运行 npm install 和 npm run build')
    if os.name != 'nt':
        return [npm]
    node = shutil.which('node')
    candidates = [Path(npm).resolve().parent / 'node_modules/npm/bin/npm-cli.js']
    if node:
        candidates.append(Path(node).resolve().parent / 'node_modules/npm/bin/npm-cli.js')
    for cli in candidates:
        if node and cli.is_file():
            return [node, str(cli)]
    raise RuntimeError('未找到 npm-cli.js，请修复 Node.js 安装后重新启动')


def source_fingerprint(directory):
    """使用内容摘要识别源码变化，避免 Git 检出时间导致重复构建。

    Args:
        directory (Path): 前端工程目录路径。

    Returns:
        str: 前端源文件的 SHA-256 校验和。
    """
    paths = [directory / 'package.json', directory / 'package-lock.json', directory / 'index.html',
             directory / 'vite.config.ts', directory / 'tsconfig.json']
    paths.extend(sorted((directory / 'src').rglob('*')))
    paths.extend(sorted((directory / 'public').rglob('*')))
    return _fingerprint(directory, paths)


def _fingerprint(directory, paths):
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _log_process_error(exc, stage='npm'):
    """记录子进程执行失败的输出，对文件占用等常见错误给予友好提示。"""
    from module.logger import logger
    detail = (getattr(exc, 'stderr', None) or getattr(exc, 'stdout', None) or '').strip()
    if detail:
        lines = [line for line in detail.splitlines() if line.strip()]
        summary = '\n'.join(lines[-15:]) if len(lines) > 15 else detail
        logger.warning(f'{stage} 错误输出:\n{summary}')
    retcode = getattr(exc, 'returncode', 0)
    if 'EPERM' in detail or 'EBUSY' in detail or retcode in (4294963248, -4048):
        logger.error('node_modules 中的文件被其他进程占用（如正在运行的 WebUI、Vite 或编辑器）。请先关闭占用进程后重新启动。')


def _install_dependencies(command, directory, flags, method, registries=_NPM_REGISTRIES):
    """按顺序尝试安装源，优先使用 npm 的下载缓存。"""
    from module.logger import logger

    args = [method, '--no-audit', '--no-fund', '--prefer-offline', '--include=dev', '--include=optional']
    if method == 'install':
        args.extend(('--package-lock', '--no-save'))
    for index, registry in enumerate(registries):
        logger.info(f'安装前端依赖（npm {method}）: {registry}')
        try:
            subprocess.run(
                [*command, *args, f'--registry={registry}'],
                cwd=directory, check=True, timeout=_INSTALL_TIMEOUT, capture_output=True, text=True,
                encoding='utf-8', errors='replace', **flags,
            )
            return
        except subprocess.CalledProcessError as exc:
            _log_process_error(exc, stage=f'npm {method}')
            if index == len(registries) - 1:
                raise
            logger.warning(f'镜像源安装失败，切换至 npm 官方源重试: {exc}')
        except subprocess.TimeoutExpired:
            if index == len(registries) - 1:
                raise
            logger.warning('镜像源安装超时，切换至 npm 官方源重试')


def _read_marker(path):
    try:
        return path.read_text(encoding='utf-8').strip()
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def _validate_dependency_lock(directory):
    """安装时要求仓库锁文件和直接依赖声明一致。"""
    try:
        manifest = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
        lock = json.loads((directory / 'package-lock.json').read_text(encoding='utf-8'))
        locked = lock['packages']['']
        if not isinstance(manifest, dict) or not isinstance(locked, dict):
            raise ValueError('依赖声明须为 JSON 对象')
    except (FileNotFoundError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('前端依赖锁文件缺失或无法读取，请在 frontend 中运行 npm install 生成锁文件') from exc
    for key in ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'):
        if manifest.get(key, {}) != locked.get(key, {}):
            raise RuntimeError('前端依赖声明与锁文件不一致，请在 frontend 中运行 npm install 同步锁文件')


def _build_tools_present(directory):
    modules = directory / 'node_modules'
    suffix = '.cmd' if os.name == 'nt' else ''
    tools = (('tsc', 'typescript/bin/tsc'), ('vite', 'vite/bin/vite.js'))
    return all((modules / f'.bin/{tool}{suffix}').is_file() and (modules / entry).is_file()
               for tool, entry in tools)


def _installed_fingerprint(directory, paths):
    return f'{sys.platform}/{platform.machine()}:{_fingerprint(directory, paths)}'


def _ensure_dependencies(command, directory, flags):
    from module.logger import logger

    installed = directory / 'node_modules/.package-lock.json'
    marker = directory / 'node_modules/.azurpilot-dependency-fingerprint'
    inputs = [directory / name for name in ('package.json', 'package-lock.json', '.npmrc')]
    fingerprint = _fingerprint(directory, inputs)
    installed_before = installed.is_file()
    cached = installed_before and _read_marker(marker) == _installed_fingerprint(directory, [*inputs, installed])
    if cached and _build_tools_present(directory):
        logger.info('复用已安装的前端依赖')
        return

    _validate_dependency_lock(directory)
    marker.unlink(missing_ok=True)
    started = time.perf_counter()
    if cached:
        logger.warning('已缓存的前端构建工具缺失，使用 npm ci 干净重装')
        _install_dependencies(command, directory, flags, 'ci')
    else:
        try:
            _install_dependencies(command, directory, flags, 'install')
        except subprocess.CalledProcessError:
            if not installed_before:
                raise
            logger.warning('现有前端依赖增量安装失败，使用官方源执行 npm ci 修复')
            _install_dependencies(command, directory, flags, 'ci', _NPM_REGISTRIES[-1:])
        else:
            if not _build_tools_present(directory):
                logger.warning('npm install 完成后仍缺少前端构建工具，使用 npm ci 干净重装')
                _install_dependencies(command, directory, flags, 'ci')

    if not _build_tools_present(directory):
        raise RuntimeError('前端依赖安装后仍缺少 TypeScript 或 Vite，请检查 npm 安装配置')
    if _fingerprint(directory, inputs) != fingerprint:
        raise RuntimeError('安装期间前端依赖配置发生变化，请重试')
    if installed.is_file():
        atomic_write(str(marker), _installed_fingerprint(directory, [*inputs, installed]) + '\n')
    logger.info(f'前端依赖安装完成，耗时 {time.perf_counter() - started:.2f} 秒')


def ensure_frontend(root=None):
    """缺少或过期时构建前端；已有对应版本的产物不要求安装 Node。

    Args:
        root (str | Path, optional): 项目根目录，默认为当前文件上两级目录。

    Raises:
        RuntimeError: 在 Android 环境缺少预构建产物时抛出。
        subprocess.CalledProcessError: 前端构建命令执行失败时抛出。
        subprocess.TimeoutExpired: 官方源安装或编译超时时抛出。
    """
    from module.logger import logger
    directory = (Path(root) if root else Path(__file__).resolve().parents[1]) / 'frontend'
    marker = directory / 'dist/.source-fingerprint'
    fingerprint = source_fingerprint(directory)
    index = directory / 'dist/index.html'
    if index.is_file() and _read_marker(marker) == fingerprint:
        return
    if os.environ.get('AZURPILOT_ANDROID') == '1':
        # 安卓永不本地编译：宿主按提交发布预构建 dist，缺失即报错，
        # 更新服务在应用前会先探测 dist 可用性，正常流程不会走到这里。
        _android_fetch_dist(directory, Path(root) if root else Path(__file__).resolve().parents[1])
        return
    # 安装与打包都修改共享目录，等待另一个启动器完成后再检查产物。
    with config_transaction(directory.parent / 'cache/frontend-build', timeout=3 * _INSTALL_TIMEOUT + _BUILD_TIMEOUT):
        fingerprint = source_fingerprint(directory)
        if index.is_file() and _read_marker(marker) == fingerprint:
            return
        command = npm_command()
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
        _ensure_dependencies(command, directory, flags)
        logger.info('正在构建 React 前端资源')
        started = time.perf_counter()
        try:
            subprocess.run(
                [*command, 'run', 'build'],
                cwd=directory, check=True, timeout=_BUILD_TIMEOUT, capture_output=True, text=True,
                encoding='utf-8', errors='replace', **flags,
            )
        except subprocess.CalledProcessError as exc:
            _log_process_error(exc, stage='前端构建')
            raise
        atomic_write(str(marker), fingerprint + '\n')
        logger.info(f'React 前端构建完成，耗时 {time.perf_counter() - started:.2f} 秒')


if __name__ == '__main__':
    ensure_frontend()
