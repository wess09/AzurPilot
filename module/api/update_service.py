"""全局更新接口：只读 Git 快照、分页历史与后台更新操作。"""
import json
import os
import subprocess
import threading
from threading import Thread
from pathlib import Path

from module.api.protocol import ApiError


class UpdateService:
    def __init__(self, root=None, updater=None):
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self._updater = updater
        self.lock = threading.Lock()
        self.operation = None
        self.error = ''

    @property
    def updater(self):
        if self._updater is None:
            from module.runtime.updater import updater
            self._updater = updater
        return self._updater

    @property
    def android(self):
        return os.environ.get('AZURPILOT_ANDROID') == '1'

    def android_manifest(self):
        try:
            return json.loads((self.root / 'BUILD_MANIFEST').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def git(self, *args, optional=False):
        """参数数组避免 shell 解释；错误只返回固定文案。"""
        try:
            result = subprocess.run([self.updater.git, *args], cwd=self.root, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApiError('UPDATE_FAILED', '无法读取 Git 仓库') from exc
        if result.returncode and not optional:
            raise ApiError('UPDATE_FAILED', '无法读取提交记录')
        return result.stdout.strip() if result.returncode == 0 else ''

    def is_ancestor(self, ancestor, descendant):
        """ancestor 是否为 descendant 的祖先；对象缺失或命令失败都算否。"""
        try:
            result = subprocess.run(
                [self.updater.git, 'merge-base', '--is-ancestor', ancestor, descendant],
                cwd=self.root, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def stale_upstream_head(self, local):
        """local 是否停留在历史重写前的旧版上游历史上。

        这种本地分支的 ahead 只是上游重写历史造成的假象，不是用户自己的提交，
        因此可以照常更新。
        """
        from module.runtime.upstream_history import REWRITE_BASES
        return any(self.is_ancestor(local, base) for base in REWRITE_BASES)

    def heads(self):
        local = self.git('rev-parse', '--verify', 'HEAD', optional=True)
        upstream = self.git('rev-parse', '--verify', f'refs/remotes/origin/{self.updater.Branch}', optional=True)
        return local, upstream

    def status(self):
        if self.android:
            manifest = self.android_manifest()
            commit = manifest.get('azurpilot_commit')
            return {'state': 'android', 'localHead': commit, 'upstreamHead': commit,
                    'branch': 'dev', 'ahead': 0, 'behind': 0, 'available': False,
                    'busy': False, 'error': '', 'canApply': False, 'canCancel': False,
                    'shaMismatch': False, 'managedByAndroid': True}
        local, upstream = self.heads()
        ahead = behind = 0
        if local and upstream:
            ahead, behind = map(int, self.git('rev-list', '--left-right', '--count', f'{local}...{upstream}').split())
            # 上游重写历史后，停在旧版上游历史的分支会被算成 ahead，但那不是用户
            # 自己的提交，按"只是落后"处理，让前端可以正常确认更新。
            if ahead and self.stale_upstream_head(local):
                ahead = 0
        # 剩余的 ahead 是真分叉：本地与上游互不包含（例如镜像仓库重写过历史导致
        # SHA 分离，或本地有自己的提交）。更新仍允许，但由前端弹窗向用户确认后果。
        mismatch = bool(local and upstream and ahead and behind)
        from module.runtime.setting import State
        state = self.updater.state
        busy = self.operation is not None or state not in (0, 1, 'failed', 'finish') or getattr(self.updater, '_force_update_checking', False)
        visible_state = {0: 'idle', 1: 'available'}.get(state, state)
        if self.operation == 'fetch' or self.operation == 'apply' and state in (0, 1, 'finish'):
            visible_state = self.operation
        return {'state': visible_state,
                'localHead': local or None, 'upstreamHead': upstream or None,
                'branch': self.updater.Branch, 'ahead': ahead, 'behind': behind,
                'available': behind > 0 or state == 1, 'busy': busy, 'error': self.error,
                'shaMismatch': mismatch,
                'canApply': bool(local and upstream and behind and not busy
                                 and State.restart_event is not None and State.dependency_sync_event is not None),
                'canCancel': state in ('start', 'wait'), 'managedByAndroid': False}

    def commits(self, offset=0, limit=50):
        """合并本地和上游可达历史，不截断总记录数，保留完整提交正文。"""
        if self.android:
            local = self.android_manifest().get('azurpilot_commit')
            return {'entries': [], 'total': 0, 'hasMore': False,
                    'localHead': local, 'upstreamHead': local}
        local, upstream = self.heads()
        refs = list(dict.fromkeys(ref for ref in (local, upstream) if ref))
        entries = []
        if refs:
            raw = self.git('log', '--topo-order', f'--skip={offset}', f'--max-count={limit + 1}',
                           '--format=%H%x00%an%x00%aI%x00%B%x00', *refs, '--')
            fields = raw.split('\x00')
            for index in range(0, len(fields) - 3, 4):
                sha, author, date, message = fields[index:index + 4]
                entries.append({'sha': sha.strip(), 'author': author, 'date': date, 'message': message.strip()})
        total = int(self.git('rev-list', '--count', *refs, '--')) if refs else 0
        return {'entries': entries[:limit], 'total': total, 'hasMore': len(entries) > limit,
                'localHead': local or None, 'upstreamHead': upstream or None}

    def start(self, operation):
        """先保留操作槽，再启动线程，避免重复点击与跨连接重复更新。"""
        if self.android:
            raise ApiError('UPDATE_MANAGED_BY_ANDROID', 'Android 版由宿主在启动时执行整包更新')
        with self.lock:
            status = self.status()
            if status['busy']:
                raise ApiError('UPDATE_BUSY', '更新器正在处理其他操作')
            if operation == 'apply' and not status['canApply']:
                raise ApiError('UPDATE_UNAVAILABLE', '当前版本或服务状态不支持更新')
            self.operation, self.error = operation, ''
            try:
                Thread(target=self._run, args=(operation,), daemon=True).start()
            except RuntimeError as exc:
                self.operation = None
                raise ApiError('UPDATE_FAILED', '无法启动更新任务，请重试') from exc
        return {'accepted': True}

    def _run(self, operation):
        owns_check = False
        try:
            if operation == 'fetch':
                # 和旧更新流程共用互斥锁；保留 checking 状态阻止定时检查插入。
                with self.updater._update_lock:
                    if self.updater.state not in (0, 1, 'failed', 'finish'):
                        raise ApiError('UPDATE_BUSY', '更新器正在处理其他操作')
                    self.updater.state = 'checking'
                    owns_check = True
                    self.updater._fetch_with_retry('origin', self.updater.Branch, max_retry=3, delay=1)
                    local, upstream = self.heads()
                    behind = int(self.git('rev-list', '--count', f'{local}..{upstream}')) if local and upstream else 0
                    self.updater.state = bool(behind)
            else:
                if self.updater.state == 'finish':
                    self.updater.state = 0
                if not self.updater.run_update():
                    raise ApiError('UPDATE_FAILED', '更新失败，请检查服务日志')
        except Exception:
            self.error = '获取更新失败，请检查网络或服务日志' if operation == 'fetch' else '更新失败，请检查服务日志'
            if owns_check:
                self.updater.state = 'failed'
        finally:
            with self.lock:
                self.operation = None

    def cancel(self):
        if self.android:
            raise ApiError('UPDATE_MANAGED_BY_ANDROID', 'Android 版由宿主在启动时执行整包更新')
        if self.updater.state not in ('start', 'wait'):
            raise ApiError('UPDATE_UNAVAILABLE', '当前更新阶段无法取消')
        self.updater.cancel()
        return {'accepted': True}


update_service = UpdateService()
