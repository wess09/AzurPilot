"""全局更新接口：只读 Git 快照、分页历史与后台更新操作。"""
import json
import os
import subprocess
import threading
from pathlib import Path
from threading import Thread

from module.api.protocol import ApiError


class UpdateService:
    """全局更新管理服务。

    提供 Git 版本状态检测、提交历史分页、拉取最新代码及后台热更新执行控制。

    Attributes:
        root: 代码仓库根目录路径。
        lock: 互斥锁，防止并发执行更新操作。
        operation: 当前进行中的操作名称（'fetch' 或 'apply'）。
        error: 记录的错误描述信息。
    """

    def __init__(self, root=None, updater=None):
        """初始化更新管理服务。

        Args:
            root: 可选的代码根目录路径。
            updater: 可选的底层 Updater 实例。
        """
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self._updater = updater
        self.lock = threading.Lock()
        self.operation = None
        self.error = ''

    @property
    def updater(self):
        """获取底层更新器单例。

        Returns:
            Updater: 底层更新器实例。
        """
        if self._updater is None:
            from module.runtime.updater import updater
            self._updater = updater
        return self._updater

    @property
    def android(self) -> bool:
        """检查当前是否处于 Android 宿主环境中。

        Returns:
            bool: 若环境变量 AZURPILOT_ANDROID 为 '1' 返回 True，否则返回 False。
        """
        return os.environ.get('AZURPILOT_ANDROID') == '1'

    def android_manifest(self) -> dict:
        """读取 Android 构建清单文件。

        Returns:
            dict: 构建清单元数据字典；若读取失败返回空字典。
        """
        try:
            return json.loads((self.root / 'BUILD_MANIFEST').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def git(self, *args: str, optional: bool = False) -> str:
        """执行 Git 命令并返回标准输出。

        参数数组避免 shell 解释；执行出错时转换为受控的 API 异常。

        Args:
            *args: Git 子命令及其参数列表。
            optional: 若为 True，则忽略非零退出码并返回空字符串。

        Returns:
            str: 去除首尾空白的标准输出字符串。

        Raises:
            ApiError: Git 进程超时或非零退出时抛出 UPDATE_FAILED。
        """
        try:
            result = subprocess.run([self.updater.git, *args], cwd=self.root, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApiError('UPDATE_FAILED', '无法读取 Git 仓库') from exc
        if result.returncode and not optional:
            raise ApiError('UPDATE_FAILED', '无法读取提交记录')
        return result.stdout.strip() if result.returncode == 0 else ''

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """判定 ancestor 是否为 descendant 的祖先提交。

        对象缺失或命令失败均判定为否。

        Args:
            ancestor: 祖先提交哈希或引用。
            descendant: 后代提交哈希或引用。

        Returns:
            bool: 是其祖先返回 True，否则返回 False。
        """
        try:
            result = subprocess.run(
                [self.updater.git, 'merge-base', '--is-ancestor', ancestor, descendant],
                cwd=self.root, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def stale_upstream_head(self, local: str) -> bool:
        """判定本地提交是否停留在历史重写前的旧版上游分支上。

        这种本地分支的 ahead 只是上游重写历史造成的假象，不是用户自己的提交，
        因此可以照常更新。

        Args:
            local: 本地提交哈希。

        Returns:
            bool: 属于重写前的陈旧上游历史返回 True，否则返回 False。
        """
        from module.runtime.upstream_history import REWRITE_BASES
        return any(self.is_ancestor(local, base) for base in REWRITE_BASES)

    def heads(self) -> tuple[str, str]:
        """获取本地分支与追踪的远程上游分支的最新提交哈希。

        Returns:
            tuple[str, str]: (本地提交哈希, 远程提交哈希)。
        """
        local = self.git('rev-parse', '--verify', 'HEAD', optional=True)
        upstream = self.git('rev-parse', '--verify', f'refs/remotes/origin/{self.updater.Branch}', optional=True)
        return local, upstream

    def status(self) -> dict:
        """查询当前更新状态元数据。

        Returns:
            dict: 包含当前分支、本地/上游提交哈希、超前/落后提交数、是否可更新以及
                是否正忙等状态字典。
        """
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
        is_mirrorchyan = bool(getattr(self.updater, 'MirrorChyan', False))
        # MirrorChyan Git Pack 跳版本会写入 shallow 截断历史，导致 local...upstream 互不可达而被算成 ahead+behind，
        # 这属于正常浅历史现象，不应误报为本地分叉弹窗。
        mismatch = False if is_mirrorchyan else bool(local and upstream and ahead and behind)
        has_update = bool(behind > 0 or (is_mirrorchyan and local and upstream and local != upstream))
        from module.runtime.setting import State
        state = self.updater.state
        busy = self.operation is not None or state not in (0, 1, 'failed', 'finish') or getattr(self.updater, '_force_update_checking', False)
        visible_state = {0: 'idle', 1: 'available'}.get(state, state)
        if self.operation == 'fetch' or self.operation == 'apply' and state in (0, 1, 'finish'):
            visible_state = self.operation
        available = has_update or state == 1
        return {'state': visible_state,
                'localHead': local or None, 'upstreamHead': upstream or None,
                'branch': self.updater.Branch, 'ahead': ahead, 'behind': behind,
                'available': available, 'busy': busy, 'error': self.error,
                'shaMismatch': mismatch,
                'mirrorChyanEnabled': is_mirrorchyan,
                'mirrorChyanConfigured': bool(getattr(self.updater, 'MirrorChyanCdk', None)),
                'canApply': bool(available and not busy
                                 and State.restart_event is not None and State.dependency_sync_event is not None),
                'canCancel': state in ('start', 'wait'), 'managedByAndroid': False}

    def commits(self, offset: int = 0, limit: int = 50) -> dict:
        """分页获取本地与上游可达的提交历史记录。

        合并本地和上游可达历史，不截断总记录数，保留完整提交正文。

        Args:
            offset: 分页偏移量。
            limit: 每页获取的提交数量上限。

        Returns:
            dict: 包含提交条目列表、历史总数、是否还有更多以及两端 HEAD 哈希的字典。
        """
        if self.android:
            local = self.android_manifest().get('azurpilot_commit')
            return {'entries': [], 'total': 0, 'hasMore': False,
                    'localHead': local, 'upstreamHead': local}
        local, upstream = self.heads()
        if getattr(self.updater, 'MirrorChyan', False):
            return {'entries': [], 'total': 0, 'hasMore': False,
                    'localHead': local or None, 'upstreamHead': upstream or None}
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

    def start(self, operation: str) -> dict:
        """启动后台更新操作（fetch 或 apply）。

        先保留操作槽位，再启动工作线程，避免重复点击与跨连接重复触发。

        Args:
            operation: 操作类型，'fetch' 表示检查获取，'apply' 表示执行更新。

        Returns:
            dict: 包含 accepted: True 的确认字典。

        Raises:
            ApiError: Android 环境不支持更新、更新器正忙 (UPDATE_BUSY)、
                当前状态不可更新 (UPDATE_UNAVAILABLE) 或无法启动线程 (UPDATE_FAILED)。
        """
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

    def _run(self, operation: str):
        """更新工作线程执行体。

        Args:
            operation: 操作名称。
        """
        owns_check = False
        try:
            if operation == 'fetch':
                # 和旧更新流程共用互斥锁；保留 checking 状态阻止定时检查插入。
                with self.updater._update_lock:
                    if self.updater.state not in (0, 1, 'failed', 'finish'):
                        raise ApiError('UPDATE_BUSY', '更新器正在处理其他操作')
                    self.updater.state = 'checking'
                    owns_check = True
                    self.updater.fetch_update('origin', self.updater.Branch, max_retry=3, delay=1)
                    local, upstream = self.heads()
                    if getattr(self.updater, 'MirrorChyan', False) and local and upstream:
                        self.updater.state = local != upstream
                    else:
                        behind = int(self.git('rev-list', '--count', f'{local}..{upstream}')) if local and upstream else 0
                        self.updater.state = bool(behind)
            else:
                if self.updater.state == 'finish':
                    self.updater.state = 0
                if not self.updater.run_update():
                    raise ApiError('UPDATE_FAILED', '更新失败，请检查服务日志')
        except Exception:
            mc_err = getattr(self.updater, '_mirrorchyan_error', '')
            if mc_err:
                self.error = mc_err
            else:
                self.error = '获取更新失败，请检查网络或服务日志' if operation == 'fetch' else '更新失败，请检查服务日志'
            if owns_check:
                self.updater.state = 'failed'
        finally:
            with self.lock:
                self.operation = None

    def cancel(self) -> dict:
        """取消当前正在等待的更新操作。

        Returns:
            dict: 包含 accepted: True 的确认字典。

        Raises:
            ApiError: Android 环境不支持更新或当前阶段无法取消 (UPDATE_UNAVAILABLE)。
        """
        if self.android:
            raise ApiError('UPDATE_MANAGED_BY_ANDROID', 'Android 版由宿主在启动时执行整包更新')
        if self.updater.state not in ('start', 'wait'):
            raise ApiError('UPDATE_UNAVAILABLE', '当前更新阶段无法取消')
        self.updater.cancel()
        return {'accepted': True}


update_service = UpdateService()
