import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter

MIRRORCHYAN_RID = 'AzurPilot'
MIRRORCHYAN_CHANNEL = 'stable'
MIRRORCHYAN_API_BASE = 'https://mirrorchyan.com/api'
MIRRORCHYAN_USER_AGENT = 'AzurPilot'
MIRRORCHYAN_HOME_URL = 'https://mirrorchyan.com?source=azurpilot_settings'

_HEX40_RE = re.compile(r'^[0-9a-f]{40}$')

# 业务错误码映射：不依赖服务端 msg 文案做分支判断，统一按 code 给出清晰提示。
_ERROR_MESSAGES: dict[int, str] = {
    1001: 'Mirror 酱请求参数不正确',
    7001: 'Mirror 酱 CDK 已过期，请更换或续费 CDK',
    7002: 'Mirror 酱 CDK 无效，请检查输入并重新填写',
    7003: 'Mirror 酱 CDK 今日下载次数已达上限，请明日再试',
    7004: 'Mirror 酱 CDK 与当前资源不匹配，请使用适用于 AzurPilot 的 CDK',
    7005: 'Mirror 酱 CDK 已被封禁，请联系 Mirror 酱用户售后',
    8001: 'Mirror 酱当前通道下暂无可用资源',
    8002: 'Mirror 酱系统参数错误',
    8003: 'Mirror 酱架构参数错误',
    8004: 'Mirror 酱更新通道参数错误',
    8009: '流程测试 CDK 不支持实际下载，请使用正式 CDK',
}


class PrintLogger:
    """简易打印日志器，用于独立客户端的回退输出。"""
    info = print
    warning = print
    error = print

    @staticmethod
    def attr(name, text):
        print(f'[{name}] {text}')


def mask_cdk(cdk: Optional[str]) -> str:
    """对 CDK 做脱敏处理，绝不在日志中输出完整密钥。"""
    if not cdk:
        return ''
    text = cdk.strip()
    if len(text) <= 6:
        return '***'
    return f'{text[:2]}***{text[-2:]}'


