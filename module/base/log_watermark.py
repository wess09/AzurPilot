"""后台生成日志来源标记，不参与任务执行或错误恢复。"""

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from deploy.utils import get_deploy_template, poor_yaml_read
from module.logger import logger


_last_watermark = '[来源水印] 源: 未知 | 分支: 未知 | 提交: 未知 | 本地修改: 未知'


def _safe_source(value):
    """只展示仓库地址，去掉凭据、查询参数和本地目录。"""
    value = str(value or '').strip()
    if '://' in value:
        try:
            parts = urlsplit(value)
            if parts.scheme not in ('https', 'http', 'ssh', 'git') or not parts.hostname:
                return '本地仓库' if parts.scheme == 'file' else '未知'
            value = urlunsplit((parts.scheme, parts.netloc.rsplit('@', 1)[-1], parts.path, '', ''))
        except ValueError:
            return '未知'
    elif re.match(r'^(?:[^/@:\\]+@)?[^/:\\]+:.+', value) and not re.match(r'^[A-Za-z]:', value):
        value = value.rsplit('@', 1)[-1].split('?', 1)[0].split('#', 1)[0]
    elif value not in ('global', 'cn', 'cnb', 'gitcode'):
        return '本地仓库' if value else '未知'
    return ' '.join(value.split())[:256]


def collect_source_watermark(root=None):
    """读取本机版本信息；只读 Git，全部命令共享三秒预算，不访问网络。"""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    settings = {}
    for file in (root / get_deploy_template(), root / 'config/deploy.yaml'):
        try:
            settings.update(poor_yaml_read(file))
        except (OSError, ValueError):
            continue

    configured_source = _safe_source(settings.get('Repository'))
    source = f'{configured_source}（配置）' if configured_source != '未知' else '未知'
    branch = commit = modified = '未知'
    if (root / '.git').exists():
        executable = root / str(settings.get('GitExecutable') or '')
        git = str(executable) if executable.is_file() else 'git'
        deadline = time.monotonic() + 3

        def read_git(*args):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                result = subprocess.run(
                    [git, '--no-optional-locks', *args], cwd=root,
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    timeout=remaining,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
                return result.stdout.strip() if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None

        actual_source = read_git('remote', 'get-url', 'origin')
        if actual_source:
            source = _safe_source(actual_source)
        actual_branch = read_git('rev-parse', '--abbrev-ref', 'HEAD')
        if actual_branch:
            branch = '分离 HEAD' if actual_branch == 'HEAD' else ' '.join(actual_branch.split())[:128]
        actual_commit = read_git('rev-parse', '--verify', 'HEAD')
        if actual_commit and re.fullmatch(r'[0-9a-fA-F]{40,64}', actual_commit):
            commit = actual_commit[:12]
        # 安装器、用户配置等未跟踪文件不代表已修改版本内的代码。
        status = read_git('status', '--porcelain', '--untracked-files=no')
        if status is not None:
            modified = '有' if status else '无'
    else:
        # Android 整包没有 .git；只采用宿主清单里明确记录的提交，不推断修改状态。
        try:
            manifest = json.loads((root / 'BUILD_MANIFEST').read_text(encoding='utf-8'))
            actual_commit = manifest.get('azurpilot_commit')
            if isinstance(actual_commit, str) and re.fullmatch(r'[0-9a-fA-F]{40,64}', actual_commit):
                commit = actual_commit[:12]
        except (OSError, ValueError, AttributeError):
            pass

    return f'[来源水印] 源: {source} | 分支: {branch} | 提交: {commit} | 本地修改: {modified}'


def _append_watermark(log_file, watermark):
    """仅追加已有现场，不覆盖原日志，也不重新创建已清理的现场。"""
    with open(log_file, 'r+', encoding='utf-8') as file:
        file.seek(0, os.SEEK_END)
        file.write(f'\n{watermark}\n')


def _write_source_watermark(log_file=None):
    """可选水印失败时保留原始日志，不让后台异常干扰运行。"""
    global _last_watermark
    try:
        watermark = collect_source_watermark()
        _last_watermark = watermark
        logger.info(watermark)
        if log_file is not None:
            _append_watermark(log_file, watermark)
    except Exception:
        logger.debug('[来源水印] 读取或追加失败，已跳过')


def start_log_watermark(log_file=None):
    """先追加缓存，再后台刷新；调用方不等待 Git。"""
    if log_file is not None:
        try:
            # 退出时 daemon 可能被终止，先留下明确标注的快照，再后台刷新。
            _append_watermark(log_file, f'{_last_watermark}（最近快照，等待后台刷新）')
        except Exception:
            logger.debug('[来源水印] 无法追加最近快照，已跳过')
    threading.Thread(
        target=_write_source_watermark, args=(log_file,),
        name='log-source-watermark', daemon=True,
    ).start()