class MirrorChyanClient:
    """Mirror 酱 Git Pack 源码更新客户端。"""

    logger = PrintLogger()

    def __init__(
        self,
        folder: str,
        cdk: str = '',
        source: str = 'origin',
        branch: str = 'master',
        git: str = 'git',
        rid: str = MIRRORCHYAN_RID,
        channel: str = MIRRORCHYAN_CHANNEL,
        api_base: str = MIRRORCHYAN_API_BASE,
        user_agent: str = MIRRORCHYAN_USER_AGENT,
    ):
        self.folder = folder.replace('\\', '/')
        self.cdk = (cdk or '').strip()
        self.source = source
        self.branch = branch
        self.git = git
        self.rid = rid
        self.channel = channel
        self.api_base = api_base.rstrip('/')
        self.user_agent = user_agent or MIRRORCHYAN_USER_AGENT
        self.last_error: str = ''
        self._session: Optional[requests.Session] = None

    @staticmethod
    def _create_session(max_retries: int = 2) -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        session.mount('http://', HTTPAdapter(max_retries=max_retries))
        session.mount('https://', HTTPAdapter(max_retries=max_retries))
        return session

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._create_session()
        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def git_command(self, *args: str, input_bytes: Optional[bytes] = None, timeout: int = 300) -> bytes:
        """在仓库目录中执行 git 命令，返回原始标准输出字节。"""
        cmd = [self.git, *args]
        result = subprocess.run(
            cmd,
            cwd=self.folder,
            input=input_bytes,
            capture_output=True,
            shell=False,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', 'replace').strip()
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=stderr
            )
        return result.stdout

    def current_commit(self) -> str:
        """获取本地仓库当前 HEAD 的完整 40 位 commit SHA，无有效 HEAD 时返回空字符串。"""
        try:
            raw = self.git_command('rev-parse', '--verify', 'HEAD^{commit}', timeout=10)
            commit = raw.decode('utf-8', 'replace').strip()
            if _HEX40_RE.fullmatch(commit):
                return commit
        except (OSError, subprocess.SubprocessError):
            pass
        return ''

    def commit_version_name(self, commit: str = 'HEAD') -> str:
        """按 GitPack 规范读取提交的 committer UTC 时间并格式化为 YYYYMMDDHHmmss。"""
        raw = self.git_command('cat-file', 'commit', commit, timeout=10).decode('utf-8', 'replace')
        header = raw.split('\n\n', 1)[0]
        for line in header.splitlines():
            if line.startswith('committer '):
                timestamp = int(line.rsplit(' ', 2)[1])
                return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y%m%d%H%M%S')
        raise ValueError(f'Commit {commit} has no committer header')

    def current_version_name(self) -> str:
        """获取本地 HEAD 对应的版本名；无有效 HEAD 时返回空字符串。"""
        head = self.current_commit()
        if not head:
            return ''
        try:
            return self.commit_version_name(head)
        except Exception as e:
            self.logger.warning(f'Failed to compute HEAD version name: {e}')
            return ''

    def request_latest(self, current_version: str = '') -> Optional[dict[str, Any]]:
        """请求 Mirror 酱 /latest 接口，失败时返回 None（绝不当作已是最新）。"""
        self.last_error = ''
        url = f'{self.api_base}/resources/{self.rid}/latest'
        params: dict[str, str] = {
            'channel': self.channel,
            'user_agent': self.user_agent,
        }
        if current_version:
            params['current_version'] = current_version
        if self.cdk:
            params['cdk'] = self.cdk

        self.logger.info(
            f'MirrorChyan check latest: rid={self.rid}, channel={self.channel}, '
            f'current_version={current_version or "<full>"}'
        )
        try:
            resp = self.session.get(url, params=params, timeout=15)
        except Exception as e:
            self.last_error = f'Mirror 酱网络请求失败: {type(e).__name__}'
            self.logger.error(self.last_error)
            return None

        try:
            payload = resp.json()
        except ValueError:
            self.last_error = f'Mirror 酱返回非 JSON 响应 (HTTP {resp.status_code})'
            self.logger.error(self.last_error)
            return None

        if not isinstance(payload, dict):
            self.last_error = f'Mirror 酱返回异常 JSON 结构 (HTTP {resp.status_code})'
            self.logger.error(self.last_error)
            return None

        code = payload.get('code')
        if code != 0:
            msg = payload.get('msg') or ''
            hint = _ERROR_MESSAGES.get(code) if isinstance(code, int) else None
            detail = f'{hint} (code={code})' if hint else f'Mirror 酱接口错误 (code={code}, msg={msg})'
            self.last_error = detail
            self.logger.error(detail)
            return None

        if resp.status_code < 200 or resp.status_code >= 300:
            self.last_error = f'Mirror 酱 HTTP 错误: status={resp.status_code}'
            self.logger.error(self.last_error)
            return None

        data = payload.get('data')
        if not isinstance(data, dict):
            self.logger.error('MirrorChyan response missing data object')
            return None

        update_type = data.get('update_type')
        has_url = bool((data.get('url') or '').strip())
        if (update_type is not None and update_type != 'pack') or (has_url and update_type != 'pack'):
            self.last_error = f'不支持的 Mirror 酱更新类型: {update_type!r}'
            self.logger.error(self.last_error)
            return None

        version_name = data.get('version_name')
        if not isinstance(version_name, str) or not version_name.strip():
            self.logger.error('MirrorChyan response missing valid version_name')
            return None

        return data

    def get_status(self) -> str:
        """检查仓库更新状态：'uptodate'、'behind' 或 'failed'。"""
        current_ver = self.current_version_name()
        data = self.request_latest(current_version=current_ver)
        if data is None:
            return 'failed'

        remote_ver = data['version_name'].strip()
        self.logger.attr('MirrorChyanVersion', f'{current_ver or "<none>"} -> {remote_ver}')
        # pack 仅比较版本名是否相等，以支持分支回退
        if current_ver and remote_ver == current_ver:
            self.logger.info('Already up to date (MirrorChyan)')
            return 'uptodate'
        self.logger.info('New update available on MirrorChyan')
        return 'behind'

    def _download_and_verify_zip(self, url: str, expected_sha256: str, dest_zip: Path) -> bool:
        """流式下载 ZIP 到目标路径并校验 SHA-256（日志绝不输出下载 URL）。"""
        self.logger.info('Downloading MirrorChyan git pack archive...')
        hasher = hashlib.sha256()
        try:
            with self.session.get(url, stream=True, allow_redirects=True, timeout=(15, 300)) as resp:
                if resp.status_code < 200 or resp.status_code >= 300:
                    err_detail = f'Mirror 酱下载失败: HTTP {resp.status_code}'
                    try:
                        err_json = resp.json()
                        if isinstance(err_json, dict) and 'code' in err_json:
                            err_code = err_json.get('code')
                            hint = _ERROR_MESSAGES.get(err_code) if isinstance(err_code, int) else None
                            err_msg = err_json.get('msg') or ''
                            err_detail = (
                                f'{hint} (code={err_code})'
                                if hint
                                else f'Mirror 酱下载错误 (code={err_code}, msg={err_msg})'
                            )
                    except ValueError:
                        pass
                    self.last_error = err_detail
                    self.logger.error(err_detail)
                    return False
                with open(dest_zip, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            hasher.update(chunk)
                            f.write(chunk)
        except Exception as e:
            self.last_error = f'Mirror 酱下载异常: {type(e).__name__}'
            self.logger.error(self.last_error)
            return False

        expected = (expected_sha256 or '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{64}', expected):
            self.last_error = 'Mirror 酱响应缺少有效的 SHA-256 摘要，拒绝导入'
            self.logger.error(self.last_error)
            return False

        actual_sha256 = hasher.hexdigest().lower()
        if actual_sha256 != expected:
            self.last_error = (
                f'Mirror 酱下载包 SHA-256 校验失败: expected={expected[:12]}..., '
                f'actual={actual_sha256[:12]}...'
            )
            self.logger.error(self.last_error)
            return False
        return True

    @staticmethod
    def _safe_extract_zip(zip_path: Path, extract_dir: Path) -> Optional[tuple[Path, dict[str, Any]]]:
        """校验归档路径并解压，返回 (pack_path, meta_dict)。"""
        base_resolved = extract_dir.resolve()
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                target = (extract_dir / info.filename).resolve()
                if base_resolved not in target.parents:
                    raise ValueError(f'Unsafe archive member path: {info.filename}')
            zf.extractall(extract_dir)

        meta_path = extract_dir / 'meta.json'
        if not meta_path.is_file():
            raise ValueError('Archive missing meta.json')
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        if not isinstance(meta, dict):
            raise ValueError('Invalid meta.json format')

        target_commit = meta.get('commit', '')
        base_commit = meta.get('base', '')
        if not isinstance(target_commit, str) or not _HEX40_RE.fullmatch(target_commit):
            raise ValueError('Invalid meta.json commit')
        if not isinstance(base_commit, str) or (base_commit and not _HEX40_RE.fullmatch(base_commit)):
            raise ValueError('Invalid meta.json base')

        pack_files = list(extract_dir.glob('*.pack'))
        if len(pack_files) != 1:
            raise ValueError(f'Expected 1 .pack file in archive, found {len(pack_files)}')

        return pack_files[0], meta

    def _import_pack(self, pack_path: Path) -> None:
        """通过 git index-pack --fsck-objects --stdin 导入对象，不使用 --strict。"""
        pack_bytes = pack_path.read_bytes()
        self.git_command('index-pack', '--fsck-objects', '--stdin', input_bytes=pack_bytes, timeout=300)

    def _verify_target_commit(self, target_commit: str, expected_version: str) -> None:
        """验证目标提交树与文件完整，且 UTC 版本名与 API 一致。"""
        self.git_command('rev-list', '--objects', '--no-walk', target_commit, timeout=60)
        actual_version = self.commit_version_name(target_commit)
        if actual_version != expected_version:
            raise ValueError(
                f'Target commit version mismatch: expected={expected_version}, actual={actual_version}'
            )

    def _maintain_shallow(self, target_commit: str) -> None:
        """当目标提交存在本地缺失的父提交时，将目标提交写入 shallow 边界。"""
        raw = self.git_command('cat-file', 'commit', target_commit, timeout=10).decode('utf-8', 'replace')
        header = raw.split('\n\n', 1)[0]
        parents = [line.split(' ', 1)[1].strip() for line in header.splitlines() if line.startswith('parent ')]

        missing_parent = False
        for parent in parents:
            try:
                self.git_command('cat-file', '-e', f'{parent}^{{commit}}', timeout=10)
            except subprocess.CalledProcessError:
                missing_parent = True
                break

        if not missing_parent:
            return

        shallow_rel = self.git_command('rev-parse', '--git-path', 'shallow', timeout=10).decode('utf-8', 'replace').strip()
        shallow_path = Path(self.folder) / shallow_rel if not os.path.isabs(shallow_rel) else Path(shallow_rel)
        shallow_path.parent.mkdir(parents=True, exist_ok=True)

        existing: list[str] = []
        if shallow_path.is_file():
            existing = [
                line.strip()
                for line in shallow_path.read_text(encoding='utf-8').splitlines()
                if line.strip()
            ]
        if target_commit not in existing:
            existing.append(target_commit)
            tmp_path = shallow_path.with_name(f'{shallow_path.name}.tmp')
            tmp_path.write_text('\n'.join(existing) + '\n', encoding='utf-8')
            os.replace(tmp_path, shallow_path)
            self.logger.info(f'Updated shallow boundary with {target_commit[:8]}')

    def update_refs(self, target_commit: str) -> bool:
        """更新远端跟踪分支引用到目标 commit。"""
        ref = f'refs/remotes/{self.source}/{self.branch}'
        try:
            self.git_command('update-ref', ref, target_commit, timeout=10)
            self.logger.info(f'Updated ref {ref} -> {target_commit[:8]}')
            return True
        except (OSError, subprocess.SubprocessError) as e:
            self.logger.error(f'Failed to update ref {ref}: {e}')
            return False

    def git_reset(self) -> bool:
        """清理锁文件并执行 git reset --hard 到远端分支。"""
        for lock_file in (
            './.git/index.lock',
            './.git/HEAD.lock',
            f'./.git/refs/heads/{self.branch}.lock',
        ):
            full_lock = os.path.join(self.folder, lock_file)
            if os.path.exists(full_lock):
                self.logger.info(f'Lock file {full_lock} exists, removing')
                os.remove(full_lock)
        try:
            self.git_command('reset', '--hard', f'{self.source}/{self.branch}', timeout=120)
            return True
        except (OSError, subprocess.SubprocessError) as e:
            self.logger.error(f'Failed to reset local repository: {e}')
            return False

    def _fetch_pack(self, allow_full_fallback: bool = True) -> Optional[str]:
        """检查并导入目标提交对象，维护 shallow 边界并更新远端跟踪引用。

        Returns:
            成功时返回目标 commit SHA（已是最新时返回当前 HEAD），失败返回 None。
        """
        head_before = self.current_commit()
        current_ver = self.current_version_name() if head_before else ''
        data = self.request_latest(current_version=current_ver)
        if data is None:
            return None

        remote_ver = data['version_name'].strip()
        if current_ver and remote_ver == current_ver and head_before:
            self.logger.info('Already up to date (MirrorChyan)')
            self.update_refs(head_before)
            return head_before

        return self._download_and_apply_pack(data, head_before, allow_full_fallback=allow_full_fallback)

    def _download_and_apply_pack(
        self, data: dict[str, Any], head_before: str, allow_full_fallback: bool
    ) -> Optional[str]:
        url = (data.get('url') or '').strip()
        if not url:
            self.last_error = (
                'Mirror 酱有新版本可用，但未返回下载地址，请填写有效 CDK 后使用高速下载'
            )
            self.logger.warning(self.last_error)
            return None

        expected_sha256 = (data.get('sha256') or '').strip()
        remote_ver = data['version_name'].strip()

        with tempfile.TemporaryDirectory(prefix='mirrorchyan-pack-') as tmp:
            tmp_dir = Path(tmp)
            zip_path = tmp_dir / 'pack.zip'
            extract_dir = tmp_dir / 'extracted'
            extract_dir.mkdir(parents=True, exist_ok=True)

            if not self._download_and_verify_zip(url, expected_sha256, zip_path):
                return None

            try:
                extracted = self._safe_extract_zip(zip_path, extract_dir)
                if extracted is None:
                    return None
                pack_path, meta = extracted
            except Exception as e:
                self.logger.error(f'Invalid MirrorChyan pack archive: {e}')
                return None

            target_commit = meta['commit']
            base_commit = meta['base']

            # 核对增量基准与 HEAD 一致性
            head_now = self.current_commit()
            if base_commit and (base_commit != head_before or base_commit != head_now):
                self.logger.warning(
                    f'MirrorChyan incremental base mismatch (base={base_commit[:8]}, head={head_now[:8]}), '
                    'falling back to full snapshot'
                )
                if allow_full_fallback:
                    full_data = self.request_latest(current_version='')
                    if full_data is not None:
                        return self._download_and_apply_pack(full_data, head_now, allow_full_fallback=False)
                return None

            # 确保仓库已初始化
            if not os.path.isdir(os.path.join(self.folder, '.git')):
                self.git_command('init', timeout=30)

            try:
                self._import_pack(pack_path)
                self._verify_target_commit(target_commit, remote_ver)
                self._maintain_shallow(target_commit)
            except Exception as e:
                self.logger.error(f'Failed to import/verify MirrorChyan pack: {e}')
                if allow_full_fallback and base_commit:
                    self.logger.warning('Retrying MirrorChyan update with full snapshot...')
                    full_data = self.request_latest(current_version='')
                    if full_data is not None:
                        return self._download_and_apply_pack(full_data, self.current_commit(), allow_full_fallback=False)
                return None

            if not self.update_refs(target_commit):
                return None
            return target_commit

    def fetch(self) -> bool:
        """仅拉取并导入对象、更新 refs/remotes/origin/<branch>，不重置工作区。"""
        return self._fetch_pack(allow_full_fallback=True) is not None

    def update(self) -> bool:
        """执行完整源码更新：检查、下载导入对象、更新引用并重置工作区。"""
        target_commit = self._fetch_pack(allow_full_fallback=True)
        if not target_commit:
            return False
        if not self.git_reset():
            return False
        self.logger.info('MirrorChyan update success')
        return True
